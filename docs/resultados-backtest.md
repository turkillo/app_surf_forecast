# Resultados del backtest histórico (Tarea 12)

Validación del detector sobre **2023-01-01 a 2025-12-31**, 13 spots, corriendo el
**mismo camino que producción**: multi-modelo con consenso
(`_combinar_multimodelo` → `evaluar_dia_multimodelo` → `detectar_ventanas`).
Reproducible con `python backtest.py`.

Criterios (del spec): volumen sano 10-25 ventanas/spot/año; menos de 5 es filtro
estrangulado, más de 60 es ruido. La distribución mensual tiene que coincidir con
la `temporada` declarada.

---

## 1. Lo que el backtest puede y no puede ver

**El archivo de Open-Meteo no sirve los mismos modelos de olas que producción.**
Verificado pidiendo cada modelo mes a mes en el período completo:

| Tramo | Modelos de olas disponibles |
|---|---|
| 2023-01-01 → 2024-06-07 | `gwam` + `meteofrance_wave` |
| 2024-06-08 → 2024-06-18 | solo `meteofrance_wave` |
| 2024-06-19 → 2025-12-08 | `meteofrance_wave` + `ncep_gfswave025` |
| 2025-12-09 en adelante | los tres |

`era5_ocean` y `era5` no devuelven swell en ninguna fecha. `marine_best_match` es
idéntico a `meteofrance_wave` y `_combinar_multimodelo` ya lo descarta por huella
de serie. De los modelos de viento, `gfs_seamless` e `icon_seamless` tienen
cobertura completa 2023-2025; `ecmwf_ifs025` no tiene datos en 2023 y arranca en
febrero de 2024, pero como sólo se empareja con el tercer modelo de olas, no
afecta.

Consecuencia: durante casi todo el período hay **2 fuentes de olas y no 3**, y
como `MINIMO_MODELOS_DE_ACUERDO = 2`, el gate pasa de "2 de 3" a "2 de 2", que es
**más estricto**. Además `ncep_gfswave025` cae en celda enmascarada como tierra en
**5 de los 13 spots** (`buchupureo`, `asia`, `huanchaco`, `punta_de_lobos`,
`joaquina`; verificado: 720/720 horas en 0.0 en junio 2025), y `surf.fetch`
descarta ese 0.0 como dato faltante. En esos 5 spots el tramo 2024-06/2025-12
queda con **una sola fuente**, que es al revés: más permisivo.

### Sesgo medido

Se midió sobre **2026-01-01 a 2026-08-10** (222 días), el único período donde el
archivo sirve los tres modelos a la vez, anulando las columnas del modelo que en
cada régimen histórico no existía. Se anulan columnas en vez de acortar la lista
de modelos a propósito: `_combinar_multimodelo` empareja el modelo de olas *i* con
el de viento *min(i, n-1)*, así que acortar la lista cambiaría también el modelo
de viento y el experimento mediría dos cosas a la vez.

| spot | producción (3 fuentes) | backtest (gwam+mf) | factor |
|---|---|---|---|
| `la_barra` | 6 | 2 | 3.00 |
| `chapadmalal` | 9 | 5 | 1.80 |
| `praia_do_rosa` | 19 | 12 | 1.58 |
| `santa_teresa` | 18 | 15 | 1.20 |
| `saquarema` | 15 | 13 | 1.15 |
| `chicama` | 13 | 11 | 1.18 |
| `lobitos` | 7 | 4 | 1.75 |
| `punta_del_diablo` | 11 | 11 | 1.00 |
| **agregado (8 spots)** | **98** | **73** | **1.34** |
| `buchupureo`, `asia`, `huanchaco`, `punta_de_lobos`, `joaquina` | — | — | 1.00 (ncep enmascarado: producción también tiene 2 fuentes) |

**Factor de corrección: ×1.34** para los 8 spots donde producción realmente tiene
una tercera fuente; **×1.00** para los 5 enmascarados, donde el backtest en régimen
de 2 fuentes *es* la configuración de producción.

