from datetime import datetime

import pytest

from surf.score import Hora, evaluar_hora
from surf.spots import Spot, Swell

SPOT = Spot(
    id="test", nombre="Test", pais="AR", lat=-38.15, lon=-57.68,
    tipo="point_break", costa_mira=140,
    swell=Swell(ventana=(110, 200), ideal=157, min_altura=1.0,
                max_altura=3.5, rango_ideal=(1.5, 2.5), min_periodo=9),
    viento_ideal=315, temporada=[3, 4, 5, 6, 7, 8],
    url_surfforecast="http://x", fuentes=["test"], confianza="alta",
)


def hora(altura=2.0, periodo=12.0, direccion=157.0,
         viento_kmh=5.0, viento_dir=320.0, de_dia=True):
    """Hora base con condiciones que pasan el gate. Cada test rompe una sola cosa."""
    return Hora(
        t=datetime(2026, 8, 21, 9, 0),
        swell_altura=altura, swell_periodo=periodo, swell_direccion=direccion,
        viento_kmh=viento_kmh, viento_direccion=viento_dir, es_de_dia=de_dia,
    )


def test_condiciones_perfectas_pasan():
    r = evaluar_hora(hora(), SPOT)
    assert r.pasa is True
    assert r.motivo_rechazo is None


def test_altura_por_debajo_del_minimo_no_pasa():
    r = evaluar_hora(hora(altura=0.7), SPOT)
    assert r.pasa is False
    assert "altura" in r.motivo_rechazo


def test_altura_por_encima_del_maximo_no_pasa():
    # El spot cierra arriba de 3.5m: un swell de 4.5m no es una alerta
    r = evaluar_hora(hora(altura=4.5), SPOT)
    assert r.pasa is False
    assert "cierra" in r.motivo_rechazo


def test_periodo_corto_no_pasa():
    r = evaluar_hora(hora(periodo=7.2), SPOT)
    assert r.pasa is False
    assert "período" in r.motivo_rechazo


def test_direccion_fuera_de_la_ventana_no_pasa():
    # Swell del NE en un spot que solo recibe del S/SE
    r = evaluar_hora(hora(direccion=45), SPOT)
    assert r.pasa is False
    assert "dirección" in r.motivo_rechazo


def test_swell_perfecto_con_onshore_no_pasa():
    # 15 km/h desde el SE (140) es onshore directo
    r = evaluar_hora(hora(viento_kmh=15, viento_dir=140), SPOT)
    assert r.pasa is False
    assert "onshore" in r.motivo_rechazo


def test_offshore_muy_fuerte_no_pasa():
    r = evaluar_hora(hora(viento_kmh=40, viento_dir=320), SPOT)
    assert r.pasa is False
    assert "offshore" in r.motivo_rechazo


def test_cross_muy_fuerte_no_pasa():
    r = evaluar_hora(hora(viento_kmh=25, viento_dir=230), SPOT)
    assert r.pasa is False
    assert "cross" in r.motivo_rechazo


def test_onshore_muy_suave_si_pasa():
    # Hasta 8 km/h el onshore es tolerable
    r = evaluar_hora(hora(viento_kmh=6, viento_dir=140), SPOT)
    assert r.pasa is True
    assert r.clase_viento == "onshore"


def test_glassy_pasa_en_cualquier_direccion():
    r = evaluar_hora(hora(viento_kmh=4, viento_dir=140), SPOT)
    assert r.pasa is True


def test_de_noche_no_pasa():
    # Condiciones perfectas a las 3 AM no son una sesion
    r = evaluar_hora(hora(de_dia=False), SPOT)
    assert r.pasa is False
    assert "luz" in r.motivo_rechazo


def test_el_gate_no_compensa_entre_criterios():
    # Swell excelente pero onshore fuerte: sigue sin pasar.
    # Este test existe para que nadie reintroduzca un promedio ponderado.
    r = evaluar_hora(hora(altura=2.5, periodo=16, viento_kmh=30, viento_dir=140), SPOT)
    assert r.pasa is False
    assert r.score == 0.0


def test_la_hora_rechazada_tiene_score_cero():
    assert evaluar_hora(hora(periodo=5), SPOT).score == 0.0
