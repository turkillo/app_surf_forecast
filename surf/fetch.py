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

# Dias de pronostico que se piden por spot. Cubre desde hoy (dia 0) hasta el
# dia 10 inclusive, que es el techo del regimen de pre-aviso (ver
# surf/alert.py). Alargar el rango NO multiplica las llamadas: siguen siendo
# dos por spot (oleaje y viento), cada una con una serie mas larga.
DIAS_PRONOSTICO = 11

_CAMPOS_MARINE = ["swell_wave_height", "swell_wave_period", "swell_wave_direction"]
_CAMPOS_CLIMA = ["wind_speed_10m", "wind_direction_10m"]

# Altura de swell que Open-Meteo devuelve cuando la celda de grilla del modelo
# esta enmascarada como tierra. No es un dato, es un hueco de cobertura.
ALTURA_HUECO_M = 0.0


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


def _bases(spot: Spot, dias: int) -> tuple[dict, dict]:
    """Params comunes de cada endpoint: oleaje y viento pueden ir a puntos distintos.

    Los modelos de olas trabajan en grillas de ~28 km y una coordenada pegada a
    la costa cae en celdas contaminadas por tierra, asi que algunos spots
    consultan el oleaje mar adentro (`spot.coords_mar`). El viento se sigue
    midiendo en la playa: a 20 km de la costa es otro viento, y es la condicion
    mas local del gate.

    Los dos puntos van con `timezone=auto`. Estan a ~20 km, asi que resuelven a
    la misma zona horaria; si alguna vez no fuera asi, `_combinar` corta con
    ErrorDatos al comparar las series y el spot se saltea, que es el
    comportamiento correcto.
    """
    lat_mar, lon_mar = spot.coords_mar
    comun = {"timezone": "auto", "forecast_days": dias}
    return ({**comun, "latitude": lat_mar, "longitude": lon_mar},
            {**comun, "latitude": spot.lat, "longitude": spot.lon})


def obtener_horas(spot: Spot, dias: int = 7, sesion=None) -> dict[date, list[Hora]]:
    """Trae el pronostico horario del spot, agrupado por dia local."""
    base_mar, base_viento = _bases(spot, dias)

    marine = _pedir(URL_MARINE, {**base_mar, "hourly": ",".join(_CAMPOS_MARINE)}, sesion)
    clima = _pedir(
        URL_CLIMA,
        {**base_viento, "hourly": ",".join(_CAMPOS_CLIMA), "daily": "sunrise,sunset",
         "wind_speed_unit": "kmh"},
        sesion,
    )
    return _combinar(marine, clima)


def obtener_horas_multimodelo(spot: Spot, dias: int = DIAS_PRONOSTICO,
                              sesion=None) -> dict[date, list["HoraMultiModelo"]]:
    """Trae el pronostico de varios modelos y los devuelve agrupados por hora.

    Los modelos de olas y de viento se emparejan por posicion. Si un modelo no
    tiene cobertura en el spot, Open-Meteo no devuelve su columna y ese modelo
    se omite; el consenso se calcula con los que si respondieron.
    """
    from surf.consenso import (MODELOS_OLAS, MODELOS_OLAS_PEDIDOS,
                               MODELOS_VIENTO, HoraMultiModelo)

    base_mar, base_viento = _bases(spot, dias)

    # Se piden tambien los respaldos (ver RESPALDO_OLAS). Traerlos no los hace
    # votar: `_combinar_multimodelo` deja entrar a uno solo cuando su titular
    # no tiene dato en este punto.
    marine = _pedir(URL_MARINE, {**base_mar, "hourly": ",".join(_CAMPOS_MARINE),
                                 "models": ",".join(MODELOS_OLAS_PEDIDOS)}, sesion)
    clima = _pedir(URL_CLIMA, {**base_viento, "hourly": ",".join(_CAMPOS_CLIMA),
                               "models": ",".join(MODELOS_VIENTO),
                               "daily": "sunrise,sunset",
                               "wind_speed_unit": "kmh"}, sesion)

    return _combinar_multimodelo(marine, clima, MODELOS_OLAS, MODELOS_VIENTO)


def _sufijo(campo: str, modelo: str, disponibles: dict) -> str | None:
    """Open-Meteo sufija cada columna con el nombre del modelo.

    La Marine API antepone 'marine_' a best_match; por eso se prueban las
    dos formas en vez de asumir una.
    """
    for candidato in (f"{campo}_{modelo}", f"{campo}_marine_{modelo}"):
        if candidato in disponibles:
            return candidato
    return None


