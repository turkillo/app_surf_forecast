"""Verifica que el spots.yaml de produccion este completo y sea coherente."""
from pathlib import Path

from surf.spots import cargar_spots

IDS_ESPERADOS = {
    "la_barra", "chapadmalal", "praia_do_rosa", "buchupureo", "asia",
    "huanchaco", "santa_teresa", "saquarema", "punta_de_lobos",
    "chicama", "lobitos", "punta_del_diablo", "joaquina",
}


def _spots():
    return cargar_spots(Path("spots.yaml"))


def test_estan_los_trece_spots():
    assert {s.id for s in _spots()} == IDS_ESPERADOS


def test_todos_tienen_al_menos_una_fuente_citada():
    for s in _spots():
        assert s.fuentes, f"{s.id} no tiene fuentes citadas"


def test_todos_tienen_url_de_surfforecast():
    for s in _spots():
        assert s.url_surfforecast.startswith("http"), f"{s.id} sin url valida"


def test_las_coordenadas_son_plausibles():
    for s in _spots():
        assert -60 < s.lat < 15, f"{s.id} latitud fuera de rango"
        assert -90 < s.lon < -30, f"{s.id} longitud fuera de rango"


def test_hay_cobertura_de_los_cinco_paises():
    paises = {s.pais for s in _spots()}
    assert {"AR", "UY", "BR", "CL", "PE"}.issubset(paises)


def test_los_perfiles_de_baja_confianza_estan_identificados():
    # No es un fallo tener baja confianza, pero tiene que estar declarado.
    for s in _spots():
        assert s.confianza in {"alta", "media", "baja"}
