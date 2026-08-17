"""Consenso entre modelos meteorologicos.

Reemplaza la funcion que cumple Windguru --comparar GFS, ICON y ECMWF lado a
lado-- calculandola en vez de mostrarla. Windguru no se puede usar como fuente:
sus terminos prohiben el uso de sus datos en software propio. Los modelos que
muestra son publicos y Open-Meteo los sirve directamente.

REGLA (rediseñada en la Tarea 16): primero se calcula el valor de consenso de
cada variable --la mediana entre los modelos que respondieron-- y despues se
evalua ESA mediana contra el gate, una sola vez.

Antes se hacia al reves: se evaluaba el gate modelo por modelo y se pedian
MINIMO_MODELOS_DE_ACUERDO votos. Dos defectos quedaron expuestos con un caso
real (praia_do_rosa, 2026-08-23 09:00, ver docs/):

  1. Las olas venian emparejadas posicionalmente con el viento, asi que el
     modelo que acerto las olas (ncep, 1.94 m @ 11.4 s contra los 1.8 m @ 11 s
     que publicaba surf-forecast) quedaba vetado por el viento de ECMWF
     --21.6 km/h contra los ~0 reales-- que no le correspondia.
  2. El gate por modelo hace que una diferencia de 2 cm (0.98 m contra un piso
     de 1.00 m) descarte un modelo entero y con el su voto.

Con el gate sobre la mediana ese dia pasa: 1.14 m, 9.35 s y 7.2 km/h.

La mediana NO debilita la proteccion contra el swell fantasma, la mejora: si
un solo modelo ve 2 m y los otros dos 0.5 m, la mediana da 0.5 y no alerta --
igual que la regla vieja--, pero ademas el outlier tampoco decide en la
direccion contraria. Los dos casos estan fijados en tests.

Modulo puro: sin red ni reloj.
"""
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime
from statistics import median

from surf.score import (HORAS_MINIMAS_CONSECUTIVAS, DiaEvaluado, Hora,
                        HoraEvaluada, evaluar_hora, _bloques_consecutivos,
                        _resumir)
from surf.spots import Spot

# Modelos de viento. Desde la Tarea 16 el ORDEN ya no decide nada: el consenso
# de viento es la mediana ENTRE ESTOS TRES, sin emparejar con los modelos de
# olas. Sigue existiendo un emparejamiento en `_combinar_multimodelo` --cada
# Hora lleva un viento adentro-- pero solo como respaldo para el camino que no
# recibe las series separadas; el consenso no lo mira.
#
# Que el emparejamiento decidiera era el defecto que motivo el rediseno: los
# tres discrepan de verdad en el mismo punto y hora (medido en asia,
# 2026-08-15 09:00: GFS 8.8 km/h del 261, ICON 4.5 del 209, ECMWF 5.4 del 250),
# asi que QUE modelo de viento le tocaba a cada modelo de olas decidia si el
# dia pasaba el gate. Se habia probado reordenar la lista y movia 5 de 91 dias
# del rango 0-6 sin que ninguno de los dos ordenes fuera mejor que el otro:
# la señal de que el problema no era el orden sino el emparejamiento.
MODELOS_VIENTO = ["gfs_seamless", "icon_seamless", "ecmwf_ifs025"]

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
# lo dice: nunca reporta concordancia alta. Para eso existe RESPALDO_OLAS.
MODELOS_OLAS = ["gwam", "meteofrance_wave", "ncep_gfswave025"]

# Que fuente OCUPA EL LUGAR de un titular cuando el titular no tiene dato en el
# punto que se esta consultando. No es un modelo mas: es el mismo puesto
# ocupado por otro.
#
# `ncep_gfswave016` es el mismo GFS-Wave de NOAA que `ncep_gfswave025` pero en
# grilla de 0.16 grados. Donde la celda gruesa cae en tierra, la fina puede caer
# en agua: en `huanchaco` la de 0.25 devuelve 0.0 el 100% de las horas y la de
# 0.16 devuelve dato en 8757 de 8760 horas del archivo 2025. Su cobertura NO es
# global -- de los 13 spots solo responde en huanchaco, santa_teresa, chicama y
# lobitos --, asi que no sirve como reemplazo global de la de 0.25.
#
# LA REGLA QUE NO SE PUEDE ROMPER: los dos son WW3 de NOAA. Contarlos como dos
# fuentes seria un solo modelo votando dos veces, que es exactamente el bug que
# se arreglo sacando best_match de MODELOS_OLAS. Por eso el respaldo entra solo
# cuando el titular NO tiene dato, y entra en su misma posicion (asi conserva el
# modelo de viento que le tocaba y ninguna otra fuente se corre).
RESPALDO_OLAS = {"ncep_gfswave025": "ncep_gfswave016"}