**Trampa importante:** en los 5 spots enmascarados, el tramo 2024-06/2025-12 del
backtest corre con **una sola fuente** y sobrestima. `huanchaco` marca 20.7/año en
la tabla completa pero **0.7/año** en el tramo de 2 fuentes y **1 ventana en 222
días** en la configuración de producción. Su "sano" es un artefacto, no un
resultado. Por eso todas las tablas llevan `fuentes` (promedio de modelos por
hora): donde dice 1.50, la mitad del período corrió con una sola fuente.

---

## 2. Tabla de veredictos (13 spots)

`23-25` = corrida completa 2023-2025. `regA` = tramo 2023-01-01/2024-06-07, el
único con 2 fuentes genuinas en los 13 spots y por lo tanto el único comparable
entre spots. `estimado prod` = `23-25 × 1.34` para los 8 spots con tercera fuente,
y `regA` directo para los 5 enmascarados.

| spot | 23-25 v/año | fuentes | veredicto | conc | temporada | regA v/año | prod 2026 (n/222d) | **estimado prod v/año** | **veredicto prod** |
|---|---|---|---|---|---|---|---|---|---|
| `la_barra` | 4.3 | 2.01 | estrangulado | 1.19 | ok | 4.9 | 6 | **5.8** | bajo |
| `chapadmalal` | 7.3 | 2.01 | bajo | 1.32 | ok | 4.9 | 9 | **9.8** | bajo |
| `praia_do_rosa` | 16.3 | 2.00 | sano | 1.29 | ok | 14.6 | 19 | **21.8** | sano |
| `buchupureo` | 33.0 | 1.50 | alto | 1.07 | ok | 34.9 | 17 | **34.9** | alto |
| `asia` | 30.3 | 1.50 | alto | 1.07 | ok | 20.2 | 15 | **20.2** | sano |
| `huanchaco` | 20.7 | 1.50 | *sano (artefacto)* | 1.13 | ok | 0.7 | 1 | **0.7** | **estrangulado** |
| `santa_teresa` | 12.3 | 2.01 | sano | 1.34 | ok | 20.9 | 18 | **16.5** | sano |
| `saquarema` | 22.3 | 2.01 | sano | 1.20 | ok | 30.0 | 16 | **29.8** | alto |
| `punta_de_lobos` | 26.3 | 1.50 | alto | 1.19 | ok | 22.3 | 14 | **22.3** | sano |
| `chicama` | 11.7 | 2.01 | sano | 1.62 | ok | 5.6 | 13 | **15.7** | sano |
| `lobitos` | 3.0 | 2.01 | estrangulado | 1.71 | ok | 3.5 | 7 | **4.0** | **estrangulado** |
| `punta_del_diablo` | 14.7 | 2.00 | sano | 1.29 | ok | 16.7 | 11 | **19.7** | sano |
| `joaquina` | 4.0 | 1.50 | estrangulado | 1.43 | ok | 4.9 | 0 | **4.9** | **estrangulado** |

**Resumen en la columna que importa (estimado producción):** 6 sanos, 2 bajos
(`la_barra`, `chapadmalal`), 2 altos (`buchupureo`, `saquarema`), **3
estrangulados** (`huanchaco`, `lobitos`, `joaquina`), **ninguno en ruido** — el más
alto (`buchupureo`, 34.9) está a poco más de la mitad del umbral de 60. Los 13
pasan el chequeo de estacionalidad.

### Cuántas alertas esperar en total

Sumando los 13 spots: **206 ventanas/año**. Pero no caen repartidas parejo: las 619
ventanas de 2023-2025 arrancan en sólo **431 días distintos**, o sea **144 días con
aviso por año ≈ 2.8 por semana**. El resto se agrupa: 290 días con un solo spot,
109 con dos, 20 con tres, 10 con cuatro, y dos días con cinco y seis spots a la
vez. Es esperable —un mismo sistema sinóptico pega en varios spots del mismo
litoral— y significa que el usuario va a recibir varios mensajes juntos y después
días de silencio. El **98 % de las semanas** tiene al menos un aviso.

