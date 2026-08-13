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

from surf.geo import angular_diff, clasificar_viento, en_ventana
from surf.spots import Spot

VIENTO_GLASSY_KMH = 6.0
OFFSHORE_IDEAL_KMH = 20.0
OFFSHORE_MAX_KMH = 35.0
CROSS_IDEAL_KMH = 12.0
CROSS_MAX_KMH = 20.0
ONSHORE_MAX_KMH = 8.0

PERIODO_TOPE_S = 16.0
PISO_FACTOR_ALTURA = 0.4
PISO_FACTOR_DIRECCION = 0.5
PISO_FACTOR_OFFSHORE = 0.4
PISO_FACTOR_CROSS = 0.3
FACTOR_CROSS_IDEAL = 0.85
FACTOR_ONSHORE = 0.5

# Pesos del score. Suman 1.0. Aca SI corresponde un promedio ponderado:
# solo se aplica sobre condiciones que ya pasaron el gate, o sea que todas
# las opciones que compara son surfeables.
PESOS = {"altura": 0.35, "periodo": 0.30, "direccion": 0.15, "viento": 0.20}


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


def _interpolar(x: float, x0: float, x1: float, y0: float, y1: float) -> float:
    """Interpolacion lineal de x en [x0,x1] hacia [y0,y1]."""
    if x1 == x0:
        return y1
    t = (x - x0) / (x1 - x0)
    return y0 + t * (y1 - y0)


def factor_altura(altura: float, spot: Spot) -> float:
    """1.0 dentro del rango ideal, cae linealmente hacia los extremos."""
    sw = spot.swell
    ideal_min, ideal_max = sw.rango_ideal
    if ideal_min <= altura <= ideal_max:
        return 1.0
    if altura < ideal_min:
        return _interpolar(altura, sw.min_altura, ideal_min, PISO_FACTOR_ALTURA, 1.0)
    return _interpolar(altura, ideal_max, sw.max_altura, 1.0, PISO_FACTOR_ALTURA)


def factor_periodo(periodo: float, spot: Spot) -> float:
    """0.0 en el minimo del spot, 1.0 a los 16 segundos, con tope."""
    f = _interpolar(periodo, spot.swell.min_periodo, PERIODO_TOPE_S, 0.0, 1.0)
    return min(1.0, max(0.0, f))


def factor_direccion(direccion: float, spot: Spot) -> float:
    """1.0 en la direccion ideal, 0.5 en los bordes de la ventana."""
    sw = spot.swell
    desvio = angular_diff(direccion, sw.ideal)
    borde = max(angular_diff(sw.ventana[0], sw.ideal),
                angular_diff(sw.ventana[1], sw.ideal))
    if borde == 0:
        return 1.0
    f = _interpolar(desvio, 0.0, borde, 1.0, PISO_FACTOR_DIRECCION)
    return min(1.0, max(PISO_FACTOR_DIRECCION, f))


def factor_viento(viento_kmh: float, clase: str) -> float:
    """Factor de viento segun la tabla del diseno."""
    if viento_kmh <= VIENTO_GLASSY_KMH:
        return 1.0
    if clase == "offshore":
        if viento_kmh <= OFFSHORE_IDEAL_KMH:
            return 1.0
        return _interpolar(viento_kmh, OFFSHORE_IDEAL_KMH, OFFSHORE_MAX_KMH,
                           1.0, PISO_FACTOR_OFFSHORE)
    if clase == "cross":
        if viento_kmh <= CROSS_IDEAL_KMH:
            return FACTOR_CROSS_IDEAL
        return _interpolar(viento_kmh, CROSS_IDEAL_KMH, CROSS_MAX_KMH,
                           FACTOR_CROSS_IDEAL, PISO_FACTOR_CROSS)
    return FACTOR_ONSHORE


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
    score = 100.0 * (
        PESOS["altura"] * factor_altura(hora.swell_altura, spot)
        + PESOS["periodo"] * factor_periodo(hora.swell_periodo, spot)
        + PESOS["direccion"] * factor_direccion(hora.swell_direccion, spot)
        + PESOS["viento"] * factor_viento(hora.viento_kmh, clase)
    )
    return HoraEvaluada(hora=hora, pasa=True, motivo_rechazo=None,
                        score=score, clase_viento=clase)
