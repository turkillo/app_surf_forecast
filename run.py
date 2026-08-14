"""Entrypoint diario del sistema de alertas.

`correr` recibe sus dependencias por parametro para poder testearlo sin red.
`main` arma las dependencias reales y traduce el resultado a exit code.
"""
import json
import os
import sys
from datetime import date
from pathlib import Path
from typing import Callable

from surf.alert import (CLAVE_OBSERVADAS_PREAVISO, CLAVE_PREAVISADAS,
                        REGIMEN_ALERTA, REGIMEN_PREAVISO, Ventana,
                        decidir_alertas, detectar_ventanas, estado_vacio,
                        regimen, registrar_corrida)
from surf.consenso import MINIMO_FUENTES_OLAS_PREAVISO, evaluar_dia_multimodelo
from surf.fetch import ErrorDatos, obtener_horas_multimodelo
from surf.notify import (ErrorEnvio, enviar, formatear_alerta, formatear_digest,
                         formatear_preaviso)
from surf.score import DiaEvaluado
from surf.spots import Spot, cargar_spots

RUTA_SPOTS = Path("spots.yaml")
RUTA_ESTADO = Path("state.json")
DIA_DEL_DIGEST = 6  # domingo


# Los motivos de rechazo son texto de cara al usuario y van acentuados, asi
# que buscar solo la forma sin acento no matcheaba nunca y el digest dominical
# no podia listar una sola ventana cerca del umbral. Se aceptan las dos formas
# para que un cambio de redaccion no vuelva a dejarlo ciego.
_MOTIVOS_CERCA = ("período", "periodo", "onshore", "cross", "dirección", "direccion")


def _cerca_del_umbral(dia: DiaEvaluado) -> bool:
    """Fallo por un solo criterio y no por falta de olas."""
    if dia.es_bueno or not dia.motivo_principal:
        return False
    return any(k in dia.motivo_principal for k in _MOTIVOS_CERCA)


def _enviar_seguro(mensaje: str, enviar_fn: Callable[[str], None], spot_id: str) -> bool:
    """Envuelve un envio individual. Un fallo de Telegram no debe abortar la
    corrida ni propagar un traceback a los logs del job (ver Tarea 9: fuga
    de token via excepcion sin capturar). Devuelve si el envio se entrego,
    para que quien llama solo registre como alertado lo que realmente salio."""
    try:
        enviar_fn(mensaje)
        return True
    except ErrorEnvio as e:
        print(f"[WARN] no se pudo enviar el mensaje de {spot_id}: {e}", file=sys.stderr)
        return False


def correr(spots: list[Spot], hoy: date,
           traer: Callable, enviar_fn: Callable[[str], None],
           estado: dict) -> tuple[dict, list[str]]:
    """Corre el ciclo completo. Devuelve el estado nuevo y los mensajes enviados.

    Cada dia del pronostico se evalua con el regimen que le corresponde segun
    su distancia a `hoy`: gate completo hasta el dia 6, solo swell del 7 al 10.
    Los dos regimenes despues corren la misma maquinaria de ventanas,
    persistencia y anti-repeticion, cada uno sobre su propia seccion del
    estado.
    """
    dias_alerta: list[DiaEvaluado] = []
    dias_preaviso: list[DiaEvaluado] = []
    cercanos: list[tuple[DiaEvaluado, Spot]] = []
    por_id = {s.id: s for s in spots}
    exitosos = 0

    for spot in spots:
        try:
            por_dia = traer(spot)
        except ErrorDatos as e:
            print(f"[WARN] {spot.id}: {e}", file=sys.stderr)
            continue
        exitosos += 1
        for fecha, horas in por_dia.items():
            cual = regimen(fecha, hoy)
            if cual == REGIMEN_ALERTA:
                d = evaluar_dia_multimodelo(horas, spot, fecha)
                dias_alerta.append(d)
                if _cerca_del_umbral(d):
                    cercanos.append((d, spot))
            elif cual == REGIMEN_PREAVISO:
                dias_preaviso.append(evaluar_dia_multimodelo(
                    horas, spot, fecha, exigir_viento=False,
                    minimo_fuentes=MINIMO_FUENTES_OLAS_PREAVISO))
            # Mas alla del horizonte no se evalua nada: a esa distancia queda
            # una sola fuente de olas y en 4 spots ninguna.

    if exitosos == 0:
        raise RuntimeError("ningun spot devolvio datos; no se escribe estado")

    enviados: list[str] = []

    ventanas = detectar_ventanas(dias_alerta)
    a_alertar = decidir_alertas(ventanas, estado, hoy)
    entregadas: list[Ventana] = []
    for v in sorted(a_alertar, key=lambda x: -x.score):
        m = formatear_alerta(v, por_id[v.spot_id])
        if _enviar_seguro(m, enviar_fn, v.spot_id):
            entregadas.append(v)
        enviados.append(m)

    # Los pre-avisos van despues de las alertas: si el mismo dia sale un
    # mensaje de cada tipo, primero se lee lo que ya esta confirmado.
    ventanas_pre = detectar_ventanas(dias_preaviso)
    a_preavisar = decidir_alertas(
        ventanas_pre, estado, hoy,
        clave_observadas=CLAVE_OBSERVADAS_PREAVISO,
        clave_enviadas=CLAVE_PREAVISADAS,
        reenviar_si_crece=False,
    )
    entregados_pre: list[Ventana] = []
    for v in sorted(a_preavisar, key=lambda x: -x.score):
        m = formatear_preaviso(v, por_id[v.spot_id], hoy)
        if _enviar_seguro(m, enviar_fn, v.spot_id):
            entregados_pre.append(v)
        enviados.append(m)

    # Solo lo que efectivamente se entrego queda marcado como avisado: una
    # ventana cuyo envio fallo (Telegram caido, token invalido, rate limit)
    # no debe perderse para siempre, tiene que reintentarse al dia siguiente.
    # Las dos pasadas se encadenan y cada una toca solo su propia seccion.
    estado_nuevo = registrar_corrida(ventanas, entregadas, estado, hoy)
    estado_nuevo = registrar_corrida(
        ventanas_pre, entregados_pre, estado_nuevo, hoy,
        clave_observadas=CLAVE_OBSERVADAS_PREAVISO,
        clave_enviadas=CLAVE_PREAVISADAS,
    )

    if hoy.weekday() == DIA_DEL_DIGEST:
        m = formatear_digest(cercanos[:10], hubo_alertas=len(a_alertar), fecha=hoy)
        _enviar_seguro(m, enviar_fn, "digest")
        enviados.append(m)

    print(f"[OK] {exitosos}/{len(spots)} spots, {len(ventanas)} ventanas, "
          f"{len(a_alertar)} alertas, {len(ventanas_pre)} ventanas a 7-10 días, "
          f"{len(a_preavisar)} pre-avisos, {len(enviados)} mensajes")
    return estado_nuevo, enviados


