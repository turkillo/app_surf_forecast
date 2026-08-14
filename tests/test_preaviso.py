"""Pre-avisos a 10 dias.

El swell y el viento no se pueden pronosticar con el mismo horizonte: un
groundswell generado a miles de kilometros ya esta viajando y es anticipable
con mas de una semana, pero el viento local de las 8 AM del dia 9 es ruido.
Por eso el sistema tiene dos regimenes:

  dias 0 a 6  -> gate completo (swell + viento) -> alerta confirmada
  dias 7 a 10 -> solo swell (sin gate de viento) -> pre-aviso

Estos tests cubren el regimen nuevo y su interaccion con el existente.
"""
from datetime import date, datetime, timedelta

import pytest

from run import correr
from surf.alert import (REGIMEN_ALERTA, REGIMEN_FUERA, REGIMEN_PREAVISO,
                        ULTIMO_DIA_GATE_COMPLETO, ULTIMO_DIA_PREAVISO,
                        decidir_alertas, detectar_ventanas, estado_vacio,
                        regimen, registrar_corrida)
from surf.consenso import evaluar_dia_multimodelo, HoraMultiModelo
from surf.notify import ErrorEnvio, formatear_preaviso
from surf.score import DiaEvaluado, Hora, evaluar_hora
from tests.test_score_gate import SPOT, hora

HOY = date(2026, 8, 13)

# Viento que reprueba el gate: 20 km/h onshore directo (la costa mira al 140).
VIENTO_MALO = (20.0, 140.0)
VIENTO_BUENO = (5.0, 320.0)


# --- score.py: el gate sin viento -------------------------------------------

def test_sin_gate_de_viento_un_swell_con_onshore_fuerte_pasa():
    """El criterio de viento no significa nada a 8 dias, asi que no se aplica."""
    r = evaluar_hora(hora(viento_kmh=20, viento_dir=140), SPOT, exigir_viento=False)
    assert r.pasa is True
    assert r.motivo_rechazo is None


def test_sin_gate_de_viento_los_demas_criterios_siguen_valiendo():
    """Altura, periodo, direccion y luz son fisica del swell: siguen aplicando."""
    assert evaluar_hora(hora(altura=0.6), SPOT, exigir_viento=False).pasa is False
    assert evaluar_hora(hora(altura=5.0), SPOT, exigir_viento=False).pasa is False
    assert evaluar_hora(hora(periodo=6.0), SPOT, exigir_viento=False).pasa is False
    assert evaluar_hora(hora(direccion=45.0), SPOT, exigir_viento=False).pasa is False
    assert evaluar_hora(hora(de_dia=False), SPOT, exigir_viento=False).pasa is False


def test_el_score_sin_viento_no_depende_del_viento():
    """Si el viento no se puede pronosticar, tampoco puede puntuar: dos horas
    con el mismo swell y viento opuesto tienen que sacar el mismo puntaje."""
    con_bueno = evaluar_hora(hora(viento_kmh=5, viento_dir=320), SPOT,
                             exigir_viento=False).score
    con_malo = evaluar_hora(hora(viento_kmh=20, viento_dir=140), SPOT,
                            exigir_viento=False).score
    assert con_bueno == pytest.approx(con_malo)
    assert con_bueno > 0.0


def test_el_score_sin_viento_sigue_en_la_escala_de_cien():
    """Los pesos se renormalizan: un swell perfecto sin viento tiene que dar
    ~100, no 80. Si no, los pre-avisos serian incomparables con las alertas."""
    perfecto = hora(altura=2.0, periodo=16.0, direccion=157.0,
                    viento_kmh=25, viento_dir=140)
    assert evaluar_hora(perfecto, SPOT, exigir_viento=False).score == pytest.approx(100.0)


def test_el_gate_completo_sigue_siendo_el_default():
    """Nadie debe poder colar un dia sin viento por olvidarse del parametro."""
    assert evaluar_hora(hora(viento_kmh=20, viento_dir=140), SPOT).pasa is False


# --- alert.py: el limite entre regimenes ------------------------------------

def _hmm(fecha, viento, altura=2.0, periodo=14.0, direccion=157.0, modelos=3):
    """Horas multi-modelo de un dia entero de luz."""
    horas = []
    kmh, rumbo = viento
    for x in range(7, 13):
        t = datetime(fecha.year, fecha.month, fecha.day, x)
        h = Hora(t=t, swell_altura=altura, swell_periodo=periodo,
                 swell_direccion=direccion, viento_kmh=kmh,
                 viento_direccion=rumbo, es_de_dia=True)
        horas.append(HoraMultiModelo(
            t=t, es_de_dia=True,
            por_modelo={f"olas{i}+viento{i}": h for i in range(modelos)}))
    return horas