def _tiene_dato_util(modelo: str, hm: dict) -> bool:
    """El modelo devolvio al menos una altura que no sea nula ni el 0.0 de mascara.

    Es la prueba de que su celda de grilla cae en agua en ESTE punto. Se mira la
    serie completa y no hora por hora a proposito: la sustitucion por respaldo
    es una decision del punto, no de la hora. Si dependiera de la hora, la
    tercera fuente cambiaria de identidad a lo largo del dia y la mediana
    saltaria entre dos modelos distintos sin que nada lo dijera.
    """
    columna = _sufijo("swell_wave_height", modelo, hm)
    if columna is None:
        return False
    return any(v is not None and float(v) != ALTURA_HUECO_M for v in hm[columna])


def _con_respaldos(modelos_olas: list[str], hm: dict,
                   respaldos: dict[str, str]) -> list[str]:
    """Reemplaza cada titular sin dato en este punto por su respaldo.

    El respaldo entra EN LA MISMA POSICION, que es lo que conserva el
    emparejamiento olas[i]+viento[i]: la fuente cambia de nombre, no de puesto.
    Y como es un reemplazo y no un agregado, titular y respaldo nunca pueden
    votar juntos -- que es obligatorio cuando los dos son el mismo modelo de
    NOAA en dos grillas (ver RESPALDO_OLAS en surf/consenso.py).
    """
    efectivos = []
    for modelo in modelos_olas:
        respaldo = respaldos.get(modelo)
        if (respaldo is not None and not _tiene_dato_util(modelo, hm)
                and _tiene_dato_util(respaldo, hm)):
            efectivos.append(respaldo)
        else:
            efectivos.append(modelo)
    return efectivos


