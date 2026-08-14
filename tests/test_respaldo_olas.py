"""Cadena de respaldo entre modelos de olas.

`ncep_gfswave025` esta enmascarado como tierra en 5 de los 13 spots. En
`huanchaco` existe `ncep_gfswave016` --el MISMO modelo de NOAA en grilla de
0.16 grados-- que si devuelve dato ahi porque su celda cae en agua.

La regla que estos tests fijan es una sola y es la que evita reintroducir el
bug de la Tarea 11 (una fuente votando dos veces): el respaldo OCUPA EL LUGAR
del titular, no se suma. `ncep_gfswave025` y `ncep_gfswave016` son los dos WW3
de NOAA: contarlos juntos seria el mismo modelo votando dos veces, no dos
opiniones independientes.
"""
from datetime import date

import pytest

from surf.consenso import (MODELOS_OLAS, MODELOS_VIENTO, RESPALDO_OLAS,
                           HoraMultiModelo, sin_modelos_excluidos)
from surf.fetch import _combinar_multimodelo
from surf.score import Hora
from surf.spots import Spot, Swell

TITULAR = "ncep_gfswave025"
RESPALDO = "ncep_gfswave016"

SPOT = Spot(
    id="test", nombre="Test", pais="PE", lat=-8.08, lon=-79.12,
    tipo="point_break", costa_mira=234,
    swell=Swell(ventana=(157, 247), ideal=202, min_altura=1.0, max_altura=2.5,
                rango_ideal=(1.5, 2.2), min_periodo=8.0),
    viento_ideal=45, temporada=[4, 5, 6, 7, 8, 9, 10],
    url_surfforecast="http://x", fuentes=["surf-forecast"], confianza="media",
)


def _marine(series: dict) -> dict:
    n = len(next(iter(series.values())))
    hourly = {"time": [f"2026-08-21T{9 + i:02d}:00" for i in range(n)]}
    for modelo, filas in series.items():
        hourly[f"swell_wave_height_{modelo}"] = [f[0] for f in filas]
        hourly[f"swell_wave_period_{modelo}"] = [f[1] for f in filas]
        hourly[f"swell_wave_direction_{modelo}"] = [f[2] for f in filas]
    return {"hourly": hourly}


def _clima(n: int) -> dict:
    hourly = {"time": [f"2026-08-21T{9 + i:02d}:00" for i in range(n)]}
    for m in MODELOS_VIENTO:
        hourly[f"wind_speed_10m_{m}"] = [7.0] * n
        hourly[f"wind_direction_10m_{m}"] = [320.0] * n
    return {"hourly": hourly,
            "daily": {"time": ["2026-08-21"], "sunrise": ["2026-08-21T06:45"],
                      "sunset": ["2026-08-21T18:20"]}}


def _horas(series: dict) -> list:
    n = len(next(iter(series.values())))
    por_dia = _combinar_multimodelo(_marine(series), _clima(n),
                                    list(MODELOS_OLAS), list(MODELOS_VIENTO))
    return por_dia[date(2026, 8, 21)]


def _modelos_de_olas(hmm: HoraMultiModelo) -> set:
    return {n.split("+")[0] for n in hmm.por_modelo}


ENMASCARADO = [(0.0, 0.0, 0.0), (0.0, 0.0, 0.0)]
GWAM = [(1.4, 13.0, 200.0), (1.5, 13.2, 201.0)]
MF = [(1.8, 14.0, 202.0), (1.9, 14.2, 203.0)]
NCEP_OK = [(1.6, 13.5, 198.0), (1.7, 13.7, 199.0)]
NCEP_OTRO = [(1.2, 12.5, 195.0), (1.3, 12.7, 196.0)]


# --- la sustitucion ---------------------------------------------------------

def test_el_respaldo_reemplaza_al_titular_enmascarado():
    horas = _horas({"gwam": GWAM, "meteofrance_wave": MF,
                    TITULAR: ENMASCARADO, RESPALDO: NCEP_OK})
    modelos = _modelos_de_olas(horas[0])
    assert RESPALDO in modelos, "el respaldo no ocupo el lugar del titular"
    assert TITULAR not in modelos
    assert len(horas[0].por_modelo) == 3


