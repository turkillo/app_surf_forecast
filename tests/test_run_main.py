"""Tests de main(): el entrypoint real que lee el entorno y decide si el
estado se escribe a disco.

Ronda 1 de revision de la Tarea 10: la regla "nunca escribir state.json si
la corrida fallo" vive fisicamente en main(), no en correr(). Los tests de
test_run.py cubren correr() con dependencias inyectadas, pero nada protegia
a main() de una regresion (por ejemplo, mover el write_text() antes del
try). Estos tests ejercitan main() de punta a punta contra archivos
temporales, con las rutas y el traer/enviar reales monkeypatcheados.
"""
import json
from datetime import date, datetime

import run as run_module
from surf.fetch import ErrorDatos
from surf.score import Hora

_SPOT_YAML = """\
- id: test
  nombre: Test
  pais: AR
  lat: -38.15
  lon: -57.68
  tipo: point_break
  costa_mira: 140
  swell:
    ventana: [110, 200]
    ideal: 157
    min_altura: 1.0
    max_altura: 3.5
    rango_ideal: [1.5, 2.5]
    min_periodo: 9
  viento_ideal: 315
  temporada: [3, 4, 5, 6, 7, 8]
  url_surfforecast: "http://x"
  fuentes: ["test"]
  confianza: alta
"""


def _preparar_spots_yaml(tmp_path):
    ruta = tmp_path / "spots.yaml"
    ruta.write_text(_SPOT_YAML)
    return ruta


def _horas_buenas(fecha):
    return [Hora(t=datetime(fecha.year, fecha.month, fecha.day, x),
                 swell_altura=2.0, swell_periodo=14.0, swell_direccion=157.0,
                 viento_kmh=5.0, viento_direccion=320.0, es_de_dia=True)
            for x in range(7, 13)]


def _obtener_horas_buenas(spot, dias=7, sesion=None):
    from datetime import timedelta
    hoy = date.today()
    return {hoy + timedelta(days=n): _horas_buenas(hoy + timedelta(days=n))
            for n in range(1, 4)}


def _obtener_horas_rota(spot, dias=7, sesion=None):
    raise ErrorDatos("Open-Meteo caido")


def test_main_sin_secrets_sale_2_y_no_toca_el_estado(monkeypatch, tmp_path):
    monkeypatch.delenv("TELEGRAM_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    ruta_estado = tmp_path / "state.json"
    monkeypatch.setattr(run_module, "RUTA_ESTADO", ruta_estado)

    codigo = run_module.main()

    assert codigo == 2
    assert not ruta_estado.exists()


def test_main_todos_los_spots_fallan_no_escribe_estado_y_sale_1(monkeypatch, tmp_path):
    monkeypatch.setenv("TELEGRAM_TOKEN", "x")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "y")
    monkeypatch.setattr(run_module, "RUTA_SPOTS", _preparar_spots_yaml(tmp_path))
    ruta_estado = tmp_path / "state.json"
    monkeypatch.setattr(run_module, "RUTA_ESTADO", ruta_estado)
    monkeypatch.setattr(run_module, "obtener_horas", _obtener_horas_rota)
    avisos = []
    monkeypatch.setattr(run_module, "enviar",
                        lambda m, token, chat_id: avisos.append(m))

    codigo = run_module.main()

    assert codigo == 1
    assert not ruta_estado.exists()
    assert len(avisos) == 1  # se intento avisar del fallo por Telegram


def test_main_corrida_normal_escribe_estado_valido(monkeypatch, tmp_path):
    monkeypatch.setenv("TELEGRAM_TOKEN", "x")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "y")
    monkeypatch.setattr(run_module, "RUTA_SPOTS", _preparar_spots_yaml(tmp_path))
    ruta_estado = tmp_path / "state.json"
    monkeypatch.setattr(run_module, "RUTA_ESTADO", ruta_estado)
    monkeypatch.setattr(run_module, "obtener_horas", _obtener_horas_buenas)
    monkeypatch.setattr(run_module, "enviar", lambda m, token, chat_id: None)

    codigo = run_module.main()

    assert codigo == 0
    assert ruta_estado.exists()
    contenido = json.loads(ruta_estado.read_text())
    assert contenido["ultima_corrida"] == date.today().isoformat()
    assert "observadas" in contenido and "alertadas" in contenido


def test_main_no_pisa_state_json_preexistente_si_la_corrida_falla(monkeypatch, tmp_path):
    monkeypatch.setenv("TELEGRAM_TOKEN", "x")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "y")
    monkeypatch.setattr(run_module, "RUTA_SPOTS", _preparar_spots_yaml(tmp_path))
    ruta_estado = tmp_path / "state.json"
    contenido_previo = {"ultima_corrida": "2026-01-01", "observadas": [], "alertadas": []}
    ruta_estado.write_text(json.dumps(contenido_previo))
    monkeypatch.setattr(run_module, "RUTA_ESTADO", ruta_estado)
    monkeypatch.setattr(run_module, "obtener_horas", _obtener_horas_rota)
    monkeypatch.setattr(run_module, "enviar", lambda m, token, chat_id: None)

    codigo = run_module.main()

    assert codigo == 1
    assert json.loads(ruta_estado.read_text()) == contenido_previo
