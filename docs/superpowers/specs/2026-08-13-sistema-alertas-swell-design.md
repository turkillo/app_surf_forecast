# Sistema de alertas de swell — Sudamérica

**Fecha:** 2026-08-13
**Estado:** Diseño aprobado, pendiente de plan de implementación

## Problema

Chequear manualmente 7 páginas de surf-forecast todos los días para detectar ventanas
de buen swell es tedioso y poco confiable: se olvida, se lee apurado, y las ventanas
buenas aparecen y desaparecen del pronóstico sin que nadie las note.

Los destinos son todos **de viaje** — ninguno está a mano. Eso define dos requisitos
duros: la alerta necesita **3 a 6 días de anticipación** para poder organizarse, y el
filtro tiene que ser **exigente**, porque solo vale la pena viajar por algo realmente
bueno.

## Objetivo

Un sistema que corre solo todos los días, evalúa 13 spots de Sudamérica y Costa Rica,
y manda un push a Telegram únicamente cuando hay una ventana de swell que justifica
un viaje.

**El requisito dominante es la calidad del detector.** El sistema vale por su precisión,
no por sus features. Un detector que alerta de más se vuelve ruido y se ignora; uno que
alerta de menos hace perder swells. Todo lo demás en este diseño está subordinado a eso.

## Fuente de datos

### Decisión: Open-Meteo, no scraping

surf-forecast.com no tiene API pública. Scrapear su HTML es frágil (se rompe con cada
cambio de diseño) y va contra sus términos de uso.

**Open-Meteo** se usa como motor de datos:

| API | Datos | Notas |
|---|---|---|
| Marine API | `swell_wave_height`, `swell_wave_period`, `swell_wave_direction`, `wave_height` | Horario, 7 días |
| Forecast API | `wind_speed_10m`, `wind_direction_10m` | Horario, 7 días |
| Forecast API (daily) | `sunrise`, `sunset` | Para filtrar horas de luz |
| Archive API | Histórico marino y de viento | Para el backtest |

Gratis, sin API key, sin límite práctico de uso. **Cobertura verificada en los 7 spots
originales el 2026-08-13** — los 7 devolvieron datos válidos de altura, período y
dirección de swell.

El link de surf-forecast de cada spot se incluye en la alerta, para consultar el
detalle específico del pico (incluida la marea).

### Limitación conocida

Open-Meteo entrega salida de modelo global en un punto de mar abierto, no un pronóstico
ajustado a la batimetría del pico. La calibración por spot (ver *Validación*) existe
justamente para corregir esto.

### Windguru: por qué no, y qué se hace en su lugar

**Windguru queda descartado como fuente.** Sus términos prohíben expresamente usar sus
datos para software propio, apps o páginas web sin acuerdo expreso, y tipifican el
crawling automatizado como incumplimiento material.

El valor de Windguru, sin embargo, no es su dato propio: es que muestra **varios modelos
meteorológicos lado a lado** (GFS, ICON, ECMWF, WRF) para que el usuario juzgue si
concuerdan. Esos modelos son públicos y Open-Meteo los sirve directamente.

**Se replica la función, no la fuente** — y mejor, porque en vez de comparar columnas a
ojo el sistema calcula la concordancia. Modelos verificados disponibles el 2026-08-13:

| Variable | Modelos |
|---|---|
| Viento | `gfs_seamless`, `icon_seamless`, `ecmwf_ifs025` |
| Olas | `best_match`, `gwam`, `meteofrance_wave` |

La discrepancia entre modelos es real y significativa. Medición en Chapadmalal, misma
hora: GFS 14.9 km/h, ICON 7.0 km/h, ECMWF 12.0 km/h. Un modelo indicaba condiciones casi
glassy y otro el doble de viento.

### Consenso multi-modelo

**El gate debe pasar en al menos 2 de los 3 modelos** para que la hora cuente. Si GFS ve
una ventana pero ICON y ECMWF no, no hay alerta.

Los valores que se muestran y puntúan son la **mediana** de los modelos, no la de uno
elegido arbitrariamente: es más robusta ante un modelo que se va de rango.

