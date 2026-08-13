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
