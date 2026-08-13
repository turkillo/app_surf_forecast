# Sistema de Alertas de Swell — Plan de Implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Un sistema que corre solo todos los días, evalúa 13 spots de surf y manda un push a Telegram únicamente cuando hay una ventana de swell que justifica un viaje.

**Architecture:** Pipeline de cuatro etapas: `fetch` trae datos horarios de Open-Meteo, `score` aplica un gate duro por spot y puntúa lo que pasa, `alert` agrupa días en ventanas y aplica persistencia contra el estado del día anterior, `notify` manda a Telegram. `score.py` y `alert.py` son funciones puras sin I/O, lo que permite que el backtest histórico ejecute exactamente el mismo código que producción. Corre en GitHub Actions con `state.json` versionado en el repo.

**Tech Stack:** Python 3.10+, `requests`, `PyYAML`, `pytest`. Sin frameworks. Open-Meteo (sin API key), Telegram Bot API, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-08-13-sistema-alertas-swell-design.md`

## Global Constraints

- **Python ≥ 3.10.** El entorno local tiene 3.10.10. No usar features de 3.11+ (`datetime.UTC`, `tomllib`, `Self`). Para timezone UTC usar `timezone.utc`.
- **Dependencias permitidas: solo `requests`, `PyYAML`, `pytest`.** Nada más. Sin pandas, sin numpy, sin frameworks.
- **Costo cero es requisito.** Open-Meteo tier gratuito sin API key (uso no comercial), GitHub Actions tier gratuito. Ninguna decisión puede introducir un servicio pago.
- **`score.py` y `alert.py` no hacen I/O.** Nada de red, archivos, ni `datetime.now()` dentro de ellos. Las fechas entran por parámetro. Es lo que permite que el backtest valide el mismo código que corre en producción.
- **Los umbrales son por spot, nunca globales hardcodeados.** Todo umbral sale de `spots.yaml`. Un número mágico en `score.py` es un bug.
- **Todo el texto de cara al usuario va en español** (mensajes de Telegram, motivos de rechazo, logs).
- **Nunca escribir `state.json` en una corrida que falló.** Ante la duda, no escribir estado corrupto.
- **Unidades fijas:** altura en metros, período en segundos, viento en km/h, direcciones en grados 0-360 (dirección *desde* la que viene, convención meteorológica).

---

### Task 1: Scaffolding y geometría angular

**Files:**
- Create: `requirements.txt`
- Create: `.gitignore`
- Create: `surf/__init__.py`
- Create: `surf/geo.py`
- Create: `tests/__init__.py`
- Test: `tests/test_geo.py`

**Interfaces:**
- Consumes: nada (primera tarea)
- Produces:
  - `angular_diff(a: float, b: float) -> float` — menor diferencia entre dos rumbos, rango 0-180
  - `clasificar_viento(viento_desde: float, costa_mira: float) -> str` — devuelve `"offshore"`, `"cross"` u `"onshore"`
  - `en_ventana(direccion: float, ventana: tuple[float, float]) -> bool` — maneja wrap en 0/360
  - `rumbo_a_texto(grados: float) -> str` — devuelve una de las 16 rosas: `"N"`, `"NNE"`, ..., `"NNW"`

- [ ] **Step 1: Crear el entorno y los archivos de configuración**

```bash
cd /Users/martinturjanski/Documents/Personal/app_surf_forecast
python3 -m venv .venv
.venv/bin/pip install --quiet --upgrade pip
```

`requirements.txt`:
```
requests==2.32.3
PyYAML==6.0.2
pytest==8.3.3
```

`.gitignore`:
```
.venv/
__pycache__/
*.pyc
.pytest_cache/
.DS_Store
```

```bash
.venv/bin/pip install --quiet -r requirements.txt
mkdir -p surf tests
touch surf/__init__.py tests/__init__.py
```

- [ ] **Step 2: Escribir los tests que fallan**

`tests/test_geo.py`:
```python
import pytest
from surf.geo import angular_diff, clasificar_viento, en_ventana, rumbo_a_texto


def test_angular_diff_directo():
    assert angular_diff(10, 40) == 30


def test_angular_diff_cruza_el_cero():
    # 350 y 10 estan a 20 grados, no a 340
    assert angular_diff(350, 10) == 20


def test_angular_diff_es_simetrica():
    assert angular_diff(10, 350) == 20


def test_angular_diff_nunca_supera_180():
    assert angular_diff(0, 270) == 90


def test_offshore_sopla_desde_tierra():
    # Playa que mira al SE (140). El offshore viene del NW (320).
    assert clasificar_viento(320, 140) == "offshore"


def test_offshore_tolera_45_grados():
    # 290 esta a 30 grados de 320 -> sigue siendo offshore
    assert clasificar_viento(290, 140) == "offshore"


def test_cross_a_noventa_grados():
    # 230 esta a 90 grados de 320 -> cross
    assert clasificar_viento(230, 140) == "cross"


def test_onshore_viene_del_mar():
    # Playa mira al SE (140): el viento del SE es onshore
    assert clasificar_viento(140, 140) == "onshore"


def test_clasificar_viento_en_chile():
    # Buchupureo mira al WNW (290). Offshore viene del ESE (110).
    assert clasificar_viento(110, 290) == "offshore"
    assert clasificar_viento(290, 290) == "onshore"


def test_en_ventana_caso_simple():
    assert en_ventana(157, (110, 200)) is True
    assert en_ventana(90, (110, 200)) is False
    assert en_ventana(250, (110, 200)) is False


def test_en_ventana_incluye_los_bordes():
    assert en_ventana(110, (110, 200)) is True
    assert en_ventana(200, (110, 200)) is True


def test_en_ventana_cruza_el_cero():
    # Ventana del NW al NE pasando por el N
    assert en_ventana(350, (300, 60)) is True
    assert en_ventana(10, (300, 60)) is True
    assert en_ventana(180, (300, 60)) is False


def test_rumbo_a_texto():
    assert rumbo_a_texto(0) == "N"
    assert rumbo_a_texto(90) == "E"
    assert rumbo_a_texto(180) == "S"
    assert rumbo_a_texto(270) == "W"
    assert rumbo_a_texto(315) == "NW"
    assert rumbo_a_texto(157) == "SSE"


def test_rumbo_a_texto_envuelve_en_360():
    assert rumbo_a_texto(359) == "N"
```

- [ ] **Step 3: Correr los tests y verificar que fallan**

Run: `.venv/bin/pytest tests/test_geo.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'surf.geo'`

- [ ] **Step 4: Implementar `surf/geo.py`**

```python
"""Geometria angular para orientacion de costa y direcciones de swell y viento.

Convencion: todas las direcciones estan en grados 0-360 e indican el rumbo
DESDE el que viene el fenomeno (convencion meteorologica), salvo `costa_mira`
que indica hacia donde mira la playa.
"""

_ROSA = [
    "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
    "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW",
]


def angular_diff(a: float, b: float) -> float:
    """Menor diferencia angular entre dos rumbos. Siempre entre 0 y 180."""
    d = abs(a - b) % 360
    return 360 - d if d > 180 else d


def clasificar_viento(viento_desde: float, costa_mira: float) -> str:
    """Clasifica el viento relativo a la orientacion de la playa.

    El offshore sopla desde tierra hacia el mar, o sea desde el rumbo
    opuesto al que mira la playa.
    """
    offshore_desde = (costa_mira + 180) % 360
    rel = angular_diff(viento_desde, offshore_desde)
    if rel < 45:
        return "offshore"
    if rel <= 135:
        return "cross"
    return "onshore"


def en_ventana(direccion: float, ventana: tuple[float, float]) -> bool:
    """Indica si una direccion cae dentro de una ventana angular.

    Soporta ventanas que cruzan el 0 (por ejemplo (300, 60)).
    Los bordes se consideran incluidos.
    """
    desde, hasta = ventana[0] % 360, ventana[1] % 360
    d = direccion % 360
    if desde <= hasta:
        return desde <= d <= hasta
    return d >= desde or d <= hasta


def rumbo_a_texto(grados: float) -> str:
    """Convierte grados a una de las 16 direcciones de la rosa de los vientos."""
    i = int((grados % 360) / 22.5 + 0.5) % 16
    return _ROSA[i]
```

- [ ] **Step 5: Correr los tests y verificar que pasan**

Run: `.venv/bin/pytest tests/test_geo.py -v`
Expected: PASS, 15 tests

- [ ] **Step 6: Commit**

```bash
git add requirements.txt .gitignore surf/ tests/
git commit -m "feat: geometria angular para viento y direcciones de swell"
```

---

### Task 2: Esquema y carga de perfiles de spot

**Files:**
- Create: `surf/spots.py`
- Create: `spots.yaml` (solo con Chapadmalal, para tener con qué testear)
- Test: `tests/test_spots.py`

**Interfaces:**
- Consumes: `surf.geo.angular_diff`, `surf.geo.clasificar_viento`
- Produces:
  - `Swell` — dataclass frozen con `ventana: tuple[float, float]`, `ideal: float`, `min_altura: float`, `max_altura: float`, `rango_ideal: tuple[float, float]`, `min_periodo: float`
  - `Spot` — dataclass frozen con `id: str`, `nombre: str`, `pais: str`, `lat: float`, `lon: float`, `tipo: str`, `costa_mira: float`, `swell: Swell`, `viento_ideal: float`, `temporada: list[int]`, `url_surfforecast: str`, `fuentes: list[str]`, `confianza: str`
  - `cargar_spots(path: Path) -> list[Spot]` — lanza `ValueError` con mensaje explícito si un perfil está incompleto o es inconsistente

- [ ] **Step 1: Escribir los tests que fallan**

`tests/test_spots.py`:
```python
import pytest
from pathlib import Path
from surf.spots import cargar_spots, Spot, Swell

FIXTURE = """
- id: test_spot
  nombre: "Spot de Prueba"
  pais: AR
  lat: -38.15
  lon: -57.68
  tipo: point_break
  costa_mira: 140
  swell:
    ventana: [110, 200]
    ideal: 157
    min_altura: 1.0
    max_altura: 3.5
    rango_ideal: [1.5, 2.5]
    min_periodo: 9
  viento_ideal: 315
  temporada: [3, 4, 5, 6, 7, 8]
  url_surfforecast: "https://es.surf-forecast.com/breaks/Chapadmalal"
  fuentes: [surf-forecast]
  confianza: alta
"""


def _escribir(tmp_path, contenido):
    p = tmp_path / "spots.yaml"
    p.write_text(contenido)
    return p


def test_carga_un_perfil_completo(tmp_path):
    spots = cargar_spots(_escribir(tmp_path, FIXTURE))
    assert len(spots) == 1
    s = spots[0]
    assert s.id == "test_spot"
    assert s.costa_mira == 140
    assert s.swell.min_periodo == 9
    assert s.swell.rango_ideal == (1.5, 2.5)


def test_los_dataclasses_son_inmutables(tmp_path):
    s = cargar_spots(_escribir(tmp_path, FIXTURE))[0]
    with pytest.raises(Exception):
        s.costa_mira = 200


def test_rechaza_campo_faltante(tmp_path):
    roto = FIXTURE.replace("  viento_ideal: 315\n", "")
    with pytest.raises(ValueError, match="viento_ideal"):
        cargar_spots(_escribir(tmp_path, roto))


def test_rechaza_max_altura_menor_que_min(tmp_path):
    roto = FIXTURE.replace("max_altura: 3.5", "max_altura: 0.5")
    with pytest.raises(ValueError, match="max_altura"):
        cargar_spots(_escribir(tmp_path, roto))


def test_rechaza_rango_ideal_fuera_de_los_limites(tmp_path):
    roto = FIXTURE.replace("rango_ideal: [1.5, 2.5]", "rango_ideal: [0.2, 2.5]")
    with pytest.raises(ValueError, match="rango_ideal"):
        cargar_spots(_escribir(tmp_path, roto))


def test_rechaza_ideal_fuera_de_la_ventana(tmp_path):
    roto = FIXTURE.replace("ideal: 157", "ideal: 20")
    with pytest.raises(ValueError, match="ideal"):
        cargar_spots(_escribir(tmp_path, roto))


def test_rechaza_confianza_invalida(tmp_path):
    roto = FIXTURE.replace("confianza: alta", "confianza: buenisima")
    with pytest.raises(ValueError, match="confianza"):
        cargar_spots(_escribir(tmp_path, roto))


def test_rechaza_costa_mira_incoherente_con_viento_ideal(tmp_path):
    # costa_mira 140 implica offshore desde 320. Un viento_ideal de 90
    # esta a mas de 30 grados: es un error de investigacion.
    roto = FIXTURE.replace("viento_ideal: 315", "viento_ideal: 90")
    with pytest.raises(ValueError, match="costa_mira"):
        cargar_spots(_escribir(tmp_path, roto))


def test_rechaza_ids_duplicados(tmp_path):
    with pytest.raises(ValueError, match="duplicado"):
        cargar_spots(_escribir(tmp_path, FIXTURE + FIXTURE))
```

- [ ] **Step 2: Correr los tests y verificar que fallan**

Run: `.venv/bin/pytest tests/test_spots.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'surf.spots'`

- [ ] **Step 3: Implementar `surf/spots.py`**

```python
"""Carga y validacion de los perfiles de spot.

Cada spot lleva sus propios umbrales. Un umbral hardcodeado en el codigo
de scoring seria un bug: todos los numeros salen de aca.
"""
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from surf.geo import angular_diff, en_ventana

_CONFIANZAS = {"alta", "media", "baja"}
_TIPOS = {"point_break", "beach_break", "reef"}
_CAMPOS_SPOT = [
    "id", "nombre", "pais", "lat", "lon", "tipo", "costa_mira",
    "swell", "viento_ideal", "temporada", "url_surfforecast",
    "fuentes", "confianza",
]
_CAMPOS_SWELL = [
    "ventana", "ideal", "min_altura", "max_altura",
    "rango_ideal", "min_periodo",
]

# Tolerancia entre la orientacion geometrica de la costa y el viento ideal
# documentado. Por encima de esto hay un error de investigacion.
TOLERANCIA_COSTA_GRADOS = 30


@dataclass(frozen=True)
class Swell:
    ventana: tuple[float, float]
    ideal: float
    min_altura: float
    max_altura: float
    rango_ideal: tuple[float, float]
    min_periodo: float


@dataclass(frozen=True)
class Spot:
    id: str
    nombre: str
    pais: str
    lat: float
    lon: float
    tipo: str
    costa_mira: float
    swell: Swell
    viento_ideal: float
    temporada: list[int]
    url_surfforecast: str
    fuentes: list[str]
    confianza: str