Cada hora y cada día llevan un nivel de **concordancia**:

| Nivel | Condición |
|---|---|
| `alta` | los 3 modelos pasan el gate |
| `media` | pasan 2 de 3 |
| `baja` | pasa 1 o ninguno → la hora no cuenta |

La concordancia se incluye en el mensaje de alerta. Es información que el usuario usa
para decidir cuánta plata pone en un pasaje.

Esto ataca directamente el requisito dominante del proyecto: es el mecanismo más
efectivo contra el falso positivo, porque un swell fantasma rara vez aparece en tres
modelos independientes a la vez.

---

## El detector

### Principio de diseño: gate duro + score, nunca promedio ponderado

Un score ponderado del tipo `0.4×altura + 0.3×período + 0.3×viento` **está
explícitamente rechazado**. Permite que un componente excelente compense uno
inaceptable: 2.5 m con onshore de 30 km/h saca ~70 puntos y dispara una alerta por un
día de pura espuma.

En su lugar, dos etapas independientes:

1. **Gate** — condiciones binarias que *todas* deben cumplirse. Si falla una, la hora
   no cuenta. Sin compensación entre criterios.
2. **Score 0-100** — se calcula solo sobre lo que pasó el gate. Sirve para rankear y
   priorizar. **Nunca decide si se alerta o no.**

Consecuencia deseada: el sistema es auditable. Ante cualquier "¿por qué no me avisó?"
hay siempre una condición concreta que falló.

### Gate (evaluado por hora)

| # | Condición | Umbral |
|---|---|---|
| 1 | Altura de swell | ≥ `spot.swell.min_altura` |
| 2 | Altura de swell | ≤ `spot.swell.max_altura` |
| 3 | Período de swell | ≥ `spot.swell.min_periodo` |
| 4 | Dirección de swell | dentro de `spot.swell.ventana` |
| 5 | Viento | pasa la tabla de viento (abajo) |
| 6 | Hora | entre `sunrise` y `sunset` |

Los umbrales son **por spot**, no globales. 1 m @ 9 s en Santa Teresa es un día
divertido; en Punta de Lobos no es nada. Un gate único trata ambos casos igual y ahí
es donde el detector falla.

**Valores de referencia** (piso global del usuario, punto de partida para los perfiles):
altura ≥ 1.0 m, período ≥ 9 s. Se toma 9 s y no 8 s porque a 8 s todavía domina el
windswell local; a 9 s ya hay groundswell con energía. Cada spot ajusta desde ahí según
su investigación.

**Por qué el período pesa tanto:** la energía de una ola escala con `H² × T`. 1 m @ 14 s
carga casi el doble de energía que 1 m @ 8 s y rompe con una cara notablemente más
grande. Por eso el período es gate *y* componente fuerte del score.

**Por qué `max_altura`:** un spot que cierra arriba de cierto tamaño no debe alertar
cuando lo supera. Wannasurf documenta este techo (`holds up to`) para la mayoría de los
spots.

### Viento, relativo a la orientación de cada playa

Cada spot lleva configurada `costa_mira` (rumbo hacia donde mira la playa, en grados).
El viento offshore sopla *desde* `costa_mira + 180°`.

```
rel = diferencia_angular(viento_desde, (costa_mira + 180) mod 360)

rel <  45°  → OFFSHORE
45° a 135°  → CROSS
rel > 135°  → ONSHORE
```

| Condición | Pasa gate | Factor de score |
|---|---|---|
| Cualquier dirección ≤ 6 km/h (glassy) | Sí | 1.00 |
| Offshore ≤ 20 km/h | Sí | 1.00 |
| Offshore 20-35 km/h | Sí | 1.00 → 0.40 (lineal) |
| Offshore > 35 km/h | **No** | — |
| Cross ≤ 12 km/h | Sí | 0.85 |
| Cross 12-20 km/h | Sí | 0.85 → 0.30 (lineal) |
| Cross > 20 km/h | **No** | — |
| Onshore ≤ 8 km/h | Sí | 0.50 |
| Onshore > 8 km/h | **No** | — |

