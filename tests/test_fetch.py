from datetime import date

import pytest
import requests

from surf.fetch import ErrorDatos, _combinar, _pedir

MARINE = {
    "hourly": {
        "time": ["2026-08-21T05:00", "2026-08-21T09:00", "2026-08-21T22:00"],
        "swell_wave_height": [1.8, 1.9, 1.7],
        "swell_wave_period": [14.0, 14.2, 13.8],
        "swell_wave_direction": [200.0, 202.0, 199.0],
    }
}

CLIMA = {
    "hourly": {
        "time": ["2026-08-21T05:00", "2026-08-21T09:00", "2026-08-21T22:00"],
        "wind_speed_10m": [8.0, 9.0, 12.0],
        "wind_direction_10m": [95.0, 97.0, 100.0],
    },
    "daily": {
        "time": ["2026-08-21"],
        "sunrise": ["2026-08-21T06:45"],
        "sunset": ["2026-08-21T18:20"],
    },
}


def test_combina_marine_y_clima_en_horas():
    por_dia = _combinar(MARINE, CLIMA)
    horas = por_dia[date(2026, 8, 21)]
    assert len(horas) == 3
    assert horas[1].swell_altura == 1.9
    assert horas[1].viento_kmh == 9.0
    assert horas[1].viento_direccion == 97.0


def test_marca_las_horas_de_luz():
    por_dia = _combinar(MARINE, CLIMA)
    horas = {h.t.hour: h for h in por_dia[date(2026, 8, 21)]}
    assert horas[5].es_de_dia is False    # antes del amanecer 06:45
    assert horas[9].es_de_dia is True     # pleno dia
    assert horas[22].es_de_dia is False   # despues del ocaso 18:20


def test_descarta_horas_con_datos_nulos():
    marine = {"hourly": dict(MARINE["hourly"])}
    marine["hourly"]["swell_wave_period"] = [14.0, None, 13.8]
    por_dia = _combinar(marine, CLIMA)
    assert len(por_dia[date(2026, 8, 21)]) == 2


def test_falla_si_faltan_campos_del_marine():
    with pytest.raises(ErrorDatos, match="swell_wave_height"):
        _combinar({"hourly": {"time": []}}, CLIMA)


def test_falla_si_las_series_no_alinean():
    clima = {"hourly": {"time": ["2026-08-21T05:00"],
                        "wind_speed_10m": [8.0], "wind_direction_10m": [95.0]},
             "daily": CLIMA["daily"]}
    with pytest.raises(ErrorDatos, match="alinea"):
        _combinar(MARINE, clima)


def test_falla_si_no_hay_datos_diarios_de_sol():
    clima = {"hourly": CLIMA["hourly"], "daily": {"time": [], "sunrise": [], "sunset": []}}
    with pytest.raises(ErrorDatos, match="sol"):
        _combinar(MARINE, clima)


class _RespuestaFalsa:
    """Simula una requests.Response con el subset que usa _pedir."""

    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class _SesionErrorSemantico:
    """Open-Meteo responde 200 pero con {'error': true}, siempre."""

    def __init__(self, payload):
        self.payload = payload
        self.llamadas = 0

    def get(self, url, params=None, timeout=None):
        self.llamadas += 1
        return _RespuestaFalsa(self.payload)


class _SesionFlaky:
    """Falla con un error de red las primeras `fallos` veces, despues responde bien."""

    def __init__(self, fallos, payload):
        self.fallos = fallos
        self.payload = payload
        self.llamadas = 0

    def get(self, url, params=None, timeout=None):
        self.llamadas += 1
        if self.llamadas <= self.fallos:
            raise requests.exceptions.ConnectionError("no hay red")
        return _RespuestaFalsa(self.payload)


def test_error_semantico_no_reintenta(monkeypatch):
    monkeypatch.setattr("surf.fetch.time.sleep", lambda s: None)
    sesion = _SesionErrorSemantico({"error": True, "reason": "coordenadas invalidas"})
    with pytest.raises(ErrorDatos, match="devolvio error"):
        _pedir("http://x", {}, sesion=sesion)
    assert sesion.llamadas == 1