**Estos 206 son un techo, no el número de mensajes de Telegram.** El backtest
detecta ventanas sobre datos de archivo en una sola pasada; producción además exige
que la ventana haya aparecido en la corrida del día anterior (persistencia) y
aplica anti-repetición, así que sólo alerta una vez por ventana salvo que se
extienda o el score salte 15 puntos. El número real de mensajes es menor.

### Distribución mensual de ventanas (2023-2025)

| spot | 01 | 02 | 03 | 04 | 05 | 06 | 07 | 08 | 09 | 10 | 11 | 12 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `la_barra` | 1 | 2 | 1 | 2 | 1 | 3 | 0 | 3 | 0 | 0 | 0 | 0 |
| `chapadmalal` | 0 | 2 | 2 | 5 | 3 | 2 | 1 | 5 | 1 | 0 | 1 | 0 |
| `praia_do_rosa` | 2 | 0 | 3 | 5 | 5 | 4 | 4 | 7 | 7 | 5 | 1 | 6 |
| `buchupureo` | 5 | 6 | 11 | 7 | 10 | 9 | 8 | 8 | 7 | 13 | 11 | 4 |
| `asia` | 12 | 1 | 5 | 6 | 5 | 8 | 7 | 10 | 10 | 11 | 10 | 6 |
| `huanchaco` | 4 | 2 | 3 | 2 | 1 | 7 | 8 | 7 | 8 | 8 | 7 | 5 |
| `santa_teresa` | 0 | 1 | 2 | 5 | 7 | 6 | 3 | 3 | 2 | 2 | 5 | 1 |
| `saquarema` | 5 | 3 | 3 | 9 | 10 | 6 | 7 | 9 | 3 | 3 | 4 | 5 |
| `punta_de_lobos` | 4 | 4 | 6 | 6 | 9 | 5 | 9 | 10 | 7 | 9 | 7 | 3 |
| `chicama` | 0 | 0 | 0 | 2 | 7 | 5 | 6 | 4 | 5 | 4 | 2 | 0 |
| `lobitos` | 0 | 0 | 0 | 0 | 2 | 4 | 2 | 1 | 0 | 0 | 0 | 0 |
| `punta_del_diablo` | 1 | 3 | 2 | 6 | 4 | 5 | 4 | 7 | 4 | 3 | 2 | 3 |
| `joaquina` | 0 | 0 | 0 | 3 | 1 | 0 | 2 | 2 | 1 | 1 | 2 | 0 |

---

## 3. La hipótesis de temporada: validada como una sola cosa

Las 13 `temporada` descansan en una hipótesis única (todas las ventanas ven sólo
sector sur → les corresponde el motor austral, [4..10], más noviembre en
`santa_teresa`). Se validó como una sola cosa y no spot por spot.

**Días buenos por mes, sumados sobre los 13 spots (2023-2025, perfiles calibrados):**

| 01 | 02 | 03 | 04 | 05 | 06 | 07 | 08 | 09 | 10 | 11 | 12 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 131 | 89 | 134 | 231 | **314** | 293 | 272 | 264 | 259 | 240 | 209 | 117 |

- **73.4 % de los días buenos caen en abril-octubre**, contra el **58.3 %** que
  daría una distribución uniforme (7 de 12 meses). Concentración global **1.26**.
- La curva es limpia: mínimo en febrero y diciembre, máximo en mayo-junio, meseta
  hasta octubre, hombro en noviembre.
- **Los 13 spots tienen concentración > 1.0**, entre 1.13 y 1.57, todos en el mismo
  sentido. El mes pico cae entre abril y septiembre en 12 de 13 (`joaquina` pica en
  septiembre).

**Veredicto: la hipótesis se sostiene.** No hay ningún spot con el signo invertido
ni un patrón sistemático de corrimiento. La concentración es moderada (1.26, no
1.71) porque estos mares no se apagan en verano, no porque la ventana esté mal
orientada.

