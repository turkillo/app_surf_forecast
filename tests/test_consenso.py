from datetime import date, datetime

import pytest

from surf.consenso import (MODELOS_OLAS, HoraMultiModelo, consensuar,
                           evaluar_dia_multimodelo)
from surf.score import Hora
from tests.test_score_gate import SPOT


def _hora(altura=2.0, periodo=13.0, viento=5.0, direccion=157.0, viento_dir=320.0,
          de_dia=True, t=None):
    return Hora(t=t or datetime(2026, 8, 21, 9), swell_altura=altura,
                swell_periodo=periodo, swell_direccion=direccion,
                viento_kmh=viento, viento_direccion=viento_dir, es_de_dia=de_dia)


def _hmm(modelos, hora=9):
    return HoraMultiModelo(t=datetime(2026, 8, 21, hora), es_de_dia=True,
                           por_modelo=modelos)


def _hmm_noche(modelos, hora=3):
    t = datetime(2026, 8, 21, hora)
    return HoraMultiModelo(
        t=t, es_de_dia=False,
        por_modelo={k: Hora(t=t, swell_altura=h.swell_altura,
                            swell_periodo=h.swell_periodo,
                            swell_direccion=h.swell_direccion,
                            viento_kmh=h.viento_kmh,
                            viento_direccion=h.viento_direccion,
                            es_de_dia=False)
                    for k, h in modelos.items()})


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


# --- Critical: MODELOS_OLAS no puede duplicar la misma fuente -----------------

def test_best_match_no_esta_entre_los_modelos_de_olas():
    """best_match de la Marine API ES meteofrance_wave: verificado contra la
    API real, identicos en altura, periodo y direccion en 72/72 horas y en los
    13 spots. Tenerlos a los dos es una sola fuente votando dos veces."""
    assert "best_match" not in MODELOS_OLAS


def test_hay_al_menos_dos_fuentes_de_olas_distintas():
    assert len(set(MODELOS_OLAS)) == len(MODELOS_OLAS)
    assert len(MODELOS_OLAS) >= 2


# --- Important: alta exige tres fuentes distintas -----------------------------

def test_dos_modelos_que_pasan_no_alcanzan_para_concordancia_alta():
    """Si Open-Meteo deja de servir un modelo quedan dos. Dos de dos no es
    'alta': nunca se consulto al tercero."""
    hmm = _hmm({"a": _hora(), "b": _hora()})
    _, nivel, n = consensuar(hmm, SPOT)
    assert n == 2
    assert nivel != "alta"
    assert nivel == "media"


def test_un_solo_modelo_que_pasa_no_da_concordancia_alta():
    hmm = _hmm({"a": _hora()})
    _, nivel, n = consensuar(hmm, SPOT)
    assert n == 1
    assert nivel != "alta"


def test_el_dia_con_dos_modelos_no_reporta_concordancia_alta():
    hmms = [_hmm({"a": _hora(), "b": _hora()}, hora=h) for h in (8, 9, 10)]
    d = evaluar_dia_multimodelo(hmms, SPOT, date(2026, 8, 21))
    assert d.es_bueno is True
    assert d.concordancia != "alta"


def test_el_dia_registra_que_modelos_respondieron():
    hmms = [_hmm({"gwam+gfs": _hora(), "mfwam+icon": _hora()}, hora=h)
            for h in (8, 9, 10)]
    d = evaluar_dia_multimodelo(hmms, SPOT, date(2026, 8, 21))
    assert set(d.modelos) == {"gwam+gfs", "mfwam+icon"}
    assert d.modelos_de_acuerdo == 2


# --- Important: el motivo de desacuerdo se traga las horas de noche ----------

def _dia_con_noche_y_periodo_corto():
    """12 horas de noche + horas de luz que fallan solo por periodo corto."""
    corta = _hora(periodo=6.0)
    noche = [_hmm_noche({"a": corta, "b": corta, "c": corta}, hora=h)
             for h in range(0, 6)] + [
             _hmm_noche({"a": corta, "b": corta, "c": corta}, hora=h)
             for h in range(19, 24)]
    dia = [_hmm({"a": corta, "b": corta, "c": corta}, hora=h)
           for h in range(8, 17)]
    return noche + dia