def _mensaje_de_prueba(spots: list[Spot]) -> str:
    """Arma un mensaje que confirma la conexion y muestra que el detector vive.

    No toca el estado ni cuenta como corrida: sirve para verificar el bot
    sin esperar a que haya un swell.
    """
    dias: list[DiaEvaluado] = []
    fallaron = 0
    for spot in spots:
        try:
            por_dia = obtener_horas_multimodelo(spot)
        except ErrorDatos:
            fallaron += 1
            continue
        for fecha, horas in por_dia.items():
            dias.append(evaluar_dia_multimodelo(horas, spot, fecha))

    ventanas = detectar_ventanas(dias)
    partes = [
        "✅ Prueba del sistema de alertas de swell",
        "",
        "Conexión con Telegram: OK",
        f"Spots consultados: {len(spots) - fallaron} de {len(spots)}",
        f"Ventanas detectadas ahora mismo: {len(ventanas)}",
    ]
    if ventanas:
        partes.append("")
        por_id = {s.id: s for s in spots}
        for v in sorted(ventanas, key=lambda x: -x.score)[:6]:
            partes.append(
                f"· {por_id[v.spot_id].nombre} — {v.desde.day}/{v.desde.month} "
                f"al {v.hasta.day}/{v.hasta.month} ({v.score:.0f}/100)"
            )
    partes += [
        "",
        "Esto es solo una prueba: no modifica el estado ni cuenta como corrida.",
        "Las alertas reales llegan cuando una ventana se confirma en dos días seguidos.",
    ]
    return "\n".join(partes)


def main() -> int:
    token = os.environ.get("TELEGRAM_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("[ERROR] faltan TELEGRAM_TOKEN o TELEGRAM_CHAT_ID", file=sys.stderr)
        return 2

    spots = cargar_spots(RUTA_SPOTS)

    if os.environ.get("MENSAJE_PRUEBA", "").lower() == "true":
        try:
            enviar(_mensaje_de_prueba(spots), token, chat_id)
        except ErrorEnvio as e:
            print(f"[ERROR] no se pudo enviar el mensaje de prueba: {e}", file=sys.stderr)
            return 1
        print("[OK] mensaje de prueba enviado; el estado no se modifico")
        return 0

    estado = json.loads(RUTA_ESTADO.read_text()) if RUTA_ESTADO.exists() else estado_vacio()

    try:
        estado_nuevo, _ = correr(
            spots, date.today(), obtener_horas_multimodelo,
            lambda m: enviar(m, token, chat_id), estado,
        )
    except RuntimeError as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        try:
            enviar(f"⚠️ El sistema de alertas falló hoy: {e}", token, chat_id)
        except ErrorEnvio:
            pass
        return 1

    # Solo se escribe estado si la corrida completa termino bien.
    RUTA_ESTADO.write_text(json.dumps(estado_nuevo, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