Nota sobre la métrica: `coincide_la_temporada` compara contra un 60 % fijo, pero
una temporada de 7 meses ya cubre el 58 % del año, así que ese umbral casi no
discrimina por sí solo. Por eso se agregó `concentracion()` (fracción observada /
fracción esperada por azar), que es el número que hay que leer. También se agregó
un test que verifica, para los 13 spots reales, que el chequeo rechaza una
distribución enteramente fuera de temporada: ningún spot declara los 12 meses, así
que el chequeo no es vacío en ninguno. **La excepción histórica de `santa_teresa`
ya no existe** — hoy declara `[4..11]` y discrimina como los demás.

---

## 4. Ajustes aplicados y por qué

### 4.1 `min_periodo` −2 s en los 13 spots (9 → 7, 10 → 8)

**Motivo: error de unidades, no de umbral.**

El diagnóstico de rechazos sobre las horas de luz de 2023-2025 mostró que
`período corto` era la segunda causa (21-29 % de los rechazos por modelo en los
spots atlánticos), con `swell_wave_period` mediano de 6.9-7.8 s contra umbrales de
9-10 s.

`min_periodo` se compara contra `swell_wave_period` de Open-Meteo, que es el
**período medio** de la partición de swell. La regla que fijó 9 s (beach break) y
10 s (point break y reef) está escrita en la unidad que publican surf-forecast y
Wannasurf, que es el **período pico**. Open-Meteo no sirve período pico para estos
modelos: `swell_wave_peak_period` devuelve vacío (verificado).

**Medición del desvío** — comparación pareada contra surf-forecast, 14-16/08/2026,
3 franjas por día, 5 spots, **n = 45**:

| spot | altura OM/SF | período OM − SF |
|---|---|---|
| `la_barra` | 1.04 | −1.4 s |
| `joaquina` | 0.88 | −4.2 s |
| `chapadmalal` | 0.89 | −1.4 s |
| `chicama` | 0.82 | −2.2 s |
| `punta_de_lobos` | 1.00 | −3.3 s |
| **global** | **0.92** | **−2.1 s** |

El signo es el mismo en los 5 spots. La física corrobora: para un espectro tipo
JONSWAP, `Tp ≈ 1.2-1.3 · Tm`, o sea ~1.8-2.2 s de diferencia con `Tm ≈ 7.5 s`.

Se aplicó **−2 s uniforme** a los 13. No es aflojar un umbral para que entren más
días: es escribir el mismo umbral en la unidad de la variable que se mide.

**La altura, en cambio, NO tiene sesgo:** el cociente Open-Meteo / surf-forecast da
**0.92** (−8 %), muy por debajo del ~20 % que el brief marca como umbral para
compensar. **No se ajustó ningún `min_altura` por sesgo de medición.**

### 4.2 `min_altura` en 5 spots — **decisión explícita del usuario**

> **Estos cinco números los eligió el usuario, no los derivó el backtest.** Se le
> presentaron tres opciones (mantener la propuesta del backtest, volver a 1.0 m en
> todos, o un punto intermedio) y eligió el intermedio. Su razonamiento: la regla
> original de 1 m sigue valiendo como criterio, pero acepta subirla donde 1 m es un
> día cualquiera y no un evento; prefiere más alertas que la propuesta del backtest
> y menos ruido que volver a 1.0 en todos. **Quien lea esto en seis meses: no son
> valores optimizados, son una preferencia declarada, y cambiarlos requiere volver
> a preguntar.**

Se hizo en dos pasadas: primero un punto intermedio, y después —al ver que tres
spots quedaban en 33-40 ventanas/año con la concentración estacional caída a
1.03-1.08— el usuario subió esos tres un escalón más. `asia` y `santa_teresa`
quedaron donde estaban porque ya daban sano.

