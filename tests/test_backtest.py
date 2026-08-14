"""Tests del backtest historico.

El backtest tiene que correr EL MISMO camino que produccion: multi-modelo con
consenso (evaluar_dia_multimodelo), no el camino single-modelo. Un backtest
que prueba un camino distinto no valida nada, asi que hay tests explicitos de
que el consenso se exige.
"""
import gzip
import json
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from backtest import (LIMITE_ESTRANGULADO, LIMITE_RUIDO, RANGO_SANO, analizar,
                      coincide_la_temporada, obtener_historico, veredicto)
from surf.consenso import HoraMultiModelo
from surf.score import Hora
from surf.spots import cargar_spots
from tests.test_score_gate import SPOT

RUTA_SPOTS = Path(__file__).resolve().parent.parent / "spots.yaml"


def _hora(t: datetime, buena: bool) -> Hora:
    alt, per, vd = (2.0, 14.0, 320.0) if buena else (0.4, 5.0, 140.0)
    return Hora(t=t, swell_altura=alt, swell_periodo=per, swell_direccion=157.0,
                viento_kmh=5.0 if buena else 30.0, viento_direccion=vd,
                es_de_dia=True)


def _dia_de_horas(f: date, buena: bool, modelos=("a", "b")) -> list:
    """Un dia de 6 horas de luz, con todos los modelos de acuerdo."""
    return _dia_mixto(f, {m: buena for m in modelos})


def _dia_mixto(f: date, por_modelo: dict) -> list:
    """Un dia donde cada modelo opina lo que dice `por_modelo`."""
    horas = []
    for x in range(7, 13):
        t = datetime(f.year, f.month, f.day, x)
        horas.append(HoraMultiModelo(
            t=t, es_de_dia=True,
            por_modelo={m: _hora(t, b) for m, b in por_modelo.items()},
        ))
    return horas


# --- analizar ---------------------------------------------------------------

def test_analizar_cuenta_las_ventanas():
    inicio = date(2024, 1, 1)
    por_dia = {}
    for n in range(24):
        f = inicio + timedelta(days=n)
        por_dia[f] = _dia_de_horas(f, buena=(n % 12) in (0, 1))
    r = analizar(SPOT, por_dia)
    assert r["total_ventanas"] == 2


def test_analizar_reporta_la_distribucion_mensual():
    inicio = date(2024, 6, 1)
    por_dia = {inicio + timedelta(days=n): _dia_de_horas(inicio + timedelta(days=n), True)
               for n in range(5)}
    r = analizar(SPOT, por_dia)
    assert r["por_mes"][6] > 0


def test_analizar_exige_consenso_entre_modelos():
    """Si un solo modelo de dos ve el swell, no hay ventana.

    Este es el test que distingue el camino multi-modelo del single-modelo: si
    `analizar` usara `evaluar_dia`, la mediana de un modelo bueno y uno malo
    podria pasar el gate y este test daria ventanas.
    """
    inicio = date(2024, 6, 1)
    por_dia = {inicio + timedelta(days=n): _dia_mixto(inicio + timedelta(days=n),
                                                      {"a": True, "b": False})
               for n in range(6)}
    r = analizar(SPOT, por_dia)
    assert r["total_ventanas"] == 0


def test_analizar_acepta_el_dia_cuando_los_dos_modelos_coinciden():
    inicio = date(2024, 6, 1)
    por_dia = {inicio + timedelta(days=n): _dia_mixto(inicio + timedelta(days=n),
                                                      {"a": True, "b": True})
               for n in range(6)}
    r = analizar(SPOT, por_dia)
    assert r["total_ventanas"] == 1


def test_analizar_reporta_cuantas_fuentes_de_olas_hubo():
    """El sesgo del backtest depende de cuantas fuentes hubo; hay que medirlo."""
    inicio = date(2024, 6, 1)
    por_dia = {inicio + timedelta(days=n): _dia_de_horas(inicio + timedelta(days=n),
                                                         True, modelos=("a", "b"))
               for n in range(6)}
    r = analizar(SPOT, por_dia)
    assert r["fuentes_promedio"] == pytest.approx(2.0)


def test_analizar_no_cuenta_las_fuentes_que_el_spot_excluye():
    """`fuentes_promedio` existe para leer el sesgo de la corrida, asi que
    tiene que contar los modelos que VOTAN. Contar uno excluido diria "3
    fuentes" sobre un consenso calculado con 2."""
    from dataclasses import replace

    inicio = date(2024, 6, 1)
    por_dia = {inicio + timedelta(days=n): _dia_de_horas(
        inicio + timedelta(days=n), True,
        modelos=("gwam+gfs_seamless", "meteofrance_wave+icon_seamless",
                 "ncep_gfswave025+ecmwf_ifs025"))
        for n in range(6)}
    assert analizar(SPOT, por_dia)["fuentes_promedio"] == pytest.approx(3.0)

    sin_gwam = replace(SPOT, modelos_excluidos=["gwam"])
    assert analizar(sin_gwam, por_dia)["fuentes_promedio"] == pytest.approx(2.0)


