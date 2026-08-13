import pytest
from pathlib import Path
from surf.spots import cargar_spots, Spot, Swell

FIXTURE = """
- id: test_spot
  nombre: "Spot de Prueba"
  pais: "AR"
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
  url_surfforecast: "https://es.surf-forecast.com/breaks/Chapadmalal"
  fuentes: [surf-forecast]
  confianza: alta
"""


def _escribir(tmp_path, contenido):
    p = tmp_path / "spots.yaml"
    p.write_text(contenido)
    return p


def test_carga_un_perfil_completo(tmp_path):
    spots = cargar_spots(_escribir(tmp_path, FIXTURE))
    assert len(spots) == 1
    s = spots[0]
    assert s.id == "test_spot"
    assert s.costa_mira == 140
    assert s.swell.min_periodo == 9
    assert s.swell.rango_ideal == (1.5, 2.5)


def test_los_dataclasses_son_inmutables(tmp_path):
    s = cargar_spots(_escribir(tmp_path, FIXTURE))[0]
    with pytest.raises(Exception):
        s.costa_mira = 200


def test_rechaza_campo_faltante(tmp_path):
    roto = FIXTURE.replace("  viento_ideal: 315\n", "")
    with pytest.raises(ValueError, match="viento_ideal"):
        cargar_spots(_escribir(tmp_path, roto))


def test_rechaza_max_altura_menor_que_min(tmp_path):
    roto = FIXTURE.replace("max_altura: 3.5", "max_altura: 0.5")
    with pytest.raises(ValueError, match="max_altura"):
        cargar_spots(_escribir(tmp_path, roto))


def test_rechaza_rango_ideal_fuera_de_los_limites(tmp_path):
    roto = FIXTURE.replace("rango_ideal: [1.5, 2.5]", "rango_ideal: [0.2, 2.5]")
    with pytest.raises(ValueError, match="rango_ideal"):
        cargar_spots(_escribir(tmp_path, roto))


def test_rechaza_ideal_fuera_de_la_ventana(tmp_path):
    roto = FIXTURE.replace("ideal: 157", "ideal: 20")
    with pytest.raises(ValueError, match="ideal"):
        cargar_spots(_escribir(tmp_path, roto))


def test_rechaza_confianza_invalida(tmp_path):
    roto = FIXTURE.replace("confianza: alta", "confianza: buenisima")
    with pytest.raises(ValueError, match="confianza"):
        cargar_spots(_escribir(tmp_path, roto))


def test_rechaza_costa_mira_incoherente_con_viento_ideal(tmp_path):
    # costa_mira 140 implica offshore desde 320. Un viento_ideal de 90
    # esta a mas de 30 grados: es un error de investigacion.
    roto = FIXTURE.replace("viento_ideal: 315", "viento_ideal: 90")
    with pytest.raises(ValueError, match="costa_mira"):
        cargar_spots(_escribir(tmp_path, roto))


def test_rechaza_ids_duplicados(tmp_path):
    with pytest.raises(ValueError, match="duplicado"):
        cargar_spots(_escribir(tmp_path, FIXTURE + FIXTURE))


def test_swell_es_inmutable(tmp_path):
    s = cargar_spots(_escribir(tmp_path, FIXTURE))[0]
    with pytest.raises(Exception):
        s.swell.min_periodo = 12


def test_rechaza_campo_numerico_con_valor_null(tmp_path):
    # Important 1: costa_mira con valor null debe lanzar ValueError accionable
    roto = FIXTURE.replace("costa_mira: 140", "costa_mira:")
    with pytest.raises(ValueError, match="costa_mira"):
        cargar_spots(_escribir(tmp_path, roto))


def test_rechaza_swell_null(tmp_path):
    # Important 1: swell con valor null debe lanzar ValueError accionable
    roto = FIXTURE.replace(
        "  swell:\n    ventana: [110, 200]\n    ideal: 157\n    min_altura: 1.0\n    max_altura: 3.5\n    rango_ideal: [1.5, 2.5]\n    min_periodo: 9\n",
        "  swell:\n"
    )
    with pytest.raises(ValueError, match="swell"):
        cargar_spots(_escribir(tmp_path, roto))


def test_rechaza_tipo_invalido_en_campo_numerico(tmp_path):
    # Important 2: error en float(lat) debe decir de qué spot y campo
    roto = FIXTURE.replace("lat: -38.15", "lat: not_a_number")
    with pytest.raises(ValueError, match="lat"):
        cargar_spots(_escribir(tmp_path, roto))


def test_rechaza_yaml_con_mapping_en_raiz(tmp_path):
    # Important 3: YAML que es un mapping (dict) en vez de lista debe lanzar ValueError
    mapping_yaml = """
id: test_spot
nombre: "Spot de Prueba"
pais: "AR"
lat: -38.15
lon: -57.68
tipo: point_break
costa_mira: 140
"""
    with pytest.raises(ValueError, match="lista"):
        cargar_spots(_escribir(tmp_path, mapping_yaml))
