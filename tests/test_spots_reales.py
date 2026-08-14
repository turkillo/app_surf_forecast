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


def test_todos_declaran_cercania_explicitamente():
    """`cercania` es opcional en el esquema y cae en "viaje", pero los 13 spots
    de produccion lo tienen que declarar a mano: el valor por defecto sirve para
    que un perfil minimo cargue, no para dejar el campo sin decidir. Se lee el
    YAML crudo justamente para que un default no haga pasar el test."""
    import yaml
    crudos = yaml.safe_load(Path("spots.yaml").read_text(encoding="utf-8"))
    sin_declarar = [c["id"] for c in crudos if "cercania" not in c]
    assert not sin_declarar, f"spots sin cercania declarada: {sin_declarar}"
    for s in _spots():
        assert s.cercania in {"local", "viaje"}, f"{s.id} sin cercania valida"


def test_los_tres_spots_locales_estan_marcados():
    """La Barra, Chapadmalal y Praia do Rosa son los spots a los que el usuario
    va sin planificar viaje. El campo registra POR QUE pueden llevar umbrales
    distintos al resto, para que nadie los "corrija" leyendo solo el volumen."""
    locales = {s.id for s in _spots() if s.cercania == "local"}
    assert locales == {"la_barra", "chapadmalal", "praia_do_rosa"}


def test_el_piso_de_altura_de_los_locales_sigue_en_un_metro():
    """Decision explicita del usuario: ser local no baja el minimo de tamano."""
    for s in _spots():
        if s.cercania == "local":
            assert s.swell.min_altura == 1.0, f"{s.id} cambio el piso de 1.0 m"


def test_los_puntos_de_oleaje_desplazados_son_los_esperados():
    """Solo `chicama`. Se probo desplazar tambien `la_barra` y `joaquina` y se
    revirtio: contra surf-forecast el punto de playa ya era el mas fiel en
    `la_barra` (1.04) y desplazarlo lo llevaba a sobreestimar (1.16), y en
    `joaquina` no existe distancia que desenmascare ncep sin leer un mar 43-49%
    mas grande. Ver docs/resultados-backtest.md."""
    desplazados = {s.id for s in _spots() if s.coords_mar != (s.lat, s.lon)}
    assert desplazados == {"chicama"}