def test_analizar_normaliza_por_dias_cubiertos_no_por_anios_calendario():
    """Medio anio de datos con 1 ventana son ~2 ventanas/anio, no 1."""
    inicio = date(2024, 1, 1)
    por_dia = {}
    for n in range(183):
        f = inicio + timedelta(days=n)
        por_dia[f] = _dia_de_horas(f, buena=n in (0, 1))
    r = analizar(SPOT, por_dia)
    assert r["total_ventanas"] == 1
    assert 1.9 < r["ventanas_por_anio"] < 2.1


def test_analizar_reporta_los_top_dias_ordenados():
    inicio = date(2024, 6, 1)
    por_dia = {inicio + timedelta(days=n): _dia_de_horas(inicio + timedelta(days=n), True)
               for n in range(6)}
    r = analizar(SPOT, por_dia)
    scores = [d["score"] for d in r["top_dias"]]
    assert scores == sorted(scores, reverse=True)
    assert r["top_dias"][0]["fecha"] == "2024-06-01"


# --- veredicto --------------------------------------------------------------

def test_veredicto_marca_filtro_estrangulado():
    assert veredicto({"ventanas_por_anio": 2.0}) == "estrangulado"


def test_veredicto_marca_ruido():
    assert veredicto({"ventanas_por_anio": 80.0}) == "ruido"


def test_veredicto_sano_en_el_rango():
    assert veredicto({"ventanas_por_anio": 15.0}) == "sano"
    assert veredicto({"ventanas_por_anio": float(RANGO_SANO[0])}) == "sano"
    assert veredicto({"ventanas_por_anio": float(RANGO_SANO[1])}) == "sano"


def test_veredicto_distingue_bajo_de_estrangulado():
    """Entre 5 y 10 el filtro esta apretado pero no roto; no es lo mismo."""
    assert veredicto({"ventanas_por_anio": float(LIMITE_ESTRANGULADO) + 1}) == "bajo"
    assert veredicto({"ventanas_por_anio": float(LIMITE_ESTRANGULADO) - 1}) == "estrangulado"


def test_veredicto_distingue_alto_de_ruido():
    assert veredicto({"ventanas_por_anio": float(LIMITE_RUIDO) - 1}) == "alto"
    assert veredicto({"ventanas_por_anio": float(LIMITE_RUIDO) + 1}) == "ruido"


# --- coincide_la_temporada --------------------------------------------------

def test_coincide_la_temporada_acepta_ventanas_en_temporada():
    r = {"por_mes": {6: 8, 7: 6, 1: 1}, "temporada_declarada": [4, 5, 6, 7, 8, 9, 10]}
    assert coincide_la_temporada(r) is True


def test_coincide_la_temporada_rechaza_ventanas_fuera_de_temporada():
    r = {"por_mes": {12: 8, 1: 6, 6: 1}, "temporada_declarada": [4, 5, 6, 7, 8, 9, 10]}
    assert coincide_la_temporada(r) is False


def test_coincide_la_temporada_sin_ventanas_no_coincide():
    r = {"por_mes": {}, "temporada_declarada": [4, 5, 6, 7, 8, 9, 10]}
    assert coincide_la_temporada(r) is False


@pytest.mark.parametrize("spot", cargar_spots(RUTA_SPOTS), ids=lambda s: s.id)
def test_el_chequeo_de_temporada_discrimina_en_los_13_spots(spot):
    """Ningun spot tiene una temporada tan ancha que el chequeo sea vacio.

    Si un spot declarara los 12 meses, `coincide_la_temporada` daria True pase
    lo que pase y el chequeo no protegeria nada. Se verifica construyendo una
    distribucion enteramente fuera de temporada y exigiendo que la rechace.
    """
    fuera = [m for m in range(1, 13) if m not in spot.temporada]
    assert fuera, f"{spot.id} declara los 12 meses: el chequeo seria vacio"

    r_fuera = {"por_mes": {m: 5 for m in fuera},
               "temporada_declarada": spot.temporada}
    assert coincide_la_temporada(r_fuera) is False

    r_dentro = {"por_mes": {m: 5 for m in spot.temporada},
                "temporada_declarada": spot.temporada}
    assert coincide_la_temporada(r_dentro) is True