def test_fallo_de_red_reintenta_y_se_recupera(monkeypatch):
    monkeypatch.setattr("surf.fetch.time.sleep", lambda s: None)
    sesion = _SesionFlaky(fallos=2, payload={"ok": True})
    datos = _pedir("http://x", {}, sesion=sesion)
    assert datos == {"ok": True}
    assert sesion.llamadas == 3


class _RespuestaJsonInvalido:
    """Simula un cuerpo que no es JSON (p.ej. un proxy devolviendo HTML)."""

    def raise_for_status(self):
        pass

    def json(self):
        raise ValueError("Expecting value: line 1 column 1 (char 0)")


class _SesionJsonSiempreInvalido:
    def __init__(self):
        self.llamadas = 0

    def get(self, url, params=None, timeout=None):
        self.llamadas += 1
        return _RespuestaJsonInvalido()


def test_json_malformado_reintenta_y_termina_en_error_datos(monkeypatch):
    monkeypatch.setattr("surf.fetch.time.sleep", lambda s: None)
    sesion = _SesionJsonSiempreInvalido()
    with pytest.raises(ErrorDatos, match="fallaron"):
        _pedir("http://x", {}, sesion=sesion)
    assert sesion.llamadas == 3


def test_combinar_multimodelo_arma_una_hora_por_modelo():
    from surf.fetch import _combinar_multimodelo

    marine = {"hourly": {
        "time": ["2026-08-21T09:00"],
        "swell_wave_height_marine_best_match": [1.8],
        "swell_wave_period_marine_best_match": [14.0],
        "swell_wave_direction_marine_best_match": [200.0],
        "swell_wave_height_gwam": [1.6],
        "swell_wave_period_gwam": [13.5],
        "swell_wave_direction_gwam": [198.0],
    }}
    clima = {"hourly": {
        "time": ["2026-08-21T09:00"],
        "wind_speed_10m_gfs_seamless": [14.9],
        "wind_direction_10m_gfs_seamless": [95.0],
        "wind_speed_10m_icon_seamless": [7.0],
        "wind_direction_10m_icon_seamless": [97.0],
    }, "daily": {"time": ["2026-08-21"], "sunrise": ["2026-08-21T06:45"],
                 "sunset": ["2026-08-21T18:20"]}}

    por_dia = _combinar_multimodelo(
        marine, clima, ["best_match", "gwam"], ["gfs_seamless", "icon_seamless"])
    hmm = por_dia[date(2026, 8, 21)][0]
    assert len(hmm.por_modelo) == 2
    assert hmm.es_de_dia is True


def test_combinar_multimodelo_falla_si_no_hay_ningun_modelo():
    from surf.fetch import _combinar_multimodelo

    marine = {"hourly": {"time": ["2026-08-21T09:00"]}}
    clima = {"hourly": {"time": ["2026-08-21T09:00"]},
             "daily": {"time": ["2026-08-21"], "sunrise": ["2026-08-21T06:45"],
                       "sunset": ["2026-08-21T18:20"]}}
    with pytest.raises(ErrorDatos, match="ningun modelo"):
        _combinar_multimodelo(marine, clima, ["best_match"], ["gfs_seamless"])


def _marine_multi(series: dict) -> dict:
    """Arma una respuesta marine con una columna por modelo.

    `series` es {modelo: [(altura, periodo, direccion), ...]}.
    """
    n = len(next(iter(series.values())))
    hourly = {"time": [f"2026-08-21T{9 + i:02d}:00" for i in range(n)]}
    for modelo, filas in series.items():
        hourly[f"swell_wave_height_{modelo}"] = [f[0] for f in filas]
        hourly[f"swell_wave_period_{modelo}"] = [f[1] for f in filas]
        hourly[f"swell_wave_direction_{modelo}"] = [f[2] for f in filas]
    return {"hourly": hourly}


def _clima_multi(modelos: list[str], n: int) -> dict:
    hourly = {"time": [f"2026-08-21T{9 + i:02d}:00" for i in range(n)]}
    for m in modelos:
        hourly[f"wind_speed_10m_{m}"] = [7.0] * n
        hourly[f"wind_direction_10m_{m}"] = [320.0] * n
    return {"hourly": hourly,
            "daily": {"time": ["2026-08-21"], "sunrise": ["2026-08-21T06:45"],
                      "sunset": ["2026-08-21T18:20"]}}