def test_el_respaldo_no_entra_si_el_titular_tiene_dato():
    horas = _horas({"gwam": GWAM, "meteofrance_wave": MF,
                    TITULAR: NCEP_OK, RESPALDO: NCEP_OTRO})
    modelos = _modelos_de_olas(horas[0])
    assert TITULAR in modelos
    assert RESPALDO not in modelos
    assert len(horas[0].por_modelo) == 3


def test_titular_y_respaldo_nunca_votan_juntos():
    """Critical. Los dos son WW3 de NOAA: juntos son un solo modelo votando dos
    veces, que es exactamente el bug que se arreglo sacando best_match."""
    for titular in (ENMASCARADO, NCEP_OK):
        for respaldo in (ENMASCARADO, NCEP_OTRO):
            horas = _horas({"gwam": GWAM, "meteofrance_wave": MF,
                            TITULAR: titular, RESPALDO: respaldo})
            for hmm in horas:
                presentes = _modelos_de_olas(hmm) & {TITULAR, RESPALDO}
                assert len(presentes) <= 1, (
                    f"los dos NCEP votaron juntos: {sorted(presentes)}")


def test_el_respaldo_no_entra_si_no_devolvio_columna():
    """8 de los 13 spots no tienen columna de ncep_gfswave016: la grilla de
    0.16 no los cubre. Ahi no cambia nada."""
    horas = _horas({"gwam": GWAM, "meteofrance_wave": MF, TITULAR: ENMASCARADO})
    assert _modelos_de_olas(horas[0]) == {"gwam", "meteofrance_wave"}


def test_el_respaldo_no_entra_si_tambien_esta_enmascarado():
    horas = _horas({"gwam": GWAM, "meteofrance_wave": MF,
                    TITULAR: ENMASCARADO, RESPALDO: ENMASCARADO})
    assert _modelos_de_olas(horas[0]) == {"gwam", "meteofrance_wave"}


def test_el_respaldo_hereda_el_viento_que_le_tocaba_al_titular():
    """El emparejamiento olas[i]+viento[i] no se toca: el respaldo entra EN LA
    POSICION del titular, asi que le toca el mismo modelo de viento y ninguna
    otra fuente se corre de lugar."""
    con_titular = _horas({"gwam": GWAM, "meteofrance_wave": MF, TITULAR: NCEP_OK})
    con_respaldo = _horas({"gwam": GWAM, "meteofrance_wave": MF,
                           TITULAR: ENMASCARADO, RESPALDO: NCEP_OK})

    viento_titular = next(n.split("+")[1] for n in con_titular[0].por_modelo
                          if n.startswith(TITULAR))
    viento_respaldo = next(n.split("+")[1] for n in con_respaldo[0].por_modelo
                           if n.startswith(RESPALDO))
    assert viento_titular == viento_respaldo

    # Y las otras dos fuentes conservan exactamente el viento que ya tenian.
    otros = {n for n in con_titular[0].por_modelo if not n.startswith(TITULAR)}
    assert otros == {n for n in con_respaldo[0].por_modelo
                     if not n.startswith(RESPALDO)}


def test_una_hora_suelta_sin_dato_del_titular_no_dispara_el_respaldo():
    """La sustitucion es una decision de PUNTO, no de hora: si el titular tiene
    dato aunque sea en parte de la serie, la celda no esta enmascarada y el
    respaldo no entra. Si no, la fuente cambiaria de identidad hora a hora."""
    horas = _horas({"gwam": GWAM, "meteofrance_wave": MF,
                    TITULAR: [(0.0, 0.0, 0.0), (1.7, 13.7, 199.0)],
                    RESPALDO: NCEP_OK})
    assert _modelos_de_olas(horas[0]) == {"gwam", "meteofrance_wave"}
    assert _modelos_de_olas(horas[1]) == {"gwam", "meteofrance_wave", TITULAR}


# --- exclusion --------------------------------------------------------------

def test_excluir_el_titular_excluye_tambien_a_su_respaldo():
    """`modelos_excluidos` nombra al titular. Si el respaldo sobreviviera, la
    exclusion no sacaria la fuente que se quiso sacar: la renombraria."""
    spot = Spot(**{**SPOT.__dict__, "modelos_excluidos": [TITULAR]})
    hmm = HoraMultiModelo(
        t=None, es_de_dia=True,
        por_modelo={f"{RESPALDO}+ecmwf_ifs025": Hora(
            t=None, swell_altura=1.6, swell_periodo=13.5, swell_direccion=198.0,
            viento_kmh=7.0, viento_direccion=45.0, es_de_dia=True)},
    )
    assert sin_modelos_excluidos(hmm, spot).por_modelo == {}