| spot | original | propuesta del backtest | 1.ª elección | **valor final (usuario)** | tope (`rango_ideal[0]`) |
|---|---|---|---|---|---|
| `buchupureo` | 1.0 | 2.0 | 1.5 | **1.8** | 2.0 |
| `asia` | 1.0 | 1.5 | 1.2 | **1.2** | 1.7 |
| `santa_teresa` | 1.0 | 1.2 | 1.2 | **1.2** | 1.3 |
| `saquarema` | 1.0 | 1.5 | 1.2 | **1.4** | 2.3 |
| `punta_de_lobos` | 1.0 | 1.8 | 1.5 | **1.8** | 2.3 |

En los 5 casos el `min_altura: 1.0` no era un dato medido: la investigación lo
documenta como *"piso del usuario"* porque Wannasurf decía *"starts working at less
than 1 m"*. Corregido el período, esos cinco spots daban entre 33 y 41
ventanas/año, es decir el detector estaba llamando "bueno" al día normal del spot.
La propuesta del backtest se había fijado con una regla puesta **antes** de mirar
resultados (subir sólo hasta `rango_ideal[0]`); el usuario se quedó por debajo de
esa propuesta en 4 de los 5.

**`rango_ideal` no se recalculó, y es deliberado.** El validador de `surf.spots`
exige `rango_ideal ⊂ [min_altura, max_altura]`, y como los cinco valores finales
son **más bajos** que los de la propuesta, ninguno rompe la contención (verificado
spot por spot antes de aplicar). Se evaluó re-derivar `rango_ideal` con la
convención de fracciones documentada y **se descartó**: esa convención toma como
entrada el *piso de funcionamiento del spot* (1.0 m, *"starts working at"*), que es
un hecho físico que no cambió. `min_altura` pasó a cumplir un segundo papel —piso
de alerta, calibrado— y realimentar ese número en la fórmula confundiría las dos
cosas y correría la banda ideal por encima de lo que dice la investigación. Además
`rango_ideal` sólo entra en el *score*, nunca en el gate, así que mantenerlo no
cambia ninguna ventana detectada.

**Efecto de la decisión del usuario respecto de la propuesta del backtest**
(estimado producción, ventanas/año):

| spot | con la propuesta | 1.ª elección | **valor final** | veredicto final |
|---|---|---|---|---|
| `buchupureo` | 25.1 | 39.7 | **34.9** | alto |
| `asia` | 13.2 | 20.2 | **20.2** | sano |
| `santa_teresa` | 16.5 | 16.5 | **16.5** | sano |
| `saquarema` | 24.1 | 35.3 | **29.8** | alto |
| `punta_de_lobos` | 22.3 | 39.0 | **22.3** | **sano** |

`punta_de_lobos` vuelve a `sano`; `buchupureo` y `saquarema` quedan en `alto`.
**Ninguno entra en zona de ruido**: el máximo es 34.9 contra un umbral de 60.

### El mecanismo "piso más alto ⇒ selecciona eventos": evidencia, no hipótesis

La primera elección del usuario dejó a tres spots con la concentración estacional
caída, lo que permitió medir el efecto de subir el piso sobre esos mismos tres:

| spot | `min_altura` | conc. antes | conc. después | Δ |
|---|---|---|---|---|
| `punta_de_lobos` | 1.5 → 1.8 | 1.08 | **1.19** | **+0.11** |
| `buchupureo` | 1.5 → 1.8 | 1.03 | **1.07** | +0.04 |
| `saquarema` | 1.2 → 1.4 | 1.22 | **1.20** | −0.02 |

**El mecanismo se confirma parcialmente, no del todo.** En `punta_de_lobos` el
efecto es claro y cruza el 1.15; en `buchupureo` la dirección es la esperada pero
el tamaño es chico y sigue casi uniforme (1.07); en `saquarema` el movimiento es
del signo contrario, aunque dentro del ruido de una muestra de 67 ventanas.

