"""Formato y envio de mensajes a Telegram."""
from datetime import date

import requests

from surf.alert import Ventana
from surf.geo import clasificar_viento, rumbo_a_texto
from surf.score import DiaEvaluado
from surf.spots import Spot

URL_TELEGRAM = "https://api.telegram.org/bot{token}/sendMessage"
TIMEOUT_S = 20

_MESES = ["", "enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
          "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
_DIAS = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]

_ORDEN_CONCORDANCIA = {"alta": 2, "media": 1, "baja": 0}

# Nombre corto y legible de cada modelo de Open-Meteo. Lo que llega en
# DiaEvaluado.modelos son pares "modelo_de_olas+modelo_de_viento".
_NOMBRES_MODELOS = {
    "gwam": "GWAM",
    "meteofrance_wave": "MFWAM",
    "ncep_gfswave025": "GFS-Wave",
    "best_match": "Open-Meteo",
    "gfs_seamless": "GFS",
    "icon_seamless": "ICON",
    "ecmwf_ifs025": "ECMWF",
}


def _nombre_legible(par: str) -> str:
    return "/".join(_NOMBRES_MODELOS.get(p, p) for p in par.split("+"))


def _listar(nombres: list[str]) -> str:
    if len(nombres) == 1:
        return nombres[0]
    return f"{', '.join(nombres[:-1])} y {nombres[-1]}"


def etiqueta_concordancia(nivel: str, modelos: tuple[str, ...],
                          de_acuerdo: int) -> str:
    """Arma la linea de concordancia con los modelos que REALMENTE respondieron.

    Antes esta linea era un texto fijo que decia "GFS, ICON y ECMWF coinciden"
    aunque el pronostico se hubiera calculado con dos modelos: si Open-Meteo
    dejaba de servir uno en un spot, el usuario leia que los tres coincidian
    sobre algo que uno de ellos nunca vio.
    """
    base = "Concordancia entre modelos"
    total = len(modelos)
    if not total:
        # Dia armado por una via que no registra modelos (p.ej. evaluar_dia
        # de un solo modelo). No se inventan nombres ni cantidades.
        if nivel == "alta":
            return f"{base}: alta (los modelos coinciden) ✓"
        return f"{base}: {nivel}"

    nombres = [_nombre_legible(m) for m in modelos]
    if nivel == "alta":
        return f"{base}: alta ({de_acuerdo} de {total} coinciden: {_listar(nombres)}) ✓"

    cola = ""
    if total < 3:
        cola = (f" — solo {total} de 3 fuentes disponibles en este spot"
                if total > 1 else " — una sola fuente disponible en este spot")
    # En media y baja NO coincidieron todos, asi que los nombres se listan como
    # "consultados" y no como "coinciden": decir lo contrario seria repetir el
    # error que este arreglo corrige.
    return (f"{base}: {nivel} ({de_acuerdo} de {total} coinciden — "
            f"consultados: {_listar(nombres)}){cola}")


class ErrorEnvio(Exception):
    """No se pudo entregar el mensaje."""


def _fecha_corta(d: date) -> str:
    return f"{_DIAS[d.weekday()]} {d.day}"


def _linea_dia(dia: DiaEvaluado, spot: Spot) -> str:
    if dia.resumen is None:
        return f"{_fecha_corta(dia.fecha):<7} (sin datos de pronóstico)"
    r = dia.resumen
    clase = clasificar_viento(r.get("viento_direccion", 0), spot.costa_mira)
    return (
        f"{_fecha_corta(dia.fecha):<7} "
        f"{r.get('altura', 0):.1f}m @ {r.get('periodo', 0):.0f}s "
        f"del {rumbo_a_texto(r.get('direccion', 0))}  ·  "
        f"viento {rumbo_a_texto(r.get('viento_direccion', 0))} "
        f"{r.get('viento_kmh', 0):.0f}km/h {clase}  ·  "
        f"{dia.score:.0f}/100"
    )