El offshore fuerte descalifica: por encima de 35 km/h no se puede remar ni entrar.

### Score (0-100)

Se calcula solo si el gate pasó:

```
factor_altura   = 1.0 si la altura cae dentro de rango_ideal;
                  entre min_altura y el piso de rango_ideal sube lineal de 0.4 a 1.0;
                  entre el techo de rango_ideal y max_altura baja lineal de 1.0 a 0.4
factor_periodo  = lineal de 0.0 en min_periodo a 1.0 en 16 s, con tope en 1.0
factor_dir      = 1.0 en spot.swell.ideal, baja lineal a 0.5 en los bordes de la ventana
factor_viento   = tabla de arriba

score = 100 × (0.35×factor_altura + 0.30×factor_periodo
             + 0.15×factor_dir + 0.20×factor_viento)
```

Es un promedio ponderado **a propósito** — acá sí corresponde, porque solo rankea entre
opciones que ya son todas surfeables.

### Agregación: de horas a días a ventanas

- **Día bueno** = al menos **3 horas de luz consecutivas** que pasan el gate completo.
  Una hora aislada es una casualidad del modelo, no una sesión.
- **Score del día** = promedio del mejor bloque de 3 horas consecutivas.
- **Ventana** = **2 o más días buenos consecutivos** en el mismo spot. Un solo día
  bueno no justifica un viaje.

### Regla de alerta

Una ventana dispara alerta solo si **también apareció en la corrida del día anterior**.

Esto filtra los swells fantasma que el modelo inventa y borra al día siguiente. Cuesta
un día de anticipación, lo cual es aceptable con un horizonte de 3-6 días.

**Anti-repetición:** cada ventana alerta **una sola vez**. Se re-alerta únicamente si
mejora de forma significativa: el score sube más de 15 puntos, o la ventana se extiende
en un día o más.

### Dos niveles de notificación

Los dos modos de fallar no son simétricos. Un falso negativo hace perder un swell; un
falso positivo erosiona la confianza hasta que el bot se ignora — y el resultado final
es el mismo. Para no tener que elegir:

- **🔥 ALERTA** — pasa el gate completo más la persistencia. Push inmediato a Telegram.
- **📋 Digest semanal** — los domingos, todo lo que quedó cerca del umbral (falló por un
  solo criterio, por ejemplo período 8.5 s). Sin push agresivo. **Se envía siempre**,
  incluso sin nada que reportar; en ese caso una sola línea de "sin ventanas esta
  semana". Además de cerrar el hueco de los falsos negativos, funciona como latido del
  sistema (ver *Riesgo operativo*).

Así nada se pierde en silencio, pero el push solo suena cuando vale la pena.

---

## Perfiles de spot

### Esquema

```yaml
- id: chapadmalal
  nombre: "Chapadmalal, Argentina"
  pais: AR
  lat: -38.15
  lon: -57.68
  tipo: point_break          # point_break | beach_break | reef

  costa_mira: 140            # grados; rumbo hacia el que mira la playa

  swell:
    ventana: [110, 200]      # rango de direcciones que efectivamente entran
    ideal: 157               # dirección óptima
    min_altura: 1.0          # empieza a funcionar
    max_altura: 3.5          # arriba de esto cierra o no es surfeable
    rango_ideal: [1.5, 2.5]  # donde da su mejor versión
    min_periodo: 9

  viento_ideal: 315          # dirección desde la que sopla el offshore ideal
  temporada: [3,4,5,6,7,8]   # meses de temporada (informativo, no gate)

  url_surfforecast: "https://es.surf-forecast.com/breaks/Chapadmalal/forecasts/latest/six_day"
  fuentes: [surf-forecast, wannasurf]
  confianza: alta            # alta | media | baja
```

El campo **`confianza`** no es decorativo: cuando es `baja`, la calibración por backtest
histórico tiene prioridad sobre el dato documentado. El sistema registra explícitamente
dónde no sabe.