La lectura honesta: **subir el piso mueve la concentración en la dirección
esperada, pero no es una palanca fuerte ni fiable spot por spot.** Donde funcionó
de verdad fue en `asia` (1.01 → 1.07 con +0.2 m, y 1.31 con +0.5 m en la prueba
previa), que era el caso extremo. En spots como `buchupureo`, donde el mar es
grande y consistente todo el año, la estacionalidad del *volumen de alertas* va a
ser débil por más que se suba el piso, sencillamente porque el spot funciona todo
el año. Eso no es un defecto del detector.

### 4.3 El caso `asia`: por qué su `NO COINCIDE` no se arregló con la regla del brief

`asia` era el único spot que fallaba estacionalidad (concentración **1.01**, o sea
distribución exactamente uniforme). La regla dice que eso significa ventana de
swell mal orientada. **Se verificó primero, y no era eso.**

Dirección mediana del swell en `asia`, todas las horas de luz, por mes:

| 01 | 02 | 03 | 04 | 05 | 06 | 07 | 08 | 09 | 10 | 11 | 12 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 206 | 202 | 203 | 202 | 203 | 205 | 203 | 202 | 199 | 201 | 201 | 199 |

El swell llega de 199-206 **todos los meses del año**, dentro de la ventana
`[180, 270]` y a ~20 grados de `ideal: 225`. La geometría está bien. Lo que sí
cambia con la estación es la **altura** (mediana de los días buenos: 1.95 m en
abril, 1.83 en mayo, contra 1.35-1.48 en diciembre-marzo).

El `NO COINCIDE` venía de que `min_altura: 1.0` estaba **por debajo de la línea de
base del año entero** en la costa central peruana: con ese piso el detector
seleccionaba "día normal en Perú", que es aseasonal por construcción, en vez de
seleccionar eventos. Subiendo el piso, `asia` deja de fallar el chequeo. Con el
piso de 1.5 que había propuesto el backtest la concentración subía a 1.31; con el
**1.2 que eligió el usuario** queda en **1.07** — pasa el chequeo, pero por poco
margen sobre una distribución uniforme, y el volumen sube a 30.3/año en la corrida
histórica. Es el intercambio consciente descrito en 4.2.

Queda registrado explícitamente: **la corrección de estacionalidad de `asia` es un
efecto secundario de una corrección de volumen, no un umbral movido para silenciar
el chequeo.** La orientación de la ventana se verificó contra el dato antes de
tocar nada, y no se modificó.

### 4.4 Lo que se revisó y NO se cambió

- **La convención del `+` de Wannasurf (`2.5m+` → 2.5) no es el problema.** Se midió
  cuántas horas de luz se rechazan por `max_altura` en 2023-2025: entre **0.00 % y
  0.29 %** en los 13 spots. `max_altura` es gate duro, pero prácticamente nunca
  llega a actuar porque estos mares no alcanzan esos techos. Hipótesis medida y
  descartada.
- **`lobitos.max_altura = 3.0`** (inferencia por analogía con `chicama`,
  `confianza: baja`): sin cambios. `max_altura` no rechaza ninguna hora en
  `lobitos` (0.00 %), así que el backtest no aporta evidencia para moverlo en
  ninguna dirección. Sigue sin validar.
- **`punta_del_diablo.max_altura = 2.5`** (sospechoso por ser menor que el 3.0 de
  `la_barra`): sin cambios, mismo motivo — rechaza el 0.08 % de las horas. El spot
  queda en 19.7/año estimado, sano, así que no hay síntoma que corregir.
- **`santa_teresa.ideal = 210`** (construido, `confianza: baja`): sin cambios. La
  dirección no es la condición que limita en `santa_teresa`; su volumen y su
  estacionalidad (conc 1.34) son de los mejores del archivo.
- **`confianza`**: no se movió ninguna. Los perfiles en `baja` siguen en `baja`.

---

## 5. Los 3 spots que siguen estrangulados, y por qué

