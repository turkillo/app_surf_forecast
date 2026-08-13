from datetime import date, timedelta

import pytest

from surf.alert import (DIAS_RETENCION_ESTADO, Ventana, decidir_alertas,
                        detectar_ventanas, estado_vacio)
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


# --- Regresion: detectar_ventanas no debe perder una racha cuando un dia
# malo la corta (bug encontrado en la revision de la Tarea 8, ronda 1). ---

def test_ventana_seguida_de_dia_malo_no_desaparece():
    v = detectar_ventanas([dia(21), dia(22), dia(23, bueno=False)])
    assert len(v) == 1
    assert v[0].desde == date(2026, 8, 21)
    assert v[0].hasta == date(2026, 8, 22)


def test_dos_ventanas_separadas_por_un_dia_malo_se_detectan_ambas():
    v = detectar_ventanas([dia(21), dia(22), dia(23, bueno=False), dia(24), dia(25)])
    assert len(v) == 2
    assert (v[0].desde, v[0].hasta) == (date(2026, 8, 21), date(2026, 8, 22))
    assert (v[1].desde, v[1].hasta) == (date(2026, 8, 24), date(2026, 8, 25))


# --- Resolucion de diseno (ronda 1): "extenderse" cubre crecer en cualquier
# direccion, no solo que "hasta" avance. Si el swell se adelanta y la ventana
# ahora arranca antes, tambien amerita re-alerta. ---

def test_realerta_si_la_ventana_se_extiende_hacia_atras():
    v1 = detectar_ventanas([dia(21), dia(22)])
    _, e1 = decidir_alertas(v1, estado_vacio(), date(2026, 8, 12))
    _, e2 = decidir_alertas(v1, e1, HOY)          # alerta aca (21-22)
    v2 = detectar_ventanas([dia(20), dia(21), dia(22)])
    a_alertar, _ = decidir_alertas(v2, e2, date(2026, 8, 14))
    assert len(a_alertar) == 1


# --- Regresion: cuando una ventana ancha ya alertada se parte en dos (un dia
# malo intermedio la corta), el pedazo que no cambio no debe perder su
# historial y volver a alertar como si fuera nuevo (bug encontrado en la
# revision de la Tarea 8, ronda 1). ---

def test_ventana_partida_en_dos_no_pierde_el_historial_del_pedazo_no_alertado():
    # Historial: chicama 21-25 con score 80, ya alertado una vez (dia 11).
    v_ancha = detectar_ventanas([dia(d, score=80) for d in range(21, 26)])
    _, e1 = decidir_alertas(v_ancha, estado_vacio(), date(2026, 8, 10))
    _, e2 = decidir_alertas(v_ancha, e1, date(2026, 8, 11))  # alerta aca (80)

    # El pronostico se refina: el dia 23 pasa a malo y la ventana se parte.
    # A (21-22) sube fuerte de score y re-alerta; B (24-25) no cambia.
    dias_partidos = [dia(21, score=97), dia(22, score=97), dia(23, bueno=False),
                     dia(24, score=80), dia(25, score=80)]
    v_partida = detectar_ventanas(dias_partidos)
    a_alertar_3, e3 = decidir_alertas(v_partida, e2, date(2026, 8, 12))
    assert [v.desde for v in a_alertar_3] == [date(2026, 8, 21)]  # solo A

    # Al dia siguiente, sin cambios: B no deberia alertar como si fuera nueva.
    a_alertar_4, _ = decidir_alertas(v_partida, e3, date(2026, 8, 13))
    assert a_alertar_4 == []


# --- Cierre del gap de cobertura detectado en la ronda 1: la purga por
# retencion (DIAS_RETENCION_ESTADO) nunca se ejercitaba con datos reales. ---

def test_la_purga_retiene_solo_lo_dentro_de_la_retencion():
    hoy = date(2026, 9, 30)
    corte = hoy - timedelta(days=DIAS_RETENCION_ESTADO)  # 2026-08-31
    vieja = {"spot_id": "chicama", "desde": "2026-08-20", "hasta": "2026-08-25",
             "score": 80.0, "fecha_alerta": "2026-08-25"}
    en_el_borde = {"spot_id": "chicama", "desde": "2026-08-28",
                   "hasta": corte.isoformat(), "score": 80.0,
                   "fecha_alerta": "2026-08-28"}
    reciente = {"spot_id": "mancora", "desde": "2026-09-10", "hasta": "2026-09-15",
                "score": 80.0, "fecha_alerta": "2026-09-10"}
    estado = {"ultima_corrida": "2026-09-29", "observadas": [],
             "alertadas": [vieja, en_el_borde, reciente]}

    _, limpio = decidir_alertas([], estado, hoy)

    assert vieja not in limpio["alertadas"]
    assert en_el_borde in limpio["alertadas"]
    assert reciente in limpio["alertadas"]