def _validar(crudo: dict[str, Any]) -> None:
    ident = crudo.get("id", "<sin id>")

    for campo in _CAMPOS_SPOT:
        if campo not in crudo:
            raise ValueError(f"[{ident}] falta el campo obligatorio '{campo}'")

    sw = crudo["swell"]
    for campo in _CAMPOS_SWELL:
        if campo not in sw:
            raise ValueError(f"[{ident}] falta el campo obligatorio 'swell.{campo}'")

    if crudo["tipo"] not in _TIPOS:
        raise ValueError(f"[{ident}] tipo invalido '{crudo['tipo']}', debe ser uno de {_TIPOS}")

    if crudo["confianza"] not in _CONFIANZAS:
        raise ValueError(
            f"[{ident}] confianza invalida '{crudo['confianza']}', debe ser una de {_CONFIANZAS}"
        )

    if sw["max_altura"] <= sw["min_altura"]:
        raise ValueError(
            f"[{ident}] max_altura ({sw['max_altura']}) debe ser mayor "
            f"que min_altura ({sw['min_altura']})"
        )

    ri_min, ri_max = sw["rango_ideal"]
    if ri_min < sw["min_altura"] or ri_max > sw["max_altura"] or ri_min > ri_max:
        raise ValueError(
            f"[{ident}] rango_ideal {sw['rango_ideal']} debe estar contenido "
            f"entre min_altura ({sw['min_altura']}) y max_altura ({sw['max_altura']})"
        )

    if not en_ventana(sw["ideal"], tuple(sw["ventana"])):
        raise ValueError(
            f"[{ident}] la direccion ideal ({sw['ideal']}) cae fuera de "
            f"la ventana {sw['ventana']}"
        )

    if sw["min_periodo"] <= 0:
        raise ValueError(f"[{ident}] min_periodo debe ser positivo")

    # El offshore sopla desde el rumbo opuesto al que mira la playa. Si el
    # viento ideal documentado no coincide, uno de los dos esta mal.
    offshore_esperado = (crudo["costa_mira"] + 180) % 360
    desvio = angular_diff(crudo["viento_ideal"], offshore_esperado)
    if desvio > TOLERANCIA_COSTA_GRADOS:
        raise ValueError(
            f"[{ident}] costa_mira ({crudo['costa_mira']}) implica offshore desde "
            f"{offshore_esperado:.0f}, pero viento_ideal es {crudo['viento_ideal']} "
            f"({desvio:.0f} grados de desvio, maximo {TOLERANCIA_COSTA_GRADOS}). "
            f"Revisar la investigacion de este spot."
        )

    for mes in crudo["temporada"]:
        if not 1 <= mes <= 12:
            raise ValueError(f"[{ident}] mes invalido en temporada: {mes}")


def cargar_spots(path: Path) -> list[Spot]:
    """Carga spots.yaml y valida cada perfil.

    Lanza ValueError con un mensaje accionable ante el primer problema.
    """
    crudos = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not crudos:
        raise ValueError(f"{path} esta vacio")

    vistos: set[str] = set()
    spots: list[Spot] = []

    for crudo in crudos:
        _validar(crudo)
        if crudo["id"] in vistos:
            raise ValueError(f"id duplicado: '{crudo['id']}'")
        vistos.add(crudo["id"])

        sw = crudo["swell"]
        spots.append(
            Spot(
                id=crudo["id"],
                nombre=crudo["nombre"],
                pais=crudo["pais"],
                lat=float(crudo["lat"]),
                lon=float(crudo["lon"]),
                tipo=crudo["tipo"],
                costa_mira=float(crudo["costa_mira"]),
                swell=Swell(
                    ventana=(float(sw["ventana"][0]), float(sw["ventana"][1])),
                    ideal=float(sw["ideal"]),
                    min_altura=float(sw["min_altura"]),
                    max_altura=float(sw["max_altura"]),
                    rango_ideal=(float(sw["rango_ideal"][0]), float(sw["rango_ideal"][1])),
                    min_periodo=float(sw["min_periodo"]),
                ),
                viento_ideal=float(crudo["viento_ideal"]),
                temporada=list(crudo["temporada"]),
                url_surfforecast=crudo["url_surfforecast"],
                fuentes=list(crudo["fuentes"]),
                confianza=crudo["confianza"],
            )
        )

    return spots
```

- [ ] **Step 4: Crear `spots.yaml` con el primer perfil**

```yaml
# Perfiles de spot. Cada uno lleva sus propios umbrales.
# Fuentes: surf-forecast.com, wannasurf.com, geometria de costa.
# El campo `confianza` indica que tan solido es el perfil: cuando es `baja`,
# el backtest historico tiene prioridad sobre el dato documentado.

- id: chapadmalal
  nombre: "Chapadmalal, Argentina"
  pais: AR
  lat: -38.15
  lon: -57.68
  tipo: point_break
  costa_mira: 140
  swell:
    ventana: [110, 200]
    ideal: 157
    min_altura: 1.0
    max_altura: 3.5
    rango_ideal: [1.5, 2.5]
    min_periodo: 9
  viento_ideal: 315
  temporada: [3, 4, 5, 6, 7, 8]
  url_surfforecast: "https://es.surf-forecast.com/breaks/Chapadmalal/forecasts/latest/six_day"
  fuentes: [surf-forecast, wannasurf]
  confianza: alta
```

- [ ] **Step 5: Correr los tests y verificar que pasan**

Run: `.venv/bin/pytest tests/ -v`
Expected: PASS, 24 tests (15 de geo + 9 de spots)

- [ ] **Step 6: Verificar que el spots.yaml real carga**

Run: `.venv/bin/python -c "from surf.spots import cargar_spots; from pathlib import Path; print([s.id for s in cargar_spots(Path('spots.yaml'))])"`
Expected: `['chapadmalal']`

- [ ] **Step 7: Commit**

```bash
git add surf/spots.py spots.yaml tests/test_spots.py
git commit -m "feat: esquema y validacion de perfiles de spot"
```

---

### Task 3: Investigación de los 13 perfiles

Esta es la tarea que más determina la calidad del detector. No es código: es investigación con criterio de aceptación verificable.

**Files:**
- Modify: `spots.yaml` (de 1 perfil a 13)
- Create: `docs/investigacion-spots.md`
- Test: `tests/test_spots_reales.py`

**Interfaces:**
- Consumes: `surf.spots.cargar_spots`
- Produces: `spots.yaml` con 13 perfiles válidos. Los `id` son: `la_barra`, `chapadmalal`, `praia_do_rosa`, `buchupureo`, `asia`, `huanchaco`, `santa_teresa`, `saquarema`, `punta_de_lobos`, `chicama`, `lobitos`, `punta_del_diablo`, `joaquina`

- [ ] **Step 1: Escribir el test de aceptación que falla**

`tests/test_spots_reales.py`:
```python
"""Verifica que el spots.yaml de produccion este completo y sea coherente."""
from pathlib import Path

from surf.spots import cargar_spots

IDS_ESPERADOS = {
    "la_barra", "chapadmalal", "praia_do_rosa", "buchupureo", "asia",
    "huanchaco", "santa_teresa", "saquarema", "punta_de_lobos",
    "chicama", "lobitos", "punta_del_diablo", "joaquina",
}


def _spots():
    return cargar_spots(Path("spots.yaml"))


def test_estan_los_trece_spots():
    assert {s.id for s in _spots()} == IDS_ESPERADOS


def test_todos_tienen_al_menos_una_fuente_citada():
    for s in _spots():
        assert s.fuentes, f"{s.id} no tiene fuentes citadas"


def test_todos_tienen_url_de_surfforecast():
    for s in _spots():
        assert s.url_surfforecast.startswith("http"), f"{s.id} sin url valida"


def test_las_coordenadas_son_plausibles():
    for s in _spots():
        assert -60 < s.lat < 15, f"{s.id} latitud fuera de rango"
        assert -90 < s.lon < -30, f"{s.id} longitud fuera de rango"


def test_hay_cobertura_de_los_cinco_paises():
    paises = {s.pais for s in _spots()}
    assert {"AR", "UY", "BR", "CL", "PE"}.issubset(paises)


def test_los_perfiles_de_baja_confianza_estan_identificados():
    # No es un fallo tener baja confianza, pero tiene que estar declarado.
    for s in _spots():
        assert s.confianza in {"alta", "media", "baja"}
```

- [ ] **Step 2: Correr el test y verificar que falla**

Run: `.venv/bin/pytest tests/test_spots_reales.py -v`
Expected: FAIL en `test_estan_los_trece_spots` (solo existe `chapadmalal`)

- [ ] **Step 3: Investigar cada spot con las tres fuentes**

Para **cada uno** de los 13 spots, completar esta grilla. Consultar en este orden:

**Fuente 1 — surf-forecast.com.** Ir a `https://es.surf-forecast.com/breaks/<Break>` (sin el sufijo `/forecasts/...`). La página incluye una descripción del pico con: dirección ideal de swell, dirección ideal de viento, tipo de pico, temporada favorita, y riesgos. Extraer los cuatro primeros.

**Fuente 2 — wannasurf.com.** Buscar `wannasurf <spot>`. La ficha da los campos estructurados `Swell direction`, `Swell size` (en la forma *"Starts working at X, holds up to Y"*), `Wind direction`, `Tide`, `Bottom`, `Wave type`, `Consistency`. De acá salen `min_altura` y `max_altura` — es la única fuente que documenta el techo.

**Fuente 3 — geometría de la costa.** Determinar `costa_mira` a partir de la orientación real del litoral en las coordenadas del spot (rumbo hacia el mar abierto, perpendicular a la línea de costa). No estimarlo a ojo desde el nombre del país.

**Reglas de conversión a los campos del YAML:**

| Campo | Cómo se deriva |
|---|---|
| `costa_mira` | Geometría de la costa (fuente 3) |
| `swell.ideal` | Dirección ideal de surf-forecast, convertida a grados (`SSE` → 157) |
| `swell.ventana` | `[ideal - 45, ideal + 45]`, ajustado si Wannasurf documenta un rango más ancho o si hay obstrucción (cabo, isla). Nunca más ancho que `costa_mira ± 90` |
| `swell.min_altura` | `Starts working at` de Wannasurf. Piso absoluto 1.0 m (requisito del usuario) — si Wannasurf dice menos, igual va 1.0 |
| `swell.max_altura` | `holds up to` de Wannasurf. Si dice `4m+`, usar 4.0 |
| `swell.rango_ideal` | Tercio central entre `min_altura` y `max_altura`, ajustado por el tipo de pico |
| `swell.min_periodo` | 9 s para `beach_break`, 10 s para `point_break` y `reef` (los points necesitan más período para envolver) |
| `viento_ideal` | Dirección ideal de viento de surf-forecast, en grados |
| `temporada` | Meses de la temporada favorita de surf-forecast |
| `confianza` | `alta` si las tres fuentes coinciden; `media` si falta Wannasurf o hay discrepancia menor; `baja` si hubo que estimar `max_altura` |

**Verificación cruzada obligatoria:** el validador ya rechaza cualquier perfil donde `costa_mira` y `viento_ideal` difieran más de 30°. Si salta ese error, **no ajustar los números para que pasen** — significa que una de las dos fuentes está mal leída y hay que volver a mirarla.

Datos ya investigados en la fase de diseño (2026-08-13), para reutilizar:

- **Chapadmalal** (surf-forecast): swell ideal *South southeast*, viento ideal *Northwest*, tipo *exposed point break*, temporada *otoño e invierno*, riesgo *rocas sumergidas*.
- **Chicama** (Wannasurf): swell *SouthWest, South*; tamaño *starts working at <1m, holds up to 4m+*; viento *East, NorthEast*; marea *todas, mejor subiendo*; fondo *arena con roca*; tipo *point-break*; consistencia *muy alta, 150 días/año*.

Coordenadas verificadas contra Open-Meteo el 2026-08-13 (usar tal cual):

| id | Spot | País | Lat | Lon |
|---|---|---|---|---|
| `la_barra` | La Barra, Punta del Este | UY | -34.92 | -54.85 |
| `chapadmalal` | Chapadmalal | AR | -38.15 | -57.68 |
| `praia_do_rosa` | Praia do Rosa | BR | -28.13 | -48.63 |
| `buchupureo` | Buchupureo | CL | -36.08 | -72.79 |
| `asia` | Asia (Mar Azul) | PE | -12.78 | -76.63 |
| `huanchaco` | Punta Huanchaco | PE | -8.08 | -79.12 |
| `santa_teresa` | Playa Santa Teresa | CR | 9.65 | -85.17 |

Coordenadas a determinar durante la investigación (verificar contra Open-Meteo antes de fijarlas): `saquarema`, `punta_de_lobos`, `chicama`, `lobitos`, `punta_del_diablo`, `joaquina`.

- [ ] **Step 4: Escribir `docs/investigacion-spots.md`**

Un bloque por spot con lo crudo de cada fuente, antes de convertirlo a YAML. Formato:

```markdown
## chapadmalal — Chapadmalal, Argentina

**surf-forecast** (consultado 2026-08-13)
- Swell ideal: South southeast
- Viento ideal: Northwest
- Tipo: exposed point break
- Temporada: otoño e invierno
- Notas: rocas sumergidas, a veces con gente

**Wannasurf** (consultado YYYY-MM-DD)
- Swell direction: ...
- Swell size: ...
- ...

**Geometría de costa**
- costa_mira derivado: 140 (litoral orientado NE-SW, mar abierto al SE)
- Offshore esperado: 320. Viento ideal documentado: 315. Desvío: 5 ✓

**Confianza:** alta
```

Es el registro de por qué cada número es el que es. Sin esto, en seis meses nadie puede auditar el detector.

- [ ] **Step 5: Completar `spots.yaml` con los 13 perfiles**

Usar el formato exacto del perfil de `chapadmalal` ya presente. Un bloque por spot, en el orden de la tabla.

- [ ] **Step 6: Correr los tests y verificar que pasan**

Run: `.venv/bin/pytest tests/ -v`
Expected: PASS, todos. Si `cargar_spots` lanza `ValueError`, el mensaje indica qué perfil y qué campo — corregir la investigación, no el validador.

- [ ] **Step 7: Verificar que Open-Meteo responde en los 6 spots nuevos**