`huanchaco` (0.7/año), `joaquina` (4.9/año) y `lobitos` (4.0/año) siguen fuera de
rango **y no es un problema de umbrales**. La causa está medida:
**`gwam` y `meteofrance_wave` no describen el mismo mar en esos puntos**, y como el
gate exige que la condición pase en 2 modelos, la intersección es casi vacía.

Tasa de aprobación por modelo sobre horas de luz, tramo de 2 fuentes:

| spot | `gwam` pasa | `gwam` H mediana | `meteofrance` pasa | `mf` H mediana | acuerdo de 2 |
|---|---|---|---|---|---|
| `huanchaco` | 1.8 % | 0.60 m | 24.2 % | 1.24 m | **0.7 %** |
| `joaquina` | 21.5 % | 1.16 m | 0.7 % | 0.60 m | **0.7 %** |
| `lobitos` | 16.9 % | 1.56 m | 2.4 % | 0.98 m | **1.7 %** |
| `chicama` | 3.9 % | 0.70 m | 22.0 % | 1.12 m | 3.1 % |
| `la_barra` | 4.5 % | 1.04 m | 1.1 % | 0.80 m | 0.8 % |

**Cuál de los dos tiene razón** — cross-check en `huanchaco` contra surf-forecast,
14-16/08/2026, n=9:

| modelo | altura OM / surf-forecast |
|---|---|
| `meteofrance_wave` | **0.99** |
| `gwam` | **0.57** |
| `ncep_gfswave025` | sin datos (celda enmascarada, 0.0) |

`meteofrance_wave` clava el dato y `gwam` reporta el 57 % de la altura real. O sea
que en `huanchaco` hay **una sola fuente confiable**, y el consenso de 2 exige que
la fuente equivocada esté de acuerdo. El spot está estructuralmente mudo en
producción, y no por conservadurismo del filtro sino por un modelo con la celda
contaminada.

Se probó mover el punto de muestreo mar adentro (5/10/20 km sobre `costa_mira`).
Reduce la divergencia en `joaquina` (ratio gwam/mf 2.02 → 1.18 a 20 km),
`chicama` (0.75 → 0.92) y `la_barra` (1.34 → 1.16), pero **no arregla `huanchaco`**
(0.58 → 0.58, plano hasta 20 km).

**No se aplicó ningún cambio por esto**, y es deliberado: excluir un modelo por
spot, o mover las coordenadas de muestreo, no es calibrar un umbral en
`spots.yaml` — toca `fetch.py`/`consenso.py` y la definición del punto de cada
spot, cambia el dato de entrada de los 13 spots a la vez y necesita su propia
validación. **Es el pendiente número uno**, con dos caminos posibles:

1. Extender el mecanismo que ya existe para el 0.0 de `ncep_gfswave025`: detectar
   por spot qué modelo está contaminado y excluirlo, dejando explícito que ese
   spot corre con menos fuentes y nunca reporta concordancia alta.
2. Mover el punto de muestreo mar adentro donde converge (ayuda en 3 de 5, no en
   `huanchaco`).

---

## 6. Top 10 días históricos — para validar contra memoria

Estos son los días que el detector eligió, ordenados por score. **Pendiente de
ground truth del usuario** (paso 7 del brief): marcar cuáles fueron realmente
buenos y cuáles no, y volver a calibrar con esa respuesta.

### `chapadmalal`

| # | fecha | score | altura | período | dir | viento | horas buenas |
|---|---|---|---|---|---|---|---|
| 1 | 2025-08-05 | 84.3 | 1.92 m | 12.5 s | 161 | 11 km/h N | 11 |
| 2 | 2024-08-13 | 82.9 | 1.99 m | 12.3 s | 141 | 17 km/h NW | 8 |
| 3 | 2023-02-19 | 82.8 | 1.82 m | 11.9 s | 149 | 18 km/h NNW | 10 |
| 4 | 2023-09-19 | 82.6 | 1.83 m | 11.7 s | 156 | 6 km/h E | 12 |
| 5 | 2025-12-30 | 81.1 | 1.49 m | 11.5 s | 166 | 8 km/h NW | 12 |
| 6 | 2025-06-09 | 81.0 | 2.12 m | 11.2 s | 157 | 6 km/h WNW | 9 |
| 7 | 2024-06-25 | 80.9 | 1.96 m | 10.9 s | 157 | 13 km/h NW | 9 |
| 8 | 2024-07-12 | 80.8 | 1.43 m | 12.6 s | 173 | 10 km/h W | 9 |
| 9 | 2025-04-05 | 80.0 | 2.01 m | 10.8 s | 155 | 11 km/h NW | 11 |
| 10 | 2025-05-22 | 79.8 | 2.05 m | 10.8 s | 161 | 5 km/h E | 10 |

