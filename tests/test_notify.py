from datetime import date, datetime

import pytest

from surf.alert import detectar_ventanas
from surf.notify import formatear_alerta, formatear_digest
from surf.score import DiaEvaluado
from tests.test_score_gate import SPOT


def dia(d, score=87.0):
    return DiaEvaluado(
        fecha=date(2026, 8, d), spot_id=SPOT.id, es_bueno=True, score=score,
        horas_buenas=5,
        bloque=(datetime(2026, 8, d, 7), datetime(2026, 8, d, 11)),
        resumen={"altura": 1.8, "periodo": 14.0, "direccion": 200.0,
                 "viento_kmh": 9.0, "viento_direccion": 95.0},
        motivo_principal=None,
    )


def test_la_alerta_nombra_el_spot_y_las_fechas():
    v = detectar_ventanas([dia(21), dia(22)])[0]
    m = formatear_alerta(v, SPOT)
    assert SPOT.nombre in m
    assert "21" in m and "22" in m


def test_la_alerta_incluye_altura_periodo_y_viento_de_cada_dia():
    v = detectar_ventanas([dia(21), dia(22)])[0]
    m = formatear_alerta(v, SPOT)
    assert "1.8m" in m
    assert "14s" in m
    assert "9km/h" in m


def test_la_alerta_traduce_las_direcciones_a_texto():
    v = detectar_ventanas([dia(21), dia(22)])[0]
    m = formatear_alerta(v, SPOT)
    assert "SSW" in m   # swell desde 200
    assert "E" in m     # viento desde 95


def test_la_alerta_clasifica_el_viento():
    v = detectar_ventanas([dia(21), dia(22)])[0]
    m = formatear_alerta(v, SPOT)
    # costa_mira 140 -> offshore desde 320. Viento desde 95 es cross.
    assert "cross" in m


def test_la_alerta_incluye_el_link_de_surfforecast():
    v = detectar_ventanas([dia(21), dia(22)])[0]
    assert SPOT.url_surfforecast in formatear_alerta(v, SPOT)


def test_la_alerta_marca_la_mejor_ventana_horaria():
    v = detectar_ventanas([dia(21), dia(22)])[0]
    m = formatear_alerta(v, SPOT)
    assert "Mejor ventana" in m


def test_la_alerta_de_baja_confianza_lo_avisa():
    from dataclasses import replace
    spot_dudoso = replace(SPOT, confianza="baja")
    v = detectar_ventanas([dia(21), dia(22)])[0]
    assert "perfil poco validado" in formatear_alerta(v, spot_dudoso)


def test_el_digest_vacio_igual_dice_algo():
    m = formatear_digest([], hubo_alertas=0, fecha=date(2026, 8, 16))
    assert "sin ventanas" in m.lower()


def test_el_digest_lista_lo_que_quedo_cerca():
    d = DiaEvaluado(fecha=date(2026, 8, 18), spot_id=SPOT.id, es_bueno=False,
                    score=0.0, horas_buenas=0, bloque=None, resumen=None,
                    motivo_principal="período corto (8.5s, mínimo 9.0s)")
    m = formatear_digest([(d, SPOT)], hubo_alertas=0, fecha=date(2026, 8, 16))
    assert SPOT.nombre in m
    assert "período corto" in m


def test_el_digest_reporta_cuantas_alertas_hubo():
    m = formatear_digest([], hubo_alertas=3, fecha=date(2026, 8, 16))
    assert "3" in m


def test_enviar_no_filtra_el_token_en_error():
    from unittest.mock import Mock
    from surf.notify import enviar, ErrorEnvio
    import requests

    mock_sesion = Mock()
    mock_response = Mock()
    mock_response.status_code = 401
    mock_response.reason = "Unauthorized"

    # Simular un HTTPError que contendria la URL con el token en requests
    error_http = requests.exceptions.HTTPError()
    error_http.response = mock_response
    mock_sesion.post.side_effect = error_http

    token_secreto = "123456789:AAHsecretTokenValueXYZ"

    with pytest.raises(ErrorEnvio) as exc_info:
        enviar("test", token_secreto, "12345", sesion=mock_sesion)

    # El token no debe aparecer en el mensaje de error
    assert token_secreto not in str(exc_info.value)
    assert "401" in str(exc_info.value)
