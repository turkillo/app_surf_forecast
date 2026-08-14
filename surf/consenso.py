"""Consenso entre modelos meteorologicos.

Reemplaza la funcion que cumple Windguru --comparar GFS, ICON y ECMWF lado a
lado-- calculandola en vez de mostrarla. Windguru no se puede usar como fuente:
sus terminos prohiben el uso de sus datos en software propio. Los modelos que
muestra son publicos y Open-Meteo los sirve directamente.

Regla: el gate tiene que pasar en al menos MINIMO_MODELOS_DE_ACUERDO modelos.
Un swell fantasma rara vez aparece en tres modelos independientes a la vez.

Modulo puro: sin red ni reloj.
"""
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime
from statistics import median

from surf.score import (HORAS_MINIMAS_CONSECUTIVAS, DiaEvaluado, Hora,
                        HoraEvaluada, evaluar_hora, _bloques_consecutivos,
                        _resumir)
from surf.spots import Spot

# El orden importa: `_combinar_multimodelo` empareja el modelo de olas i con
# el modelo de viento i, y si el de viento se queda sin datos antes, la fila
# entera se descarta y se pierde esa fuente de olas. Medido contra la API real
# con forecast_days=11:
#
#   olas    gwam 169 h · meteofrance_wave 235 h · ncep_gfswave025 264 h
#   viento  icon_seamless 177 h · ecmwf_ifs025 264 h · gfs_seamless 264 h
#
# Los pares quedan gwam+ICON, meteofrance+ECMWF, ncep+GFS: cada modelo de olas
# va con uno de viento que llega por lo menos igual de lejos. Con el orden
# anterior (gfs, icon, ecmwf), meteofrance quedaba atado a icon y los dias 8 y
# 9 --el corazon del pre-aviso-- perdian su unica fuente de olas util.
MODELOS_VIENTO = ["icon_seamless", "ecmwf_ifs025", "gfs_seamless"]

# Fuentes de olas GENUINAMENTE distintas. best_match de la Marine API no es
# una fuente propia: es meteofrance_wave con otro nombre (verificado contra la
# API real: identicos en altura, periodo y direccion en 72/72 horas y en los
# 13 spots). Tenerlo aca hacia que una sola fuente votara dos veces y que gwam
# --el unico que realmente difiere-- quedara en minoria permanente.
#
# ncep_gfswave025 si es independiente, pero su grilla de 0.25 grados deja 5 de
# los 13 spots en una celda enmascarada como tierra y devuelve 0.0/0.0/0 las
# 72 horas. Ese 0.0 se descarta como dato faltante en fetch, no se toma como
# mar planchado. En esos spots el consenso queda con dos fuentes y el sistema
# lo dice: nunca reporta concordancia alta.
MODELOS_OLAS = ["gwam", "meteofrance_wave", "ncep_gfswave025"]

MINIMO_MODELOS_DE_ACUERDO = 2
# "Alta" es la etiqueta que le dice al usuario que puede manejar cuatro horas
# sin chequear nada mas. No se puede afirmar con menos de tres fuentes: si un
# modelo no respondio, no hay tres opiniones, hay dos.
MINIMO_MODELOS_PARA_ALTA = 3

_ORDEN_CONCORDANCIA = {"alta": 2, "media": 1, "baja": 0}


@dataclass(frozen=True)
class HoraMultiModelo:
    t: datetime
    es_de_dia: bool
    por_modelo: dict[str, Hora]