def _combinar_multimodelo(marine: dict, clima: dict, modelos_olas: list[str],
                          modelos_viento: list[str],
                          respaldos: dict[str, str] | None = None) -> dict:
    """Une las respuestas multi-modelo. Funcion pura."""
    from surf.consenso import RESPALDO_OLAS, HoraMultiModelo

    hm, hc, dc = marine.get("hourly", {}), clima.get("hourly", {}), clima.get("daily", {})
    modelos_olas = _con_respaldos(
        modelos_olas, hm, RESPALDO_OLAS if respaldos is None else respaldos)

    if "time" not in hm or "time" not in hc:
        raise ErrorDatos("falta la serie 'time' en alguna respuesta")
    if hm["time"] != hc["time"]:
        raise ErrorDatos("las series horarias de marine y clima no alinean")

    # Open-Meteo sufija sunrise/sunset por modelo igual que las columnas
    # horarias cuando se pide "models" en la Forecast API, asi que "sunrise"
    # a secas no esta presente. Se usa el primer modelo de viento disponible
    # como referencia (el amanecer/ocaso no varia de forma relevante entre
    # modelos).
    col_sunrise = _sufijo("sunrise", modelos_viento[0], dc) if modelos_viento else None
    col_sunset = _sufijo("sunset", modelos_viento[0], dc) if modelos_viento else None
    if col_sunrise is None or col_sunset is None:
        for candidato in dc:
            if candidato.startswith("sunrise") and dc.get(candidato):
                col_sunrise = candidato
            if candidato.startswith("sunset") and dc.get(candidato):
                col_sunset = candidato
    if not col_sunrise or not col_sunset or not dc.get(col_sunrise) or not dc.get(col_sunset):
        raise ErrorDatos("faltan los datos de salida y puesta del sol")

    # Columnas de viento de cada modelo, en el orden de `modelos_viento`.
    # Sirven como respaldo: ver el emparejamiento mas abajo.
    viento_por_modelo: list[tuple[str, dict]] = []
    for mv in modelos_viento:
        cols = {c: _sufijo(c, mv, hc) for c in _CAMPOS_CLIMA}
        if all(v is not None for v in cols.values()):
            viento_por_modelo.append((mv, cols))

    # Emparejar modelos de olas con modelos de viento por posicion.
    pares = []
    series_vistas: dict[tuple, str] = {}
    for i, mo in enumerate(modelos_olas):
        cols_olas = {c: _sufijo(c, mo, hm) for c in _CAMPOS_MARINE}
        if any(v is None for v in cols_olas.values()):
            continue

        # Dos modelos que devuelven la MISMA serie son una sola fuente, no dos
        # votos. Es exactamente lo que pasaba con best_match y meteofrance_wave
        # (identicos en 72/72 horas y en los 13 spots): el consenso "2 de 3"
        # se satisfacia con una sola fuente de olas votando dos veces. Se
        # descarta aca, en el origen, para que el bug no pueda reintroducirse
        # agregando un modelo redundante a la lista.
        huella = tuple(tuple(hm[cols_olas[c]]) for c in _CAMPOS_MARINE)
        if huella in series_vistas:
            continue
        series_vistas[huella] = mo

        if not viento_por_modelo:
            continue
        preferido = modelos_viento[min(i, len(modelos_viento) - 1)]
        # El modelo de viento asignado va primero y el resto queda de respaldo,
        # en orden. El respaldo NO cambia el emparejamiento cuando el preferido
        # tiene dato: solo entra cuando la columna preferida viene vacia a esa
        # hora, y entonces la alternativa es usar otro viento o perder por
        # completo esa fuente de olas.
        #
        # Es lo que pasa a partir del dia 7: icon_seamless muere a las 177 h
        # mientras meteofrance_wave llega a las 235 h, asi que sin respaldo la
        # unica fuente de olas util de los dias 8 y 9 --el corazon del
        # pre-aviso-- se descartaria por falta de viento. Reordenar
        # MODELOS_VIENTO tambien lo arreglaria, pero movia 5 de 91 dias del
        # rango 0-6 (medido): el respaldo no toca nada ahi, porque en esos
        # dias los tres modelos de viento tienen cobertura completa.
        alternativas = ([p for p in viento_por_modelo if p[0] == preferido]
                        + [p for p in viento_por_modelo if p[0] != preferido])
        pares.append((mo, cols_olas, alternativas))

    if not pares:
        raise ErrorDatos("ningun modelo devolvio las columnas esperadas")

    sol = {date.fromisoformat(d): (datetime.fromisoformat(dc[col_sunrise][i]),
                                   datetime.fromisoformat(dc[col_sunset][i]))
           for i, d in enumerate(dc["time"])}

    por_dia: dict = {}
    for i, t_str in enumerate(hm["time"]):
        t = datetime.fromisoformat(t_str)
        if t.date() not in sol:
            continue
        amanecer, ocaso = sol[t.date()]
        es_de_dia = amanecer <= t <= ocaso

        por_modelo = {}
        for mo, cols_olas, alternativas in pares:
            if any(hm[c][i] is None for c in cols_olas.values()):
                continue
            # Primer modelo de viento con dato a esta hora: el preferido salvo
            # que no lo tenga. El nombre lleva el que se uso de verdad, no el
            # que le tocaba, para que la linea de concordancia no nombre un
            # modelo que en esa hora no aporto nada.
            cols_viento = nombre = None
            for mv, cols in alternativas:
                if all(hc[c][i] is not None for c in cols.values()):
                    cols_viento, nombre = cols, f"{mo}+{mv}"
                    break
            if cols_viento is None:
                continue
            if float(hm[cols_olas["swell_wave_height"]][i]) == ALTURA_HUECO_M:
                # Un 0.0 exacto donde otros modelos ven mas de un metro no es
                # mar planchado: es una celda de grilla enmascarada como
                # tierra. ncep_gfswave025 devuelve 0.0/0.0/0 las 72 horas en 5
                # de los 13 spots (verificado contra la API real). Tomarlo
                # como cero real haria que ese modelo votara siempre que no,
                # y arrastraria la mediana de altura hacia abajo.
                continue
            por_modelo[nombre] = Hora(
                t=t,
                swell_altura=float(hm[cols_olas["swell_wave_height"]][i]),
                swell_periodo=float(hm[cols_olas["swell_wave_period"]][i]),
                swell_direccion=float(hm[cols_olas["swell_wave_direction"]][i]),
                viento_kmh=float(hc[cols_viento["wind_speed_10m"]][i]),
                viento_direccion=float(hc[cols_viento["wind_direction_10m"]][i]),
                es_de_dia=es_de_dia,
            )

        if por_modelo:
            por_dia.setdefault(t.date(), []).append(
                HoraMultiModelo(t=t, es_de_dia=es_de_dia, por_modelo=por_modelo)
            )

    return por_dia