```bash
.venv/bin/python - <<'EOF'
from pathlib import Path
import requests
from surf.spots import cargar_spots

for s in cargar_spots(Path("spots.yaml")):
    r = requests.get(
        "https://marine-api.open-meteo.com/v1/marine",
        params={"latitude": s.lat, "longitude": s.lon,
                "hourly": "swell_wave_height,swell_wave_period", "forecast_days": 1},
        timeout=30,
    ).json()
    h = r.get("hourly", {}).get("swell_wave_height")
    ok = h is not None and h[12] is not None
    print(f"{'OK ' if ok else 'FALLA'} {s.id}: {h[12] if ok else r.get('reason')}")
EOF
```
Expected: `OK` en los 13. Si alguno falla o devuelve `null`, correr la coordenada mar adentro hasta que el modelo tenga dato y anotarlo en `docs/investigacion-spots.md`.

- [ ] **Step 8: Commit**

```bash
git add spots.yaml docs/investigacion-spots.md tests/test_spots_reales.py
git commit -m "feat: investigacion y perfiles de los 13 spots"
```

---

### Task 4: Gate horario

**Files:**
- Create: `surf/score.py`
- Test: `tests/test_score_gate.py`

**Interfaces:**
- Consumes: `surf.spots.Spot`, `surf.geo.clasificar_viento`, `surf.geo.en_ventana`
- Produces:
  - `Hora` — dataclass frozen: `t: datetime`, `swell_altura: float`, `swell_periodo: float`, `swell_direccion: float`, `viento_kmh: float`, `viento_direccion: float`, `es_de_dia: bool`
  - `HoraEvaluada` — dataclass frozen: `hora: Hora`, `pasa: bool`, `motivo_rechazo: str | None`, `score: float`, `clase_viento: str`
  - `evaluar_hora(hora: Hora, spot: Spot) -> HoraEvaluada`
  - Constantes de umbral de viento a nivel de modulo: `VIENTO_GLASSY_KMH`, `OFFSHORE_IDEAL_KMH`, `OFFSHORE_MAX_KMH`, `CROSS_IDEAL_KMH`, `CROSS_MAX_KMH`, `ONSHORE_MAX_KMH`. Las `*_IDEAL_*` las consume `factor_viento` en la Task 5.

- [ ] **Step 1: Escribir los tests que fallan**

`tests/test_score_gate.py`:
```python
from datetime import datetime

import pytest

from surf.score import Hora, evaluar_hora
from surf.spots import Spot, Swell

SPOT = Spot(
    id="test", nombre="Test", pais="AR", lat=-38.15, lon=-57.68,
    tipo="point_break", costa_mira=140,
    swell=Swell(ventana=(110, 200), ideal=157, min_altura=1.0,
                max_altura=3.5, rango_ideal=(1.5, 2.5), min_periodo=9),
    viento_ideal=315, temporada=[3, 4, 5, 6, 7, 8],
    url_surfforecast="http://x", fuentes=["test"], confianza="alta",
)


def hora(altura=2.0, periodo=12.0, direccion=157.0,
         viento_kmh=5.0, viento_dir=320.0, de_dia=True):
    """Hora base con condiciones que pasan el gate. Cada test rompe una sola cosa."""
    return Hora(
        t=datetime(2026, 8, 21, 9, 0),
        swell_altura=altura, swell_periodo=periodo, swell_direccion=direccion,
        viento_kmh=viento_kmh, viento_direccion=viento_dir, es_de_dia=de_dia,
    )


def test_condiciones_perfectas_pasan():
    r = evaluar_hora(hora(), SPOT)
    assert r.pasa is True
    assert r.motivo_rechazo is None


def test_altura_por_debajo_del_minimo_no_pasa():
    r = evaluar_hora(hora(altura=0.7), SPOT)
    assert r.pasa is False
    assert "altura" in r.motivo_rechazo


def test_altura_por_encima_del_maximo_no_pasa():
    # El spot cierra arriba de 3.5m: un swell de 4.5m no es una alerta
    r = evaluar_hora(hora(altura=4.5), SPOT)
    assert r.pasa is False
    assert "cierra" in r.motivo_rechazo


def test_periodo_corto_no_pasa():
    r = evaluar_hora(hora(periodo=7.2), SPOT)
    assert r.pasa is False
    assert "periodo" in r.motivo_rechazo


def test_direccion_fuera_de_la_ventana_no_pasa():
    # Swell del NE en un spot que solo recibe del S/SE
    r = evaluar_hora(hora(direccion=45), SPOT)
    assert r.pasa is False
    assert "direccion" in r.motivo_rechazo


def test_swell_perfecto_con_onshore_no_pasa():
    # 15 km/h desde el SE (140) es onshore directo
    r = evaluar_hora(hora(viento_kmh=15, viento_dir=140), SPOT)
    assert r.pasa is False
    assert "onshore" in r.motivo_rechazo


def test_offshore_muy_fuerte_no_pasa():
    r = evaluar_hora(hora(viento_kmh=40, viento_dir=320), SPOT)
    assert r.pasa is False
    assert "offshore" in r.motivo_rechazo


def test_cross_muy_fuerte_no_pasa():
    r = evaluar_hora(hora(viento_kmh=25, viento_dir=230), SPOT)
    assert r.pasa is False
    assert "cross" in r.motivo_rechazo


def test_onshore_muy_suave_si_pasa():
    # Hasta 8 km/h el onshore es tolerable
    r = evaluar_hora(hora(viento_kmh=6, viento_dir=140), SPOT)
    assert r.pasa is True
    assert r.clase_viento == "onshore"


def test_glassy_pasa_en_cualquier_direccion():
    r = evaluar_hora(hora(viento_kmh=4, viento_dir=140), SPOT)
    assert r.pasa is True


def test_de_noche_no_pasa():
    # Condiciones perfectas a las 3 AM no son una sesion
    r = evaluar_hora(hora(de_dia=False), SPOT)
    assert r.pasa is False
    assert "luz" in r.motivo_rechazo


def test_el_gate_no_compensa_entre_criterios():
    # Swell excelente pero onshore fuerte: sigue sin pasar.
    # Este test existe para que nadie reintroduzca un promedio ponderado.
    r = evaluar_hora(hora(altura=2.5, periodo=16, viento_kmh=30, viento_dir=140), SPOT)
    assert r.pasa is False
    assert r.score == 0.0


def test_la_hora_rechazada_tiene_score_cero():
    assert evaluar_hora(hora(periodo=5), SPOT).score == 0.0
```

- [ ] **Step 2: Correr los tests y verificar que fallan**

Run: `.venv/bin/pytest tests/test_score_gate.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'surf.score'`

- [ ] **Step 3: Implementar el gate en `surf/score.py`**

```python
"""Gate y scoring de condiciones de surf.

Diseno deliberado: gate duro primero, score despues. El gate son condiciones
binarias que TODAS deben cumplirse; no hay compensacion entre criterios. Un
promedio ponderado sobre el gate permitiria que 2.5m con onshore de 30 km/h
saque 70 puntos y dispare una alerta por un dia de espuma.

Este modulo es puro: no hace red, ni archivos, ni consulta la hora actual.
Es lo que permite que el backtest corra exactamente el mismo codigo que
produccion.
"""
from dataclasses import dataclass
from datetime import datetime

from surf.geo import clasificar_viento, en_ventana
from surf.spots import Spot

VIENTO_GLASSY_KMH = 6.0
OFFSHORE_IDEAL_KMH = 20.0
OFFSHORE_MAX_KMH = 35.0
CROSS_IDEAL_KMH = 12.0
CROSS_MAX_KMH = 20.0
ONSHORE_MAX_KMH = 8.0


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


def _gate_viento(hora: Hora, clase: str) -> str | None:
    """Devuelve el motivo de rechazo, o None si el viento pasa."""
    if hora.viento_kmh <= VIENTO_GLASSY_KMH:
        return None
    if clase == "offshore":
        if hora.viento_kmh > OFFSHORE_MAX_KMH:
            return f"offshore muy fuerte ({hora.viento_kmh:.0f} km/h, maximo {OFFSHORE_MAX_KMH:.0f})"
        return None
    if clase == "cross":
        if hora.viento_kmh > CROSS_MAX_KMH:
            return f"cross muy fuerte ({hora.viento_kmh:.0f} km/h, maximo {CROSS_MAX_KMH:.0f})"
        return None
    if hora.viento_kmh > ONSHORE_MAX_KMH:
        return f"viento onshore ({hora.viento_kmh:.0f} km/h, maximo {ONSHORE_MAX_KMH:.0f})"
    return None


def _gate(hora: Hora, spot: Spot, clase: str) -> str | None:
    """Aplica las seis condiciones. Devuelve el primer motivo de rechazo."""
    sw = spot.swell

    if not hora.es_de_dia:
        return "fuera de horas de luz"
    if hora.swell_altura < sw.min_altura:
        return f"altura insuficiente ({hora.swell_altura:.1f}m, minimo {sw.min_altura:.1f}m)"
    if hora.swell_altura > sw.max_altura:
        return f"el spot cierra con este tamano ({hora.swell_altura:.1f}m, maximo {sw.max_altura:.1f}m)"
    if hora.swell_periodo < sw.min_periodo:
        return f"periodo corto ({hora.swell_periodo:.1f}s, minimo {sw.min_periodo:.1f}s)"
    if not en_ventana(hora.swell_direccion, sw.ventana):
        return (
            f"direccion fuera de la ventana del spot "
            f"({hora.swell_direccion:.0f}, ventana {sw.ventana[0]:.0f}-{sw.ventana[1]:.0f})"
        )
    return _gate_viento(hora, clase)


def evaluar_hora(hora: Hora, spot: Spot) -> HoraEvaluada:
    """Evalua una hora contra el perfil del spot."""
    clase = clasificar_viento(hora.viento_direccion, spot.costa_mira)
    motivo = _gate(hora, spot, clase)
    if motivo is not None:
        return HoraEvaluada(hora=hora, pasa=False, motivo_rechazo=motivo,
                            score=0.0, clase_viento=clase)
    return HoraEvaluada(hora=hora, pasa=True, motivo_rechazo=None,
                        score=0.0, clase_viento=clase)
```

Nota: `score` queda en `0.0` en esta tarea. La Task 5 lo calcula.

- [ ] **Step 4: Correr los tests y verificar que pasan**

Run: `.venv/bin/pytest tests/test_score_gate.py -v`
Expected: PASS, 13 tests

- [ ] **Step 5: Commit**

```bash
git add surf/score.py tests/test_score_gate.py
git commit -m "feat: gate horario con seis condiciones duras"
```

---

### Task 5: Score 0-100

**Files:**
- Modify: `surf/score.py`
- Test: `tests/test_score_puntaje.py`

**Interfaces:**
- Consumes: `surf.score.Hora`, `surf.score.HoraEvaluada`, `surf.spots.Spot`
- Produces:
  - `factor_altura(altura: float, spot: Spot) -> float` — 0.4 a 1.0
  - `factor_periodo(periodo: float, spot: Spot) -> float` — 0.0 a 1.0
  - `factor_direccion(direccion: float, spot: Spot) -> float` — 0.5 a 1.0
  - `factor_viento(viento_kmh: float, clase: str) -> float` — 0.3 a 1.0
  - `evaluar_hora` ahora devuelve `score` real en `HoraEvaluada`

- [ ] **Step 1: Escribir los tests que fallan**

`tests/test_score_puntaje.py`:
```python
import pytest

from surf.score import (factor_altura, factor_direccion, factor_periodo,
                        factor_viento, evaluar_hora)
from tests.test_score_gate import SPOT, hora


def test_altura_en_el_rango_ideal_da_uno():
    # rango_ideal = (1.5, 2.5)
    assert factor_altura(2.0, SPOT) == 1.0
    assert factor_altura(1.5, SPOT) == 1.0
    assert factor_altura(2.5, SPOT) == 1.0


def test_altura_en_el_minimo_da_el_piso():
    # min_altura = 1.0
    assert factor_altura(1.0, SPOT) == pytest.approx(0.4)


def test_altura_sube_lineal_hasta_el_rango_ideal():
    # Punto medio entre 1.0 y 1.5 -> punto medio entre 0.4 y 1.0
    assert factor_altura(1.25, SPOT) == pytest.approx(0.7)


def test_altura_baja_lineal_pasado_el_rango_ideal():
    # Punto medio entre 2.5 y 3.5 -> punto medio entre 1.0 y 0.4
    assert factor_altura(3.0, SPOT) == pytest.approx(0.7)


def test_periodo_en_el_minimo_da_cero():
    # min_periodo = 9
    assert factor_periodo(9.0, SPOT) == pytest.approx(0.0)


def test_periodo_de_dieciseis_da_uno():
    assert factor_periodo(16.0, SPOT) == pytest.approx(1.0)


def test_periodo_por_encima_de_dieciseis_topea_en_uno():
    assert factor_periodo(20.0, SPOT) == pytest.approx(1.0)


def test_periodo_intermedio_es_lineal():
    # Punto medio entre 9 y 16 es 12.5
    assert factor_periodo(12.5, SPOT) == pytest.approx(0.5)


def test_direccion_ideal_da_uno():
    assert factor_direccion(157, SPOT) == pytest.approx(1.0)


def test_direccion_en_el_borde_de_la_ventana_da_medio():
    # ventana (110, 200), ideal 157
    assert factor_direccion(110, SPOT) == pytest.approx(0.5)
    assert factor_direccion(200, SPOT) == pytest.approx(0.5)


def test_viento_glassy_da_uno():
    assert factor_viento(4.0, "onshore") == 1.0


def test_offshore_suave_da_uno():
    assert factor_viento(15.0, "offshore") == 1.0


def test_offshore_fuerte_degrada():
    # 20 -> 1.0, 35 -> 0.4; el punto medio 27.5 -> 0.7
    assert factor_viento(27.5, "offshore") == pytest.approx(0.7)


def test_cross_suave_da_cero_ochenta_y_cinco():
    assert factor_viento(10.0, "cross") == pytest.approx(0.85)


def test_onshore_tolerable_da_medio():
    assert factor_viento(7.0, "onshore") == pytest.approx(0.5)


def test_score_de_condiciones_perfectas_es_alto():
    r = evaluar_hora(hora(altura=2.0, periodo=16, direccion=157,
                          viento_kmh=4, viento_dir=320), SPOT)
    assert r.pasa is True
    assert r.score == pytest.approx(100.0)


def test_score_de_condiciones_apenas_suficientes_es_bajo():
    r = evaluar_hora(hora(altura=1.0, periodo=9.0, direccion=110,
                          viento_kmh=7, viento_dir=140), SPOT)
    assert r.pasa is True
    # 0.35*0.4 + 0.30*0.0 + 0.15*0.5 + 0.20*0.5 = 0.315
    assert r.score == pytest.approx(31.5)


def test_los_pesos_suman_uno():
    from surf.score import PESOS
    assert sum(PESOS.values()) == pytest.approx(1.0)
```

