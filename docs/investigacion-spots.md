# Investigación de los 13 spots

Registro crudo de cada fuente **antes** de convertirla a `spots.yaml`. Si dentro de
seis meses alguien pregunta de dónde salió un número, la respuesta está acá.

Fecha de consulta de todas las fuentes: **2026-08-13**.

## Definición de `temporada` (leer antes de tocar ese campo)

> **`temporada` son los meses en que SE GENERA el groundswell que la `ventana` de ese spot
> puede recibir.** No son los meses de mejor viento, ni los de temporada turística, ni los de
> agua más cálida, ni los que una fuente llame "mejor época del año".

Esta definición faltaba en las primeras versiones de este archivo, y esa ausencia es la causa
raíz de un defecto que hubo que corregir en tres revisiones seguidas: sin una definición, el
campo se pobló con **dos cosas distintas en filas distintas** —en unos spots "los meses que
la fuente llama mejor época", en otros "los meses en que se genera el swell"— y un campo que
significa cosas diferentes según la fila es inutilizable.

Aplicada de forma uniforme a los 13, la definición da:

| Sector que ve la `ventana` | Motor | Meses de generación |
|---|---|---|
| Sur (S, SSW, SW, SSE, SE) | Océano Austral, invierno del hemisferio sur | **abril a octubre** = [4, 5, 6, 7, 8, 9, 10] |
| Norte (N, NW, NNW, NE) | Pacífico / Atlántico norte, invierno boreal | noviembre a marzo = [11, 12, 1, 2, 3] |

**Criterio de redacción, para que las dos ventanas del motor austral no se contradigan entre
bloques:** el motor austral **se genera de abril a octubre**, y esa es la frase que se usa en
todo este documento. La `temporada` de un spot es esa ventana **desplazada por el tiempo de
viaje del swell hasta ese spot**. Para los 12 spots sudamericanos el viaje es de días y no
mueve el borde, así que su `temporada` es exactamente [4..10]. `santa_teresa` es la única que
suma un mes —llega hasta noviembre— porque está a 9.65 N, mucho más lejos de la zona de
generación, y la cola de la temporada austral le aterriza recién el mes siguiente.

**Los 13 spots de este archivo tienen ventanas que ven únicamente sector sur** (verificado con
`en_ventana` contra los rumbos 290-360 y 0-70), así que a los 13 les corresponde el motor
austral. La única fila distinta es `santa_teresa`, con [4..11] por la demora de propagación
que se documenta en su bloque.

### Origen del dato: mes citado vs mes derivado

Ningún valor de `temporada` en este archivo es una cita textual de una fuente. **Los 13 son
derivados** de la definición de arriba. Eso es distinto de una estimación a ciegas: la
derivación se apoya en el sector de la `ventana`, que está medido, y en el régimen estacional
del motor correspondiente, que es inequívoco. Por eso **no baja la `confianza` de ningún
perfil**: la confianza sigue reflejando la solidez de los campos de swell y viento.

Lo que sí queda registrado, spot por spot, es qué decía la fuente y por qué se descartó.

## Método

**Fuente 1 — surf-forecast.com.** Página del break (`/breaks/<Break>`, sin el sufijo
`/forecasts/...`). De ahí salen: dirección ideal de swell, dirección ideal de viento,
tipo de pico, temporada favorita y riesgos.

**Fuente 2 — wannasurf.com.** Ficha estructurada del spot. De ahí salen `min_altura`
y `max_altura` (campo *Swell size: "Starts working at X, holds up to Y"*), que es la
única fuente que documenta el techo, más el fondo y el tipo de ola.

**Fuente 3 — geometría de la costa.** `costa_mira` NO se estimó a ojo. Se muestreó la
elevación del terreno (API de elevación de Open-Meteo, modelo Copernicus DEM) en 36
rumbos por spot y a 4 radios (2, 5, 10 y 20 km). Un punto con elevación <= 0.5 m se
considera mar. `costa_mira` es la media circular de los rumbos con mar, ponderada por
cuántos de los 4 radios dan mar en ese rumbo. Esto da el rumbo hacia mar abierto
perpendicular a la línea de costa real, y detecta obstrucciones (cabos, islas) porque
esos rumbos quedan con peso parcial o cero. El script fue de un solo uso y no se versionó;
el método queda descrito acá con el detalle suficiente para reproducirlo, y el sector de
mar medido queda registrado en el bloque de cada spot.

### Convenciones de conversión aplicadas

Además de las reglas del brief, se fijaron estas convenciones para que los números sean
reproducibles:

- **Rosa de los vientos a grados:** N=0, NNE=22, NE=45, ENE=67, E=90, ESE=112, SE=135,
  SSE=157, S=180, SSW=202, SW=225, WSW=247, W=270, WNW=292, NW=315, NNW=337.
