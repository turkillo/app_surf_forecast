from datetime import date, datetime

import pytest

from run import correr
from surf.alert import estado_vacio
from surf.fetch import ErrorDatos
from surf.notify import ErrorEnvio
from surf.score import Hora
from tests.test_score_gate import SPOT

HOY = date(2026, 8, 13)


def _horas_buenas(fecha):
    return [Hora(t=datetime(fecha.year, fecha.month, fecha.day, x),
                 swell_altura=2.0, swell_periodo=14.0, swell_direccion=157.0,
                 viento_kmh=5.0, viento_direccion=320.0, es_de_dia=True)
            for x in range(7, 13)]


def _traer_bueno(spot, dias=7):
    from datetime import timedelta
    return {HOY + timedelta(days=n): _horas_buenas(HOY + timedelta(days=n))
            for n in range(1, 4)}


def _traer_roto(spot, dias=7):
    raise ErrorDatos("Open-Meteo caido")


def test_una_corrida_normal_actualiza_el_estado():
    enviados = []
    estado, msgs = correr([SPOT], HOY, _traer_bueno, enviados.append, estado_vacio())
    assert estado["ultima_corrida"] == HOY.isoformat()
    assert len(estado["observadas"]) >= 1


def test_la_primera_corrida_no_alerta():
    enviados = []
    correr([SPOT], HOY, _traer_bueno, enviados.append, estado_vacio())
    assert enviados == []


def test_la_segunda_corrida_consecutiva_si_alerta():
    from datetime import timedelta
    enviados = []
    estado, _ = correr([SPOT], HOY - timedelta(days=1), _traer_bueno,
                       lambda m: None, estado_vacio())
    correr([SPOT], HOY, _traer_bueno, enviados.append, estado)
    assert len(enviados) >= 1
    assert "BUEN SWELL" in enviados[0]


def test_si_un_spot_falla_los_demas_siguen():
    from dataclasses import replace
    otro = replace(SPOT, id="otro")
    llamadas = {"n": 0}

    def traer(spot, dias=7):
        llamadas["n"] += 1
        if spot.id == "otro":
            raise ErrorDatos("sin datos")
        return _traer_bueno(spot)

    estado, msgs = correr([SPOT, otro], HOY, traer, lambda m: None, estado_vacio())
    assert llamadas["n"] == 2
    assert estado["ultima_corrida"] == HOY.isoformat()


def test_si_fallan_todos_los_spots_no_se_escribe_estado():
    with pytest.raises(RuntimeError, match="ningun spot"):
        correr([SPOT], HOY, _traer_roto, lambda m: None, estado_vacio())


def test_el_domingo_se_manda_el_digest():
    enviados = []
    domingo = date(2026, 8, 16)
    assert domingo.weekday() == 6
    correr([SPOT], domingo, _traer_bueno, enviados.append, estado_vacio())
    assert any("Resumen semanal" in m for m in enviados)


def test_entre_semana_no_se_manda_digest():
    enviados = []
    jueves = date(2026, 8, 13)
    assert jueves.weekday() == 3
    correr([SPOT], jueves, _traer_bueno, enviados.append, estado_vacio())
    assert not any("Resumen semanal" in m for m in enviados)


def test_un_envio_fallido_no_aborta_los_demas():
    """Si enviar_fn explota en un mensaje, correr sigue con los siguientes y
    termina normalmente: la falla de Telegram no debe abortar la corrida ni
    impedir que se calcule y devuelva el estado nuevo (Tarea 9 ya sufrio una
    fuga de token porque una excepcion de envio se propagaba sin capturar)."""
    from dataclasses import replace
    from datetime import timedelta

    otro = replace(SPOT, id="otro")
    intentos = []

    def enviar_que_falla_una_vez(m):
        intentos.append(m)
        if len(intentos) == 1:
            raise ErrorEnvio("simulado")

    estado_previo, _ = correr([SPOT, otro], HOY - timedelta(days=1), _traer_bueno,
                              lambda m: None, estado_vacio())
    estado_nuevo, enviados = correr([SPOT, otro], HOY, _traer_bueno,
                                    enviar_que_falla_una_vez, estado_previo)

    assert len(intentos) == 2
    assert estado_nuevo["ultima_corrida"] == HOY.isoformat()
