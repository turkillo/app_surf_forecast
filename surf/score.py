"""Gate y scoring de condiciones de surf.

Diseno deliberado: gate duro primero, score despues. El gate son condiciones
binarias que TODAS deben cumplirse; no hay compensacion entre criterios. Un
promedio ponderado sobre el gate permitiria que 2.5m con onshore de 30 km/h
saque 70 puntos y dispare una alerta por un dia de espuma.

Este modulo es puro: no hace red, ni archivos, ni consulta la hora actual.
Es lo que permite que el backtest corra exactamente el mismo codigo que
produccion.
"""
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime

from surf.geo import angular_diff, clasificar_viento, en_ventana
from surf.spots import Spot

VIENTO_GLASSY_KMH = 6.0
OFFSHORE_IDEAL_KMH = 20.0
OFFSHORE_MAX_KMH = 35.0
CROSS_IDEAL_KMH = 12.0
CROSS_MAX_KMH = 20.0
ONSHORE_MAX_KMH = 8.0

PERIODO_TOPE_S = 16.0
PISO_FACTOR_ALTURA = 0.4
PISO_FACTOR_DIRECCION = 0.5
PISO_FACTOR_OFFSHORE = 0.4
PISO_FACTOR_CROSS = 0.3
FACTOR_CROSS_IDEAL = 0.85
FACTOR_ONSHORE = 0.5

# Pesos del score. Suman 1.0. Aca SI corresponde un promedio ponderado:
# solo se aplica sobre condiciones que ya pasaron el gate, o sea que todas
# las opciones que compara son surfeables.
PESOS = {"altura": 0.35, "periodo": 0.30, "direccion": 0.15, "viento": 0.20}

# Pesos para el regimen de pre-aviso (dias 7 a 10), donde el viento no se
# evalua porque a esa distancia no se puede pronosticar. Se renormalizan sobre
# los tres criterios de swell para que el puntaje siga siendo sobre 100 y un
# pre-aviso se pueda leer en la misma escala que una alerta. Si no se
# renormalizaran, el mejor swell posible sacaria 80 y pareceria mediocre.
_PESO_SWELL = PESOS["altura"] + PESOS["periodo"] + PESOS["direccion"]
PESOS_SOLO_SWELL = {k: PESOS[k] / _PESO_SWELL
                    for k in ("altura", "periodo", "direccion")}

HORAS_MINIMAS_CONSECUTIVAS = 3

# Energia por ola y por metro de cresta, en kJ. Es la magnitud que surf-forecast
# publica en su columna de energia, y se incluye en el mensaje para poder
# contrastar contra esa fuente. NO participa del gate ni del score: es un dato
# informativo.
#
# La constante se ajusto empiricamente contra 24 lecturas de surf-forecast en
# tres spots (chapadmalal, la_barra, praia_do_rosa) el 2026-08-14: k = 1.95 con
# 7% de dispersion, explicada por el redondeo con que surf-forecast publica
# altura y periodo. Ajusta a H^2*T^2 y no a H^2*T (13% de dispersion).
#
# Coincide con la fisica: la energia por ola por metro de cresta es
# (rho*g^2/64pi) * H^2 * T^2 = 0.49 * H^2 * T^2, y 1.95 es casi exactamente
# cuatro veces eso, consistente con que surf-forecast use la altura maxima
# (~2*Hs) en vez de la significativa, ya que la energia va con el cuadrado.
CONSTANTE_ENERGIA_KJ = 1.95


def energia_kj(altura: float, periodo: float) -> float:
    """Energia por ola y por metro de cresta, en kJ.

    Funcion pura: solo depende de altura y periodo del swell.
    """
    return CONSTANTE_ENERGIA_KJ * altura * altura * periodo * periodo


@dataclass(frozen=True)
class Hora:
    t: datetime
    swell_altura: float
    swell_periodo: float
    swell_direccion: float
    viento_kmh: float
    viento_direccion: float
    es_de_dia: bool