**`temporada` es informativo y no forma parte del gate.** Se usa para validar la
distribución estacional en el backtest y para dar contexto en el mensaje, pero no
bloquea alertas fuera de temporada — un buen swell en un mes atípico sigue siendo un
buen swell.

### Método de investigación por spot

Tres fuentes cruzadas. **Donde se contradigan, gana el backtest histórico.**

1. **surf-forecast.com** — dirección ideal de swell, dirección ideal de viento, tipo de
   pico, temporada. Cobertura confirmada en los 13 spots.
2. **Wannasurf** — rango de tamaño (`starts working at` / `holds up to`), marea, tipo de
   fondo, consistencia. Es la única fuente que da el techo de tamaño.
3. **Geometría de la costa** — `costa_mira` se calcula desde la geometría real del
   litoral en las coordenadas del spot, no se estima a ojo. Se contrasta contra el
   `viento_ideal` documentado: si no coinciden dentro de ~30°, hay un error y el perfil
   se revisa a mano.

Cada perfil queda con sus fuentes citadas en el YAML.

**Criterio de aceptación de la investigación:** ningún spot entra en producción sin los
seis campos de `swell` completos, `costa_mira` verificado contra `viento_ideal`, y un
valor de `confianza` asignado.

### Ejemplos ya investigados

**Chapadmalal** (fuente: surf-forecast, 2026-08-13) — swell ideal *South southeast*,
viento ideal *Northwest*, tipo *exposed point break*, temporada *otoño e invierno*,
riesgo *rocas sumergidas*.

**Chicama** (fuente: Wannasurf, 2026-08-13) — swell *SouthWest, South*, tamaño *starts
working at <1m, holds up to 4m+*, viento *East, NorthEast*, marea *todas, mejor
subiendo*, fondo *arena con roca*, tipo *point-break*, consistencia *muy alta, 150
días/año*.

### Los 13 spots

**Originales (7)** — coordenadas verificadas contra Open-Meteo el 2026-08-13:

| Spot | País | Lat | Lon |
|---|---|---|---|
| La Barra, Punta del Este | UY | -34.92 | -54.85 |
| Chapadmalal | AR | -38.15 | -57.68 |
| Praia do Rosa | BR | -28.13 | -48.63 |
| Buchupureo | CL | -36.08 | -72.79 |
| Asia (Mar Azul) | PE | -12.78 | -76.63 |
| Huanchaco | PE | -8.08 | -79.12 |
| Playa Santa Teresa | CR | 9.65 | -85.17 |

**Agregados (6)** — coordenadas a verificar en la fase de investigación:

| Spot | País | Motivo |
|---|---|---|
| Saquarema, RJ | BR | Mejor beach break de Brasil, sede del CT |
| Punta de Lobos, Pichilemu | CL | La izquierda más consistente de Chile, aguanta tamaño grande |
| Chicama | PE | La izquierda más larga del mundo, 150 días/año |
| Lobitos | PE | Izquierdas de clase mundial, ventana Abr-Oct |
| Punta del Diablo | UY | Más expuesto al swell que La Barra; cubre cuando Punta no entra |
| Florianópolis (Joaquina/Mole) | BR | Complementa Praia do Rosa, a 90 km |

Santa Teresa es Costa Rica, no Sudamérica; se mantiene por pedido explícito.

**Banco de spots para más adelante:** Necochea y Mar del Plata (AR), Pacasmayo y Punta
Hermosa (PE), Iquique y Arica (CL), Garopaba e Itacaré (BR), José Ignacio y La Pedrera
(UY).

### Alcance: la marea queda fuera

La marea **no forma parte del gate** en esta versión. Open-Meteo no la provee, sumarla
implica otra fuente de datos, y solo algunos de los spots dependen fuerte de ella. La
alerta incluye el link de surf-forecast, donde la marea se consulta directamente.

Si el backtest muestra que en algún spot específico la marea explica una parte grande
de la varianza, se agrega solo para ese spot.

---

## Validación

Un algoritmo sin validar es una opinión. **Estas tres pruebas se ejecutan antes de que
el sistema mande su primer mensaje.**

### 1. Backtest histórico (2023-2025)

