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

# --- Los dos regimenes del sistema -----------------------------------------
#
# El swell y el viento no se pueden pronosticar con el mismo horizonte. Un
# groundswell generado por una tormenta a miles de kilometros ya esta
# viajando: es fisica en curso y se anticipa con una semana o mas. El viento
# local de las 8 AM del dia 9 es esencialmente impredecible. Estirar el gate
# completo a 10 dias no daria mas anticipacion, daria ruido.
#
# Hasta el dia 6 inclusive corre el gate completo y sale una alerta
# confirmada. Del 7 al 10 se evalua solo el swell y sale un pre-aviso.
#
# El techo es 10 y no 14 por cobertura de los modelos (medido contra la API):
# a partir del dia 7 se cae gwam (olas, 169 h) e icon (viento, 177 h), y a
# partir del dia 10 la unica fuente de olas viva es la de NOAA (ncep_gfswave025
# o su respaldo ncep_gfswave016), que ademas esta enmascarada por tierra en 4
# de los 13 spots. El respaldo NO alarga el horizonte: las dos grillas de NOAA
# llegan a las mismas 264 h, asi que el dia 10 sigue quedando con una sola
# fuente en todos los spots y el pre-aviso lo sigue rechazando.
ULTIMO_DIA_GATE_COMPLETO = 6
ULTIMO_DIA_PREAVISO = 10

REGIMEN_ALERTA = "alerta"
REGIMEN_PREAVISO = "preaviso"
REGIMEN_FUERA = "fuera"

# Secciones de state.json. Las del pre-aviso son propias y NO se mezclan con
# las de las alertas: si compartieran lista, un pre-aviso ya mandado marcaria
# el swell como avisado y bloquearia la alerta confirmada del mismo swell,
# que es justo el mensaje que sirve para viajar.
CLAVE_OBSERVADAS = "observadas"
CLAVE_ALERTADAS = "alertadas"
CLAVE_OBSERVADAS_PREAVISO = "observadas_preaviso"
CLAVE_PREAVISADAS = "preavisadas"


def regimen(fecha: date, hoy: date) -> str:
    """Que regimen le toca a una fecha, medido desde `hoy`.

    `hoy` entra por parametro a proposito: el limite entre regimenes se mueve
    todos los dias, y un indice fijo sobre la lista del pronostico lo
    congelaria en la posicion equivocada apenas la API devolviera un dia de
    mas o de menos.
    """
    dias = (fecha - hoy).days
    if dias <= ULTIMO_DIA_GATE_COMPLETO:
        return REGIMEN_ALERTA
    if dias <= ULTIMO_DIA_PREAVISO:
        return REGIMEN_PREAVISO
    return REGIMEN_FUERA


@dataclass(frozen=True)
class Ventana:
    spot_id: str
    desde: date
    hasta: date
    dias: tuple[DiaEvaluado, ...]
    score: float


def estado_vacio() -> dict:
    return {"ultima_corrida": None,
            CLAVE_OBSERVADAS: [], CLAVE_ALERTADAS: [],
            CLAVE_OBSERVADAS_PREAVISO: [], CLAVE_PREAVISADAS: []}


def detectar_ventanas(dias: list[DiaEvaluado]) -> list[Ventana]:
    """Agrupa dias buenos consecutivos del mismo spot en ventanas."""
    ventanas: list[Ventana] = []
    ordenados = sorted(dias, key=lambda d: (d.spot_id, d.fecha))

    for spot_id, grupo in groupby(ordenados, key=lambda d: d.spot_id):
        racha: list[DiaEvaluado] = []
        for d in grupo:
            if not d.es_bueno:
                if len(racha) >= DIAS_MINIMOS_VENTANA:
                    ventanas.append(_armar(spot_id, racha))
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