- [ ] **Step 2: Correr los tests y verificar que fallan**

Run: `.venv/bin/pytest tests/test_score_puntaje.py -v`
Expected: FAIL con `ImportError: cannot import name 'factor_altura'`

- [ ] **Step 3: Implementar los factores en `surf/score.py`**

Agregar debajo de las constantes de viento:

```python
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


def _interpolar(x: float, x0: float, x1: float, y0: float, y1: float) -> float:
    """Interpolacion lineal de x en [x0,x1] hacia [y0,y1]."""
    if x1 == x0:
        return y1
    t = (x - x0) / (x1 - x0)
    return y0 + t * (y1 - y0)
```

Y las cuatro funciones de factor:

```python
def factor_altura(altura: float, spot: Spot) -> float:
    """1.0 dentro del rango ideal, cae linealmente hacia los extremos."""
    sw = spot.swell
    ideal_min, ideal_max = sw.rango_ideal
    if ideal_min <= altura <= ideal_max:
        return 1.0
    if altura < ideal_min:
        return _interpolar(altura, sw.min_altura, ideal_min, PISO_FACTOR_ALTURA, 1.0)
    return _interpolar(altura, ideal_max, sw.max_altura, 1.0, PISO_FACTOR_ALTURA)


def factor_periodo(periodo: float, spot: Spot) -> float:
    """0.0 en el minimo del spot, 1.0 a los 16 segundos, con tope."""
    f = _interpolar(periodo, spot.swell.min_periodo, PERIODO_TOPE_S, 0.0, 1.0)
    return min(1.0, max(0.0, f))


def factor_direccion(direccion: float, spot: Spot) -> float:
    """1.0 en la direccion ideal, 0.5 en los bordes de la ventana."""
    sw = spot.swell
    desvio = angular_diff(direccion, sw.ideal)
    borde = max(angular_diff(sw.ventana[0], sw.ideal),
                angular_diff(sw.ventana[1], sw.ideal))
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
        return _interpolar(viento_kmh, OFFSHORE_IDEAL_KMH, OFFSHORE_MAX_KMH,
                           1.0, PISO_FACTOR_OFFSHORE)
    if clase == "cross":
        if viento_kmh <= CROSS_IDEAL_KMH:
            return FACTOR_CROSS_IDEAL
        return _interpolar(viento_kmh, CROSS_IDEAL_KMH, CROSS_MAX_KMH,
                           FACTOR_CROSS_IDEAL, PISO_FACTOR_CROSS)
    return FACTOR_ONSHORE
```

Reemplazar el `return` final de `evaluar_hora` por:

```python
    score = 100.0 * (
        PESOS["altura"] * factor_altura(hora.swell_altura, spot)
        + PESOS["periodo"] * factor_periodo(hora.swell_periodo, spot)
        + PESOS["direccion"] * factor_direccion(hora.swell_direccion, spot)
        + PESOS["viento"] * factor_viento(hora.viento_kmh, clase)
    )
    return HoraEvaluada(hora=hora, pasa=True, motivo_rechazo=None,
                        score=score, clase_viento=clase)
```

Cambiar el import de geo en el tope del archivo para incluir `angular_diff`:

```python
from surf.geo import angular_diff, clasificar_viento, en_ventana
```

- [ ] **Step 4: Correr todos los tests y verificar que pasan**

Run: `.venv/bin/pytest tests/ -v`
Expected: PASS. Las horas rechazadas siguen con `score == 0.0`.

- [ ] **Step 5: Commit**

```bash
git add surf/score.py tests/test_score_puntaje.py
git commit -m "feat: score 0-100 sobre las horas que pasan el gate"
```

---

### Task 6: Agregación de horas a días

**Files:**
- Modify: `surf/score.py`
- Test: `tests/test_score_dia.py`

**Interfaces:**
- Consumes: `surf.score.evaluar_hora`, `surf.score.Hora`, `surf.spots.Spot`
- Produces:
  - `DiaEvaluado` — dataclass frozen: `fecha: date`, `spot_id: str`, `es_bueno: bool`, `score: float`, `horas_buenas: int`, `bloque: tuple[datetime, datetime] | None`, `resumen: dict[str, float] | None`, `motivo_principal: str | None`
  - `evaluar_dia(horas: list[Hora], spot: Spot, fecha: date) -> DiaEvaluado`
  - `HORAS_MINIMAS_CONSECUTIVAS = 3`

`resumen` contiene las claves `altura`, `periodo`, `direccion`, `viento_kmh`, `viento_direccion`, promediadas sobre el mejor bloque (la dirección se toma la del punto medio del bloque, no se promedia, para evitar el error de promediar ángulos).

- [ ] **Step 1: Escribir los tests que fallan**

`tests/test_score_dia.py`:
```python
from datetime import date, datetime

import pytest

from surf.score import Hora, evaluar_dia
from tests.test_score_gate import SPOT

FECHA = date(2026, 8, 21)


def h(hora_del_dia, buena=True, de_dia=True):
    """Hora buena o mala segun el flag, en el horario indicado."""
    if buena:
        return Hora(t=datetime(2026, 8, 21, hora_del_dia), swell_altura=2.0,
                    swell_periodo=13.0, swell_direccion=157.0, viento_kmh=5.0,
                    viento_direccion=320.0, es_de_dia=de_dia)
    return Hora(t=datetime(2026, 8, 21, hora_del_dia), swell_altura=0.5,
                swell_periodo=5.0, swell_direccion=157.0, viento_kmh=25.0,
                viento_direccion=140.0, es_de_dia=de_dia)


def test_tres_horas_buenas_consecutivas_hacen_un_dia_bueno():
    horas = [h(8), h(9), h(10)]
    d = evaluar_dia(horas, SPOT, FECHA)
    assert d.es_bueno is True
    assert d.horas_buenas == 3


def test_dos_horas_buenas_consecutivas_no_alcanzan():
    horas = [h(8), h(9), h(10, buena=False)]
    d = evaluar_dia(horas, SPOT, FECHA)
    assert d.es_bueno is False


def test_tres_horas_buenas_no_consecutivas_no_alcanzan():
    # Buenas a las 8, 10 y 12 pero cortadas: no es una sesion
    horas = [h(8), h(9, buena=False), h(10), h(11, buena=False), h(12)]
    d = evaluar_dia(horas, SPOT, FECHA)
    assert d.es_bueno is False


def test_el_bloque_reportado_es_el_de_mejor_score():
    # Bloque de la manana flojo, bloque de la tarde perfecto
    flojas = [Hora(t=datetime(2026, 8, 21, x), swell_altura=1.1,
                   swell_periodo=9.5, swell_direccion=120.0, viento_kmh=7.0,
                   viento_direccion=230.0, es_de_dia=True) for x in (7, 8, 9)]
    buenas = [h(x) for x in (15, 16, 17)]
    d = evaluar_dia(flojas + buenas, SPOT, FECHA)
    assert d.es_bueno is True
    assert d.bloque[0].hour == 15
    assert d.bloque[1].hour == 17


def test_dia_sin_horas_de_luz_buenas_no_es_bueno():
    horas = [h(3, de_dia=False), h(4, de_dia=False), h(5, de_dia=False)]
    d = evaluar_dia(horas, SPOT, FECHA)
    assert d.es_bueno is False


def test_dia_malo_reporta_el_motivo_mas_frecuente():
    horas = [h(x, buena=False) for x in (8, 9, 10)]
    d = evaluar_dia(horas, SPOT, FECHA)
    assert d.es_bueno is False
    assert d.motivo_principal is not None


def test_el_resumen_trae_las_condiciones_del_mejor_bloque():
    d = evaluar_dia([h(8), h(9), h(10)], SPOT, FECHA)
    assert d.resumen["altura"] == pytest.approx(2.0)
    assert d.resumen["periodo"] == pytest.approx(13.0)
    assert d.resumen["viento_kmh"] == pytest.approx(5.0)


def test_dia_malo_no_trae_resumen_ni_bloque():
    d = evaluar_dia([h(8, buena=False)], SPOT, FECHA)
    assert d.bloque is None
    assert d.resumen is None


def test_lista_vacia_no_rompe():
    d = evaluar_dia([], SPOT, FECHA)
    assert d.es_bueno is False
    assert d.score == 0.0
```

- [ ] **Step 2: Correr los tests y verificar que fallan**

Run: `.venv/bin/pytest tests/test_score_dia.py -v`
Expected: FAIL con `ImportError: cannot import name 'evaluar_dia'`

- [ ] **Step 3: Implementar `evaluar_dia` en `surf/score.py`**

Agregar `from collections import Counter` y `from datetime import date, datetime` a los imports.

```python
HORAS_MINIMAS_CONSECUTIVAS = 3


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
```

- [ ] **Step 4: Correr todos los tests y verificar que pasan**

Run: `.venv/bin/pytest tests/ -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add surf/score.py tests/test_score_dia.py
git commit -m "feat: agregacion de horas a dias con bloque minimo de 3 horas"
```

---

### Task 7: Obtención de datos de Open-Meteo

**Files:**
- Create: `surf/fetch.py`
- Test: `tests/test_fetch.py`

**Interfaces:**
- Consumes: `surf.spots.Spot`, `surf.score.Hora`
- Produces:
  - `obtener_horas(spot: Spot, dias: int = 7, sesion=None) -> dict[date, list[Hora]]`
  - `ErrorDatos` — excepción propia
  - `_combinar(marine: dict, clima: dict) -> dict[date, list[Hora]]` — función pura, testeable sin red

- [ ] **Step 1: Escribir los tests que fallan**

`tests/test_fetch.py`:
```python
from datetime import date

import pytest

from surf.fetch import ErrorDatos, _combinar

MARINE = {
    "hourly": {
        "time": ["2026-08-21T05:00", "2026-08-21T09:00", "2026-08-21T22:00"],
        "swell_wave_height": [1.8, 1.9, 1.7],
        "swell_wave_period": [14.0, 14.2, 13.8],
        "swell_wave_direction": [200.0, 202.0, 199.0],
    }
}

CLIMA = {
    "hourly": {
        "time": ["2026-08-21T05:00", "2026-08-21T09:00", "2026-08-21T22:00"],
        "wind_speed_10m": [8.0, 9.0, 12.0],
        "wind_direction_10m": [95.0, 97.0, 100.0],
    },
    "daily": {
        "time": ["2026-08-21"],
        "sunrise": ["2026-08-21T06:45"],
        "sunset": ["2026-08-21T18:20"],
    },
}


def test_combina_marine_y_clima_en_horas():
    por_dia = _combinar(MARINE, CLIMA)
    horas = por_dia[date(2026, 8, 21)]
    assert len(horas) == 3
    assert horas[1].swell_altura == 1.9
    assert horas[1].viento_kmh == 9.0
    assert horas[1].viento_direccion == 97.0


def test_marca_las_horas_de_luz():
    por_dia = _combinar(MARINE, CLIMA)
    horas = {h.t.hour: h for h in por_dia[date(2026, 8, 21)]}
    assert horas[5].es_de_dia is False    # antes del amanecer 06:45
    assert horas[9].es_de_dia is True     # pleno dia
    assert horas[22].es_de_dia is False   # despues del ocaso 18:20


def test_descarta_horas_con_datos_nulos():
    marine = {"hourly": dict(MARINE["hourly"])}
    marine["hourly"]["swell_wave_period"] = [14.0, None, 13.8]
    por_dia = _combinar(marine, CLIMA)
    assert len(por_dia[date(2026, 8, 21)]) == 2


def test_falla_si_faltan_campos_del_marine():
    with pytest.raises(ErrorDatos, match="swell_wave_height"):
        _combinar({"hourly": {"time": []}}, CLIMA)


def test_falla_si_las_series_no_alinean():
    clima = {"hourly": {"time": ["2026-08-21T05:00"],
                        "wind_speed_10m": [8.0], "wind_direction_10m": [95.0]},
             "daily": CLIMA["daily"]}
    with pytest.raises(ErrorDatos, match="alinea"):
        _combinar(MARINE, clima)


def test_falla_si_no_hay_datos_diarios_de_sol():
    clima = {"hourly": CLIMA["hourly"], "daily": {"time": [], "sunrise": [], "sunset": []}}
    with pytest.raises(ErrorDatos, match="sol"):
        _combinar(MARINE, clima)
```

- [ ] **Step 2: Correr los tests y verificar que fallan**

Run: `.venv/bin/pytest tests/test_fetch.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'surf.fetch'`

- [ ] **Step 3: Implementar `surf/fetch.py`**

