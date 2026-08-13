"""Obtencion de datos de Open-Meteo.

Dos endpoints: Marine API para el swell, Forecast API para viento y
amanecer/ocaso. Ambos en el tier gratuito, sin API key.

`timezone=auto` hace que Open-Meteo devuelva todo en la hora local del spot,
que es lo que importa para decidir si una hora es de luz.
"""
import time
from datetime import date, datetime

import requests

from surf.score import Hora
from surf.spots import Spot

URL_MARINE = "https://marine-api.open-meteo.com/v1/marine"
URL_CLIMA = "https://api.open-meteo.com/v1/forecast"

REINTENTOS = 3
ESPERA_BASE_S = 2
TIMEOUT_S = 30

_CAMPOS_MARINE = ["swell_wave_height", "swell_wave_period", "swell_wave_direction"]
_CAMPOS_CLIMA = ["wind_speed_10m", "wind_direction_10m"]


class ErrorDatos(Exception):
    """Los datos recibidos no sirven para evaluar."""


def _pedir(url: str, params: dict, sesion=None) -> dict:
    """GET con reintentos y backoff exponencial."""
    cliente = sesion or requests
    ultimo: Exception | None = None
    for intento in range(REINTENTOS):
        try:
            r = cliente.get(url, params=params, timeout=TIMEOUT_S)
            r.raise_for_status()
            datos = r.json()
            if datos.get("error"):
                raise ErrorDatos(f"Open-Meteo devolvio error: {datos.get('reason')}")
            return datos
        except (requests.exceptions.RequestException, ValueError) as e:
            # Fallos de red/HTTP y de parseo (JSON malformado, p.ej. un
            # proxy o un 502 que devuelve HTML) se reintentan. ErrorDatos
            # semantico (Open-Meteo respondio pero con {"error": true}) no
            # es RequestException ni ValueError y se propaga de inmediato:
            # reintentar no arregla una coordenada invalida ni un parametro
            # mal formado.
            ultimo = e
            if intento < REINTENTOS - 1:
                time.sleep(ESPERA_BASE_S * (2 ** intento))
    raise ErrorDatos(f"fallaron los {REINTENTOS} intentos contra {url}: {ultimo}")


def _validar_series(bloque: dict, campos: list[str], nombre: str) -> None:
    if "time" not in bloque:
        raise ErrorDatos(f"la respuesta de {nombre} no trae 'time'")
    for campo in campos:
        if campo not in bloque:
            raise ErrorDatos(f"la respuesta de {nombre} no trae '{campo}'")


def _combinar(marine: dict, clima: dict) -> dict[date, list[Hora]]:
    """Une las dos respuestas en horas agrupadas por dia. Funcion pura."""
    hm = marine.get("hourly", {})
    hc = clima.get("hourly", {})
    dc = clima.get("daily", {})

    _validar_series(hm, _CAMPOS_MARINE, "marine")
    _validar_series(hc, _CAMPOS_CLIMA, "clima")

    if hm["time"] != hc["time"]:
        raise ErrorDatos("las series horarias de marine y clima no alinean")

    if not dc.get("sunrise") or not dc.get("sunset"):
        raise ErrorDatos("faltan los datos de salida y puesta del sol")

    sol = {
        date.fromisoformat(d): (
            datetime.fromisoformat(dc["sunrise"][i]),
            datetime.fromisoformat(dc["sunset"][i]),
        )
        for i, d in enumerate(dc["time"])
    }

    por_dia: dict[date, list[Hora]] = {}
    for i, t_str in enumerate(hm["time"]):
        valores = [hm[c][i] for c in _CAMPOS_MARINE] + [hc[c][i] for c in _CAMPOS_CLIMA]
        if any(v is None for v in valores):
            continue

        t = datetime.fromisoformat(t_str)
        if t.date() not in sol:
            continue
        amanecer, ocaso = sol[t.date()]

        por_dia.setdefault(t.date(), []).append(
            Hora(
                t=t,
                swell_altura=float(hm["swell_wave_height"][i]),
                swell_periodo=float(hm["swell_wave_period"][i]),
                swell_direccion=float(hm["swell_wave_direction"][i]),
                viento_kmh=float(hc["wind_speed_10m"][i]),
                viento_direccion=float(hc["wind_direction_10m"][i]),
                es_de_dia=amanecer <= t <= ocaso,
            )
        )

    return por_dia


def obtener_horas(spot: Spot, dias: int = 7, sesion=None) -> dict[date, list[Hora]]:
    """Trae el pronostico horario del spot, agrupado por dia local."""
    base = {"latitude": spot.lat, "longitude": spot.lon,
            "timezone": "auto", "forecast_days": dias}

    marine = _pedir(URL_MARINE, {**base, "hourly": ",".join(_CAMPOS_MARINE)}, sesion)
    clima = _pedir(
        URL_CLIMA,
        {**base, "hourly": ",".join(_CAMPOS_CLIMA), "daily": "sunrise,sunset",
         "wind_speed_unit": "kmh"},
        sesion,
    )
    return _combinar(marine, clima)
