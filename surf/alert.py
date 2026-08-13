"""Deteccion de ventanas y logica de persistencia.

Una ventana es una racha de dias buenos consecutivos en el mismo spot. Solo
alerta si tambien aparecio en la corrida del dia anterior: es el filtro contra
los swells fantasma que el modelo inventa y borra al dia siguiente.

Modulo puro: la fecha de hoy entra por parametro, no se consulta el reloj.
"""
from dataclasses import dataclass
from datetime import date, timedelta
from itertools import groupby

from surf.score import DiaEvaluado

DIAS_MINIMOS_VENTANA = 2
SALTO_SCORE_REALERTA = 15.0
DIAS_RETENCION_ESTADO = 30


@dataclass(frozen=True)
class Ventana:
    spot_id: str
    desde: date
    hasta: date
    dias: tuple[DiaEvaluado, ...]
    score: float


def estado_vacio() -> dict:
    return {"ultima_corrida": None, "observadas": [], "alertadas": []}


def detectar_ventanas(dias: list[DiaEvaluado]) -> list[Ventana]:
    """Agrupa dias buenos consecutivos del mismo spot en ventanas."""
    ventanas: list[Ventana] = []
    ordenados = sorted(dias, key=lambda d: (d.spot_id, d.fecha))

    for spot_id, grupo in groupby(ordenados, key=lambda d: d.spot_id):
        racha: list[DiaEvaluado] = []
        for d in grupo:
            if not d.es_bueno:
                racha = []
                continue
            if racha and d.fecha != racha[-1].fecha + timedelta(days=1):
                if len(racha) >= DIAS_MINIMOS_VENTANA:
                    ventanas.append(_armar(spot_id, racha))
                racha = []
            racha.append(d)
        if len(racha) >= DIAS_MINIMOS_VENTANA:
            ventanas.append(_armar(spot_id, racha))

    return ventanas


def _armar(spot_id: str, racha: list[DiaEvaluado]) -> Ventana:
    return Ventana(spot_id=spot_id, desde=racha[0].fecha, hasta=racha[-1].fecha,
                   dias=tuple(racha), score=max(d.score for d in racha))


def _solapa(v: Ventana, registro: dict) -> bool:
    """Dos ventanas del mismo spot son 'la misma' si sus rangos se tocan.

    El pronostico puede correr el inicio un dia sin que sea otra ventana.
    """
    if registro["spot_id"] != v.spot_id:
        return False
    return not (v.hasta < date.fromisoformat(registro["desde"])
                or v.desde > date.fromisoformat(registro["hasta"]))


def _a_registro(v: Ventana) -> dict:
    return {"spot_id": v.spot_id, "desde": v.desde.isoformat(),
            "hasta": v.hasta.isoformat(), "score": v.score}


def decidir_alertas(ventanas: list[Ventana], estado: dict,
                    hoy: date) -> tuple[list[Ventana], dict]:
    """Aplica persistencia y anti-repeticion.

    Devuelve las ventanas a alertar y el estado actualizado. El estado nuevo
    se escribe solo si la corrida completa termino bien.
    """
    ultima = estado.get("ultima_corrida")
    ultima_fecha = date.fromisoformat(ultima) if ultima else None
    # La confirmacion solo vale si la corrida anterior fue realmente ayer.
    hay_corrida_previa = ultima_fecha == hoy - timedelta(days=1)

    observadas = estado.get("observadas", [])
    alertadas = estado.get("alertadas", [])
    a_alertar: list[Ventana] = []

    for v in ventanas:
        confirmada = hay_corrida_previa and any(_solapa(v, r) for r in observadas)
        if not confirmada:
            continue

        previas = [r for r in alertadas if _solapa(v, r)]
        if not previas:
            a_alertar.append(v)
            continue

        mejor_previa = max(previas, key=lambda r: r["score"])
        se_extendio = any(v.hasta > date.fromisoformat(r["hasta"]) for r in previas)
        mejoro = v.score - mejor_previa["score"] >= SALTO_SCORE_REALERTA
        if se_extendio or mejoro:
            a_alertar.append(v)

    corte = hoy - timedelta(days=DIAS_RETENCION_ESTADO)
    nuevo = {
        "ultima_corrida": hoy.isoformat(),
        "observadas": [_a_registro(v) for v in ventanas],
        "alertadas": (
            [r for r in alertadas if date.fromisoformat(r["hasta"]) >= corte
             and not any(_solapa(v, r) for v in a_alertar)]
            + [{**_a_registro(v), "fecha_alerta": hoy.isoformat()} for v in a_alertar]
        ),
    }
    nuevo["alertadas"] = [r for r in nuevo["alertadas"]
                          if date.fromisoformat(r["hasta"]) >= corte]
    return a_alertar, nuevo