```python
"""Obtencion de datos de Open-Meteo.

Dos endpoints: Marine API para el swell, Forecast API para viento y
amanecer/ocaso. Ambos en el tier gratuito, sin API key.

`timezone=auto` hace que Open-Meteo devuelva todo en la hora local del spot,
que es lo que importa para decidir si una hora es de luz.
"""
import time
from datetime import date, datetime

import requests

from surf.score import Hora
from surf.spots import Spot

URL_MARINE = "https://marine-api.open-meteo.com/v1/marine"
URL_CLIMA = "https://api.open-meteo.com/v1/forecast"

REINTENTOS = 3
ESPERA_BASE_S = 2
TIMEOUT_S = 30

_CAMPOS_MARINE = ["swell_wave_height", "swell_wave_period", "swell_wave_direction"]
_CAMPOS_CLIMA = ["wind_speed_10m", "wind_direction_10m"]


class ErrorDatos(Exception):
    """Los datos recibidos no sirven para evaluar."""


def _pedir(url: str, params: dict, sesion=None) -> dict:
    """GET con reintentos y backoff exponencial."""
    cliente = sesion or requests
    ultimo: Exception | None = None
    for intento in range(REINTENTOS):
        try:
            r = cliente.get(url, params=params, timeout=TIMEOUT_S)
            r.raise_for_status()
            datos = r.json()
            if datos.get("error"):
                raise ErrorDatos(f"Open-Meteo devolvio error: {datos.get('reason')}")
            return datos
        except Exception as e:  # noqa: BLE001 - reintentamos ante cualquier fallo de red
            ultimo = e
            if intento < REINTENTOS - 1:
                time.sleep(ESPERA_BASE_S * (2 ** intento))
    raise ErrorDatos(f"fallaron los {REINTENTOS} intentos contra {url}: {ultimo}")


def _validar_series(bloque: dict, campos: list[str], nombre: str) -> None:
    if "time" not in bloque:
        raise ErrorDatos(f"la respuesta de {nombre} no trae 'time'")
    for campo in campos:
        if campo not in bloque:
            raise ErrorDatos(f"la respuesta de {nombre} no trae '{campo}'")


def _combinar(marine: dict, clima: dict) -> dict[date, list[Hora]]:
    """Une las dos respuestas en horas agrupadas por dia. Funcion pura."""
    hm = marine.get("hourly", {})
    hc = clima.get("hourly", {})
    dc = clima.get("daily", {})

    _validar_series(hm, _CAMPOS_MARINE, "marine")
    _validar_series(hc, _CAMPOS_CLIMA, "clima")

    if hm["time"] != hc["time"]:
        raise ErrorDatos("las series horarias de marine y clima no alinean")

    if not dc.get("sunrise") or not dc.get("sunset"):
        raise ErrorDatos("faltan los datos de salida y puesta del sol")

    sol = {
        date.fromisoformat(d): (
            datetime.fromisoformat(dc["sunrise"][i]),
            datetime.fromisoformat(dc["sunset"][i]),
        )
        for i, d in enumerate(dc["time"])
    }

    por_dia: dict[date, list[Hora]] = {}
    for i, t_str in enumerate(hm["time"]):
        valores = [hm[c][i] for c in _CAMPOS_MARINE] + [hc[c][i] for c in _CAMPOS_CLIMA]
        if any(v is None for v in valores):
            continue

        t = datetime.fromisoformat(t_str)
        if t.date() not in sol:
            continue
        amanecer, ocaso = sol[t.date()]

        por_dia.setdefault(t.date(), []).append(
            Hora(
                t=t,
                swell_altura=float(hm["swell_wave_height"][i]),
                swell_periodo=float(hm["swell_wave_period"][i]),
                swell_direccion=float(hm["swell_wave_direction"][i]),
                viento_kmh=float(hc["wind_speed_10m"][i]),
                viento_direccion=float(hc["wind_direction_10m"][i]),
                es_de_dia=amanecer <= t <= ocaso,
            )
        )

    return por_dia


def obtener_horas(spot: Spot, dias: int = 7, sesion=None) -> dict[date, list[Hora]]:
    """Trae el pronostico horario del spot, agrupado por dia local."""
    base = {"latitude": spot.lat, "longitude": spot.lon,
            "timezone": "auto", "forecast_days": dias}

    marine = _pedir(URL_MARINE, {**base, "hourly": ",".join(_CAMPOS_MARINE)}, sesion)
    clima = _pedir(
        URL_CLIMA,
        {**base, "hourly": ",".join(_CAMPOS_CLIMA), "daily": "sunrise,sunset",
         "wind_speed_unit": "kmh"},
        sesion,
    )
    return _combinar(marine, clima)
```

**Importante:** `wind_speed_unit=kmh` es obligatorio. Open-Meteo devuelve km/h por defecto en la Forecast API, pero fijarlo explícitamente evita que un cambio de default rompa todos los umbrales en silencio.

- [ ] **Step 4: Correr los tests y verificar que pasan**

Run: `.venv/bin/pytest tests/test_fetch.py -v`
Expected: PASS, 6 tests

- [ ] **Step 5: Verificar contra la API real**

```bash
.venv/bin/python - <<'EOF'
from pathlib import Path
from surf.fetch import obtener_horas
from surf.score import evaluar_dia
from surf.spots import cargar_spots

spot = [s for s in cargar_spots(Path("spots.yaml")) if s.id == "chapadmalal"][0]
por_dia = obtener_horas(spot, dias=3)
for fecha, horas in sorted(por_dia.items()):
    d = evaluar_dia(horas, spot, fecha)
    estado = "BUENO" if d.es_bueno else f"no ({d.motivo_principal})"
    print(f"{fecha}  {len(horas)}h  score {d.score:5.1f}  {estado}")
EOF
```
Expected: 3 líneas, ~24 horas cada día, sin excepciones.

- [ ] **Step 6: Commit**

```bash
git add surf/fetch.py tests/test_fetch.py
git commit -m "feat: obtencion de datos de Open-Meteo con reintentos"
```

---

### Task 8: Ventanas, persistencia y anti-repetición

**Files:**
- Create: `surf/alert.py`
- Test: `tests/test_alert.py`

**Interfaces:**
- Consumes: `surf.score.DiaEvaluado`
- Produces:
  - `Ventana` — dataclass frozen: `spot_id: str`, `desde: date`, `hasta: date`, `dias: tuple[DiaEvaluado, ...]`, `score: float`
  - `detectar_ventanas(dias: list[DiaEvaluado]) -> list[Ventana]`
  - `decidir_alertas(ventanas: list[Ventana], estado: dict, hoy: date) -> tuple[list[Ventana], dict]`
  - `estado_vacio() -> dict`
  - `DIAS_MINIMOS_VENTANA = 2`, `SALTO_SCORE_REALERTA = 15.0`

Formato de `state.json`:
```json
{
  "ultima_corrida": "2026-08-13",
  "observadas": [{"spot_id": "chicama", "desde": "2026-08-21", "hasta": "2026-08-23", "score": 87.0}],
  "alertadas": [{"spot_id": "chicama", "desde": "2026-08-21", "hasta": "2026-08-23", "score": 87.0, "fecha_alerta": "2026-08-13"}]
}
```

Las ventanas se emparejan **por solapamiento de fechas**, no por igualdad exacta: el pronóstico puede correr el inicio de la ventana un día sin que sea una ventana distinta.

- [ ] **Step 1: Escribir los tests que fallan**

`tests/test_alert.py`:
```python
from datetime import date

import pytest

from surf.alert import (Ventana, decidir_alertas, detectar_ventanas,
                        estado_vacio)
from surf.score import DiaEvaluado

HOY = date(2026, 8, 13)


def dia(d, bueno=True, score=80.0, spot="chicama"):
    return DiaEvaluado(fecha=date(2026, 8, d), spot_id=spot, es_bueno=bueno,
                       score=score if bueno else 0.0, horas_buenas=5 if bueno else 0,
                       bloque=None, resumen=None, motivo_principal=None)


def test_dos_dias_consecutivos_forman_ventana():
    v = detectar_ventanas([dia(21), dia(22)])
    assert len(v) == 1
    assert v[0].desde == date(2026, 8, 21)
    assert v[0].hasta == date(2026, 8, 22)


def test_un_dia_aislado_no_forma_ventana():
    assert detectar_ventanas([dia(21)]) == []


def test_dos_dias_buenos_separados_no_forman_ventana():
    assert detectar_ventanas([dia(21), dia(22, bueno=False), dia(23)]) == []


def test_la_ventana_toma_el_score_maximo_de_sus_dias():
    v = detectar_ventanas([dia(21, score=70), dia(22, score=94), dia(23, score=78)])
    assert v[0].score == 94.0


def test_ventanas_de_spots_distintos_no_se_mezclan():
    dias = [dia(21, spot="chicama"), dia(22, spot="chicama"),
            dia(21, spot="lobitos"), dia(22, spot="lobitos")]
    assert len(detectar_ventanas(dias)) == 2


def test_ventana_nueva_no_alerta_falta_persistencia():
    v = detectar_ventanas([dia(21), dia(22)])
    a_alertar, nuevo = decidir_alertas(v, estado_vacio(), HOY)
    assert a_alertar == []
    assert len(nuevo["observadas"]) == 1


def test_ventana_confirmada_ayer_si_alerta():
    v = detectar_ventanas([dia(21), dia(22)])
    _, estado = decidir_alertas(v, estado_vacio(), date(2026, 8, 12))
    a_alertar, _ = decidir_alertas(v, estado, HOY)
    assert len(a_alertar) == 1
    assert a_alertar[0].spot_id == "chicama"


def test_no_realerta_la_misma_ventana():
    v = detectar_ventanas([dia(21), dia(22)])
    _, e1 = decidir_alertas(v, estado_vacio(), date(2026, 8, 12))
    _, e2 = decidir_alertas(v, e1, HOY)          # alerta aca
    a_alertar, _ = decidir_alertas(v, e2, date(2026, 8, 14))
    assert a_alertar == []


def test_realerta_si_el_score_mejora_mucho():
    v1 = detectar_ventanas([dia(21, score=70), dia(22, score=70)])
    _, e1 = decidir_alertas(v1, estado_vacio(), date(2026, 8, 12))
    _, e2 = decidir_alertas(v1, e1, HOY)
    v2 = detectar_ventanas([dia(21, score=92), dia(22, score=92)])
    a_alertar, _ = decidir_alertas(v2, e2, date(2026, 8, 14))
    assert len(a_alertar) == 1


def test_realerta_si_la_ventana_se_extiende():
    v1 = detectar_ventanas([dia(21), dia(22)])
    _, e1 = decidir_alertas(v1, estado_vacio(), date(2026, 8, 12))
    _, e2 = decidir_alertas(v1, e1, HOY)
    v2 = detectar_ventanas([dia(21), dia(22), dia(23)])
    a_alertar, _ = decidir_alertas(v2, e2, date(2026, 8, 14))
    assert len(a_alertar) == 1


def test_la_ventana_que_corre_un_dia_sigue_siendo_la_misma():
    # Ayer se vio 21-22, hoy el modelo la muestra 20-22: es la misma ventana
    v1 = detectar_ventanas([dia(21), dia(22)])
    _, e1 = decidir_alertas(v1, estado_vacio(), date(2026, 8, 12))
    v2 = detectar_ventanas([dia(20), dia(21), dia(22)])
    a_alertar, _ = decidir_alertas(v2, e1, HOY)
    assert len(a_alertar) == 1  # alerta por persistencia, no la trata como nueva


def test_un_hueco_en_las_corridas_resetea_la_persistencia():
    # Si la ultima corrida fue hace 3 dias, no hay confirmacion valida
    v = detectar_ventanas([dia(21), dia(22)])
    _, estado = decidir_alertas(v, estado_vacio(), date(2026, 8, 9))
    a_alertar, _ = decidir_alertas(v, estado, HOY)
    assert a_alertar == []


def test_se_purgan_las_ventanas_ya_pasadas():
    v = detectar_ventanas([dia(21), dia(22)])
    _, estado = decidir_alertas(v, estado_vacio(), date(2026, 8, 12))
    _, limpio = decidir_alertas([], estado, date(2026, 9, 30))
    assert limpio["observadas"] == []
    assert limpio["alertadas"] == []
```

- [ ] **Step 2: Correr los tests y verificar que fallan**

Run: `.venv/bin/pytest tests/test_alert.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'surf.alert'`

- [ ] **Step 3: Implementar `surf/alert.py`**

```python
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
```

- [ ] **Step 4: Correr los tests y verificar que pasan**

Run: `.venv/bin/pytest tests/test_alert.py -v`
Expected: PASS, 13 tests

- [ ] **Step 5: Commit**

```bash
git add surf/alert.py tests/test_alert.py
git commit -m "feat: ventanas con persistencia y anti-repeticion"
```

---

### Task 9: Mensajes de Telegram

**Files:**
- Create: `surf/notify.py`
- Test: `tests/test_notify.py`

**Interfaces:**
- Consumes: `surf.alert.Ventana`, `surf.score.DiaEvaluado`, `surf.spots.Spot`, `surf.geo.rumbo_a_texto`
- Produces:
  - `formatear_alerta(ventana: Ventana, spot: Spot) -> str`
  - `formatear_digest(cercanos: list[tuple[DiaEvaluado, Spot]], hubo_alertas: int, fecha: date) -> str`
  - `enviar(mensaje: str, token: str, chat_id: str, sesion=None) -> None`
  - `ErrorEnvio` — excepción propia

- [ ] **Step 1: Escribir los tests que fallan**

`tests/test_notify.py`:
```python
from datetime import date, datetime

import pytest

from surf.alert import detectar_ventanas
from surf.notify import formatear_alerta, formatear_digest
from surf.score import DiaEvaluado
from tests.test_score_gate import SPOT


def dia(d, score=87.0):
    return DiaEvaluado(
        fecha=date(2026, 8, d), spot_id=SPOT.id, es_bueno=True, score=score,
        horas_buenas=5,
        bloque=(datetime(2026, 8, d, 7), datetime(2026, 8, d, 11)),
        resumen={"altura": 1.8, "periodo": 14.0, "direccion": 200.0,
                 "viento_kmh": 9.0, "viento_direccion": 95.0},
        motivo_principal=None,
    )


def test_la_alerta_nombra_el_spot_y_las_fechas():
    v = detectar_ventanas([dia(21), dia(22)])[0]
    m = formatear_alerta(v, SPOT)
    assert SPOT.nombre in m
    assert "21" in m and "22" in m


def test_la_alerta_incluye_altura_periodo_y_viento_de_cada_dia():
    v = detectar_ventanas([dia(21), dia(22)])[0]
    m = formatear_alerta(v, SPOT)
    assert "1.8m" in m
    assert "14s" in m
    assert "9km/h" in m


def test_la_alerta_traduce_las_direcciones_a_texto():
    v = detectar_ventanas([dia(21), dia(22)])[0]
    m = formatear_alerta(v, SPOT)
    assert "SSW" in m   # swell desde 200
    assert "E" in m     # viento desde 95


def test_la_alerta_clasifica_el_viento():
    v = detectar_ventanas([dia(21), dia(22)])[0]
    m = formatear_alerta(v, SPOT)
    # costa_mira 140 -> offshore desde 320. Viento desde 95 es cross.
    assert "cross" in m


def test_la_alerta_incluye_el_link_de_surfforecast():
    v = detectar_ventanas([dia(21), dia(22)])[0]
    assert SPOT.url_surfforecast in formatear_alerta(v, SPOT)


def test_la_alerta_marca_la_mejor_ventana_horaria():
    v = detectar_ventanas([dia(21), dia(22)])[0]
    m = formatear_alerta(v, SPOT)
    assert "Mejor ventana" in m


def test_la_alerta_de_baja_confianza_lo_avisa():
    from dataclasses import replace
    spot_dudoso = replace(SPOT, confianza="baja")
    v = detectar_ventanas([dia(21), dia(22)])[0]
    assert "perfil poco validado" in formatear_alerta(v, spot_dudoso)


def test_el_digest_vacio_igual_dice_algo():
    m = formatear_digest([], hubo_alertas=0, fecha=date(2026, 8, 16))
    assert "sin ventanas" in m.lower()


def test_el_digest_lista_lo_que_quedo_cerca():
    d = DiaEvaluado(fecha=date(2026, 8, 18), spot_id=SPOT.id, es_bueno=False,
                    score=0.0, horas_buenas=0, bloque=None, resumen=None,
                    motivo_principal="periodo corto (8.5s, minimo 9.0s)")
    m = formatear_digest([(d, SPOT)], hubo_alertas=0, fecha=date(2026, 8, 16))
    assert SPOT.nombre in m
    assert "periodo corto" in m


def test_el_digest_reporta_cuantas_alertas_hubo():
    m = formatear_digest([], hubo_alertas=3, fecha=date(2026, 8, 16))
    assert "3" in m
```