def test_el_limite_se_calcula_desde_hoy_no_desde_un_indice_fijo():
    for n in range(0, ULTIMO_DIA_GATE_COMPLETO + 1):
        assert regimen(HOY + timedelta(days=n), HOY) == REGIMEN_ALERTA
    for n in range(ULTIMO_DIA_GATE_COMPLETO + 1, ULTIMO_DIA_PREAVISO + 1):
        assert regimen(HOY + timedelta(days=n), HOY) == REGIMEN_PREAVISO
    assert regimen(HOY + timedelta(days=ULTIMO_DIA_PREAVISO + 1), HOY) == REGIMEN_FUERA


def test_el_horizonte_del_preaviso_llega_al_dia_diez():
    assert ULTIMO_DIA_GATE_COMPLETO == 6
    assert ULTIMO_DIA_PREAVISO == 10


def test_el_limite_se_mueve_con_hoy():
    """La misma fecha cambia de regimen segun cuando se la mire."""
    fecha = HOY + timedelta(days=7)
    assert regimen(fecha, HOY) == REGIMEN_PREAVISO
    assert regimen(fecha, HOY + timedelta(days=1)) == REGIMEN_ALERTA


# --- alert.py: estado separado ----------------------------------------------

def _dia(d, spot="chicama", score=80.0):
    return DiaEvaluado(fecha=date(2026, 8, d), spot_id=spot, es_bueno=True,
                       score=score, horas_buenas=5, bloque=None, resumen=None,
                       motivo_principal=None)


def test_el_estado_vacio_trae_las_secciones_del_preaviso():
    e = estado_vacio()
    assert e["observadas_preaviso"] == []
    assert e["preavisadas"] == []


def test_registrar_el_preaviso_no_pisa_las_alertas():
    v = detectar_ventanas([_dia(21), _dia(22)])
    e1 = registrar_corrida(v, v, estado_vacio(), HOY)
    assert len(e1["alertadas"]) == 1

    e2 = registrar_corrida(v, v, e1, HOY,
                           clave_observadas="observadas_preaviso",
                           clave_enviadas="preavisadas")
    assert len(e2["alertadas"]) == 1, "la seccion de alertas se perdio"
    assert len(e2["preavisadas"]) == 1
    assert len(e2["observadas"]) == 1
    assert len(e2["observadas_preaviso"]) == 1


def test_un_preaviso_ya_mandado_no_bloquea_la_alerta_confirmada_del_mismo_swell():
    """Es el motivo por el que las secciones estan separadas: si compartieran
    lista, el pre-aviso marcaria el swell como ya avisado y la alerta
    confirmada -- la que de verdad sirve para viajar -- nunca saldria."""
    v = detectar_ventanas([_dia(21), _dia(22)])
    estado = registrar_corrida(v, [], estado_vacio(), HOY - timedelta(days=1),
                               clave_observadas="observadas_preaviso",
                               clave_enviadas="preavisadas")
    estado = registrar_corrida(v, v, estado, HOY,
                               clave_observadas="observadas_preaviso",
                               clave_enviadas="preavisadas")
    assert len(estado["preavisadas"]) == 1

    # Ahora el mismo swell entra en el rango de la alerta. Lo unico que le
    # falta es la persistencia normal, que llega de "observadas".
    estado = registrar_corrida(v, [], estado, HOY)
    a_alertar = decidir_alertas(v, estado, HOY + timedelta(days=1))
    assert len(a_alertar) == 1


def test_el_preaviso_no_se_confirma_con_las_ventanas_del_regimen_de_alerta():
    """Las observadas de cada regimen viven en su propia lista: una ventana
    vista con gate completo no puede confirmar un pre-aviso sin viento."""
    v = detectar_ventanas([_dia(21), _dia(22)])
    estado = registrar_corrida(v, [], estado_vacio(), HOY - timedelta(days=1))
    a_preavisar = decidir_alertas(v, estado, HOY,
                                  clave_observadas="observadas_preaviso",
                                  clave_enviadas="preavisadas")
    assert a_preavisar == []


