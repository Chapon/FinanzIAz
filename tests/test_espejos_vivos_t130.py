"""Tarea 130 (ESPEJOS-VIVOS) — los espejos ``LIVE_*`` se comparan contra lo VIVO.

Los tres guards que existían para esto comparaban contra el **repo**:
``test_exit_policy_t92.py`` y ``test_desvios_declarados_t94_96.py`` contra un literal
escrito en el propio test, y ``test_volpen_t42.py`` contra ``DEFAULTS`` —o sea el
schema—. **Ninguno podía leer ``~/.finanzias/settings.json``**, así que ninguno podía
enterarse de que Chapa moviera una perilla.

**La prueba estaba adentro del propio test.** ``test_desvios_declarados_t94_96.py``
decía *«este test hizo su trabajo: pinneaba el 0.5 y falló al cambiar el valor
vivo»* — pero ``git show --stat 2a4404a`` muestra que ``harness_config.py`` y el
assert cambiaron **en el mismo commit**: disparó sobre la edición del **repo**, nunca
sobre la del settings.

Lo que se pierde cuando esto no existe está medido por el propio proyecto: el harness
declaró la política de salida **al revés** durante seis días (tarea 92) y eso valía
**7,16 pp de CAGR** — más que el look-ahead del fill que se ganó la tarea 33.

**Hoy los 13 espejos coinciden con el vivo: falta el guard, no la corrección.**

Dos decisiones de diseño que vale la pena leer antes de tocar esto:

1. **El valor vivo de una clave ausente del json es el default del schema.**
   ``paper_vol_penalty_coef`` no está escrita en el archivo, así que hoy el default
   *es* el valor vivo. Un guard construido sobre ``DEFAULTS`` acierta ahí **por
   accidente**, y deja de acertar apenas alguien escriba la clave. Acá se lee el json
   primero y se cae al schema sólo cuando la clave no está.
2. **La población se descubre, no se enumera.** ``test_ningun_LIVE_queda_sin_clasificar``
   barre ``dir(harness_config)`` y exige que **todo** ``LIVE_*`` esté o en la tabla de
   espejos de settings o en la lista de los que no salen de ahí, con su motivo. Un
   espejo nuevo no puede nacer invisible — que es el defecto de la 133, la 141 y la
   147. Ver [[guard-no-puede-usar-de-verdad-lo-que-chequea]].

**Lo que este guard NO puede ver, y va declarado.** Su población son los ``LIVE_*``
que **existen**, así que una perilla viva que **no tiene espejo** le es invisible.
Esto cierra *«el espejo dejó de seguir al vivo»* y **no** *«hay algo vivo sin
espejo»*: son dos agujeros distintos y éste tapa uno solo.

**Ese punto ciego lo cierra ahora ``tests/test_espejos_direccion_faltante_t185.py``**, que
barre la dirección contraria —del ``SCHEMA`` hacia los espejos— y exige que toda clave que el
camino vivo de decisión lea esté espejada **o** clasificada con un motivo escrito.

**Acá decía cuántas perillas estaban en esa situación, y era un conteo que este guard no puede
hacer (tarea 182).** Decía *«las dos … ``atr_stops_enabled`` (132) y
``paper_universe_screen_enabled`` (131)»*, y la auditoría del 2026-09-11 encontró que había más
—entre ellas ``atr_tp_mult``, que es **política de salida**—. Un guard no puede contar la
población a la que es ciego: el número sale de la clasificación de la 185, que sí la barre.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import analysis.harness_config as hc
from config.settings_manager import DEFAULTS

# ── La tabla: espejo → clave del settings vivo ───────────────────────────────

ESPEJOS: tuple[tuple[str, str], ...] = (
    ("LIVE_ATR_STOPS_ENABLED", "atr_stops_enabled"),
    ("LIVE_HARD_STOP_ENABLED", "atr_hard_stop_enabled"),
    ("LIVE_STOP_MULT", "atr_stop_mult"),
    ("LIVE_TRAIL_MULT", "atr_trail_mult"),
    ("LIVE_UNIVERSE_SCREEN_ENABLED", "paper_universe_screen_enabled"),
    ("LIVE_VOL_OVERLAY_ENABLED", "vol_overlay_enabled"),
    ("LIVE_VOL_TARGET_ANNUAL", "vol_target_portfolio_annual"),
    ("LIVE_VOL_PENALTY_COEF", "paper_vol_penalty_coef"),
    ("LIVE_REGIME_SCALE_ENABLED", "paper_regime_scale_enabled"),
    ("LIVE_REGIME_SCALE_FACTOR", "paper_regime_scale_factor"),
    ("LIVE_EARNINGS_BLACKOUT_DAYS", "earnings_blackout_days"),
    ("LIVE_WHIPSAW_LOOKBACK_DAYS", "paper_whipsaw_lookback_days"),
    ("LIVE_WHIPSAW_MIN_LOSS_PCT", "paper_whipsaw_min_loss_pct"),
    ("LIVE_CHURN_LOOKBACK_DAYS", "paper_churn_lookback_days"),
    ("LIVE_CHURN_MAX_CYCLES", "paper_churn_max_cycles"),
)

# Los ``LIVE_*`` que **no** salen del settings, con el motivo. No es una excepción:
# es la otra mitad de la clasificación que el test de población exige completa.
NO_SON_DE_SETTINGS: dict[str, str] = {
    "LIVE_ACCOUNT_ID": "sale de paper_accounts (DB); lo re-verifica test_account_defaults_t99",
    "LIVE_ACCOUNT_NAME": "sale de paper_accounts (DB)",
    "LIVE_MAX_POSITIONS": "sale de paper_accounts (DB)",
    "LIVE_MODE": "sale de paper_accounts (DB)",
    "LIVE_ALLOCATION_MODE": "sale de paper_accounts (DB)",
    "LIVE_WATCHLIST_SIZE": "sale de paper_watchlist (DB); lo re-verifica test_watchlist_size_t89",
    "LIVE_UNIVERSE_FILE": "ruta de un archivo del repo, no una perilla",
    "LIVE_HISTORY_BARS": "propiedad del frame que lee el harness, no del settings",
    "LIVE_EXIT_EVAL_DESC": "texto descriptivo del banner",
    "LIVE_FILL_DESC": "texto descriptivo del banner",
}

_SETTINGS_VIVO = Path.home() / ".finanzias" / "settings.json"


# ── El lector y la comparación ───────────────────────────────────────────────


def leer_settings(path: Path) -> dict | None:
    """El settings vivo, o ``None`` si **no hay con qué comparar**.

    ``utf-8-sig`` a propósito: PowerShell 5.1 escribe UTF-8 **con BOM** por default,
    y este archivo se edita a mano. Con ``utf-8`` pelado, un BOM rompe el parseo y el
    guard se caería en vez de saltearse.

    Las cuatro formas de *no hay con qué comparar* —sin archivo, ilegible, no es un
    objeto, o está vacío— devuelven ``None``. Es la lección de la 107: un guard que
    pregunta por el **archivo** y no por los **datos** deja el CI rojo doce corridas.
    """
    if not path.exists():
        return None
    try:
        datos = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
    return datos if isinstance(datos, dict) and datos else None


def valor_vivo(clave: str, vivo: dict):
    """El valor **efectivo** de una clave: el del json, o el default del schema.

    Una clave ausente del json no es *desconocida*: es la que el schema decide.
    """
    return vivo[clave] if clave in vivo else DEFAULTS.get(clave, "<no está en el schema>")


def _movido(actual):
    """Un valor **garantizadamente distinto** de ``actual``, del mismo tipo cuando se puede.

    **Tarea 175.** Antes esto era inline y hacía ``f"{actual}-movido"`` para todo lo que no
    fuera bool, o sea que convertía un float en str: distinto, sí, pero por el tipo y no por
    el valor. Un `!=` que pasa por el tipo no ejercita la comparación que el guard hace.
    """
    if isinstance(actual, bool):
        return not actual
    if isinstance(actual, (int, float)):
        return actual + 1
    return f"{actual}-movido"


def desvios(vivo: dict) -> list[str]:
    """Los espejos que ya no describen a la cuenta viva, con el detalle."""
    out = []
    for espejo, clave in ESPEJOS:
        actual = getattr(hc, espejo)
        esperado = valor_vivo(clave, vivo)
        if actual != esperado:
            fuente = "settings.json" if clave in vivo else "default del schema"
            out.append(f"{espejo} = {actual!r} pero {clave} vale {esperado!r} ({fuente})")
    return out


# ── El guard ─────────────────────────────────────────────────────────────────


def test_los_espejos_siguen_al_settings_VIVO():
    """El que faltaba: compara los 13 de una contra el archivo que Chapa edita.

    Se saltea sin datos (CI, checkout limpio, una instalación nueva) por el mismo
    motivo que el de la 89: existe para cazar el drift acá, no para romper donde no
    hay contra qué medirlo.
    """
    vivo = leer_settings(_SETTINGS_VIVO)
    if vivo is None:
        pytest.skip("sin settings.json vivo en este entorno")

    assert not (malos := desvios(vivo)), (
        "estos espejos de `analysis/harness_config.py` dejaron de describir a la "
        "cuenta viva, así que `deviations()` está declarando el desvío AL REVÉS "
        "(tarea 92: seis días así valieron 7,16 pp de CAGR):\n  " + "\n  ".join(malos)
    )


@pytest.mark.parametrize(("espejo", "clave"), ESPEJOS, ids=[e for e, _ in ESPEJOS])
def test_mut_mover_una_clave_del_settings_acusa_a_su_espejo(espejo, clave):
    """Mutación clave por clave: las 13 tienen que ser capaces de fallar.

    Un guard que compara 13 valores puede estar mirando 12 y nadie se entera. Acá se
    le mueve **una** al valor vivo y se exige que el mensaje **nombre a esa**.
    """
    # **Tarea 175 — la línea base sale de los ESPEJOS, no del settings vivo.**
    # Antes era `leer_settings(...) or {}`, y con eso el test dependía del entorno: donde
    # no hay `~/.finanzias/settings.json` —el CI— la base caía al **default del schema**,
    # que para tres claves **no** coincide con su espejo (`atr_stops_enabled` y
    # `atr_hard_stop_enabled` y `paper_universe_screen_enabled`: default `False`, vivo
    # `True`). Flipear un bool desde el default aterrizaba entonces **sobre** el valor del
    # espejo, la mutación quedaba en no-op y el test fallaba. Verde en Windows, rojo en
    # Ubuntu desde su propio commit (`94dcae5`), 35 corridas.
    #
    # Una mutación necesita una base **sin desvíos por construcción**, y eso es lo que los
    # espejos son. El assert de abajo lo exige en vez de suponerlo: sin él, un caso puede
    # arrancar ya desviado y "pasar" por el desvío que traía, no por el que se inyectó.
    base = {c: getattr(hc, e) for e, c in ESPEJOS}
    assert desvios(base) == [], "la línea base ya traía desvíos: la mutación no probaría nada"

    actual = base[clave]
    mutado = dict(base)
    mutado[clave] = _movido(actual)
    assert mutado[clave] != actual, f"la mutación de {clave} no movió el valor"

    malos = desvios(mutado)
    assert any(espejo in m for m in malos), f"mover {clave} no acusó a {espejo}"
    assert len(malos) == 1, f"mover {clave} acusó a más de un espejo: {malos}"


def test_una_clave_AUSENTE_del_json_cae_al_default_del_schema():
    """El caso ``paper_vol_penalty_coef``, que es el que hace sutil a esto.

    No está escrita en el settings, así que su valor vivo **es** el default. Un guard
    que sólo mirara el json la trataría como desconocida; uno que sólo mirara
    ``DEFAULTS`` acertaría por accidente hasta que alguien la escriba.
    """
    assert valor_vivo("paper_vol_penalty_coef", {}) == DEFAULTS["paper_vol_penalty_coef"]
    assert valor_vivo("paper_vol_penalty_coef", {"paper_vol_penalty_coef": 9.9}) == 9.9


def test_las_cuatro_formas_de_no_tener_con_que_comparar_saltean(tmp_path):
    """Sin archivo, ilegible, no-objeto o vacío ⇒ ``None`` ⇒ skip. Nunca un fallo."""
    assert leer_settings(tmp_path / "no-existe.json") is None

    roto = tmp_path / "roto.json"
    roto.write_text("{no soy json", encoding="utf-8")
    assert leer_settings(roto) is None

    lista = tmp_path / "lista.json"
    lista.write_text("[1, 2, 3]", encoding="utf-8")
    assert leer_settings(lista) is None

    vacio = tmp_path / "vacio.json"
    vacio.write_text("{}", encoding="utf-8")
    assert leer_settings(vacio) is None


def test_un_settings_con_BOM_se_lee_igual(tmp_path):
    """PowerShell 5.1 escribe UTF-8 **con BOM**, y este archivo se edita a mano."""
    con_bom = tmp_path / "bom.json"
    con_bom.write_text('{"atr_trail_mult": 2.0}', encoding="utf-8-sig")
    assert leer_settings(con_bom) == {"atr_trail_mult": 2.0}


# ── La población, que es lo que impide que la tabla envejezca ────────────────


def test_ningun_LIVE_queda_sin_clasificar():
    """**El test que evita que esto se vuelva la 133 / 141 / 147.**

    La población se **descubre** de ``dir(harness_config)``, no se enumera. Un
    ``LIVE_*`` nuevo obliga a decidir: o es un espejo del settings y va a ``ESPEJOS``,
    o no lo es y va a ``NO_SON_DE_SETTINGS`` con el motivo escrito. Lo que no puede
    es nacer invisible, que es exactamente cómo el harness terminó declarando la
    política de salida al revés.
    """
    todos = {k for k in dir(hc) if k.startswith("LIVE_")}
    clasificados = {e for e, _ in ESPEJOS} | set(NO_SON_DE_SETTINGS)

    assert not (sin := todos - clasificados), (
        "estos LIVE_* no están clasificados: decidí si son espejo del settings vivo "
        f"(a ESPEJOS) o no (a NO_SON_DE_SETTINGS, con el motivo): {sorted(sin)}"
    )
    assert not (fantasmas := clasificados - todos), (
        f"estos LIVE_* ya no existen en harness_config: {sorted(fantasmas)}"
    )


@pytest.mark.parametrize("clave", [c for _, c in ESPEJOS])
def test_cada_clave_de_la_tabla_existe_en_el_schema(clave):
    """Una clave mal escrita haría que el guard compare contra un centinela y pase.

    Es el modo de fallo de la 128 con otra ropa: lo que no se pudo leer no se aprueba.
    """
    assert clave in DEFAULTS, f"{clave} no está en el schema de settings"
