"""Tarea 160 (SETTINGS-FANTASMA-2) — los seis flags fantasma, y el séptimo que era ESTADO.

El predicado por AST que shipeó la 154 —*«¿hay algún `settings.get(clave, fallback)` con
una clave que no está en el `SCHEMA`?»*— encontró **siete** más. Seis son configuración
y se declaran acá con **el mismo valor** que su fallback inline (hay un test por clave).
Tres de esos seis gatean decisiones del motor (Gate 2c), y por eso esto no es higiene.

**El séptimo no era una perilla: era estado.** `surprise_last_build` lo escribía el
*scheduler* dentro del `settings.json` de Chapa — el único estado que la app mutaba en el
archivo de perillas, y el mismo que `SettingsManager.save()` vuelca entero. Y era una
**segunda fuente de verdad**: el artefacto ya declara su `_meta.built_at`, así que un
build corrido a mano movía una marca y no la otra, y el scheduler seguía contando la
semana desde una fecha que ya no era la del último build. Ahora la cadencia se lee del
artefacto (`analysis.surprise_score.last_build_iso`) y la clave desaparece del código.

**Una premisa de la 154 era falsa, y acá se corrige.** Esa tarea dijo que los flags sin
schema *«no salían en la pestaña Settings, que se arma del schema»*, y con ese argumento
dejó los tres del Gate 2c sin declarar: exponerlos sería decisión de producto. Medido el
2026-09-10: **`ui/` no menciona `SCHEMA` en ninguna línea** — `settings_tab.py` arma sus
secciones con **listas explícitas** de claves. O sea que declarar en el schema **no**
expone nada en la UI, y la decisión de producto es otra cosa (tarea 162, abierta). Con la
premisa corregida, declarar los seis es un cambio de valor nulo.

**Lo que cambia de comportamiento, declarado:** con la marca en el artefacto, (1) un build
corrido a mano **sí** resetea el reloj, y (2) borrar el artefacto dispara un rebuild en vez
de dejar al scheduler esperando una semana por una marca que sobrevivió al archivo.
"""

from __future__ import annotations

import ast
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from analysis.surprise_score import (
    DEFAULT_BUILD_INTERVAL_DAYS,
    PROFILES_PATH,
    build_due,
    last_build_iso,
)
from config.settings_manager import DEFAULTS, SCHEMA

_REPO = Path(__file__).resolve().parent.parent

# Los seis, con el fallback que tenían escrito al lado del call site. Es la contraprueba
# de que "declarar" no fue "cambiar el valor" — mismo criterio que la 154.
_FALLBACKS_HISTORICOS: dict[str, object] = {
    "paper_catalyst_exit_veto_enabled": False,  # engine.py:898 (Gate 2c)
    "paper_catalyst_veto_min_score": 0.30,  # engine.py:899
    "paper_catalyst_veto_gray_high": 0.50,  # engine.py:900
    "dashboard_refresh_enabled": True,  # scheduler.py (×2)
    "surprise_build_enabled": True,  # scheduler.py
    "surprise_build_interval_days": 7,  # scheduler.py, vía DEFAULT_BUILD_INTERVAL_DAYS
}


# ── (1) declarar no movió ninguna perilla ────────────────────────────────────


@pytest.mark.parametrize(("clave", "fallback"), _FALLBACKS_HISTORICOS.items())
def test_los_seis_estan_en_el_schema_con_SU_valor(clave, fallback):
    """Si el default del schema difiere del fallback que corría, esto **movió** un gate
    del motor o un job del scheduler sin que nadie lo pidiera."""
    assert clave in SCHEMA, f"{clave} no está declarada en el SCHEMA"
    assert DEFAULTS[clave] == fallback, (
        f"{clave}: el schema dice {DEFAULTS[clave]!r} y el fallback era {fallback!r}"
    )


@pytest.mark.parametrize("clave", _FALLBACKS_HISTORICOS)
def test_cada_una_esta_DOCUMENTADA(clave):
    assert SCHEMA[clave].doc and len(SCHEMA[clave].doc) > 40


def test_el_gate_2c_sigue_en_OFF():
    """El claim de `CLAUDE.md` (*«Gate 2c — DEFAULT OFF»*) pasa de ser cierto **por
    coincidencia** a estar contrastado: antes el `False` vivía en un fallback inline que
    nada miraba."""
    assert DEFAULTS["paper_catalyst_exit_veto_enabled"] is False


def test_el_intervalo_espeja_la_constante_del_modulo():
    """Dos fuentes para el mismo default es el defecto; el espejo lo vuelve verificable.

    No se importa `analysis` desde `settings_manager` (medio proyecto lo importa a él),
    así que el valor está escrito dos veces y **esto** es lo que las mantiene iguales.
    """
    assert DEFAULTS["surprise_build_interval_days"] == DEFAULT_BUILD_INTERVAL_DAYS


