"""Exclusion de un modelo de olas en un spot puntual.

El gate exige que la condicion pase en 2 modelos. Donde un modelo esta medido
como sesgado en ese punto --gwam devuelve el 63 % de la altura real en
`huanchaco` y el 189 % en `lobitos`--, ese modelo le veta el aviso al que mide
bien. Este campo permite sacarlo de la votacion CON evidencia, en vez de bajar
el liston del consenso para todos.
"""
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path

import pytest
import yaml

from surf.consenso import (MODELOS_OLAS, HoraMultiModelo, consensuar,
                           evaluar_dia_multimodelo)
from surf.score import Hora
from surf.spots import cargar_spots
from tests.test_score_gate import SPOT
from tests.test_spots import FIXTURE, _escribir


# --- esquema y validacion ---------------------------------------------------

def test_sin_el_campo_no_se_excluye_ningun_modelo(tmp_path):
    s = cargar_spots(_escribir(tmp_path, FIXTURE))[0]
    assert list(s.modelos_excluidos) == []


def test_carga_la_lista_de_modelos_excluidos(tmp_path):
    yml = FIXTURE + "  modelos_excluidos: [gwam]\n"
    s = cargar_spots(_escribir(tmp_path, yml))[0]
    assert list(s.modelos_excluidos) == ["gwam"]


def test_rechaza_un_modelo_que_no_existe(tmp_path):
    yml = FIXTURE + "  modelos_excluidos: [gwan]\n"
    with pytest.raises(ValueError) as e:
        cargar_spots(_escribir(tmp_path, yml))
    # El mensaje tiene que ser accionable: decir cual es el nombre invalido y
    # cuales son los validos, porque el error tipico es un typo.
    assert "gwan" in str(e.value)
    for m in MODELOS_OLAS:
        assert m in str(e.value)


def test_rechaza_quedarse_con_menos_de_dos_fuentes(tmp_path):
    """Con una sola fuente el consenso deja de existir: un modelo solo no
    puede desmentirse a si mismo. Es peor que el problema que arregla."""
    yml = FIXTURE + "  modelos_excluidos: [gwam, meteofrance_wave]\n"
    with pytest.raises(ValueError) as e:
        cargar_spots(_escribir(tmp_path, yml))
    assert "2" in str(e.value)
    assert "test_spot" in str(e.value)


def test_rechaza_nombres_repetidos(tmp_path):
    """Repetir un nombre no excluye dos fuentes; si se contara como dos, el
    limite de fuentes minimas se dispararia por el motivo equivocado."""
    yml = FIXTURE + "  modelos_excluidos: [gwam, gwam]\n"
    with pytest.raises(ValueError) as e:
        cargar_spots(_escribir(tmp_path, yml))
    assert "gwam" in str(e.value)


def test_rechaza_un_valor_que_no_es_lista(tmp_path):
    yml = FIXTURE + "  modelos_excluidos: gwam\n"
    with pytest.raises(ValueError, match="modelos_excluidos"):
        cargar_spots(_escribir(tmp_path, yml))


def test_la_lista_vacia_es_valida(tmp_path):
    yml = FIXTURE + "  modelos_excluidos: []\n"
    s = cargar_spots(_escribir(tmp_path, yml))[0]
    assert list(s.modelos_excluidos) == []


# --- consenso ---------------------------------------------------------------

def _hora(altura=2.0, periodo=13.0, viento=5.0, direccion=157.0,
          viento_dir=320.0, de_dia=True, t=None):
    return Hora(t=t or datetime(2026, 8, 21, 9), swell_altura=altura,
                swell_periodo=periodo, swell_direccion=direccion,
                viento_kmh=viento, viento_direccion=viento_dir, es_de_dia=de_dia)


def _hmm(modelos, hora=9):
    return HoraMultiModelo(t=datetime(2026, 8, 21, hora), es_de_dia=True,
                           por_modelo=modelos)


SPOT_SIN_GWAM = replace(SPOT, modelos_excluidos=["gwam"])


def test_consensuar_no_cuenta_el_modelo_excluido():
    """El modelo excluido votaba; sacarlo tiene que bajar el conteo de fuentes
    y con el la etiqueta, porque "alta" exige tres opiniones."""
    hmm = _hmm({"gwam+gfs_seamless": _hora(),
                "meteofrance_wave+icon_seamless": _hora(),
                "ncep_gfswave025+ecmwf_ifs025": _hora()})
    c = consensuar(hmm, SPOT)
    assert (c.nivel, c.fuentes_olas) == ("alta", 3)

    c = consensuar(hmm, SPOT_SIN_GWAM)
    assert c.fuentes_olas == 2
    # "alta" exige tres opiniones; con dos fuentes no se puede afirmar.
    assert c.nivel == "media"


def test_el_modelo_excluido_no_arrastra_la_mediana():
    """Es el caso de `huanchaco`: gwam lee la mitad y hunde la mediana de
    altura, que es el numero que despues se compara contra min_altura."""
    hmm = _hmm({"gwam+gfs_seamless": _hora(altura=0.6),
                "meteofrance_wave+icon_seamless": _hora(altura=1.8),
                "ncep_gfswave025+ecmwf_ifs025": _hora(altura=1.7)})
    con_gwam = consensuar(hmm, SPOT).hora
    sin_gwam = consensuar(hmm, SPOT_SIN_GWAM).hora
    assert con_gwam.swell_altura == 1.7
    assert sin_gwam.swell_altura == pytest.approx(1.75)


