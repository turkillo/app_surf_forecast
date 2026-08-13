from datetime import date, datetime

import pytest

from surf.score import Hora, evaluar_dia
from tests.test_score_gate import SPOT

FECHA = date(2026, 8, 21)


def h(hora_del_dia, buena=True, de_dia=True):
    """Hora buena o mala segun el flag, en el horario indicado."""
    if buena:
        return Hora(t=datetime(2026, 8, 21, hora_del_dia), swell_altura=2.0,
                    swell_periodo=13.0, swell_direccion=157.0, viento_kmh=5.0,
                    viento_direccion=320.0, es_de_dia=de_dia)
    return Hora(t=datetime(2026, 8, 21, hora_del_dia), swell_altura=0.5,
                swell_periodo=5.0, swell_direccion=157.0, viento_kmh=25.0,
                viento_direccion=140.0, es_de_dia=de_dia)


def test_tres_horas_buenas_consecutivas_hacen_un_dia_bueno():
    horas = [h(8), h(9), h(10)]
    d = evaluar_dia(horas, SPOT, FECHA)
    assert d.es_bueno is True
    assert d.horas_buenas == 3


def test_dos_horas_buenas_consecutivas_no_alcanzan():
    horas = [h(8), h(9), h(10, buena=False)]
    d = evaluar_dia(horas, SPOT, FECHA)
    assert d.es_bueno is False


def test_tres_horas_buenas_no_consecutivas_no_alcanzan():
    # Buenas a las 8, 10 y 12 pero cortadas: no es una sesion
    horas = [h(8), h(9, buena=False), h(10), h(11, buena=False), h(12)]
    d = evaluar_dia(horas, SPOT, FECHA)
    assert d.es_bueno is False


def test_el_bloque_reportado_es_el_de_mejor_score():
    # Bloque de la manana flojo, bloque de la tarde perfecto
    flojas = [Hora(t=datetime(2026, 8, 21, x), swell_altura=1.1,
                   swell_periodo=9.5, swell_direccion=120.0, viento_kmh=7.0,
                   viento_direccion=230.0, es_de_dia=True) for x in (7, 8, 9)]
    buenas = [h(x) for x in (15, 16, 17)]
    d = evaluar_dia(flojas + buenas, SPOT, FECHA)
    assert d.es_bueno is True
    assert d.bloque[0].hour == 15
    assert d.bloque[1].hour == 17


def test_dia_sin_horas_de_luz_buenas_no_es_bueno():
    horas = [h(3, de_dia=False), h(4, de_dia=False), h(5, de_dia=False)]
    d = evaluar_dia(horas, SPOT, FECHA)
    assert d.es_bueno is False


def test_dia_malo_reporta_el_motivo_mas_frecuente():
    horas = [h(x, buena=False) for x in (8, 9, 10)]
    d = evaluar_dia(horas, SPOT, FECHA)
    assert d.es_bueno is False
    assert d.motivo_principal is not None


def test_el_resumen_trae_las_condiciones_del_mejor_bloque():
    d = evaluar_dia([h(8), h(9), h(10)], SPOT, FECHA)
    assert d.resumen["altura"] == pytest.approx(2.0)
    assert d.resumen["periodo"] == pytest.approx(13.0)
    assert d.resumen["viento_kmh"] == pytest.approx(5.0)


def test_dia_malo_no_trae_resumen_ni_bloque():
    d = evaluar_dia([h(8, buena=False)], SPOT, FECHA)
    assert d.bloque is None
    assert d.resumen is None


def test_lista_vacia_no_rompe():
    d = evaluar_dia([], SPOT, FECHA)
    assert d.es_bueno is False
    assert d.score == 0.0
