"""Tarea 181 — `kill_only` era el nombre de una configuración, no un mecanismo.

**Lo que decían los TRES documentos de referencia del proyecto.** `docs/ARCHITECTURE.md`:
*«`hmm_enabled`/`stacking_enabled` **forzados OFF** … los defaults de SettingSpec dicen otra
cosa; **kill_only los pisa**»*. `docs/SETTINGS_REFERENCE.md` abría con *«**kill_only pisa
defaults**»*. Y `CLAUDE.md` lo repetía en el mapa rápido.

**Nada fuerza ni pisa nada.** `analysis/technical._toggle` los lee con `default=True`, el
`SCHEMA` los tiene en `True`, y estaban OFF **únicamente** porque una clave escrita a mano en
`~/.finanzias/settings.json` —un archivo **fuera del repo**— lo decía.
`paper_trading/feature_switch.py`, que declara *«always OFF»*, es **dead code**: sólo lo
importan un harness y su test.

**Dónde muerde de verdad, y no es el scan.** La fase adversarial refutó dos de las tres patas
de impacto que tenía el hallazgo original (el CI no: `conftest` redirige el settings; y
`stacking` no corre en el scan vivo). Lo que quedó, y es más grande:
`scripts/precompute_pit_signals.py` llama a `analyze()` y su salida —el **store PIT**— es el
sustrato de **todos** los runners modernos, que no llaman a `analyze()` porque leen señales
precomputadas. El store es **regenerable y gitignoreado**, y se recomputó **dos veces** en la
semana del 2026-09-09. En cualquier máquina sin ese archivo habría salido con hmm y stacking
**ON**: señales silenciosamente distintas, y cada runner midiendo otra cosa.

**El arreglo.** `analysis.harness_config.HARNESS_MODEL_TOGGLES` declara la config **en el
repo**, y los productores de artefactos la fijan **en memoria** con
`settings.set_ephemeral` — que valida como `set()` pero **no persiste**, porque `set()` llama
a `save()` y eso le reescribiría el `settings.json` entero a Chapa. Los valores son los vivos,
así que **en su máquina no cambia nada**: lo que cambia es que dejan de depender de un archivo
que no está versionado.

**Por qué este guard NO busca las palabras «fuerza» ni «pisa».** Porque las correcciones de
los tres docs **citan la frase vieja** para explicar qué se corrigió, así que un substring no
podría distinguir *«el doc todavía lo afirma»* de *«el doc cuenta que dejó de afirmarlo»* — el
defecto que las tareas 173, 150, 176, 177 y 179 cometieron. Se verifica la **sustancia**.
"""

from __future__ import annotations

import ast
import inspect
import json
from pathlib import Path

import pytest

from analysis.harness_config import HARNESS_MODEL_TOGGLES, apply_model_toggles
from config.settings_manager import DEFAULTS, _SettingsManager

_REPO = Path(__file__).resolve().parent.parent


def _scripts_que_llaman_analyze() -> dict[str, bool]:
    """``{script: aplica_los_toggles}`` para cada script que llama a ``analyze()`` directo.

    La población se **descubre** por AST: un productor nuevo no puede nacer invisible.
    """
    out: dict[str, bool] = {}
    for p in sorted((_REPO / "scripts").glob("*.py")):
        src = p.read_text(encoding="utf-8")
        try:
            tree = ast.parse(src)
        except SyntaxError:  # pragma: no cover
            continue
        llama = any(
            isinstance(n, ast.Call)
            and (getattr(n.func, "id", None) == "analyze" or getattr(n.func, "attr", None) == "analyze")
            for n in ast.walk(tree)
        )
        if llama:
            out[p.name] = "apply_model_toggles()" in src
    return out


# ── La config declarada, y que sea la VIVA ──────────────────────────────────


def test_la_config_de_modelo_esta_declarada_en_el_REPO():
    """El punto de la tarea: que la config no viva sólo en un archivo fuera del repo."""
    assert set(HARNESS_MODEL_TOGGLES) == {"hmm_enabled", "stacking_enabled", "xgb_signal_enabled"}
    assert HARNESS_MODEL_TOGGLES["hmm_enabled"] is False
    assert HARNESS_MODEL_TOGGLES["stacking_enabled"] is False
    assert HARNESS_MODEL_TOGGLES["xgb_signal_enabled"] is True


def test_los_toggles_declarados_DIFIEREN_del_schema_y_por_eso_hacen_falta():
    """**La contraprueba que justifica que esto exista.** Si los declarados coincidieran con
    los `DEFAULTS`, fijarlos sería decorativo: un entorno sin `settings.json` ya daría lo
    correcto. Difieren en dos de tres, y por eso un store generado sin ese archivo sale mal."""
    difieren = {k: (DEFAULTS[k], v) for k, v in HARNESS_MODEL_TOGGLES.items() if DEFAULTS[k] != v}
    assert set(difieren) == {"hmm_enabled", "stacking_enabled"}, (
        "cambió la relación entre el schema y la config declarada: si ya no difieren, "
        f"revisá si esta tarea sigue teniendo objeto. Hoy: {difieren}"
    )