def test_el_preaviso_se_manda_una_sola_vez_aunque_la_ventana_crezca():
    """Regla propia del pre-aviso: una sola vez. En el borde del horizonte la
    ventana crece un dia por corrida a medida que rueda el pronostico, y con
    la regla de re-alerta por extension mandaria un mensaje por dia."""
    claves = {"clave_observadas": "observadas_preaviso",
              "clave_enviadas": "preavisadas", "reenviar_si_crece": False}
    v1 = detectar_ventanas([_dia(21), _dia(22)])
    e1 = registrar_corrida(v1, [], estado_vacio(), HOY - timedelta(days=1),
                           clave_observadas="observadas_preaviso",
                           clave_enviadas="preavisadas")
    enviados = decidir_alertas(v1, e1, HOY, **claves)
    assert len(enviados) == 1
    e2 = registrar_corrida(v1, enviados, e1, HOY,
                           clave_observadas="observadas_preaviso",
                           clave_enviadas="preavisadas")

    v2 = detectar_ventanas([_dia(21), _dia(22), _dia(23, score=99.0)])
    assert decidir_alertas(v2, e2, HOY + timedelta(days=1), **claves) == []


def test_la_alerta_confirmada_si_se_reenvia_cuando_la_ventana_crece():
    """El regimen de alerta no cambia: sigue re-alertando si se extiende."""
    v1 = detectar_ventanas([_dia(21), _dia(22)])
    e1 = registrar_corrida(v1, [], estado_vacio(), HOY - timedelta(days=1))
    enviados = decidir_alertas(v1, e1, HOY)
    e2 = registrar_corrida(v1, enviados, e1, HOY)
    v2 = detectar_ventanas([_dia(21), _dia(22), _dia(23)])
    assert len(decidir_alertas(v2, e2, HOY + timedelta(days=1))) == 1


# --- consenso.py: el consenso degrada sin romper -----------------------------

def test_el_dia_sin_gate_de_viento_es_bueno_con_viento_horrible():
    fecha = HOY + timedelta(days=8)
    d = evaluar_dia_multimodelo(_hmm(fecha, VIENTO_MALO), SPOT, fecha,
                                exigir_viento=False)
    assert d.es_bueno is True
    assert evaluar_dia_multimodelo(_hmm(fecha, VIENTO_MALO), SPOT, fecha).es_bueno is False


def test_con_dos_fuentes_nunca_declara_concordancia_alta():
    """Regla que ya existia y que el rango 7-10 pone a prueba todo el tiempo:
    ahi quedan dos modelos de olas, o uno solo."""
    fecha = HOY + timedelta(days=8)
    d = evaluar_dia_multimodelo(_hmm(fecha, VIENTO_MALO, modelos=2), SPOT, fecha,
                                exigir_viento=False)
    assert d.es_bueno is True
    assert d.concordancia != "alta"
    assert len(d.modelos) == 2


def test_con_una_sola_fuente_la_concordancia_es_baja():
    fecha = HOY + timedelta(days=10)
    d = evaluar_dia_multimodelo(_hmm(fecha, VIENTO_MALO, modelos=1), SPOT, fecha,
                                exigir_viento=False)
    assert d.concordancia == "baja"
    assert len(d.modelos) == 1


def test_sin_ninguna_fuente_de_olas_no_rompe():
    fecha = HOY + timedelta(days=10)
    d = evaluar_dia_multimodelo([], SPOT, fecha, exigir_viento=False)
    assert d.es_bueno is False


# --- notify.py: el mensaje ---------------------------------------------------

def _ventana_preaviso(hoy, primer_dia=7, dias=3, modelos=("gwam+x", "ncep_gfswave025+y")):
    evaluados = []
    for n in range(dias):
        fecha = hoy + timedelta(days=primer_dia + n)
        d = evaluar_dia_multimodelo(_hmm(fecha, VIENTO_MALO), SPOT, fecha,
                                    exigir_viento=False)
        evaluados.append(DiaEvaluado(
            fecha=d.fecha, spot_id=d.spot_id, es_bueno=True, score=d.score,
            horas_buenas=d.horas_buenas, bloque=d.bloque, resumen=d.resumen,
            motivo_principal=None, concordancia="media", modelos=modelos,
            modelos_de_acuerdo=len(modelos)))
    return detectar_ventanas(evaluados)[0]


