"""
Config de referencia de los harness — **Tarea 27 (HARNESS-CFG)**.

Por qué existe
-------------
Los harness de la serie (T7→T13) no corren contra una cuenta —y está bien: un
backtest de 10 años no puede correr sobre una cuenta viva de 7 semanas— pero
entonces *"¿contra qué cuenta?"* se traduce en *"¿con qué config?"*, y la config
que venían usando (`max_positions=5`, 41 tickers) es la de la **cuenta 1, pausada
desde el 2026-07-01**. La cuenta viva es la **2**: 10 slots y 128 tickers.
Ninguno de los desvíos estaba declarado en ningún pre-registro
(`docs/deep_analysis_2026-08-12.md` §1).

Esto no invalida los veredictos publicados: las afirmaciones sobre la **señal**
(T9 AUC 0.498, T11b robustez de régimen, T12 insider en stress, T10 sizing por
nombre) no dependen de cuántos slots hay. Sí se mueven las que dependen de
**escasez de slots** — T23 (su NO-SHIP sale de la cascada de path con slots
finitos), T13(b) (su "sin población" sale de la tenencia del harness) y la 21
(el ranking decide más cuanto peor es el ratio de selección).

Qué provee
----------
Un solo lugar donde vive la config de la cuenta viva, para que un harness nuevo
no pueda volver a heredar en silencio la de una cuenta apagada, y un **banner**
que imprime la config usada y **nombra los desvíos** — el objetivo de la tarea no
es que todo coincida a la fuerza, sino que *coincida o que el desvío esté escrito*.

Es lógica pura (stdlib): sin red, sin DB. Los valores se refrescan con
``scripts/refresh_live_universe.py``, que sí lee la DB.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import TextIO

# ── Cuenta viva (verificado 2026-08-12 contra paper_accounts) ────────────────
LIVE_ACCOUNT_ID = 2
LIVE_ACCOUNT_NAME = "Sim Segundo"
LIVE_MAX_POSITIONS = 10
LIVE_MODE = "auto"
LIVE_ALLOCATION_MODE = "equal_weight"
LIVE_WATCHLIST_SIZE = 128

# Config de la cuenta 1 (pausada), que es la que heredaron T7→T13.
LEGACY_MAX_POSITIONS = 5
LEGACY_ACCOUNT_ID = 1

# Universo de referencia para harness nuevos: la watchlist de la cuenta viva
# recortada a los tickers con artefacto PIT (127/128; falta ASML).
LIVE_UNIVERSE_FILE = "data/harness_universe_live_acct2.txt"
LEGACY_UNIVERSE_FILE = "data/harness_universe_41_10y.txt"

# ── Ventana de `analyze()` — el desvío que NO se corrige acá ─────────────────
# El engine vivo le pasa a ``analyze()`` una ventana **fija** de 2 años
# (``paper_history_period="2y"`` ⇒ ~504 barras). Los artefactos de
# ``data/pit_signals/`` se generaron con ventana **expandida** (250 → ~2.514
# barras). No es el mismo generador de señal: cambian el train set del XGBoost,
# el fit de GARCH, el detector de régimen y el warm-up de SMA200.
#
# Regenerar los artefactos cuesta horas (la corrida de T12 fueron 10,76 h) y
# **cuál de las dos ventanas produce mejor señal es una pregunta aparte**, con su
# propio pre-registro. Acá sólo se declara el desvío para que ningún
# pre-registro futuro lo herede sin saberlo.
LIVE_HISTORY_BARS = 504
PIT_WINDOW_DESC = "expandida (250 → ~2.514 barras)"


@dataclass(frozen=True)
class HarnessConfig:
    """La config con la que efectivamente corre un harness."""

    max_positions: int
    universe_file: str
    n_tickers: int
    # Config con la que corrió el veredicto ya publicado de esa tarea, si lo hay.
    # Sirve para que el banner avise que un default nuevo no lo reproduce.
    verdict_max_positions: int | None = None


def deviations(cfg: HarnessConfig) -> list[str]:
    """Desvíos de ``cfg`` respecto de la cuenta viva, en prosa."""
    out: list[str] = []
    if cfg.max_positions != LIVE_MAX_POSITIONS:
        out.append(
            f"slots {cfg.max_positions} vs {LIVE_MAX_POSITIONS} de la cuenta "
            f"{LIVE_ACCOUNT_ID}"
        )
    if cfg.n_tickers < LIVE_WATCHLIST_SIZE:
        out.append(
            f"universo {cfg.n_tickers} tickers vs {LIVE_WATCHLIST_SIZE} de la watchlist viva"
        )
    # La ventana de señal siempre difiere mientras los artefactos PIT sean los
    # actuales — se declara siempre, no es condicional.
    out.append(
        f"ventana de analyze() {PIT_WINDOW_DESC} vs {LIVE_HISTORY_BARS} barras fijas en vivo"
    )
    return out


def config_banner(cfg: HarnessConfig) -> str:
    """Bloque de texto que todo harness imprime antes de correr.

    Nombra la config usada y los desvíos contra la cuenta viva. Si el veredicto
    publicado de esa tarea corrió con otros slots, lo dice — así un default nuevo
    no rompe la reproducibilidad en silencio.
    """
    lines = [
        f"Config: max_positions={cfg.max_positions} · universo={cfg.universe_file} "
        f"({cfg.n_tickers} tickers)",
        f"Cuenta viva de referencia: {LIVE_ACCOUNT_NAME} (id={LIVE_ACCOUNT_ID}, "
        f"{LIVE_MODE}, {LIVE_ALLOCATION_MODE}, {LIVE_MAX_POSITIONS} slots)",
    ]
    devs = deviations(cfg)
    if devs:
        lines.append("DESVÍOS declarados vs la cuenta viva:")
        lines.extend(f"  · {d}" for d in devs)
    else:
        lines.append("Sin desvíos contra la cuenta viva.")
    if (cfg.verdict_max_positions is not None
            and cfg.verdict_max_positions != cfg.max_positions):
        lines.append(
            f"OJO: el veredicto publicado de esta tarea corrió con "
            f"max_positions={cfg.verdict_max_positions}; para reproducirlo pasá "
            f"--max-positions {cfg.verdict_max_positions}."
        )
    return "\n".join(lines)


def announce(
    max_positions: int,
    universe_file: str,
    n_tickers: int,
    *,
    verdict_max_positions: int | None = None,
    file: TextIO | None = None,
) -> HarnessConfig:
    """Arma la config, **imprime el banner** y la devuelve.

    Es la línea única que cada runner llama antes de simular: así declarar los
    desvíos no depende de que quien escriba el próximo harness se acuerde.
    """
    cfg = HarnessConfig(
        max_positions=max_positions,
        universe_file=universe_file,
        n_tickers=n_tickers,
        verdict_max_positions=verdict_max_positions,
    )
    print(config_banner(cfg) + "\n", file=file if file is not None else sys.stdout)
    return cfg