def test_la_config_declarada_es_la_VIVA():
    """Y que sea la de la cuenta viva, no una elegida acá: lo que se fija tiene que ser la
    config bajo la que se midió cada veredicto publicado."""
    vivo_path = Path.home() / ".finanzias" / "settings.json"
    if not vivo_path.exists():
        pytest.skip("sin settings.json vivo en este entorno")
    vivo = json.loads(vivo_path.read_text(encoding="utf-8-sig"))
    for clave, valor in HARNESS_MODEL_TOGGLES.items():
        if clave in vivo:
            assert vivo[clave] == valor, (
                f"{clave} vale {vivo[clave]!r} en la cuenta viva y {valor!r} en "
                "HARNESS_MODEL_TOGGLES: los artefactos se estarían generando bajo otra config "
                "que la que corre"
            )


# ── `set_ephemeral`: valida pero NO persiste ────────────────────────────────


def test_set_ephemeral_NO_persiste():
    """**La condición de seguridad de todo esto.** `set()` llama a `save()`, y `save()` vuelca
    el dict entero de memoria: usarlo acá le reescribiría el `settings.json` a Chapa y se
    llevaría puesta cualquier edición externa. `set_ephemeral` no puede tocar el disco."""
    fuente = inspect.getsource(_SettingsManager.set_ephemeral)
    arbol = ast.parse(fuente.lstrip())
    llamadas = {
        getattr(n.func, "attr", None) or getattr(n.func, "id", None)
        for n in ast.walk(arbol)
        if isinstance(n, ast.Call)
    }
    assert "save" not in llamadas, "`set_ephemeral` llama a save(): dejaría de ser efímero"
    assert "_validate_value" in llamadas, "`set_ephemeral` dejó de validar: acepta cualquier cosa"


def test_set_ephemeral_valida_igual_que_set(tmp_path, monkeypatch):
    """Un valor inválido se rechaza y el anterior queda — si no, sería un agujero para
    escribir basura en memoria que después se persiste desde otro lado."""
    import config.settings_manager as sm

    monkeypatch.setattr(sm, "_CONFIG_PATH", tmp_path / "settings.json")
    s = sm._SettingsManager()
    s.load()
    assert s.set_ephemeral("hmm_enabled", False) is True
    assert s.get("hmm_enabled") is False
    assert s.set_ephemeral("hmm_enabled", "no es un bool") is False
    assert s.get("hmm_enabled") is False, "un valor inválido pisó el anterior"
    assert not (tmp_path / "settings.json").exists(), "set_ephemeral escribió el archivo"


def test_apply_model_toggles_deja_la_config_declarada(tmp_path, monkeypatch):
    """De punta a punta, en un entorno **sin** `settings.json` — que es el caso que rompía."""
    import config.settings_manager as sm

    monkeypatch.setattr(sm, "_CONFIG_PATH", tmp_path / "settings.json")
    sm.settings.load()
    assert sm.settings.get("hmm_enabled") is True, "sin archivo, el default es True (el defecto)"

    devuelto = apply_model_toggles()
    assert devuelto == HARNESS_MODEL_TOGGLES
    for clave, valor in HARNESS_MODEL_TOGGLES.items():
        assert sm.settings.get(clave) == valor
    assert not (tmp_path / "settings.json").exists(), "apply_model_toggles escribió el archivo"


# ── La población: todo productor que llama a analyze() los fija ─────────────


def test_hay_scripts_que_llaman_analyze():
    """Contraprueba de población: sin esto, un cambio de nombre dejaría el test de abajo
    pasando **por vacío**."""
    llaman = _scripts_que_llaman_analyze()
    assert llaman, "el barrido AST no encontró ningún script que llame a analyze()"
    assert "precompute_pit_signals.py" in llaman, "no se ve el productor del store PIT"


def test_TODO_script_que_llama_analyze_fija_la_config():
    """El invariante: un artefacto no puede depender de la config de la máquina que lo generó."""
    sin_fijar = sorted(n for n, fija in _scripts_que_llaman_analyze().items() if not fija)
    assert not sin_fijar, (
        "estos scripts llaman a `analyze()` sin fijar la config de modelo, así que heredan "
        "`hmm_enabled`/`stacking_enabled` del `settings.json` del ambiente (tarea 181). "
        "Agregá `apply_model_toggles()`:\n  " + "\n  ".join(sin_fijar)
    )


def test_el_pool_los_fija_TAMBIEN_en_el_worker():
    """Cada worker del pool es **otro proceso** y no hereda la memoria del padre. Sin esto, el
    padre correría bajo la config declarada y los workers —que son los que de verdad llaman a
    `analyze()`— bajo la del ambiente, que es el peor de los dos mundos: parecería arreglado."""
    src = (_REPO / "scripts" / "precompute_pit_signals.py").read_text(encoding="utf-8")
    arbol = ast.parse(src)
    worker = next(n for n in ast.walk(arbol) if isinstance(n, ast.FunctionDef) and n.name == "_init_worker")
    llamadas = {
        getattr(n.func, "attr", None) or getattr(n.func, "id", None)
        for n in ast.walk(worker)
        if isinstance(n, ast.Call)
    }
    assert "apply_model_toggles" in llamadas, "`_init_worker` no fija los toggles"


def test_el_artefacto_ESTAMPA_la_config():
    """Un store computado bajo otra config deja de ser indistinguible de uno correcto. Los
    artefactos anteriores a la 181 no traen el sello, y eso se lee como *«no se sabe»* — no se
    fuerza una regeneración, que es cara."""
    src = (_REPO / "scripts" / "precompute_pit_signals.py").read_text(encoding="utf-8")
    assert '"model_toggles": dict(HARNESS_MODEL_TOGGLES)' in src