def test_el_preaviso_dice_que_es_un_preaviso_y_cuanto_falta():
    v = _ventana_preaviso(HOY, primer_dia=8, dias=3)
    m = formatear_preaviso(v, SPOT, HOY)
    assert "PRE-AVISO" in m
    assert SPOT.nombre in m
    assert "faltan 8 días" in m
    assert "(3 días)" in m


def test_el_preaviso_no_habla_de_viento_en_las_lineas_de_cada_dia():
    """El viento a esta distancia no se puede pronosticar: mostrarlo seria
    darle al usuario un dato que el propio sistema decidio no evaluar."""
    v = _ventana_preaviso(HOY, primer_dia=7, dias=2)
    m = formatear_preaviso(v, SPOT, HOY)
    lineas = [ln for ln in m.split("\n") if "m @ " in ln]
    assert len(lineas) == 2
    for ln in lineas:
        assert "km/h" not in ln
        assert "viento" not in ln.lower()


def test_el_preaviso_avisa_que_el_viento_falta_y_que_va_a_confirmar():
    v = _ventana_preaviso(HOY, primer_dia=7, dias=2)
    m = formatear_preaviso(v, SPOT, HOY)
    assert "El viento todavía no se puede pronosticar a esta distancia." in m
    assert "Te confirmo cuando entre en los próximos 6 días." in m


def test_el_preaviso_dice_con_cuantas_fuentes_de_olas_se_calculo():
    v = _ventana_preaviso(HOY, primer_dia=7, dias=2,
                          modelos=("gwam+x", "ncep_gfswave025+y"))
    assert "Fuentes de olas disponibles: 2 de 3" in formatear_preaviso(v, SPOT, HOY)

    v1 = _ventana_preaviso(HOY, primer_dia=9, dias=2, modelos=("ncep_gfswave025+y",))
    assert "Fuentes de olas disponibles: 1 de 3" in formatear_preaviso(v1, SPOT, HOY)


def test_el_preaviso_lleva_el_link_del_spot():
    v = _ventana_preaviso(HOY, primer_dia=7, dias=2)
    assert SPOT.url_surfforecast in formatear_preaviso(v, SPOT, HOY)


# --- run.py: el ciclo completo ----------------------------------------------

def _traer_swell(deltas, viento=VIENTO_MALO, modelos=3):
    """Devuelve un `traer` que reporta buen swell en los deltas dados."""
    def traer(spot, dias=None):
        hoy = traer.hoy
        return {hoy + timedelta(days=n): _hmm(hoy + timedelta(days=n), viento,
                                              modelos=modelos)
                for n in deltas}
    return traer


def _correr(traer, hoy, estado, enviados=None):
    traer.hoy = hoy
    enviados = [] if enviados is None else enviados
    estado, msgs = correr([SPOT], hoy, traer, enviados.append, estado)
    return estado, msgs


def test_un_swell_a_ocho_dias_genera_preaviso_y_no_alerta():
    traer = _traer_swell([8, 9, 10])
    estado, _ = _correr(traer, HOY - timedelta(days=1), estado_vacio())
    msgs = []
    estado, _ = _correr(traer, HOY, estado, msgs)
    assert len(msgs) == 1
    assert "PRE-AVISO" in msgs[0]
    assert "BUEN SWELL" not in msgs[0]


def test_la_primera_corrida_no_manda_preaviso():
    """Persistencia: un pre-aviso fantasma es tan inutil como una alerta fantasma."""
    msgs = []
    _correr(_traer_swell([8, 9]), HOY, estado_vacio(), msgs)
    assert msgs == []


def test_un_solo_dia_a_ocho_dias_no_genera_preaviso():
    traer = _traer_swell([8])
    estado, _ = _correr(traer, HOY - timedelta(days=1), estado_vacio())
    msgs = []
    _correr(traer, HOY, estado, msgs)
    assert msgs == []


def test_el_preaviso_no_se_repite_al_dia_siguiente():
    traer = _traer_swell([8, 9])
    estado, _ = _correr(traer, HOY - timedelta(days=1), estado_vacio())
    msgs = []
    estado, _ = _correr(traer, HOY, estado, msgs)
    assert len(msgs) == 1

    # Al dia siguiente el mismo swell sigue ahi (ahora en los deltas 7 y 8).
    traer2 = _traer_swell([7, 8])
    msgs2 = []
    _correr(traer2, HOY + timedelta(days=1), estado, msgs2)
    assert msgs2 == []