def test_dos_modelos_de_olas_identicos_cuentan_como_una_sola_fuente():
    """Critical de la Tarea 11: best_match de la Marine API ES
    meteofrance_wave. Dos series identicas no pueden ser dos votos, o el
    consenso de '2 de 3' se convierte en una sola fuente votando dos veces."""
    from surf.fetch import _combinar_multimodelo

    filas = [(1.8, 14.0, 200.0), (1.9, 14.2, 202.0)]
    marine = _marine_multi({"clonado": list(filas), "gwam": [(1.2, 9.0, 190.0),
                                                            (1.3, 9.2, 191.0)],
                            "original": list(filas)})
    clima = _clima_multi(["gfs_seamless", "icon_seamless", "ecmwf_ifs025"], 2)

    por_dia = _combinar_multimodelo(
        marine, clima, ["clonado", "gwam", "original"],
        ["gfs_seamless", "icon_seamless", "ecmwf_ifs025"])
    hmm = por_dia[date(2026, 8, 21)][0]
    assert len(hmm.por_modelo) == 2, (
        f"series duplicadas contadas dos veces: {sorted(hmm.por_modelo)}")
    assert not any(n.startswith("original") for n in hmm.por_modelo)


def test_altura_cero_se_trata_como_hueco_de_cobertura():
    """ncep_gfswave025 devuelve 0.0/0.0/0 en 5 de los 13 spots: es una celda
    de grilla enmascarada como tierra, no mar planchado. Verificado contra la
    API real. Un 0.0 no puede votar como si fuera un dato."""
    from surf.fetch import _combinar_multimodelo

    marine = _marine_multi({
        "gwam": [(1.8, 14.0, 200.0), (1.9, 14.2, 202.0)],
        "ncep_gfswave025": [(0.0, 0.0, 0.0), (0.0, 0.0, 0.0)],
    })
    clima = _clima_multi(["gfs_seamless", "icon_seamless"], 2)

    por_dia = _combinar_multimodelo(
        marine, clima, ["gwam", "ncep_gfswave025"],
        ["gfs_seamless", "icon_seamless"])
    hmm = por_dia[date(2026, 8, 21)][0]
    assert len(hmm.por_modelo) == 1
    assert not any("ncep" in n for n in hmm.por_modelo)


def test_altura_cero_no_descarta_las_horas_con_dato_real_del_mismo_modelo():
    from surf.fetch import _combinar_multimodelo

    marine = _marine_multi({
        "gwam": [(1.8, 14.0, 200.0), (1.9, 14.2, 202.0)],
        "ncep_gfswave025": [(0.0, 0.0, 0.0), (1.5, 13.0, 198.0)],
    })
    clima = _clima_multi(["gfs_seamless", "icon_seamless"], 2)

    por_dia = _combinar_multimodelo(
        marine, clima, ["gwam", "ncep_gfswave025"],
        ["gfs_seamless", "icon_seamless"])
    horas = por_dia[date(2026, 8, 21)]
    assert len(horas[0].por_modelo) == 1
    assert len(horas[1].por_modelo) == 2


def test_combinar_multimodelo_usa_sunrise_sufijado_por_modelo():
    # Open-Meteo tambien sufija sunrise/sunset por modelo cuando se pide
    # "models" en la Forecast API (no solo las columnas horarias).
    from surf.fetch import _combinar_multimodelo

    marine = {"hourly": {
        "time": ["2026-08-21T09:00"],
        "swell_wave_height_marine_best_match": [1.8],
        "swell_wave_period_marine_best_match": [14.0],
        "swell_wave_direction_marine_best_match": [200.0],
    }}
    clima = {"hourly": {
        "time": ["2026-08-21T09:00"],
        "wind_speed_10m_gfs_seamless": [14.9],
        "wind_direction_10m_gfs_seamless": [95.0],
    }, "daily": {
        "time": ["2026-08-21"],
        "sunrise_gfs_seamless": ["2026-08-21T06:45"],
        "sunset_gfs_seamless": ["2026-08-21T18:20"],
    }}

    por_dia = _combinar_multimodelo(
        marine, clima, ["best_match"], ["gfs_seamless"])
    hmm = por_dia[date(2026, 8, 21)][0]
    assert len(hmm.por_modelo) == 1
    assert hmm.es_de_dia is True


# --- punto de oleaje separado del punto de viento ---------------------------