def _mediana_angular(angulos: list[float]) -> float:
    """Mediana de direcciones. Toma el valor central del conjunto ordenado
    por cercania al primero, para no promediar angulos que cruzan el 0."""
    if len(angulos) == 1:
        return angulos[0]
    ref = angulos[0]
    ordenados = sorted(angulos, key=lambda a: ((a - ref + 180) % 360) - 180)
    return ordenados[len(ordenados) // 2]


def consensuar(hmm: HoraMultiModelo, spot: Spot,
               exigir_viento: bool = True) -> tuple[Hora, str, int]:
    """Devuelve la hora mediana, el nivel de concordancia y cuantos modelos pasaron."""
    horas = list(hmm.por_modelo.values())
    pasaron = sum(1 for h in horas if evaluar_hora(h, spot, exigir_viento).pasa)

    total = len(horas)
    if pasaron == total and total >= MINIMO_MODELOS_PARA_ALTA:
        nivel = "alta"
    elif pasaron >= MINIMO_MODELOS_DE_ACUERDO:
        nivel = "media"
    else:
        # Incluye el caso de un solo modelo: que no haya desacuerdo posible
        # no es lo mismo que haya acuerdo. Una sola fuente es el escenario
        # de falso positivo que este modulo existe para evitar.
        nivel = "baja"

    mediana = Hora(
        t=hmm.t,
        swell_altura=median(h.swell_altura for h in horas),
        swell_periodo=median(h.swell_periodo for h in horas),
        swell_direccion=_mediana_angular([h.swell_direccion for h in horas]),
        viento_kmh=median(h.viento_kmh for h in horas),
        viento_direccion=_mediana_angular([h.viento_direccion for h in horas]),
        es_de_dia=hmm.es_de_dia,
    )
    return mediana, nivel, pasaron


def _categoria(motivo: str | None) -> str | None:
    """Motivo sin los valores medidos.

    Los motivos son texto de cara al usuario y llevan el numero adentro
    ("periodo corto (6.0s, minimo 9.0s)"), asi que tres modelos que rechazan
    por lo mismo producen tres strings distintos. Comparar el string completo
    haria pasar por desacuerdo lo que es coincidencia.
    """
    if motivo is None:
        return None
    return motivo.split("(")[0].strip()


def _motivo_de_rechazo(hmm: HoraMultiModelo, mediana: Hora, spot: Spot,
                       pasaron: int, exigir_viento: bool = True) -> str:
    """Por que se rechaza una hora que no junto los votos necesarios.

    Si TODOS los modelos rechazan la hora por el mismo motivo, ese es el
    motivo real y hay que conservarlo: a las 3 AM los tres modelos coinciden
    perfectamente en que es de noche, decir "los modelos no coinciden" es
    falso y ademas tapa el motivo que el digest necesita leer.
    """
    motivos = [evaluar_hora(h, spot, exigir_viento).motivo_rechazo
               for h in hmm.por_modelo.values()]
    categorias = {_categoria(m) for m in motivos}
    if len(categorias) == 1 and None not in categorias:
        # Se prefiere el motivo de la hora mediana, que es la que el resto del
        # sistema reporta; si la mediana no cae en la misma categoria, sirve
        # cualquiera de los modelos porque todos dicen lo mismo.
        de_mediana = evaluar_hora(mediana, spot, exigir_viento).motivo_rechazo
        if _categoria(de_mediana) in categorias:
            return de_mediana
        return motivos[0]
    return f"los modelos no coinciden ({pasaron} de {len(hmm.por_modelo)})"


def _motivo_principal(evaluadas: list[HoraEvaluada],
                      de_dia: dict[datetime, bool]) -> str | None:
    """Motivo dominante del dia, contado SOLO sobre las horas de luz.

    Hay ~12 horas de noche por dia y todas se rechazan por la misma razon, asi
    que si entraran en la cuenta ganarian siempre y el motivo del dia seria
    "fuera de horas de luz" para todos los dias del ano. Eso deja ciego al
    digest dominical, que es la red contra los falsos negativos.
    """
    def contar(horas: list[HoraEvaluada]) -> str | None:
        # Se cuenta por categoria, no por string completo: si no, "periodo
        # corto (6.0s...)" y "periodo corto (6.5s...)" se reparten los votos
        # y puede ganar un motivo que aparecio una sola vez.
        con_motivo = [e for e in horas if e.motivo_rechazo]
        if not con_motivo:
            return None
        categorias = Counter(_categoria(e.motivo_rechazo) for e in con_motivo)
        gana = categorias.most_common(1)[0][0]
        return next(e.motivo_rechazo for e in con_motivo
                    if _categoria(e.motivo_rechazo) == gana)

    luz = [e for e in evaluadas if de_dia.get(e.hora.t, e.hora.es_de_dia)]
    # Si el dia no tiene ninguna hora de luz (o ninguna con motivo), se cae al
    # conjunto completo antes que devolver None.
    return contar(luz) or contar(evaluadas)


def evaluar_dia_multimodelo(hmms: list[HoraMultiModelo], spot: Spot,
                            fecha: date,
                            exigir_viento: bool = True) -> DiaEvaluado:
    """Igual que evaluar_dia, pero exigiendo acuerdo entre modelos.

    `exigir_viento=False` es el regimen de pre-aviso (dias 7 a 10): se pide
    acuerdo entre modelos igual que siempre, pero solo sobre el swell. En ese
    rango quedan menos fuentes de olas vivas, asi que la etiqueta de
    concordancia baja sola -- la regla de no declarar "alta" con menos de
    MINIMO_MODELOS_PARA_ALTA fuentes se sigue aplicando sin cambios.
    """
    vacio = DiaEvaluado(fecha=fecha, spot_id=spot.id, es_bueno=False, score=0.0,
                        horas_buenas=0, bloque=None, resumen=None,
                        motivo_principal=None, concordancia="baja")
    if not hmms:
        return vacio

    evaluadas: list[HoraEvaluada] = []
    niveles: dict[datetime, str] = {}
    modelos: dict[datetime, tuple[str, ...]] = {}
    acuerdos: dict[datetime, int] = {}
    de_dia: dict[datetime, bool] = {}

    for hmm in sorted(hmms, key=lambda x: x.t):
        mediana, nivel, pasaron = consensuar(hmm, spot, exigir_viento)
        niveles[hmm.t] = nivel
        modelos[hmm.t] = tuple(hmm.por_modelo)
        acuerdos[hmm.t] = pasaron
        de_dia[hmm.t] = hmm.es_de_dia
        if pasaron < min(MINIMO_MODELOS_DE_ACUERDO, len(hmm.por_modelo)):
            evaluadas.append(HoraEvaluada(
                hora=mediana, pasa=False,
                motivo_rechazo=_motivo_de_rechazo(hmm, mediana, spot, pasaron,
                                                  exigir_viento),
                score=0.0, clase_viento="",
            ))
        else:
            evaluadas.append(evaluar_hora(mediana, spot, exigir_viento))

    bloques = [b for b in _bloques_consecutivos(evaluadas)
               if len(b) >= HORAS_MINIMAS_CONSECUTIVAS]

    if not bloques:
        return DiaEvaluado(
            fecha=fecha, spot_id=spot.id, es_bueno=False, score=0.0,
            horas_buenas=sum(1 for e in evaluadas if e.pasa), bloque=None,
            resumen=None,
            motivo_principal=_motivo_principal(evaluadas, de_dia),
            concordancia="baja",
        )

    mejor: list[HoraEvaluada] | None = None
    mejor_score = -1.0
    for bloque in bloques:
        for i in range(len(bloque) - HORAS_MINIMAS_CONSECUTIVAS + 1):
            ventana = bloque[i:i + HORAS_MINIMAS_CONSECUTIVAS]
            s = sum(e.score for e in ventana) / len(ventana)
            if s > mejor_score:
                mejor_score, mejor = s, ventana

    assert mejor is not None
    # El dia hereda la PEOR concordancia de su mejor bloque: es el dato
    # conservador, que es el que corresponde para decidir un viaje. Los
    # nombres de los modelos y cuantos coincidieron salen de esa misma hora,
    # para que el mensaje describa exactamente la hora que define la etiqueta.
    t_peor = min((e.hora.t for e in mejor),
                 key=lambda t: (_ORDEN_CONCORDANCIA[niveles[t]], acuerdos[t]))

    return DiaEvaluado(
        fecha=fecha, spot_id=spot.id, es_bueno=True, score=mejor_score,
        horas_buenas=sum(1 for e in evaluadas if e.pasa),
        bloque=(mejor[0].hora.t, mejor[-1].hora.t),
        resumen=_resumir(mejor), motivo_principal=None,
        concordancia=niveles[t_peor], modelos=modelos[t_peor],
        modelos_de_acuerdo=acuerdos[t_peor],
    )