def test_un_preaviso_no_entregado_no_queda_registrado_y_se_reintenta():
    traer = _traer_swell([8, 9])
    estado, _ = _correr(traer, HOY - timedelta(days=1), estado_vacio())

    def explota(m):
        raise ErrorEnvio("Telegram caido")

    traer.hoy = HOY
    estado_fallido, _ = correr([SPOT], HOY, traer, explota, estado)
    assert estado_fallido["preavisadas"] == []

    # El mismo swell al dia siguiente: ahora cae en los deltas 7 y 8.
    traer2 = _traer_swell([7, 8])
    msgs = []
    _correr(traer2, HOY + timedelta(days=1), estado_fallido, msgs)
    assert len(msgs) == 1
    assert "PRE-AVISO" in msgs[0]


def test_los_dias_cercanos_no_generan_preaviso():
    """Los dias 0 a 6 se siguen evaluando con gate completo: si el viento no
    da, no hay mensaje de ningun tipo."""
    traer = _traer_swell([2, 3, 4])
    estado, _ = _correr(traer, HOY - timedelta(days=1), estado_vacio())
    msgs = []
    _correr(traer, HOY, estado, msgs)
    assert msgs == []


def test_los_dias_mas_alla_del_horizonte_se_ignoran():
    traer = _traer_swell([11, 12, 13])
    estado, _ = _correr(traer, HOY - timedelta(days=1), estado_vacio())
    msgs = []
    estado, _ = _correr(traer, HOY, estado, msgs)
    assert msgs == []
    assert estado["observadas_preaviso"] == []


def test_el_mismo_swell_da_primero_preaviso_y_despues_alerta_confirmada():
    """Es a proposito: el pre-aviso sirve para bloquear fechas, la alerta
    confirmada para viajar. Si el swell se cae en el medio, el segundo no
    llega -- y eso tambien es informacion."""
    fechas = [HOY + timedelta(days=n) for n in (8, 9, 10)]

    def traer_para(hoy, viento):
        def traer(spot, dias=None):
            return {f: _hmm(f, viento) for f in fechas}
        traer.hoy = hoy
        return traer

    # Dos corridas con el swell a 8-10 dias: sale el pre-aviso.
    estado, _ = _correr(traer_para(HOY - timedelta(days=1), VIENTO_MALO),
                        HOY - timedelta(days=1), estado_vacio())
    msgs = []
    estado, _ = _correr(traer_para(HOY, VIENTO_MALO), HOY, estado, msgs)
    assert len(msgs) == 1 and "PRE-AVISO" in msgs[0]

    # Pasan los dias y el swell entra en el rango de 6, ahora con buen viento.
    for n in range(1, 5):
        hoy = HOY + timedelta(days=n)
        msgs_dia = []
        estado, _ = _correr(traer_para(hoy, VIENTO_BUENO), hoy, estado, msgs_dia)
        if any("BUEN SWELL" in m for m in msgs_dia):
            break
    else:
        pytest.fail("el swell nunca genero la alerta confirmada")

    assert not any("PRE-AVISO" in m for m in msgs_dia), \
        "no debe repetir el pre-aviso junto con la alerta"


def test_el_preaviso_pasa_por_enviar_seguro():
    """Un fallo de Telegram en un pre-aviso no puede abortar la corrida."""
    traer = _traer_swell([8, 9])
    estado, _ = _correr(traer, HOY - timedelta(days=1), estado_vacio())

    def explota(m):
        raise ErrorEnvio("Telegram caido")

    traer.hoy = HOY
    estado_nuevo, _ = correr([SPOT], HOY, traer, explota, estado)
    assert estado_nuevo["ultima_corrida"] == HOY.isoformat()


# --- fetch.py: el rango se alarga, las llamadas no se multiplican ------------

class _RespuestaEspia:
    def __init__(self, cuerpo):
        self._cuerpo = cuerpo

    def raise_for_status(self):
        return None

    def json(self):
        return self._cuerpo