@dataclass(frozen=True)
class HoraEvaluada:
    hora: Hora
    pasa: bool
    motivo_rechazo: str | None
    score: float
    clase_viento: str


@dataclass(frozen=True)
class DiaEvaluado:
    fecha: date
    spot_id: str
    es_bueno: bool
    score: float
    horas_buenas: int
    bloque: tuple[datetime, datetime] | None
    resumen: dict[str, float] | None
    motivo_principal: str | None
    concordancia: str = "alta"
    # Modelos que efectivamente respondieron en la hora que define la
    # concordancia del dia, y cuantos de ellos pasaron el gate. Se guardan
    # para que el mensaje pueda nombrar las fuentes reales en vez de un
    # trio hardcodeado (Tarea 11: el texto decia "GFS, ICON y ECMWF
    # coinciden" aun cuando a uno nunca se lo habia consultado).
    modelos: tuple[str, ...] = ()
    modelos_de_acuerdo: int = 0


def _interpolar(x: float, x0: float, x1: float, y0: float, y1: float) -> float:
    """Interpolacion lineal de x en [x0,x1] hacia [y0,y1]."""
    if x1 == x0:
        return y1
    t = (x - x0) / (x1 - x0)
    return y0 + t * (y1 - y0)


def factor_altura(altura: float, spot: Spot) -> float:
    """1.0 dentro del rango ideal, cae linealmente hacia los extremos."""
    sw = spot.swell
    ideal_min, ideal_max = sw.rango_ideal
    if ideal_min <= altura <= ideal_max:
        return 1.0
    if altura < ideal_min:
        f = _interpolar(altura, sw.min_altura, ideal_min, PISO_FACTOR_ALTURA, 1.0)
    else:
        f = _interpolar(altura, ideal_max, sw.max_altura, 1.0, PISO_FACTOR_ALTURA)
    return min(1.0, max(PISO_FACTOR_ALTURA, f))


def factor_periodo(periodo: float, spot: Spot) -> float:
    """0.0 en el minimo del spot, 1.0 a los 16 segundos, con tope."""
    f = _interpolar(periodo, spot.swell.min_periodo, PERIODO_TOPE_S, 0.0, 1.0)
    return min(1.0, max(0.0, f))


def factor_direccion(direccion: float, spot: Spot) -> float:
    """1.0 en la direccion ideal, 0.5 en los bordes de la ventana."""
    sw = spot.swell
    desvio = angular_diff(direccion, sw.ideal)
    # Determinar qué borde usar: izquierdo si direccion <= ideal, derecho si no
    delta = ((direccion - sw.ideal + 180) % 360) - 180
    borde = angular_diff(sw.ventana[0], sw.ideal) if delta <= 0 else angular_diff(sw.ventana[1], sw.ideal)
    if borde == 0:
        return 1.0
    f = _interpolar(desvio, 0.0, borde, 1.0, PISO_FACTOR_DIRECCION)
    return min(1.0, max(PISO_FACTOR_DIRECCION, f))


def factor_viento(viento_kmh: float, clase: str) -> float:
    """Factor de viento segun la tabla del diseno."""
    if viento_kmh <= VIENTO_GLASSY_KMH:
        return 1.0
    if clase == "offshore":
        if viento_kmh <= OFFSHORE_IDEAL_KMH:
            return 1.0
        f = _interpolar(viento_kmh, OFFSHORE_IDEAL_KMH, OFFSHORE_MAX_KMH,
                        1.0, PISO_FACTOR_OFFSHORE)
        return min(1.0, max(PISO_FACTOR_OFFSHORE, f))
    if clase == "cross":
        if viento_kmh <= CROSS_IDEAL_KMH:
            return FACTOR_CROSS_IDEAL
        f = _interpolar(viento_kmh, CROSS_IDEAL_KMH, CROSS_MAX_KMH,
                        FACTOR_CROSS_IDEAL, PISO_FACTOR_CROSS)
        return min(1.0, max(PISO_FACTOR_CROSS, f))
    return FACTOR_ONSHORE


