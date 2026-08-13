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

from surf.alert import (Ventana, decidir_alertas, detectar_ventanas,
                        estado_vacio, registrar_corrida)
from surf.fetch import ErrorDatos, obtener_horas
from surf.notify import ErrorEnvio, enviar, formatear_alerta, formatear_digest
from surf.score import DiaEvaluado, evaluar_dia
from surf.spots import Spot, cargar_spots

RUTA_SPOTS = Path("spots.yaml")
RUTA_ESTADO = Path("state.json")
DIA_DEL_DIGEST = 6  # domingo


def _cerca_del_umbral(dia: DiaEvaluado) -> bool:
    """Fallo por un solo criterio y no por falta de olas."""
    if dia.es_bueno or not dia.motivo_principal:
        return False
    return any(k in dia.motivo_principal for k in ("periodo", "onshore", "cross", "direccion"))


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
    """Corre el ciclo completo. Devuelve el estado nuevo y los mensajes enviados."""
    todos_los_dias: list[DiaEvaluado] = []
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
            d = evaluar_dia(horas, spot, fecha)
            todos_los_dias.append(d)
            if _cerca_del_umbral(d):
                cercanos.append((d, spot))

    if exitosos == 0:
        raise RuntimeError("ningun spot devolvio datos; no se escribe estado")

    ventanas = detectar_ventanas(todos_los_dias)
    a_alertar = decidir_alertas(ventanas, estado, hoy)

    enviados: list[str] = []
    entregadas: list[Ventana] = []
    for v in sorted(a_alertar, key=lambda x: -x.score):
        m = formatear_alerta(v, por_id[v.spot_id])
        if _enviar_seguro(m, enviar_fn, v.spot_id):
            entregadas.append(v)
        enviados.append(m)

    # Solo lo que efectivamente se entrego queda marcado como alertado: una
    # ventana cuyo envio fallo (Telegram caido, token invalido, rate limit)
    # no debe perderse para siempre, tiene que reintentarse al dia siguiente.
    estado_nuevo = registrar_corrida(ventanas, entregadas, estado, hoy)

    if hoy.weekday() == DIA_DEL_DIGEST:
        m = formatear_digest(cercanos[:10], hubo_alertas=len(a_alertar), fecha=hoy)
        _enviar_seguro(m, enviar_fn, "digest")
        enviados.append(m)

    print(f"[OK] {exitosos}/{len(spots)} spots, {len(ventanas)} ventanas, "
          f"{len(a_alertar)} alertas, {len(enviados)} mensajes")
    return estado_nuevo, enviados


def main() -> int:
    token = os.environ.get("TELEGRAM_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("[ERROR] faltan TELEGRAM_TOKEN o TELEGRAM_CHAT_ID", file=sys.stderr)
        return 2

    spots = cargar_spots(RUTA_SPOTS)
    estado = json.loads(RUTA_ESTADO.read_text()) if RUTA_ESTADO.exists() else estado_vacio()

    try:
        estado_nuevo, _ = correr(
            spots, date.today(), obtener_horas,
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
