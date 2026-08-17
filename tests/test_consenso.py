"""Consenso entre modelos.

Rediseno de la Tarea 16. Dos cambios de fondo respecto de la version anterior:

  1. El consenso de olas se calcula entre los modelos de OLAS y el de viento
     entre los modelos de VIENTO. No hay emparejamiento posicional, asi que
     un modelo de olas correcto ya no puede quedar vetado por un viento que no
     le corresponde.
  2. El gate se aplica UNA vez, sobre el valor de consenso (la mediana), y no
     modelo por modelo. Antes una diferencia de 2 cm descartaba un modelo
     entero y con el se iba su voto.

La medida de confianza dejo de ser "cuantos pasaron" y pasa a ser cuanto
difieren entre si (`dispersion`).
"""
from datetime import date, datetime
from pathlib import Path

import pytest

from surf.consenso import (CORTE_DISPERSION_ALTA, CORTE_DISPERSION_MEDIA,
                           MODELOS_OLAS, HoraMultiModelo, consensuar,
                           dispersion_relativa, evaluar_dia_multimodelo)
from surf.score import Hora
from surf.spots import cargar_spots
from tests.test_score_gate import SPOT

RUTA_SPOTS = Path(__file__).resolve().parent.parent / "spots.yaml"


def _hora(altura=2.0, periodo=13.0, viento=5.0, direccion=157.0, viento_dir=320.0,
          de_dia=True, t=None):
    return Hora(t=t or datetime(2026, 8, 21, 9), swell_altura=altura,
                swell_periodo=periodo, swell_direccion=direccion,
                viento_kmh=viento, viento_direccion=viento_dir, es_de_dia=de_dia)


def _hmm(modelos, hora=9, viento=None):
    return HoraMultiModelo(t=datetime(2026, 8, 21, hora), es_de_dia=True,
                           por_modelo=modelos,
                           viento_por_modelo=dict(viento or {}))


def _hmm_noche(modelos, hora=3):
    t = datetime(2026, 8, 21, hora)
    return HoraMultiModelo(
        t=t, es_de_dia=False,
        por_modelo={k: Hora(t=t, swell_altura=h.swell_altura,
                            swell_periodo=h.swell_periodo,
                            swell_direccion=h.swell_direccion,
                            viento_kmh=h.viento_kmh,
                            viento_direccion=h.viento_direccion,
                            es_de_dia=False)
                    for k, h in modelos.items()})


# --- 1. olas y viento desacoplados ------------------------------------------

def test_el_viento_de_consenso_es_la_mediana_de_los_modelos_de_viento():
    """Sin emparejamiento: el viento sale de los modelos de viento, y punto."""
    hmm = _hmm({"gwam": _hora(), "mfwam": _hora(), "ncep": _hora()},
               viento={"gfs": (1.1, 320.0), "icon": (7.2, 320.0),
                       "ecmwf": (21.6, 320.0)})
    c = consensuar(hmm, SPOT)
    assert c.hora.viento_kmh == pytest.approx(7.2)


def test_el_emparejamiento_ya_no_decide_nada():
    """El mismo trio de olas y el mismo trio de vientos, repartidos al reves,
    tienen que dar exactamente el mismo consenso. Es el defecto que motivo el
    rediseno: a `ncep` --que acerto las olas-- le tocaba el viento de ECMWF y
    esa combinacion mataba el dia."""
    vientos = {"gfs": (1.1, 320.0), "icon": (7.2, 320.0), "ecmwf": (21.6, 320.0)}
    olas = {"gwam": _hora(altura=1.14, periodo=9.35),
            "mfwam": _hora(altura=0.98, periodo=8.00),
            "ncep": _hora(altura=1.94, periodo=11.40)}

    # El viento que cada Hora trae adentro es distinto en las dos versiones:
    # si el emparejamiento todavia pesara, los consensos no coincidirian.
    a = _hmm({k: _hora(altura=h.swell_altura, periodo=h.swell_periodo, viento=v[0])
              for (k, h), v in zip(olas.items(), vientos.values())}, viento=vientos)
    b = _hmm({k: _hora(altura=h.swell_altura, periodo=h.swell_periodo, viento=v[0])
              for (k, h), v in zip(olas.items(), reversed(list(vientos.values())))},
             viento=vientos)

    assert consensuar(a, SPOT).hora == consensuar(b, SPOT).hora