Se corre el detector sobre tres años completos de datos de archivo de Open-Meteo en los
13 spots. Dos criterios objetivos:

- **Volumen.** Rango sano: **10 a 25 alertas por spot por año**. Menos de 5 significa
  que el filtro está estrangulado; más de 60 significa que es ruido.
- **Estacionalidad.** La distribución de alertas debe coincidir con las temporadas
  conocidas: Perú y Chile concentrados en invierno austral (abril-septiembre), Costa
  Rica en mayo-octubre, el Atlántico sur en otoño-invierno.

**Si la distribución estacional no coincide con la realidad documentada, el algoritmo
está mal.** Es un test objetivo que no depende de la opinión de nadie.

### 2. Cross-check contra surf-forecast

Para una muestra de días, se comparan los valores de Open-Meteo contra los que muestra
surf-forecast en el mismo spot y momento. Si aparece un sesgo sistemático en algún spot
—típico donde la batimetría es particular— se calibra un offset para ese spot.

### 3. Ground truth del usuario

Se presentan los **top 10 días históricos** que el algoritmo eligió para el spot que el
usuario mejor conozca, y él indica cuáles fueron realmente buenos. Es la única prueba
que valida contra la realidad y no contra otro modelo. Los umbrales se ajustan con ese
resultado.

### 4. Tests unitarios de `score.py`

Casos construidos a mano, con resultado esperado explícito:

| Caso | Esperado |
|---|---|
| Swell perfecto + onshore 15 km/h | No pasa gate |
| Swell perfecto + offshore 40 km/h | No pasa gate |
| Altura sobre `max_altura` | No pasa gate |
| Dirección fuera de ventana | No pasa gate |
| Buenas condiciones a las 3 AM | No pasa gate (fuera de luz) |
| 2 horas buenas consecutivas | Día no bueno |
| 3 horas buenas consecutivas | Día bueno |
| 1 día bueno aislado | Sin ventana |
| 2 días buenos consecutivos, sin corrida previa | Sin alerta (falta persistencia) |
| 2 días buenos consecutivos, confirmados ayer | Alerta |

Son la red que permite ajustar umbrales después sin romper nada en silencio.

---

## Arquitectura

### Ejecución: GitHub Actions

Corre en la nube, diariamente, sin depender de que la Mac esté encendida. Un cron local
solo dispara si la computadora está prendida, y el día que se pierde el swell es
justamente el que quedó apagada.

- Repo privado, gratis en este volumen de uso.
- El token de Telegram va como **GitHub Secret** — no queda en el código ni lo maneja
  nadie más que el usuario.
- `state.json` se versiona en el repo, lo que da persistencia entre corridas y además
  historial auditable de qué se alertó y cuándo.
- Corre a las **7:00 AM hora Argentina** (10:00 UTC).

### Estructura

```
app_surf_forecast/
├── spots.yaml              # los 13 perfiles investigados
├── fetch.py                # Open-Meteo: marine + viento + sunrise/sunset
├── score.py                # gate + score  ← el corazón
├── alert.py                # ventanas, persistencia, anti-repetición
├── notify.py               # Telegram
├── backtest.py             # validación histórica
├── tests/test_score.py     # los casos de la tabla de arriba
├── state.json              # corridas previas y ventanas ya alertadas
└── .github/workflows/daily.yml
```

Cada módulo tiene una responsabilidad y una interfaz clara:

| Módulo | Entrada | Salida | Depende de |
|---|---|---|---|
| `fetch.py` | lista de spots | series horarias por spot | Open-Meteo |
| `score.py` | serie horaria + perfil de spot | días buenos con score | nada (puro) |
| `alert.py` | días buenos + `state.json` | ventanas a alertar | nada (puro) |
| `notify.py` | ventanas | mensajes enviados | Telegram |

`score.py` y `alert.py` son **funciones puras sin I/O**, lo que los hace testeables sin
red y permite correr el backtest reutilizando exactamente el mismo código que
producción. Es deliberado: el backtest no valida nada si prueba un camino distinto al
que corre en vivo.

### Entrega: Telegram

