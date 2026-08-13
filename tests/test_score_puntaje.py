import pytest

from surf.score import (factor_altura, factor_direccion, factor_periodo,
                        factor_viento, evaluar_hora)
from tests.test_score_gate import SPOT, hora


def test_altura_en_el_rango_ideal_da_uno():
    # rango_ideal = (1.5, 2.5)
    assert factor_altura(2.0, SPOT) == 1.0
    assert factor_altura(1.5, SPOT) == 1.0
    assert factor_altura(2.5, SPOT) == 1.0


def test_altura_en_el_minimo_da_el_piso():
    # min_altura = 1.0
    assert factor_altura(1.0, SPOT) == pytest.approx(0.4)


def test_altura_sube_lineal_hasta_el_rango_ideal():
    # Punto medio entre 1.0 y 1.5 -> punto medio entre 0.4 y 1.0
    assert factor_altura(1.25, SPOT) == pytest.approx(0.7)


def test_altura_baja_lineal_pasado_el_rango_ideal():
    # Punto medio entre 2.5 y 3.5 -> punto medio entre 1.0 y 0.4
    assert factor_altura(3.0, SPOT) == pytest.approx(0.7)


def test_periodo_en_el_minimo_da_cero():
    # min_periodo = 9
    assert factor_periodo(9.0, SPOT) == pytest.approx(0.0)


def test_periodo_de_dieciseis_da_uno():
    assert factor_periodo(16.0, SPOT) == pytest.approx(1.0)


def test_periodo_por_encima_de_dieciseis_topea_en_uno():
    assert factor_periodo(20.0, SPOT) == pytest.approx(1.0)


def test_periodo_intermedio_es_lineal():
    # Punto medio entre 9 y 16 es 12.5
    assert factor_periodo(12.5, SPOT) == pytest.approx(0.5)


def test_direccion_ideal_da_uno():
    assert factor_direccion(157, SPOT) == pytest.approx(1.0)


def test_direccion_en_el_borde_de_la_ventana_da_medio():
    # Ambos bordes de la ventana dan 0.5, independientemente de la simetria
    assert factor_direccion(SPOT.swell.ventana[0], SPOT) == pytest.approx(0.5)
    assert factor_direccion(SPOT.swell.ventana[1], SPOT) == pytest.approx(0.5)


def test_viento_glassy_da_uno():
    assert factor_viento(4.0, "onshore") == 1.0


def test_offshore_suave_da_uno():
    assert factor_viento(15.0, "offshore") == 1.0


def test_offshore_fuerte_degrada():
    # 20 -> 1.0, 35 -> 0.4; el punto medio 27.5 -> 0.7
    assert factor_viento(27.5, "offshore") == pytest.approx(0.7)


def test_cross_suave_da_cero_ochenta_y_cinco():
    assert factor_viento(10.0, "cross") == pytest.approx(0.85)


def test_onshore_tolerable_da_medio():
    assert factor_viento(7.0, "onshore") == pytest.approx(0.5)


def test_score_de_condiciones_perfectas_es_alto():
    r = evaluar_hora(hora(altura=2.0, periodo=16, direccion=157,
                          viento_kmh=4, viento_dir=320), SPOT)
    assert r.pasa is True
    assert r.score == pytest.approx(100.0)


def test_score_de_condiciones_apenas_suficientes_es_bajo():
    r = evaluar_hora(hora(altura=1.0, periodo=9.0, direccion=110,
                          viento_kmh=7, viento_dir=140), SPOT)
    assert r.pasa is True
    # 0.35*0.4 + 0.30*0.0 + 0.15*0.5 + 0.20*0.5 = 0.315
    assert r.score == pytest.approx(31.5)


def test_los_pesos_suman_uno():
    from surf.score import PESOS
    assert sum(PESOS.values()) == pytest.approx(1.0)


def test_direccion_asimetrica_izquierda_da_medio():
    # Ventana asimetrica: [210, 270], ideal 225. Distancia a 210 es 15, a 270 es 45.
    from surf.spots import Swell, Spot
    spot_asimetrico = Spot(
        id="test_asim_izq", nombre="Test Asimetrico Izq", pais="AR", lat=-38.15, lon=-57.68,
        tipo="point_break", costa_mira=140,
        swell=Swell(ventana=(210, 270), ideal=225, min_altura=1.0,
                    max_altura=3.5, rango_ideal=(1.5, 2.5), min_periodo=9),
        viento_ideal=315, temporada=[3, 4, 5, 6, 7, 8],
        url_surfforecast="http://x", fuentes=["test"], confianza="alta",
    )
    # El borde izquierdo (210) debe dar 0.5 con la formula por lado
    assert factor_direccion(210, spot_asimetrico) == pytest.approx(0.5)
    # El borde derecho (270) tambien debe dar 0.5
    assert factor_direccion(270, spot_asimetrico) == pytest.approx(0.5)


def test_direccion_asimetrica_derecha_da_medio():
    # Ventana asimetrica: [173, 247], ideal 202. Distancia a 173 es 29, a 247 es 45.
    from surf.spots import Swell, Spot
    spot_asimetrico = Spot(
        id="test_asim_der", nombre="Test Asimetrico Der", pais="AR", lat=-38.15, lon=-57.68,
        tipo="point_break", costa_mira=140,
        swell=Swell(ventana=(173, 247), ideal=202, min_altura=1.0,
                    max_altura=3.5, rango_ideal=(1.5, 2.5), min_periodo=9),
        viento_ideal=315, temporada=[3, 4, 5, 6, 7, 8],
        url_surfforecast="http://x", fuentes=["test"], confianza="alta",
    )
    # El borde izquierdo (173) debe dar 0.5 con la formula por lado
    assert factor_direccion(173, spot_asimetrico) == pytest.approx(0.5)
    # El borde derecho (247) tambien debe dar 0.5
    assert factor_direccion(247, spot_asimetrico) == pytest.approx(0.5)


def test_factor_altura_clampea_fuera_de_rango():
    # Valores extremos fuera del rango deben quedar clampeados
    assert factor_altura(-100.0, SPOT) >= 0.4
    assert factor_altura(-100.0, SPOT) <= 1.0
    assert factor_altura(1000.0, SPOT) >= 0.4
    assert factor_altura(1000.0, SPOT) <= 1.0


def test_factor_viento_offshore_clampea_fuera_de_rango():
    # Valores extremos fuera del rango deben quedar clampeados
    assert factor_viento(1000.0, "offshore") >= 0.4
    assert factor_viento(1000.0, "offshore") <= 1.0


def test_factor_viento_cross_clampea_fuera_de_rango():
    # Valores extremos fuera del rango deben quedar clampeados
    assert factor_viento(1000.0, "cross") >= 0.3
    assert factor_viento(1000.0, "cross") <= 1.0