- [ ] **Step 2: Correr los tests y verificar que fallan**

Run: `.venv/bin/pytest tests/test_notify.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'surf.notify'`

- [ ] **Step 3: Implementar `surf/notify.py`**

```python
"""Formato y envio de mensajes a Telegram."""
from datetime import date

import requests

from surf.alert import Ventana
from surf.geo import clasificar_viento, rumbo_a_texto
from surf.score import DiaEvaluado
from surf.spots import Spot

URL_TELEGRAM = "https://api.telegram.org/bot{token}/sendMessage"
TIMEOUT_S = 20

_MESES = ["", "enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
          "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
_DIAS = ["Lun", "Mar", "Mie", "Jue", "Vie", "Sab", "Dom"]


class ErrorEnvio(Exception):
    """No se pudo entregar el mensaje."""


def _fecha_corta(d: date) -> str:
    return f"{_DIAS[d.weekday()]} {d.day}"


def _linea_dia(dia: DiaEvaluado, spot: Spot) -> str:
    r = dia.resumen or {}
    clase = clasificar_viento(r.get("viento_direccion", 0), spot.costa_mira)
    return (
        f"{_fecha_corta(dia.fecha):<7} "
        f"{r.get('altura', 0):.1f}m @ {r.get('periodo', 0):.0f}s "
        f"del {rumbo_a_texto(r.get('direccion', 0))}  ·  "
        f"viento {rumbo_a_texto(r.get('viento_direccion', 0))} "
        f"{r.get('viento_kmh', 0):.0f}km/h {clase}  ·  "
        f"{dia.score:.0f}/100"
    )


def formatear_alerta(ventana: Ventana, spot: Spot) -> str:
    mejor = max(ventana.dias, key=lambda d: d.score)
    cant = len(ventana.dias)

    partes = [
        f"🔥 BUEN SWELL — {spot.nombre}",
        f"{_fecha_corta(ventana.desde)} a {_fecha_corta(ventana.hasta)} "
        f"de {_MESES[ventana.hasta.month]} ({cant} dias)",
        "",
    ]
    partes += [_linea_dia(d, spot) for d in ventana.dias]
    partes.append("")

    if mejor.bloque:
        partes.append(
            f"Mejor ventana: {_fecha_corta(mejor.fecha).lower()} "
            f"{mejor.bloque[0].hour}-{mejor.bloque[1].hour} hs"
        )
    partes.append("Confirmado en 2 corridas consecutivas ✓")

    if spot.confianza == "baja":
        partes.append("⚠️ perfil poco validado — chequear en surf-forecast antes de viajar")

    partes.append(f"→ {spot.url_surfforecast}")
    return "\n".join(partes)


def formatear_digest(cercanos: list[tuple[DiaEvaluado, Spot]],
                     hubo_alertas: int, fecha: date) -> str:
    partes = [f"📋 Resumen semanal — {fecha.day} de {_MESES[fecha.month]}", ""]

    if hubo_alertas:
        partes.append(f"Alertas enviadas esta semana: {hubo_alertas}")
    else:
        partes.append("Alertas enviadas esta semana: 0")
    partes.append("")

    if not cercanos:
        partes.append("Sin ventanas cerca del umbral en los proximos dias.")
    else:
        partes.append("Quedo cerca pero no alcanzo:")
        for dia, spot in cercanos:
            partes.append(f"· {spot.nombre} — {_fecha_corta(dia.fecha)}: {dia.motivo_principal}")

    partes.append("")
    partes.append("(Este resumen llega todos los domingos. Si algun domingo no llega, "
                  "el sistema esta caido.)")
    return "\n".join(partes)


def enviar(mensaje: str, token: str, chat_id: str, sesion=None) -> None:
    """Manda un mensaje. Lanza ErrorEnvio si no se pudo entregar."""
    cliente = sesion or requests
    try:
        r = cliente.post(
            URL_TELEGRAM.format(token=token),
            json={"chat_id": chat_id, "text": mensaje, "disable_web_page_preview": True},
            timeout=TIMEOUT_S,
        )
        r.raise_for_status()
    except Exception as e:  # noqa: BLE001
        raise ErrorEnvio(f"no se pudo enviar a Telegram: {e}") from e
```

- [ ] **Step 4: Correr los tests y verificar que pasan**

Run: `.venv/bin/pytest tests/ -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add surf/notify.py tests/test_notify.py
git commit -m "feat: formato y envio de mensajes de Telegram"
```

---

### Task 10: Entrypoint y workflow de GitHub Actions

**Files:**
- Create: `run.py`
- Create: `.github/workflows/daily.yml`
- Create: `state.json`
- Create: `README.md`
- Test: `tests/test_run.py`

**Interfaces:**
- Consumes: todos los módulos anteriores
- Produces:
  - `correr(spots, hoy, traer, enviar_fn, estado) -> tuple[dict, list[str]]` — el orquestador, con las dependencias inyectadas para poder testearlo sin red
  - `main() -> int` — lee entorno, arma las dependencias reales, devuelve exit code

- [ ] **Step 1: Escribir los tests que fallan**

`tests/test_run.py`:
```python
from datetime import date, datetime

import pytest

from run import correr
from surf.alert import estado_vacio
from surf.fetch import ErrorDatos
from surf.score import Hora
from tests.test_score_gate import SPOT

HOY = date(2026, 8, 13)


def _horas_buenas(fecha):
    return [Hora(t=datetime(fecha.year, fecha.month, fecha.day, x),
                 swell_altura=2.0, swell_periodo=14.0, swell_direccion=157.0,
                 viento_kmh=5.0, viento_direccion=320.0, es_de_dia=True)
            for x in range(7, 13)]


def _traer_bueno(spot, dias=7):
    from datetime import timedelta
    return {HOY + timedelta(days=n): _horas_buenas(HOY + timedelta(days=n))
            for n in range(1, 4)}


def _traer_roto(spot, dias=7):
    raise ErrorDatos("Open-Meteo caido")


def test_una_corrida_normal_actualiza_el_estado():
    enviados = []
    estado, msgs = correr([SPOT], HOY, _traer_bueno, enviados.append, estado_vacio())
    assert estado["ultima_corrida"] == HOY.isoformat()
    assert len(estado["observadas"]) >= 1


def test_la_primera_corrida_no_alerta():
    enviados = []
    correr([SPOT], HOY, _traer_bueno, enviados.append, estado_vacio())
    assert enviados == []


def test_la_segunda_corrida_consecutiva_si_alerta():
    from datetime import timedelta
    enviados = []
    estado, _ = correr([SPOT], HOY - timedelta(days=1), _traer_bueno,
                       lambda m: None, estado_vacio())
    correr([SPOT], HOY, _traer_bueno, enviados.append, estado)
    assert len(enviados) >= 1
    assert "BUEN SWELL" in enviados[0]


def test_si_un_spot_falla_los_demas_siguen():
    from dataclasses import replace
    otro = replace(SPOT, id="otro")
    llamadas = {"n": 0}

    def traer(spot, dias=7):
        llamadas["n"] += 1
        if spot.id == "otro":
            raise ErrorDatos("sin datos")
        return _traer_bueno(spot)

    estado, msgs = correr([SPOT, otro], HOY, traer, lambda m: None, estado_vacio())
    assert llamadas["n"] == 2
    assert estado["ultima_corrida"] == HOY.isoformat()


def test_si_fallan_todos_los_spots_no_se_escribe_estado():
    with pytest.raises(RuntimeError, match="ningun spot"):
        correr([SPOT], HOY, _traer_roto, lambda m: None, estado_vacio())


def test_el_domingo_se_manda_el_digest():
    enviados = []
    domingo = date(2026, 8, 16)
    assert domingo.weekday() == 6
    correr([SPOT], domingo, _traer_bueno, enviados.append, estado_vacio())
    assert any("Resumen semanal" in m for m in enviados)


def test_entre_semana_no_se_manda_digest():
    enviados = []
    jueves = date(2026, 8, 13)
    assert jueves.weekday() == 3
    correr([SPOT], jueves, _traer_bueno, enviados.append, estado_vacio())
    assert not any("Resumen semanal" in m for m in enviados)
```

- [ ] **Step 2: Correr los tests y verificar que fallan**

Run: `.venv/bin/pytest tests/test_run.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'run'`

- [ ] **Step 3: Implementar `run.py`**

```python
"""Entrypoint diario del sistema de alertas.

`correr` recibe sus dependencias por parametro para poder testearlo sin red.
`main` arma las dependencias reales y traduce el resultado a exit code.
"""
import json
import os
import sys
from datetime import date
from pathlib import Path
from typing import Callable

from surf.alert import decidir_alertas, detectar_ventanas, estado_vacio
from surf.fetch import ErrorDatos, obtener_horas
from surf.notify import ErrorEnvio, enviar, formatear_alerta, formatear_digest
from surf.score import DiaEvaluado, evaluar_dia
from surf.spots import Spot, cargar_spots

RUTA_SPOTS = Path("spots.yaml")
RUTA_ESTADO = Path("state.json")
DIA_DEL_DIGEST = 6  # domingo


def _cerca_del_umbral(dia: DiaEvaluado) -> bool:
    """Fallo por un solo criterio y no por falta de olas."""
    if dia.es_bueno or not dia.motivo_principal:
        return False
    return any(k in dia.motivo_principal for k in ("periodo", "onshore", "cross", "direccion"))


def correr(spots: list[Spot], hoy: date,
           traer: Callable, enviar_fn: Callable[[str], None],
           estado: dict) -> tuple[dict, list[str]]:
    """Corre el ciclo completo. Devuelve el estado nuevo y los mensajes enviados."""
    todos_los_dias: list[DiaEvaluado] = []
    cercanos: list[tuple[DiaEvaluado, Spot]] = []
    por_id = {s.id: s for s in spots}
    exitosos = 0

    for spot in spots:
        try:
            por_dia = traer(spot)
        except ErrorDatos as e:
            print(f"[WARN] {spot.id}: {e}", file=sys.stderr)
            continue
        exitosos += 1
        for fecha, horas in por_dia.items():
            d = evaluar_dia(horas, spot, fecha)
            todos_los_dias.append(d)
            if _cerca_del_umbral(d):
                cercanos.append((d, spot))

    if exitosos == 0:
        raise RuntimeError("ningun spot devolvio datos; no se escribe estado")

    ventanas = detectar_ventanas(todos_los_dias)
    a_alertar, estado_nuevo = decidir_alertas(ventanas, estado, hoy)

    enviados: list[str] = []
    for v in sorted(a_alertar, key=lambda x: -x.score):
        m = formatear_alerta(v, por_id[v.spot_id])
        enviar_fn(m)
        enviados.append(m)

    if hoy.weekday() == DIA_DEL_DIGEST:
        m = formatear_digest(cercanos[:10], hubo_alertas=len(a_alertar), fecha=hoy)
        enviar_fn(m)
        enviados.append(m)

    print(f"[OK] {exitosos}/{len(spots)} spots, {len(ventanas)} ventanas, "
          f"{len(a_alertar)} alertas, {len(enviados)} mensajes")
    return estado_nuevo, enviados


def main() -> int:
    token = os.environ.get("TELEGRAM_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("[ERROR] faltan TELEGRAM_TOKEN o TELEGRAM_CHAT_ID", file=sys.stderr)
        return 2

    spots = cargar_spots(RUTA_SPOTS)
    estado = json.loads(RUTA_ESTADO.read_text()) if RUTA_ESTADO.exists() else estado_vacio()

    try:
        estado_nuevo, _ = correr(
            spots, date.today(), obtener_horas,
            lambda m: enviar(m, token, chat_id), estado,
        )
    except RuntimeError as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        try:
            enviar(f"⚠️ El sistema de alertas fallo hoy: {e}", token, chat_id)
        except ErrorEnvio:
            pass
        return 1

    # Solo se escribe estado si la corrida completa termino bien.
    RUTA_ESTADO.write_text(json.dumps(estado_nuevo, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Crear `state.json` inicial**

```json
{
  "ultima_corrida": null,
  "observadas": [],
  "alertadas": []
}
```

- [ ] **Step 5: Correr los tests y verificar que pasan**

Run: `.venv/bin/pytest tests/ -v`
Expected: PASS, la suite completa

- [ ] **Step 6: Crear el workflow**

`.github/workflows/daily.yml`:
```yaml
name: Chequeo diario de swell

on:
  schedule:
    # 10:00 UTC = 07:00 hora Argentina (UTC-3)
    - cron: "0 10 * * *"
  workflow_dispatch:

permissions:
  contents: write

jobs:
  chequear:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - run: pip install -r requirements.txt

      - run: pytest tests/ -q

      - name: Chequear los spots
        env:
          TELEGRAM_TOKEN: ${{ secrets.TELEGRAM_TOKEN }}
          TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}
        run: python run.py

      - name: Guardar el estado
        # El commit diario mantiene el repo activo. GitHub desactiva los
        # workflows programados tras 60 dias sin commits, y esa falla seria
        # silenciosa.
        run: |
          git config user.name "surf-forecast-bot"
          git config user.email "bot@users.noreply.github.com"
          git add state.json
          git diff --staged --quiet || git commit -m "chore: estado del $(date -u +%Y-%m-%d)"
          git push
```

- [ ] **Step 7: Escribir el `README.md`**

Debe incluir: qué hace el sistema, cómo crear el bot con @BotFather, cómo obtener el `chat_id` (mandarle un mensaje al bot y consultar `https://api.telegram.org/bot<TOKEN>/getUpdates`), cómo cargar los dos secrets en Settings → Secrets and variables → Actions, cómo correrlo a mano con `workflow_dispatch`, y cómo ajustar umbrales editando `spots.yaml`.

- [ ] **Step 8: Probar la corrida completa en local**

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
Expected: corre los 13 spots sin excepción e imprime el conteo. No manda nada a Telegram (la primera corrida nunca alerta).