# Lo que se le pide a la API: los titulares mas los respaldos. Que un respaldo
# venga en la respuesta no lo hace votar; quien decide es `surf.fetch`.
MODELOS_OLAS_PEDIDOS = MODELOS_OLAS + [m for m in RESPALDO_OLAS.values()
                                       if m not in MODELOS_OLAS]

# Cortes de la medida de confianza, en unidades de `dispersion_relativa`.
#
# NO son numeros redondos: son los cuartiles de la distribucion real. Se midio
# max(dispersion de altura, dispersion de periodo) sobre las 5.079 horas de luz
# que pasan el gate con las TRES fuentes vivas, entre 2025-12-09 --el primer
# dia que el archivo sirve los tres modelos-- y 2026-08-15:
#
#     p10 0.112   p25 0.137   p50 0.190   p75 0.287   p90 0.385
#
# `alta` es el cuarto de horas donde los modelos mas coinciden y `baja` el
# cuarto donde mas discrepan; la mitad central queda en `media`. Leido como el
# "±" del mensaje: alta es "todos dentro de ±14%", baja es "±29% o peor", que
# sobre 1.5 m son 43 cm de indefinicion.
#
# LA POBLACION IMPORTA, y es el error que se cometio primero. Los cuartiles
# sobre las 23.347 horas de 2023-2025 dan 0.094 y 0.192, bastante mas
# estrechos, porque el 96% de esas horas tiene solo DOS fuentes y el maximo de
# dos numeros es sistematicamente menor que el de tres. Calibrar ahi y emitir
# en produccion --donde hay tres-- hacia que casi todo saliera "baja" y la
# etiqueta no distinguiera nada. Los cortes tienen que salir de la misma
# poblacion sobre la que se van a aplicar.
#
# La eleccion de los cuartiles y no de los tercios es por la asimetria de la
# consecuencia: `alta` es una promesa (el usuario maneja cuatro horas sin
# chequear nada mas) y `baja` es una advertencia. Las dos tienen que ser la
# excepcion, y la etiqueta corriente tiene que ser `media`.
CORTE_DISPERSION_ALTA = 0.137
CORTE_DISPERSION_MEDIA = 0.287

# Desacuerdo a partir del cual la mediana deja de significar algo y el sistema
# NO opina. No es una etiqueta de confianza: es un rechazo.
#
# Existe por el caso de las DOS fuentes, donde la mediana es el promedio y por
# lo tanto no protege de un outlier: un modelo que ve 2.0 m @ 14 s con offshore
# y otro que ve 0.4 m @ 5 s con onshore de 30 km/h promedian 1.2 m @ 9.5 s con
# viento moderado, o sea un dia bueno que ninguno de los dos pronostico. Los
# dos no estan describiendo el mismo mar, y promediarlos inventa un tercer mar.
#
# El valor tiene una lectura exacta: con dos fuentes, dispersion = (a-b)/(a+b),
# asi que 0.5 es "un modelo ve el TRIPLE que el otro". Es un filtro de casos
# irreconciliables, no un dial de volumen, y esta medido en las dos
# poblaciones: rechaza el 0.4% de las horas que pasarian el gate en 2023-2025
# (117 de 30.578, mayormente dos fuentes) y el 1.6% con las tres fuentes vivas
# (82 de 5.079). Bajarlo a 0.30 se llevaria el 10.6% y ahi si estaria
# calibrando el volumen por la puerta de atras.
DISPERSION_INCONCILIABLE = 0.5

# Fuentes de olas que tienen que estar DISPONIBLES para emitir un pre-aviso.
# No es lo mismo que la medida de dispersion: aquella describe cuanto difieren
# las fuentes que hubo, esta exige que haya con quien contrastar en primer
# lugar. Con la mediana la diferencia es critica: la mediana de UNA fuente es
# esa fuente, asi que sin este piso un modelo solo se auto-confirmaria.
#
# Existe porque un modelo solo puede inventar un swell que no existe, y a 8
# dias no hay con que contrastarlo -- no queda ninguna otra fuente viva que
# lo desmienta. El pre-aviso es ademas donde el falso positivo cuesta mas
# caro: es el mensaje que hace que el usuario empiece a mover fechas.
#
# El precio, aceptado a proposito: los spots donde ncep_gfswave025 esta
# enmascarado por tierra y no hay respaldo con cobertura (buchupureo, asia,
# punta_de_lobos, joaquina) se quedan con una sola fuente a partir del dia 8 y
# no van a generar pre-avisos. Mejor ninguno que uno que no se puede
# contrastar. huanchaco salio de esa lista en la Tarea 15: ncep_gfswave016 le
# da la segunda fuente hasta el dia 9 (medido: 12 de 12 horas de luz de los
# dias 8 y 9, contra 0 antes).
#
# El regimen de alerta confirmada (dias 0-6) NO usa esta regla: ahi hay
# cobertura de sobra y la mediana se calcula sobre dos o tres fuentes.
MINIMO_FUENTES_OLAS_PREAVISO = 2
# "Alta" es la etiqueta que le dice al usuario que puede manejar cuatro horas
# sin chequear nada mas. No se puede afirmar con menos de tres fuentes: si un
# modelo no respondio, no hay tres opiniones, hay dos.
MINIMO_MODELOS_PARA_ALTA = 3

