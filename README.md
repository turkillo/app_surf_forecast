# app_surf_forecast

Sistema de alertas de swell para surf. Todos los días a la mañana revisa el
pronóstico de 13 spots (Open-Meteo), evalúa cada uno contra su propio perfil
de condiciones ideales, y manda un mensaje de Telegram cuando aparece una
ventana de buen swell confirmada en dos corridas consecutivas. Los domingos
además manda un resumen semanal aunque no haya habido alertas.

Repositorio: https://github.com/turkillo/app_surf_forecast

## Cómo funciona, en corto

- `spots.yaml` tiene el perfil de cada spot: dirección de swell ideal, altura
  mínima/máxima, período mínimo, viento ideal, etc.
- Cada mañana, `run.py` trae el pronóstico horario de cada spot, lo evalúa
  hora por hora contra su perfil (`surf/score.py`), agrupa los días buenos en
  "ventanas" (`surf/alert.py`) y manda un mensaje por Telegram
  (`surf/notify.py`) solo si la ventana se confirmó en dos días seguidos —
  así se filtran los swells fantasma que el modelo inventa y borra al otro
  día.
- El estado (`state.json`) guarda qué se observó y qué se alertó, para no
  repetir avisos y para poder confirmar ventanas entre una corrida y la
  siguiente. Solo se reescribe si la corrida terminó bien: si algo falla, el
  estado anterior queda intacto.
- Todo corre gratis en GitHub Actions (`.github/workflows/daily.yml`), una
  vez por día.

## Puesta en marcha

### 1. Crear el bot de Telegram

1. Hablá con [@BotFather](https://t.me/BotFather) en Telegram.
2. Mandale `/newbot` y seguí las instrucciones (nombre y username del bot).
3. Al terminar te va a dar un **token**, algo como
   `123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ`. Ese es tu `TELEGRAM_TOKEN`.

### 2. Obtener el chat_id

1. Mandale cualquier mensaje a tu bot recién creado (por ejemplo "hola").
2. Abrí en el navegador, reemplazando `<TOKEN>` por el token del paso
   anterior:

   ```
   https://api.telegram.org/bot<TOKEN>/getUpdates
   ```

3. En la respuesta JSON buscá `"chat":{"id":...}`. Ese número (puede ser
   negativo si es un grupo) es tu `TELEGRAM_CHAT_ID`.

### 3. Cargar los secrets en GitHub

En el repositorio, andá a **Settings → Secrets and variables → Actions →
New repository secret** y creá dos:

- `TELEGRAM_TOKEN`: el token del paso 1.
- `TELEGRAM_CHAT_ID`: el chat_id del paso 2.

Nadie más que vos y el workflow puede leer estos valores; no se muestran en
los logs ni se guardan en el código.

### 4. Disparar la primera corrida a mano

El workflow corre solo todos los días a las 07:00 (hora Argentina), pero
podés probarlo cuando quieras sin esperar:

1. Andá a la pestaña **Actions** del repositorio.
2. Elegí el workflow **"Chequeo diario de swell"** en la lista de la
   izquierda.
3. Click en **Run workflow** (botón a la derecha) → **Run workflow**.
4. Mirá los logs del job para confirmar que corrió bien. Como es la primera
   corrida, no debería mandar ninguna alerta todavía (se necesitan dos
   corridas consecutivas para confirmar una ventana) — sí debería avisar el
   resumen semanal si cae domingo.

Después de esa corrida, el workflow commitea `state.json` con el resultado
automáticamente. Ese commit diario **no es cosmético**: GitHub apaga los
workflows programados (`schedule`) si el repositorio pasa 60 días sin
actividad de commits, y esa desactivación es silenciosa — no llega ningún
aviso. El commit de estado, al correr todos los días, mantiene el repo
activo y evita que el sistema se apague solo sin que nadie se entere.

## Si el workflow falla

1. Andá a la pestaña **Actions** del repositorio y abrí la corrida que
   falló (la de la fecha en cuestión, o la última con una X roja).
2. Mirá el log del paso **"Chequear los spots"** — ahí queda todo lo que
   imprime `run.py`, con las advertencias `[WARN]` de cada spot que no trajo
   datos y, si corresponde, el `[ERROR]` final.
3. El **exit code** del paso te dice qué pasó:
   - **1**: la corrida falló porque *ningún* spot devolvió datos (Open-Meteo
     caído, o los 13 fallaron por algún otro motivo). El sistema intenta
     avisar por Telegram del fallo; si ese aviso también falla, quedás sin
     notificación y solo te enterás mirando los logs. `state.json` no se
     tocó — el próximo día arranca desde el mismo estado que tenía antes.
   - **2**: faltan los secrets `TELEGRAM_TOKEN` o `TELEGRAM_CHAT_ID`. Revisá
     que estén cargados en **Settings → Secrets and variables → Actions**
     con esos nombres exactos.
4. Si sale bien un chequeo pero falla el paso siguiente, **"Guardar el
   estado"**, sospechá primero de la protección de rama: si la rama por
   defecto tiene una regla de protección que exige pull request o revisión
   para todo push (incluyendo el del propio repositorio), el `git push` de
   ese paso va a fallar **todos los días**, aunque el chequeo de spots haya
   ido perfecto. En ese caso hay que excluir al usuario/bot que corre el
   workflow de esa regla, o darle un permiso especial para pushear
   `state.json` directo a la rama por defecto.
5. Una alerta que no llegó por un corte de Telegram no se pierde: si el
   envío de un mensaje falla, esa ventana queda sin marcar como alertada en
   `state.json` y el sistema la vuelve a intentar solo, al día siguiente.

## Ajustar los umbrales de un spot

Todos los umbrales viven en `spots.yaml`, no en el código. Para ajustar un
spot, editá su bloque:

```yaml
- id: mi-spot
  nombre: Mi Spot
  swell:
    ventana: [110, 200]      # rango de direcciones de swell aceptable (grados)
    ideal: 157                 # direccion ideal dentro de esa ventana
    min_altura: 1.0             # por debajo de esto, no hay olas suficientes
    max_altura: 3.5             # por encima de esto, el spot cierra
    rango_ideal: [1.5, 2.5]    # dentro de este rango, la altura puntua 100%
    min_periodo: 9              # periodo minimo en segundos para que valga la pena
  viento_ideal: 315             # direccion de viento offshore ideal
  costa_mira: 140                # hacia donde mira la costa (define offshore/onshore/cross)
```

Después de editar, corré `.venv/bin/pytest tests/ -q` localmente para
confirmar que el spot sigue siendo válido (por ejemplo, que `ideal` cae
dentro de `ventana`, o que `viento_ideal` es coherente con `costa_mira`) y
subí el cambio; la próxima corrida programada ya usa los valores nuevos.

## Desarrollo local

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/pytest tests/ -v
```

Para probar el pipeline completo contra los 13 spots reales sin mandar nada
a Telegram (la primera corrida nunca alerta):

```bash
TELEGRAM_TOKEN=x TELEGRAM_CHAT_ID=y .venv/bin/python -c "
from datetime import date
from pathlib import Path
from run import correr
from surf.alert import estado_vacio
from surf.fetch import obtener_horas
from surf.spots import cargar_spots
estado, msgs = correr(cargar_spots(Path('spots.yaml')), date.today(),
                      obtener_horas, print, estado_vacio())
print(f'--- ventanas observadas: {len(estado[\"observadas\"])}')
"
```