- **`min_altura` cuando Wannasurf da una banda** (por ejemplo *"Starts working at
  1.0m-1.5m"*): se toma el **extremo inferior** de la banda, con piso absoluto 1.0 m.
- **`max_altura` cuando Wannasurf pone un `+`** (por ejemplo *"holds up to 2.5m+"*): se
  toma el número sin el `+`, igual que la regla del brief para `4m+` -> 4.0.
- **`rango_ideal`**, con `R = max_altura - min_altura`:
  - `beach_break`: `[min + R/3, min + 2R/3]` (tercio central exacto).
  - `point_break` y `reef`: `[min + R/3, min + 0.8*R]`. Se corre el techo hacia arriba
    porque un point aguanta tamaño limpio donde un beach break ya cerró.
  - Redondeado a un decimal.
- **`swell.ventana`:** `[ideal - 45, ideal + 45]`, recortada a `costa_mira ± 90` y a lo
  que la geometría muestre obstruido. Nunca `(0, 360)`.
- **`min_periodo`:** 9 s para `beach_break`, 10 s para `point_break` y `reef`.

### Verificación cruzada

Para cada spot se compara el `offshore esperado` (`costa_mira + 180`) contra el
`viento_ideal` documentado por surf-forecast. `surf.spots.cargar_spots` rechaza el perfil
si difieren más de 30 grados. Ningún número se ajustó para silenciar ese validador: donde
saltó una diferencia, se volvió a la fuente.

---

## ⚠️ LA TRAMPA DE `temporada` EN SURF-FORECAST — LEER ANTES DE TOCAR ESTE CAMPO

**La causa raíz, en una frase:** surf-forecast define "mejor época del año" como *swell
surfeable con viento flojo u offshore*, o sea que mide **días agradables, no días con olas**,
y por eso premia los meses chicos y vidriados — que en los 13 spots de este archivo son
justo los opuestos a los meses en que el spot rompe.

Copiar ese campo tal cual **invierte el signo de la temporada** en cualquier spot cuya
`ventana` de swell mire al sector sur. Pasó en cuatro de los 13 (`chicama`, `lobitos`,
`huanchaco`, `asia`) y se corrigió en las revisiones 1/5 y 2/5.

**La regla correcta.** `temporada` son los meses en que **se genera** el groundswell que la
`ventana` del spot puede ver:

| Sector que ve la `ventana` | Motor | Meses |
|---|---|---|
| Sur (S, SSW, SW, SSE, SE) | Océano Austral, invierno del hemisferio sur | **abril a octubre** |
| Norte (N, NW, NNW, NE) | Pacífico / Atlántico norte, invierno boreal | noviembre a marzo |

**Los 13 spots de este archivo ven únicamente sector sur.** Ninguna `ventana` alcanza un solo
rumbo del norte — verificado con `en_ventana` contra los rumbos 290-360 y 0-70. Incluye a
`santa_teresa`, que está en el hemisferio norte pero cuya ventana [180, 280] tampoco llega al
NW. En consecuencia: **en este archivo, una `temporada` centrada en diciembre-febrero está
mal por construcción.**

**Cómo auditarlo sin reintroducir el error.** La verificación válida es contra el régimen
físico y contra la propia `ventana` del perfil, que son independientes de surf-forecast.
**No** sirve comparar la `temporada` de un spot contra la de un vecino: si los dos salieron
de la misma estadística, la comparación detecta que hay una incoherencia pero no dice cuál de
los dos lados está mal. Ese error de método se cometió al corregir `chicama` en la revisión
1/5 y está anotado en ese bloque.

### Barrido de los 13 (revisión 2/5)

Pregunta aplicada a cada perfil: *¿la `ventana` mira al sector desde donde llega el
groundswell estacional, y la `temporada` coincide con la estación en que ese groundswell se
genera?* `solape` = meses de la `temporada` que caen dentro de abril-octubre.

Estado **final** tras aplicar la definición de forma uniforme en la revisión 3/5 y cerrar la
última fila incoherente (`santa_teresa`) en la 4/5. `solape` = meses de la `temporada` que
caen dentro de abril-octubre.

| id | ventana | ¿ve sector norte? | temporada | origen | solape | qué decía surf-forecast |
|---|---|---|---|---|---|---|
| `la_barra` | 135-225 | no | [4..10] | derivado | 7/7 | otoño e invierno |
| `chapadmalal` | 112-202 | no | [4..10] | derivado | 7/7 | otoño e invierno |
| `praia_do_rosa` | 90-180 | no | [4..10] | derivado | 7/7 | otoño e invierno |
| `buchupureo` | 197-270 | no | [4..10] | derivado | 7/7 | invierno / mayo |
| `asia` | 180-270 | no | [4..10] | derivado | 7/7 | **verano / febrero** |
| `huanchaco` | 157-247 | no | [4..10] | derivado | 7/7 | otoño / marzo |
| `santa_teresa` | 180-280 | no | **[4..11]** | derivado (motor austral + demora) | 7/7 | todo el año |
| `saquarema` | 135-225 | no | [4..10] | derivado | 7/7 | otoño / junio |
| `punta_de_lobos` | 191-270 | no | [4..10] | derivado | 7/7 | invierno / julio |
| `chicama` | 173-247 | no | [4..10] | derivado | 7/7 | **verano / febrero** |
| `lobitos` | 210-270 | no | [4..10] | derivado | 7/7 | otoño / marzo |
| `punta_del_diablo` | 90-180 | no | [4..10] | derivado | 7/7 | otoño e invierno |
| `joaquina` | 90-180 | no | [4..10] | derivado | 7/7 | invierno / junio |

**Los 13 quedan con solape 7/7 y una sola semántica.** Doce filas dicen [4..10]; `santa_teresa`
dice [4..11] —el mismo motor austral, con un mes más de cola por la distancia hasta la zona de
generación— y la diferencia está justificada en su bloque por el régimen físico, no heredada
de la fuente. **Ninguna fila declara meses que su propia `ventana` no pueda ver**, que es la
condición para que `coincide_la_temporada` discrimine algo en la Tarea 12.

**Ningún valor de `temporada` es una cita textual.** La columna "qué decía surf-forecast"
muestra por qué: de las 13 filas, ninguna coincide con lo que declara la fuente, y dos
(`asia` y `chicama`) tenían directamente el signo invertido. El campo quedó **derivado** de la
definición en los 13 casos, que es lo que lo vuelve comparable entre filas.

**Historia del defecto**, para que se entienda por qué costó tres revisiones: en la primera
pasada las 13 filas salieron de la estadística de surf-forecast, con cuatro invertidas
(`asia`, `chicama`, `lobitos`, `huanchaco`) y tres recortadas al núcleo del invierno
(`punta_de_lobos`, `joaquina`, `buchupureo`). Se corrigieron dos en la revisión 1/5 y dos en
la 2/5, spot por spot, sin tocar la causa. La causa era que **el campo nunca había sido
definido**, así que cada fila se pobló con lo que pareciera razonable en ese momento. La
revisión 3/5 definió la semántica y la aplicó a las 13 de una sola vez. La 4/5 cerró la única
fila que seguía contradiciéndola: `santa_teresa` declaraba doce meses con una `ventana` que
solo ve siete, y pasó a [4..11].

---

## la_barra — La Barra, Punta del Este, Uruguay

**surf-forecast** — `https://es.surf-forecast.com/breaks/La-Barra_2`

> Nota: el slug `La-Barra` (sin sufijo) es **otro** break, en Gran Canaria (28.14 N,
> 15.44 W). El de Uruguay es `La-Barra_2`. Se verificó por las coordenadas de la página.

- Swell ideal: *South*
- Viento ideal: *North-northwest* (descrito como offshore)
- Tipo: *Point/river* — "exposed point/rivermouth break"
- Temporada: "Autumn and winter are the optimum times of year for waves"
- Marea: mejor con marea baja
- Riesgos: "Take care of rocks in the line up"
- Coordenadas de la página: 34.92 S, 54.87 W

**Wannasurf** — `https://www.wannasurf.com/spot/South_America/Uruguay/la_barra/`

- Swell direction: no cargado en la ficha
- Swell size: *"Starts working at 1.0m-1.5m / 3ft-5ft and holds up to 3m+ / 10ft+"*
- Wind direction: no cargado en la ficha
- Tide: no cargado
- Bottom: *Sandy with rock*
- Wave type: right and left; "Hollow, Fast, Powerful"
- Consistency: *"Don't know"*
- GPS: 34° 55.174' S / 54° 51.96' W (= -34.9196, -54.8660)

**Geometría de costa** (muestreo DEM en -34.92, -54.85)

- Rumbos con mar en los 4 radios: 70 a 230 grados.
- `costa_mira` derivado: **165** (litoral orientado ENE-WSW, mar abierto al SSE).
- Offshore esperado: 345. Viento ideal documentado: 337 (NNW). Desvío: **8** OK

**Conversión**

- `tipo`: `point_break` (surf-forecast: Point/river) -> `min_periodo` 10
- `swell.ideal`: 180 (South)
- `swell.ventana`: [135, 225]. Contenida en `costa_mira ± 90` = [75, 255]. OK
- `min_altura` 1.0 / `max_altura` 3.0 -> R=3.0-1.0=2.0 -> `rango_ideal` [1.7, 2.6]
- `temporada`: **[4, 5, 6, 7, 8, 9, 10]** (derivado de la definición, revisión 3/5; ver nota abajo)
> **Origen del dato (revisión 3/5):** surf-forecast declaraba `otoño e invierno`. Ese campo mide días de
> viento flojo, no meses de swell (ver la sección de la trampa). La ventana de este spot ve
> únicamente sector sur, así que por la definición de `temporada` le corresponde el invierno
> austral completo, [4..10]. Valor **derivado**, no citado; la `confianza` del perfil no cambia
> por esto.

**Confianza: media.** Las tres fuentes son coherentes y la geometría cierra con 8 grados
de desvío, pero Wannasurf tiene los campos `Swell direction`, `Wind direction` y
`Consistency` sin cargar: el techo de 3 m viene de un solo campo sin corroborar.

---

## chapadmalal — Chapadmalal, Argentina

**surf-forecast** — `https://www.surf-forecast.com/breaks/Chapadmalal`

- Swell ideal: *South southeast*
- Viento ideal: *Northwest* (offshore)
- Tipo: *point break*, "offers both left and right hand waves"
- Temporada: otoño e invierno; mes óptimo junio
- Riesgos: "Submerged rocks are a hazard"; "Sometimes crowded here"
- Coordenadas de la página: 38.21 S, 57.69 W

**Wannasurf** — `https://www.wannasurf.com/spot/South_America/Argentina/North/chapadmalal/`

- Swell direction: *"NorthWest, West, SouthWest, South"* <- **incoherente**, ver abajo
- Swell size: *"Starts working at Less than 1m / 3ft and holds up to 2.5m+ / 8ft+"*
- Wind direction: *"North, NorthWest, West"*
- Tide: *All tides*
- Bottom: *Sandy*
- Wave type: *Point-break*, right and left
- Consistency: *Regular*
- GPS: 38° 12.418' S / 57° 41.291' W (= -38.2070, -57.6882)

**Geometría de costa** (muestreo DEM en -38.15, -57.68)

- `costa_mira` derivado: **135** (litoral orientado NE-SW, mar abierto al SE).
- Offshore esperado: 315. Viento ideal documentado: 315 (NW). Desvío: **0** OK

**Contradicción entre fuentes y cómo se resolvió**

Wannasurf lista `Swell direction: NorthWest, West, SouthWest, South`. Chapadmalal está
en la costa atlántica bonaerense: los rumbos NW, W y SW son **tierra adentro**, no puede
entrar swell de ahí. El muestreo DEM lo confirma (cero mar en todo el sector 250-360 y
0-100). Es un error de carga de Wannasurf. Se usa la dirección de surf-forecast (SSE) y
de Wannasurf se toma **solo el tamaño**, que es el campo para el que se la consulta.

**Conversión**

- `tipo`: `point_break` -> `min_periodo` **10**
- `swell.ideal`: 157 (SSE)
- `swell.ventana`: [112, 202]. Contenida en `costa_mira ± 90` = [45, 225]. OK
- `min_altura` 1.0 (Wannasurf dice "less than 1m", aplica el piso del usuario)
- `max_altura` 2.5 -> R=1.5 -> `rango_ideal` [1.5, 2.2]
- `temporada`: **[4, 5, 6, 7, 8, 9, 10]** (derivado de la definición, revisión 3/5; ver nota abajo)
> **Origen del dato (revisión 3/5):** surf-forecast declaraba `otoño e invierno`. Ese campo mide días de
> viento flojo, no meses de swell (ver la sección de la trampa). La ventana de este spot ve
> únicamente sector sur, así que por la definición de `temporada` le corresponde el invierno
> austral completo, [4..10]. Valor **derivado**, no citado; la `confianza` del perfil no cambia
> por esto.

> **Cambios respecto del perfil de ejemplo que venía en `spots.yaml`.** Ese perfil era un
> placeholder de la fase de diseño y no había pasado por Wannasurf. Se corrigieron tres
> cosas, todas por aplicar reglas del propio brief con la fuente real en mano:
> `min_periodo` 9 -> **10** (la regla dice 10 para `point_break`); `max_altura` 3.5 ->
> **2.5** (Wannasurf documenta "holds up to 2.5m+"); `confianza` alta -> **media** (por
> el campo incoherente de Wannasurf). También `costa_mira` 140 -> 135 y la ventana
> [110, 200] -> [112, 202], para que salgan de la geometría medida y de la regla
> `ideal ± 45` en vez de números redondeados a ojo.

**Confianza: media.**

---

## praia_do_rosa — Praia do Rosa, Santa Catarina, Brasil

**surf-forecast** — `https://www.surf-forecast.com/breaks/Rosa`

- Swell ideal: *southeast*
- Viento ideal: *west* (offshore)
- Tipo: *beach break*, "offers both left and right hand waves"
- Temporada: el párrafo guía dice "Winter is the best time of year for surfing here";
  la línea de estadística dice "Autumn and most often the month of May". Se toman las dos
  (otoño e invierno).
- Marea: "Good surf at all stages of the tide"
- Riesgos: "Beware of rips and rocks"
- Coordenadas de la página: 28.13 S, 48.64 W

**Wannasurf** — `https://www.wannasurf.com/spot/South_America/Brazil/Santa_Catarina/rosa_norte/`
(Wannasurf parte el spot en *Rosa Norte* y *Rosa Sul*; se tomó Rosa Norte, que es el pico
de olas más rápidas y potentes)

- Swell direction: *"North, South, SouthEast, East, NorthEast"*
- Swell size: *"Starts working at Less than 1m / 3ft and holds up to 2.5m+ / 8ft+"*
- Wind direction: *"North, NorthWest, West, NorthEast"*
- Tide: *All tides*, subiendo y bajando
- Bottom: *Sandy*
- Wave type: *Beach-break*, right and left
- Consistency: "one of the most consistent spots in the area"
- GPS: 28° 7.462' S / 48° 38.261' W (= -28.1244, -48.6377)

**Geometría de costa** (muestreo DEM en -28.13, -48.63)

- Rumbos con mar en los 4 radios: 20 a 200 grados.
- `costa_mira` derivado: **114** (mar abierto al ESE).
- Offshore esperado: 294. Viento ideal documentado: 270 (W). Desvío: **24** OK

**Conversión**

- `tipo`: `beach_break` -> `min_periodo` 9
- `swell.ideal`: 135 (SE)
- `swell.ventana`: [90, 180]. Contenida en `costa_mira ± 90` = [24, 204]. OK, y coincide
  con el sector E-SE-S que Wannasurf marca como sector de swell útil.
- `min_altura` 1.0 / `max_altura` 2.5 -> R=1.5 -> `rango_ideal` [1.5, 2.0]
- `temporada`: **[4, 5, 6, 7, 8, 9, 10]** (derivado de la definición, revisión 3/5; ver nota abajo)
> **Origen del dato (revisión 3/5):** surf-forecast declaraba `otoño e invierno`. Ese campo mide días de
> viento flojo, no meses de swell (ver la sección de la trampa). La ventana de este spot ve
> únicamente sector sur, así que por la definición de `temporada` le corresponde el invierno
> austral completo, [4..10]. Valor **derivado**, no citado; la `confianza` del perfil no cambia
> por esto.

**Confianza: alta.** Las tres fuentes coinciden: SE es la dirección ideal, el sector de
swell de Wannasurf la contiene, y el offshore documentado cae a 24 grados del que predice
la geometría.

---

## buchupureo — Buchupureo, Ñuble, Chile

**surf-forecast** — `https://www.surf-forecast.com/breaks/Buchupureo`

- Swell ideal: *Southwest*
- Viento ideal: *southeast* ("offshore winds blow from the southeast")
- Tipo: *exposed point break*
- Temporada: invierno, mes óptimo mayo
- Marea: "Best around low tide when the tide is falling"
- Notas: "Groundswells are more common than windswells"; "Often Crowded"
- Coordenadas de la página: 36.08 S, 72.80 W

**Wannasurf** — `https://en.wannasurf.com/spot/South_America/Chile/Sur/Buchupureo/`

- Swell direction: *"West, South"*
- Swell size: *"Starts working at 1.0m-1.5m / 3ft-5ft and holds up to 4m+ / 12ft"*
- Wind direction: *"North, East"*
- Tide: *All tides*, mejor bajando
- Bottom: *Sandy with rock*
- Wave type: *Rivermouth*
- Consistency: *Very consistent (150 day/year)*
- GPS: 36° 4.642' S / 72° 47.933' W (= -36.0774, -72.7989)

**Geometría de costa** (muestreo DEM en -36.08, -72.79)

- Rumbos con mar en los 4 radios: 250 a 350 y 0. El sector 190-240 (SSW a WSW) da mar
  solo en 2-3 de los 4 radios: hay obstrucción parcial por la punta al sur de la bahía.
- `costa_mira` derivado: **287** (bahía abierta al WNW).
- Offshore esperado: 107. Viento ideal documentado: 135 (SE). Desvío: **28** OK (al filo)

**Contradicción entre fuentes y cómo se resolvió**

surf-forecast dice offshore del *SE* (135); Wannasurf dice buenos vientos del *North, East*
(E = 90). La geometría predice 107 (ESE), justo entre los dos. Se usó el valor de
surf-forecast (135) porque es la fuente que el brief designa para `viento_ideal`; pasa el
validador con 28 grados de los 30 permitidos. Que las dos fuentes discrepen 45 grados
entre sí es la razón de bajar la confianza a media, no un motivo para inventar un número
intermedio.

Sobre el tipo: surf-forecast dice *point break*, Wannasurf dice *Rivermouth*. Es una
izquierda larga de desembocadura que rompe en secciones sobre fondo de arena con roca;
se clasificó `point_break`, que es lo que determina el `min_periodo` de 10 s.

**Conversión**

- `tipo`: `point_break` -> `min_periodo` 10
- `swell.ideal`: 225 (SW)
- `swell.ventana`: [197, 270]. `ideal ± 45` daría [180, 270], pero `costa_mira ± 90` =
  [197, 17] y el DEM muestra el sector 190-240 parcialmente tapado: se recorta el borde
  sur a 197. El sector [197, 270] coincide además con el rango *"West, South"* de
  Wannasurf una vez descontada la obstrucción.
- `min_altura` 1.0 / `max_altura` 4.0 -> R=3.0 -> `rango_ideal` [2.0, 3.4]
- `temporada`: **[4, 5, 6, 7, 8, 9, 10]** (derivado de la definición, revisión 3/5; ver nota abajo)
> **Origen del dato (revisión 3/5):** surf-forecast declaraba `invierno / mayo`. Ese campo mide días de
> viento flojo, no meses de swell (ver la sección de la trampa). La ventana de este spot ve
> únicamente sector sur, así que por la definición de `temporada` le corresponde el invierno
> austral completo, [4..10]. Valor **derivado**, no citado; la `confianza` del perfil no cambia
> por esto.

**Confianza: media.**

---

## asia — Asia (Mar Azul), Lima, Perú

**surf-forecast** — `https://www.surf-forecast.com/breaks/Mar-Azul-1` ("Asia - Mar Azul")

- Swell ideal: *southwest*
- Viento ideal: *northeast* ("best wind direction is from the northeast")
- Tipo: *exposed beach break*, "usually a safe bet and works all around the year"
- Temporada: verano, mes óptimo febrero
- Marea: "Good surf is found at all stages of the tide"
- Riesgos: playa privada; "unlikely to be too crowded"
- Coordenadas de la página: 12.77 S, 76.61 W

**Wannasurf** — `https://www.wannasurf.com/spot/South_America/Peru/Lima/mar_azul/`

- Swell direction: *"SouthWest, South, SouthEast"*
- Swell size: *"Starts working at Less than 1m / 3ft and holds up to 3m+ / 10ft+"*
- Wind direction: *"North"*
- Tide: *All tides*, mejor bajando
- Bottom: *Sandy*
- Wave type: *Beach-break*, right and left
- Consistency: *Very consistent (150 day/year)*
- GPS: **no cargado** ("GPS coordinates not set")

**Geometría de costa** (muestreo DEM en -12.78, -76.63)

- Rumbos con mar en los 4 radios: 140 a 340 grados.
- `costa_mira` derivado: **239** (mar abierto al WSW).
- Offshore esperado: 59. Viento ideal documentado: 45 (NE). Desvío: **14** OK

**Discrepancia menor:** surf-forecast dice viento ideal *northeast* (45), Wannasurf dice
*North* (0). Están a 45 grados. Se usa el de surf-forecast, que además cae a 14 grados del
offshore que predice la geometría; el de Wannasurf caería a 59.

**Conversión**

- `tipo`: `beach_break` -> `min_periodo` 9
- `swell.ideal`: 225 (SW)
- `swell.ventana`: [180, 270]. Contenida en `costa_mira ± 90` = [149, 329]. OK, y coincide
  con el sector SE-S-SW de Wannasurf.
- `min_altura` 1.0 / `max_altura` 3.0 -> R=2.0 -> `rango_ideal` [1.7, 2.3]
- `temporada`: **[4, 5, 6, 7, 8, 9, 10]** (corregido, ver abajo)

**Corrección aplicada (revisión 2/5): `temporada` [12,1,2] -> [4,5,6,7,8,9,10]**

El [12,1,2] salía del *"Summer, most often February"* de surf-forecast: la misma estadística
defectuosa que ya se corrigió en `chicama`, `lobitos` y `huanchaco`.

Se evaluó y se descartó el argumento de que Lima recibe swell del W/NW en verano. **No se
sostiene contra el propio perfil de este spot:** la `ventana` de `asia` es [180, 270], de S a
W. Un swell del NW llega desde ~315 y **cae fuera de esa ventana**, así que el detector no lo
vería aunque existiera. El perfil, tal como está construido, solo puede ver groundswell del
Océano Austral, que se genera de abril a octubre. Con `temporada: [12,1,2]` el solape con la
única fuente de swell que la ventana admite era de **0 meses sobre 7**: el peor de los 13.

Que Asia sea culturalmente un balneario de verano limeño no cambia cuándo rompe.

**Confianza: media** (sin cambio). La discrepancia menor de viento (NE vs N) y el GPS
faltante de Wannasurf siguen ahí y siguen siendo la razón de que no sea `alta`. La
corrección de temporada **aumenta** la solidez del perfil en vez de reducirla: reemplaza un
campo copiado de una estadística que mide otra cosa por uno derivado del régimen de swell
que la propia ventana del spot admite. No se baja a `baja` porque el dato no está en disputa
ni es una estimación: el sector de swell está medido y el régimen estacional que le
corresponde es inequívoco.

---

## huanchaco — Punta Huanchaco, La Libertad, Perú

**surf-forecast** — `https://www.surf-forecast.com/breaks/Punta-Huanchaco`

- Swell ideal: *south southwest*
- Viento ideal: *northeast* ("works best in offshore winds from the northeast"). La línea
  de estadística agrega "East-southeast" para las mejores condiciones registradas.
- Tipo: *Point*
- Temporada: otoño, mes óptimo marzo
- Marea: buena en todas
- Riesgos: "urchins and pollution"
- Coordenadas de la página: 8.08 S, 79.12 W

**Wannasurf** — `https://www.wannasurf.com/spot/South_America/Peru/North/huanchaco/`

- Swell direction: **no cargado**
- Swell size: *"Starts working at 1.0m-1.5m / 3ft-5ft and holds up to 2.5m+ / 8ft+"*
- Wind direction: **no cargado**
- Tide: *Mid and high tide*, subiendo
- Bottom: *Flat rocks with sand*
- Wave type: *Point-break*, izquierda; "a long irregular point which wraps around from the
  south for about 700m past the pier"
- Consistency: *Very consistent (150 day/year)*
- GPS: 8° 4.915' S / 79° 7.495' W (= -8.0819, -79.1249)

**Geometría de costa** (muestreo DEM en -8.08, -79.12)

- Rumbos con mar en los 4 radios: 170 a 310 grados.
- `costa_mira` derivado: **234** (mar abierto al SW).
- Offshore esperado: 54. Viento ideal documentado: 45 (NE). Desvío: **9** OK

**Conversión**

- `tipo`: `point_break` -> `min_periodo` 10
- `swell.ideal`: 202 (SSW)
- `swell.ventana`: [157, 247]. Contenida en `costa_mira ± 90` = [144, 324]. OK. La nota de
  Wannasurf ("wraps around from the south") confirma que el sector sur es el que alimenta
  la izquierda.
- `min_altura` 1.0 / `max_altura` 2.5 -> R=1.5 -> `rango_ideal` [1.5, 2.2]
- `temporada`: **[4, 5, 6, 7, 8, 9, 10]** (corregido, ver abajo)

**Corrección aplicada (revisión 2/5): `temporada` [3,4,5] -> [4,5,6,7,8,9,10]**

Mismo defecto de origen que `chicama` y `lobitos`: el [3,4,5] salía del *"Autumn, month of
March"* de surf-forecast, que es su estadística de "swell surfeable con viento flojo" y
premia los días chicos y vidriados, no los meses en que el spot rompe.

La evidencia acá es **más fuerte que la de `chicama` y no depende de ningún vecino**. El
perfil está construido enteramente sobre swell del sur y no tiene ninguna componente del
norte: `ideal: 202` (SSW), `ventana: [157, 247]`, `costa_mira: 234`, y la nota de la propia
Wannasurf, *"a long irregular point which wraps around from the south"*. Cortar la temporada
en mayo excluía junio-octubre, o sea **la mitad más fuerte de la única fuente de swell que
la ventana del spot puede ver**.

**Por qué [4..10] y no [3,4,5,9,10].** La segunda opción reflejaría que con `max_altura: 2.5`
los swells grandes de junio-agosto se le pasan de rosca al spot. Se descartó porque
`max_altura` **ya es gate duro y rechaza esos días por su cuenta**: codificar la misma
restricción en dos campos la aplicaría dos veces y, peor, dejaría a la Tarea 12 sin poder
distinguir si un `NO COINCIDE` viene de la estación o del tamaño. Cada campo restringe una
sola cosa.

**Confianza: media.** Wannasurf tiene `Swell direction` y `Wind direction` sin cargar, y
surf-forecast da dos vientos distintos (NE en la guía, ESE en la estadística). El techo de
2.5 m sí sale de Wannasurf, no es estimado.

---

## santa_teresa — Playa Santa Teresa, Guanacaste, Costa Rica

**surf-forecast** — `https://es.surf-forecast.com/breaks/Playa-Santa-Teresa`

- Swell ideal: *West northwest*
- Viento ideal: *northeast* ("Offshore winds blow from the northeast")
- Tipo: *beach break*, "exposed", "Groundswells more frequent than windswells"
- Temporada: todo el año ("usually has waves and can work at any time of the year")
- Marea: "Best around low tide"
- Riesgos: "Take care of the strong rips here"; se llena cuando funciona
- Coordenadas de la página: 9.63 N, 85.16 W

**Wannasurf** — `https://www.wannasurf.com/spot/Central_America/Costa_Rica/Guanacaste/santa_teresa/`

- Swell direction: *"NorthWest, West, SouthWest"*
- Swell size: *"Starts working at 1.0m-1.5m / 3ft-5ft and holds up to 2m+ / 6ft+"*
- Wind direction: *"West"* <- **incoherente**, ver abajo
- Tide: *Low and mid tide*
- Bottom: *Flat rocks with sand*
- Wave type: *Beach-break*, right and left
- Consistency: *Regular*
- GPS: 9° 38.233' N / 85° 10.09' W (= 9.6372, -85.1682)

**Geometría de costa** (muestreo DEM en 9.65, -85.17)

- Rumbos con mar en los 4 radios: 160 a 300 grados.
- `costa_mira` derivado: **224** (costa oeste de la península de Nicoya, mar abierto al SW).
- Offshore esperado: 44. Viento ideal documentado: 45 (NE). Desvío: **1** OK

**Contradicciones y cómo se resolvieron**

1. Wannasurf pone `Wind direction: West`. Con la playa mirando al SW (224 medido), un
   viento del oeste es onshore-cross, no offshore. surf-forecast dice NE, que la geometría
   confirma con 1 grado de desvío. Se usa NE y se descarta el campo de Wannasurf.
2. Más serio: surf-forecast da `swell ideal = West northwest` (292), pero la costa mide
   224. Un swell del WNW llega 68 grados fuera de la normal de la playa. Wannasurf lista
   *SouthWest* dentro de su rango, y el SW es el groundswell dominante del Pacífico sur en
   esta costa. **Se priorizó la geometría medida por sobre el campo de la fuente.** Ver
   abajo.

**Corrección aplicada (revisión, fix 1/5): la geometría medida gana sobre el campo de la
fuente cuando el campo cierra una compuerta**

En la primera pasada se dejó `ideal: 292` y `ventana: [225, 305]`, con el criterio de "no
tocar el número que documenta la fuente designada". **Ese criterio estaba mal aplicado
acá**, y la distinción importa para el resto del proyecto:

- La política vale cuando el número es **informativo**: si queda algo corrido, degrada un
  puntaje y el backtest lo corrige.
- No vale cuando el número **cierra una compuerta**. `swell.ventana` es gate duro: lo que
  cae afuera no genera alerta nunca, y el backtest no puede corregir lo que jamás se evaluó.

Con `ventana: [225, 305]` quedaba excluido todo el sector 180-224. El groundswell del
Pacífico sur **se genera de abril a octubre** y llega a la península de Nicoya desde ~190-215
(SSW-SW) entre abril y noviembre —un mes más tarde en la cola, por el tiempo de viaje— y
**es el swell principal de Santa Teresa**: la ventana anterior dejaba afuera la temporada
principal entera, sin una sola alerta posible. Y como `factor_dir` valía 1.0 en 292, hasta
un SW de 225 entrando de frente puntuaba la mitad.

La contradicción ya estaba medida en este mismo documento: `costa_mira` = 224 por muestreo
DEM, o sea 68 grados de desfasaje contra el `ideal` de la fuente. Con la playa mirando al
224, un WNW llega oblicuo y refractado mientras que el SW entra de frente. **La medición
propia le gana al campo de surf-forecast**, que es justamente lo que la fuente 3 existe para
arbitrar.

`confianza` sigue en `baja`: el perfil quedó armado en contra de la fuente primaria, así que
el backtest histórico tiene que revisarlo igual.

**Conversión**

- `tipo`: `beach_break` -> `min_periodo` 9
- `swell.ideal`: **210**. Entre la normal de la costa medida (224, donde la transferencia de
  energía es máxima) y el centro de la banda de llegada del groundswell del Pacífico sur
  (~202), de modo que ni el swell dominante ni un SW de frente queden penalizados. El 292 de
  surf-forecast queda descartado, con el descarte registrado arriba.
- `swell.ventana`: **[180, 280]**. Cubre entera la banda 190-215 del groundswell del sur y
  llega hasta el W para los swells de invierno boreal que documentan las dos fuentes.
  Contenida en `costa_mira ± 90` = [134, 314] y dentro del sector de mar del DEM (160-300).
- `min_altura` 1.0 / `max_altura` 2.0 -> R=1.0 -> `rango_ideal` [1.3, 1.7]
- `temporada`: **[4, 5, 6, 7, 8, 9, 10, 11]**. Es la **única fila de las 13 que no es
  [4..10]**: mismo motor austral que las otras doce, con noviembre de más por la demora de
  propagación hasta 9.65 N. Ver abajo.

**`temporada`: por qué [4..11] y no [1..12] (revisión 4/5)**

Santa Teresa **sí tiene dos motores de swell reales**, y ese conocimiento del spot no se
pierde acá:

- groundswell del **Océano Austral**, generado de abril a octubre, que llega desde ~190-215
  (SSW-SW) entre abril y **noviembre**: es el swell principal del spot;
- groundswell del **Pacífico norte**, de noviembre a marzo, que llega **del NW (~315)**.

Por eso surf-forecast la describe como spot de todo el año. Pero `temporada` no es una
descripción del spot: es lo que este perfil puede llegar a detectar, y **la `ventana` de este
perfil es [180, 280], que no alcanza el 315 del motor del norte**. Verificable en una línea:

```
.venv/bin/python -c "from surf.geo import en_ventana; print(en_ventana(315, (180, 280)))"
# False
```

Con esa ventana, **ningún swell del Pacífico norte pasa el gate direccional**, así que los
meses de noviembre a marzo no pueden producir una sola alerta en este spot. Declararlos en
`temporada` era declarar meses que el perfil nunca iba a poblar. En la revisión 3/5 estaban
cargados igual, con la contradicción anotada como deliberada; la 4/5 la resuelve: `temporada`
declara **solo el motor que la ventana ve**.

De ahí [4, 5, 6, 7, 8, 9, 10, 11]: la ventana de generación austral (abril a octubre) más
noviembre, porque a 9.65 N —mucho más lejos de la zona de generación que los otros 12— la cola
de la temporada le llega un mes más tarde. Es la única fila del archivo que no es [4..10], y
la diferencia es distancia de propagación, no otro motor.

**El motor del norte queda como conocimiento registrado, no como campo.** El orden correcto
para incorporarlo, si el backtest muestra que vale la pena, es: **primero ensanchar la
`ventana`** hasta cubrir el NW, y **recién después** ampliar `temporada` a [1..12]. Al revés
no sirve de nada: ampliar `temporada` sin tocar la `ventana` agrega meses que el gate
direccional sigue bloqueando. No se ensanchó ahora porque la ventana se corrigió en la
revisión 1/5 justamente para dejar de diluir el sector austral, que es el principal; abrirla
hasta 315 sin dato histórico volvería a ese problema.

> **Nota para la Tarea 12 — punto resuelto en la revisión 4/5.**
> La versión anterior de este bloque pedía **excluir a `santa_teresa` del chequeo de
> estacionalidad**, porque con doce meses cargados `coincide_la_temporada` devolvía `True`
> incondicionalmente y el chequeo no se aplicaba. **Esa excepción ya no hace falta**: con
> `temporada: [4..11]` el campo vuelve a discriminar —una ventana detectada en enero o en
> febrero ahora cae afuera y se reporta— así que `santa_teresa` entra en la validación de
> temporada como los otros 12, sin trato especial.
>
> Lo que el backtest sí tiene que responder acá: de los días con buen swell registrado en
> `santa_teresa`, ¿cuántos vinieron del sector 180-280 y cuántos del NW? Si la cola del NW
> resulta significativa, el cambio es **ensanchar la `ventana` primero** y ampliar `temporada`
> después. Si es marginal, el perfil queda como está.

**Confianza: baja.**

---

## saquarema — Saquarema (Itaúna), Rio de Janeiro, Brasil

**surf-forecast** — `https://www.surf-forecast.com/breaks/Saquarema`

- Swell ideal: *south*
- Viento ideal: *north*
- Tipo: *beach break*
- Temporada: otoño, mes óptimo junio (la página etiqueta la estación como *Autumn* pero el
  mes que destaca es junio, ya invierno; se toman las dos estaciones)
- Marea: todas
- Riesgos: "The crowds in the water make a gash helmet a good idea"
- Coordenadas de la página: 22.94 S, 42.48 W

**Wannasurf** — `https://www.wannasurf.com/spot/South_America/Brazil/Rio_de_Janeiro_Norte/Saquarema_-_Itauna_Beach/`

- Swell direction: *"North, NorthWest, SouthWest, South, SouthEast"*
- Swell size: *"Starts working at Less than 1m / 3ft and holds up to 5m / 16 ft and over"*
- Wind direction: *"North, NorthWest, SouthWest, South, SouthEast"* <- **idéntico al campo
  de swell**, ver abajo
- Tide: *Low and mid tide*, subiendo
- Bottom: *Sandy*
- Wave type: *Beach-break*
- Consistency: *Very consistent (150 day/year)*
- GPS: 22° 56.299' S / 42° 28.799' W (= -22.9383, -42.4800)

**Contradicción y cómo se resolvió**

Los campos `Swell direction` y `Wind direction` de Wannasurf traen exactamente la misma
lista de cinco rumbos. Que dos campos independientes coincidan letra por letra es un
artefacto de carga, no un dato: la lista además incluye N y NW, que en Itaúna son tierra
(el DEM da cero mar en todo el sector 300-80). Se descartan los dos campos direccionales de
Wannasurf y se usa solo `Swell size`, que es para lo que se la consulta. Direcciones: de
surf-forecast y de la geometría.

**Geometría de costa** (muestreo DEM en -22.94, -42.48)

- Rumbos con mar en los 4 radios: 90 a 260 grados.
- `costa_mira` derivado: **187** (mar abierto al sur).
- Offshore esperado: 7. Viento ideal documentado: 0 (N). Desvío: **7** OK

**Conversión**

- `tipo`: `beach_break` -> `min_periodo` 9
- `swell.ideal`: 180 (S)
- `swell.ventana`: [135, 225]. Contenida en `costa_mira ± 90` = [97, 277]. OK
- `min_altura` 1.0 / `max_altura` 5.0 -> R=4.0 -> `rango_ideal` [2.3, 3.7]
- `temporada`: **[4, 5, 6, 7, 8, 9, 10]** (derivado de la definición, revisión 3/5; ver nota abajo)
> **Origen del dato (revisión 3/5):** surf-forecast declaraba `otoño / junio`. Ese campo mide días de
> viento flojo, no meses de swell (ver la sección de la trampa). La ventana de este spot ve
> únicamente sector sur, así que por la definición de `temporada` le corresponde el invierno
> austral completo, [4..10]. Valor **derivado**, no citado; la `confianza` del perfil no cambia
> por esto.

**Confianza: media.** Techo de 5 m bien documentado y geometría limpia, pero los campos
direccionales de Wannasurf son inutilizables.

---

## punta_de_lobos — Punta de Lobos, Pichilemu, Chile

**surf-forecast** — `https://www.surf-forecast.com/breaks/Puntade-Lobos`

- Swell ideal: *southwest*
- Viento ideal: *east southeast*
- Tipo: *exposed reef and point break*, "A reef breaks left and there is also a left hand
  point break"
- Temporada: invierno, mes óptimo julio
- Riesgos: "Watch out for urchins, rips and rocks"; se llena con buen swell
- Coordenadas de la página: 34.42 S, 72.05 W

**Wannasurf** — `https://www.wannasurf.com/spot/South_America/Chile/Central_Santiago/punta_de_los_lobos/`

- Swell direction: *"North, NorthWest, West, SouthWest, South"*
- Swell size: *"Starts working at Less than 1m / 3ft and holds up to 5m / 16ft and over"*
- Wind direction: *"South, SouthEast, East"*
- Tide: *Low and mid tide*, subiendo y bajando
- Bottom: *Sandy with rock*
- Wave type: *Point-break*
- Consistency: *Very consistent (150 day/year)*
- GPS: 34° 25.424' S / 72° 2.87' W (= -34.4237, -72.0478)

**Geometría de costa** (muestreo DEM en -34.42, -72.05)

- Rumbos con mar en los 4 radios: 180 a 350 y 0-10. El sector 20-50 (NNE-NE) da mar
  parcial y el 70-150 es tierra: la punta cierra el este.
- `costa_mira` derivado: **281** (mar abierto al oeste).
- Offshore esperado: 101. Viento ideal documentado: 112 (ESE). Desvío: **11** OK

**Conversión**

- `tipo`: `point_break` -> `min_periodo` 10
- `swell.ideal`: 225 (SW)
- `swell.ventana`: [191, 270]. `ideal ± 45` daría [180, 270]; se recorta el borde inferior
  a 191 por el tope de `costa_mira ± 90` = [191, 11]. El rango de Wannasurf (S a N por el
  oeste) es más ancho pero no se usa para ensanchar más allá de ese tope.
- `min_altura` 1.0 / `max_altura` 5.0 -> R=4.0 -> `rango_ideal` [2.3, 4.2]
- `temporada`: **[4, 5, 6, 7, 8, 9, 10]** (derivado de la definición, revisión 3/5; ver nota abajo)
> **Origen del dato (revisión 3/5):** surf-forecast declaraba `invierno / julio`. Ese campo mide días de
> viento flojo, no meses de swell (ver la sección de la trampa). La ventana de este spot ve
> únicamente sector sur, así que por la definición de `temporada` le corresponde el invierno
> austral completo, [4..10]. Valor **derivado**, no citado; la `confianza` del perfil no cambia
> por esto.

**Confianza: alta.** Las tres fuentes coinciden: SW de swell, viento del sector E/SE,
point break, y el techo de 5 m está documentado en Wannasurf.

---

## chicama — Chicama (El Point), La Libertad, Perú

**surf-forecast** — `https://www.surf-forecast.com/breaks/Chicama` ("Chicama - El Point")

- Swell ideal: *south-southwest*
- Viento ideal: *east-northeast*
- Tipo: *beach reef and point break*; "there is a left hand point break too"
- Temporada: verano, mes óptimo febrero
- Riesgos: "Watch out for rocks"; "Relatively few surfers here, even on good days"
- Coordenadas de la página: 7.71 S, 79.45 W

**Wannasurf** — `https://www.wannasurf.com/spot/South_America/Peru/North/chicama/`
(coincide con el dato ya relevado en la fase de diseño)

- Swell direction: *"SouthWest, South"*
- Swell size: *"Starts working at Less than 1m / 3ft and holds up to 4m+ / 12ft"*
- Wind direction: *"East, NorthEast"*
- Tide: *All tides*, mejor subiendo
- Bottom: *Sandy with rock*
- Wave type: *Point-break*
- Consistency: *Very consistent (150 day/year)*
- GPS: 7° 42.301' S / 79° 27.137' W (= -7.7050, -79.4523)

**Geometría de costa** (muestreo DEM en -7.71, -79.45)

- Rumbos con mar en los 4 radios: 200 a 330. El sector 150-190 da mar parcial (3 de 4
  radios): es el cabo que arma la izquierda larga.
- `costa_mira` derivado: **263** (mar abierto al oeste).
- Offshore esperado: 83. Viento ideal documentado: 67 (ENE). Desvío: **16** OK

**Conversión**

- `tipo`: `point_break` -> `min_periodo` 10
- `swell.ideal`: 202 (SSW)
- `swell.ventana`: [173, 247]. `ideal ± 45` daría [157, 247]; se recorta el borde inferior
  a 173 por `costa_mira ± 90` = [173, 353], que es coherente con la obstrucción parcial que
  muestra el DEM entre 150 y 190. El rango de Wannasurf (S a SW, 180-225) queda contenido.
- `min_altura` 1.0 (Wannasurf "less than 1m", aplica el piso) / `max_altura` 4.0
  -> R=3.0 -> `rango_ideal` [2.0, 3.4]
- `temporada`: **[4, 5, 6, 7, 8, 9, 10]** (corregido, ver abajo)

**Corrección aplicada (revisión, fix 1/5): `temporada` [12,1,2] -> [4,5,6,7,8,9,10]**

La primera pasada dejó `[12, 1, 2]` siguiendo al pie de la letra la regla del brief
(`temporada` = temporada favorita de surf-forecast), y **registró la tensión sin resolverla**.
Registrarla no alcanzaba: el número estaba mal y había que corregirlo.

El diagnóstico original era correcto. surf-forecast define "mejor época" como *swell
surfeable con viento flojo u offshore*, o sea que premia los días chicos y vidriados, no los
meses en que el spot rompe. El groundswell del Pacífico sur que hace a Chicama entra de
**abril a octubre**.

**El argumento que sostiene la corrección es el régimen físico, no la comparación con el
vecino.** La ventana de `chicama` es [173, 247]: ve solo el sector sur, no alcanza ningún
rumbo del norte. Su única fuente de swell es el Océano Austral, que genera groundswell
durante el invierno del hemisferio sur, de abril a octubre. Una `temporada` de [12, 1, 2]
declaraba que el spot funciona justo en los meses en que su única fuente de swell está
apagada. Eso se decide con el régimen estacional y con la propia ventana del perfil, sin
mirar ningún otro spot.

> **Corrección de método (revisión 2/5).** La primera versión de este bloque apoyaba la
> conclusión en un segundo argumento: "`huanchaco` está a 42 km con la misma exposición y
> tiene [3,4,5], y dos vecinos no pueden tener temporadas disjuntas". **Ese argumento era
> circular y quedó retirado.** La `temporada` de `huanchaco` salía de la misma estadística
> defectuosa de surf-forecast, así que comparar contra ella detecta que hay una
> incoherencia pero no dice cuál de los dos lados está mal — de hecho estaban mal los dos, y
> `huanchaco` se corrigió en la revisión 2/5. Una verificación cruzada solo vale si la
> fuente con la que se cruza es independiente de la que se está auditando.

**Por qué importaba aunque `temporada` no sea gate.** No se pierden alertas: el daño es en
la Tarea 12. `coincide_la_temporada` habría dado `NO COINCIDE`, y la tabla de remediación
del plan lee esa señal como "la ventana de swell está mal orientada". O sea que el backtest
habría mandado a alguien a romper una `swell.ventana` que está bien, guiado por un campo que
estaba mal. Un dato incorrecto en un campo no-gate puede hacer que se rompa un campo que sí
lo es.

**Confianza: media** (bajada de `alta`). Las tres fuentes siguen coincidiendo en dirección
de swell (SSW/SW-S), viento del sector E/ENE y tipo point break, y el techo de 4 m está
documentado; pero la temporada quedó armada contra lo que dice surf-forecast, así que el
perfil ya no tiene las tres fuentes limpias.

---

## lobitos — Lobitos, Piura, Perú

**surf-forecast** — `https://www.surf-forecast.com/breaks/Lobitos`

- Párrafo guía: "Lobitos in Piura is an exposed beach and reef break that has quite
  reliable surf." — *"Clean groundswells prevail and the optimum swell angle is from the*
  ***northwest***. *Ideal winds are from the east."*
- Línea de estadística de la misma página: "The best conditions reported for surf at
  Lobitos occur when a ***South-southwest*** swell combines with an offshore wind direction
  from the ***East-southeast***."
- Tipo: "left hand reef break"
- Temporada: otoño, mes óptimo marzo
- Riesgos: "Take care of rocks in the line up"; casi nunca se llena
- Coordenadas de la página: 4.45 S, 81.29 W

**Wannasurf** — `https://www.wannasurf.com/spot/South_America/Peru/North/lobitos/`

- Swell direction: *"SouthWest"*
- Swell size: *"Starts working at 1.0m-1.5m / 3ft-5ft and holds up to 2m+ / 6ft+"*
- Wind direction: *"SouthEast"*
- Tide: *Mid and high tide*, subiendo
- Bottom: *Sandy with rock*
- Wave type: *Reef-rocky*, izquierda; "World Class"
- Consistency: *Regular*
- GPS: 4° 27.105' S / 81° 17.17' W (= -4.4518, -81.2862)

**Geometría de costa** (muestreo DEM en -4.45, -81.29)

- Rumbos con mar en los 4 radios: 210 a 350 y 0-10. Sector 180-200 parcial, 80-170 tierra.
- `costa_mira` derivado: **294** (mar abierto al WNW).
- Offshore esperado: 114. Vientos documentados: E=90 (guía de surf-forecast, desvío 24),
  ESE=112 (estadística de surf-forecast, desvío **2**), SE=135 (Wannasurf, desvío 21).
  Los tres pasan el validador.

**Contradicción y cómo se resolvió — este es el spot peor documentado de los 13**

surf-forecast se contradice a sí misma dentro de la misma página: el párrafo guía dice
swell ideal del **noroeste**, y la línea de estadística dice **sur-suroeste**. Son 113
grados de diferencia. Wannasurf, independientemente, dice **SouthWest**.

Se resolvió a favor del sector sur, por tres razones registrables:
1. Dos lecturas independientes (la estadística de surf-forecast y el campo estructurado de
   Wannasurf) coinciden en SSW/SW; solo una dice NW.
2. La ola es una **izquierda**. Una izquierda de point/reef se arma con swell que envuelve
   la punta desde el sur; un swell del NW entraría de frente sobre una costa que mira al
   294 y cerraría.
3. El DEM muestra el sector 210-350 abierto, o sea que tanto el SW como el NW llegan; la
   geometría sola no desempata, pero tampoco contradice al sur.

Para el viento se tomó **112 (ESE)**: es un valor documentado por surf-forecast (su propia
línea de estadística), queda entre el E de la guía y el SE de Wannasurf, y cae a 2 grados
del offshore que predice la geometría. No es un promedio inventado para pasar el validador
— los tres valores documentados pasan el validador por separado.

**Conversión**

- `tipo`: `reef` (Wannasurf *Reef-rocky*; surf-forecast "left hand reef break")
  -> `min_periodo` 10
- `swell.ideal`: 225 (SW, campo estructurado de Wannasurf, corroborado por la estadística
  SSW de surf-forecast)
- `swell.ventana`: [210, 270]. `ideal ± 45` daría [180, 270]; se recorta a 210 porque
  `costa_mira ± 90` = [204, 24] y porque el DEM muestra el sector 180-200 obstruido.
- `min_altura` 1.0 / `max_altura` **3.0** (corregido, ver abajo) -> R=2.0
  -> `rango_ideal` [1.7, 2.6]
- `temporada`: **[4, 5, 6, 7, 8, 9, 10]** (corregido, ver abajo)

**Corrección aplicada (revisión, fix 1/5): `max_altura` 2.0 -> 3.0**

En la primera pasada se tomó el *"holds up to 2m+ / 6ft+"* de Wannasurf al pie de la letra.
Se había marcado como sospechoso, pero con el argumento débil ("parece bajo para una ola
World Class"). El argumento fuerte es la **inconsistencia interna del propio `spots.yaml`**:

`chicama` está en la misma costa norte peruana, a ~400 km, es la misma izquierda larga
alimentada por el mismo groundswell del sur, y tiene `max_altura: 4.0` documentado. Que
Lobitos aguante la mitad que Chicama no es plausible físicamente.

Y el efecto es grave porque `max_altura` **es gate duro**: con 2.0, todo swell por encima de
2 m —justo el que hace funcionar el reef— quedaba mudo. El perfil silenciaba exactamente la
temporada que lo justifica.

Se subió a **3.0**, no a 4.0: Lobitos es un reef más corto y menos expuesto que el point de
arena y roca de Chicama, así que se tomó el extremo conservador del rango. **Es un valor a
calibrar en el backtest**, no una medición.

**Corrección aplicada (revisión, fix 1/5): `temporada` [3,4,5] -> [4,5,6,7,8,9,10]**

La primera pasada tomó *"Autumn, month of March"* de surf-forecast y **no chequeó el
documento de diseño del proyecto**, que en
`docs/superpowers/specs/2026-08-13-sistema-alertas-swell-design.md:322` dice textualmente:
"Lobitos | PE | Izquierdas de clase mundial, ventana **Abr-Oct**". Esa contradicción tendría
que haber estado registrada en la primera pasada y no lo estuvo.

El spec tiene razón y surf-forecast no: la ventana de Lobitos es el groundswell del Pacífico
sur, de abril a octubre, igual que la de Chicama (ver la corrección análoga en ese bloque).
El *marzo* de surf-forecast sale de su estadística de "swell surfeable con viento flojo",
que premia los días chicos y vidriados, no los meses en que el spot rompe.

**Confianza: baja.** Contradicción de 113 grados dentro de la fuente primaria, y un
`max_altura` que ahora es una inferencia por analogía con Chicama en vez de un dato.
Spot prioritario para el backtest histórico.

---

## punta_del_diablo — Punta del Diablo, Rocha, Uruguay

**surf-forecast** — `https://www.surf-forecast.com/breaks/Puntadel-Diablo`

- Swell ideal: *southeast*
- Viento ideal: *northwest*
- Tipo: *exposed beach break*, "reasonably consistent surf", "Waves at the beach tend to
  peel to the right"
- Temporada: "Autumn and winter are the favoured times of year for waves"; mes óptimo julio
- Riesgos: "Watch out for dangerous rips"
- Coordenadas de la página: 34.04 S, 53.53 W

**Wannasurf** — `https://www.wannasurf.com/spot/South_America/Uruguay/punta_del_diablo/`

La ficha está **prácticamente vacía**. Lo único cargado:

- Bottom: *Sandy*
- Consistency: *"Don't know"*
- Wave power: "Powerful, Fun"; largo normal 50-150 m, hasta 150-300 m en días buenos
- GPS: 34° 2.937' S / 53° 32.393' W (= -34.0490, -53.5399)
- Swell direction: **no cargado**
- **Swell size: no cargado** — el campo aparece como *"Starts working at ... and holds up
  to ..."* sin valores
- Wind direction: **no cargado**

**Geometría de costa** (muestreo DEM en -34.04, -53.53)

- Rumbos con mar en los 4 radios: 20 a 220 grados.
- `costa_mira` derivado: **111** (mar abierto al ESE).
- Offshore esperado: 291. Viento ideal documentado: 315 (NW). Desvío: **24** OK

**Qué faltó y qué se hizo**

Es el único spot donde **`max_altura` es una estimación**, no un dato. Wannasurf no
documenta el tamaño y no hay una segunda fuente que dé el techo. Se estimó **2.5 m** por
analogía con los otros dos beach breaks atlánticos de latitud parecida y exposición
parecida que sí están documentados: Chapadmalal (2.5 m, Wannasurf) y Praia do Rosa (2.5 m,
Wannasurf). Queda explícito que es una analogía y no una medición.

**Conversión**

- `tipo`: `beach_break` -> `min_periodo` 9
- `swell.ideal`: 135 (SE)
- `swell.ventana`: [90, 180]. Contenida en `costa_mira ± 90` = [21, 201]. OK
- `min_altura` 1.0 (piso del usuario, sin dato de origen) / `max_altura` 2.5 **estimado**
  -> R=1.5 -> `rango_ideal` [1.5, 2.0]
- `temporada`: **[4, 5, 6, 7, 8, 9, 10]** (derivado de la definición, revisión 3/5; ver nota abajo)
> **Origen del dato (revisión 3/5):** surf-forecast declaraba `otoño e invierno`. Ese campo mide días de
> viento flojo, no meses de swell (ver la sección de la trampa). La ventana de este spot ve
> únicamente sector sur, así que por la definición de `temporada` le corresponde el invierno
> austral completo, [4..10]. Valor **derivado**, no citado; la `confianza` del perfil no cambia
> por esto.

**Confianza: baja.** Regla explícita del brief: si hubo que estimar `max_altura`, es baja.

---

## joaquina — Praia da Joaquina, Florianópolis, Brasil

**surf-forecast** — `https://www.surf-forecast.com/breaks/Joaquina`

- Swell ideal: *southeast*
- Viento ideal: *northwest*
- Tipo: *exposed beach break* / "Sandbar"; "Waves at the beach are mainly lefts"
- Temporada: invierno, mes óptimo junio
- Riesgos: "Surfing here means negotiating dangerous rips"; *Often Crowded*
- Coordenadas de la página: 27.63 S, 48.45 W

**Wannasurf** — `https://www.wannasurf.com/spot/South_America/Brazil/Florianopolis/Joaquina/`

- Swell direction: *"West, SouthWest"* <- **incoherente**, ver abajo
- Swell size: *"Starts working at Less than 1m / 3ft and holds up to 3m+ / 10ft+"*
- Wind direction: *"North, NorthWest, West"*
- Tide: *All tides*, subiendo y bajando
- Bottom: *Sandy*
- Wave type: *Sand-bar*, izquierda
- Consistency: *Very consistent (150 day/year)*
- GPS: 27° 37.775' S / 48° 26.926' W (= -27.6296, -48.4488)

**Contradicción y cómo se resolvió**

Wannasurf lista `Swell direction: West, SouthWest`. Joaquina está en la costa **este** de
la isla de Santa Catarina: el oeste es la isla y el continente. El DEM lo confirma (cero
mar en 220-40). Es un error de carga. Se usa SE, de surf-forecast, que además es coherente
con el offshore del NW que las dos fuentes sí comparten (Wannasurf dice N/NW/W como buenos
vientos, y NW es justo el offshore que predice la geometría).

**Geometría de costa** (muestreo DEM en -27.63, -48.45)

- Rumbos con mar en los 4 radios: 50 a 200 grados.
- `costa_mira` derivado: **121** (mar abierto al ESE).
- Offshore esperado: 301. Viento ideal documentado: 315 (NW). Desvío: **14** OK

**Conversión**

- `tipo`: `beach_break` -> `min_periodo` 9
- `swell.ideal`: 135 (SE)
- `swell.ventana`: [90, 180]. Contenida en `costa_mira ± 90` = [31, 211]. OK
- `min_altura` 1.0 / `max_altura` 3.0 -> R=2.0 -> `rango_ideal` [1.7, 2.3]
- `temporada`: **[4, 5, 6, 7, 8, 9, 10]** (derivado de la definición, revisión 3/5; ver nota abajo)
> **Origen del dato (revisión 3/5):** surf-forecast declaraba `invierno / junio`. Ese campo mide días de
> viento flojo, no meses de swell (ver la sección de la trampa). La ventana de este spot ve
> únicamente sector sur, así que por la definición de `temporada` le corresponde el invierno
> austral completo, [4..10]. Valor **derivado**, no citado; la `confianza` del perfil no cambia
> por esto.

**Confianza: media.** El campo direccional de swell de Wannasurf es inutilizable, pero el
tamaño y el viento cierran con surf-forecast y con la geometría.

---

## Verificación de coordenadas contra Open-Meteo

Las 7 coordenadas fijadas en la fase de diseño se usaron tal cual. Las 6 restantes
(`saquarema`, `punta_de_lobos`, `chicama`, `lobitos`, `punta_del_diablo`, `joaquina`) se
tomaron de la página de surf-forecast de cada break y se contrastaron con el GPS de
Wannasurf, que coincide en todos los casos dentro de ~1.5 km.

Verificación contra el modelo marino de Open-Meteo (`swell_wave_height` a las 12 h,
2026-08-13). **Los 13 puntos devuelven dato válido; ninguna coordenada hubo que correrla
mar adentro.**

| id | lat | lon | swell_wave_height (m) |
|---|---|---|---|
| `la_barra` | -34.92 | -54.85 | 1.34 |
| `chapadmalal` | -38.15 | -57.68 | 1.38 |
| `praia_do_rosa` | -28.13 | -48.63 | 1.24 |
| `buchupureo` | -36.08 | -72.79 | 1.08 |
| `asia` | -12.78 | -76.63 | 1.36 |
| `huanchaco` | -8.08 | -79.12 | 1.14 |
| `santa_teresa` | 9.65 | -85.17 | 0.88 |
| `saquarema` | -22.94 | -42.48 | 2.30 |
| `punta_de_lobos` | -34.42 | -72.05 | 0.96 |
| `chicama` | -7.71 | -79.45 | 1.04 |
| `lobitos` | -4.45 | -81.29 | 0.98 |
| `punta_del_diablo` | -34.04 | -53.53 | 1.26 |
| `joaquina` | -27.63 | -48.45 | 0.72 |

---

## Resumen de confianza

| id | Spot | País | Confianza | Por qué |
|---|---|---|---|---|
| `praia_do_rosa` | Praia do Rosa | BR | **alta** | Las tres fuentes coinciden |
| `punta_de_lobos` | Punta de Lobos | CL | **alta** | Las tres fuentes coinciden |
| `chicama` | Chicama (El Point) | PE | media | `temporada` corregida contra surf-forecast |
| `la_barra` | La Barra | UY | media | Wannasurf sin dirección de swell ni de viento |
| `chapadmalal` | Chapadmalal | AR | media | Campo de swell de Wannasurf incoherente |
| `buchupureo` | Buchupureo | CL | media | Viento SE (surf-forecast) vs E (Wannasurf) |
| `asia` | Asia (Mar Azul) | PE | media | Viento NE vs N; Wannasurf sin GPS |
| `huanchaco` | Punta Huanchaco | PE | media | Wannasurf sin direcciones; dos vientos en surf-forecast |
| `saquarema` | Saquarema (Itaúna) | BR | media | Campos direccionales de Wannasurf duplicados |
| `joaquina` | Praia da Joaquina | BR | media | Campo de swell de Wannasurf incoherente |
| `santa_teresa` | Playa Santa Teresa | CR | **baja** | `ideal` y `ventana` reorientados contra surf-forecast, según la geometría medida |
| `lobitos` | Lobitos | PE | **baja** | surf-forecast se contradice 113 grados a sí misma; `max_altura` por analogía |
| `punta_del_diablo` | Punta del Diablo | UY | **baja** | `max_altura` estimado: Wannasurf no lo documenta |

Dos `alta`, ocho `media`, tres `baja`. Ningún perfil se infló: los `media` lo son porque una
de las tres fuentes falló en un campo concreto, y los `baja` porque el dato central está en
disputa o es una estimación. Los tres `baja` son los que el backtest histórico debería
revisar primero.

## Lección de la revisión 1/5: campos gate vs campos informativos

Los tres defectos que encontró la revisión salieron de contradicciones que este mismo
documento ya tenía registradas. El problema no fue detectarlas sino **cómo se resolvieron**.
El criterio que faltaba:

- **Campo informativo** (`swell.ideal` como semilla de puntaje, `rango_ideal`, `temporada`):
  ante la duda, se respeta lo que dice la fuente y se baja la confianza. Si queda corrido,
  degrada un puntaje y el backtest lo corrige con dato histórico.
- **Campo gate** (`swell.ventana`, `min_altura`, `max_altura`, y `swell.ideal` en la medida
  en que ancla la ventana): ante la duda, **se corrige el número**. Lo que cae afuera de un
  gate no genera alerta nunca, y el backtest no puede corregir lo que jamás se evaluó. Un
  perfil honestamente marcado como `baja` no compensa un gate mal puesto.

Corolario que costó `chicama`: un campo no-gate mal cargado puede provocar que alguien
rompa un campo gate que estaba bien, si el diagnóstico automático de la Tarea 12 lo lee como
síntoma de otra cosa. Una `temporada` incorrecta no pierde alertas por sí misma, pero manda
al backtest a reorientar una `swell.ventana` correcta.


---

# Calibración por backtest (Tarea 12)

El backtest histórico 2023-2025 corrió el detector real (multi-modelo con consenso) sobre los
13 spots y cambió cinco números de `spots.yaml`. El detalle completo —tablas por spot, sesgo
medido del backtest contra producción, y todo lo que se revisó y **no** se cambió— está en
**`docs/resultados-backtest.md`**. Acá queda sólo el registro de origen de cada número nuevo,
que es la función de este archivo.

## `min_periodo`: 9 → 7 (beach break) y 10 → 8 (point break y reef), los 13 spots

**No es un aflojamiento de umbral: es una corrección de unidades.**

La regla original de este documento ("`min_periodo`: 9 s para `beach_break`, 10 s para
`point_break` y `reef`") está escrita en la unidad que publican surf-forecast y Wannasurf,
que es el **período pico** (`Tp`). El detector la compara contra `swell_wave_period` de
Open-Meteo, que es el **período medio** de la partición de swell (`Tm`). Son dos variables
distintas. Open-Meteo no sirve período pico para estos modelos: `swell_wave_peak_period`
devuelve vacío en las tres fuentes de olas (verificado contra la API).

**Medición del desvío**, comparación pareada contra surf-forecast del 14 al 16/08/2026, tres
franjas por día, 5 spots, n = 45:

| spot | altura OM/SF | período OM − SF |
|---|---|---|
| `la_barra` | 1.04 | −1.4 s |
| `joaquina` | 0.88 | −4.2 s |
| `chapadmalal` | 0.89 | −1.4 s |
| `chicama` | 0.82 | −2.2 s |
| `punta_de_lobos` | 1.00 | −3.3 s |
| **global** | **0.92** | **−2.1 s** |

Mismo signo en los 5 spots. La física lo corrobora: para un espectro tipo JONSWAP,
`Tp ≈ 1.2-1.3 · Tm`, o sea 1.8-2.2 s de diferencia con `Tm ≈ 7.5 s`. Se aplicó **−2 s
uniforme**, que es el mismo umbral escrito en la unidad de la variable que se mide.

La **altura no tiene sesgo**: el cociente Open-Meteo / surf-forecast da 0.92 (−8 %), muy por
debajo del ~20 % que justificaría compensar. Ningún `min_altura` se movió por sesgo de
medición.

## `min_altura`: 5 spots, por volumen

Regla fijada **antes** de mirar los resultados, para no sobreajustar: `min_altura` sólo puede
subir hasta `rango_ideal[0]`, número que este documento ya define como el piso de las
condiciones buenas del spot. Alertar por debajo de él es alertar por un día del fondo del
rango.

| spot | de | a | tope permitido | motivo |
|---|---|---|---|---|
| `buchupureo` | 1.0 | **2.0** | 2.0 | 41 ventanas/año post-corrección de período |
| `asia` | 1.0 | **1.5** | 1.7 | volumen alto **y** estacionalidad plana (ver abajo) |
| `santa_teresa` | 1.0 | **1.2** | 1.3 | 33 ventanas/año |
| `saquarema` | 1.0 | **1.5** | 2.3 | 39 ventanas/año |
| `punta_de_lobos` | 1.0 | **1.8** | 2.3 | 38 ventanas/año |

En los 5 casos el `1.0` no era un dato de fuente: este documento lo registra como **"piso del
usuario"**, aplicado porque Wannasurf decía *"starts working at less than 1m"*. O sea que no
se está contradiciendo ninguna fuente; se está reemplazando un piso genérico por uno medido.

## `asia`: por qué su fallo de estacionalidad NO se resolvió reorientando la ventana

`asia` fue el único spot que falló el chequeo de estacionalidad (concentración 1.01, o sea
distribución uniforme). La regla de la Tarea 12 dice que eso indica `swell.ventana` o
`costa_mira` mal orientados. **Se verificó primero contra el dato, y no era eso:** la
dirección mediana del swell en `asia` es 199-206 grados **todos los meses del año**, dentro
de la ventana `[180, 270]` y a ~20 grados de `ideal: 225`.

Lo que sí varía con la estación es la altura (mediana de los días buenos: 1.95 m en abril
contra 1.35 m en diciembre). El problema era que `min_altura: 1.0` estaba **por debajo de la
línea de base de todo el año** en la costa central peruana, así que el detector seleccionaba
"día normal en Perú" —que es aseasonal por construcción— en vez de seleccionar eventos.

Con `min_altura: 1.5` la concentración sube a 1.31 y el volumen queda en 24/año. **La
`swell.ventana`, el `swell.ideal` y la `costa_mira` de `asia` no se tocaron**, y el corolario
de la lección 1/5 de este archivo se respetó: no se reorientó un campo gate correcto para
explicar un síntoma que venía de otro lado.

## Los tres `confianza: baja` siguen sin validar

`lobitos`, `santa_teresa` y `punta_del_diablo` eran los perfiles que el backtest debía
revisar primero. El resultado es que **el backtest no aportó evidencia para moverlos**:

- **`lobitos.max_altura = 3.0`** (inferencia por analogía con `chicama`): `max_altura` rechaza
  el **0.00 %** de las horas de luz de `lobitos` en 2023-2025. El gate nunca llega a actuar,
  así que el histórico no dice nada sobre si 3.0 es el número correcto. Sigue sin validar.
- **`punta_del_diablo.max_altura = 2.5`** (estimado por analogía, y sospechoso por ser menor
  que el 3.0 de `la_barra`): rechaza el **0.08 %** de las horas. Mismo caso. El spot queda en
  volumen sano, así que no hay síntoma que corregir.
- **`santa_teresa.ideal = 210`** (construido entre la normal de costa medida y el centro de la
  banda de groundswell): la dirección no es la condición que limita en ese spot; su
  estacionalidad es de las mejores del archivo (concentración 1.34). Sin cambios.

**La convención del `+` de Wannasurf queda medida y descartada como problema.** Se temía que
tomar `2.5m+` como 2.5 produjera techos sistemáticamente conservadores en 8 spots, y que eso
pesara por ser `max_altura` un gate duro. La medición sobre 2023-2025 dice que `max_altura`
rechaza entre **0.00 % y 0.29 %** de las horas de luz en los 13 spots: el techo prácticamente
nunca se alcanza. Ninguna `confianza` se movió por esto.