- [ ] **Step 9: Commit**

```bash
git add run.py state.json README.md .github/ tests/test_run.py
git commit -m "feat: entrypoint diario y workflow de GitHub Actions"
```

---

### Task 11: Consenso multi-modelo

Capa aditiva sobre el sistema ya funcionando. Reemplaza la función de Windguru —
comparar modelos— calculándola en vez de mostrarla.

**Files:**
- Create: `surf/consenso.py`
- Modify: `surf/fetch.py` (pasar a multi-modelo)
- Modify: `surf/score.py` (agregar campo `concordancia` a `DiaEvaluado`)
- Modify: `surf/notify.py` (mostrar concordancia)
- Modify: `run.py` (usar `evaluar_dia_multimodelo`)
- Test: `tests/test_consenso.py`

**Interfaces:**
- Consumes: `surf.score.Hora`, `surf.score.evaluar_hora`, `surf.score.DiaEvaluado`, `surf.spots.Spot`
- Produces:
  - `HoraMultiModelo` — dataclass frozen: `t: datetime`, `es_de_dia: bool`, `por_modelo: dict[str, Hora]`
  - `consensuar(hmm: HoraMultiModelo, spot: Spot) -> tuple[Hora, str, int]` — devuelve la `Hora` mediana, el nivel de concordancia (`"alta"`/`"media"`/`"baja"`) y cuántos modelos pasaron el gate
  - `evaluar_dia_multimodelo(hmms: list[HoraMultiModelo], spot: Spot, fecha: date) -> DiaEvaluado`
  - `MODELOS_VIENTO = ["gfs_seamless", "icon_seamless", "ecmwf_ifs025"]`
  - `MODELOS_OLAS = ["best_match", "gwam", "meteofrance_wave"]`
  - `MINIMO_MODELOS_DE_ACUERDO = 2`
- `DiaEvaluado` gana el campo `concordancia: str = "alta"` (con default, para no romper los tests existentes)

- [ ] **Step 1: Escribir los tests que fallan**

`tests/test_consenso.py`:
```python
from datetime import date, datetime

import pytest

from surf.consenso import (HoraMultiModelo, consensuar,
                           evaluar_dia_multimodelo)
from surf.score import Hora
from tests.test_score_gate import SPOT


def _hora(altura=2.0, periodo=13.0, viento=5.0, direccion=157.0, viento_dir=320.0):
    return Hora(t=datetime(2026, 8, 21, 9), swell_altura=altura,
                swell_periodo=periodo, swell_direccion=direccion,
                viento_kmh=viento, viento_direccion=viento_dir, es_de_dia=True)


def _hmm(modelos, hora=9):
    return HoraMultiModelo(t=datetime(2026, 8, 21, hora), es_de_dia=True,
                           por_modelo=modelos)


def test_los_tres_de_acuerdo_dan_concordancia_alta():
    hmm = _hmm({"a": _hora(), "b": _hora(), "c": _hora()})
    _, nivel, n = consensuar(hmm, SPOT)
    assert nivel == "alta"
    assert n == 3


def test_dos_de_tres_dan_concordancia_media():
    # El tercero ve viento onshore fuerte
    hmm = _hmm({"a": _hora(), "b": _hora(),
                "c": _hora(viento=30.0, viento_dir=140.0)})
    _, nivel, n = consensuar(hmm, SPOT)
    assert nivel == "media"
    assert n == 2


def test_uno_de_tres_da_concordancia_baja():
    malo = _hora(altura=0.3, periodo=5.0)
    hmm = _hmm({"a": _hora(), "b": malo, "c": malo})
    _, nivel, n = consensuar(hmm, SPOT)
    assert nivel == "baja"
    assert n == 1


def test_la_hora_consensuada_usa_la_mediana():
    hmm = _hmm({"a": _hora(altura=1.5), "b": _hora(altura=2.0),
                "c": _hora(altura=3.0)})
    hora, _, _ = consensuar(hmm, SPOT)
    assert hora.swell_altura == pytest.approx(2.0)


def test_la_mediana_ignora_el_modelo_desviado():
    # Un modelo dice 30 km/h de viento y los otros dos 5
    hmm = _hmm({"a": _hora(viento=5.0), "b": _hora(viento=5.0),
                "c": _hora(viento=30.0)})
    hora, _, _ = consensuar(hmm, SPOT)
    assert hora.viento_kmh == pytest.approx(5.0)


def test_un_solo_modelo_funciona_igual():
    hmm = _hmm({"a": _hora()})
    hora, nivel, n = consensuar(hmm, SPOT)
    assert n == 1
    assert hora.swell_altura == pytest.approx(2.0)


def test_la_hora_con_concordancia_baja_no_cuenta_para_el_dia():
    malo = _hora(altura=0.3, periodo=5.0)
    hmms = [_hmm({"a": _hora(), "b": malo, "c": malo}, hora=h)
            for h in (8, 9, 10)]
    d = evaluar_dia_multimodelo(hmms, SPOT, date(2026, 8, 21))
    assert d.es_bueno is False


def test_tres_horas_con_los_modelos_de_acuerdo_hacen_un_dia_bueno():
    hmms = [_hmm({"a": _hora(), "b": _hora(), "c": _hora()}, hora=h)
            for h in (8, 9, 10)]
    d = evaluar_dia_multimodelo(hmms, SPOT, date(2026, 8, 21))
    assert d.es_bueno is True
    assert d.concordancia == "alta"


def test_el_dia_reporta_la_peor_concordancia_de_su_bloque():
    disidente = _hora(viento=30.0, viento_dir=140.0)
    hmms = [
        _hmm({"a": _hora(), "b": _hora(), "c": _hora()}, hora=8),
        _hmm({"a": _hora(), "b": _hora(), "c": disidente}, hora=9),
        _hmm({"a": _hora(), "b": _hora(), "c": _hora()}, hora=10),
    ]
    d = evaluar_dia_multimodelo(hmms, SPOT, date(2026, 8, 21))
    assert d.es_bueno is True
    assert d.concordancia == "media"


def test_el_motivo_de_rechazo_por_desacuerdo_es_explicito():
    malo = _hora(altura=0.3, periodo=5.0)
    hmms = [_hmm({"a": _hora(), "b": malo, "c": malo}, hora=h) for h in (8, 9, 10)]
    d = evaluar_dia_multimodelo(hmms, SPOT, date(2026, 8, 21))
    assert "modelos" in (d.motivo_principal or "")
```

- [ ] **Step 2: Correr los tests y verificar que fallan**

Run: `.venv/bin/pytest tests/test_consenso.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'surf.consenso'`

- [ ] **Step 3: Agregar el campo `concordancia` a `DiaEvaluado` en `surf/score.py`**

En la definición de la dataclass, agregar como último campo:

```python
    concordancia: str = "alta"
```

Va con default para que las construcciones existentes en `evaluar_dia` sigan funcionando sin cambios.

- [ ] **Step 4: Implementar `surf/consenso.py`**

```python
"""Consenso entre modelos meteorologicos.

Reemplaza la funcion que cumple Windguru —comparar GFS, ICON y ECMWF lado a
lado— calculandola en vez de mostrarla. Windguru no se puede usar como fuente:
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
```

- [ ] **Step 5: Correr los tests y verificar que pasan**

Run: `.venv/bin/pytest tests/test_consenso.py -v`
Expected: PASS, 10 tests

- [ ] **Step 6: Pasar `fetch.py` a multi-modelo**

Agregar a `surf/fetch.py`, sin borrar `obtener_horas` (el backtest la sigue usando):

```python
def obtener_horas_multimodelo(spot: Spot, dias: int = 7,
                              sesion=None) -> dict[date, list["HoraMultiModelo"]]:
    """Trae el pronostico de varios modelos y los devuelve agrupados por hora.

    Los modelos de olas y de viento se emparejan por posicion. Si un modelo no
    tiene cobertura en el spot, Open-Meteo no devuelve su columna y ese modelo
    se omite; el consenso se calcula con los que si respondieron.
    """
    from surf.consenso import MODELOS_OLAS, MODELOS_VIENTO, HoraMultiModelo

    base = {"latitude": spot.lat, "longitude": spot.lon,
            "timezone": "auto", "forecast_days": dias}

    marine = _pedir(URL_MARINE, {**base, "hourly": ",".join(_CAMPOS_MARINE),
                                 "models": ",".join(MODELOS_OLAS)}, sesion)
    clima = _pedir(URL_CLIMA, {**base, "hourly": ",".join(_CAMPOS_CLIMA),
                               "models": ",".join(MODELOS_VIENTO),
                               "daily": "sunrise,sunset",
                               "wind_speed_unit": "kmh"}, sesion)

    return _combinar_multimodelo(marine, clima, MODELOS_OLAS, MODELOS_VIENTO)
```

Y la función pura que las une:

```python
def _sufijo(campo: str, modelo: str, disponibles: dict) -> str | None:
    """Open-Meteo sufija cada columna con el nombre del modelo.

    La Marine API antepone 'marine_' a best_match; por eso se prueban las
    dos formas en vez de asumir una.
    """
    for candidato in (f"{campo}_{modelo}", f"{campo}_marine_{modelo}"):
        if candidato in disponibles:
            return candidato
    return None


def _combinar_multimodelo(marine: dict, clima: dict, modelos_olas: list[str],
                          modelos_viento: list[str]) -> dict:
    """Une las respuestas multi-modelo. Funcion pura."""
    from surf.consenso import HoraMultiModelo

    hm, hc, dc = marine.get("hourly", {}), clima.get("hourly", {}), clima.get("daily", {})

    if "time" not in hm or "time" not in hc:
        raise ErrorDatos("falta la serie 'time' en alguna respuesta")
    if hm["time"] != hc["time"]:
        raise ErrorDatos("las series horarias de marine y clima no alinean")
    if not dc.get("sunrise") or not dc.get("sunset"):
        raise ErrorDatos("faltan los datos de salida y puesta del sol")

    # Emparejar modelos de olas con modelos de viento por posicion.
    pares = []
    for i, mo in enumerate(modelos_olas):
        cols_olas = {c: _sufijo(c, mo, hm) for c in _CAMPOS_MARINE}
        if any(v is None for v in cols_olas.values()):
            continue
        mv = modelos_viento[min(i, len(modelos_viento) - 1)]
        cols_viento = {c: _sufijo(c, mv, hc) for c in _CAMPOS_CLIMA}
        if any(v is None for v in cols_viento.values()):
            continue
        pares.append((f"{mo}+{mv}", cols_olas, cols_viento))

    if not pares:
        raise ErrorDatos("ningun modelo devolvio las columnas esperadas")

    sol = {date.fromisoformat(d): (datetime.fromisoformat(dc["sunrise"][i]),
                                   datetime.fromisoformat(dc["sunset"][i]))
           for i, d in enumerate(dc["time"])}

    por_dia: dict = {}
    for i, t_str in enumerate(hm["time"]):
        t = datetime.fromisoformat(t_str)
        if t.date() not in sol:
            continue
        amanecer, ocaso = sol[t.date()]
        es_de_dia = amanecer <= t <= ocaso

        por_modelo = {}
        for nombre, cols_olas, cols_viento in pares:
            vals = ([hm[c][i] for c in cols_olas.values()]
                    + [hc[c][i] for c in cols_viento.values()])
            if any(v is None for v in vals):
                continue
            por_modelo[nombre] = Hora(
                t=t,
                swell_altura=float(hm[cols_olas["swell_wave_height"]][i]),
                swell_periodo=float(hm[cols_olas["swell_wave_period"]][i]),
                swell_direccion=float(hm[cols_olas["swell_wave_direction"]][i]),
                viento_kmh=float(hc[cols_viento["wind_speed_10m"]][i]),
                viento_direccion=float(hc[cols_viento["wind_direction_10m"]][i]),
                es_de_dia=es_de_dia,
            )

        if por_modelo:
            por_dia.setdefault(t.date(), []).append(
                HoraMultiModelo(t=t, es_de_dia=es_de_dia, por_modelo=por_modelo)
            )

    return por_dia
```

- [ ] **Step 7: Agregar tests de `_combinar_multimodelo`**

Agregar a `tests/test_fetch.py`:

```python
def test_combinar_multimodelo_arma_una_hora_por_modelo():
    from surf.fetch import _combinar_multimodelo

    marine = {"hourly": {
        "time": ["2026-08-21T09:00"],
        "swell_wave_height_marine_best_match": [1.8],
        "swell_wave_period_marine_best_match": [14.0],
        "swell_wave_direction_marine_best_match": [200.0],
        "swell_wave_height_gwam": [1.6],
        "swell_wave_period_gwam": [13.5],
        "swell_wave_direction_gwam": [198.0],
    }}
    clima = {"hourly": {
        "time": ["2026-08-21T09:00"],
        "wind_speed_10m_gfs_seamless": [14.9],
        "wind_direction_10m_gfs_seamless": [95.0],
        "wind_speed_10m_icon_seamless": [7.0],
        "wind_direction_10m_icon_seamless": [97.0],
    }, "daily": {"time": ["2026-08-21"], "sunrise": ["2026-08-21T06:45"],
                 "sunset": ["2026-08-21T18:20"]}}

    por_dia = _combinar_multimodelo(
        marine, clima, ["best_match", "gwam"], ["gfs_seamless", "icon_seamless"])
    hmm = por_dia[date(2026, 8, 21)][0]
    assert len(hmm.por_modelo) == 2
    assert hmm.es_de_dia is True


def test_combinar_multimodelo_falla_si_no_hay_ningun_modelo():
    from surf.fetch import _combinar_multimodelo

    marine = {"hourly": {"time": ["2026-08-21T09:00"]}}
    clima = {"hourly": {"time": ["2026-08-21T09:00"]},
             "daily": {"time": ["2026-08-21"], "sunrise": ["2026-08-21T06:45"],
                       "sunset": ["2026-08-21T18:20"]}}
    with pytest.raises(ErrorDatos, match="ningun modelo"):
        _combinar_multimodelo(marine, clima, ["best_match"], ["gfs_seamless"])
```

- [ ] **Step 8: Mostrar la concordancia en el mensaje**

En `surf/notify.py`, dentro de `formatear_alerta`, antes de la línea del link:

```python
    _ETIQUETA_CONCORDANCIA = {
        "alta": "Concordancia entre modelos: alta (GFS, ICON y ECMWF coinciden) ✓",
        "media": "Concordancia entre modelos: media (2 de 3 coinciden)",
        "baja": "Concordancia entre modelos: baja",
    }
```

