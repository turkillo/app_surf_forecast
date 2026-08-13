"""Carga y validacion de los perfiles de spot.

Cada spot lleva sus propios umbrales. Un umbral hardcodeado en el codigo
de scoring seria un bug: todos los numeros salen de aca.
"""
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from surf.geo import angular_diff, en_ventana

_CONFIANZAS = {"alta", "media", "baja"}
_TIPOS = {"point_break", "beach_break", "reef"}
_CAMPOS_SPOT = [
    "id", "nombre", "pais", "lat", "lon", "tipo", "costa_mira",
    "swell", "viento_ideal", "temporada", "url_surfforecast",
    "fuentes", "confianza",
]
_CAMPOS_SWELL = [
    "ventana", "ideal", "min_altura", "max_altura",
    "rango_ideal", "min_periodo",
]

# Tolerancia entre la orientacion geometrica de la costa y el viento ideal
# documentado. Por encima de esto hay un error de investigacion.
TOLERANCIA_COSTA_GRADOS = 30


@dataclass(frozen=True)
class Swell:
    ventana: tuple[float, float]
    ideal: float
    min_altura: float
    max_altura: float
    rango_ideal: tuple[float, float]
    min_periodo: float


@dataclass(frozen=True)
class Spot:
    id: str
    nombre: str
    pais: str
    lat: float
    lon: float
    tipo: str
    costa_mira: float
    swell: Swell
    viento_ideal: float
    temporada: list[int]
    url_surfforecast: str
    fuentes: list[str]
    confianza: str


def _validar(crudo: dict[str, Any]) -> None:
    ident = crudo.get("id", "<sin id>")

    for campo in _CAMPOS_SPOT:
        if campo not in crudo:
            raise ValueError(f"[{ident}] falta el campo obligatorio '{campo}'")
        if crudo[campo] is None:
            raise ValueError(f"[{ident}] el campo '{campo}' no puede estar vacio")

    sw = crudo["swell"]
    if sw is None or not isinstance(sw, dict):
        raise ValueError(f"[{ident}] swell debe ser un diccionario con campos obligatorios")
    for campo in _CAMPOS_SWELL:
        if campo not in sw:
            raise ValueError(f"[{ident}] falta el campo obligatorio 'swell.{campo}'")
        if sw[campo] is None:
            raise ValueError(f"[{ident}] el campo 'swell.{campo}' no puede estar vacio")

    if crudo["tipo"] not in _TIPOS:
        raise ValueError(f"[{ident}] tipo invalido '{crudo['tipo']}', debe ser uno de {_TIPOS}")

    if crudo["confianza"] not in _CONFIANZAS:
        raise ValueError(
            f"[{ident}] confianza invalida '{crudo['confianza']}', debe ser una de {_CONFIANZAS}"
        )

    if sw["max_altura"] <= sw["min_altura"]:
        raise ValueError(
            f"[{ident}] max_altura ({sw['max_altura']}) debe ser mayor "
            f"que min_altura ({sw['min_altura']})"
        )

    ri_min, ri_max = sw["rango_ideal"]
    if ri_min < sw["min_altura"] or ri_max > sw["max_altura"] or ri_min > ri_max:
        raise ValueError(
            f"[{ident}] rango_ideal {sw['rango_ideal']} debe estar contenido "
            f"entre min_altura ({sw['min_altura']}) y max_altura ({sw['max_altura']})"
        )

    if not en_ventana(sw["ideal"], tuple(sw["ventana"])):
        raise ValueError(
            f"[{ident}] la direccion ideal ({sw['ideal']}) cae fuera de "
            f"la ventana {sw['ventana']}"
        )

    if sw["min_periodo"] <= 0:
        raise ValueError(f"[{ident}] min_periodo debe ser positivo")

    # El offshore sopla desde el rumbo opuesto al que mira la playa. Si el
    # viento ideal documentado no coincide, uno de los dos esta mal.
    offshore_esperado = (crudo["costa_mira"] + 180) % 360
    desvio = angular_diff(crudo["viento_ideal"], offshore_esperado)
    if desvio > TOLERANCIA_COSTA_GRADOS:
        raise ValueError(
            f"[{ident}] costa_mira ({crudo['costa_mira']}) implica offshore desde "
            f"{offshore_esperado:.0f}, pero viento_ideal es {crudo['viento_ideal']} "
            f"({desvio:.0f} grados de desvio, maximo {TOLERANCIA_COSTA_GRADOS}). "
            f"Revisar la investigacion de este spot."
        )

    for mes in crudo["temporada"]:
        if not 1 <= mes <= 12:
            raise ValueError(f"[{ident}] mes invalido en temporada: {mes}")


def cargar_spots(path: Path) -> list[Spot]:
    """Carga spots.yaml y valida cada perfil.

    Lanza ValueError con un mensaje accionable ante el primer problema.
    """
    crudos = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not crudos:
        raise ValueError(f"{path} esta vacio")
    if not isinstance(crudos, list):
        raise ValueError(f"{path} debe contener una lista de spots, no un mapping")

    vistos: set[str] = set()
    spots: list[Spot] = []

    for crudo in crudos:
        _validar(crudo)
        if crudo["id"] in vistos:
            raise ValueError(f"id duplicado: '{crudo['id']}'")
        vistos.add(crudo["id"])

        sw = crudo["swell"]
        ident = crudo.get("id", "<sin id>")

        try:
            lat = float(crudo["lat"])
        except (ValueError, TypeError):
            raise ValueError(f"[{ident}] lat debe ser un numero, se recibio: {crudo['lat']}")

        try:
            lon = float(crudo["lon"])
        except (ValueError, TypeError):
            raise ValueError(f"[{ident}] lon debe ser un numero, se recibio: {crudo['lon']}")

        try:
            costa_mira = float(crudo["costa_mira"])
        except (ValueError, TypeError):
            raise ValueError(f"[{ident}] costa_mira debe ser un numero, se recibio: {crudo['costa_mira']}")

        try:
            viento_ideal = float(crudo["viento_ideal"])
        except (ValueError, TypeError):
            raise ValueError(f"[{ident}] viento_ideal debe ser un numero, se recibio: {crudo['viento_ideal']}")

        try:
            swell_ventana_0 = float(sw["ventana"][0])
            swell_ventana_1 = float(sw["ventana"][1])
            swell_ideal = float(sw["ideal"])
            swell_min_altura = float(sw["min_altura"])
            swell_max_altura = float(sw["max_altura"])
            swell_rango_ideal_0 = float(sw["rango_ideal"][0])
            swell_rango_ideal_1 = float(sw["rango_ideal"][1])
            swell_min_periodo = float(sw["min_periodo"])
        except (ValueError, TypeError) as e:
            raise ValueError(f"[{ident}] error al parsear valores numericos de swell: {e}")

        spots.append(
            Spot(
                id=crudo["id"],
                nombre=crudo["nombre"],
                pais=crudo["pais"],
                lat=lat,
                lon=lon,
                tipo=crudo["tipo"],
                costa_mira=costa_mira,
                swell=Swell(
                    ventana=(swell_ventana_0, swell_ventana_1),
                    ideal=swell_ideal,
                    min_altura=swell_min_altura,
                    max_altura=swell_max_altura,
                    rango_ideal=(swell_rango_ideal_0, swell_rango_ideal_1),
                    min_periodo=swell_min_periodo,
                ),
                viento_ideal=viento_ideal,
                temporada=list(crudo["temporada"]),
                url_surfforecast=crudo["url_surfforecast"],
                fuentes=list(crudo["fuentes"]),
                confianza=crudo["confianza"],
            )
        )

    return spots