# --- obtener_historico ------------------------------------------------------

class _SesionFalsa:
    """Devuelve respuestas de archivo fijas y cuenta cuantas veces la llaman."""

    def __init__(self):
        self.llamadas = 0

    def get(self, url, params=None, timeout=None):
        self.llamadas += 1
        horas = [f"2024-06-0{d}T{h:02d}:00" for d in (1, 2) for h in range(24)]
        if "marine" in url:
            cuerpo = {"hourly": {"time": horas}}
            # Alturas distintas por modelo a proposito: `_combinar_multimodelo`
            # descarta como duplicada toda serie identica a otra ya vista, asi
            # que dos modelos con los mismos numeros contarian como uno solo.
            for m, alt in (("gwam", 2.0), ("meteofrance_wave", 2.1)):
                cuerpo["hourly"][f"swell_wave_height_{m}"] = [alt] * len(horas)
                cuerpo["hourly"][f"swell_wave_period_{m}"] = [14.0] * len(horas)
                cuerpo["hourly"][f"swell_wave_direction_{m}"] = [157.0] * len(horas)
        else:
            cuerpo = {"hourly": {"time": horas},
                      "daily": {"time": ["2024-06-01", "2024-06-02"],
                                "sunrise_gfs_seamless": ["2024-06-01T07:00", "2024-06-02T07:00"],
                                "sunset_gfs_seamless": ["2024-06-01T18:00", "2024-06-02T18:00"]}}
            # Los tres modelos de viento, no dos: `_combinar_multimodelo`
            # empareja el modelo de olas i con el de viento i, y desde que el
            # orden de MODELOS_VIENTO se eligio por alcance temporal (ver
            # surf/consenso.py) el doble tiene que traer los tres o el par
            # correspondiente se cae por falta de columna de viento.
            for m in ("gfs_seamless", "icon_seamless", "ecmwf_ifs025"):
                cuerpo["hourly"][f"wind_speed_10m_{m}"] = [5.0] * len(horas)
                cuerpo["hourly"][f"wind_direction_10m_{m}"] = [320.0] * len(horas)
        return _RespuestaFalsa(cuerpo)


class _RespuestaFalsa:
    def __init__(self, cuerpo):
        self._cuerpo = cuerpo
        self.status_code = 200

    def raise_for_status(self):
        return None

    def json(self):
        return self._cuerpo


def test_obtener_historico_devuelve_horas_multimodelo(tmp_path):
    sesion = _SesionFalsa()
    por_dia = obtener_historico(SPOT, date(2024, 6, 1), date(2024, 6, 2),
                                sesion=sesion, cache_dir=tmp_path)
    assert set(por_dia) == {date(2024, 6, 1), date(2024, 6, 2)}
    alguna = por_dia[date(2024, 6, 1)][0]
    assert isinstance(alguna, HoraMultiModelo)
    assert len(alguna.por_modelo) == 2


def test_obtener_historico_cachea_en_disco(tmp_path):
    """Sin cache, cada iteracion de calibracion re-baja 3 anios por 13 spots."""
    sesion = _SesionFalsa()
    obtener_historico(SPOT, date(2024, 6, 1), date(2024, 6, 2),
                      sesion=sesion, cache_dir=tmp_path)
    primeras = sesion.llamadas
    assert primeras > 0
    assert list(tmp_path.glob("*.json.gz"))

    obtener_historico(SPOT, date(2024, 6, 1), date(2024, 6, 2),
                      sesion=sesion, cache_dir=tmp_path)
    assert sesion.llamadas == primeras


def test_obtener_historico_no_reusa_cache_de_otro_spot(tmp_path):
    sesion = _SesionFalsa()
    obtener_historico(SPOT, date(2024, 6, 1), date(2024, 6, 2),
                      sesion=sesion, cache_dir=tmp_path)
    primeras = sesion.llamadas
    otro = SPOT.__class__(**{**SPOT.__dict__, "id": "otro", "lat": 10.0, "lon": 20.0})
    obtener_historico(otro, date(2024, 6, 1), date(2024, 6, 2),
                      sesion=sesion, cache_dir=tmp_path)
    assert sesion.llamadas > primeras


def test_obtener_historico_guarda_json_legible(tmp_path):
    sesion = _SesionFalsa()
    obtener_historico(SPOT, date(2024, 6, 1), date(2024, 6, 2),
                      sesion=sesion, cache_dir=tmp_path)
    archivo = sorted(tmp_path.glob("*.json.gz"))[0]
    with gzip.open(archivo, "rt", encoding="utf-8") as fh:
        assert "hourly" in json.load(fh)