Bot propio creado por el usuario vía @BotFather. El token se guarda como GitHub Secret.

Formato del mensaje:

```
🔥 BUEN SWELL — Chicama, Perú
Vie 21 a Dom 23 de agosto (3 días)

Vie 21  1.8m @ 14s del SW  ·  viento E 9km/h offshore  ·  87/100
Sáb 22  2.1m @ 15s del SSW ·  viento E 6km/h offshore  ·  94/100
Dom 23  1.6m @ 13s del SW  ·  viento NE 11km/h cross   ·  78/100

Mejor ventana: sábado 7-11 AM
Confirmado en 2 corridas consecutivas ✓
→ ver en surf-forecast
```

### Manejo de errores

| Falla | Comportamiento |
|---|---|
| Open-Meteo caído o timeout | 3 reintentos con backoff; si falla, se aborta la corrida **sin escribir `state.json`** para no romper la cadena de persistencia, y se notifica el error por Telegram |
| Un spot devuelve datos incompletos | Se saltea ese spot, los demás siguen; queda registrado en el log |
| Telegram falla | Se reintenta; si falla, la corrida queda marcada como no notificada y la ventana se re-evalúa al día siguiente |
| Corrida diaria no ejecutada | Al día siguiente la persistencia detecta el hueco y trata la corrida como primera observación (no alerta, espera confirmación) |

El principio: **ante la duda, no escribir estado corrupto**. Es preferible perder una
corrida que envenenar la cadena de persistencia.

---

## Costo

**Requisito del usuario: el sistema tiene que ser gratis.** Verificado el 2026-08-13.

| Servicio | Límite del tier gratuito | Uso estimado | Margen |
|---|---|---|---|
| Open-Meteo | 10.000 llamadas/día, 300.000/mes | ~39/día (13 spots × 3 endpoints) | 0,4% |
| GitHub Actions | 2.000 min/mes en repo privado (plan Free) | ~60 min/mes (2 min/día) | 3% |
| Telegram Bot API | sin límite relevante | 0-4 mensajes/semana | — |

**Costo total: USD 0.** El margen es de dos órdenes de magnitud en ambos servicios, así
que ampliar la lista de spots no acerca el sistema a ningún techo.

Condiciones a respetar:

- El tier gratuito de Open-Meteo es **solo para uso no comercial**. Este proyecto es de
  uso personal y califica. Si eso cambiara, hay que revisar la licencia.
- Open-Meteo no ofrece garantía de uptime en el plan gratuito. Cubierto por el manejo de
  errores: una corrida fallida no escribe estado y se recupera al día siguiente.
- El backtest usa la Archive API, también incluida en el tier gratuito. Es una carga
  puntual de ~40 llamadas, no recurrente.

## Riesgo operativo: desactivación del workflow programado

**GitHub desactiva automáticamente los workflows programados en repos que pasan 60 días
sin actividad de commits.** Es la falla más peligrosa del diseño porque es silenciosa:
el sistema deja de correr y no avisa.

**Mitigación:** el workflow commitea `state.json` en cada corrida diaria, lo que mantiene
el repositorio activo de forma permanente y evita que el contador de 60 días llegue a
cumplirse. Como respaldo, GitHub envía un aviso por email antes de desactivar, y
reactivar es un clic en la pestaña Actions.

**Verificación:** el mensaje de digest de los domingos se envía siempre, incluso cuando
no hay nada cerca del umbral (en ese caso, una línea de "sin ventanas esta semana").
Funciona como latido: si un domingo no llega nada, el sistema está caído.

## Fuera de alcance

- Marea como criterio del gate (ver *Alcance: la marea queda fuera*).
- Temperatura del agua y recomendación de traje.
- Precios de vuelos o integración con reservas.
- Interfaz web o dashboard. La entrega es Telegram.
- Predicción propia: se consume modelo de terceros, no se genera pronóstico.

## Decisiones abiertas para la implementación

Ninguna. Los umbrales iniciales quedan definidos arriba y se ajustan con el resultado de
la validación, que es un paso explícito del plan de implementación.