# --- estructura -------------------------------------------------------------

def test_el_respaldo_no_es_un_modelo_mas_de_la_votacion():
    for titular, respaldo in RESPALDO_OLAS.items():
        assert titular in MODELOS_OLAS, (
            f"{titular} no es un modelo titular: el respaldo no tiene a quien "
            f"reemplazar")
        assert respaldo not in MODELOS_OLAS, (
            f"{respaldo} esta en MODELOS_OLAS: seria un cuarto voto en vez de "
            f"un reemplazo, y con {titular} presente serian dos WW3 votando")


def test_ningun_modelo_es_respaldo_de_dos_titulares():
    respaldos = list(RESPALDO_OLAS.values())
    assert len(set(respaldos)) == len(respaldos)


def test_se_le_piden_los_respaldos_a_la_api():
    """Si no se piden, la cadena no puede activarse nunca."""
    from surf.consenso import MODELOS_OLAS_PEDIDOS

    for titular, respaldo in RESPALDO_OLAS.items():
        assert respaldo in MODELOS_OLAS_PEDIDOS
        assert titular in MODELOS_OLAS_PEDIDOS


def test_obtener_horas_multimodelo_pide_los_respaldos():
    from surf.consenso import MODELOS_OLAS_PEDIDOS
    from surf.fetch import obtener_horas_multimodelo

    pedidos = []

    class _Sesion:
        def get(self, url, params=None, timeout=None):
            pedidos.append(params)
            raise RuntimeError("corta aca: solo interesa que parametros se pidieron")

    with pytest.raises(RuntimeError):
        obtener_horas_multimodelo(SPOT, sesion=_Sesion())

    assert pedidos[0]["models"] == ",".join(MODELOS_OLAS_PEDIDOS)


def test_todo_modelo_que_puede_votar_tiene_nombre_legible():
    """La linea de concordancia nombra los modelos que se consultaron. Un
    respaldo sin entrada en la tabla saldria con su id crudo de Open-Meteo en
    el mensaje que lee el usuario."""
    from surf.consenso import MODELOS_OLAS_PEDIDOS
    from surf.notify import _NOMBRES_MODELOS

    for m in MODELOS_OLAS_PEDIDOS + MODELOS_VIENTO:
        assert m in _NOMBRES_MODELOS, f"{m} no tiene nombre legible"


def test_los_dos_ncep_no_se_llaman_igual():
    """Si compartieran nombre, el mensaje no dejaria ver cual de las dos
    grillas fue la que opino en ese spot."""
    from surf.notify import _NOMBRES_MODELOS

    for titular, respaldo in RESPALDO_OLAS.items():
        assert _NOMBRES_MODELOS[titular] != _NOMBRES_MODELOS[respaldo]


def test_el_backtest_tambien_pide_los_respaldos(tmp_path):
    """Si el backtest no los pidiera, mediria una configuracion que no es la
    que corre en produccion, que es justo lo que no puede pasar."""
    from backtest import obtener_historico

    pedidos = []

    class _Sesion:
        def get(self, url, params=None, timeout=None):
            pedidos.append((url, params))
            raise RuntimeError("corta aca")

    with pytest.raises(RuntimeError):
        obtener_historico(SPOT, date(2026, 8, 1), date(2026, 8, 2),
                          sesion=_Sesion(), cache_dir=tmp_path)

    modelos = pedidos[0][1]["models"].split(",")
    for titular, respaldo in RESPALDO_OLAS.items():
        assert titular in modelos
        assert respaldo in modelos


def test_el_backtest_respeta_los_modelos_que_le_pasan_por_linea_de_comando(tmp_path):
    """`--modelos-olas` sirve para medir el sesgo del archivo. El respaldo de un
    modelo que no se pidio no tiene por que aparecer."""
    from backtest import obtener_historico

    pedidos = []

    class _Sesion:
        def get(self, url, params=None, timeout=None):
            pedidos.append((url, params))
            raise RuntimeError("corta aca")

    with pytest.raises(RuntimeError):
        obtener_historico(SPOT, date(2026, 8, 1), date(2026, 8, 2),
                          sesion=_Sesion(), cache_dir=tmp_path,
                          modelos_olas=["gwam", "meteofrance_wave"])

    assert pedidos[0][1]["models"].split(",") == ["gwam", "meteofrance_wave"]