class _SesionEspia:
    """Registra los params de cada GET para poder afirmar que endpoint recibio
    que coordenada."""

    def __init__(self):
        self.llamadas = []

    def get(self, url, params=None, timeout=None):
        self.llamadas.append((url, dict(params or {})))
        horas = ["2026-08-21T09:00", "2026-08-21T10:00"]
        if "marine" in url:
            cuerpo = {"hourly": {"time": horas}}
            for i, m in enumerate(("gwam", "meteofrance_wave", "ncep_gfswave025")):
                cuerpo["hourly"][f"swell_wave_height_{m}"] = [1.8 + i * 0.1] * 2
                cuerpo["hourly"][f"swell_wave_period_{m}"] = [14.0 + i] * 2
                cuerpo["hourly"][f"swell_wave_direction_{m}"] = [200.0 + i] * 2
        else:
            cuerpo = {"hourly": {"time": horas},
                      "daily": {"time": ["2026-08-21"],
                                "sunrise_gfs_seamless": ["2026-08-21T06:45"],
                                "sunset_gfs_seamless": ["2026-08-21T18:20"]}}
            for i, m in enumerate(("gfs_seamless", "icon_seamless", "ecmwf_ifs025")):
                cuerpo["hourly"][f"wind_speed_10m_{m}"] = [8.0 + i] * 2
                cuerpo["hourly"][f"wind_direction_10m_{m}"] = [95.0 + i] * 2
        return _RespuestaEspia(cuerpo)


class _RespuestaEspia:
    def __init__(self, cuerpo):
        self._cuerpo = cuerpo

    def raise_for_status(self):
        return None

    def json(self):
        return self._cuerpo


def _spot_partido():
    from surf.spots import Spot, Swell
    return Spot(id="partido", nombre="Partido", pais="UY", lat=-34.92, lon=-54.85,
                tipo="point_break", costa_mira=165,
                swell=Swell(ventana=(135, 225), ideal=180, min_altura=1.0,
                            max_altura=3.0, rango_ideal=(1.7, 2.6), min_periodo=8),
                viento_ideal=337, temporada=[4], url_surfforecast="http://x",
                fuentes=["t"], confianza="media",
                lat_mar=-35.094, lon_mar=-54.793)


def test_el_oleaje_se_pide_mar_adentro_y_el_viento_en_la_playa():
    """El punto desplazado corrige la celda de grilla del modelo de olas, pero
    el viento a 20 km de la costa es otro viento (medido: +7 a +14 km/h y sin
    horas glassy). Cada endpoint tiene que recibir su propia coordenada."""
    from surf.fetch import obtener_horas_multimodelo
    sesion = _SesionEspia()
    obtener_horas_multimodelo(_spot_partido(), dias=1, sesion=sesion)

    marine = [p for u, p in sesion.llamadas if "marine" in u]
    clima = [p for u, p in sesion.llamadas if "marine" not in u]
    assert marine and clima
    assert (marine[0]["latitude"], marine[0]["longitude"]) == (-35.094, -54.793)
    assert (clima[0]["latitude"], clima[0]["longitude"]) == (-34.92, -54.85)


def test_sin_desplazamiento_los_dos_endpoints_reciben_el_mismo_punto():
    from surf.fetch import obtener_horas_multimodelo
    from dataclasses import replace
    sesion = _SesionEspia()
    spot = replace(_spot_partido(), lat_mar=None, lon_mar=None)
    obtener_horas_multimodelo(spot, dias=1, sesion=sesion)
    puntos = {(p["latitude"], p["longitude"]) for _, p in sesion.llamadas}
    assert puntos == {(-34.92, -54.85)}


def test_obtener_horas_simple_tambien_parte_el_punto():
    """El camino single-modelo no corre en produccion pero sigue existiendo:
    si no se parte igual, quien lo use mide el viento en alta mar."""
    from surf.fetch import obtener_horas
    sesion = _SesionEspiaSimple()
    obtener_horas(_spot_partido(), dias=1, sesion=sesion)
    marine = [p for u, p in sesion.llamadas if "marine" in u]
    clima = [p for u, p in sesion.llamadas if "marine" not in u]
    assert (marine[0]["latitude"], marine[0]["longitude"]) == (-35.094, -54.793)
    assert (clima[0]["latitude"], clima[0]["longitude"]) == (-34.92, -54.85)


