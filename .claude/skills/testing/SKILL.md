---
name: testing
description: Cómo escribir y correr tests en FinanzIAs — fixtures de conftest, mockeo de yfinance, DB en memoria, markers. Usar al agregar o modificar tests, o cuando un test falla por tocar red/DB real o por estado filtrado de settings.
---

# Testing — FinanzIAs

Suite con pytest. Comando canónico (ver `finanzias-conventions`):
```
python -m pytest tests/ -ra -m "not network" --tb=short
```
**La suite sola NO define "done"** — son cuatro comandos, y esa distinción costó plata de
atención **dos veces**: ver *Antes de declarar "done"*, abajo. El cuarto
(`scripts/run_suite_sin_estado_vivo.py`) corre esta misma suite con `HOME`/`USERPROFILE` en un
directorio vacío, o sea sin `~/.finanzias/settings.json`: es el que caza un test que lea estado
vivo de la máquina y por lo tanto pase acá y falle en el CI (tarea 176).
Config en `pyproject.toml`: `testpaths=["tests"]`, `python_files=["test_*.py"]`, `addopts="-ra --strict-markers"`. **`--strict-markers`** = un marker no declarado hace fallar la corrida; declarar markers nuevos en `pyproject.toml`.

## Reglas de oro

1. **Nunca tocar la red.** yfinance es lento, rate-limited y no determinístico. Los unit tests no deben pegar a Yahoo.
2. **Nunca tocar `finanzias.db` real.** Usar la DB en memoria del fixture.
3. **Determinismo.** Nada de `datetime.now()` sin control ni random sin seed. Usar `ohlcv_factory` (tiene seed).

## Fixtures disponibles (`tests/conftest.py`)

- **`test_db`** — reapunta `database.models.ENGINE`/`SessionLocal` a SQLite `:memory:` y crea todas las tablas (incluye las de `paper_trading.models`). Úsalo en cualquier test que toque la DB:
  ```python
  def test_algo(test_db):
      with session_scope() as s:
          ...
  ```
- **`mock_yfinance`** — parchea `data.yahoo_finance.yf` con un `MagicMock` y lo devuelve para configurar returns:
  ```python
  def test_precio(mock_yfinance):
      mock_yfinance.Ticker.return_value.fast_info.last_price = 150.0
  ```
- **`ohlcv_factory`** — genera un DataFrame OHLCV determinístico (random-walk con seed):
  ```python
  def test_indicador(ohlcv_factory):
      df = ohlcv_factory(rows=300, start_price=100, seed=42)
  ```
- **`_disable_settings_persistence`** (autouse) — redirige `settings.json` a un tmp por test y recarga el singleton `settings`, así cada test arranca con defaults limpios y no filtra config del host. No hace falta pedirlo; ya corre solo.

## Markers

- `network` — tests que pegan a Yahoo de verdad. Se **saltean** en la corrida normal (`-m "not network"`). Marcarlos: `@pytest.mark.network`.
- `slow` — tests lentos; deseleccionar con `-m "not slow"`.
- Cualquier marker nuevo va declarado en `pyproject.toml` (por `--strict-markers`).

## Convención de escritura

- Un archivo `tests/test_<modulo>.py` por módulo (ej. `tests/test_leads.py`, `tests/test_valuation.py`).
- Funciones puras → tests puros sin fixtures. Lógica que toca DB → `test_db`. Lógica que toca yfinance → `mock_yfinance` (o un `MagicMock` propio).
- Si un test necesita red de verdad, marcalo `@pytest.mark.network` (no corre en la suite estándar) — no lo dejes pegando a Yahoo en un unit test.

## Antes de declarar "done"

Son **cuatro** comandos, todos en **Windows** (entorno real, Anaconda), y los cuatro tienen que pasar:

```
python -m pytest tests/ -ra -m "not network" --tb=short
python -m ruff check .
python -m ruff format --check .
python scripts/run_suite_sin_estado_vivo.py
```

Reportar el conteo (`NNN passed, M skipped`) en el cuerpo del commit (ver skill `git-workflow`).

**Por qué ruff está acá y no sólo en el CI (tarea 106).** Hasta el 2026-09-03 el done era la
suite sola. El 2026-09-02 el job `lint` del CI quedó en **rojo** —15 errores de ruff y 18
archivos sin formatear, introducidos por los tests y el cableado de las tareas 74, 76, 81, 83,
85, 86 y 92— y **trece tareas se cerraron declarando "suite verde"** sin que nadie se enterara.
No estaban mintiendo: la suite **estaba** verde. El criterio era el que estaba incompleto, y el
único lugar donde ruff corría era un CI que nadie lee. Es el mismo diagnóstico de la tarea 65
(*"el pipeline nunca estuvo en verde, así que no avisa de nada"*), cuatro días después de
cerrarla.

Si ruff falla: `ruff check --fix .` y `ruff format .`, **revisando el diff** — no es
auto-aceptar. El procedimiento y el pin de versión están en `requirements-dev.txt:16`.

**Por qué el cuarto comando está acá, que es el mismo defecto otra vez (tarea 176).** El
2026-09-09 el job `pytest` quedó rojo **en el mismo commit que shipeó el guard de la tarea
130**, y **36 tareas** se cerraron declarando *«suite Windows verde»* — que era **verdad**. 35
corridas en rojo, y lo reportó Chapa, no el proceso. La causa: el test de mutación de ese guard
leía `~/.finanzias/settings.json` para armar su línea base, y **en la máquina de Chapa ese
archivo existe**; en el CI no, así que la base caía al default del schema y la mutación quedaba
en no-op. O sea: un defecto que los tres comandos **no podían ver por diseño**, porque los tres
corren en una máquina con estado.

`scripts/run_suite_sin_estado_vivo.py` corre esta misma suite con `HOME` y `USERPROFILE`
apuntando a un directorio **vacío** — las dos variables, porque en Windows `Path.home()`
resuelve por `USERPROFILE` y setear sólo `HOME` no aísla nada. El script se **niega a reportar**
(exit 2) si el aislamiento no funcionó, en vez de dar un verde falso.

Dos cosas prácticas al leer su salida:

* Su conteo difiere del primero en **1 skip**, y eso es correcto: el test que compara los
  espejos contra el settings vivo se saltea cuando no hay con qué comparar.
* **No cubre** lo que sólo rompe en Linux de verdad (separadores de path, permisos, locale,
  `case` del filesystem). Eso lo sigue viendo únicamente el CI. Cubre la clase *«estado vivo de
  la máquina»*, que es la que mordió.

Para reproducir un caso puntual sin correr la suite entera, acepta argumentos de pytest:
`python scripts/run_suite_sin_estado_vivo.py tests/test_x.py -q`.

**Corolario al escribir tests:** si un test necesita leer estado vivo de la máquina —y a veces
es legítimo, como el guard de los espejos de la 130— tiene que **saltearse** cuando no está, no
degradar a otra cosa. Degradar en silencio es lo que produjo las 35 corridas.