def test_las_horas_de_noche_no_definen_el_motivo_del_dia():
    d = evaluar_dia_multimodelo(_dia_con_noche_y_periodo_corto(), SPOT,
                                date(2026, 8, 21))
    assert d.es_bueno is False
    assert "período corto" in (d.motivo_principal or "")


def test_el_motivo_real_se_conserva_cuando_los_modelos_coinciden_en_el():
    """A las 3 AM los tres modelos coinciden perfectamente en que es de noche;
    llamar a eso 'los modelos no coinciden' es falso."""
    corta = _hora(periodo=6.0)
    hmms = [_hmm({"a": corta, "b": corta, "c": corta}, hora=h)
            for h in (8, 9, 10)]
    d = evaluar_dia_multimodelo(hmms, SPOT, date(2026, 8, 21))
    assert "no coinciden" not in (d.motivo_principal or "")
    assert "período corto" in (d.motivo_principal or "")


def test_el_motivo_real_se_conserva_aunque_cada_modelo_mida_distinto():
    """Los motivos llevan el valor medido adentro ("período corto (6.0s...)"),
    asi que tres modelos que rechazan por lo mismo producen tres strings
    distintos. Sigue siendo el mismo motivo, no un desacuerdo."""
    hmms = [_hmm({"a": _hora(periodo=6.0), "b": _hora(periodo=6.5),
                  "c": _hora(periodo=7.0)}, hora=h) for h in range(8, 17)]
    d = evaluar_dia_multimodelo(hmms, SPOT, date(2026, 8, 21))
    assert "no coinciden" not in (d.motivo_principal or "")
    assert "período corto" in (d.motivo_principal or "")


def test_un_dia_malo_por_periodo_corto_con_medidas_distintas_lo_ve_el_digest():
    from run import _cerca_del_umbral

    hmms = [_hmm({"a": _hora(periodo=6.0), "b": _hora(periodo=6.5),
                  "c": _hora(periodo=7.0)}, hora=h) for h in range(8, 17)]
    d = evaluar_dia_multimodelo(hmms, SPOT, date(2026, 8, 21))
    assert _cerca_del_umbral(d) is True


def test_motivos_de_distinta_categoria_si_son_desacuerdo():
    """Un modelo que ve poca altura y otro que ve viento onshore no estan
    coincidiendo: eso si es desacuerdo y hay que decirlo."""
    hmms = [_hmm({"a": _hora(altura=0.3), "b": _hora(viento=30.0, viento_dir=140.0),
                  "c": _hora(periodo=5.0)}, hora=h) for h in range(8, 17)]
    d = evaluar_dia_multimodelo(hmms, SPOT, date(2026, 8, 21))
    assert "no coinciden" in (d.motivo_principal or "")


def test_un_dia_malo_por_periodo_corto_lo_ve_el_digest():
    """El digest dominical es la red contra los falsos negativos. Si el motivo
    principal no matchea _cerca_del_umbral, el digest queda estructuralmente
    ciego."""
    from run import _cerca_del_umbral

    d = evaluar_dia_multimodelo(_dia_con_noche_y_periodo_corto(), SPOT,
                                date(2026, 8, 21))
    assert _cerca_del_umbral(d) is True


def test_un_dia_malo_por_direccion_lo_ve_el_digest():
    from run import _cerca_del_umbral

    fuera = _hora(direccion=10.0)
    hmms = [_hmm({"a": fuera, "b": fuera, "c": fuera}, hora=h)
            for h in range(8, 17)]
    d = evaluar_dia_multimodelo(hmms, SPOT, date(2026, 8, 21))
    assert "dirección" in (d.motivo_principal or "")
    assert _cerca_del_umbral(d) is True


def test_el_desacuerdo_real_sigue_reportandose_como_desacuerdo():
    malo = _hora(altura=0.3, periodo=5.0)
    hmms = [_hmm({"a": _hora(), "b": malo, "c": _hora(viento=30.0, viento_dir=140.0)},
                 hora=h) for h in range(8, 17)]
    d = evaluar_dia_multimodelo(hmms, SPOT, date(2026, 8, 21))
    assert "no coinciden" in (d.motivo_principal or "")