def test_sin_modelos_de_viento_propios_cae_a_los_que_traen_las_olas():
    """Compatibilidad: una HoraMultiModelo armada a mano (tests viejos, o un
    camino que no separa las fuentes) tiene que seguir funcionando."""
    hmm = _hmm({"a": _hora(viento=5.0), "b": _hora(viento=5.0),
                "c": _hora(viento=30.0)})
    assert consensuar(hmm, SPOT).hora.viento_kmh == pytest.approx(5.0)


def test_las_direcciones_se_promedian_con_mediana_angular():
    """350 y 10 no promedian 180."""
    hmm = _hmm({"a": _hora(direccion=170.0), "b": _hora(direccion=178.0),
                "c": _hora(direccion=115.0)},
               viento={"x": (5.0, 350.0), "y": (5.0, 10.0), "z": (5.0, 355.0)})
    c = consensuar(hmm, SPOT)
    assert c.hora.viento_direccion in (350.0, 355.0, 10.0)
    assert c.hora.swell_direccion == pytest.approx(170.0)


# --- 2. el gate se aplica a la mediana --------------------------------------

def test_la_hora_consensuada_usa_la_mediana():
    hmm = _hmm({"a": _hora(altura=1.5), "b": _hora(altura=2.0),
                "c": _hora(altura=3.0)})
    assert consensuar(hmm, SPOT).hora.swell_altura == pytest.approx(2.0)


def test_tres_modelos_que_fallan_por_motivos_distintos_igual_hacen_un_dia_bueno():
    """El caso del rediseno: ninguno de los tres pasa el gate por si solo --uno
    por altura, otro por periodo, otro por viento-- pero la mediana de cada
    variable cumple todo. Con la regla vieja de "2 de 3 pasan" el dia se perdia."""
    hmms = [_hmm({"a": _hora(altura=0.9, periodo=13.0),
                  "b": _hora(altura=2.0, periodo=8.0),
                  "c": _hora(altura=2.2, periodo=14.0)},
                 hora=h,
                 viento={"x": (2.0, 320.0), "y": (5.0, 320.0), "z": (40.0, 320.0)})
            for h in (8, 9, 10)]
    d = evaluar_dia_multimodelo(hmms, SPOT, date(2026, 8, 21))
    assert d.es_bueno is True


def test_el_swell_fantasma_de_un_solo_modelo_no_alerta():
    """Proteccion que NO se puede debilitar: un modelo ve 2 m y los otros dos
    0.5 m. La mediana da 0.5 y no hay alerta."""
    hmms = [_hmm({"a": _hora(altura=2.0), "b": _hora(altura=0.5),
                  "c": _hora(altura=0.5)}, hora=h) for h in (8, 9, 10)]
    assert consensuar(hmms[0], SPOT).hora.swell_altura == pytest.approx(0.5)
    d = evaluar_dia_multimodelo(hmms, SPOT, date(2026, 8, 21))
    assert d.es_bueno is False