_ORDEN_CONCORDANCIA = {"alta": 2, "media": 1, "baja": 0}


@dataclass(frozen=True)
class HoraMultiModelo:
    t: datetime
    es_de_dia: bool
    # Modelos de OLAS. Cada Hora trae ademas un viento adentro por herencia del
    # emparejamiento historico; el consenso ya no lo usa salvo como respaldo.
    por_modelo: dict[str, Hora]
    # Modelos de VIENTO, servidos aparte: {modelo: (km/h, direccion)}. Es lo
    # que permite calcular el consenso de viento entre los modelos de viento
    # en vez de heredarlo del emparejamiento. Vacio significa "esta hora vino
    # por un camino que no separa las fuentes" y entonces se cae al viento que
    # traen las Horas de `por_modelo`.
    viento_por_modelo: dict[str, tuple[float, float]] = field(default_factory=dict)


@dataclass(frozen=True)
class Consenso:
    """Lo que opinan los modelos, junto."""
    hora: Hora
    nivel: str
    dispersion: float
    fuentes_olas: int
    fuentes_viento: int
    # Cuantas fuentes de olas pasarian el gate por si solas. Ya no decide la
    # etiqueta (ver DiaEvaluado.modelos_de_acuerdo): es diagnostico.
    pasan_solas: int