### `la_barra`

| # | fecha | score | altura | período | dir | viento | horas buenas |
|---|---|---|---|---|---|---|---|
| 1 | 2023-08-13 | 84.9 | 2.48 m | 12.3 s | 174 | 11 km/h NNW | 7 |
| 2 | 2024-08-13 | 81.9 | 2.23 m | 12.3 s | 154 | 14 km/h NNW | 11 |
| 3 | 2023-02-19 | 81.8 | 2.50 m | 11.9 s | 163 | 10 km/h NNW | 7 |
| 4 | 2024-05-16 | 81.3 | 2.00 m | 11.5 s | 168 | 14 km/h NW | 10 |
| 5 | 2025-06-08 | 80.3 | 1.57 m | 12.8 s | 164 | 6 km/h WSW | 3 |
| 6 | 2024-08-08 | 80.3 | 1.98 m | 11.2 s | 167 | 17 km/h NW | 10 |
| 7 | 2025-12-30 | 80.1 | 1.46 m | 13.5 s | 159 | 18 km/h NW | 11 |
| 8 | 2024-04-19 | 79.6 | 1.81 m | 10.8 s | 175 | 12 km/h NNW | 11 |
| 9 | 2023-08-08 | 79.0 | 2.59 m | 12.2 s | 164 | 10 km/h E | 8 |
| 10 | 2024-06-30 | 78.5 | 2.13 m | 11.9 s | 171 | 18 km/h NW | 5 |

**Los dos spots comparten el 13/08/2024 y el 19/02/2023 en el top 3**, lo cual es
coherente: están a 300 km sobre el mismo litoral y con ventanas de swell que se
solapan. Que el detector los marque juntos es señal de que está leyendo el mismo
evento y no ruido de modelo.

**Ojo con el 19/02/2023 y el 30/12/2025:** son días de verano, fuera de temporada,
y entraron con altura y período altos. Si el usuario dice que esos días no fueron
buenos, la conclusión no es subir umbrales sino que falta un criterio (muy
probablemente el viento de la tarde, o la marea, que está fuera de alcance por
diseño).

---

## 7. Estado final

- **Estacionalidad: 13/13 ok.** Hipótesis de temporada validada como una sola cosa
  (concentración global 1.26; los 13 spots > 1.0 y en el mismo sentido). Con los
  pisos que fijó el usuario, `buchupureo` (1.07) y `asia` (1.07) pasan con poco
  margen: son los que hay que revisar si aparecen alertas de verano que no sirven
  (ver 4.2).
- **Volumen: 6 sanos, 2 bajos, 2 altos, 3 estrangulados, 0 en ruido.**
- **Total: 206 ventanas/año sobre los 13 spots**, agrupadas en ~144 días con aviso
  (≈2.8 por semana), y es un techo: producción además exige persistencia y aplica
  anti-repetición.
- Ningún spot quedó en la zona de ruido, que es el modo de falla que hace que el
  usuario ignore el bot. El más alto (`buchupureo`, 34.9/año) está a poco más de la
  mitad del umbral de 60.
- **Bloqueante conocido:** `huanchaco`, `joaquina` y `lobitos` siguen estrangulados
  por divergencia entre modelos de olas, no por umbrales (sección 5).
- **Pendiente:** ground truth del usuario sobre los top 10 (sección 6).
