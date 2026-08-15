"""Energia del swell en kJ, la magnitud que publica surf-forecast.

La constante se ajusto contra lecturas reales de surf-forecast. Estos tests
la fijan contra esas lecturas: si alguien cambia la constante, tienen que
fallar mostrando cuanto se aparta de la fuente.
"""
from datetime import date, datetime

import pytest

from surf.alert import detectar_ventanas
from surf.notify import formatear_alerta
from surf.score import DiaEvaluado, energia_kj
from tests.test_score_gate import SPOT

# Lecturas reales de surf-forecast del 2026-08-14: (altura m, periodo s, energia kJ).
# Tres spots distintos, para que el test no dependa de la particularidad de uno.
LECTURAS = [
    # chapadmalal
    (0.7, 8, 64), (1.0, 6, 69), (1.1, 7, 121), (1.0, 9, 155), (0.9, 9, 132),
    # la_barra
    (1.2, 6, 95), (1.6, 6, 190), (1.6, 7, 272), (2.1, 10, 846),
    # praia_do_rosa
    (1.4, 12, 541), (2.2, 8, 545), (2.1, 8, 517),
]


@pytest.mark.parametrize("altura,periodo,esperado", LECTURAS)
def test_reproduce_la_energia_de_surfforecast(altura, periodo, esperado):
    """Dentro del 20%: surf-forecast redondea altura y periodo al publicarlos,
    y un redondeo de 0.05 m sobre 1 m ya mueve la energia un 10% porque va
    con el cuadrado."""
    calculado = energia_kj(altura, periodo)
    error = abs(calculado - esperado) / esperado
    assert error < 0.20, (
        f"{altura}m @ {periodo}s: calculado {calculado:.0f} kJ, "
        f"surf-forecast {esperado} kJ, error {error*100:.0f}%"
    )


def test_el_error_medio_contra_surfforecast_es_chico():
    """El promedio sobre las 12 lecturas tiene que ser mejor que cada una
    suelta: los errores individuales vienen del redondeo y se compensan."""
    errores = [abs(energia_kj(a, p) - e) / e for a, p, e in LECTURAS]
    assert sum(errores) / len(errores) < 0.10


def test_escala_con_el_cuadrado_de_la_altura():
    assert energia_kj(2.0, 10) == pytest.approx(4 * energia_kj(1.0, 10))


def test_escala_con_el_cuadrado_del_periodo():
    assert energia_kj(1.0, 20) == pytest.approx(4 * energia_kj(1.0, 10))


def test_un_mar_mas_grande_pero_corto_puede_tener_mas_energia_y_peor_score():
    """El dato de energia no contradice al score: miden cosas distintas.
    2.5m @ 8s tiene mas energia que 1.5m @ 12s, y es peor ola para surfear."""
    assert energia_kj(2.5, 8) > energia_kj(1.5, 12)


def _dia(d, altura=1.8, periodo=14.0):
    return DiaEvaluado(
        fecha=date(2026, 8, d), spot_id=SPOT.id, es_bueno=True, score=87.0,
        horas_buenas=5,
        bloque=(datetime(2026, 8, d, 7), datetime(2026, 8, d, 11)),
        resumen={"altura": altura, "periodo": periodo, "direccion": 200.0,
                 "viento_kmh": 9.0, "viento_direccion": 95.0},
        motivo_principal=None,
    )


def test_la_alerta_muestra_la_energia_en_kj():
    v = detectar_ventanas([_dia(21), _dia(22)])[0]
    mensaje = formatear_alerta(v, SPOT)
    assert "kJ" in mensaje
    esperado = f"{energia_kj(1.8, 14.0):.0f} kJ"
    assert esperado in mensaje


def test_la_alerta_sin_datos_no_inventa_energia():
    dia = DiaEvaluado(
        fecha=date(2026, 8, 21), spot_id=SPOT.id, es_bueno=True, score=50.0,
        horas_buenas=3, bloque=None, resumen=None, motivo_principal=None,
    )
    otro = DiaEvaluado(
        fecha=date(2026, 8, 22), spot_id=SPOT.id, es_bueno=True, score=50.0,
        horas_buenas=3, bloque=None, resumen=None, motivo_principal=None,
    )
    v = detectar_ventanas([dia, otro])[0]
    mensaje = formatear_alerta(v, SPOT)
    assert "kJ" not in mensaje
    assert "sin datos" in mensaje
