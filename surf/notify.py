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
_DIAS = ["Lun", "Mar", "Mie", "Jue", "Vie", "Sab", "Dom"]


class ErrorEnvio(Exception):
    """No se pudo entregar el mensaje."""


def _fecha_corta(d: date) -> str:
    return f"{_DIAS[d.weekday()]} {d.day}"


def _linea_dia(dia: DiaEvaluado, spot: Spot) -> str:
    r = dia.resumen or {}
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

    partes = [
        f"🔥 BUEN SWELL — {spot.nombre}",
        f"{_fecha_corta(ventana.desde)} a {_fecha_corta(ventana.hasta)} "
        f"de {_MESES[ventana.hasta.month]} ({cant} dias)",
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
        partes.append("Sin ventanas cerca del umbral en los proximos dias.")
    else:
        partes.append("Quedo cerca pero no alcanzo:")
        for dia, spot in cercanos:
            partes.append(f"· {spot.nombre} — {_fecha_corta(dia.fecha)}: {dia.motivo_principal}")

    partes.append("")
    partes.append("(Este resumen llega todos los domingos. Si algun domingo no llega, "
                  "el sistema esta caido.)")
    return "\n".join(partes)


def enviar(mensaje: str, token: str, chat_id: str, sesion=None) -> None:
    """Manda un mensaje. Lanza ErrorEnvio si no se pudo entregar."""
    cliente = sesion or requests
    try:
        r = cliente.post(
            URL_TELEGRAM.format(token=token),
            json={"chat_id": chat_id, "text": mensaje, "disable_web_page_preview": True},
            timeout=TIMEOUT_S,
        )
        r.raise_for_status()
    except Exception as e:  # noqa: BLE001
        raise ErrorEnvio(f"no se pudo enviar a Telegram: {e}") from e