def _gate_viento(hora: Hora, clase: str) -> str | None:
    """Devuelve el motivo de rechazo, o None si el viento pasa."""
    if hora.viento_kmh <= VIENTO_GLASSY_KMH:
        return None
    if clase == "offshore":
        if hora.viento_kmh > OFFSHORE_MAX_KMH:
            return f"offshore muy fuerte ({hora.viento_kmh:.0f} km/h, máximo {OFFSHORE_MAX_KMH:.0f})"
        return None
    if clase == "cross":
        if hora.viento_kmh > CROSS_MAX_KMH:
            return f"cross muy fuerte ({hora.viento_kmh:.0f} km/h, máximo {CROSS_MAX_KMH:.0f})"
        return None
    if hora.viento_kmh > ONSHORE_MAX_KMH:
        return f"viento onshore ({hora.viento_kmh:.0f} km/h, máximo {ONSHORE_MAX_KMH:.0f})"
    return None


def _gate(hora: Hora, spot: Spot, clase: str,
          exigir_viento: bool = True) -> str | None:
    """Aplica las condiciones del gate. Devuelve el primer motivo de rechazo.

    Con `exigir_viento=False` se saltea SOLO el criterio de viento. Es el
    regimen de pre-aviso: a mas de una semana el viento local no se puede
    pronosticar, asi que exigirlo no filtra nada, solo agrega ruido. La
    altura, el periodo, la direccion y la luz son fisica del swell en curso
    (o astronomia) y siguen aplicando igual.
    """
    sw = spot.swell

    if not hora.es_de_dia:
        return "fuera de horas de luz"
    if hora.swell_altura < sw.min_altura:
        return f"altura insuficiente ({hora.swell_altura:.1f}m, mínimo {sw.min_altura:.1f}m)"
    if hora.swell_altura > sw.max_altura:
        return f"el spot cierra con este tamaño ({hora.swell_altura:.1f}m, máximo {sw.max_altura:.1f}m)"
    if hora.swell_periodo < sw.min_periodo:
        return f"período corto ({hora.swell_periodo:.1f}s, mínimo {sw.min_periodo:.1f}s)"
    if not en_ventana(hora.swell_direccion, sw.ventana):
        return (
            f"dirección fuera de la ventana del spot "
            f"({hora.swell_direccion:.0f}, ventana {sw.ventana[0]:.0f}-{sw.ventana[1]:.0f})"
        )
    if not exigir_viento:
        return None
    return _gate_viento(hora, clase)


def evaluar_hora(hora: Hora, spot: Spot,
                 exigir_viento: bool = True) -> HoraEvaluada:
    """Evalua una hora contra el perfil del spot.

    `exigir_viento=False` es el regimen de pre-aviso: el viento no entra ni
    en el gate ni en el puntaje. Que no se pueda evaluar y que igual puntee
    seria lo peor de los dos mundos -- un swell identico sacaria puntajes
    distintos segun un dato que el propio sistema declaro impronosticable.
    """
    clase = clasificar_viento(hora.viento_direccion, spot.costa_mira)
    motivo = _gate(hora, spot, clase, exigir_viento)
    if motivo is not None:
        return HoraEvaluada(hora=hora, pasa=False, motivo_rechazo=motivo,
                            score=0.0, clase_viento=clase)
    if exigir_viento:
        score = 100.0 * (
            PESOS["altura"] * factor_altura(hora.swell_altura, spot)
            + PESOS["periodo"] * factor_periodo(hora.swell_periodo, spot)
            + PESOS["direccion"] * factor_direccion(hora.swell_direccion, spot)
            + PESOS["viento"] * factor_viento(hora.viento_kmh, clase)
        )
    else:
        score = 100.0 * (
            PESOS_SOLO_SWELL["altura"] * factor_altura(hora.swell_altura, spot)
            + PESOS_SOLO_SWELL["periodo"] * factor_periodo(hora.swell_periodo, spot)
            + PESOS_SOLO_SWELL["direccion"] * factor_direccion(hora.swell_direccion, spot)
        )
    return HoraEvaluada(hora=hora, pasa=True, motivo_rechazo=None,
                        score=score, clase_viento=clase)


