from datetime import date, datetime

import pytest

from surf.consenso import (HoraMultiModelo, consensuar,
                           evaluar_dia_multimodelo)
from surf.score import Hora
from tests.test_score_gate import SPOT


def _hora(altura=2.0, periodo=13.0, viento=5.0, direccion=157.0, viento_dir=320.0):
    return Hora(t=datetime(2026, 8, 21, 9), swell_altura=altura,
                swell_periodo=periodo, swell_direccion=direccion,
                viento_kmh=viento, viento_direccion=viento_dir, es_de_dia=True)


def _hmm(modelos, hora=9):
    return HoraMultiModelo(t=datetime(2026, 8, 21, hora), es_de_dia=True,
                           por_modelo=modelos)


def test_los_tres_de_acuerdo_dan_concordancia_alta():
    hmm = _hmm({"a": _hora(), "b": _hora(), "c": _hora()})
    _, nivel, n = consensuar(hmm, SPOT)
    assert nivel == "alta"
    assert n == 3


def test_dos_de_tres_dan_concordancia_media():
    # El tercero ve viento onshore fuerte
    hmm = _hmm({"a": _hora(), "b": _hora(),
                "c": _hora(viento=30.0, viento_dir=140.0)})
    _, nivel, n = consensuar(hmm, SPOT)
    assert nivel == "media"
    assert n == 2


def test_uno_de_tres_da_concordancia_baja():
    malo = _hora(altura=0.3, periodo=5.0)
    hmm = _hmm({"a": _hora(), "b": malo, "c": malo})
    _, nivel, n = consensuar(hmm, SPOT)
    assert nivel == "baja"
    assert n == 1


def test_la_hora_consensuada_usa_la_mediana():
    hmm = _hmm({"a": _hora(altura=1.5), "b": _hora(altura=2.0),
                "c": _hora(altura=3.0)})
    hora, _, _ = consensuar(hmm, SPOT)
    assert hora.swell_altura == pytest.approx(2.0)


def test_la_mediana_ignora_el_modelo_desviado():
    # Un modelo dice 30 km/h de viento y los otros dos 5
    hmm = _hmm({"a": _hora(viento=5.0), "b": _hora(viento=5.0),
                "c": _hora(viento=30.0)})
    hora, _, _ = consensuar(hmm, SPOT)
    assert hora.viento_kmh == pytest.approx(5.0)


def test_un_solo_modelo_funciona_igual():
    hmm = _hmm({"a": _hora()})
    hora, nivel, n = consensuar(hmm, SPOT)
    assert n == 1
    assert hora.swell_altura == pytest.approx(2.0)


def test_la_hora_con_concordancia_baja_no_cuenta_para_el_dia():
    malo = _hora(altura=0.3, periodo=5.0)
    hmms = [_hmm({"a": _hora(), "b": malo, "c": malo}, hora=h)
            for h in (8, 9, 10)]
    d = evaluar_dia_multimodelo(hmms, SPOT, date(2026, 8, 21))
    assert d.es_bueno is False


def test_tres_horas_con_los_modelos_de_acuerdo_hacen_un_dia_bueno():
    hmms = [_hmm({"a": _hora(), "b": _hora(), "c": _hora()}, hora=h)
            for h in (8, 9, 10)]
    d = evaluar_dia_multimodelo(hmms, SPOT, date(2026, 8, 21))
    assert d.es_bueno is True
    assert d.concordancia == "alta"


def test_el_dia_reporta_la_peor_concordancia_de_su_bloque():
    disidente = _hora(viento=30.0, viento_dir=140.0)
    hmms = [
        _hmm({"a": _hora(), "b": _hora(), "c": _hora()}, hora=8),
        _hmm({"a": _hora(), "b": _hora(), "c": disidente}, hora=9),
        _hmm({"a": _hora(), "b": _hora(), "c": _hora()}, hora=10),
    ]
    d = evaluar_dia_multimodelo(hmms, SPOT, date(2026, 8, 21))
    assert d.es_bueno is True
    assert d.concordancia == "media"


def test_el_motivo_de_rechazo_por_desacuerdo_es_explicito():
    malo = _hora(altura=0.3, periodo=5.0)
    hmms = [_hmm({"a": _hora(), "b": malo, "c": malo}, hora=h) for h in (8, 9, 10)]
    d = evaluar_dia_multimodelo(hmms, SPOT, date(2026, 8, 21))
    assert "modelos" in (d.motivo_principal or "")
