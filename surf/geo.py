"""Geometria angular para orientacion de costa y direcciones de swell y viento.

Convencion: todas las direcciones estan en grados 0-360 e indican el rumbo
DESDE el que viene el fenomeno (convencion meteorologica), salvo `costa_mira`
que indica hacia donde mira la playa.
"""

_ROSA = [
    "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
    "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW",
]


def angular_diff(a: float, b: float) -> float:
    """Menor diferencia angular entre dos rumbos. Siempre entre 0 y 180."""
    d = abs(a - b) % 360
    return 360 - d if d > 180 else d


def clasificar_viento(viento_desde: float, costa_mira: float) -> str:
    """Clasifica el viento relativo a la orientacion de la playa.

    El offshore sopla desde tierra hacia el mar, o sea desde el rumbo
    opuesto al que mira la playa.
    """
    offshore_desde = (costa_mira + 180) % 360
    rel = angular_diff(viento_desde, offshore_desde)
    if rel < 45:
        return "offshore"
    if rel <= 135:
        return "cross"
    return "onshore"


def en_ventana(direccion: float, ventana: tuple[float, float]) -> bool:
    """Indica si una direccion cae dentro de una ventana angular.

    Soporta ventanas que cruzan el 0 (por ejemplo (300, 60)).
    Los bordes se consideran incluidos.
    """
    desde, hasta = ventana[0] % 360, ventana[1] % 360
    d = direccion % 360
    if desde <= hasta:
        return desde <= d <= hasta
    return d >= desde or d <= hasta


def rumbo_a_texto(grados: float) -> str:
    """Convierte grados a una de las 16 direcciones de la rosa de los vientos."""
    i = int((grados % 360) / 22.5 + 0.5) % 16
    return _ROSA[i]