Definir ese dict a nivel de módulo (no dentro de la función) y agregar en `formatear_alerta`, después de la línea de confirmación:

```python
    peor = min((d.concordancia for d in ventana.dias),
               key=lambda n: {"alta": 2, "media": 1, "baja": 0}[n])
    partes.append(_ETIQUETA_CONCORDANCIA[peor])
```

Agregar el test correspondiente a `tests/test_notify.py`:

```python
def test_la_alerta_reporta_la_concordancia_entre_modelos():
    v = detectar_ventanas([dia(21), dia(22)])[0]
    assert "Concordancia entre modelos" in formatear_alerta(v, SPOT)
```

- [ ] **Step 9: Cambiar `run.py` para usar el camino multi-modelo**

En `run.py`, cambiar los imports y la llamada dentro de `correr`:

```python
from surf.consenso import evaluar_dia_multimodelo
from surf.fetch import ErrorDatos, obtener_horas_multimodelo
```

y reemplazar `evaluar_dia(horas, spot, fecha)` por `evaluar_dia_multimodelo(horas, spot, fecha)`.
En `main`, pasar `obtener_horas_multimodelo` en lugar de `obtener_horas`.

Actualizar el helper `_traer_bueno` de `tests/test_run.py` para que devuelva `HoraMultiModelo` con tres modelos idénticos.

- [ ] **Step 10: Verificar contra la API real**

```bash
.venv/bin/python - <<'EOF'
from pathlib import Path
from surf.consenso import evaluar_dia_multimodelo, consensuar
from surf.fetch import obtener_horas_multimodelo
from surf.spots import cargar_spots

spot = [s for s in cargar_spots("spots.yaml") if s.id == "chapadmalal"][0]
por_dia = obtener_horas_multimodelo(spot, dias=3)
primera = next(iter(sorted(por_dia.items())))[1][12]
print("modelos activos:", list(primera.por_modelo.keys()))
for nombre, h in primera.por_modelo.items():
    print(f"  {nombre:35} {h.swell_altura:.2f}m @ {h.swell_periodo:.1f}s  viento {h.viento_kmh:.1f}")
for fecha, hmms in sorted(por_dia.items()):
    d = evaluar_dia_multimodelo(hmms, spot, fecha)
    print(f"{fecha}  score {d.score:5.1f}  concordancia {d.concordancia:6}  "
          f"{'BUENO' if d.es_bueno else d.motivo_principal}")
EOF
```
Expected: al menos 2 modelos activos y la discrepancia visible entre ellos. Si sale un solo modelo, revisar los sufijos de columna en `_sufijo`.

- [ ] **Step 11: Correr la suite completa**

Run: `.venv/bin/pytest tests/ -v`
Expected: PASS, todo

- [ ] **Step 12: Commit**

```bash
git add surf/consenso.py surf/fetch.py surf/score.py surf/notify.py run.py tests/
git commit -m "feat: consenso multi-modelo en reemplazo de Windguru"
```

---

### Task 12: Backtest y calibración

Esta tarea decide si el detector sirve. **No se despliega nada hasta que el backtest pase sus criterios.**

**Files:**
- Create: `backtest.py`
- Create: `docs/resultados-backtest.md`
- Test: `tests/test_backtest.py`

**Interfaces:**
- Consumes: `surf.spots.Spot`, `surf.score.evaluar_dia`, `surf.alert.detectar_ventanas`, `surf.fetch._combinar`
- Produces:
  - `obtener_historico(spot: Spot, desde: date, hasta: date) -> dict[date, list[Hora]]`
  - `analizar(spot: Spot, por_dia: dict) -> dict` — devuelve `{"ventanas_por_anio": float, "por_mes": dict[int, int], "top_dias": list, "total_ventanas": int}`
  - `RANGO_SANO = (10, 25)`

- [ ] **Step 1: Escribir los tests que fallan**

`tests/test_backtest.py`:
```python
from datetime import date, datetime, timedelta

import pytest

from backtest import RANGO_SANO, analizar, veredicto
from surf.score import Hora
from tests.test_score_gate import SPOT


def _dia_de_horas(f, buena):
    alt, per, vd = (2.0, 14.0, 320.0) if buena else (0.4, 5.0, 140.0)
    return [Hora(t=datetime(f.year, f.month, f.day, x), swell_altura=alt,
                 swell_periodo=per, swell_direccion=157.0,
                 viento_kmh=5.0 if buena else 30.0, viento_direccion=vd,
                 es_de_dia=True) for x in range(7, 13)]


def test_analizar_cuenta_las_ventanas():
    inicio = date(2024, 1, 1)
    # Dos dias buenos seguidos, despues 10 malos, repetido
    por_dia = {}
    for n in range(24):
        f = inicio + timedelta(days=n)
        por_dia[f] = _dia_de_horas(f, buena=(n % 12) in (0, 1))
    r = analizar(SPOT, por_dia)
    assert r["total_ventanas"] == 2


def test_analizar_reporta_la_distribucion_mensual():
    inicio = date(2024, 6, 1)
    por_dia = {inicio + timedelta(days=n): _dia_de_horas(inicio + timedelta(days=n), True)
               for n in range(5)}
    r = analizar(SPOT, por_dia)
    assert r["por_mes"][6] > 0


def test_veredicto_marca_filtro_estrangulado():
    assert veredicto({"ventanas_por_anio": 2.0}) == "estrangulado"


def test_veredicto_marca_ruido():
    assert veredicto({"ventanas_por_anio": 80.0}) == "ruido"


def test_veredicto_sano_en_el_rango():
    assert veredicto({"ventanas_por_anio": 15.0}) == "sano"
    assert veredicto({"ventanas_por_anio": float(RANGO_SANO[0])}) == "sano"
    assert veredicto({"ventanas_por_anio": float(RANGO_SANO[1])}) == "sano"
```

- [ ] **Step 2: Correr los tests y verificar que fallan**

Run: `.venv/bin/pytest tests/test_backtest.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'backtest'`

- [ ] **Step 3: Implementar `backtest.py`**

```python
"""Validacion historica del detector.

Corre exactamente el mismo codigo de scoring que produccion sobre datos de
archivo. Si probara un camino distinto, no validaria nada.

Criterios objetivos:
  - Volumen: entre 10 y 25 ventanas por spot por anio.
  - Estacionalidad: la distribucion mensual tiene que coincidir con la
    temporada documentada del spot.
"""
import sys
from collections import Counter
from datetime import date
from pathlib import Path

import requests

from surf.alert import detectar_ventanas
from surf.fetch import _CAMPOS_CLIMA, _CAMPOS_MARINE, ErrorDatos, _combinar
from surf.score import evaluar_dia
from surf.spots import Spot, cargar_spots

URL_MARINE_ARCHIVO = "https://marine-api.open-meteo.com/v1/marine"
URL_CLIMA_ARCHIVO = "https://archive-api.open-meteo.com/v1/archive"
RANGO_SANO = (10, 25)
TIMEOUT_S = 120


def obtener_historico(spot: Spot, desde: date, hasta: date) -> dict:
    """Trae datos de archivo para el rango indicado."""
    base = {"latitude": spot.lat, "longitude": spot.lon, "timezone": "auto",
            "start_date": desde.isoformat(), "end_date": hasta.isoformat()}

    marine = requests.get(URL_MARINE_ARCHIVO,
                          params={**base, "hourly": ",".join(_CAMPOS_MARINE)},
                          timeout=TIMEOUT_S).json()
    clima = requests.get(URL_CLIMA_ARCHIVO,
                         params={**base, "hourly": ",".join(_CAMPOS_CLIMA),
                                 "daily": "sunrise,sunset", "wind_speed_unit": "kmh"},
                         timeout=TIMEOUT_S).json()
    for r, nombre in ((marine, "marine"), (clima, "clima")):
        if r.get("error"):
            raise ErrorDatos(f"archivo {nombre}: {r.get('reason')}")
    return _combinar(marine, clima)


def analizar(spot: Spot, por_dia: dict) -> dict:
    """Corre el detector sobre el historico y resume el resultado."""
    dias = [evaluar_dia(horas, spot, fecha) for fecha, horas in sorted(por_dia.items())]
    ventanas = detectar_ventanas(dias)

    anios = len({f.year for f in por_dia}) or 1
    por_mes = Counter(v.desde.month for v in ventanas)
    top = sorted((d for d in dias if d.es_bueno), key=lambda d: -d.score)[:10]

    return {
        "spot_id": spot.id,
        "total_ventanas": len(ventanas),
        "ventanas_por_anio": len(ventanas) / anios,
        "por_mes": dict(por_mes),
        "top_dias": [(d.fecha.isoformat(), round(d.score, 1)) for d in top],
        "temporada_declarada": spot.temporada,
    }


def veredicto(resultado: dict) -> str:
    """Clasifica el volumen de alertas."""
    v = resultado["ventanas_por_anio"]
    if v < RANGO_SANO[0]:
        return "estrangulado"
    if v > RANGO_SANO[1]:
        return "ruido"
    return "sano"


def coincide_la_temporada(resultado: dict) -> bool:
    """Verifica que la mayoria de las ventanas caigan en la temporada declarada."""
    por_mes = resultado["por_mes"]
    total = sum(por_mes.values())
    if total == 0:
        return False
    en_temporada = sum(n for m, n in por_mes.items() if m in resultado["temporada_declarada"])
    return en_temporada / total >= 0.6


def main() -> int:
    desde, hasta = date(2023, 1, 1), date(2025, 12, 31)
    problemas = 0

    for spot in cargar_spots(Path("spots.yaml")):
        try:
            r = analizar(spot, obtener_historico(spot, desde, hasta))
        except Exception as e:  # noqa: BLE001
            print(f"{spot.id:20} ERROR: {e}")
            problemas += 1
            continue

        v = veredicto(r)
        temp = "ok" if coincide_la_temporada(r) else "NO COINCIDE"
        marca = "  " if v == "sano" and temp == "ok" else "!!"
        if marca == "!!":
            problemas += 1
        print(f"{marca} {spot.id:20} {r['ventanas_por_anio']:5.1f}/anio  "
              f"volumen={v:12} temporada={temp}")
        print(f"     meses: {sorted(r['por_mes'].items())}")
        print(f"     top 3: {r['top_dias'][:3]}")

    print(f"\n{problemas} spots requieren ajuste.")
    return 1 if problemas else 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Correr los tests y verificar que pasan**

Run: `.venv/bin/pytest tests/test_backtest.py -v`
Expected: PASS, 5 tests

- [ ] **Step 5: Correr el backtest real sobre 2023-2025**

Run: `.venv/bin/python backtest.py | tee docs/resultados-backtest.md`
Expected: una línea por spot. Tarda varios minutos (13 spots × 3 años de datos horarios).

- [ ] **Step 6: Calibrar los spots marcados con `!!`**

Para cada spot fuera de rango, ajustar **`spots.yaml`, nunca `score.py`**:

| Síntoma | Ajuste |
|---|---|
| `volumen=estrangulado` (<10/año) | Bajar `min_periodo` en 0.5 s, o ensanchar `swell.ventana` en 10° por lado |
| `volumen=ruido` (>25/año) | Subir `min_periodo` en 0.5 s, o subir `min_altura` en 0.1 m |
| `temporada=NO COINCIDE` | La ventana de swell está mal orientada. Volver a la investigación del spot: probablemente `swell.ideal` o `costa_mira` estén mal |

Después de cada ajuste, volver a correr el backtest de ese spot. Registrar cada cambio y su motivo en `docs/resultados-backtest.md`.

**Un `temporada=NO COINCIDE` no se arregla tocando umbrales.** Es señal de un error de investigación y hay que corregir el perfil en el origen.

- [ ] **Step 7: Ground truth con el usuario**

Presentarle los `top_dias` del spot que mejor conozca (probablemente Chapadmalal o La Barra) y pedirle que marque cuáles fueron realmente buenos. Registrar la respuesta en `docs/resultados-backtest.md` y ajustar umbrales según lo que diga.

- [ ] **Step 8: Cross-check contra surf-forecast**

Para 3 spots, comparar altura y período de Open-Meteo contra lo que muestra surf-forecast el mismo día. Si aparece un sesgo sistemático mayor a ~20%, anotarlo en `docs/resultados-backtest.md` y compensarlo ajustando `min_altura` de ese spot.

- [ ] **Step 9: Commit**

```bash
git add backtest.py docs/resultados-backtest.md spots.yaml tests/test_backtest.py
git commit -m "feat: backtest historico y calibracion de los perfiles"
```

---

## Self-Review

**Cobertura del spec:**

| Requisito del spec | Tarea |
|---|---|
| Open-Meteo como fuente, no scraping | 7 |
| Gate duro de 6 condiciones | 4 |
| Score 0-100 separado del gate | 5 |
| Umbrales por spot, no globales | 2, 3 |
| Viento relativo a `costa_mira` | 1, 4 |
| `max_altura` (spot que cierra) | 2, 4 |
| `min_periodo` por tipo de pico | 3 |
| Campo `confianza` | 2, 9 |
| Bloque mínimo de 3 horas | 6 |
| Solo horas de luz | 4, 7 |
| Ventana de 2+ días | 8 |
| Persistencia contra corrida previa | 8 |
| Anti-repetición | 8 |
| Digest semanal, siempre enviado | 9, 10 |
| Investigación de 3 fuentes cruzadas | 3 |
| Windguru descartado, función replicada vía multi-modelo | 11 |
| Gate en 2 de 3 modelos, valores por mediana | 11 |
| Concordancia reportada en la alerta | 11 |
| Backtest 2023-2025 con criterios objetivos | 12 |
| Ground truth del usuario | 12 |
| Cross-check contra surf-forecast | 12 |
| Tests unitarios de score | 4, 5, 6 |
| GitHub Actions, 7 AM ARG | 10 |
| `state.json` versionado | 8, 10 |
| No escribir estado en corrida fallida | 10 |
| Un spot falla, los demás siguen | 10 |
| Mitigación del corte por 60 días de inactividad | 10 |
| Costo cero | Global Constraints |
| Marea fuera de alcance | — (no se implementa, por diseño) |

Sin huecos.

**Consistencia de tipos:** `Hora` se define en Task 4 y la consumen 6, 7, 10, 11. `DiaEvaluado` se define en 6 y la consumen 8, 9, 10, 11. `Ventana` se define en 8 y la consumen 9, 10. `Spot`/`Swell` se definen en 2 y las consumen 3-11. `_combinar` se define en 7 y la reusa 11. `evaluar_dia(horas, spot, fecha)` mantiene la misma firma en 6, 10 y 11.
