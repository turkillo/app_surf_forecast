from datetime import date

import pytest

from surf.fetch import ErrorDatos, _combinar

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
