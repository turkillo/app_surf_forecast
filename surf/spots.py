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


def _num(
    contenedor: dict[str, Any],
    campo: str,
    ident: str,
    prefijo: str = "",
) -> float:
    """Valida y convierte un campo numerico. Lanza ValueError con contexto."""
    campo_full = f"{prefijo}{campo}" if prefijo else campo
    if campo not in contenedor:
        raise ValueError(f"[{ident}] falta el campo obligatorio '{campo_full}'")
    valor = contenedor[campo]
    if valor is None:
        raise ValueError(f"[{ident}] el campo '{campo_full}' no puede estar vacio")
    try:
        return float(valor)
    except (ValueError, TypeError):
        raise ValueError(
            f"[{ident}] el campo '{campo_full}' debe ser numerico, se recibio: {valor}"
        )


def _num_list_item(
    contenedor: dict[str, Any],
    lista_campo: str,
    indice: int,
    ident: str,
) -> float:
    """Valida y convierte un elemento numerico dentro de una lista."""
    if lista_campo not in contenedor:
        raise ValueError(f"[{ident}] falta el campo obligatorio '{lista_campo}'")
    lista = contenedor[lista_campo]
    if not isinstance(lista, list) or len(lista) <= indice:
        raise ValueError(
            f"[{ident}] {lista_campo} debe ser una lista con al menos {indice + 1} elementos"
        )
    valor = lista[indice]
    try:
        return float(valor)
    except (ValueError, TypeError):
        raise ValueError(
            f"[{ident}] el elemento [{indice}] de {lista_campo} debe ser numerico, se recibio: {valor}"
        )


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

    # Validar y convertir todos los campos numericos AL INICIO, antes de usarlos
    lat = _num(crudo, "lat", ident)
    lon = _num(crudo, "lon", ident)
    costa_mira = _num(crudo, "costa_mira", ident)
    viento_ideal = _num(crudo, "viento_ideal", ident)

    # Validar y convertir campos numericos de swell
    swell_vent_0 = _num_list_item(sw, "ventana", 0, ident)
    swell_vent_1 = _num_list_item(sw, "ventana", 1, ident)
    swell_ideal = _num(sw, "ideal", ident, "swell.")
    swell_min_altura = _num(sw, "min_altura", ident, "swell.")
    swell_max_altura = _num(sw, "max_altura", ident, "swell.")
    swell_rango_0 = _num_list_item(sw, "rango_ideal", 0, ident)
    swell_rango_1 = _num_list_item(sw, "rango_ideal", 1, ident)
    swell_min_periodo = _num(sw, "min_periodo", ident, "swell.")

    if crudo["tipo"] not in _TIPOS:
        raise ValueError(f"[{ident}] tipo invalido '{crudo['tipo']}', debe ser uno de {_TIPOS}")

    if crudo["confianza"] not in _CONFIANZAS:
        raise ValueError(
            f"[{ident}] confianza invalida '{crudo['confianza']}', debe ser una de {_CONFIANZAS}"
        )

    if swell_max_altura <= swell_min_altura:
        raise ValueError(
            f"[{ident}] max_altura ({swell_max_altura}) debe ser mayor "
            f"que min_altura ({swell_min_altura})"
        )

    if swell_rango_0 < swell_min_altura or swell_rango_1 > swell_max_altura or swell_rango_0 > swell_rango_1:
        raise ValueError(
            f"[{ident}] rango_ideal ({swell_rango_0}, {swell_rango_1}) debe estar contenido "
            f"entre min_altura ({swell_min_altura}) y max_altura ({swell_max_altura})"
        )

    if not en_ventana(swell_ideal, (swell_vent_0, swell_vent_1)):
        raise ValueError(
            f"[{ident}] la direccion ideal ({swell_ideal}) cae fuera de "
            f"la ventana ({swell_vent_0}, {swell_vent_1})"
        )

    if swell_min_periodo <= 0:
        raise ValueError(f"[{ident}] min_periodo debe ser positivo")

    # El offshore sopla desde el rumbo opuesto al que mira la playa. Si el
    # viento ideal documentado no coincide, uno de los dos esta mal.
    offshore_esperado = (costa_mira + 180) % 360
    desvio = angular_diff(viento_ideal, offshore_esperado)
    if desvio > TOLERANCIA_COSTA_GRADOS:
        raise ValueError(
            f"[{ident}] costa_mira ({costa_mira}) implica offshore desde "
            f"{offshore_esperado:.0f}, pero viento_ideal es {viento_ideal} "
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
        # Tras _validar, todos los campos numericos estan garantizados como convertibles a float
        spots.append(
            Spot(
                id=crudo["id"],
                nombre=crudo["nombre"],
                pais=crudo["pais"],
                lat=float(crudo["lat"]),
                lon=float(crudo["lon"]),
                tipo=crudo["tipo"],
                costa_mira=float(crudo["costa_mira"]),
                swell=Swell(
                    ventana=(float(sw["ventana"][0]), float(sw["ventana"][1])),
                    ideal=float(sw["ideal"]),
                    min_altura=float(sw["min_altura"]),
                    max_altura=float(sw["max_altura"]),
                    rango_ideal=(float(sw["rango_ideal"][0]), float(sw["rango_ideal"][1])),
                    min_periodo=float(sw["min_periodo"]),
                ),
                viento_ideal=float(crudo["viento_ideal"]),
                temporada=list(crudo["temporada"]),
                url_surfforecast=crudo["url_surfforecast"],
                fuentes=list(crudo["fuentes"]),
                confianza=crudo["confianza"],
            )
        )

    return spots