def test_el_modelo_excluido_no_veta_el_dia():
    """El caso que motiva la tarea: el modelo excluido ve 0.5 m donde el otro
    ve 2.0 m. Con los dos adentro no hay una lectura del mar --difieren
    ±60%, mas que DISPERSION_INCONCILIABLE-- y el dia se cae."""
    def dia(hora):
        return _hmm({"gwam+gfs_seamless": _hora(altura=0.5, t=datetime(2026, 8, 21, hora)),
                     "meteofrance_wave+icon_seamless": _hora(t=datetime(2026, 8, 21, hora))},
                    hora=hora)

    hmms = [dia(h) for h in (9, 10, 11, 12)]
    assert evaluar_dia_multimodelo(hmms, SPOT, date(2026, 8, 21)).es_bueno is False
    d = evaluar_dia_multimodelo(hmms, SPOT_SIN_GWAM, date(2026, 8, 21))
    assert d.es_bueno is True
    assert d.concordancia == "baja", "una sola fuente no es acuerdo"
    assert d.modelos == ("meteofrance_wave+icon_seamless",)


def test_excluir_un_modelo_de_olas_no_toca_el_consenso_de_viento():
    """Desde la Tarea 16 el viento se consensua entre los modelos de VIENTO, y
    ninguno de ellos se excluye nunca. Sacar una fuente de olas no puede mover
    el viento con el que se evalua el dia."""
    hmm = HoraMultiModelo(
        t=datetime(2026, 8, 21, 9), es_de_dia=True,
        por_modelo={"gwam+gfs_seamless": _hora(viento=25.0, viento_dir=140.0),
                    "meteofrance_wave+icon_seamless": _hora(viento=3.0, viento_dir=320.0)},
        viento_por_modelo={"gfs_seamless": (5.0, 320.0),
                           "icon_seamless": (6.0, 322.0),
                           "ecmwf_ifs025": (7.0, 318.0)})
    con_gwam = consensuar(hmm, SPOT).hora
    sin_gwam = consensuar(hmm, SPOT_SIN_GWAM).hora
    # Medianas de los TRES modelos de viento: 6.0 km/h y 320 grados. Ninguno
    # de los dos vientos que traen las Horas de olas (25 y 3 km/h) participa.
    assert con_gwam.viento_kmh == sin_gwam.viento_kmh == 6.0
    assert con_gwam.viento_direccion == sin_gwam.viento_direccion == 320.0


def test_la_exclusion_no_hace_match_parcial_de_nombres():
    """El nombre del par es 'olas+viento'. Excluir 'gwam' saca gwam, no
    cualquier modelo cuyo nombre lo contenga."""
    hmm = _hmm({"gwam+gfs_seamless": _hora(),
                "meteofrance_wave+icon_seamless": _hora()})
    c = consensuar(hmm, replace(SPOT, modelos_excluidos=["gwa"]))
    assert c.fuentes_olas == 2, "un prefijo no es un nombre de modelo"


def test_una_hora_sin_modelos_utiles_no_rompe_ni_pasa():
    """Si la unica fuente presente a esa hora es la excluida, la hora se cae:
    no hay sobre que opinar. No puede explotar ni contarse como buena."""
    hmms = [_hmm({"gwam+gfs_seamless": _hora(t=datetime(2026, 8, 21, h))}, hora=h)
            for h in (9, 10, 11, 12)]
    d = evaluar_dia_multimodelo(hmms, SPOT_SIN_GWAM, date(2026, 8, 21))
    assert d.es_bueno is False
    assert d.horas_buenas == 0


def test_el_dia_sin_exclusiones_da_exactamente_lo_mismo():
    """Control: un spot sin el campo tiene que dar el mismo resultado que
    antes de que el campo existiera."""
    hmms = [_hmm({"gwam+gfs_seamless": _hora(t=datetime(2026, 8, 21, h)),
                  "meteofrance_wave+icon_seamless": _hora(t=datetime(2026, 8, 21, h)),
                  "ncep_gfswave025+ecmwf_ifs025": _hora(t=datetime(2026, 8, 21, h))},
                 hora=h)
            for h in (9, 10, 11, 12)]
    d = evaluar_dia_multimodelo(hmms, SPOT, date(2026, 8, 21))
    assert d.es_bueno is True
    assert d.concordancia == "alta"
    assert d.modelos_de_acuerdo == 3


# --- mensaje ----------------------------------------------------------------

