"""
Tests del cableado de la Tarea 53 (STOP-WIRE) — el ship de la Tarea 37.

Qué se cabla
------------
Hasta acá ``gates.atr_exit_decision`` usaba **el mismo ``stop_mult``** para el
stop duro y para el trailing, así que el candidato que la T37 validó
(``soff_t2.0``: stop duro apagado, trailing en 2.0×ATR) **no era expresable**
con los settings existentes. Esta tarea agrega dos knobs:

    atr_trail_mult          múltiplo del trailing, independiente del stop duro.
                            0.0 (default) ⇒ sigue a ``atr_stop_mult``.
    atr_hard_stop_enabled   sub-switch del stop duro. True (default) ⇒ dispara
                            como siempre.

**Los dos defaults preservan el comportamiento histórico** — el ship es el
mecanismo, no el cambio de política. Prender el candidato es decisión de Chapa
(``docs/stop_value_t37_2026-08-27.md``, las tres reservas del §VEREDICTO).

Lo que estos tests fijan, por orden de importancia
--------------------------------------------------
1. **Paridad con el brazo medido.** ``hard_stop_enabled=False`` en el gate es
   idéntico, decisión por decisión, al ``stop_mult=1e9`` con que
   ``analysis.exit_replay`` corrió ``soff_t2.0`` en la T37. Sin esto el
   cableado no shipea el brazo validado sino otra cosa parecida.
2. **Los defaults no mueven nada** (regresión sobre el engine y sobre el gate).
3. El desacople muerde: con ``trail_mult`` distinto del stop, el nivel y el
   texto del ``reason`` citan el múltiplo del trailing.
4. Sin stop duro **no hay R:R y no se inventa uno** (consecuencia de display
   declarada en el §8 del veredicto; display-only, regla 3).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from analysis.exit_replay import AtrParams, atr_exit
from config.settings_manager import DEFAULTS, SCHEMA, settings
from database.models import session_scope
from paper_trading.account import create_account
from paper_trading.engine import _compute_atr_forced_exits
from paper_trading.gates import (
    TRAIL_MULT_FOLLOWS_STOP,
    atr_exit_decision,
    effective_trail_mult,
    entry_risk_levels,
    format_entry_risk_note,
)
from paper_trading.models import PaperPosition

# ── Helpers ───────────────────────────────────────────────────────────────────

ATR = 5.0
ENTRY = 100.0


def _make_ohlcv(closes: list[float], *, high_pad: float = 0.5, low_pad: float = 0.5):
    """Igual que en ``tests/test_atr_stops.py``: sobre un close estable el TR
    por barra es ``high_pad + low_pad``, así que el ATR converge a ese valor."""
    closes_a = np.asarray(closes, dtype=float)
    idx = pd.date_range(end=pd.Timestamp.today().normalize(), periods=len(closes_a), freq="B")
    return pd.DataFrame(
        {
            "Open": np.r_[closes_a[0], closes_a[:-1]],
            "High": closes_a + high_pad,
            "Low": closes_a - low_pad,
            "Close": closes_a,
            "Volume": np.full(len(closes_a), 1_000_000.0),
        },
        index=idx,
    )


def _gate_reason(price: float, hwm: float, **kw) -> str | None:
    """Prefijo del ``reason`` del gate (el replay devuelve solo el prefijo)."""
    kw.setdefault("stop_mult", 2.0)
    kw.setdefault("tp_mult", 4.0)
    kw.setdefault("trail_enabled", True)
    reason, _ = atr_exit_decision(
        current_price=price, avg_cost=ENTRY, high_water_mark=hwm, atr_value=ATR, **kw
    )
    return reason.split(" ")[0] if reason else None


# Rejilla de paridad: barre las tres barreras y las zonas muertas entre ellas.
# Los HWM cubren el trailing desarmado (≤ entry+1×ATR) y armado.
_PRICES = [60.0, 85.0, 89.9, 90.0, 90.1, 99.0, 105.0, 109.0, 110.0, 119.9, 120.0, 130.0]
_HWMS = [100.0, 104.9, 105.0, 105.1, 110.0, 120.0, 140.0]
_PARITY_GRID = [(p, h) for p in _PRICES for h in _HWMS]


# ── 1. Paridad con el brazo que la T37 midió ──────────────────────────────────


class TestParidadConElHarness:
    """El gate cableado tiene que decidir *exactamente* lo mismo que el
    instrumento con el que se tomó la decisión. Si esto se rompe, lo que está
    en vivo no es el brazo validado."""

    @pytest.mark.parametrize("price,hwm", _PARITY_GRID)
    def test_candidato_soff_t2_es_el_stop_mult_1e9_del_replay(self, price, hwm):
        """`hard_stop_enabled=False` (engine) == `stop_mult=1e9` (harness).

        Es la equivalencia que hace que el cableado shipee `soff_t2.0` y no
        una variante. El harness apaga el stop duro empujando el nivel fuera
        del dominio de precios; el engine lo apaga con un switch, sin tocar
        `atr_stop_mult` (que sigue valiendo para el R:R y para volver atrás).
        """
        gate = _gate_reason(
            price, hwm, stop_mult=2.0, trail_mult=2.0, hard_stop_enabled=False
        )
        replay = atr_exit(
            current_price=price, avg_cost=ENTRY, high_water_mark=hwm, atr_value=ATR,
            p=AtrParams(stop_mult=1e9, trail_mult=2.0),
        )
        assert gate == replay

    @pytest.mark.parametrize("price,hwm", _PARITY_GRID)
    def test_default_acoplado_es_el_trail_mult_none_del_replay(self, price, hwm):
        """El default (`trail_mult=None`) reproduce el acople histórico."""
        gate = _gate_reason(price, hwm, stop_mult=2.0)
        replay = atr_exit(
            current_price=price, avg_cost=ENTRY, high_water_mark=hwm, atr_value=ATR,
            p=AtrParams(stop_mult=2.0, trail_mult=None),
        )
        assert gate == replay

    @pytest.mark.parametrize("price,hwm", _PARITY_GRID)
    def test_desacople_parcial_tambien_espeja(self, price, hwm):
        """Stop en 2.0 y trailing en 3.0: la celda `s2.0_t3.0` de la rejilla."""
        gate = _gate_reason(price, hwm, stop_mult=2.0, trail_mult=3.0)
        replay = atr_exit(
            current_price=price, avg_cost=ENTRY, high_water_mark=hwm, atr_value=ATR,
            p=AtrParams(stop_mult=2.0, trail_mult=3.0),
        )
        assert gate == replay

    def test_la_rejilla_de_paridad_ejercita_las_tres_barreras(self):
        """Guardrail del propio test: una rejilla que nunca dispara nada
        pasaría los tres tests de arriba sin probar nada."""
        vistos = {
            atr_exit(
                current_price=p, avg_cost=ENTRY, high_water_mark=h, atr_value=ATR,
                p=AtrParams(stop_mult=2.0, trail_mult=2.0),
            )
            for p, h in _PARITY_GRID
        }
        assert vistos == {None, "atr_stop", "atr_trail", "atr_tp"}


# ── 2. effective_trail_mult ───────────────────────────────────────────────────


class TestEffectiveTrailMult:
    def test_none_cae_al_stop(self):
        assert effective_trail_mult(2.0, None) == 2.0

    def test_cero_es_el_sentinela_de_seguir_al_stop(self):
        assert effective_trail_mult(2.5, TRAIL_MULT_FOLLOWS_STOP) == 2.5
        assert effective_trail_mult(2.5, 0.0) == 2.5

    def test_valor_positivo_desacopla(self):
        assert effective_trail_mult(2.0, 3.0) == 3.0

    def test_espeja_a_atrparams(self):
        """Misma semántica que ``AtrParams.effective_trail_mult`` — es el
        contrato que sostiene los tests de paridad."""
        for stop, trail in [(2.0, None), (2.0, 3.0), (4.0, 2.0), (2.0, 2.0)]:
            assert effective_trail_mult(stop, trail) == AtrParams(
                stop_mult=stop, trail_mult=trail
            ).effective_trail_mult


# ── 3. Semántica del gate ─────────────────────────────────────────────────────


class TestGateHardStopSwitch:
    def test_hard_stop_off_no_dispara_el_stop(self):
        """Precio muy por debajo del nivel del stop y el gate no vende: el
        HWM está en la entrada, así que el trailing tampoco está armado."""
        reason, level = atr_exit_decision(
            current_price=60.0, avg_cost=ENTRY, high_water_mark=ENTRY, atr_value=ATR,
            stop_mult=2.0, tp_mult=4.0, trail_enabled=True, hard_stop_enabled=False,
        )
        assert reason is None and level is None

    def test_hard_stop_on_es_el_default(self):
        reason, level = atr_exit_decision(
            current_price=60.0, avg_cost=ENTRY, high_water_mark=ENTRY, atr_value=ATR,
            stop_mult=2.0, tp_mult=4.0, trail_enabled=True,
        )
        assert reason is not None and reason.startswith("atr_stop")
        assert level == 90.0

    def test_sin_stop_duro_el_trailing_sigue_vivo(self):
        """La barrera que queda. HWM=120 (armado), trail 2.0 → nivel 110."""
        reason, level = atr_exit_decision(
            current_price=109.0, avg_cost=ENTRY, high_water_mark=120.0, atr_value=ATR,
            stop_mult=2.0, tp_mult=4.0, trail_enabled=True,
            trail_mult=2.0, hard_stop_enabled=False,
        )
        assert reason is not None and reason.startswith("atr_trail")
        assert level == 110.0

    def test_sin_stop_duro_el_take_profit_sigue_vivo(self):
        reason, level = atr_exit_decision(
            current_price=121.0, avg_cost=ENTRY, high_water_mark=121.0, atr_value=ATR,
            stop_mult=2.0, tp_mult=4.0, trail_enabled=True, hard_stop_enabled=False,
        )
        assert reason is not None and reason.startswith("atr_tp")
        assert level == 120.0

    def test_apagar_el_stop_no_toca_stop_mult(self):
        """`atr_stop_mult` sigue siendo el número que gobierna el nivel cuando
        el switch vuelve a True — apagar no es re-calibrar."""
        kw = dict(
            current_price=89.0, avg_cost=ENTRY, high_water_mark=ENTRY, atr_value=ATR,
            stop_mult=2.0, tp_mult=4.0, trail_enabled=True,
        )
        assert atr_exit_decision(**kw, hard_stop_enabled=False)[0] is None
        assert atr_exit_decision(**kw, hard_stop_enabled=True)[1] == 90.0


class TestGateTrailMult:
    def test_trail_mult_mueve_el_nivel_sin_mover_el_stop(self):
        """Trailing en 3.0 con stop en 2.0: nivel = 120 − 3×5 = 105."""
        reason, level = atr_exit_decision(
            current_price=104.0, avg_cost=ENTRY, high_water_mark=120.0, atr_value=ATR,
            stop_mult=2.0, tp_mult=4.0, trail_enabled=True, trail_mult=3.0,
        )
        assert reason is not None and reason.startswith("atr_trail")
        assert level == 105.0

    def test_trail_mas_ancho_no_dispara_donde_el_acoplado_si(self):
        """Precio 109: con el trailing acoplado (2.0) el nivel es 110 y vende;
        con el trailing en 3.0 el nivel es 105 y aguanta. Es el desacople."""
        acoplado, _ = atr_exit_decision(
            current_price=109.0, avg_cost=ENTRY, high_water_mark=120.0, atr_value=ATR,
            stop_mult=2.0, tp_mult=4.0, trail_enabled=True,
        )
        desacoplado, _ = atr_exit_decision(
            current_price=109.0, avg_cost=ENTRY, high_water_mark=120.0, atr_value=ATR,
            stop_mult=2.0, tp_mult=4.0, trail_enabled=True, trail_mult=3.0,
        )
        assert acoplado is not None and acoplado.startswith("atr_trail")
        assert desacoplado is None

    def test_el_reason_cita_el_multiplo_del_trailing(self):
        """El texto va al ``PaperOrder.reason`` y es lo que Chapa lee en la UI:
        con el trailing desacoplado tiene que decir 3.0, no el 2.0 del stop."""
        reason, _ = atr_exit_decision(
            current_price=104.0, avg_cost=ENTRY, high_water_mark=120.0, atr_value=ATR,
            stop_mult=2.0, tp_mult=4.0, trail_enabled=True, trail_mult=3.0,
        )
        assert reason is not None
        assert "3.0×ATR" in reason
        assert "2.0×ATR" not in reason

    def test_trail_mult_cero_es_el_comportamiento_historico(self):
        con_cero, lvl_cero = atr_exit_decision(
            current_price=109.0, avg_cost=ENTRY, high_water_mark=120.0, atr_value=ATR,
            stop_mult=2.0, tp_mult=4.0, trail_enabled=True, trail_mult=0.0,
        )
        sin_knob, lvl_sin = atr_exit_decision(
            current_price=109.0, avg_cost=ENTRY, high_water_mark=120.0, atr_value=ATR,
            stop_mult=2.0, tp_mult=4.0, trail_enabled=True,
        )
        assert (con_cero, lvl_cero) == (sin_knob, lvl_sin)

    @pytest.mark.parametrize("bad", [-1.0, float("nan"), float("inf")])
    def test_trail_mult_degenerado_falla_cerrado(self, bad):
        """Un múltiplo inválido no vende: mismo criterio defensivo que el
        resto de los inputs del gate."""
        assert atr_exit_decision(
            current_price=60.0, avg_cost=ENTRY, high_water_mark=140.0, atr_value=ATR,
            stop_mult=2.0, tp_mult=4.0, trail_enabled=True, trail_mult=bad,
        ) == (None, None)

    def test_trail_disabled_gana_sobre_trail_mult(self):
        """El switch del trailing manda: setear el múltiplo no lo reactiva."""
        reason, _ = atr_exit_decision(
            current_price=104.0, avg_cost=ENTRY, high_water_mark=120.0, atr_value=ATR,
            stop_mult=2.0, tp_mult=4.0, trail_enabled=False, trail_mult=3.0,
        )
        assert reason is None


# ── 4. Display: sin stop duro no hay R:R ──────────────────────────────────────


class TestEntryRiskLevelsSinStopDuro:
    def test_stop_y_rr_quedan_indefinidos(self):
        """No se proyecta un "nivel de trailing" a la entrada: a la entrada el
        trailing **no está armado** (necesita HWM > entry + 1×ATR), así que ese
        nivel sería un stop que no puede dispararse."""
        lv = entry_risk_levels(
            entry_price=ENTRY, atr_value=ATR, stop_mult=2.0, tp_mult=4.0,
            hard_stop_enabled=False,
        )
        assert lv is not None
        assert lv["stop"] is None
        assert lv["rr"] is None

    def test_el_tp_y_el_atr_sobreviven(self):
        """La barrera de arriba no cambió (T23 la dejó en 4.0)."""
        lv = entry_risk_levels(
            entry_price=ENTRY, atr_value=ATR, stop_mult=2.0, tp_mult=4.0,
            hard_stop_enabled=False,
        )
        assert lv["tp"] == pytest.approx(120.0)
        assert lv["atr"] == pytest.approx(ATR)
        assert lv["entry"] == pytest.approx(ENTRY)

    def test_default_no_cambia_nada(self):
        con = entry_risk_levels(
            entry_price=ENTRY, atr_value=ATR, stop_mult=2.0, tp_mult=4.0,
            hard_stop_enabled=True,
        )
        sin_knob = entry_risk_levels(
            entry_price=ENTRY, atr_value=ATR, stop_mult=2.0, tp_mult=4.0,
        )
        assert con == sin_knob
        assert con["stop"] == pytest.approx(90.0)
        assert con["rr"] == pytest.approx(2.0)

    def test_la_nota_lo_dice_en_vez_de_inventar_un_nivel(self):
        nota = format_entry_risk_note(
            entry_risk_levels(
                entry_price=ENTRY, atr_value=ATR, stop_mult=2.0, tp_mult=4.0,
                hard_stop_enabled=False,
            )
        )
        assert nota is not None
        assert "sin stop duro" in nota
        assert "TP $120.00" in nota
        assert "$" not in nota.split("·")[1]  # el tramo del stop no trae precio

    def test_la_nota_clasica_no_cambia(self):
        nota = format_entry_risk_note(
            entry_risk_levels(
                entry_price=ENTRY, atr_value=ATR, stop_mult=2.0, tp_mult=4.0,
            )
        )
        assert nota == "R:R 2.0 · stop $90.00 · TP $120.00"


# ── 5. Settings ───────────────────────────────────────────────────────────────


class TestSettingsSchema:
    def test_los_dos_knobs_existen(self):
        assert "atr_trail_mult" in SCHEMA
        assert "atr_hard_stop_enabled" in SCHEMA

    def test_los_defaults_preservan_el_comportamiento(self):
        """Es la decisión de la tarea: se shipea el mecanismo, no el cambio de
        política. Prender el candidato es setear los dos a mano."""
        assert DEFAULTS["atr_trail_mult"] == 0.0
        assert DEFAULTS["atr_hard_stop_enabled"] is True

    def test_trail_mult_valida_rango(self):
        assert settings.set("atr_trail_mult", 2.0) is True
        assert settings.get("atr_trail_mult") == 2.0
        assert settings.set("atr_trail_mult", -1.0) is False
        assert settings.set("atr_trail_mult", 99.0) is False
        assert settings.get("atr_trail_mult") == 2.0  # no lo pisó

    def test_hard_stop_enabled_es_bool_estricto(self):
        assert settings.set("atr_hard_stop_enabled", False) is True
        assert settings.get("atr_hard_stop_enabled") is False
        assert settings.set("atr_hard_stop_enabled", "no") is False


# ── 6. Engine ─────────────────────────────────────────────────────────────────


def _pos(account_id: int, ticker: str, hwm: float) -> PaperPosition:
    return PaperPosition(
        account_id=account_id, ticker=ticker, shares=10.0,
        avg_cost=ENTRY, high_water_mark=hwm,
    )


def _exits(account_id: int, price: float, df):
    with session_scope() as s:
        positions = (
            s.query(PaperPosition).filter(PaperPosition.account_id == account_id).all()
        )
        return _compute_atr_forced_exits(
            positions, prices={"AAPL": price}, history_provider=lambda _t: df
        )


class TestEngineWiring:
    """El gate puro ya está probado arriba; acá se prueba que el engine
    **lee los settings nuevos** — que es donde vive el bug de cableado."""

    def test_hard_stop_off_no_fuerza_la_salida(self, test_db):
        settings.set("atr_stops_enabled", True)
        settings.set("atr_stop_mult", 2.0)
        settings.set("atr_tp_mult", 50.0)
        settings.set("atr_hard_stop_enabled", False)
        a = create_account(name="A", initial_capital=10_000.0)
        with session_scope() as s:
            s.add(_pos(a.id, "AAPL", ENTRY))
        # ATR≈1.0 ⇒ stop@98. Precio 95 lo perfora; el trailing no está armado.
        assert _exits(a.id, 95.0, _make_ohlcv([100.0] * 60)) == []

    def test_default_sigue_forzando_la_salida(self, test_db):
        """Regresión: sin tocar los knobs nuevos, el engine hace lo de antes."""
        settings.set("atr_stops_enabled", True)
        settings.set("atr_stop_mult", 2.0)
        settings.set("atr_tp_mult", 50.0)
        a = create_account(name="A", initial_capital=10_000.0)
        with session_scope() as s:
            s.add(_pos(a.id, "AAPL", ENTRY))
        exits = _exits(a.id, 95.0, _make_ohlcv([100.0] * 60))
        assert len(exits) == 1
        assert exits[0].reason.startswith("atr_stop")

    def test_sin_stop_duro_el_trailing_sigue_saliendo(self, test_db):
        """La barrera que queda en el candidato, cableada de punta a punta."""
        settings.set("atr_stops_enabled", True)
        settings.set("atr_stop_mult", 2.0)
        settings.set("atr_tp_mult", 50.0)
        settings.set("atr_trail_enabled", True)
        settings.set("atr_trail_mult", 2.0)
        settings.set("atr_hard_stop_enabled", False)
        a = create_account(name="A", initial_capital=10_000.0)
        with session_scope() as s:
            s.add(_pos(a.id, "AAPL", 110.0))  # HWM > entry + 1×ATR ⇒ armado
        # ATR≈1.0 ⇒ trail@108. Precio 107 lo perfora.
        exits = _exits(a.id, 107.0, _make_ohlcv([100.0] * 60))
        assert len(exits) == 1
        assert exits[0].reason.startswith("atr_trail")

    def test_trail_mult_del_engine_mueve_el_nivel(self, test_db):
        """Trailing en 4.0 (nivel 106) contra el acoplado en 2.0 (nivel 108):
        a 107 el acoplado vende y el desacoplado aguanta."""
        settings.set("atr_stops_enabled", True)
        settings.set("atr_stop_mult", 2.0)
        settings.set("atr_tp_mult", 50.0)
        settings.set("atr_hard_stop_enabled", False)
        settings.set("atr_trail_mult", 4.0)
        a = create_account(name="A", initial_capital=10_000.0)
        with session_scope() as s:
            s.add(_pos(a.id, "AAPL", 110.0))
        df = _make_ohlcv([100.0] * 60)
        assert _exits(a.id, 107.0, df) == []
        exits = _exits(a.id, 105.0, df)
        assert len(exits) == 1
        assert exits[0].reason.startswith("atr_trail")

    def test_la_nota_de_riesgo_de_la_buy_no_inventa_stop(self, test_db):
        """`_buy_risk_note` es display-only (regla 3) pero tiene que leer el
        switch: sin stop duro no puede seguir mostrando un R:R de 2.0."""
        from paper_trading.engine import _buy_risk_note

        settings.set("atr_stop_mult", 2.0)
        settings.set("atr_tp_mult", 4.0)
        settings.set("atr_hard_stop_enabled", False)
        df = _make_ohlcv([100.0] * 60)
        nota = _buy_risk_note("AAPL", ENTRY, lambda _t: df)
        assert nota is not None
        assert "sin stop duro" in nota

    def test_la_nota_de_riesgo_por_default_no_cambia(self, test_db):
        from paper_trading.engine import _buy_risk_note

        settings.set("atr_stop_mult", 2.0)
        settings.set("atr_tp_mult", 4.0)
        df = _make_ohlcv([100.0] * 60)
        nota = _buy_risk_note("AAPL", ENTRY, lambda _t: df)
        assert nota is not None
        assert "R:R 2.0" in nota
        assert "stop $" in nota
