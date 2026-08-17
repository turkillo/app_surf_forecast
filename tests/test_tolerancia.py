"""Banda de tolerancia sobre los umbrales del gate.

Pedido explicito del usuario: "un +/- porcentual de error para los modelos,
para no ser tan deterministico". Un criterio que se cumple raspando --dentro
de TOLERANCIA_UMBRAL del umbral-- cuenta como cumplido, pero marca el dia, y
esa marca tiene que llegar al mensaje.

La banda NO es un dial de volumen: cada test de aca fija un limite de hasta
donde llega, y `test_backtest.py` fija que el volumen no se dispare.
"""
from datetime import date, datetime

import pytest

from surf.alert import Ventana
from surf.consenso import HoraMultiModelo, evaluar_dia_multimodelo
from surf.notify import formatear_alerta
from surf.score import TOLERANCIA_UMBRAL, Hora, evaluar_hora
from tests.test_score_gate import SPOT, hora

SW = SPOT.swell


def test_la_tolerancia_es_una_constante_nombrada_y_moderada():
    """Tiene que quedar por debajo del 14.3%: a partir de ahi la banda del
    offshore (maximo 35 km/h) se tragaria los 40 km/h que `test_score_gate`
    exige rechazar, y ese test es la definicion del gate."""
    assert 0.0 < TOLERANCIA_UMBRAL < 0.143


# --- pisos: altura y periodo -------------------------------------------------

def test_una_altura_que_raspa_el_minimo_pasa_y_queda_marcada():
    apenas = SW.min_altura * (1 - TOLERANCIA_UMBRAL / 2)
    r = evaluar_hora(hora(altura=apenas), SPOT)
    assert r.pasa is True
    assert r.al_limite is True


def test_una_altura_fuera_de_la_banda_sigue_sin_pasar():
    lejos = SW.min_altura * (1 - TOLERANCIA_UMBRAL * 2)
    r = evaluar_hora(hora(altura=lejos), SPOT)
    assert r.pasa is False
    assert "altura" in r.motivo_rechazo


def test_una_altura_holgada_no_queda_marcada():
    r = evaluar_hora(hora(altura=2.0), SPOT)
    assert r.pasa is True
    assert r.al_limite is False


def test_el_borde_exacto_de_la_banda_todavia_pasa():
    borde = SW.min_altura * (1 - TOLERANCIA_UMBRAL)
    assert evaluar_hora(hora(altura=borde), SPOT).pasa is True


def test_un_periodo_que_raspa_el_minimo_pasa_y_queda_marcado():
    apenas = SW.min_periodo * (1 - TOLERANCIA_UMBRAL / 2)
    r = evaluar_hora(hora(periodo=apenas), SPOT)
    assert r.pasa is True
    assert r.al_limite is True


# --- techos de viento --------------------------------------------------------

def test_un_cross_que_raspa_el_maximo_pasa_y_queda_marcado():
    from surf.score import CROSS_MAX_KMH
    apenas = CROSS_MAX_KMH * (1 + TOLERANCIA_UMBRAL / 2)
    r = evaluar_hora(hora(viento_kmh=apenas, viento_dir=230), SPOT)
    assert r.clase_viento == "cross"
    assert r.pasa is True
    assert r.al_limite is True


def test_un_onshore_que_raspa_el_maximo_pasa_y_queda_marcado():
    from surf.score import ONSHORE_MAX_KMH
    apenas = ONSHORE_MAX_KMH * (1 + TOLERANCIA_UMBRAL / 2)
    r = evaluar_hora(hora(viento_kmh=apenas, viento_dir=140), SPOT)
    assert r.clase_viento == "onshore"
    assert r.pasa is True
    assert r.al_limite is True


# --- donde la banda NO se aplica ---------------------------------------------

def test_el_tamanio_que_cierra_el_spot_no_tiene_banda():
    """Asimetria deliberada. La banda existe para no PERDER un buen dia por el
    error del modelo; aflojar max_altura hace lo contrario: manda al usuario a
    un mar que cierra. El error del modelo no puede jugar a favor del riesgo."""
    apenas = SW.max_altura * (1 + TOLERANCIA_UMBRAL / 2)
    r = evaluar_hora(hora(altura=apenas), SPOT)
    assert r.pasa is False
    assert "cierra" in r.motivo_rechazo


def test_la_noche_no_tiene_banda():
    """La luz es astronomia, no una estimacion de un modelo."""
    assert evaluar_hora(hora(de_dia=False), SPOT).pasa is False


# --- la marca llega al dia y al mensaje --------------------------------------

def _hmm(hora_del_dia, altura, dia=21):
    t = datetime(2026, 8, dia, hora_del_dia)
    h = Hora(t=t, swell_altura=altura, swell_periodo=13.0, swell_direccion=157.0,
             viento_kmh=5.0, viento_direccion=320.0, es_de_dia=True)
    return HoraMultiModelo(t=t, es_de_dia=True,
                           por_modelo={"a": h, "b": h, "c": h})


def _dia(altura, d=21):
    apenas = [_hmm(h, altura, dia=d) for h in (8, 9, 10)]
    return evaluar_dia_multimodelo(apenas, SPOT, date(2026, 8, d))


def test_el_dia_que_paso_raspando_lo_dice():
    d = _dia(SW.min_altura * (1 - TOLERANCIA_UMBRAL / 2))
    assert d.es_bueno is True
    assert d.al_limite is True


def test_el_dia_holgado_no_queda_marcado():
    d = _dia(2.0)
    assert d.es_bueno is True
    assert d.al_limite is False


def test_el_mensaje_avisa_que_el_dia_paso_al_limite():
    dias = (_dia(SW.min_altura * (1 - TOLERANCIA_UMBRAL / 2), d=21),
            _dia(2.0, d=22))
    v = Ventana(spot_id=SPOT.id, desde=date(2026, 8, 21), hasta=date(2026, 8, 22),
                dias=dias, score=max(x.score for x in dias))
    m = formatear_alerta(v, SPOT)
    assert "al límite" in m
    # y tiene que decir cual: la marca va en la linea del dia que raspo
    lineas = [ln for ln in m.split("\n") if "m @ " in ln]
    assert "al límite" in lineas[0]
    assert "al límite" not in lineas[1]


def test_una_ventana_holgada_no_habla_de_limites():
    dias = (_dia(2.0, d=21), _dia(2.0, d=22))
    v = Ventana(spot_id=SPOT.id, desde=date(2026, 8, 21), hasta=date(2026, 8, 22),
                dias=dias, score=87.0)
    assert "al límite" not in formatear_alerta(v, SPOT)
