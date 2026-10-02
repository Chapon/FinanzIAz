# Auditoría — dependencias — 2026-10-02

Tarea **275**, primera corrida del área `dependencias` (categoría K, creada por la 274). READ-ONLY. Kill-criteria congelado en `docs/auditoria_tanda_killcriteria_2026-10-02.md` §7.

## 1. Alcance real

**Mirado:**
- **Los imports de terceros** de todos los `.py` versionados (AST, módulos de primer nivel fuera de la stdlib y de los paquetes locales), contra `requirements.txt` y `requirements-dev.txt`.
- **`requirements.lock`** (100 paquetes) contra lo instalado en la **Anaconda** de Chapa (`C:\Users\chapa\anaconda3`, Python 3.12.4, donde corre la app) y en el **`.venv`** (Python 3.12.4).
- **Lo instalado en la Anaconda** contra los especificadores de `requirements.txt` (con `packaging`).
- **Los cuatro jobs del CI** (`.github/workflows/ci.yml`: Python 3.11, instala `requirements.txt` sin lock) y su última corrida (`37055857658`, `5906efe`), leída por la API pública de Actions.
- **`pip-audit`** sobre las versiones **de la Anaconda** de 16 paquetes del runtime, corrido desde el `.venv`.

**NO mirado:**
- Los 397 paquetes de la Anaconda que la app no usa.
- Las dependencias transitivas más allá de `urllib3`/`certifi`.

## 2. Hallazgos

### [K-2] El entorno donde corre la app no es el que describe el lock ni el que prueba el CI: tres entornos, tres juegos de versiones
Severidad: **MEDIUM** · Confianza: **ALTA**

**Evidencia:**
- El encabezado de `requirements.lock` dice *«Python: 3.12.4 | packaged by Anaconda»* (generado el 2026-07-11). Pero el lock coincide **exacto** con el `.venv` y la Anaconda **difiere en 75 de sus 100 paquetes**. Siete son de runtime (lock → Anaconda):

| paquete | lock | Anaconda |
|---|---|---|
| `pyarrow` | 25.0.0 | 14.0.2 |
| `sqlalchemy` | 2.0.51 | 2.0.30 |
| `matplotlib` | 3.11.0 | 3.8.4 |
| `requests` | 2.34.2 | 2.32.2 |
| `reportlab` | 5.0.0 | 4.5.0 |
| `openpyxl` | 3.1.5 | 3.1.2 |
| `alembic` | 1.18.5 | 1.18.4 |

- El CI corre **Python 3.11** e instala `requirements.txt` sin lock, o sea la última versión que permiten los rangos.
- El núcleo sí coincide en los tres: numpy 1.26.4, pandas 2.3.3, scikit-learn 1.4.2, yfinance 1.4.1, xgboost 3.2.0, PyQt6 6.7.1.

**Razonamiento:** el *done* (regla 1 de `CLAUDE.md`) se mide en la Anaconda, y eso está bien, pero el lock no la reproduce y el CI tampoco. Un defecto que dependa de la versión de `pyarrow` o de `sqlalchemy` sólo aparece en una de las tres.

**¿Por qué no antes?** (b): el área no existía. La memoria del proyecto ya registraba la divergencia Anaconda/`.venv` en el conteo de tests, pero no como hallazgo con tarea.

**Acción:** que el lock se genere **desde la Anaconda** (o que el encabezado diga de qué entorno sale), y que el CI corra con el lock o declare la diferencia.

→ tarea **284**.

### [K-3] La Anaconda viola el mínimo declarado de `pyarrow` (14.0.2 contra `>=16.0`), y pyarrow es el backend vivo del cache de históricos
Severidad: **MEDIUM** · Confianza: **ALTA**

**Evidencia:**
- Chequeo de especificadores sobre la Anaconda: el **único** paquete fuera de rango es `pyarrow 14.0.2`, contra `pyarrow>=16.0` (`requirements.txt:43`).
- El settings vivo tiene `historical_cache_backend = "parquet"`, con 837 archivos en `data/parquet/`.

**Impacto:** el cache de producción (ARQ1) corre sobre una versión que el proyecto declara no soportada y que el CI nunca prueba.

**Acción:** subir pyarrow en la Anaconda a una versión ≥16 compatible con `numpy<2`, verificando la suite; o bajar el mínimo con un motivo escrito.

→ tarea **284**.

### [K-4] Vulnerabilidades conocidas en cuatro paquetes del runtime de la Anaconda, invisibles para el `pip-audit` del CI
Severidad: **MEDIUM** · Confianza: **ALTA** en el dato, **BAJA** en la explotabilidad

**Evidencia:** `pip-audit` sobre las versiones de la Anaconda encuentra 21 avisos en 4 paquetes:

| paquete | versión | aviso | se arregla en |
|---|---|---|---|
| `pyarrow` | 14.0.2 | PYSEC-2024-161 | 17.0.0 |
| `requests` | 2.32.2 | PYSEC-2026-1872, -2275 | 2.32.4 / 2.33.0 |
| `scikit-learn` | 1.4.2 | PYSEC-2024-110 | 1.5.0, que entra en el pin `<1.8` |
| `urllib3` | 2.2.2 | ocho avisos | 2.5.0 a 2.8.0 |

El job `pip-audit` del CI dio `success` en la última corrida, porque audita **lo que instala el CI**, no lo que corre en la máquina de Chapa. Además es `continue-on-error`.

**Razonamiento:**
- La explotabilidad acá es baja: los parquets los escribe la propia app (el aviso de pyarrow es sobre datos no confiables), y `requests`/`urllib3` hablan con endpoints conocidos.
- Pero son los paquetes de red de la app que maneja la cuenta.

**Acción:** actualizar en la Anaconda `requests`, `urllib3` y `pyarrow`, y `scikit-learn` a 1.5.x si la suite lo tolera (la 1.8 es la que rompe). Correr `pip-audit` contra el entorno real como parte de la 284.

→ tarea **284**.

### [K-1] `urllib3` se importa a nivel de módulo sin estar declarado
Severidad: **LOW** · Confianza: **ALTA**

**Ubicación:** `data/yahoo_finance.py:31`, `from urllib3.util.retry import Retry`.

**Razonamiento:** llega como dependencia de `requests`, así que hoy siempre está. Pero el código lo usa directo y su versión importa (K-4).

**Acción:** declararlo.

→ tarea **284**.

## 3. Barrido limpio en lo demás

- **Imports opcionales**, todos dentro de `try` con camino alternativo:
  - `anthropic` (`data/catalyst_classifier.py:248`, backend opcional del clasificador);
  - `pytz` (`data/yahoo_finance.py:2494`);
  - `curl_cffi` (`tests/_cortafuegos/cortafuegos_red.py:127`).
- **Todo lo declarado** en `requirements.txt` está instalado en la Anaconda y en el `.venv`.
- **Los pines** (`numpy<2`, `scikit-learn<1.8`, `PyQt6<6.8`) tienen su motivo escrito en `requirements.txt`, y sigue siendo cierto: el stack instalado es el validado. Subirlos es la tarea de *Ideas*.

## 4. Mapeo hallazgo → tarea

| hallazgo | tarea |
|---|---|
| K-1 | 284 |
| K-2 | 284 |
| K-3 | 284 |
| K-4 | 284 |