class _SesionEspia:
    def __init__(self, horas=24):
        self.llamadas = []
        self.horas = horas

    def get(self, url, params=None, timeout=None):
        self.llamadas.append((url, dict(params or {})))
        tiempos = [f"2026-08-{21 + i // 24:02d}T{i % 24:02d}:00" for i in range(self.horas)]
        if "marine" in url:
            cuerpo = {"hourly": {"time": tiempos}}
            for i, m in enumerate(("gwam", "meteofrance_wave", "ncep_gfswave025")):
                cuerpo["hourly"][f"swell_wave_height_{m}"] = [1.8 + i * 0.1] * self.horas
                cuerpo["hourly"][f"swell_wave_period_{m}"] = [14.0 + i] * self.horas
                cuerpo["hourly"][f"swell_wave_direction_{m}"] = [200.0 + i] * self.horas
        else:
            dias = sorted({t[:10] for t in tiempos})
            cuerpo = {"hourly": {"time": tiempos},
                      "daily": {"time": dias,
                                "sunrise_icon_seamless": [f"{d}T06:45" for d in dias],
                                "sunset_icon_seamless": [f"{d}T18:20" for d in dias]}}
            for i, m in enumerate(("gfs_seamless", "icon_seamless", "ecmwf_ifs025")):
                cuerpo["hourly"][f"wind_speed_10m_{m}"] = [8.0 + i] * self.horas
                cuerpo["hourly"][f"wind_direction_10m_{m}"] = [95.0 + i] * self.horas
        return _RespuestaEspia(cuerpo)


def test_el_horizonte_por_defecto_cubre_hasta_el_dia_diez():
    from surf.fetch import DIAS_PRONOSTICO, obtener_horas_multimodelo
    assert DIAS_PRONOSTICO == ULTIMO_DIA_PREAVISO + 1  # dias 0..10 inclusive

    sesion = _SesionEspia()
    obtener_horas_multimodelo(SPOT, sesion=sesion)
    for _, params in sesion.llamadas:
        assert params["forecast_days"] == DIAS_PRONOSTICO


def test_alargar_el_rango_no_multiplica_las_llamadas():
    """Pasar de 7 a 11 dias alarga el rango de cada request; sigue habiendo
    exactamente dos llamadas por spot (oleaje y viento)."""
    from surf.fetch import obtener_horas_multimodelo
    sesion = _SesionEspia()
    obtener_horas_multimodelo(SPOT, sesion=sesion)
    assert len(sesion.llamadas) == 2


def test_los_modelos_de_olas_largos_no_se_pierden_por_un_viento_corto():
    """icon_seamless muere a las 177 h y meteofrance_wave llega a las 235 h
    (medido contra la API real). Si se emparejan, la unica fuente de olas que
    cubre los dias 8 y 9 se descarta por falta de viento y el pre-aviso se
    queda sin datos justo donde lo necesita."""
    from surf.consenso import MODELOS_OLAS, MODELOS_VIENTO
    from surf.fetch import _combinar_multimodelo

    tiempos = ["2026-08-21T09:00", "2026-08-21T10:00"]
    marine = {"hourly": {"time": tiempos}}
    # gwam es el modelo de olas de rango corto: en la segunda hora ya no tiene dato.
    for m, filas in (("gwam", [(1.8, 14.0, 200.0), (None, None, None)]),
                     ("meteofrance_wave", [(1.9, 14.5, 201.0), (1.9, 14.5, 201.0)]),
                     ("ncep_gfswave025", [(1.7, 13.5, 199.0), (1.7, 13.5, 199.0)])):
        marine["hourly"][f"swell_wave_height_{m}"] = [f[0] for f in filas]
        marine["hourly"][f"swell_wave_period_{m}"] = [f[1] for f in filas]
        marine["hourly"][f"swell_wave_direction_{m}"] = [f[2] for f in filas]

    clima = {"hourly": {"time": tiempos}, "daily": {
        "time": ["2026-08-21"], "sunrise_icon_seamless": ["2026-08-21T06:45"],
        "sunset_icon_seamless": ["2026-08-21T18:20"]}}
    for m in ("gfs_seamless", "ecmwf_ifs025"):
        clima["hourly"][f"wind_speed_10m_{m}"] = [8.0, 8.0]
        clima["hourly"][f"wind_direction_10m_{m}"] = [95.0, 95.0]
    # icon_seamless es el modelo de viento de rango corto.
    clima["hourly"]["wind_speed_10m_icon_seamless"] = [7.0, None]
    clima["hourly"]["wind_direction_10m_icon_seamless"] = [97.0, None]

    por_dia = _combinar_multimodelo(marine, clima, MODELOS_OLAS, MODELOS_VIENTO)
    horas = por_dia[date(2026, 8, 21)]
    assert len(horas[0].por_modelo) == 3
    assert len(horas[1].por_modelo) == 2, (
        "un modelo de olas de largo alcance se perdio por el viento: "
        f"{sorted(horas[1].por_modelo)}")
