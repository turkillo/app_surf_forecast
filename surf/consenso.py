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

MODELOS_VIENTO = ["gfs_seamless", "icon_seamless", "ecmwf_ifs025"]
MODELOS_OLAS = ["best_match", "gwam", "meteofrance_wave"]
MINIMO_MODELOS_DE_ACUERDO = 2

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


def consensuar(hmm: HoraMultiModelo, spot: Spot) -> tuple[Hora, str, int]:
    """Devuelve la hora mediana, el nivel de concordancia y cuantos modelos pasaron."""
    horas = list(hmm.por_modelo.values())
    pasaron = sum(1 for h in horas if evaluar_hora(h, spot).pasa)

    total = len(horas)
    if pasaron == total and total >= MINIMO_MODELOS_DE_ACUERDO:
        nivel = "alta"
    elif pasaron >= MINIMO_MODELOS_DE_ACUERDO:
        nivel = "media"
    elif total == 1 and pasaron == 1:
        nivel = "alta"  # con un solo modelo no hay desacuerdo posible
    else:
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


def evaluar_dia_multimodelo(hmms: list[HoraMultiModelo], spot: Spot,
                            fecha: date) -> DiaEvaluado:
    """Igual que evaluar_dia, pero exigiendo acuerdo entre modelos."""
    vacio = DiaEvaluado(fecha=fecha, spot_id=spot.id, es_bueno=False, score=0.0,
                        horas_buenas=0, bloque=None, resumen=None,
                        motivo_principal=None, concordancia="baja")
    if not hmms:
        return vacio

    evaluadas: list[HoraEvaluada] = []
    niveles: dict[datetime, str] = {}

    for hmm in sorted(hmms, key=lambda x: x.t):
        mediana, nivel, pasaron = consensuar(hmm, spot)
        niveles[hmm.t] = nivel
        if pasaron < min(MINIMO_MODELOS_DE_ACUERDO, len(hmm.por_modelo)):
            evaluadas.append(HoraEvaluada(
                hora=mediana, pasa=False,
                motivo_rechazo=f"los modelos no coinciden ({pasaron} de {len(hmm.por_modelo)})",
                score=0.0, clase_viento="",
            ))
        else:
            evaluadas.append(evaluar_hora(mediana, spot))

    bloques = [b for b in _bloques_consecutivos(evaluadas)
               if len(b) >= HORAS_MINIMAS_CONSECUTIVAS]

    if not bloques:
        motivos = Counter(e.motivo_rechazo for e in evaluadas if e.motivo_rechazo)
        return DiaEvaluado(
            fecha=fecha, spot_id=spot.id, es_bueno=False, score=0.0,
            horas_buenas=sum(1 for e in evaluadas if e.pasa), bloque=None,
            resumen=None,
            motivo_principal=motivos.most_common(1)[0][0] if motivos else None,
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
    # conservador, que es el que corresponde para decidir un viaje.
    peor = min((niveles[e.hora.t] for e in mejor),
               key=lambda n: _ORDEN_CONCORDANCIA[n])

    return DiaEvaluado(
        fecha=fecha, spot_id=spot.id, es_bueno=True, score=mejor_score,
        horas_buenas=sum(1 for e in evaluadas if e.pasa),
        bloque=(mejor[0].hora.t, mejor[-1].hora.t),
        resumen=_resumir(mejor), motivo_principal=None, concordancia=peor,
    )
