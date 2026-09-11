"""Tarea 185 — la dirección que faltaba: del SETTINGS hacia los espejos.

**El guard de la 130 mira `espejos → settings` y declara que no puede mirar al revés.**
Su docstring lo dice textual: *«Su población son los ``LIVE_*`` que **existen**, así que una
perilla viva que **no tiene espejo** le es invisible. Esto cierra "el espejo dejó de seguir al
vivo" y **no** "hay algo vivo sin espejo": son dos agujeros distintos y éste tapa uno solo.»*

Las dos que estaban en esa situación se cerraron **una por una** —``atr_stops_enabled`` en la
tarea 132 y ``paper_universe_screen_enabled`` en la 131— y **nunca se shipeó el mecanismo que
encuentra la próxima**. La auditoría del 2026-09-11 encontró que había más. Un punto ciego
declarado y no cerrado es una promesa, no un guard.

**Qué hace este archivo.** Barre por **AST** las claves del `SCHEMA` que el **camino vivo de
decisión** lee, y exige que cada una esté **o espejada** (tiene su `LIVE_*` en la tabla de la
130) **o clasificada acá con un motivo escrito**. Una clave nueva no puede nacer invisible.

**Dos detalles del instrumento que costaron una pasada, y van escritos porque el barrido
mentiría sin ellos:**

1. **Hay que mirar las dos formas de llamada.** `settings.get("x")` es un `ast.Attribute` y
   `_toggle("x")` —el helper de `analysis/technical.py`— es un `ast.Name`. La primera versión
   sólo miraba `func.attr` y por eso **no veía** `hmm_enabled`, `stacking_enabled` ni
   `xgb_signal_enabled`, que son justamente tres de los casos que la auditoría reportó.
2. **La población se descubre, no se enumera.** Si esta lista fuera un literal, sería el defecto
   de la 133 / 141 / 147 un nivel más arriba.

**Lo que este guard NO hace, y va dicho:** no decide si una perilla **debería** estar modelada
por el harness — eso es una decisión de trading. Sólo exige que la respuesta esté **escrita**.
La categoría `FALTA_ESPEJO` existe justamente para que un caso pendiente quede **visible como
pendiente** en vez de enterrado en un allowlist.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from config.settings_manager import DEFAULTS
from tests.test_espejos_vivos_t130 import ESPEJOS

_REPO = Path(__file__).resolve().parent.parent

# El camino vivo de decisión: lo que corre cuando el engine propone y filtra una orden.
_CAMINO_VIVO: tuple[str, ...] = (
    "paper_trading/engine.py",
    "paper_trading/gates.py",
    "paper_trading/strategies.py",
    "analysis/technical.py",
    "analysis/ml_signals.py",
)

# Las dos formas en que el camino vivo lee una perilla. Ver el §2 del docstring: mirar una sola
# deja fuera a los tres toggles de modelo.
_LECTORES = ("get", "_toggle")


# ── La clasificación: toda clave sin espejo necesita un motivo ────────────────
#
# El valor es el motivo, y el prefijo dice de qué tipo es. `FALTA_ESPEJO:` es el único que
# significa *«esto es un pendiente reconocido»* — los demás son cierres.

SIN_ESPEJO: dict[str, str] = {
    # ── FALTA_ESPEJO — reconocidos como pendientes por la auditoría del 2026-09-11 ──
    "atr_tp_mult": (
        "FALTA_ESPEJO: es política de SALIDA y el harness la modela con un literal "
        "(`analysis/exit_replay.py` → `tp_mult: float = 4.0`) que hoy coincide por casualidad. "
        "Si se mueve, todos los harness de salida siguen modelando 4.0 y nada lo dice — es el "
        "defecto de la tarea 92, que costó 7,16 pp de CAGR"
    ),
    "atr_trail_enabled": (
        "FALTA_ESPEJO: master switch del trailing, mismo eje que `atr_stops_enabled` (que sí "
        "tiene espejo desde la tarea 132). Apagarlo cambiaría qué salidas simula el harness"
    ),
    "paper_adv_cap_pct": (
        "FALTA_ESPEJO: está ON en la cuenta viva (0.05 contra un default de 0.0) y trima cada "
        "BUY; el harness no lo modela. Hoy es inerte —el cap sólo mordería con ADV$ < ~$103k— "
        "pero no está declarado. Tarea 184"
    ),
    "hmm_enabled": (
        "FALTA_ESPEJO: está OFF en vivo contra un default de True, y los harness que no fijan "
        "los toggles lo heredan del ambiente. Tarea 181"
    ),
    "stacking_enabled": (
        "FALTA_ESPEJO: ídem `hmm_enabled` — OFF en vivo contra default True. Su camino no corre "
        "en el scan (`analyze_stacked` sólo lo llama `analysis/backtest.py`), pero sí en harness"
    ),
    # ── NO_MODELABLE — el harness diario no puede representarlos ──
    "paper_min_holding_minutes": "NO_MODELABLE: tiempo intradía; el harness decide sobre barras diarias",
    "paper_anti_flap_minutes": "NO_MODELABLE: ventana intradía entre órdenes, sin equivalente en barras diarias",
    "paper_enforce_market_hours": "NO_MODELABLE: horario de mercado real; el harness no tiene reloj de sesión",
    "paper_history_period": "NO_MODELABLE: es el período que pide el engine a Yahoo; el harness usa su propio cohorte",
    # ── NO_ES_DECISION — no entran en qué se compra o se vende ──
    "slack_notifications_enabled": (
        "NO_ES_DECISION: avisa DESPUÉS de que la orden se decidió; no entra en qué se compra "
        "ni a qué tamaño. Está ON en vivo contra un default OFF, y eso es correcto"
    ),
    "slack_notify_on": (
        "NO_ES_DECISION: elige QUÉ eventos se notifican (`both`), posterior a la decisión. "
        "El harness no notifica nada, así que no hay nada que espejar"
    ),
    "ibkr_commission_plan": "NO_ES_DECISION: el harness modela costos por su cuenta (`paper_trading/costs.py`)",
    # ── SUBSISTEMA_OFF — apagados y sin camino vivo ──
    "paper_catalyst_exit_veto_enabled": (
        "SUBSISTEMA_OFF: Gate 2c, OFF por kill-criteria no superado (T-CAT-6) y además sin "
        "`catalyst_signal_provider` inyectado en producción. Tarea 162"
    ),
    "paper_catalyst_veto_min_score": "SUBSISTEMA_OFF: parámetro del Gate 2c, que no corre (ver arriba)",
    "paper_catalyst_veto_gray_high": "SUBSISTEMA_OFF: parámetro del Gate 2c, que no corre (ver arriba)",
    "cross_sectional_enabled": "SUBSISTEMA_OFF: ranking cross-sectional (T05), OFF en vivo y en el harness",
    "cross_sectional_lookback": (
        "SUBSISTEMA_OFF: ventana del ranking cross-sectional (T05). Inerte mientras "
        "`cross_sectional_enabled` sea False, que es el estado vivo y el del harness"
    ),
    "cross_sectional_weight": (
        "SUBSISTEMA_OFF: peso del ranking cross-sectional (T05) en la señal combinada. "
        "Inerte mientras `cross_sectional_enabled` sea False, que es el estado vivo"
    ),
    "vol_overlay_trim_enabled": "SUBSISTEMA_OFF: el trim del overlay está OFF; el overlay en sí sí tiene espejo",
    # ── YA_DECLARADO — cubiertos por una clave de `deviations_keyed()` ──
    "earnings_blackout_block_sells": (
        "YA_DECLARADO: la clave `earnings_blackout` declara el gate entero, y su texto dice que "
        "el harness no lo modela — el lado SELL no agrega un eje nuevo"
    ),
    # ── ENTRADA_DEL_MODELO — parametrizan el cálculo, no la política ──
    "atr_period": "ENTRADA_DEL_MODELO: ventana del ATR; el harness usa la misma y no es una perilla de política",
    "paper_adv_lookback_days": "ENTRADA_DEL_MODELO: ventana del ADV$, que sólo alimenta al cap (ver `paper_adv_cap_pct`)",
    "xgb_signal_enabled": "ENTRADA_DEL_MODELO: ON en vivo y en el harness; es el camino por default de la señal",
    # ── SIZING_NO_CABLEADO — existen en el schema pero el sizing vivo no los usa hoy ──
    "kelly_fraction": "SIZING_NO_CABLEADO: `equal_weight` es el modo de la cuenta viva; Kelly no entra",
    "max_position_weight": "SIZING_NO_CABLEADO: tope por posición, inerte bajo `equal_weight` con 10 slots",
    "vol_target_annual": "SIZING_NO_CABLEADO: objetivo de vol por NOMBRE; el que muerde es el de CARTERA, que sí tiene espejo",
    "paper_min_trade_dollars": (
        "SIZING_NO_CABLEADO: piso de notional (250 USD) contra un tamaño de BUY de ~5.150 USD "
        "en la cuenta viva, o sea inerte por dos órdenes de magnitud"
    ),
    "paper_signal_sell_bypass_score": "YA_DECLARADO: parte del Gate 2b, que la clave `reentry_gates` ya declara",
    "paper_signal_sell_min_age_bdays": "YA_DECLARADO: parte del Gate 2b, que la clave `reentry_gates` ya declara",
}

_PREFIJOS_VALIDOS = (
    "FALTA_ESPEJO:",
    "NO_MODELABLE:",
    "NO_ES_DECISION:",
    "SUBSISTEMA_OFF:",
    "YA_DECLARADO:",
    "ENTRADA_DEL_MODELO:",
    "SIZING_NO_CABLEADO:",
)


def claves_del_camino_vivo() -> dict[str, set[str]]:
    """``{clave: {archivos que la leen}}``, por AST sobre el camino vivo de decisión."""
    out: dict[str, set[str]] = {}
    for rel in _CAMINO_VIVO:
        p = _REPO / rel
        if not p.exists():  # pragma: no cover
            continue
        for n in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
            if not (isinstance(n, ast.Call) and n.args):
                continue
            nombre = getattr(n.func, "attr", None) or getattr(n.func, "id", None)
            if nombre not in _LECTORES:
                continue
            arg = n.args[0]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str) and arg.value in DEFAULTS:
                out.setdefault(arg.value, set()).add(rel)
    return out


# ── La población: se descubre, y tiene que ser grande ────────────────────────


def test_el_barrido_encuentra_una_poblacion_de_verdad():
    """Contraprueba: sin esto, un cambio de nombre del helper dejaría todo lo de abajo pasando
    **por vacío** y "demostrando" que no falta ningún espejo."""
    leidas = claves_del_camino_vivo()
    assert len(leidas) >= 40, f"el barrido sólo vio {len(leidas)} claves: revisar `_LECTORES`"
    # las dos formas de llamada tienen que estar representadas
    assert "paper_min_trade_dollars" in leidas, "no se ven las lecturas por `settings.get(...)`"
    assert "hmm_enabled" in leidas, "no se ven las lecturas por `_toggle(...)` — es un ast.Name"


def test_las_DOS_formas_de_lectura_estan_cubiertas():
    """**El defecto que tuvo la primera versión de este guard.** `_toggle("x")` es un `ast.Name`
    y `settings.get("x")` un `ast.Attribute`: mirar sólo `func.attr` dejaba fuera a los tres
    toggles de modelo, que son tres de los casos que la auditoría reportó."""
    src = (_REPO / "analysis" / "technical.py").read_text(encoding="utf-8")
    assert '_toggle("hmm_enabled"' in src, "cambió la forma de leer los toggles: revisar el barrido"


# ── El invariante de la tarea ───────────────────────────────────────────────


def test_TODA_clave_viva_esta_espejada_o_clasificada():
    """**El invariante.** La dirección que la 130 declaró que no podía mirar."""
    espejadas = {clave for _, clave in ESPEJOS}
    huerfanas = sorted(set(claves_del_camino_vivo()) - espejadas - set(SIN_ESPEJO))
    assert not huerfanas, (
        "estas claves las lee el camino vivo de decisión y no tienen espejo `LIVE_*` ni "
        "clasificación con motivo (tarea 185). Agregá el espejo, o clasificala acá diciendo "
        "por qué no hace falta:\n  " + "\n  ".join(huerfanas)
    )


def test_ninguna_clasificada_esta_TAMBIEN_espejada():
    """Si una clave tiene espejo **y** figura acá como que no lo necesita, una de las dos cosas
    está mal y el próximo lector no sabe cuál."""
    espejadas = {clave for _, clave in ESPEJOS}
    dobles = sorted(espejadas & set(SIN_ESPEJO))
    assert not dobles, f"clasificadas como sin-espejo pero espejadas: {dobles}"


def test_no_hay_entradas_FANTASMA():
    """Una clave clasificada que el camino vivo **ya no lee** es basura que envejece: da la
    impresión de que se pensó algo que hoy no aplica. Mismo criterio que el guard de claves
    fantasma de la tarea 152."""
    leidas = set(claves_del_camino_vivo())
    fantasmas = sorted(set(SIN_ESPEJO) - leidas)
    assert not fantasmas, f"clasificadas pero ya nadie las lee en el camino vivo: {fantasmas}"


@pytest.mark.parametrize("clave", sorted(SIN_ESPEJO))
def test_cada_clasificacion_declara_su_TIPO_y_su_motivo(clave):
    """Un motivo libre se degrada a *«porque sí»* en tres ediciones. El prefijo obliga a elegir
    una de las categorías, y el largo a escribir el porqué."""
    motivo = SIN_ESPEJO[clave]
    assert motivo.startswith(_PREFIJOS_VALIDOS), f"{clave}: el motivo no declara su tipo"
    assert len(motivo) > 60, f"{clave}: el motivo es demasiado corto para ser uno"


# ── Los pendientes quedan VISIBLES como pendientes ──────────────────────────


def test_los_FALTA_ESPEJO_son_los_que_la_auditoria_reporto():
    """**La condición de honestidad de este guard.** `FALTA_ESPEJO` no es una excepción: es un
    pendiente reconocido. Si alguien "resuelve" un caso moviéndolo a otra categoría en vez de
    darle espejo, esto se pone rojo y hay que justificarlo acá."""
    faltan = {c for c, m in SIN_ESPEJO.items() if m.startswith("FALTA_ESPEJO:")}
    assert faltan == {
        "atr_tp_mult",
        "atr_trail_enabled",
        "paper_adv_cap_pct",
        "hmm_enabled",
        "stacking_enabled",
    }, (
        "cambió el conjunto de pendientes de espejo. Si le diste espejo a uno, sacalo de "
        f"`SIN_ESPEJO` y actualizá este test. Hoy: {sorted(faltan)}"
    )


def test_los_pendientes_DIFIEREN_del_default_o_son_de_politica():
    """Por qué esos cinco y no otros: o su valor vivo **difiere** del default del schema —lo que
    los vuelve invisibles a cualquier guard construido sobre `DEFAULTS`— o son perillas de
    **política de salida**, que es el eje donde un desvío no declarado ya costó 7,16 pp."""
    vivo_path = Path.home() / ".finanzias" / "settings.json"
    if not vivo_path.exists():
        pytest.skip("sin settings.json vivo en este entorno")
    vivo = json.loads(vivo_path.read_text(encoding="utf-8-sig"))

    de_politica = {"atr_tp_mult", "atr_trail_enabled"}
    for clave, motivo in SIN_ESPEJO.items():
        if not motivo.startswith("FALTA_ESPEJO:"):
            continue
        difiere = clave in vivo and vivo[clave] != DEFAULTS[clave]
        assert difiere or clave in de_politica, (
            f"{clave} está marcada FALTA_ESPEJO pero ni difiere del default ni es de política "
            "de salida: revisá si de verdad hace falta"
        )