def formatear_alerta(ventana: Ventana, spot: Spot) -> str:
    mejor = max(ventana.dias, key=lambda d: d.score)
    cant = len(ventana.dias)

    if ventana.desde.month == ventana.hasta.month:
        rango_fechas = f"{_fecha_corta(ventana.desde)} a {_fecha_corta(ventana.hasta)} de {_MESES[ventana.hasta.month]}"
    else:
        rango_fechas = f"{_fecha_corta(ventana.desde)} de {_MESES[ventana.desde.month]} a {_fecha_corta(ventana.hasta)} de {_MESES[ventana.hasta.month]}"

    plural = "día" if cant == 1 else "días"
    partes = [
        f"🔥 BUEN SWELL — {spot.nombre}",
        f"{rango_fechas} ({cant} {plural})",
        "",
    ]
    partes += [_linea_dia(d, spot) for d in ventana.dias]
    partes.append("")

    if mejor.bloque:
        partes.append(
            f"Mejor ventana: {_fecha_corta(mejor.fecha).lower()} "
            f"{mejor.bloque[0].hour}-{mejor.bloque[1].hour} hs"
        )
    partes.append("Confirmado en 2 corridas consecutivas ✓")

    # El dia con peor concordancia manda: es el dato conservador. Se toman de
    # ese mismo dia los modelos y el conteo, para que la linea describa la
    # situacion real y no una mezcla de dias distintos.
    peor_dia = min(ventana.dias,
                   key=lambda d: (_ORDEN_CONCORDANCIA[d.concordancia],
                                  len(d.modelos), d.modelos_de_acuerdo))
    partes.append(etiqueta_concordancia(peor_dia.concordancia, peor_dia.modelos,
                                        peor_dia.modelos_de_acuerdo))

    if spot.confianza == "baja":
        partes.append("⚠️ perfil poco validado — chequear en surf-forecast antes de viajar")

    partes.append(f"→ {spot.url_surfforecast}")
    return "\n".join(partes)


def formatear_digest(cercanos: list[tuple[DiaEvaluado, Spot]],
                     hubo_alertas: int, fecha: date) -> str:
    partes = [f"📋 Resumen semanal — {fecha.day} de {_MESES[fecha.month]}", ""]

    if hubo_alertas:
        partes.append(f"Alertas enviadas esta semana: {hubo_alertas}")
    else:
        partes.append("Alertas enviadas esta semana: 0")
    partes.append("")

    if not cercanos:
        partes.append("Sin ventanas cerca del umbral en los próximos días.")
    else:
        partes.append("Quedó cerca pero no alcanzó:")
        for dia, spot in cercanos:
            partes.append(f"· {spot.nombre} — {_fecha_corta(dia.fecha)}: {dia.motivo_principal}")

    partes.append("")
    partes.append("(Este resumen llega todos los domingos. Si algún domingo no llega, "
                  "el sistema está caído.)")
    return "\n".join(partes)


def enviar(mensaje: str, token: str, chat_id: str, sesion=None) -> None:
    """Manda un mensaje. Lanza ErrorEnvio si no se pudo entregar."""
    cliente = sesion or requests
    error_msg = None
    try:
        r = cliente.post(
            URL_TELEGRAM.format(token=token),
            json={"chat_id": chat_id, "text": mensaje, "disable_web_page_preview": True},
            timeout=TIMEOUT_S,
        )
        r.raise_for_status()
    except requests.exceptions.HTTPError as e:
        status = getattr(getattr(e, 'response', None), 'status_code', '?')
        reason = getattr(getattr(e, 'response', None), 'reason', '?')
        error_msg = f"no se pudo enviar a Telegram ({status} {reason})"
    except requests.exceptions.Timeout:
        error_msg = "no se pudo enviar a Telegram: timeout"
    except requests.exceptions.RequestException:
        error_msg = "no se pudo enviar a Telegram: error de conexión"
    except Exception:  # noqa: BLE001
        error_msg = "no se pudo enviar a Telegram: error inesperado"

    if error_msg is not None:
        raise ErrorEnvio(error_msg)
