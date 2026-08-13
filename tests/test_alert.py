from datetime import date

import pytest

from surf.alert import (Ventana, decidir_alertas, detectar_ventanas,
                        estado_vacio)
from surf.score import DiaEvaluado

HOY = date(2026, 8, 13)


def dia(d, bueno=True, score=80.0, spot="chicama"):
    return DiaEvaluado(fecha=date(2026, 8, d), spot_id=spot, es_bueno=bueno,
                       score=score if bueno else 0.0, horas_buenas=5 if bueno else 0,
                       bloque=None, resumen=None, motivo_principal=None)


def test_dos_dias_consecutivos_forman_ventana():
    v = detectar_ventanas([dia(21), dia(22)])
    assert len(v) == 1
    assert v[0].desde == date(2026, 8, 21)
    assert v[0].hasta == date(2026, 8, 22)


def test_un_dia_aislado_no_forma_ventana():
    assert detectar_ventanas([dia(21)]) == []


def test_dos_dias_buenos_separados_no_forman_ventana():
    assert detectar_ventanas([dia(21), dia(22, bueno=False), dia(23)]) == []


def test_la_ventana_toma_el_score_maximo_de_sus_dias():
    v = detectar_ventanas([dia(21, score=70), dia(22, score=94), dia(23, score=78)])
    assert v[0].score == 94.0


def test_ventanas_de_spots_distintos_no_se_mezclan():
    dias = [dia(21, spot="chicama"), dia(22, spot="chicama"),
            dia(21, spot="lobitos"), dia(22, spot="lobitos")]
    assert len(detectar_ventanas(dias)) == 2


def test_ventana_nueva_no_alerta_falta_persistencia():
    v = detectar_ventanas([dia(21), dia(22)])
    a_alertar, nuevo = decidir_alertas(v, estado_vacio(), HOY)
    assert a_alertar == []
    assert len(nuevo["observadas"]) == 1


def test_ventana_confirmada_ayer_si_alerta():
    v = detectar_ventanas([dia(21), dia(22)])
    _, estado = decidir_alertas(v, estado_vacio(), date(2026, 8, 12))
    a_alertar, _ = decidir_alertas(v, estado, HOY)
    assert len(a_alertar) == 1
    assert a_alertar[0].spot_id == "chicama"


def test_no_realerta_la_misma_ventana():
    v = detectar_ventanas([dia(21), dia(22)])
    _, e1 = decidir_alertas(v, estado_vacio(), date(2026, 8, 12))
    _, e2 = decidir_alertas(v, e1, HOY)          # alerta aca
    a_alertar, _ = decidir_alertas(v, e2, date(2026, 8, 14))
    assert a_alertar == []


def test_realerta_si_el_score_mejora_mucho():
    v1 = detectar_ventanas([dia(21, score=70), dia(22, score=70)])
    _, e1 = decidir_alertas(v1, estado_vacio(), date(2026, 8, 12))
    _, e2 = decidir_alertas(v1, e1, HOY)
    v2 = detectar_ventanas([dia(21, score=92), dia(22, score=92)])
    a_alertar, _ = decidir_alertas(v2, e2, date(2026, 8, 14))
    assert len(a_alertar) == 1


def test_realerta_si_la_ventana_se_extiende():
    v1 = detectar_ventanas([dia(21), dia(22)])
    _, e1 = decidir_alertas(v1, estado_vacio(), date(2026, 8, 12))
    _, e2 = decidir_alertas(v1, e1, HOY)
    v2 = detectar_ventanas([dia(21), dia(22), dia(23)])
    a_alertar, _ = decidir_alertas(v2, e2, date(2026, 8, 14))
    assert len(a_alertar) == 1


def test_la_ventana_que_corre_un_dia_sigue_siendo_la_misma():
    # Ayer se vio 21-22, hoy el modelo la muestra 20-22: es la misma ventana
    v1 = detectar_ventanas([dia(21), dia(22)])
    _, e1 = decidir_alertas(v1, estado_vacio(), date(2026, 8, 12))
    v2 = detectar_ventanas([dia(20), dia(21), dia(22)])
    a_alertar, _ = decidir_alertas(v2, e1, HOY)
    assert len(a_alertar) == 1  # alerta por persistencia, no la trata como nueva


def test_un_hueco_en_las_corridas_resetea_la_persistencia():
    # Si la ultima corrida fue hace 3 dias, no hay confirmacion valida
    v = detectar_ventanas([dia(21), dia(22)])
    _, estado = decidir_alertas(v, estado_vacio(), date(2026, 8, 9))
    a_alertar, _ = decidir_alertas(v, estado, HOY)
    assert a_alertar == []


def test_se_purgan_las_ventanas_ya_pasadas():
    v = detectar_ventanas([dia(21), dia(22)])
    _, estado = decidir_alertas(v, estado_vacio(), date(2026, 8, 12))
    _, limpio = decidir_alertas([], estado, date(2026, 9, 30))
    assert limpio["observadas"] == []
    assert limpio["alertadas"] == []