def _bloques_consecutivos(evaluadas: list[HoraEvaluada]) -> list[list[HoraEvaluada]]:
    """Agrupa las horas que pasaron en rachas consecutivas."""
    bloques: list[list[HoraEvaluada]] = []
    actual: list[HoraEvaluada] = []
    for ev in evaluadas:
        if ev.pasa:
            actual.append(ev)
        else:
            if actual:
                bloques.append(actual)
            actual = []
    if actual:
        bloques.append(actual)
    return bloques


def _resumir(bloque: list[HoraEvaluada]) -> dict[str, float]:
    """Condiciones representativas del bloque.

    Las direcciones se toman del punto medio en vez de promediarse: promediar
    angulos da resultados sin sentido cuando cruzan el 0 (350 y 10 promedian 180).
    """
    n = len(bloque)
    medio = bloque[n // 2].hora
    return {
        "altura": sum(e.hora.swell_altura for e in bloque) / n,
        "periodo": sum(e.hora.swell_periodo for e in bloque) / n,
        "viento_kmh": sum(e.hora.viento_kmh for e in bloque) / n,
        "direccion": medio.swell_direccion,
        "viento_direccion": medio.viento_direccion,
    }


def evaluar_dia(horas: list[Hora], spot: Spot, fecha: date) -> DiaEvaluado:
    """Agrega horas en un veredicto diario.

    Un dia es bueno si tiene al menos HORAS_MINIMAS_CONSECUTIVAS horas de luz
    seguidas que pasan el gate. Una hora aislada es una casualidad del modelo,
    no una sesion.
    """
    vacio = DiaEvaluado(fecha=fecha, spot_id=spot.id, es_bueno=False, score=0.0,
                        horas_buenas=0, bloque=None, resumen=None,
                        motivo_principal=None)
    if not horas:
        return vacio

    evaluadas = [evaluar_hora(h, spot) for h in sorted(horas, key=lambda x: x.t)]
    bloques = [b for b in _bloques_consecutivos(evaluadas)
               if len(b) >= HORAS_MINIMAS_CONSECUTIVAS]

    if not bloques:
        motivos = Counter(e.motivo_rechazo for e in evaluadas if e.motivo_rechazo)
        return DiaEvaluado(
            fecha=fecha, spot_id=spot.id, es_bueno=False, score=0.0,
            horas_buenas=sum(1 for e in evaluadas if e.pasa), bloque=None,
            resumen=None,
            motivo_principal=motivos.most_common(1)[0][0] if motivos else None,
        )

    # De cada bloque, la mejor ventana de HORAS_MINIMAS_CONSECUTIVAS seguidas.
    mejor: list[HoraEvaluada] | None = None
    mejor_score = -1.0
    for bloque in bloques:
        for i in range(len(bloque) - HORAS_MINIMAS_CONSECUTIVAS + 1):
            ventana = bloque[i:i + HORAS_MINIMAS_CONSECUTIVAS]
            s = sum(e.score for e in ventana) / len(ventana)
            if s > mejor_score:
                mejor_score, mejor = s, ventana

    assert mejor is not None
    return DiaEvaluado(
        fecha=fecha, spot_id=spot.id, es_bueno=True, score=mejor_score,
        horas_buenas=sum(1 for e in evaluadas if e.pasa),
        bloque=(mejor[0].hora.t, mejor[-1].hora.t),
        resumen=_resumir(mejor), motivo_principal=None,
    )