def test_el_denominador_de_fuentes_descuenta_las_exclusiones():
    """"1 de 3" seria mentira en un spot donde solo se consultan 2 modelos."""
    from surf.alert import Ventana
    from surf.notify import formatear_preaviso
    from surf.score import DiaEvaluado

    def dia(d):
        return DiaEvaluado(
            fecha=date(2026, 8, d), spot_id=SPOT.id, es_bueno=True, score=80.0,
            horas_buenas=5, bloque=(datetime(2026, 8, d, 9), datetime(2026, 8, d, 12)),
            resumen={"altura": 1.8, "periodo": 12.0, "direccion": 157.0,
                     "viento_kmh": 5.0, "viento_direccion": 320.0},
            motivo_principal=None, concordancia="baja",
            modelos=("meteofrance_wave+icon_seamless",), modelos_de_acuerdo=1)

    v = Ventana(spot_id=SPOT.id, desde=date(2026, 8, 21), hasta=date(2026, 8, 22),
                dias=(dia(21), dia(22)), score=80.0)
    assert "Fuentes de olas disponibles: 1 de 2" in formatear_preaviso(
        v, SPOT_SIN_GWAM, date(2026, 8, 14))
    assert "Fuentes de olas disponibles: 1 de 3" in formatear_preaviso(
        v, SPOT, date(2026, 8, 14))


def test_la_linea_de_concordancia_no_reclama_una_fuente_que_no_se_consulta():
    """En un spot con exclusion, 2 de 2 es cobertura COMPLETA. Decir "solo 2 de
    3 fuentes disponibles" ahi seria reportar como falta algo que se saco a
    proposito."""
    from surf.alert import Ventana
    from surf.notify import formatear_alerta
    from surf.score import DiaEvaluado

    def dia(d):
        return DiaEvaluado(
            fecha=date(2026, 8, d), spot_id=SPOT.id, es_bueno=True, score=80.0,
            horas_buenas=5, bloque=(datetime(2026, 8, d, 9), datetime(2026, 8, d, 12)),
            resumen={"altura": 1.8, "periodo": 12.0, "direccion": 157.0,
                     "viento_kmh": 5.0, "viento_direccion": 320.0},
            motivo_principal=None, concordancia="media",
            modelos=("meteofrance_wave+icon_seamless",
                     "ncep_gfswave025+ecmwf_ifs025"),
            modelos_de_acuerdo=2)

    v = Ventana(spot_id=SPOT.id, desde=date(2026, 8, 21), hasta=date(2026, 8, 22),
                dias=(dia(21), dia(22)), score=80.0)
    assert "de 3 fuentes disponibles" in formatear_alerta(v, SPOT)
    assert "fuentes disponibles" not in formatear_alerta(v, SPOT_SIN_GWAM)


# --- el YAML de produccion --------------------------------------------------

def _crudos():
    return yaml.safe_load(Path("spots.yaml").read_text(encoding="utf-8"))


def test_las_exclusiones_reales_son_las_documentadas():
    """Si aparece una exclusion nueva sin pasar por la medicion, este test la
    frena. La lista sale de docs/resultados-backtest.md, seccion de ratios."""
    reales = {s.id: list(s.modelos_excluidos)
              for s in cargar_spots(Path("spots.yaml")) if s.modelos_excluidos}
    assert reales == {"lobitos": ["gwam"]}


def test_huanchaco_no_excluye_gwam_aunque_la_medicion_lo_justifique():
    """La evidencia da (gwam/SF = 0.63, gwam/mf = 0.50 en 13110 horas) pero
    ncep_gfswave025 esta enmascarado en ese punto: sacar gwam deja UNA fuente
    viva. Medido: el backtest salta de 20.7 a 41.0 ventanas/anio y la
    estacionalidad se cae a NO COINCIDE. Este test existe para que nadie lo
    "arregle" mirando solo el volumen."""
    spots = {s.id: s for s in cargar_spots(Path("spots.yaml"))}
    assert list(spots["huanchaco"].modelos_excluidos) == []


def test_ningun_spot_queda_con_menos_de_dos_fuentes():
    for s in cargar_spots(Path("spots.yaml")):
        quedan = len(MODELOS_OLAS) - len(s.modelos_excluidos)
        assert quedan >= 2, f"{s.id} quedaria con {quedan} fuente(s) de olas"


def test_cada_exclusion_lleva_su_evidencia_en_el_yaml():
    """La exclusion es una afirmacion sobre la realidad ("este modelo mide mal
    aca"), asi que el archivo tiene que traer el numero y la fecha de la
    medicion. Sin eso, dentro de seis meses es una linea que nadie puede
    auditar."""
    texto = Path("spots.yaml").read_text(encoding="utf-8")
    con_exclusion = [c["id"] for c in _crudos() if c.get("modelos_excluidos")]
    assert con_exclusion, "no hay exclusiones que verificar"

    for spot_id in con_exclusion:
        bloque = texto.split(f"- id: {spot_id}\n")[1].split("\n- id:")[0]
        lineas = bloque.splitlines()
        i = next(n for n, ln in enumerate(lineas)
                 if ln.strip().startswith("modelos_excluidos:"))
        comentario = "\n".join(lineas[max(0, i - 8):i + 1])
        assert "ratio" in comentario.lower(), (
            f"{spot_id}: la exclusion no documenta el ratio medido")
        assert "2026-" in comentario, (
            f"{spot_id}: la exclusion no documenta la fecha de la medicion")
