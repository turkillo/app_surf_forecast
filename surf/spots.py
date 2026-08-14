"""Carga y validacion de los perfiles de spot.

Cada spot lleva sus propios umbrales. Un umbral hardcodeado en el codigo
de scoring seria un bug: todos los numeros salen de aca.
"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from surf.geo import angular_diff, en_ventana

_CONFIANZAS = {"alta", "media", "baja"}
_TIPOS = {"point_break", "beach_break", "reef"}

# `cercania` registra COMO llega el usuario al spot, y existe para dejar
# asentado por que dos spots pueden llevar umbrales distintos:
#   local -> va sin planificar viaje, el costo de ir es bajo
#   viaje -> hay que sacar pasaje, solo vale la pena por algo muy bueno
# No es decorativo. Si alguien corre el backtest dentro de seis meses, ve que
# un spot local da mas alertas que el resto y lo "corrige", rompe una decision
# deliberada. Es la leccion que dejo `temporada`, que se poblo con dos
# significados distintos porque nunca se documento cual era.
_CERCANIAS = {"local", "viaje"}

_CAMPOS_SPOT = [
    "id", "nombre", "pais", "lat", "lon", "tipo", "costa_mira",
    "swell", "viento_ideal", "temporada", "url_surfforecast",
    "fuentes", "confianza",
]

# `cercania` es OPCIONAL en el YAML y cae en "viaje", la categoria estricta.
# Que sea opcional es para que un perfil minimo siga cargando; que los 13 spots
# reales lo declaren igual lo verifica un test sobre el YAML de produccion.
CERCANIA_POR_DEFECTO = "viaje"

# Maximo desvio permitido entre el punto del spot y el punto donde se consulta
# el oleaje. No es una tolerancia fisica: es una guarda contra un error de
# tipeo que mande el punto a otro oceano. Un grado son ~111 km, y los
# desplazamientos reales son de 20 km.
MAX_DESVIO_PUNTO_MAR_GRADOS = 1.0
_CAMPOS_SWELL = [
    "ventana", "ideal", "min_altura", "max_altura",
    "rango_ideal", "min_periodo",
]

# Tolerancia entre la orientacion geometrica de la costa y el viento ideal
# documentado. Por encima de esto hay un error de investigacion.
TOLERANCIA_COSTA_GRADOS = 30

# Fuentes de olas que tienen que quedar CONFIGURADAS despues de aplicar
# `modelos_excluidos`. Con una sola fuente no hay consenso: un modelo solo no
# puede desmentirse a si mismo, y el falso positivo que el consenso existe para
# evitar vuelve a entrar. Es peor que el problema que la exclusion arregla.
MINIMO_FUENTES_OLAS_CONFIGURADAS = 2


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
    # Por defecto `viaje`, que es la categoria ESTRICTA: un spot al que nadie
    # le puso la etiqueta se filtra con el criterio conservador.
    cercania: str = "viaje"
    # Punto donde se consulta el OLEAJE, cuando no es el del spot. Los modelos
    # de olas trabajan en grillas de 0.25 grados (~28 km), asi que una
    # coordenada pegada a la costa cae en celdas parcialmente enmascaradas como
    # tierra y el modelo devuelve alturas muy por debajo de las reales. El
    # viento NO se mueve: a 20 km de la costa es otro viento (medido: +7 a
    # +14.5 km/h de mediana y practicamente sin horas glassy), y el viento es
    # la condicion mas local del gate.
    lat_mar: float | None = None
    lon_mar: float | None = None
    # Modelos de OLAS que no votan en este spot. Un modelo de olas no vale lo
    # mismo en todos los puntos: su celda de grilla puede estar contaminada por
    # tierra o por una batimetria que no es la del pico, y ahi describe un mar
    # que no existe. Cuando eso pasa, el consenso "2 de 3" se vuelve en contra:
    # el modelo equivocado le veta el aviso al que mide bien.
    #
    # NO es un dial para subir el volumen de alertas. Cada nombre de esta lista
    # tiene que venir con un ratio medido contra surf-forecast anotado en
    # spots.yaml, y el validador exige que queden al menos
    # MINIMO_FUENTES_OLAS_CONFIGURADAS fuentes.
    modelos_excluidos: list[str] = field(default_factory=list)

    @property
    def coords_mar(self) -> tuple[float, float]:
        """Punto para la Marine API. Cae en el del spot si no se desplazo."""
        return (self.lat if self.lat_mar is None else self.lat_mar,
                self.lon if self.lon_mar is None else self.lon_mar)


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


def _validar_modelos_excluidos(crudo: dict[str, Any], ident: str) -> None:
    """El campo es opcional; si esta, tiene que nombrar modelos que existan y
    dejar con que contrastar.

    La lista de modelos vive en `surf.consenso`, que a su vez importa este
    modulo: el import va adentro de la funcion para no cerrar el ciclo. Es el
    mismo recurso que ya usa `surf.fetch`. La alternativa --repetir los nombres
    aca-- deja dos listas que pueden divergir en silencio, que es peor.
    """
    from surf.consenso import MODELOS_OLAS

    if "modelos_excluidos" not in crudo or crudo["modelos_excluidos"] is None:
        return

    excluidos = crudo["modelos_excluidos"]
    if not isinstance(excluidos, list):
        raise ValueError(
            f"[{ident}] modelos_excluidos debe ser una lista de nombres de "
            f"modelo, se recibio: {excluidos!r}"
        )

    for nombre in excluidos:
        if nombre not in MODELOS_OLAS:
            raise ValueError(
                f"[{ident}] modelos_excluidos nombra '{nombre}', que no es un "
                f"modelo de olas. Los validos son: {', '.join(MODELOS_OLAS)}"
            )

    if len(set(excluidos)) != len(excluidos):
        raise ValueError(
            f"[{ident}] modelos_excluidos repite nombres ({', '.join(excluidos)}). "
            f"Repetir uno no excluye dos fuentes: revisar la lista."
        )

    quedan = len(MODELOS_OLAS) - len(set(excluidos))
    if quedan < MINIMO_FUENTES_OLAS_CONFIGURADAS:
        raise ValueError(
            f"[{ident}] excluir {', '.join(excluidos)} deja {quedan} fuente(s) "
            f"de olas y el minimo es {MINIMO_FUENTES_OLAS_CONFIGURADAS}: con una "
            f"sola fuente no hay consenso posible. Sacar un nombre de la lista, "
            f"o corregir el punto de muestreo del spot en vez de excluir."
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

    if crudo.get("cercania", CERCANIA_POR_DEFECTO) not in _CERCANIAS:
        raise ValueError(
            f"[{ident}] cercania invalida '{crudo['cercania']}', debe ser una de {_CERCANIAS}"
        )

    # El punto de oleaje es opcional, pero o estan las dos coordenadas o
    # ninguna: media coordenada desplazada daria un punto que no eligio nadie.
    tiene_lat_mar = crudo.get("lat_mar") is not None
    tiene_lon_mar = crudo.get("lon_mar") is not None
    if tiene_lat_mar != tiene_lon_mar:
        raise ValueError(
            f"[{ident}] lat_mar y lon_mar van juntos: si se desplaza el punto de "
            f"oleaje hay que dar las dos coordenadas"
        )
    if tiene_lat_mar:
        lat_mar = _num(crudo, "lat_mar", ident)
        lon_mar = _num(crudo, "lon_mar", ident)
        if (abs(lat_mar - lat) > MAX_DESVIO_PUNTO_MAR_GRADOS
                or abs(lon_mar - lon) > MAX_DESVIO_PUNTO_MAR_GRADOS):
            raise ValueError(
                f"[{ident}] el punto de oleaje (lat_mar {lat_mar}, lon_mar {lon_mar}) "
                f"esta a mas de {MAX_DESVIO_PUNTO_MAR_GRADOS} grado del spot "
                f"({lat}, {lon}). Revisar: parece un error de tipeo."
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

    _validar_modelos_excluidos(crudo, ident)


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
                cercania=crudo.get("cercania", CERCANIA_POR_DEFECTO),
                lat_mar=(float(crudo["lat_mar"])
                         if crudo.get("lat_mar") is not None else None),
                lon_mar=(float(crudo["lon_mar"])
                         if crudo.get("lon_mar") is not None else None),
                modelos_excluidos=list(crudo.get("modelos_excluidos") or []),
            )
        )

    return spots
