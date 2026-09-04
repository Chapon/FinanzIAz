"""ACCT1-DEFAULTS (tarea 99) — qué cuenta mira un runner cuando nadie se lo dice.

Siete runners tenían ``--account`` con ``default=1``, y la cuenta 1 está **pausada**
desde el 2026-07-01. La forma peligrosa es que **no fallan**: esa cuenta tiene 91
fills reales congelados, así que devolvían un replay completo y plausible de una
cuenta muerta — sin un error, sin un aviso, sin un cero sospechoso.

Es el defecto que la tarea **70** cerró para los jobs de fondo, un directorio más
allá. La lección que se fija acá no es el arreglo puntual sino la de la
**población**: la 70 arregló *"los jobs de fondo"* y estos siete quedaron afuera
porque el conjunto se definió por **dónde se encontró el defecto** y no por la
propiedad que lo hace un defecto — *elegir cuenta con un literal*. El mismo patrón
dejó cuatro ``measure_*`` fuera del guard de cohorte de la 76 (tarea 101).

Por eso el test que más vale es ``test_ningun_runner_hardcodea_una_cuenta``: barre
``scripts/`` con **AST** y no con grep, y falla cuando aparece el próximo.
"""

from __future__ import annotations

import ast
import sqlite3
from pathlib import Path

import pytest

from scripts.baseline_metrics import NoLiveAccount, resolve_account_id

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"


@pytest.fixture
def base_con_cuentas():
    """Una base en memoria con la 1 PAUSADA y la 2 activa — el estado real."""
    con = sqlite3.connect(":memory:")
    con.execute(
        "CREATE TABLE paper_accounts (id INTEGER PRIMARY KEY, name TEXT, initial_capital REAL, "
        "cash REAL, is_active INTEGER, allocation_mode TEXT, strategy TEXT, created_at TEXT)"
    )
    con.executemany(
        "INSERT INTO paper_accounts VALUES (?,?,?,?,?,?,?,?)",
        [
            (1, "Sim Principal", 50_000.0, 0.0, 0, "equal_weight", "auto", "2026-05-01"),
            (2, "Sim Segundo", 50_000.0, 0.0, 1, "equal_weight", "auto", "2026-07-01"),
        ],
    )
    return con


def test_sin_flag_resuelve_la_cuenta_VIVA_no_la_1(base_con_cuentas):
    """El corazón del arreglo: el default deja de ser un literal."""
    assert resolve_account_id(base_con_cuentas) == 2


def test_un_flag_explicito_se_respeta_aunque_apunte_a_una_pausada(base_con_cuentas, capsys):
    """Mandó el operador — pero **no en silencio**.

    Es la decisión de diseño 1 de la tarea 70: reproducir un número histórico sobre
    la cuenta 1 es legítimo, y el silencio es lo que dejó correr el defecto dos meses.
    """
    assert resolve_account_id(base_con_cuentas, 1) == 1
    err = capsys.readouterr().err
    assert "PAUSADA" in err
    assert "Sim Principal" in err


def test_un_flag_explicito_a_la_viva_no_grita(base_con_cuentas, capsys):
    """El aviso tiene que discriminar, o se vuelve ruido que nadie lee."""
    assert resolve_account_id(base_con_cuentas, 2) == 2
    assert capsys.readouterr().err == ""


def test_una_cuenta_inexistente_LEVANTA_en_vez_de_adivinar(base_con_cuentas):
    """Devolver un default acá sería reintroducir el defecto con otro número."""
    with pytest.raises(NoLiveAccount, match="no existe"):
        resolve_account_id(base_con_cuentas, 99)


def test_sin_ninguna_cuenta_activa_LEVANTA(base_con_cuentas):
    """Un runner que no sabe sobre qué cuenta mide no debe elegir una."""
    base_con_cuentas.execute("UPDATE paper_accounts SET is_active = 0")
    with pytest.raises(NoLiveAccount, match="is_active=1"):
        resolve_account_id(base_con_cuentas)


def test_con_varias_activas_toma_la_de_menor_id_y_avisa(base_con_cuentas, capsys):
    """Ambigüedad, no error: se elige de forma determinística y se dice."""
    base_con_cuentas.execute("UPDATE paper_accounts SET is_active = 1")
    assert resolve_account_id(base_con_cuentas) == 1
    assert "2 cuentas activas" in capsys.readouterr().err


# ── El test de POBLACIÓN, que es el que caza al próximo ───────────────────────


def _defaults_de_cuenta(path: Path) -> list[tuple[str, object]]:
    """``[(flag, default)]`` de cada ``add_argument`` de cuenta. Por AST, no grep.

    Con grep esto se escapa apenas alguien parta la llamada en varias líneas —que
    es justo lo que hizo `ruff format` con estos mismos archivos.
    """
    try:
        arbol = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:  # pragma: no cover — un script roto ya lo caza la suite
        return []
    out: list[tuple[str, object]] = []
    for nodo in ast.walk(arbol):
        if not (isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Attribute)):
            continue
        if nodo.func.attr != "add_argument" or not nodo.args:
            continue
        primero = nodo.args[0]
        if not (isinstance(primero, ast.Constant) and isinstance(primero.value, str)):
            continue
        flag = primero.value
        if flag not in ("--account", "--account-id"):
            continue
        for kw in nodo.keywords:
            if kw.arg == "default":
                out.append((flag, getattr(kw.value, "value", "<no-literal>")))
    return out


def test_ningun_runner_hardcodea_una_cuenta():
    """Ningún ``--account`` puede tener un id literal como default.

    Éste es el test que importa: el arreglo puntual de los siete envejece, pero el
    invariante —*nadie elige cuenta con un literal*— es el que evita que la lista
    vuelva a crecer por el costado, que es exactamente cómo estos siete quedaron
    afuera de la tarea 70.
    """
    culpables = []
    for py in sorted(_SCRIPTS.glob("*.py")):
        for flag, default in _defaults_de_cuenta(py):
            if isinstance(default, int):
                culpables.append(f"{py.name}: {flag} default={default}")

    assert not culpables, (
        "estos runners eligen cuenta con un id hardcodeado; el default tiene que ser "
        "None y resolverse contra `is_active` (tarea 99):\n  " + "\n  ".join(culpables)
    )


def test_los_siete_runners_declaran_el_flag_y_lo_resuelven():
    """Contraprueba del anterior: que no pasen por estar vacíos.

    Un barrido que no encuentra nada porque **no miró nada** pasa igual de verde.
    Acá se fija que los siete sigan existiendo, sigan declarando el flag y sigan
    llamando al resolver.
    """
    esperados = {
        "run_exit_replay_t61.py",
        "run_atr_stop_recalib.py",
        "run_catalyst_exit_veto_backtest.py",
        "run_earnings_blackout_replay.py",
        "run_exposure_cap_replay.py",
        "run_risk_exit_autofill_replay.py",
        "analyze_expired_buys_financing.py",
    }
    for nombre in sorted(esperados):
        py = _SCRIPTS / nombre
        assert py.exists(), f"{nombre} desapareció — actualizá esta lista si fue a propósito"
        assert _defaults_de_cuenta(py), f"{nombre} dejó de declarar --account"
        assert "resolve_account_id(" in py.read_text(encoding="utf-8"), (
            f"{nombre} declara --account pero no lo resuelve contra `is_active` (tarea 99)"
        )