def test_el_guard_de_la_154_quedo_sin_pendientes():
    """La señal de que la brecha se cerró: la excepción de la 154 queda **vacía**.

    No se tapó — se volvió innecesaria, que es el mismo cierre que la 154 le dio al
    `_SIN_SCHEMA` del guard de la 137.
    """
    from tests.test_settings_fantasma_t154 import _PENDIENTES_T160

    assert _PENDIENTES_T160 == {}, f"quedaron pendientes sin declarar: {sorted(_PENDIENTES_T160)}"


# ── (2) el estado sale del settings ──────────────────────────────────────────

_PAQUETES_RUNTIME = ("paper_trading", "analysis", "data", "alerts", "database")


def _escrituras_de_settings() -> list[str]:
    """``settings.set(...)`` en los paquetes de runtime de la app.

    `ui/` queda afuera **a propósito**: ahí el usuario guarda sus propias perillas, que
    es de quién es el archivo. Los `scripts/` de setup también (son el operador). Lo que
    no puede pasar es que un **job de fondo** escriba en el settings de Chapa.
    """
    out = []
    for paquete in _PAQUETES_RUNTIME:
        for p in sorted((_REPO / paquete).rglob("*.py")):
            try:
                arbol = ast.parse(p.read_text(encoding="utf-8"))
            except SyntaxError:  # pragma: no cover
                continue
            for n in ast.walk(arbol):
                if (
                    isinstance(n, ast.Call)
                    and isinstance(n.func, ast.Attribute)
                    and n.func.attr == "set"
                    and isinstance(n.func.value, ast.Name)
                    and n.func.value.id == "settings"
                ):
                    clave = n.args[0].value if n.args and isinstance(n.args[0], ast.Constant) else "?"
                    out.append(f"{p.relative_to(_REPO).as_posix()}: settings.set({clave!r}, …)")
    return out


def test_ningun_job_de_fondo_escribe_en_el_settings():
    """**El invariante que deja la 160.** No es *«no escribas `surprise_last_build`»* —eso
    sería la lista de siempre— sino *«el runtime no muta el archivo de perillas»*.

    `SettingsManager.save()` vuelca el dict **entero** de memoria, así que una escritura
    de fondo pisa cualquier edición externa del archivo; y encima convierte en
    "configuración" algo que el código decide solo.
    """
    assert not (culpables := _escrituras_de_settings()), (
        "estos escriben en el settings vivo desde el runtime (tarea 160). El estado va "
        "donde va el estado — para la cadencia de surprise, el `_meta` del artefacto:\n  "
        + "\n  ".join(culpables)
    )


def _accesos_a_settings(paquetes: tuple[str, ...]) -> list[tuple[str, str, str]]:
    """``(archivo, 'get'|'set', clave)`` de cada ``settings.get/set("clave", …)``.

    **Por AST y no por texto**, y no es preferencia: la primera versión de este test
    buscaba la clave como *string en el archivo* y acusó a `scheduler.py` y a
    `surprise_score.py` por los **comentarios** que yo mismo escribí explicando que la
    clave se fue. Grep no distingue código de prosa — la lección de la 147.
    """
    out = []
    for paquete in paquetes:
        for p in sorted((_REPO / paquete).rglob("*.py")):
            try:
                arbol = ast.parse(p.read_text(encoding="utf-8"))
            except SyntaxError:  # pragma: no cover
                continue
            for n in ast.walk(arbol):
                if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)):
                    continue
                if n.func.attr not in ("get", "set") or not isinstance(n.func.value, ast.Name):
                    continue
                if n.func.value.id != "settings" or not n.args:
                    continue
                if isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str):
                    out.append((p.relative_to(_REPO).as_posix(), n.func.attr, n.args[0].value))
    return out


def test_la_clave_de_estado_ya_no_se_lee_en_ningun_lado():
    """Contraprueba del de arriba por el otro lado: tampoco se **lee**. Si quedara una
    lectura, la cadencia tendría dos fuentes otra vez."""
    culpables = [
        f"{arch}: settings.{op}('surprise_last_build', …)"
        for arch, op, clave in _accesos_a_settings((*_PAQUETES_RUNTIME, "ui", "scripts", "config"))
        if clave == "surprise_last_build"
    ]
    assert not culpables, "la clave de estado sigue en el código:\n  " + "\n  ".join(culpables)


def test_el_barrido_de_accesos_ve_de_verdad_el_codigo():
    """Contraprueba del barrido: si el AST dejara de encontrar accesos, el test de arriba
    pasaría verde sobre una población vacía (la forma de la 110 y la 101)."""
    accesos = _accesos_a_settings(("paper_trading",))
    claves = {c for _, _, c in accesos}
    assert "surprise_build_enabled" in claves, "el barrido dejó de ver el scheduler"
    assert len(accesos) > 10