def test_el_fantasma_lo_frena_la_mediana_aunque_el_desacuerdo_sea_moderado():
    """El mismo caso pero sin desacuerdo extremo, para que el rechazo NO
    pueda venir de DISPERSION_INCONCILIABLE y quede probado que es la mediana
    la que protege: 1.4 contra 0.9 y 0.9 da 0.9, por debajo del minimo."""
    from surf.consenso import DISPERSION_INCONCILIABLE

    hmms = [_hmm({"a": _hora(altura=1.4), "b": _hora(altura=0.9),
                  "c": _hora(altura=0.9)}, hora=h) for h in (8, 9, 10)]
    c = consensuar(hmms[0], SPOT)
    assert c.dispersion < DISPERSION_INCONCILIABLE
    assert c.hora.swell_altura == pytest.approx(0.9)
    d = evaluar_dia_multimodelo(hmms, SPOT, date(2026, 8, 21))
    assert d.es_bueno is False
    assert "altura" in (d.motivo_principal or "")


def test_la_mediana_es_mas_robusta_al_outlier_que_la_regla_vieja():
    """La contracara del test anterior: con dos modelos de acuerdo en que SI
    hay olas, el tercero desviado no manda. Los dos casos juntos son la prueba
    de que la mediana no debilito la proteccion, la mejoro: el outlier no
    decide en ninguna de las dos direcciones."""
    hmms = [_hmm({"a": _hora(altura=0.4), "b": _hora(altura=2.0),
                  "c": _hora(altura=2.1)}, hora=h) for h in (8, 9, 10)]
    d = evaluar_dia_multimodelo(hmms, SPOT, date(2026, 8, 21))
    assert d.es_bueno is True


def test_con_dos_fuentes_irreconciliables_el_sistema_no_opina():
    """El agujero propio de tener solo DOS fuentes: la mediana es el promedio,
    asi que no protege de un outlier. Un modelo que ve 2.0 m y otro que ve
    0.2 m promedian 1.1 m, un mar que ninguno de los dos pronostico.

    Por eso existe DISPERSION_INCONCILIABLE: cuando un modelo ve mas del
    triple que el otro no hay una lectura del mar, y el sistema se calla en
    vez de inventar el promedio."""
    from surf.consenso import DISPERSION_INCONCILIABLE

    hmms = [_hmm({"a": _hora(altura=2.0), "b": _hora(altura=0.2)}, hora=h)
            for h in (8, 9, 10)]
    assert consensuar(hmms[0], SPOT).dispersion > DISPERSION_INCONCILIABLE
    d = evaluar_dia_multimodelo(hmms, SPOT, date(2026, 8, 21))
    assert d.es_bueno is False
    assert "no coinciden" in (d.motivo_principal or "")


def test_dos_fuentes_que_discrepan_dentro_de_lo_normal_si_promedian():
    """La contracara: el rechazo por desacuerdo es para casos
    irreconciliables, no un segundo gate. 1.8 y 1.2 difieren ±20% y el dia
    sale con la mediana en 1.5."""
    hmms = [_hmm({"a": _hora(altura=1.8), "b": _hora(altura=1.2)}, hora=h)
            for h in (8, 9, 10)]
    d = evaluar_dia_multimodelo(hmms, SPOT, date(2026, 8, 21))
    assert d.es_bueno is True
    assert d.resumen["altura"] == pytest.approx(1.5)


def test_un_solo_modelo_funciona_igual():
    hmm = _hmm({"a": _hora()})
    c = consensuar(hmm, SPOT)
    assert c.fuentes_olas == 1
    assert c.hora.swell_altura == pytest.approx(2.0)


# --- el caso real que motivo el rediseno ------------------------------------

def _praia_do_rosa():
    return next(s for s in cargar_spots(RUTA_SPOTS) if s.id == "praia_do_rosa")


