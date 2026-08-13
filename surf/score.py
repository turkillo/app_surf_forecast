"""Gate y scoring de condiciones de surf.

Diseno deliberado: gate duro primero, score despues. El gate son condiciones
binarias que TODAS deben cumplirse; no hay compensacion entre criterios. Un
promedio ponderado sobre el gate permitiria que 2.5m con onshore de 30 km/h
saque 70 puntos y dispare una alerta por un dia de espuma.

Este modulo es puro: no hace red, ni archivos, ni consulta la hora actual.
Es lo que permite que el backtest corra exactamente el mismo codigo que
produccion.
"""
from dataclasses import dataclass
from datetime import datetime

from surf.geo import clasificar_viento, en_ventana
from surf.spots import Spot

VIENTO_GLASSY_KMH = 6.0
OFFSHORE_IDEAL_KMH = 20.0
OFFSHORE_MAX_KMH = 35.0
CROSS_IDEAL_KMH = 12.0
CROSS_MAX_KMH = 20.0
ONSHORE_MAX_KMH = 8.0


@dataclass(frozen=True)
class Hora:
    t: datetime
    swell_altura: float
    swell_periodo: float
    swell_direccion: float
    viento_kmh: float
    viento_direccion: float
    es_de_dia: bool


@dataclass(frozen=True)
class HoraEvaluada:
    hora: Hora
    pasa: bool
    motivo_rechazo: str | None
    score: float
    clase_viento: str


def _gate_viento(hora: Hora, clase: str) -> str | None:
    """Devuelve el motivo de rechazo, o None si el viento pasa."""
    if hora.viento_kmh <= VIENTO_GLASSY_KMH:
        return None
    if clase == "offshore":
        if hora.viento_kmh > OFFSHORE_MAX_KMH:
            return f"offshore muy fuerte ({hora.viento_kmh:.0f} km/h, maximo {OFFSHORE_MAX_KMH:.0f})"
        return None
    if clase == "cross":
        if hora.viento_kmh > CROSS_MAX_KMH:
            return f"cross muy fuerte ({hora.viento_kmh:.0f} km/h, maximo {CROSS_MAX_KMH:.0f})"
        return None
    if hora.viento_kmh > ONSHORE_MAX_KMH:
        return f"viento onshore ({hora.viento_kmh:.0f} km/h, maximo {ONSHORE_MAX_KMH:.0f})"
    return None


def _gate(hora: Hora, spot: Spot, clase: str) -> str | None:
    """Aplica las seis condiciones. Devuelve el primer motivo de rechazo."""
    sw = spot.swell

    if not hora.es_de_dia:
        return "fuera de horas de luz"
    if hora.swell_altura < sw.min_altura:
        return f"altura insuficiente ({hora.swell_altura:.1f}m, minimo {sw.min_altura:.1f}m)"
    if hora.swell_altura > sw.max_altura:
        return f"el spot cierra con este tamano ({hora.swell_altura:.1f}m, maximo {sw.max_altura:.1f}m)"
    if hora.swell_periodo < sw.min_periodo:
        return f"periodo corto ({hora.swell_periodo:.1f}s, minimo {sw.min_periodo:.1f}s)"
    if not en_ventana(hora.swell_direccion, sw.ventana):
        return (
            f"direccion fuera de la ventana del spot "
            f"({hora.swell_direccion:.0f}, ventana {sw.ventana[0]:.0f}-{sw.ventana[1]:.0f})"
        )
    return _gate_viento(hora, clase)


def evaluar_hora(hora: Hora, spot: Spot) -> HoraEvaluada:
    """Evalua una hora contra el perfil del spot."""
    clase = clasificar_viento(hora.viento_direccion, spot.costa_mira)
    motivo = _gate(hora, spot, clase)
    if motivo is not None:
        return HoraEvaluada(hora=hora, pasa=False, motivo_rechazo=motivo,
                            score=0.0, clase_viento=clase)
    return HoraEvaluada(hora=hora, pasa=True, motivo_rechazo=None,
                        score=0.0, clase_viento=clase)
