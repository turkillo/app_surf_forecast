import pytest
from surf.geo import angular_diff, clasificar_viento, en_ventana, rumbo_a_texto


def test_angular_diff_directo():
    assert angular_diff(10, 40) == 30


def test_angular_diff_cruza_el_cero():
    # 350 y 10 estan a 20 grados, no a 340
    assert angular_diff(350, 10) == 20


def test_angular_diff_es_simetrica():
    assert angular_diff(10, 350) == 20


def test_angular_diff_nunca_supera_180():
    assert angular_diff(0, 270) == 90


def test_offshore_sopla_desde_tierra():
    # Playa que mira al SE (140). El offshore viene del NW (320).
    assert clasificar_viento(320, 140) == "offshore"


def test_offshore_tolera_45_grados():
    # 290 esta a 30 grados de 320 -> sigue siendo offshore
    assert clasificar_viento(290, 140) == "offshore"


def test_cross_a_noventa_grados():
    # 230 esta a 90 grados de 320 -> cross
    assert clasificar_viento(230, 140) == "cross"


def test_onshore_viene_del_mar():
    # Playa mira al SE (140): el viento del SE es onshore
    assert clasificar_viento(140, 140) == "onshore"


def test_clasificar_viento_en_chile():
    # Buchupureo mira al WNW (290). Offshore viene del ESE (110).
    assert clasificar_viento(110, 290) == "offshore"
    assert clasificar_viento(290, 290) == "onshore"


def test_en_ventana_caso_simple():
    assert en_ventana(157, (110, 200)) is True
    assert en_ventana(90, (110, 200)) is False
    assert en_ventana(250, (110, 200)) is False


def test_en_ventana_incluye_los_bordes():
    assert en_ventana(110, (110, 200)) is True
    assert en_ventana(200, (110, 200)) is True


def test_en_ventana_cruza_el_cero():
    # Ventana del NW al NE pasando por el N
    assert en_ventana(350, (300, 60)) is True
    assert en_ventana(10, (300, 60)) is True
    assert en_ventana(180, (300, 60)) is False


def test_rumbo_a_texto():
    assert rumbo_a_texto(0) == "N"
    assert rumbo_a_texto(90) == "E"
    assert rumbo_a_texto(180) == "S"
    assert rumbo_a_texto(270) == "W"
    assert rumbo_a_texto(315) == "NW"
    assert rumbo_a_texto(157) == "SSE"


def test_rumbo_a_texto_envuelve_en_360():
    assert rumbo_a_texto(359) == "N"