def test_el_caso_de_praia_do_rosa_ahora_pasa():
    """Medido el 2026-08-23 09:00 (ver el reporte de la tarea):

        gwam              1.14 m @ 9.35 s   viento gfs    1.1 km/h
        meteofrance_wave  0.98 m @ 8.00 s   viento icon   7.2 km/h
        ncep_gfswave025   1.94 m @ 11.40 s  viento ecmwf 21.6 km/h

    surf-forecast publicaba 1.8 m @ 11 s y glassy. Ninguno de los tres pasaba
    el gate solo; las medianas (1.14 m, 9.35 s, 7.2 km/h) lo pasan todas.
    """
    spot = _praia_do_rosa()
    olas = [(1.14, 9.35), (0.98, 8.00), (1.94, 11.40)]
    vientos = {"gfs": (1.1, 294.0), "icon": (7.2, 294.0), "ecmwf": (21.6, 294.0)}
    hmms = []
    for h in (8, 9, 10):
        por_modelo = {
            nombre: _hora(altura=a, periodo=p, direccion=135.0,
                          t=datetime(2026, 8, 23, h))
            for nombre, (a, p) in zip(MODELOS_OLAS, olas)
        }
        hmms.append(HoraMultiModelo(t=datetime(2026, 8, 23, h), es_de_dia=True,
                                    por_modelo=por_modelo,
                                    viento_por_modelo=vientos))
    c = consensuar(hmms[0], spot)
    assert c.hora.swell_altura == pytest.approx(1.14)
    assert c.hora.swell_periodo == pytest.approx(9.35)
    assert c.hora.viento_kmh == pytest.approx(7.2)

    d = evaluar_dia_multimodelo(hmms, spot, date(2026, 8, 23))
    assert d.es_bueno is True


# --- 3. la dispersion como medida de confianza ------------------------------

def test_la_dispersion_es_el_semirango_relativo_sobre_la_mediana():
    """Es el numero que sale impreso como "±" en el mensaje, asi que tiene que
    significar exactamente eso: 1.0 +/- 20% cubre de 0.8 a 1.2."""
    assert dispersion_relativa([0.8, 1.0, 1.2]) == pytest.approx(0.2)
    assert dispersion_relativa([2.0, 2.0, 2.0]) == pytest.approx(0.0)
    assert dispersion_relativa([1.0]) == pytest.approx(0.0)


def test_la_dispersion_toma_la_peor_de_altura_y_periodo():
    """Medido sobre 2023-2025: la dispersion de altura y la de periodo son
    casi independientes (la de altura es la mayor solo en el 51% de las
    horas), asi que mirar una sola dejaria pasar como "alta" horas donde los
    modelos discrepan fuerte en la otra."""
    hmm = _hmm({"a": _hora(altura=2.0, periodo=10.0),
                "b": _hora(altura=2.0, periodo=13.0),
                "c": _hora(altura=2.0, periodo=16.0)})
    # altura: 0. periodo: (16-10)/(2*13) = 0.2308
    assert consensuar(hmm, SPOT).dispersion == pytest.approx(6 / 26)


def test_modelos_muy_de_acuerdo_dan_concordancia_alta():
    hmm = _hmm({"a": _hora(altura=2.00), "b": _hora(altura=2.01),
                "c": _hora(altura=2.02)})
    c = consensuar(hmm, SPOT)
    assert c.dispersion < CORTE_DISPERSION_ALTA
    assert c.nivel == "alta"


def test_modelos_que_discrepan_lo_normal_dan_concordancia_media():
    disp = (CORTE_DISPERSION_ALTA + CORTE_DISPERSION_MEDIA) / 2
    hmm = _hmm({"a": _hora(altura=2.0 * (1 - disp)), "b": _hora(altura=2.0),
                "c": _hora(altura=2.0 * (1 + disp))})
    assert consensuar(hmm, SPOT).nivel == "media"


def test_modelos_que_discrepan_mucho_dan_concordancia_baja():
    hmm = _hmm({"a": _hora(altura=1.2), "b": _hora(altura=2.0),
                "c": _hora(altura=2.8)})
    c = consensuar(hmm, SPOT)
    assert c.dispersion > CORTE_DISPERSION_MEDIA
    assert c.nivel == "baja"