def _mediana_angular(angulos: list[float]) -> float:
    """Mediana de direcciones. Toma el valor central del conjunto ordenado
    por cercania al primero, para no promediar angulos que cruzan el 0."""
    if len(angulos) == 1:
        return angulos[0]
    ref = angulos[0]
    ordenados = sorted(angulos, key=lambda a: ((a - ref + 180) % 360) - 180)
    return ordenados[len(ordenados) // 2]


def _modelo_de_olas(nombre: str) -> str:
    """Nombre del modelo de OLAS dentro de la clave del par.

    `_combinar_multimodelo` nombra cada fuente `"<olas>+<viento>"` para que la
    linea de concordancia diga con que viento se evaluo. La exclusion es del
    modelo de olas, asi que se compara contra la parte de la izquierda: un
    match por substring sacaria de la votacion a cualquier par cuyo modelo de
    viento se llamara parecido.
    """
    return nombre.split("+")[0]


def sin_modelos_excluidos(hmm: HoraMultiModelo, spot: Spot) -> HoraMultiModelo:
    """La misma hora sin las fuentes de olas que el spot excluye.

    Se filtra ACA y no en `surf.fetch`: lo que se excluye son fuentes de OLAS,
    y sacarlas de la lista que se le pide a la API tocaria tambien la deteccion
    de series duplicadas y la cadena de respaldo. El consenso de viento no se
    toca --se calcula entre los modelos de viento y ninguno de ellos se excluye
    nunca-- asi que `viento_por_modelo` viaja intacto.
    """
    if not spot.modelos_excluidos:
        return hmm
    # Excluir un titular excluye tambien a su respaldo: el respaldo es el mismo
    # puesto ocupado por otra grilla del mismo modelo, no una fuente distinta.
    # Si sobreviviera, la exclusion no sacaria la fuente que se quiso sacar --
    # la renombraria.
    excluidos = set(spot.modelos_excluidos)
    excluidos |= {RESPALDO_OLAS[m] for m in excluidos if m in RESPALDO_OLAS}
    quedan = {n: h for n, h in hmm.por_modelo.items()
              if _modelo_de_olas(n) not in excluidos}
    if len(quedan) == len(hmm.por_modelo):
        return hmm
    return HoraMultiModelo(t=hmm.t, es_de_dia=hmm.es_de_dia, por_modelo=quedan,
                           viento_por_modelo=hmm.viento_por_modelo)


def dispersion_relativa(valores: list[float]) -> float:
    """Semirango relativo sobre la mediana: cuanto difieren entre si.

    Se eligio esta forma y no el desvio estandar ni el rango intercuartil
    porque con 2 o 3 fuentes --que es lo que hay siempre-- el IQR es
    degenerado y el desvio de una muestra de 3 no significa gran cosa. El
    semirango, en cambio, se lee directo como el "±" que sale impreso en el
    mensaje: `dispersion_relativa([0.8, 1.0, 1.2]) == 0.2` es exactamente
    "1.0 ± 20%".

    Con una sola fuente devuelve 0.0, que NO quiere decir acuerdo: quiere
    decir que no hay desacuerdo medible. Quien clasifica se ocupa de eso.
    """
    if len(valores) < 2:
        return 0.0
    centro = median(valores)
    if centro == 0:
        return 0.0
    return (max(valores) - min(valores)) / (2 * centro)


def _viento_de_consenso(hmm: HoraMultiModelo,
                        horas: list[Hora]) -> tuple[float, float, int]:
    """Mediana del viento ENTRE LOS MODELOS DE VIENTO. Sin emparejamiento.

    Cuando la hora no trae las series de viento separadas se cae al viento que
    cada Hora de olas lleva adentro. Es solo compatibilidad: por ese camino
    vuelve a haber tantos vientos como modelos de olas, que es la situacion
    que el rediseno vino a eliminar.
    """
    if hmm.viento_por_modelo:
        vientos = list(hmm.viento_por_modelo.values())
    else:
        vientos = [(h.viento_kmh, h.viento_direccion) for h in horas]
    return (median(v[0] for v in vientos),
            _mediana_angular([v[1] for v in vientos]),
            len(vientos))


def _nivel(dispersion: float, fuentes_olas: int) -> str:
    """Etiqueta de confianza a partir de cuanto difieren los modelos."""
    if fuentes_olas < 2:
        # Que no haya desacuerdo posible no es lo mismo que haya acuerdo. Una
        # sola fuente es el escenario de falso positivo que este modulo existe
        # para evitar.
        return "baja"
    if (fuentes_olas >= MINIMO_MODELOS_PARA_ALTA
            and dispersion <= CORTE_DISPERSION_ALTA):
        return "alta"
    if dispersion <= CORTE_DISPERSION_MEDIA:
        return "media"
    return "baja"


def consensuar(hmm: HoraMultiModelo, spot: Spot) -> Consenso:
    """Calcula el valor de consenso de la hora y cuanta confianza merece.

    NO aplica el gate: quien llama evalua la hora resultante una sola vez. Es
    la inversion de orden que define la Tarea 16.
    """
    hmm = sin_modelos_excluidos(hmm, spot)
    horas = list(hmm.por_modelo.values())

    alturas = [h.swell_altura for h in horas]
    periodos = [h.swell_periodo for h in horas]
    viento_kmh, viento_dir, fuentes_viento = _viento_de_consenso(hmm, horas)

    mediana = Hora(
        t=hmm.t,
        swell_altura=median(alturas),
        swell_periodo=median(periodos),
        swell_direccion=_mediana_angular([h.swell_direccion for h in horas]),
        viento_kmh=viento_kmh,
        viento_direccion=viento_dir,
        es_de_dia=hmm.es_de_dia,
    )

    # Se toma la PEOR de las dos dispersiones del swell. La de altura y la de
    # periodo son casi independientes: la de altura es la mayor solo en el 51%
    # de las horas con dos fuentes y en el 62% con tres, asi que mirar una sola
    # etiquetaria como "alta" horas donde los modelos discrepan fuerte en la
    # otra. El viento queda afuera a proposito: el pre-aviso ni siquiera lo
    # evalua (la etiqueta tiene que significar lo mismo en los dos regimenes)
    # y ademas su dispersion relativa es el doble que la del swell (p50 0.157
    # contra 0.095) por una razon que no es desacuerdo real -- 3 km/h de
    # diferencia sobre 6 km/h ya son 25%, y las dos lecturas son glassy.
    dispersion = max(dispersion_relativa(alturas), dispersion_relativa(periodos))

    return Consenso(
        hora=mediana,
        nivel=_nivel(dispersion, len(horas)),
        dispersion=dispersion,
        fuentes_olas=len(horas),
        fuentes_viento=fuentes_viento,
        pasan_solas=sum(1 for h in horas if evaluar_hora(h, spot).pasa),
    )


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
                            exigir_viento: bool = True,
                            minimo_fuentes: int = 1) -> DiaEvaluado:
    """Igual que evaluar_dia, pero exigiendo acuerdo entre modelos.

    `exigir_viento=False` es el regimen de pre-aviso (dias 7 a 10): se pide
    acuerdo entre modelos igual que siempre, pero solo sobre el swell. En ese
    rango quedan menos fuentes de olas vivas, asi que la etiqueta de
    concordancia baja sola -- la regla de no declarar "alta" con menos de
    MINIMO_MODELOS_PARA_ALTA fuentes se sigue aplicando sin cambios.

    `minimo_fuentes` exige un piso de fuentes de olas DISPONIBLES para que la
    hora pueda pasar. El default de 1 conserva el comportamiento del regimen
    de alerta; el pre-aviso lo sube a MINIMO_FUENTES_OLAS_PREAVISO.
    """
    vacio = DiaEvaluado(fecha=fecha, spot_id=spot.id, es_bueno=False, score=0.0,
                        horas_buenas=0, bloque=None, resumen=None,
                        motivo_principal=None, concordancia="baja")
    if not hmms:
        return vacio

    evaluadas: list[HoraEvaluada] = []
    niveles: dict[datetime, str] = {}
    modelos: dict[datetime, tuple[str, ...]] = {}
    vientos: dict[datetime, tuple[str, ...]] = {}
    acuerdos: dict[datetime, int] = {}
    dispersiones: dict[datetime, float] = {}
    de_dia: dict[datetime, bool] = {}

    for hmm in sorted(hmms, key=lambda x: x.t):
        # Se filtra una sola vez por hora y despues se trabaja con el resultado:
        # el conteo de fuentes, el motivo de rechazo y los nombres que sale a
        # informar el mensaje tienen que hablar de los modelos que votaron.
        hmm = sin_modelos_excluidos(hmm, spot)
        if not hmm.por_modelo:
            # A esta hora la unica fuente presente era la excluida. No es un
            # rechazo por las condiciones: es una hora sobre la que el spot no
            # tiene dato, igual que si la API no la hubiera devuelto.
            continue
        c = consensuar(hmm, spot)
        niveles[hmm.t] = c.nivel
        modelos[hmm.t] = tuple(hmm.por_modelo)
        vientos[hmm.t] = tuple(hmm.viento_por_modelo)
        acuerdos[hmm.t] = c.pasan_solas
        dispersiones[hmm.t] = c.dispersion
        de_dia[hmm.t] = hmm.es_de_dia
        if len(hmm.por_modelo) < minimo_fuentes:
            # Sin fuentes suficientes no se rechaza por las condiciones: se
            # rechaza por no poder contrastarlas. Es una hora sobre la que el
            # sistema no tiene derecho a opinar.
            evaluadas.append(HoraEvaluada(
                hora=c.hora, pasa=False,
                motivo_rechazo=(f"fuentes de olas insuficientes "
                                f"({len(hmm.por_modelo)}, mínimo {minimo_fuentes})"),
                score=0.0, clase_viento="",
            ))
        elif (c.fuentes_olas >= 2
                and c.dispersion > DISPERSION_INCONCILIABLE):
            # Los modelos no describen el mismo mar. La mediana entre ellos
            # seria un mar que no pronostico ninguno.
            evaluadas.append(HoraEvaluada(
                hora=c.hora, pasa=False,
                motivo_rechazo=(f"los modelos no coinciden "
                                f"(±{c.dispersion:.0%} entre {c.fuentes_olas})"),
                score=0.0, clase_viento="",
            ))
        else:
            # EL gate, una sola vez, sobre el valor de consenso.
            evaluadas.append(evaluar_hora(c.hora, spot, exigir_viento))

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
    # nombres de los modelos y la dispersion salen de esa misma hora, para que
    # el mensaje describa exactamente la hora que define la etiqueta.
    t_peor = min((e.hora.t for e in mejor),
                 key=lambda t: (_ORDEN_CONCORDANCIA[niveles[t]],
                                -dispersiones[t]))

    return DiaEvaluado(
        fecha=fecha, spot_id=spot.id, es_bueno=True, score=mejor_score,
        horas_buenas=sum(1 for e in evaluadas if e.pasa),
        bloque=(mejor[0].hora.t, mejor[-1].hora.t),
        resumen=_resumir(mejor), motivo_principal=None,
        concordancia=niveles[t_peor], modelos=modelos[t_peor],
        modelos_de_acuerdo=acuerdos[t_peor],
        modelos_viento=vientos[t_peor],
        dispersion=dispersiones[t_peor],
        # Basta con que UNA hora del bloque haya raspado: el dia paso al
        # limite y el usuario tiene que enterarse.
        al_limite=any(e.al_limite for e in mejor),
    )
