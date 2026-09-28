"""Tarea 233 — DESVIOS-TEXTO-VS-VALOR-VIVO.

Tres textos del registro de desvíos contradecían al valor vivo o al motor actual, y la
auditoría del 2026-09-11 no podía verlos porque los contrastó **contra el código**:

- **[D-3] `universe_screen`** decía que en vivo el screen dropea *«por ADV$/fragilidad
  fundamental»*. El código tiene la pata de ADV$; el valor vivo
  (`paper_universe_min_adv_dollars = 0.0`) la **apaga**. Ahora el texto se deriva de dos
  espejos que el guard de la 130 compara contra el settings vivo.
- **[D-4.1]** el comentario de `dividendos` decía que el motor no los mira; desde la 222
  los acredita.
- **[D-4.2]** `regime_scale` decía *«0 de 62 BUY vivas»* sin fecha, leído como actual.

El caso vivo (piso en 0) es justamente donde el texto viejo y el nuevo **difieren**, así que
los tests de abajo no pasan con el defecto puesto.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import analysis.harness_config as hc
from analysis.harness_config import (
    LIVE_MAX_POSITIONS,
    LIVE_WATCHLIST_SIZE,
    HarnessConfig,
    deviations_keyed,
)
from data.edgar_fundamentals import FundamentalFacts
from paper_trading.universe import REASON_ADV, REASON_FRAGILE, UniverseThresholds, screen_candidate

_REPO = Path(__file__).resolve().parent.parent


def _cfg() -> HarnessConfig:
    return HarnessConfig(LIVE_MAX_POSITIONS, "x.txt", LIVE_WATCHLIST_SIZE)


def _textos() -> dict[str, str]:
    return {d.clave: d.texto for d in deviations_keyed(_cfg())}


def _screen() -> str:
    return _textos()["universe_screen"]


# ── [D-3] el texto del screen sale de las patas vivas ───────────────────────


def test_con_el_piso_de_ADV_en_CERO_el_texto_no_nombra_la_pata_de_liquidez():
    """El estado vivo, y el que el texto viejo describía mal."""
    assert hc.LIVE_UNIVERSE_MIN_ADV_DOLLARS == 0.0
    texto = _screen()
    assert "ADV$" not in texto
    assert "fragilidad fundamental" in texto
    assert "la única pata encendida" in texto


def test_con_el_piso_de_ADV_PRENDIDO_el_texto_nombra_las_dos(monkeypatch):
    monkeypatch.setattr(hc, "LIVE_UNIVERSE_MIN_ADV_DOLLARS", 5_000_000.0)
    texto = _screen()
    assert "ADV$ por debajo de 5,000,000 USD" in texto
    assert "fragilidad fundamental" in texto
    assert "única pata" not in texto


def test_con_las_dos_patas_apagadas_dice_que_no_dropea_a_nadie(monkeypatch):
    monkeypatch.setattr(hc, "LIVE_UNIVERSE_FUNDAMENTALS_ENABLED", False)
    texto = _screen()
    assert "ADV$" not in texto
    assert "fragilidad" not in texto
    assert "no dropea a nadie" in texto


@pytest.mark.parametrize("min_adv", [0.0, 5_000_000.0])
@pytest.mark.parametrize("fundamentales", [True, False])
def test_las_patas_del_texto_son_las_que_EXCLUYEN_en_screen_candidate(monkeypatch, min_adv, fundamentales):
    """El texto no puede tener una regla propia de qué pata corre: se contrasta contra la
    función pura del screen, con un candidato ilíquido **y** frágil (tipo MLTX), una pata
    por vez para que la primera que gana no tape a la otra."""
    monkeypatch.setattr(hc, "LIVE_UNIVERSE_MIN_ADV_DOLLARS", min_adv)
    monkeypatch.setattr(hc, "LIVE_UNIVERSE_FUNDAMENTALS_ENABLED", fundamentales)
    umbrales = UniverseThresholds(min_adv_dollars=min_adv, fundamentals_enabled=fundamentales)
    fragil = FundamentalFacts("MLTX", net_income_annual=(("2025-12-31", -227e6), ("2024-12-31", -118e6)))

    liquidez_excluye = screen_candidate("MLTX", 1_000_000.0, None, umbrales).reason == REASON_ADV
    fundamental_excluye = screen_candidate("MLTX", None, fragil, umbrales).reason == REASON_FRAGILE

    patas = hc.universe_screen_patas()
    assert any(p.startswith("ADV$") for p in patas) is liquidez_excluye
    assert any(p.startswith("fragilidad") for p in patas) is fundamental_excluye
    assert len(patas) == liquidez_excluye + fundamental_excluye


# ── [D-4.2] un conteo vivo lleva fecha ──────────────────────────────────────

_CONTEO = re.compile(r"\b\d+ de \d+ BUY[^.;:]*")
_FECHA = re.compile(r"\d{4}-\d{2}-\d{2}")


def test_todo_conteo_de_BUY_vivas_en_los_desvios_lleva_FECHA():
    conteos = [m.group(0) for t in _textos().values() for m in _CONTEO.finditer(t)]
    assert conteos, "no se encontró ningún conteo: el patrón ya no mira nada"
    sin_fecha = [c for c in conteos if not _FECHA.search(c)]
    assert not sin_fecha, f"conteos presentados como actuales sin fecha: {sin_fecha}"


def test_el_patron_de_conteo_ACUSA_uno_sin_fecha():
    """Contraprueba del instrumento: el texto viejo tiene que caer."""
    viejo = "0 de 62 BUY vivas lo dispararon, pero el 15.96% de las ruedas"
    (c,) = [m.group(0) for m in _CONTEO.finditer(viejo)]
    assert not _FECHA.search(c)


# ── [D-4.1] el comentario de dividendos describe el motor de hoy ────────────


def test_el_comentario_de_dividendos_ya_no_dice_que_el_motor_no_los_mira():
    fuente = (_REPO / "analysis" / "harness_config.py").read_text(encoding="utf-8")
    assert "el motor no tiene forma" not in fuente
    assert "hasta que la 221 lo cierre" not in fuente


# ── la regla de método, en la skill ─────────────────────────────────────────


def test_la_skill_de_auditoria_tiene_la_regla_del_valor_vivo():
    skill = (_REPO / ".claude" / "skills" / "auditoria" / "SKILL.md").read_text(encoding="utf-8")
    seccion_c = " ".join(skill.split("### C.", 1)[1].split("### D.", 1)[0].split())
    assert "contra el valor vivo" in seccion_c
    assert "lleva **fecha** o se **deriva**" in seccion_c