def decidir_alertas(ventanas: list[Ventana], estado: dict, hoy: date,
                    clave_observadas: str = CLAVE_OBSERVADAS,
                    clave_enviadas: str = CLAVE_ALERTADAS,
                    reenviar_si_crece: bool = True) -> list[Ventana]:
    """Aplica persistencia y anti-repeticion. Funcion de decision pura.

    Devuelve las ventanas que corresponde avisar hoy. No toca el estado:
    quien llama todavia no sabe si el envio de cada una va a llegar, asi que
    no hay nada que registrar todavia. Ver `registrar_corrida`.

    Las claves permiten correr la MISMA logica sobre las dos secciones del
    estado (alertas y pre-avisos) sin duplicarla: dos copias de esta funcion
    se desincronizarian a la primera correccion.

    `reenviar_si_crece=False` hace la anti-repeticion estricta -- una sola vez
    y nunca mas. Es la regla del pre-aviso: en el borde del horizonte la
    ventana gana un dia por corrida a medida que el pronostico rueda hacia
    adelante, asi que la regla de re-aviso por extension mandaria un mensaje
    por dia sobre el mismo swell.
    """
    ultima = estado.get("ultima_corrida")
    ultima_fecha = date.fromisoformat(ultima) if ultima else None
    # La confirmacion solo vale si la corrida anterior fue realmente ayer.
    hay_corrida_previa = ultima_fecha == hoy - timedelta(days=1)

    observadas = estado.get(clave_observadas, [])
    enviadas = estado.get(clave_enviadas, [])
    a_alertar: list[Ventana] = []

    for v in ventanas:
        confirmada = hay_corrida_previa and any(_solapa(v, r) for r in observadas)
        if not confirmada:
            continue

        previas = [r for r in enviadas if _solapa(v, r)]
        if not previas:
            a_alertar.append(v)
            continue
        if not reenviar_si_crece:
            continue

        mejor_previa = max(previas, key=lambda r: r["score"])
        # "Se extiende" cubre crecer en cualquier direccion: el swell puede
        # adelantarse (desde mas temprano) o durar mas (hasta mas tarde). En
        # los dos casos cambia cuando hay que viajar, y amerita el aviso.
        se_extendio = any(v.hasta > date.fromisoformat(r["hasta"])
                          or v.desde < date.fromisoformat(r["desde"])
                          for r in previas)
        mejoro = v.score - mejor_previa["score"] >= SALTO_SCORE_REALERTA
        if se_extendio or mejoro:
            a_alertar.append(v)

    return a_alertar


def registrar_corrida(ventanas: list[Ventana], entregadas: list[Ventana],
                      estado: dict, hoy: date,
                      clave_observadas: str = CLAVE_OBSERVADAS,
                      clave_enviadas: str = CLAVE_ALERTADAS) -> dict:
    """Construye el estado nuevo a partir de lo que se detecto y lo que
    efectivamente se logro entregar.

    Actualiza SOLO las dos claves indicadas y conserva el resto del estado tal
    cual. Es lo que permite llamarla dos veces en la misma corrida --una por
    regimen-- encadenando el resultado, sin que la segunda pasada borre lo que
    escribio la primera.

    Separado de `decidir_alertas` a proposito: `decidir_alertas` dice que
    ventanas corresponde alertar, pero el envio puede fallar (Telegram
    caido, token invalido, rate limit). Si una ventana decidida no esta en
    `entregadas`, no se marca como alertada aca -- queda pendiente, y como
    `decidir_alertas` la va a volver a proponer al no encontrarla en
    "alertadas", se reintenta sola en la proxima corrida. Marcarla como
    alertada sin haberse entregado la perderia para siempre (solo
    re-alertaria si el score sube mucho o la ventana se extiende).
    """
    enviadas = estado.get(clave_enviadas, [])

    def _reemplazada(r: dict) -> bool:
        """r queda obsoleto solo si TODAS las ventanas de hoy que lo tocan
        se entregaron. Si una ventana ancha ya alertada se parte en dos
        por un dia malo intermedio y solo una mitad re-alerta, la otra mitad
        sigue necesitando su historial: no alcanza con que r solape a
        alguna ventana entregada, tiene que quedar cubierto por completo.
        """
        solapantes = [v for v in ventanas if _solapa(v, r)]
        return bool(solapantes) and all(v in entregadas for v in solapantes)

    corte = hoy - timedelta(days=DIAS_RETENCION_ESTADO)
    conservadas = [r for r in enviadas
                  if date.fromisoformat(r["hasta"]) >= corte and not _reemplazada(r)]
    nuevas = [{**_a_registro(v), "fecha_alerta": hoy.isoformat()} for v in entregadas]

    return {
        **estado,
        "ultima_corrida": hoy.isoformat(),
        clave_observadas: [_a_registro(v) for v in ventanas],
        clave_enviadas: conservadas + nuevas,
    }