def test_los_cortes_salen_de_la_distribucion_medida_con_tres_fuentes():
    """Cuartiles de max(dispersion de altura, dispersion de periodo) sobre las
    5.079 horas de luz que pasan el gate con las TRES fuentes vivas
    (2025-12-09 a 2026-08-15): p25 = 0.137 y p75 = 0.287.

    La poblacion es deliberada: sobre 2023-2025 --96% de horas con solo dos
    fuentes-- los mismos cuartiles dan 0.094 y 0.192, y calibrar ahi hacia que
    en produccion, donde hay tres, casi todo saliera "baja"."""
    assert CORTE_DISPERSION_ALTA == pytest.approx(0.137)
    assert CORTE_DISPERSION_MEDIA == pytest.approx(0.287)
    assert CORTE_DISPERSION_ALTA < CORTE_DISPERSION_MEDIA


def test_el_conteo_de_cuantos_pasaron_ya_no_decide_la_etiqueta():
    """Dos modelos que pasan el gate y uno que no, pero los tres muy de
    acuerdo en el swell: la etiqueta la manda el acuerdo, no el conteo."""
    hmm = _hmm({"a": _hora(altura=2.0), "b": _hora(altura=2.0),
                "c": _hora(altura=2.0)},
               viento={"x": (2.0, 320.0), "y": (2.0, 320.0), "z": (40.0, 320.0)})
    assert consensuar(hmm, SPOT).nivel == "alta"


# --- honestidad: nunca "alta" con menos de tres fuentes ---------------------

def test_dos_modelos_identicos_no_alcanzan_para_concordancia_alta():
    """Si Open-Meteo deja de servir un modelo quedan dos. Dos de dos no es
    'alta': nunca se consulto al tercero."""
    hmm = _hmm({"a": _hora(), "b": _hora()})
    c = consensuar(hmm, SPOT)
    assert c.fuentes_olas == 2
    assert c.dispersion == pytest.approx(0.0)
    assert c.nivel == "media"


def test_un_solo_modelo_da_concordancia_baja():
    """Que no haya desacuerdo posible no es lo mismo que haya acuerdo."""
    c = consensuar(_hmm({"a": _hora()}), SPOT)
    assert c.dispersion == pytest.approx(0.0)
    assert c.nivel == "baja"


def test_el_dia_con_dos_modelos_no_reporta_concordancia_alta():
    hmms = [_hmm({"a": _hora(), "b": _hora()}, hora=h) for h in (8, 9, 10)]
    d = evaluar_dia_multimodelo(hmms, SPOT, date(2026, 8, 21))
    assert d.es_bueno is True
    assert d.concordancia != "alta"


def test_el_dia_registra_que_modelos_respondieron():
    hmms = [_hmm({"gwam+gfs": _hora(), "mfwam+icon": _hora()}, hora=h,
                 viento={"gfs_seamless": (5.0, 320.0), "icon_seamless": (6.0, 320.0)})
            for h in (8, 9, 10)]
    d = evaluar_dia_multimodelo(hmms, SPOT, date(2026, 8, 21))
    assert set(d.modelos) == {"gwam+gfs", "mfwam+icon"}
    assert set(d.modelos_viento) == {"gfs_seamless", "icon_seamless"}


def test_el_dia_reporta_la_dispersion_de_su_hora_mas_floja():
    hmms = [
        _hmm({"a": _hora(altura=2.0), "b": _hora(altura=2.0),
              "c": _hora(altura=2.0)}, hora=8),
        _hmm({"a": _hora(altura=1.4), "b": _hora(altura=2.0),
              "c": _hora(altura=2.6)}, hora=9),
        _hmm({"a": _hora(altura=2.0), "b": _hora(altura=2.0),
              "c": _hora(altura=2.0)}, hora=10),
    ]
    d = evaluar_dia_multimodelo(hmms, SPOT, date(2026, 8, 21))
    assert d.es_bueno is True
    # Dos de las tres horas tienen dispersion 0; el dia reporta la de la hora
    # floja, que es la que define la etiqueta.
    assert d.dispersion == pytest.approx(0.3)
    assert d.concordancia == "baja"


