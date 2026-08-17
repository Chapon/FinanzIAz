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

La T26 (STOP-CAL) sumó un **cuarto** desvío que la T27 no había nombrado: el
**precio contra el que se deciden las barreras ATR** (close diario en el harness,
intradía en el engine). A diferencia de los otros tres, éste no depende de cómo
se invoque el harness —es estructural de ``replay_cycle``— y toca a los cinco
harness de salida de la serie. Ver ``LIVE_EXIT_EVAL_DESC`` más abajo.

La 26b destapó el **quinto**, que es de otra especie: los otros cuatro son
diferencias *declarables* entre dos cosas defendibles, y éste era un **defecto**
—look-ahead en el fill de la barrera decidida al close— que dio vuelta el
hallazgo central de la T26. La Tarea 33 lo declara acá, invierte el default de
``fill_mode`` a la variante honesta y re-lee los veredictos que corrieron con el
legacy. Ver ``HARNESS_FILL_MODE`` más abajo.

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

# ── Precio de evaluación de las barreras — el desvío que destapó la T26 ──────
# ``scaleout_replay.replay_cycle`` decide **toda** salida ATR contra el **close
# diario** (``atr_exit(current_price=close_i, …)``): una barra cuyo *mínimo*
# perforó el nivel pero cuyo *close* se recuperó **no dispara**. El engine vivo
# decide contra el **precio corriente intradía** (``get_bulk_prices`` =
# *"current prices"*, ``engine.py:627``) en cada scan (~15 min), así que esa
# misma barra **sí** sale.
#
# Afecta a los CINCO harness de salida de la serie (T7, T23, T13, T21, T26),
# porque todos corren sobre ``replay_cycle``. No invalida sus veredictos —igual
# que los slots de la T27— pero **sesga de forma asimétrica según la barrera**:
# el harness sub-dispara siempre, y el sesgo crece cuanto más ajustado el
# múltiplo. En el stop eso hace que mida un stop *confirmado al close*, más
# benigno que el vivo; en el take-profit implica que la T23 pudo haber
# **subestimado** el beneficio de aflojar el TP.
#
# La 26b lo **cuantificó** en el múltiplo vivo y a 10 slots: el modo ``close``
# mide **+3.39 pp de CAGR por encima** de la regla que el engine ejecuta.
# Ninguno de los dos modos ES producción: ``close`` es la cota **inferior** de
# frecuencia de disparo y ``touch`` la **superior**; el engine samplea c/15 min,
# así que queda entre las dos y más cerca de ``touch``.
LIVE_EXIT_EVAL_DESC = "precio corriente intradía (scan ~15 min)"
PIT_EXIT_EVAL_DESC = "close diario"
TOUCH_EXIT_EVAL_DESC = "toque intradía del extremo de la barra"

# ── Fill de las barreras — el quinto desvío, lo destapó la 26b (Tarea 33) ────
# La frase que este bloque reemplaza decía *"el fill sí está modelado; la decisión
# no"*. **Era falsa en modo ``close``**, y esa media verdad tapó el defecto durante
# cinco harness: ``replay_cycle`` decidía la barrera contra el close y la llenaba
# en el **nivel** (``_exit_fill_price``, modelo de *orden en reposo*). Como al
# disparar al close vale ``low ≤ close ≤ nivel``, el fill legacy devolvía
# **siempre** el nivel — un precio mejor que el close y tocado *antes* de que
# existiera la información que tomó la decisión. Eso es look-ahead, no una
# convención discutible, y valía ``LOOKAHEAD_FILL_COST_DESC``.
#
# La Tarea 33 invirtió el default a ``"decision"``. Con el default honesto el
# harness sigue **sin** coincidir con el engine, pero ahora por el lado
# conservador: el engine llena con el modelo de orden en reposo
# (``gates.model_exit_fill_price``, ``engine.py:427``) y el harness al close que
# decidió. Bajo ``eval_mode="touch"`` los dos fill_mode coinciden **y coinciden
# con el engine**: ahí el precio que decide *es* el nivel.
HARNESS_FILL_MODE = "decision"
LEGACY_FILL_MODE = "resting"
LIVE_FILL_DESC = "modelo de orden en reposo en el nivel (gates.model_exit_fill_price)"
LOOKAHEAD_FILL_COST_DESC = (
    "+5.01 pp de CAGR al múltiplo vivo y +20.97 pp a 1.0×ATR, 10 slots "
    "(docs/stop_price_t26b_2026-08-16.md §2)"
)