class _SesionEspiaSimple(_SesionEspia):
    def get(self, url, params=None, timeout=None):
        self.llamadas.append((url, dict(params or {})))
        horas = ["2026-08-21T09:00", "2026-08-21T10:00"]
        if "marine" in url:
            cuerpo = {"hourly": {"time": horas, "swell_wave_height": [1.8, 1.9],
                                 "swell_wave_period": [14.0, 14.2],
                                 "swell_wave_direction": [200.0, 202.0]}}
        else:
            cuerpo = {"hourly": {"time": horas, "wind_speed_10m": [8.0, 9.0],
                                 "wind_direction_10m": [95.0, 97.0]},
                      "daily": {"time": ["2026-08-21"],
                                "sunrise": ["2026-08-21T06:45"],
                                "sunset": ["2026-08-21T18:20"]}}
        return _RespuestaEspia(cuerpo)


# --- Tarea 16: el viento se sirve desacoplado de las olas --------------------

def test_el_viento_viene_por_modelo_sin_emparejar():
    """El consenso de viento se calcula entre los modelos de viento. Para eso
    `_combinar_multimodelo` tiene que entregar la serie de cada modelo de
    viento por separado, no solo el que le toco a cada modelo de olas."""
    from surf.fetch import _combinar_multimodelo

    marine = _marine_multi({"gwam": [(1.8, 14.0, 200.0)],
                            "meteofrance_wave": [(1.6, 13.0, 198.0)],
                            "ncep_gfswave025": [(2.0, 15.0, 202.0)]})
    clima = {"hourly": {
        "time": ["2026-08-21T09:00"],
        "wind_speed_10m_gfs_seamless": [1.1],
        "wind_direction_10m_gfs_seamless": [320.0],
        "wind_speed_10m_icon_seamless": [7.2],
        "wind_direction_10m_icon_seamless": [318.0],
        "wind_speed_10m_ecmwf_ifs025": [21.6],
        "wind_direction_10m_ecmwf_ifs025": [316.0],
    }, "daily": {"time": ["2026-08-21"], "sunrise": ["2026-08-21T06:45"],
                 "sunset": ["2026-08-21T18:20"]}}

    por_dia = _combinar_multimodelo(
        marine, clima, ["gwam", "meteofrance_wave", "ncep_gfswave025"],
        ["gfs_seamless", "icon_seamless", "ecmwf_ifs025"])
    hmm = por_dia[date(2026, 8, 21)][0]

    assert set(hmm.viento_por_modelo) == {"gfs_seamless", "icon_seamless",
                                          "ecmwf_ifs025"}
    assert hmm.viento_por_modelo["ecmwf_ifs025"] == (21.6, 316.0)


def test_el_viento_por_modelo_omite_los_que_no_tienen_dato_a_esa_hora():
    """icon_seamless muere a las 177 h mientras las olas llegan a las 235 h.
    El modelo que no tiene dato no vota; los que si tienen, siguen votando."""
    from surf.fetch import _combinar_multimodelo

    marine = _marine_multi({"gwam": [(1.8, 14.0, 200.0), (1.8, 14.0, 200.0)],
                            "meteofrance_wave": [(1.6, 13.0, 198.0), (1.6, 13.0, 198.0)]})
    clima = {"hourly": {
        "time": ["2026-08-21T09:00", "2026-08-21T10:00"],
        "wind_speed_10m_gfs_seamless": [8.0, 8.0],
        "wind_direction_10m_gfs_seamless": [320.0, 320.0],
        "wind_speed_10m_icon_seamless": [7.0, None],
        "wind_direction_10m_icon_seamless": [318.0, None],
    }, "daily": {"time": ["2026-08-21"], "sunrise": ["2026-08-21T06:45"],
                 "sunset": ["2026-08-21T18:20"]}}

    por_dia = _combinar_multimodelo(
        marine, clima, ["gwam", "meteofrance_wave"],
        ["gfs_seamless", "icon_seamless"])
    horas = por_dia[date(2026, 8, 21)]
    assert set(horas[0].viento_por_modelo) == {"gfs_seamless", "icon_seamless"}
    assert set(horas[1].viento_por_modelo) == {"gfs_seamless"}