def test_el_dia_hereda_la_peor_concordancia_de_su_bloque():
    hmms = [
        _hmm({"a": _hora(), "b": _hora(), "c": _hora()}, hora=8),
        _hmm({"a": _hora(altura=1.7), "b": _hora(altura=2.0),
              "c": _hora(altura=2.3)}, hora=9),
        _hmm({"a": _hora(), "b": _hora(), "c": _hora()}, hora=10),
    ]
    d = evaluar_dia_multimodelo(hmms, SPOT, date(2026, 8, 21))
    assert d.es_bueno is True
    assert d.concordancia == "media"


# --- Critical: MODELOS_OLAS no puede duplicar la misma fuente -----------------

def test_best_match_no_esta_entre_los_modelos_de_olas():
    """best_match de la Marine API ES meteofrance_wave: verificado contra la
    API real, identicos en altura, periodo y direccion en 72/72 horas y en los
    13 spots. Tenerlos a los dos es una sola fuente votando dos veces."""
    assert "best_match" not in MODELOS_OLAS


def test_hay_al_menos_dos_fuentes_de_olas_distintas():
    assert len(set(MODELOS_OLAS)) == len(MODELOS_OLAS)
    assert len(MODELOS_OLAS) >= 2


# --- el motivo del dia ------------------------------------------------------

def _dia_con_noche_y_periodo_corto():
    """12 horas de noche + horas de luz que fallan solo por periodo corto."""
    corta = _hora(periodo=6.0)
    noche = [_hmm_noche({"a": corta, "b": corta, "c": corta}, hora=h)
             for h in range(0, 6)] + [
             _hmm_noche({"a": corta, "b": corta, "c": corta}, hora=h)
             for h in range(19, 24)]
    dia = [_hmm({"a": corta, "b": corta, "c": corta}, hora=h)
           for h in range(8, 17)]
    return noche + dia


def test_las_horas_de_noche_no_definen_el_motivo_del_dia():
    d = evaluar_dia_multimodelo(_dia_con_noche_y_periodo_corto(), SPOT,
                                date(2026, 8, 21))
    assert d.es_bueno is False
    assert "período corto" in (d.motivo_principal or "")


def test_el_motivo_es_el_de_la_mediana_no_una_mezcla_de_modelos():
    """Con el gate sobre la mediana el motivo deja de ser un veredicto sobre
    el desacuerdo y pasa a ser lo que le falto al consenso: es lo que el
    digest dominical necesita leer."""
    hmms = [_hmm({"a": _hora(periodo=6.0), "b": _hora(periodo=6.5),
                  "c": _hora(periodo=7.0)}, hora=h) for h in range(8, 17)]
    d = evaluar_dia_multimodelo(hmms, SPOT, date(2026, 8, 21))
    assert "período corto" in (d.motivo_principal or "")
    assert "6.5s" in (d.motivo_principal or "")


def test_un_dia_malo_por_periodo_corto_lo_ve_el_digest():
    """El digest dominical es la red contra los falsos negativos. Si el motivo
    principal no matchea _cerca_del_umbral, el digest queda estructuralmente
    ciego."""
    from run import _cerca_del_umbral

    d = evaluar_dia_multimodelo(_dia_con_noche_y_periodo_corto(), SPOT,
                                date(2026, 8, 21))
    assert _cerca_del_umbral(d) is True


def test_un_dia_malo_por_direccion_lo_ve_el_digest():
    from run import _cerca_del_umbral

    fuera = _hora(direccion=10.0)
    hmms = [_hmm({"a": fuera, "b": fuera, "c": fuera}, hora=h)
            for h in range(8, 17)]
    d = evaluar_dia_multimodelo(hmms, SPOT, date(2026, 8, 21))
    assert "dirección" in (d.motivo_principal or "")
    assert _cerca_del_umbral(d) is True