@dataclass(frozen=True)
class HarnessConfig:
    """La config con la que efectivamente corre un harness."""

    max_positions: int
    universe_file: str
    n_tickers: int
    # Config con la que corrió el veredicto ya publicado de esa tarea, si lo hay.
    # Sirve para que el banner avise que un default nuevo no lo reproduce.
    verdict_max_positions: int | None = None
    # Regla de salida simulada (Tareas 26b/33). Los defaults son los de
    # ``replay_cycle``, así que un runner que no los pase declara lo que corre.
    eval_mode: str = "close"
    fill_mode: str = HARNESS_FILL_MODE


def exit_rule_line(eval_mode: str = "close", fill_mode: str = HARNESS_FILL_MODE) -> str:
    """Una línea que dice **qué regla de salida** se está simulando.

    Se imprime siempre (aunque no hubiera desvíos) porque las dos mitades —contra
    qué precio se decide la barrera y a qué precio se llena— son las que la serie
    T7→T26 arrastró sin nombrar, y la segunda ni siquiera estaba en el banner.
    Toma los modos sueltos (y no un ``HarnessConfig``) para que la use también el
    T7, que corre con capital ilimitado y no tiene config de cartera.
    """
    decide = PIT_EXIT_EVAL_DESC if eval_mode == "close" else TOUCH_EXIT_EVAL_DESC
    fill = ("al precio que tomó la decisión" if fill_mode == HARNESS_FILL_MODE
            else "orden en reposo en el nivel (LEGACY)")
    return f"Regla de salida simulada: barrera decidida al {decide} · fill {fill}"


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
    # Ídem el precio contra el que se deciden las barreras ATR: es estructural de
    # ``replay_cycle``, así que no depende de cómo se llame al harness. Lo que sí
    # depende del brazo es de qué lado del engine cae el desvío.
    if cfg.eval_mode == "close":
        out.append(
            f"barreras ATR decididas al {PIT_EXIT_EVAL_DESC} vs {LIVE_EXIT_EVAL_DESC} "
            f"en vivo (cota INFERIOR de frecuencia de disparo: mide +3.39pp de CAGR "
            f"de más que la regla viva, T26b §1)"
        )
    else:
        out.append(
            f"barreras ATR decididas al {TOUCH_EXIT_EVAL_DESC} vs "
            f"{LIVE_EXIT_EVAL_DESC} en vivo (cota SUPERIOR de frecuencia de disparo)"
        )
    # Y el fill de esa barrera, que es el quinto desvío (T33). El caso legacy en
    # modo ``close`` no es un desvío: es un defecto, y se anuncia como tal.
    if cfg.fill_mode == LEGACY_FILL_MODE and cfg.eval_mode == "close":
        out.append(
            f"LOOK-AHEAD ACTIVO — la barrera se decide al {PIT_EXIT_EVAL_DESC} y se "
            f"llena en el NIVEL: un precio mejor que el close y tocado ANTES de la "
            f"información que decidió. Vale {LOOKAHEAD_FILL_COST_DESC}. "
            f"Sólo para reproducir T7/T23/T13/T21/T26"
        )
    elif cfg.eval_mode == "close":
        out.append(
            f"fill de la barrera al close que la decidió vs {LIVE_FILL_DESC} en vivo "
            f"(desvío conservador: el harness cobra el peor de los dos precios)"
        )
    # Bajo ``touch`` los dos fill_mode coinciden **y coinciden con el engine** (el
    # precio que decide es el nivel), así que ahí no hay nada que declarar.
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
        exit_rule_line(cfg.eval_mode, cfg.fill_mode),
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
    eval_mode: str = "close",
    fill_mode: str = HARNESS_FILL_MODE,
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
        eval_mode=eval_mode,
        fill_mode=fill_mode,
    )
    print(config_banner(cfg) + "\n", file=file if file is not None else sys.stdout)
    return cfg