# ── (3) la marca sale del artefacto ──────────────────────────────────────────


def test_el_que_escribe_y_el_que_lee_hablan_del_mismo_archivo():
    """Si el builder escribe en otro path que el que mira la cadencia, la marca no se ve
    y el rebuild corre todos los días. Por eso la ruta se declara una sola vez."""
    from scripts.build_surprise_profiles import DEFAULT_OUT

    assert Path(DEFAULT_OUT) == PROFILES_PATH


def test_lee_el_built_at_del_artefacto(tmp_path):
    art = tmp_path / "perfiles.json"
    art.write_text(json.dumps({"_meta": {"built_at": "2026-09-03T20:58:27+00:00"}, "profiles": {}}))
    assert last_build_iso(art) == "2026-09-03T20:58:27+00:00"


@pytest.mark.parametrize(
    "contenido",
    [None, "{no es json", '"un string"', "{}", '{"_meta": []}', '{"_meta": {"built_at": ""}}'],
    ids=["sin archivo", "json roto", "raíz no dict", "sin _meta", "_meta no dict", "built_at vacío"],
)
def test_las_seis_formas_de_no_haber_marca_dan_None_y_por_lo_tanto_DUE(tmp_path, contenido):
    """Fail-soft, y el sentido del fail-soft acá es **construir**: si no se puede saber
    cuándo fue el último build, el rebuild corresponde. Lo contrario —asumir reciente—
    dejaría el artefacto podrido para siempre."""
    art = tmp_path / "perfiles.json"
    if contenido is not None:
        art.write_text(contenido, encoding="utf-8")
    assert last_build_iso(art) is None
    assert build_due(last_build_iso(art), datetime(2026, 9, 10), 7) is True


def test_el_artefacto_vivo_trae_una_marca_parseable():
    """Contraprueba contra el artefacto real: que los tests de arriba no pasen porque la
    función devuelve `None` para todo. Se saltea si no está el archivo (lección 107:
    preguntar por los **datos**, no por el archivo)."""
    if not PROFILES_PATH.exists():
        pytest.skip("no hay artefacto de perfiles en esta máquina")
    iso = last_build_iso()
    assert iso, "el artefacto vivo no declara _meta.built_at"
    assert datetime.fromisoformat(iso)


# ── (4) la zona horaria, que habría apagado el job en silencio ───────────────


def test_un_built_at_tz_aware_contra_un_now_naive_no_revienta():
    """**El trap que el cambio traía puesto.** El `built_at` del artefacto es tz-aware
    (UTC) y el `now` del scheduler es naive (`utcnow_naive`): restarlos levanta
    `TypeError`, que el scheduler se come en su `except Exception` ⇒ el rebuild **no
    correría nunca**, sin una línea de log. Medido antes de shipear, no después.
    """
    aware = "2026-09-03T20:58:27.348848+00:00"
    assert build_due(aware, datetime(2026, 9, 4), 7) is False  # 1 día: no corresponde
    assert build_due(aware, datetime(2026, 9, 11), 7) is True  # 8 días: corresponde


def test_y_al_reves_tambien(monkeypatch):
    """La otra mezcla: marca naive y `now` aware. Simétrico, por si el día que
    `utcnow_naive` pase a ser aware esto no se entere."""
    naive = "2026-09-03T20:58:27"
    ahora = datetime(2026, 9, 11, tzinfo=timezone.utc)
    assert build_due(naive, ahora, 7) is True
    assert build_due(naive, datetime(2026, 9, 4, tzinfo=timezone.utc), 7) is False


def test_los_dos_naive_siguen_funcionando_igual():
    """Regresión de lo que ya había: la normalización no puede cambiar el caso uniforme."""
    base = datetime(2026, 9, 10)
    assert build_due((base - timedelta(days=8)).isoformat(), base, 7) is True
    assert build_due((base - timedelta(days=6)).isoformat(), base, 7) is False


# ── (5) la premisa de la 154 que resultó falsa ───────────────────────────────


def test_la_pestania_settings_NO_se_arma_del_schema():
    """La 154 justificó su diferimiento con *«la pestaña Settings se arma del schema»*, y
    no es así: `ui/` no menciona `SCHEMA`. Declarar ≠ exponer, y este test lo fija para
    que la próxima tarea no herede el razonamiento.

    Si algún día la UI **sí** se armara del schema, esto se pone rojo — y ahí declarar un
    flag pasaría a ser, de verdad, una decisión de producto.
    """
    menciones = [
        p.relative_to(_REPO).as_posix()
        for p in sorted((_REPO / "ui").rglob("*.py"))
        if "SCHEMA" in p.read_text(encoding="utf-8")
    ]
    assert not menciones, f"la UI ahora lee el SCHEMA: {menciones} — revisar la tarea 162"
