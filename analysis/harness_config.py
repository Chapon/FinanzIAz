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

La T34 destapó el **sexto**, en la otra punta del ciclo: los **gates de re-entrada**.
``portfolio_sim`` sólo rechaza un candidato si el ticker ya está abierto; el engine
vivo además bloquea el re-BUY después de un ciclo perdedor reciente (Gate 5) o
después de demasiados ciclos seguidos (Gate 5b). Medido: afecta al **21-36%** de las
entradas tomadas, con **gradiente en el múltiplo del stop**, así que no es un nivel
común y no se cancela solo en la comparación. Ver ``LIVE_WHIPSAW_LOOKBACK_DAYS``.

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

import contextlib
import json
import math
import os
import socket
import statistics
import sys
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, TextIO

# Raíz del repo — para resolver los archivos de universo, que se declaran
# relativos a ella (`data/harness_universe_*.txt`).
_REPO_ROOT = Path(__file__).resolve().parent.parent

# ── Cuenta viva (verificado 2026-08-12 contra paper_accounts) ────────────────
LIVE_ACCOUNT_ID = 2
LIVE_ACCOUNT_NAME = "Sim Segundo"
LIVE_MAX_POSITIONS = 10
LIVE_MODE = "auto"
LIVE_ALLOCATION_MODE = "equal_weight"
# Tamaño de la watchlist de la cuenta viva. Es un número **declarado**, no
# derivado: `deviations()` es pura y la watchlist vive en la DB, así que leerla acá
# sería meterle I/O a una función que hoy no lo tiene. Lo que lo sostiene es un
# test que lo **re-verifica contra la DB** cuando hay DB
# (`tests/test_watchlist_size_t89.py`), en vez de que envejezca solo — que es lo
# que pasaba: era un entero hardcodeado que nada re-chequeaba (tarea 89).
LIVE_WATCHLIST_SIZE = 128

# ── Política de SALIDA de la cuenta viva — Tarea 92 (EXITPOL-HARNESS) ────────
#
# Vive acá y no duplicada en cada runner por el mismo motivo que los slots y el
# universo: hasta la 92 estaba repartida en constantes por script —`LIVE_STOP`,
# `LIVE_TRAIL`, `LIVE_MULT`, `NO_STOP`— en **cinco** archivos, y cuando Chapa
# cambió la política en vivo el **2026-08-27** ninguna se enteró. Peor:
# `run_stop_value_t37.py:116` define `LIVE_STOP, LIVE_TRAIL = 2.0, 2.0`, o sea que
# **la constante que se llama "LIVE" quedó falsa el mismo día que esa tarea
# shipeó**.
#
# El costo de que nadie lo declarara está medido por el propio proyecto
# (`docs/stop_value_t37_2026-08-27.md` §2): el default del harness —stop 2.0,
# trail 2.0— da **2,01%** de CAGR y lo vivo —stop OFF, trail 2.0— da **9,17%**.
# **7,16 pp**, más que el look-ahead del fill (5,01 pp) que se ganó la tarea 33.
#
# Verificado contra `~/.finanzias/settings.json` el 2026-09-02, con el rastro del
# flip en `backups/settings_pre_soff_t2.0_20260827_195731.json`, que difiere de la
# config actual **exactamente** en estas dos claves.
LIVE_HARD_STOP_ENABLED = False  # `atr_hard_stop_enabled` — apagado desde 2026-08-27
LIVE_STOP_MULT = 2.0  # `atr_stop_mult` (el valor sigue, pero el stop está apagado)
LIVE_TRAIL_MULT = 2.0  # `atr_trail_mult` — el candidato `soff_t2.0` de la tarea 37

# El harness no tiene un flag para apagar el stop duro: lo expresa con un múltiplo
# que nunca dispara. `paper_trading/gates.py:113-117` documenta que las dos formas
# son "equivalentes dígito por dígito", y esta constante es la que hace que la
# comparación de `deviations()` pueda cruzarlas.
NO_STOP_MULT = 1e9

# ── Sizing y gates vivos que el harness NO modela — Tareas 94, 95 y 96 ───────
#
# Las tres son perillas **encendidas en la cuenta 2** que ningún runner modela.
# Hasta la auditoría `desvios` del 2026-09-02 la declaración dependía de que el
# autor del pre-registro se acordara de escribirla a mano: el escalado por régimen
# aparecía en **14** pre-registros y el blackout de earnings en **7**, y el overlay
# de volatilidad **en ninguno**. Y el pre-registro más nuevo (T51) dejó de
# enumerarlos y delegó en esta función — o sea que **lo que acá no se diga, no lo
# dice nadie**.
#
# Verificadas contra `~/.finanzias/settings.json` el 2026-09-02.

# Overlay de σ de cartera (tarea 94). `strategies.py:525` lo aplica a **todas** las
# BUY nuevas. Es el que más muerde: **dispara todos los días** (medido en el log:
# `σ=15.8% > target 12.0% … ×0.76`, y `σ=37.2% … ×0.32`).
LIVE_VOL_OVERLAY_ENABLED = True
LIVE_VOL_TARGET_ANNUAL = 0.12

# Escalado por régimen R2b (tarea 95). En risk-off las BUY entran a la mitad.
# **Nunca disparó en vivo** —0 de 62 BUY filled— pero **15,96%** de las ruedas de
# la ventana del harness son risk-off, así que sí muerde en backtest. Medido por
# la T20: ΔCAGR **+0,59 pp** y maxDD **21,6% → 19,1%**.
LIVE_REGIME_SCALE_ENABLED = True
LIVE_REGIME_SCALE_FACTOR = 0.5

# Blackout de earnings, Gate 6 (tarea 96). Bloquea **BUY** con earnings dentro de
# ±N días. **No se puede modelar con los datos que hay**: no existen fechas de
# earnings point-in-time a 10 años (`earnings_cache` arranca el 2026-06-26). Por
# eso se declara en vez de modelarse. Población medida sobre los round-trips
# reales: **15,8%** son near-earnings (`docs/earnings_blackout_replay_2026-06-25.md`).
LIVE_EARNINGS_BLACKOUT_DAYS = 2

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

# ── Gates de re-entrada — el SEXTO desvío, lo destapó la T34 ─────────────────
# ``portfolio_sim`` sólo rechaza una entrada si el ticker **ya está abierto**
# (``allow_reentry_while_open=False``). El engine vivo tiene además dos gates que
# miran **ciclos cerrados** y bloquean el re-BUY:
#
#   * **Gate 5 (anti-whipsaw, ``engine.py:993``)** — bloquea si el último ciclo
#     cerrado del ticker dentro de ``LIVE_WHIPSAW_LOOKBACK_DAYS`` cerró con
#     pérdida. Con ``paper_whipsaw_min_loss_pct=0.0`` —el valor vivo— **cualquier**
#     pérdida bloquea: es el ajuste **más estricto**, no un no-op.
#   * **Gate 5b (anti-churn, ``engine.py:1013``)** — bloquea si hay
#     ``LIVE_CHURN_MAX_CYCLES`` o más ciclos cerrados dentro de
#     ``LIVE_CHURN_LOOKBACK_DAYS``, agnóstico al P/L.
#
# **Por qué no es una nota al pie y por qué la T34 lo modela en vez de sólo
# declararlo:** medido sobre la rejilla de múltiplos del stop, Gate 5 bloquearía
# entre 21,15% y 36,36% de las entradas que el harness toma — y el share se mueve
# **monótonamente con el múltiplo** (36,36% a 1.0×ATR, 21,15% sin stop). Por el
# criterio que dejó la T33 —*"¿los brazos disparan barreras a tasas distintas?"*—
# acá la tasa de stop varía por un factor de 7, así que el desvío **no es un nivel
# común y no se cancela en la comparación**. Un stop ajustado cierra muchos ciclos
# chicos en rojo y cada uno arma en vivo un cooldown de 7 días que el harness
# ignora: le regala re-entradas a los brazos ajustados, y más cuanto más ajustado.
LIVE_WHIPSAW_LOOKBACK_DAYS = 7
LIVE_WHIPSAW_MIN_LOSS_PCT = 0.0
LIVE_CHURN_LOOKBACK_DAYS = 10
LIVE_CHURN_MAX_CYCLES = 3
REENTRY_GATES_COST_DESC = (
    "21,15%-36,36% de los trades que el harness toma SIN gates habrían sido "
    "bloqueados en vivo, con gradiente monótono en el múltiplo del stop "
    "(docs/stop_loosen_prereg_t34_2026-08-18.md §3). Ojo con la etiqueta: es el "
    "TAMAÑO del desvío medido sobre el path sin gates, NO la tasa de bloqueo en "
    "régimen del path ya gateado — el gate es auto-extintivo y ahí da 2,44% "
    "(docs/stop_loosen_enmienda_t34_2026-08-18.md §1)"
)


# ── Ventana de los artefactos — el SÉPTIMO desvío (Tarea 48) ────────────────
# Los artefactos del harness (``data/parquet/*__10y__1d.parquet`` y
# ``data/pit_signals/``) guardan una ventana de 10 años **anclada al día del
# refresh**, no a una fecha fija. Cuando se refrescan, la ventana **rueda**: se
# caen barras del principio y entran del final.
#
# **Por qué importa y no es una nota al pie:** ningún veredicto publicado es
# reproducible dígito a dígito después de un refresh. Medido re-corriendo la T11b
# con su comando publicado un mes después (artefactos refrescados el 2026-08-09):
# ``A_k2.0_m1.5`` da **12.77%** contra los **12.89%** publicados, Sharpe 1.22 vs
# 1.24, y **los nueve brazos perdieron entre 1 y 3 entradas**. No cambió el
# detector ni el simulador: cambió la muestra.
#
# **Lo caro no es el 0.12 pp.** La serie adoptó (26b §5, 47 §5.4, 45 §5.3, 49 §5.2)
# sanity de reproducción con tolerancias de ±0.05 pp, y la regla congelada dice que
# un sanity fallado ⇒ **corrida INVÁLIDA**. Con la ventana rodante ese diseño
# convierte **el paso del tiempo** en corridas inválidas: no distingue *"cambió la
# cañería"* (que es lo que quiere detectar) de *"se movió la muestra"* (que no le
# importa). Por eso el helper de abajo devuelve **tres** estados y no dos.
#
# **La decisión (Tarea 48): se acepta la ventana rodante y se la hace VISIBLE**, en
# vez de anclarla. Anclarla —un ``--end-date`` fijo o un snapshot congelado— daría
# reproducibilidad bit a bit al costo de que el harness deje de ver los datos que la
# cuenta viva sigue acumulando, que es justamente lo que destraba las tareas
# bloqueadas por datos (el Brazo A de la 11). La reproducibilidad se recupera por
# el otro lado: **declarando la ventana efectiva de cada corrida** y haciendo que
# los sanity de reproducción sepan contra qué muestra se midió su número.
#
# **La 52 completó el otro eje.** "Contra qué muestra" son dos cosas —*cuándo* y
# *sobre qué*— y la 48 sólo cubrió la primera: el smoke de la 37 corrió sobre el
# universo legacy con la ventana de siempre y los tres chequeos dictaminaron
# ``FALLA — MISMA ventana ⇒ cambió la cañería`` sin que hubiera cambiado una línea.
# El mismo error de categoría, por el otro eje, y con la misma consecuencia: una
# máquina de invalidar corridas buenas. Por eso el helper también toma la
# **población** y devuelve un cuarto estado, ``REPRO_NA``.
ARTIFACT_PERIOD = "10y"
ARTIFACT_WINDOW_IS_ROLLING = True


@dataclass(frozen=True)
class ArtifactWindow:
    """La ventana efectiva de barras con la que corrió un harness.

    Se computa de las barras ya cargadas (pura, sin I/O): ``start`` es la fecha
    más temprana y ``end`` la más tardía de todo el universo, y ``n_bars`` el
    máximo de barras de un ticker. Dos corridas con la misma tripleta corrieron
    sobre la misma muestra."""

    start: str
    end: str
    n_bars: int

    def __str__(self) -> str:
        return f"{self.start}..{self.end} ({self.n_bars} barras)"


def artifact_window(bars_by: dict[str, list]) -> ArtifactWindow | None:
    """Ventana efectiva de ``{ticker: [Bar]}`` — ``None`` si no hay barras.

    ``Bar`` es una tupla cuyo primer elemento es la fecha ISO-10, así que esto no
    depende de pandas ni toca el disco."""
    starts: list[str] = []
    ends: list[str] = []
    n = 0
    for bars in bars_by.values():
        if not bars:
            continue
        starts.append(bars[0][0])
        ends.append(bars[-1][0])
        n = max(n, len(bars))
    if not starts:
        return None
    return ArtifactWindow(start=min(starts), end=max(ends), n_bars=n)


# ── Frescura del cohorte de artefactos — Tarea 30 (DOC-SYNC) ─────────────────
#
# ``artifact_window`` declara ``min(starts)..max(ends)`` sobre el universo, y esa
# agregación **esconde exactamente el defecto que la 30 vino a arreglar**: un solo
# artefacto congelado no mueve el ``max(ends)`` —lo tapan los otros 505— pero sí
# puede quedarse con el ``min(starts)``, y ahí entra en la ventana publicada sin
# que nada lo declare.
#
# **Y eso ya había pasado, medido el 2026-09-01.** De los 506 artefactos ``10y``,
# **503** terminaban el 2026-08-07 y tres estaban congelados: **SPY** (14 ruedas
# atrás), **TSM** (21) y **MLTX** (48). El ancla publicada de la T48
# —``WINDOW_REFRESH_2026_08_09`` = ``2016-07-11..2026-08-07``— tenía el **end** de
# los 503 sanos y el **start del artefacto congelado de TSM**: al refrescarlo, el
# start del universo se movió a **2016-08-08**. O sea que la ventana con la que se
# declararon las corridas de la serie estaba **construida en parte sobre un
# artefacto viejo**, y la agregación lo hacía invisible. Eso es el hallazgo, no un
# efecto colateral del refresh.
#
# De ahí que este chequeo mire el **cohorte** y no un umbral absoluto de fecha: lo
# que importa no es "¿está viejo?" sino "**¿está desalineado del resto?**". Y mira
# los dos lados —atrasados y adelantados— porque un refresh **parcial** rompe la
# uniformidad igual que uno faltante, que es justo el estado en que quedó TSM.
#
# La referencia es la **moda** de las últimas barras, no el máximo: con el máximo,
# un solo artefacto refrescado de más haría aparecer a los otros 505 como
# atrasados. La moda es el batch, que es lo que se quiere comparar.
#
# La tolerancia es **declarada, no calibrada** — no hay una población de "desvíos
# legítimos" que medir como en la 64: un batch de refresh deja a todos en la misma
# fecha. 5 ruedas es holgura para un ticker que no operó algún día (halt, feriado
# propio) y queda muy por debajo de los tres casos reales (14, 21 y 48).
ARTIFACT_MAX_LAG_DAYS = 5

# Artefactos que **a propósito** no se refrescan, con su razón escrita. No es lo
# mismo que uno que se quedó viejo sin que nadie lo note: acá la excepción está
# declarada, se imprime **por nombre y con el motivo** en cada corrida, y por eso
# no dispara el abort. Un dict y no una lista justamente para que agregar uno
# obligue a escribir el porqué.
ARTIFACT_REFRESH_EXCEPTIONS: dict[str, str] = {
    "AVB": (
        "tarea 63: Yahoo le aplica un split FANTASMA de 2.793 al frame 2y. El 10y "
        "(bajado el 2026-08-09) es la escala sana contra la cual `scale_is_disputed` "
        "detecta la disputa — refrescarlo lo pondría a la escala podrida, los dos "
        "frames coincidirían y AVB pasaría de *vendible* a TRABADO. El caveat NO "
        "caduca con la 63: vale mientras el proveedor siga reportando el split."
    ),
}


class StaleArtifactError(RuntimeError):
    """Un harness arrancó con el cohorte de artefactos desalineado (T30)."""


@dataclass(frozen=True)
class StaleArtifact:
    """Un artefacto cuya última barra no está donde la del resto del cohorte."""

    ticker: str
    end: str
    cohort_end: str
    lag_days: int  # >0 atrasado, <0 adelantado (ruedas)

    @property
    def ahead(self) -> bool:
        return self.lag_days < 0

    def __str__(self) -> str:
        lado = "ADELANTE del" if self.ahead else "atrás del"
        return (
            f"{self.ticker}: última barra {self.end}, {abs(self.lag_days)} ruedas "
            f"{lado} cohorte ({self.cohort_end})"
        )


def _busday_lag(desde: str, hasta: str) -> int:
    """Ruedas (lun-vie) entre dos fechas ISO-10. 0 si alguna no se puede parsear.

    Sin numpy y sin calendario de feriados a propósito: este módulo no depende de
    pandas ni toca el disco, y para lo único que se usa el número —comparar contra
    una tolerancia de 5— un par de feriados no cambia ningún veredicto. Los tres
    casos reales estaban a 14, 21 y 48 ruedas.
    """
    try:
        d0 = date.fromisoformat(desde[:10])
        d1 = date.fromisoformat(hasta[:10])
    except ValueError:
        return 0
    signo = 1 if d1 >= d0 else -1
    a, b = (d0, d1) if d1 >= d0 else (d1, d0)
    semanas, resto = divmod((b - a).days, 7)
    n = 5 * semanas + sum(1 for i in range(resto) if (a + timedelta(days=i)).weekday() < 5)
    return signo * n


def cohort_end(bars_by: dict[str, list]) -> str:
    """La última barra **modal** del cohorte — la fecha del batch de refresh.

    Moda y no máximo a propósito: un único artefacto refrescado de más haría que
    todos los demás parecieran atrasados. Empate ⇒ gana la más nueva.
    """
    ends = [bars[-1][0] for bars in bars_by.values() if bars]
    if not ends:
        return ""
    cuenta = Counter(ends)
    top = max(cuenta.values())
    return max(e for e, n in cuenta.items() if n == top)


def stale_artifacts(
    bars_by: dict[str, list], *, max_lag_days: int = ARTIFACT_MAX_LAG_DAYS
) -> tuple[StaleArtifact, ...]:
    """Los artefactos desalineados del cohorte, del más desviado al menos.

    Mira **los dos lados**: un refresh parcial deja artefactos *adelantados*, que
    rompen la uniformidad de la muestra igual que uno congelado — y encima mueven
    el ``max(ends)`` de la ventana publicada, así que son **más** visibles en el
    resultado y **menos** visibles en el diagnóstico.

    Es pura: no toca el disco ni la red, y trabaja sobre las barras ya cargadas.
    """
    ref = cohort_end(bars_by)
    if not ref:
        return ()
    fuera = [
        StaleArtifact(ticker=t, end=bars[-1][0], cohort_end=ref, lag_days=_busday_lag(bars[-1][0], ref))
        for t, bars in bars_by.items()
        if bars
        and t.upper() not in ARTIFACT_REFRESH_EXCEPTIONS
        and abs(_busday_lag(bars[-1][0], ref)) > max_lag_days
    ]
    return tuple(sorted(fuera, key=lambda s: -abs(s.lag_days)))


def declared_exceptions(bars_by: dict[str, list]) -> tuple[StaleArtifact, ...]:
    """Los artefactos desalineados que están **declarados** como excepción (T30).

    Se separan de ``stale_artifacts`` para que el banner pueda decirlos con su
    motivo en vez de callarlos: una excepción silenciosa vuelve a ser el defecto
    que la 30 vino a arreglar."""
    ref = cohort_end(bars_by)
    if not ref:
        return ()
    return tuple(
        StaleArtifact(ticker=t, end=bars[-1][0], cohort_end=ref, lag_days=_busday_lag(bars[-1][0], ref))
        for t, bars in sorted(bars_by.items())
        if bars and t.upper() in ARTIFACT_REFRESH_EXCEPTIONS and bars[-1][0] != ref
    )


def announce_artifacts(
    bars_by: dict[str, list],
    *,
    max_lag_days: int = ARTIFACT_MAX_LAG_DAYS,
    strict: bool = True,
    file: TextIO | None = None,
) -> tuple[StaleArtifact, ...]:
    """Declara la frescura del cohorte y **falla ruidoso** si está desalineado.

    Misma política que la **T22**: un artefacto viejo no puede degradar en
    silencio. Con ``strict=False`` sólo declara — para un harness que a propósito
    corre sobre un cohorte mezclado y lo dice en su pre-registro.

    Se llama **al arrancar**, junto a ``announce()``: si la muestra está torcida,
    la corrida entera no vale y no tiene sentido pagarla antes de enterarse.
    """
    fuera = stale_artifacts(bars_by, max_lag_days=max_lag_days)
    salida = file if file is not None else sys.stdout
    ref = cohort_end(bars_by)
    n = sum(1 for b in bars_by.values() if b)
    print(
        f"Frescura del cohorte — {n} artefactos, última barra modal {ref} "
        f"(tolerancia {max_lag_days} ruedas):",
        file=salida,
    )
    for exc in declared_exceptions(bars_by):
        print(f"  [excepción declarada] {exc}", file=salida)
        print(f"      {ARTIFACT_REFRESH_EXCEPTIONS[exc.ticker.upper()]}", file=salida)
    if not fuera:
        print("  todos alineados.\n", file=salida)
        return fuera
    for s in fuera:
        print(f"  {s}", file=salida)
    print(
        f"  AVISO: {len(fuera)} artefacto(s) fuera del cohorte. La ventana que "
        f"declara `artifact_window` es min(starts)..max(ends), así que uno solo "
        f"puede correrla sin que se note (T30).\n",
        file=salida,
    )
    if strict:
        raise StaleArtifactError(
            f"{len(fuera)} artefacto(s) fuera del cohorte ({ref}): "
            + " · ".join(str(s) for s in fuera[:5])
            + ". Refrescar el cohorte (y re-anclar las constantes de reproducción) "
            "o correr con strict=False declarándolo en el pre-registro."
        )
    return fuera


# ── Cobertura del store de señales PIT — Tarea 86 (PITCOV-CONSUMIDOR) ────────
#
# ``announce_artifacts`` mira **las barras**. El store de señales es el **otro**
# sustrato compartido, y hasta la 86 nadie lo miraba desde el lado del consumidor:
# la tarea 69 arregló el **productor** —``pending_dates`` decide por fechas, y su
# docstring dice que ``complete`` "ya no alcanza solo"— pero esa función vive sólo
# en los dos ``precompute_*``. Los seis sitios consumidores hacían
# ``if not blob.get("complete")`` y nada más.
#
# El flag **sí puede quedar corto**: se escribe al terminar un barrido y nada lo
# invalida cuando el frame rueda. Así que un runner podía **pasar el guard del
# cohorte y correr igual sobre una muestra encogida** — que es lo que pasó el
# 2026-09-01 (el universo vivo se movió de 141.777 a 142.670 entradas y hubo que
# re-medir 17 constantes publicadas, tarea 68).


class SignalStoreGapError(RuntimeError):
    """Un harness arrancó con el store de señales PIT más corto que su cohorte (T86)."""


def signal_store_gaps(bars_by: dict[str, list], period: str, warmup: int) -> dict[str, tuple[int, str]]:
    """``{ticker: (fechas sin cubrir, la última que sí)}`` — vacío si el store cubre todo.

    Compara contra las **fechas crudas** del artefacto, no contra las señales que
    el loader se queda: los loaders filtran a señal *truthy*
    (``if sv[0]``), así que una fecha evaluada sin señal **no está** en su
    ``sigs_by``. Compararlo contra eso reportaría un hueco por cada día sin BUY —
    o sea, casi todos.

    Y compara contra **las barras que el runner va a usar**, no contra el Parquet:
    es la muestra real de la corrida, y así el chequeo no depende de que el loader
    haya descartado alguna fila malformada.
    """
    from scripts.precompute_pit_signals import _load_existing, _out_path

    faltantes: dict[str, tuple[int, str]] = {}
    for t, bars in bars_by.items():
        if not bars or len(bars) <= warmup:
            continue
        blob = _load_existing(_out_path(t, period, warmup))
        cubiertas = set(blob.get("signals") or {})
        if not cubiertas:
            continue  # sin artefacto: el loader ya lo excluye y lo reporta como `missing`
        sin_cubrir = [b[0] for b in bars[warmup:] if b[0] not in cubiertas]
        if sin_cubrir:
            faltantes[t] = (len(sin_cubrir), max(cubiertas))
    return faltantes


def announce_signal_store(
    bars_by: dict[str, list],
    period: str,
    warmup: int,
    *,
    strict: bool = True,
    file: TextIO | None = None,
) -> dict[str, tuple[int, str]]:
    """Declara la cobertura del store de señales y **falla ruidoso** si está corto.

    Se llama **al arrancar**, junto a ``announce_artifacts``: los dos preguntan lo
    mismo —*¿la muestra es la que digo que es?*— sobre los dos sustratos
    compartidos. En el caso sano imprime una línea y sigue.
    """
    salida = file if file is not None else sys.stdout
    faltantes = signal_store_gaps(bars_by, period, warmup)
    n = sum(1 for b in bars_by.values() if b)
    if not faltantes:
        print(f"Cobertura del store de señales — {n} tickers, sin fechas pendientes.\n", file=salida)
        return faltantes
    peor = sorted(faltantes.items(), key=lambda kv: -kv[1][0])
    print(
        f"Cobertura del store de señales — {len(faltantes)} de {n} tickers con fechas "
        f"SIN señal precomputada:",
        file=salida,
    )
    for t, (cuantas, ultima) in peor[:5]:
        print(f"  {t}: faltan {cuantas} fecha(s); el store llega al {ultima}", file=salida)
    print(
        "  AVISO: esas fechas quedan sin señal, así que la corrida mide sobre una "
        "muestra MÁS CHICA que la que declara. Corré scripts/precompute_pit_signals.py.\n",
        file=salida,
    )
    if strict:
        raise SignalStoreGapError(
            f"{len(faltantes)} ticker(s) con el store de señales corto "
            f"(peor: {peor[0][0]} con {peor[0][1][0]} fechas). Correr "
            "scripts/precompute_pit_signals.py, o strict=False declarándolo en el pre-registro."
        )
    return faltantes


@dataclass(frozen=True)
class ArtifactPopulation:
    """La **muestra** sobre la que corrió un harness — **Tarea 52 (REPRO-POP)**.

    La ventana dice *cuándo*; la población dice *sobre qué*. Dos corridas pueden
    compartir la ventana al día y aun así medir cosas distintas porque una corrió
    sobre 127 tickers y la otra sobre 41: ahí un desajuste **no** es evidencia de
    que cambió la cañería, y tratarlo como tal invalida corridas buenas (que es el
    defecto de la 48 por el otro eje).

    ``n_entries`` es opcional: las anclas compartidas declaran universo y tickers
    (que no dependen de la config del runner) y cada corrida declara además sus
    entradas, que sí dependen de ``cap_days``, gates y demás.
    """

    universe_file: str
    n_tickers: int
    n_entries: int | None = None
    tickers_fp: str | None = None

    def __str__(self) -> str:
        entradas = f", {self.n_entries} entradas" if self.n_entries is not None else ""
        return f"{self.universe_file} ({self.n_tickers} tickers{entradas})"

    def same_universe_as(self, other: ArtifactPopulation) -> bool:
        """¿Las dos corridas miraron el **mismo conjunto de tickers**?

        Es el eje categórico: si difiere, el ancla se midió sobre otra cosa y no
        hay nada que reproducir (``REPRO_NA``).

        **Compara el CONJUNTO cuando puede, y el conteo sólo si no puede**
        (tarea 87). El nombre de esta función siempre prometió *"el mismo conjunto
        de tickers"* y lo que comparaba era **un string de path y un entero**:
        con eso, cambiar un ticker por otro dejaba ``127 == 127`` y la corrida
        seguía afirmando *"MISMA muestra"*. Y no es hipotético —
        ``scripts/refresh_live_universe.py`` regenera el archivo **en el lugar**,
        con el mismo nombre.

        ``tickers_fp`` es la huella del conjunto efectivo. Si **las dos** la
        declaran, manda ella; si alguna no, se cae al par (archivo, conteo) —
        más débil, y por eso las anclas compartidas la declaran.
        """
        if self.universe_file != other.universe_file:
            return False
        if self.tickers_fp is not None and other.tickers_fp is not None:
            return self.tickers_fp == other.tickers_fp
        return self.n_tickers == other.n_tickers

    def matches(self, other: ArtifactPopulation) -> bool:
        """Misma muestra: mismo universo y —cuando **las dos** lo declaran— mismas
        entradas. Si una de las dos no declara ``n_entries``, no se lo compara: no
        se puede acusar por un dato que nadie publicó."""
        if not self.same_universe_as(other):
            return False
        if self.n_entries is None or other.n_entries is None:
            return True
        return self.n_entries == other.n_entries


def tickers_fingerprint(tickers) -> str:
    """Huella corta y estable del **conjunto** de tickers (tarea 87).

    Doce hex de un SHA-256 sobre los nombres ordenados. Corta a propósito: entra
    en una línea de banner y en una constante sin volverla ilegible, y para lo que
    hace —distinguir un conjunto de otro— doce hex son de sobra.

    Estable a propósito: **ordenada**, así que no depende del orden en que el
    loader haya recorrido el universo, y sobre los nombres en mayúscula, así que
    no depende de cómo los haya escrito el archivo.
    """
    import hashlib

    nombres = sorted({str(t).strip().upper() for t in tickers if str(t).strip()})
    return hashlib.sha256(",".join(nombres).encode("utf-8")).hexdigest()[:12]


@lru_cache(maxsize=32)
def universe_fingerprint(universe_file: str) -> str | None:
    """Huella del **archivo de universo**, o ``None`` si no se puede leer.

    **Una sola semántica, a propósito** (tarea 87): la huella es del universo
    *declarado* —el archivo—, no del conjunto que efectivamente cargó. Las dos
    tentaciones se descartaron por esto:

    * el conjunto **cargado** cambiaría con una falla transitoria de carga, y eso
      no es un cambio de universo — es un hipo. El eje "qué cargó" ya lo lleva
      ``n_tickers``, por separado.
    * tener **las dos** huellas sería dos fuentes de verdad para la misma
      pregunta, que es justo el defecto que esta tarea vino a cerrar.

    Fail-open a ``None`` (archivo inexistente, permisos): sin huella el chequeo
    cae al conteo, que es el comportamiento previo. Un guard que revienta por no
    poder leer un archivo de universo sería peor que el defecto.
    """
    try:
        raw = (_REPO_ROOT / universe_file).read_text(encoding="utf-8-sig")
    except OSError:
        return None
    tickers = [
        ln.split("#", 1)[0].strip()
        for ln in raw.splitlines()
        if ln.strip() and not ln.lstrip().startswith("#")
    ]
    tickers = [t for t in tickers if t]
    return tickers_fingerprint(tickers) if tickers else None


def artifact_population(
    universe_file: str,
    bars_by: dict[str, list] | None = None,
    *,
    n_tickers: int | None = None,
    n_entries: int | None = None,
) -> ArtifactPopulation:
    """Población de una corrida.

    Lee el archivo de universo para la huella (cacheado, y fail-open a ``None`` si
    no se puede leer); el resto es puro. Decía *"pura, sin I/O"* y dejó de serlo
    en la tarea 87 — se corrige acá en vez de dejar el claim viejo.

    ``n_tickers`` sale de ``bars_by`` si no se lo pasa explícito (los tickers que
    efectivamente cargaron, que es lo que ``announce()`` ya imprime, y no los que
    el archivo de universo pretendía).

    Y con ``bars_by`` se calcula además la **huella del conjunto** (tarea 87): es
    la de los tickers que **efectivamente cargaron**, no la del archivo — misma
    lógica que ``n_tickers``, y es la que corresponde porque la muestra de la
    corrida son los que cargaron. Sigue siendo pura: la huella sale de las claves
    que ya están en memoria.
    """
    if n_tickers is None:
        n_tickers = len(bars_by or {})
    return ArtifactPopulation(universe_file, n_tickers, n_entries, universe_fingerprint(universe_file))


# Estados de ``reproduction_check``.
REPRO_OK = "OK"
REPRO_FAIL = "FALLA"
REPRO_INDETERMINATE = "INDETERMINADO"
# Cuarto estado (Tarea 52): el ancla se midió sobre **otra población**, así que el
# chequeo no aplica. NO cuenta como OK — una corrida cuyo sanity de reproducción
# no aplica no reprodujo nada y no puede dictar veredicto por ese lado.
REPRO_NA = "NO APLICA"


def reproduction_check(
    measured: float | None,
    expected: float,
    *,
    tol: float,
    current: ArtifactWindow | None = None,
    measured_on: ArtifactWindow | str | None = None,
    population: ArtifactPopulation | None = None,
    measured_over: ArtifactPopulation | None = None,
) -> tuple[str, str]:
    """Sanity de reproducción consciente de la **ventana** (T48) y de la
    **población** (T52).

    Devuelve ``(estado, motivo)`` con cuatro estados posibles:

    * ``REPRO_OK`` — el número reproduce dentro de ``tol``.
    * ``REPRO_NA`` — el ancla se midió sobre **otro universo** ⇒ no hay nada que
      reproducir. No cuenta como OK, pero tampoco acusa a nadie.
    * ``REPRO_FAIL`` — no reproduce **y la muestra es la misma** —misma ventana y
      misma población— ⇒ cambió algo en la cañería, que es exactamente lo que el
      sanity existe para detectar. La corrida es INVÁLIDA.
    * ``REPRO_INDETERMINATE`` — no reproduce **y la muestra se movió, o no se sabe
      cuál era** ⇒ el chequeo **no puede distinguir** un cambio de cañería de un
      refresh de artefactos o de un cambio de muestra, así que no afirma ninguna de
      las dos cosas. Quien corra tiene que re-medir la referencia sobre la muestra
      nueva antes de sacar conclusiones.

    ``measured_on`` es la ventana y ``measured_over`` la población con las que se
    midió ``expected``; ``current`` y ``population`` son las de esta corrida. Si
    alguna de las dos referencias no se declara, un desajuste no puede atribuirse y
    sale ``INDETERMINADO``: **el default es no acusar a la cañería sin evidencia**,
    y para acusar hacen falta los dos ejes (una corrida sobre otro universo tiene
    la misma ventana que ésta, y aun así no dice nada de la cañería).
    """
    # El eje categórico va primero: si el ancla se midió sobre otro universo, no
    # hay desajuste que interpretar — ni siquiera un brazo que no corrió.
    if (
        population is not None
        and measured_over is not None
        and not population.same_universe_as(measured_over)
    ):
        return REPRO_NA, (
            f"la referencia se midió sobre {measured_over}; esta corrida usa "
            f"{population}. El ancla no aplica (tarea 52): re-medila sobre esta "
            f"población si querés un sanity de reproducción acá."
        )
    if measured is None:
        return REPRO_FAIL, "no se midió el brazo de reproducción"
    if abs(measured - expected) <= tol:
        return REPRO_OK, f"{measured:.4f} vs {expected:.4f} (tol {tol:.4f})"
    same_window = measured_on is not None and current is not None and str(measured_on) == str(current)
    same_population = (
        population is not None and measured_over is not None and population.matches(measured_over)
    )
    detail = f"{measured:.4f} vs {expected:.4f} esperado (tol {tol:.4f})"
    # Para ACUSAR a la cañería hacen falta las dos mitades de "misma muestra", y
    # la de entradas tiene que haberse podido **comparar de verdad** (tarea 87).
    # `matches()` devuelve True cuando alguna de las dos no declara `n_entries`
    # —"no se puede acusar por un dato que nadie publicó"—, pero ese True entraba
    # acá como si fuera evidencia: no-declarar volvía al chequeo **más** confiado,
    # exactamente al revés de su objetivo. Y las dos anclas compartidas no lo
    # declaran, así que ésta era la rama por default.
    entradas_comparables = (
        population is not None
        and measured_over is not None
        and population.n_entries is not None
        and measured_over.n_entries is not None
    )
    if same_window and same_population and entradas_comparables:
        return REPRO_FAIL, (
            f"{detail} — MISMA muestra (ventana {current} · población {population}) ⇒ cambió la cañería"
        )
    if same_window and same_population:
        return REPRO_INDETERMINATE, (
            f"{detail} — misma ventana ({current}) y mismo universo ({population}), pero "
            f"la referencia NO declara sus entradas, así que no se puede confirmar que la "
            f"muestra sea la misma (tarea 87). Para poder acusar a la cañería, el ancla "
            f"tiene que declarar `n_entries`."
        )
    if not same_window:
        movida = (
            f"la ventana se movió ({measured_on} → {current})"
            if measured_on
            else "la referencia no declara sobre qué ventana se midió"
        )
        return (
            REPRO_INDETERMINATE,
            f"{detail} — {movida}: el chequeo no distingue cañería de refresh de "
            f"artefactos (tarea 48). Re-medí la referencia sobre la ventana actual "
            f"({current}) antes de sacar conclusiones.",
        )
    cambio = (
        f"cambió la muestra dentro del universo ({measured_over} → {population})"
        if measured_over is not None and population is not None
        else "la referencia no declara sobre qué población se midió"
    )
    return (
        REPRO_INDETERMINATE,
        f"{detail} — MISMA ventana ({current}) pero {cambio}: el chequeo no "
        f"distingue cañería de cambio de muestra (tarea 52). Re-medí la referencia "
        f"sobre esta población antes de sacar conclusiones.",
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
    # Gates de re-entrada del engine modelados o no (Tarea 34). El default espeja
    # el de ``portfolio_sim.simulate_portfolio``, así que un runner que no lo pase
    # declara lo que realmente corre.
    live_gates: bool = False
    # Ventana efectiva de los artefactos (Tarea 48). ``None`` ⇒ el runner no la
    # declaró, y el banner lo dice en vez de callarse.
    window: ArtifactWindow | None = None
    # Política de salida simulada (Tarea 92). Los defaults **espejan los de
    # ``AtrParams``**, así que un runner que no los pase declara exactamente lo que
    # corre — mismo criterio que ``eval_mode``/``fill_mode``/``live_gates``. Eso es
    # lo que hace que el desvío se declare **sin tocar los 21 runners**.
    atr_stop_mult: float = 2.0
    atr_trail_mult: float | None = None
    # Sizing y gates vivos que el runner declara modelar (Tareas 94, 95, 96). El
    # default es ``False`` porque **ningún runner los modela hoy**, así que un
    # runner que no diga nada declara exactamente lo que corre — mismo criterio
    # que ``live_gates``.
    models_vol_overlay: bool = False
    models_regime_scale: bool = False
    models_earnings_blackout: bool = False

    @property
    def effective_trail_mult(self) -> float:
        """Espeja ``AtrParams.effective_trail_mult``: sin trail propio, manda el stop."""
        return self.atr_stop_mult if self.atr_trail_mult is None else self.atr_trail_mult

    @property
    def hard_stop_on(self) -> bool:
        """¿El stop duro puede disparar? El harness lo apaga con un múltiplo enorme."""
        return self.atr_stop_mult < NO_STOP_MULT

    def population(self, n_entries: int | None = None) -> ArtifactPopulation:
        """La población de esta corrida (Tarea 52), para el sanity de reproducción.

        Sale de lo que el banner ya declara —universo y tickers cargados— más las
        entradas, que el runner recién conoce después de armarlas.

        Lleva además la **huella del universo** (tarea 87). Sin esto el arreglo
        quedaba **inerte en producción**: cuatro de los ocho call sites del sanity
        construyen su población por acá, y sin huella `same_universe_as` cae al
        conteo — o sea al defecto que la tarea vino a cerrar."""
        return ArtifactPopulation(
            self.universe_file,
            self.n_tickers,
            n_entries,
            universe_fingerprint(self.universe_file),
        )


def exit_rule_line(eval_mode: str = "close", fill_mode: str = HARNESS_FILL_MODE) -> str:
    """Una línea que dice **qué regla de salida** se está simulando.

    Se imprime siempre (aunque no hubiera desvíos) porque las dos mitades —contra
    qué precio se decide la barrera y a qué precio se llena— son las que la serie
    T7→T26 arrastró sin nombrar, y la segunda ni siquiera estaba en el banner.
    Toma los modos sueltos (y no un ``HarnessConfig``) para que la use también el
    T7, que corre con capital ilimitado y no tiene config de cartera.
    """
    decide = PIT_EXIT_EVAL_DESC if eval_mode == "close" else TOUCH_EXIT_EVAL_DESC
    fill = (
        "al precio que tomó la decisión"
        if fill_mode == HARNESS_FILL_MODE
        else "orden en reposo en el nivel (LEGACY)"
    )
    return f"Regla de salida simulada: barrera decidida al {decide} · fill {fill}"


def deviations(cfg: HarnessConfig) -> list[str]:
    """Desvíos de ``cfg`` respecto de la cuenta viva, en prosa."""
    out: list[str] = []
    if cfg.max_positions != LIVE_MAX_POSITIONS:
        out.append(f"slots {cfg.max_positions} vs {LIVE_MAX_POSITIONS} de la cuenta {LIVE_ACCOUNT_ID}")
    # Bilateral a propósito (tarea 89). Era `<`, así que un universo de harness
    # MÁS GRANDE que la watchlist viva no declaraba nada — y un desvío es un
    # desvío para los dos lados, igual que en `stale_artifacts` (T30), que mira
    # los dos porque un refresh parcial rompe la uniformidad tanto como uno
    # faltante. Lo que este chequeo NO puede ver, y queda dicho: compara
    # **tamaños**, no conjuntos, porque el conjunto vivo está en la DB y esta
    # función es pura. El eje del conjunto lo cubre `tickers_fp` del lado de la
    # población (tarea 87).
    if cfg.n_tickers != LIVE_WATCHLIST_SIZE:
        lado = "menos" if cfg.n_tickers < LIVE_WATCHLIST_SIZE else "MÁS"
        out.append(
            f"universo {cfg.n_tickers} tickers vs {LIVE_WATCHLIST_SIZE} de la watchlist "
            f"viva ({lado} que la cuenta {LIVE_ACCOUNT_ID})"
        )
    # La ventana de señal siempre difiere mientras los artefactos PIT sean los
    # actuales — se declara siempre, no es condicional.
    out.append(f"ventana de analyze() {PIT_WINDOW_DESC} vs {LIVE_HISTORY_BARS} barras fijas en vivo")
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
    # Y el sexto: los gates de re-entrada. Es estructural de ``portfolio_sim`` —el
    # simulador nunca los tuvo— así que se declara siempre que no se los modele.
    # Y el séptimo (Tarea 48): la ventana de los artefactos es RODANTE, así que
    # todo número de esta corrida está atado a la muestra de hoy. Se declara
    # siempre: cuando el runner no la pasa, el banner dice que no la declaró.
    if cfg.window is not None:
        out.append(
            f"ventana de los artefactos {ARTIFACT_PERIOD} = {cfg.window} — es "
            f"RODANTE (anclada al refresh, no a una fecha fija): estos números "
            f"dejan de reproducir cuando se refresquen los parquet (tarea 48)"
        )
    else:
        out.append(
            "el runner NO declara la ventana efectiva de los artefactos — es "
            "RODANTE, así que no se sabe contra qué muestra se midió (tarea 48)"
        )
    # OCTAVO desvío (Tarea 92): la política de SALIDA. La cuenta viva apagó el stop
    # duro el 2026-08-27 (`soff_t2.0`) y el default de ``AtrParams`` lo dejó
    # encendido a 2.0×ATR. Vale **7,16 pp de CAGR** medidos por el propio T37
    # (2,01% con el default vs 9,17% con lo vivo) — más que el look-ahead del fill.
    # Se compara contra la config viva, igual que slots y universo, en vez de
    # depender de que el autor del pre-registro se acuerde de escribirlo a mano.
    if cfg.hard_stop_on != LIVE_HARD_STOP_ENABLED:
        estado_h = f"ENCENDIDO a {cfg.atr_stop_mult:.1f}×ATR" if cfg.hard_stop_on else "APAGADO"
        estado_v = f"ENCENDIDO a {LIVE_STOP_MULT:.1f}×ATR" if LIVE_HARD_STOP_ENABLED else "APAGADO"
        out.append(
            f"stop duro {estado_h} en el harness vs {estado_v} en la cuenta "
            f"{LIVE_ACCOUNT_ID} (desde el 2026-08-27, `soff_t2.0` de la T37): "
            f"vale 7.16pp de CAGR sobre la muestra de esa tarea (2.01% vs 9.17%)"
        )
    if abs(cfg.effective_trail_mult - LIVE_TRAIL_MULT) > 1e-9:
        out.append(
            f"trailing {cfg.effective_trail_mult:.1f}×ATR en el harness vs "
            f"{LIVE_TRAIL_MULT:.1f}×ATR en la cuenta {LIVE_ACCOUNT_ID}"
        )
    # Tarea 94 — el que más muerde de los tres: dispara TODOS los días.
    if LIVE_VOL_OVERLAY_ENABLED and not cfg.models_vol_overlay:
        out.append(
            f"NO se modela el overlay de volatilidad de cartera (target "
            f"{100 * LIVE_VOL_TARGET_ANNUAL:.0f}% anual), que en vivo recorta **todas** las "
            f"BUY nuevas y dispara todos los días (medido: ×0.76 con σ=15.8%, ×0.32 con σ=37.2%)"
        )
    # Tarea 95 — nunca disparó en vivo, pero sí muerde en la ventana del harness.
    if LIVE_REGIME_SCALE_ENABLED and not cfg.models_regime_scale:
        out.append(
            f"NO se modela el escalado por régimen (×{LIVE_REGIME_SCALE_FACTOR:.2f} en "
            f"risk-off): 0 de 62 BUY vivas lo dispararon, pero el 15.96% de las ruedas de "
            f"la ventana son risk-off. Vale +0.59pp de CAGR y −2.5pp de maxDD (T20)"
        )
    # Tarea 96 — no se puede modelar con los datos que hay, y por eso se declara.
    if LIVE_EARNINGS_BLACKOUT_DAYS > 0 and not cfg.models_earnings_blackout:
        out.append(
            f"NO se modela el blackout de earnings (Gate 6, ±{LIVE_EARNINGS_BLACKOUT_DAYS}d, "
            f"bloquea BUY): el harness entra en trades que el engine habría frenado. El "
            f"15.8% de los round-trips reales son near-earnings. NO es modelable hoy — no "
            f"hay fechas de earnings point-in-time a 10 años"
        )
    if not cfg.live_gates:
        out.append(
            f"NO se modelan los gates de re-entrada del engine — Gate 5 "
            f"(anti-whipsaw: cualquier pérdida dentro de {LIVE_WHIPSAW_LOOKBACK_DAYS}d "
            f"bloquea el re-BUY, umbral vivo {LIVE_WHIPSAW_MIN_LOSS_PCT:.1f}%) y Gate 5b "
            f"(anti-churn: ≥{LIVE_CHURN_MAX_CYCLES} ciclos en {LIVE_CHURN_LOOKBACK_DAYS}d). "
            f"Vale {REENTRY_GATES_COST_DESC}"
        )
    return out


def config_banner(cfg: HarnessConfig) -> str:
    """Bloque de texto que todo harness imprime antes de correr.

    Nombra la config usada y los desvíos contra la cuenta viva. Si el veredicto
    publicado de esa tarea corrió con otros slots, lo dice — así un default nuevo
    no rompe la reproducibilidad en silencio.
    """
    lines = [
        f"Config: max_positions={cfg.max_positions} · universo={cfg.universe_file} ({cfg.n_tickers} tickers)",
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
    if cfg.verdict_max_positions is not None and cfg.verdict_max_positions != cfg.max_positions:
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
    live_gates: bool = False,
    window: ArtifactWindow | None = None,
    atr_stop_mult: float = 2.0,
    atr_trail_mult: float | None = None,
    models_vol_overlay: bool = False,
    models_regime_scale: bool = False,
    models_earnings_blackout: bool = False,
    file: TextIO | None = None,
) -> HarnessConfig:
    """Arma la config, **imprime el banner** y la devuelve.

    Es la línea única que cada runner llama antes de simular: así declarar los
    desvíos no depende de que quien escriba el próximo harness se acuerde.
    """
    cfg = HarnessConfig(
        atr_stop_mult=atr_stop_mult,
        atr_trail_mult=atr_trail_mult,
        models_vol_overlay=models_vol_overlay,
        models_regime_scale=models_regime_scale,
        models_earnings_blackout=models_earnings_blackout,
        max_positions=max_positions,
        universe_file=universe_file,
        n_tickers=n_tickers,
        verdict_max_positions=verdict_max_positions,
        eval_mode=eval_mode,
        fill_mode=fill_mode,
        live_gates=live_gates,
        window=window,
    )
    print(config_banner(cfg) + "\n", file=file if file is not None else sys.stdout)
    return cfg


# ── Población de la grilla — Tarea 58 (GRIDPOP) ──────────────────────────────
#
# La 51 congeló una grilla de topes de tenencia sin haber medido nunca cuántos
# trades de la cuenta viva llegan a esos valores, y **un tercio de la grilla era
# inerte**: los brazos de 40 y 60 ruedas daban ``Δ = 0.0000`` porque ningún trade
# pasa de **37**. Un brazo así no es "no significativo": es **el baseline con otro
# nombre**, y ocupa lugar en la grilla, en el walk-forward y en el costo de
# multiplicidad. Lo más caro fue lo otro: el walk-forward eligió ``N=30`` con
# acuerdo **5/5 folds** sobre **seis trades de 2.509**, y fuera de muestra devolvió
# el mismo dígito que el baseline. **Un acuerdo perfecto no es evidencia si la
# regla casi no se ejecuta** (``docs/event_timestop_t51_2026-08-28.md`` §2 y §4.1).
#
# El umbral es el de la **T13**, reusado tal cual: por debajo del 5% de los trades
# alcanzados el brazo se reporta **«sin población» — sin poder, NO refutado**.
GRID_MIN_POPULATION = 0.05


def _nearest_rank(ordenados: Sequence[float], q: float) -> float:
    """Percentil por *nearest-rank*: sin numpy y sin interpolar entre trades.

    Interpolar inventaría una tenencia que ningún trade tuvo, y acá el número se
    usa para decidir qué valores de la grilla tienen población."""
    idx = math.ceil(q * len(ordenados)) - 1
    return ordenados[min(max(idx, 0), len(ordenados) - 1)]


def _fmt_value(v: float) -> str:
    return f"{int(v)}" if float(v).is_integer() else f"{v:.2f}"


@dataclass(frozen=True)
class GridArm:
    """Un valor de la grilla y **a cuántos trades del baseline llegaría a tocar**."""

    value: float
    n_hit: int
    share: float
    min_share: float = GRID_MIN_POPULATION

    @property
    def inert(self) -> bool:
        """No toca **ningún** trade ⇒ no es un brazo, es el baseline renombrado."""
        return self.n_hit == 0

    @property
    def underpowered(self) -> bool:
        """Toca algo, pero menos que el umbral de la T13 ⇒ **«sin población»**.

        Se distingue de ``inert`` a propósito: un brazo inerte hay que **sacarlo**
        de la grilla; uno sin población se puede medir, pero su resultado no se
        puede leer como refutación."""
        return not self.inert and self.share < self.min_share

    @property
    def viable(self) -> bool:
        return not self.inert and not self.underpowered


@dataclass(frozen=True)
class GridPopulation:
    """La distribución que **tendría que haberse mirado antes** de congelar la grilla.

    ``arms`` va en el orden en que se pasó la grilla. La regla de *tocar* es
    monótona: un brazo con umbral ``v`` alcanza a los trades cuya medida es
    ``>= v`` — que es exactamente lo que hace un cap duro de tenencia."""

    n_trades: int
    mean: float
    p25: float
    p50: float
    p75: float
    p90: float
    p95: float
    p99: float
    maximum: float
    arms: tuple[GridArm, ...]
    label: str = "tenencia (ruedas)"

    @property
    def inert(self) -> tuple[GridArm, ...]:
        return tuple(a for a in self.arms if a.inert)

    @property
    def underpowered(self) -> tuple[GridArm, ...]:
        return tuple(a for a in self.arms if a.underpowered)

    @property
    def viable(self) -> tuple[float, ...]:
        """Los valores que **sí** se pueden medir — los que debería recorrer el
        walk-forward, para que el acuerdo entre folds signifique algo."""
        return tuple(a.value for a in self.arms if a.viable)

    def warnings(self) -> list[str]:
        """Los avisos que el banner grita. Vacío ⇒ toda la grilla tiene población."""
        out: list[str] = []
        if self.inert:
            vals = ", ".join(_fmt_value(a.value) for a in self.inert)
            out.append(
                f"AVISO: {len(self.inert)} brazo(s) INERTE(s) ({vals}) — no tocan "
                f"ningún trade: son el baseline con otro nombre. Sacarlos de la "
                f"grilla (T58)."
            )
        if self.underpowered:
            vals = ", ".join(_fmt_value(a.value) for a in self.underpowered)
            out.append(
                f"AVISO: {len(self.underpowered)} brazo(s) SIN POBLACIÓN ({vals}) — "
                f"por debajo del {100 * GRID_MIN_POPULATION:.0f}% de la T13: un "
                f"resultado ahí es *sin poder, NO refutado*."
            )
        if not self.viable:
            out.append(
                "AVISO: NINGÚN valor de la grilla tiene población — la pregunta no se "
                "puede medir sobre esta cartera, y un veredicto sería sobre ruido."
            )
        return out

    def lines(self) -> list[str]:
        out = [
            f"Población de la grilla — {self.label} sobre {self.n_trades} trades del baseline:",
            f"  media {self.mean:.1f} · p25 {_fmt_value(self.p25)} · "
            f"p50 {_fmt_value(self.p50)} · p75 {_fmt_value(self.p75)} · "
            f"p90 {_fmt_value(self.p90)} · p95 {_fmt_value(self.p95)} · "
            f"p99 {_fmt_value(self.p99)} · MÁX {_fmt_value(self.maximum)}",
            f"  {'valor':>8} {'trades':>8} {'población':>11}",
        ]
        for a in self.arms:
            nota = ""
            if a.inert:
                nota = "  <- INERTE: es el baseline con otro nombre"
            elif a.underpowered:
                nota = f"  <- sin población (<{100 * a.min_share:.0f}%)"
            out.append(f"  {_fmt_value(a.value):>8} {a.n_hit:>8} {100 * a.share:>10.2f}%{nota}")
        out.extend("  " + w for w in self.warnings())
        return out

    def __str__(self) -> str:
        return "\n".join(self.lines())


def grid_population(
    per_trade: Iterable[float],
    grid: Iterable[float],
    *,
    label: str = "tenencia (ruedas)",
    min_share: float = GRID_MIN_POPULATION,
) -> GridPopulation:
    """La población de cada valor de la grilla, sobre la cartera del **baseline**.

    ``per_trade`` es la medida por trade contra la que se compara la grilla — para
    un tope de tenencia, ``[t.held_days for t in base_res.trades]``. Es pura: no
    importa ``portfolio_sim`` ni toca el disco.
    """
    medidas = sorted(float(x) for x in per_trade)
    if not medidas:
        raise ValueError("sin trades: no hay población de grilla que medir")
    n = len(medidas)
    arms = []
    for v in grid:
        hit = sum(1 for m in medidas if m >= v)
        arms.append(GridArm(value=v, n_hit=hit, share=hit / n, min_share=min_share))
    return GridPopulation(
        n_trades=n,
        mean=statistics.fmean(medidas),
        p25=_nearest_rank(medidas, 0.25),
        p50=_nearest_rank(medidas, 0.50),
        p75=_nearest_rank(medidas, 0.75),
        p90=_nearest_rank(medidas, 0.90),
        p95=_nearest_rank(medidas, 0.95),
        p99=_nearest_rank(medidas, 0.99),
        maximum=medidas[-1],
        arms=tuple(arms),
        label=label,
    )


def announce_grid(
    per_trade: Iterable[float],
    grid: Iterable[float],
    *,
    label: str = "tenencia (ruedas)",
    min_share: float = GRID_MIN_POPULATION,
    file: TextIO | None = None,
) -> GridPopulation:
    """Mide la población de la grilla, **la imprime** y la devuelve.

    Es el par de ``announce()`` para el segundo momento del harness: aquél declara
    la config **antes** de simular, éste declara la muestra de la grilla apenas hay
    baseline y **antes** de correr los brazos y el walk-forward. Se imprime aunque
    esté todo bien: el precedente de la 48 y la 52 es que la muestra se declara
    siempre, no sólo cuando hay un problema.
    """
    pop = grid_population(per_trade, grid, label=label, min_share=min_share)
    print("\n".join(pop.lines()) + "\n", file=file if file is not None else sys.stdout)
    return pop


# ── Población EFECTIVA — Tarea 62 (EXITPOP) ──────────────────────────────────
#
# La 58 dejó el instrumento para la población **cruzada**: a cuántos trades del
# baseline llega a tocar cada valor de la grilla. La 54 midió las dos cosas sobre
# la MISMA corrida y la brecha es de **trece veces**: 336 trades cruzan el umbral
# de armado del trailing (17,98% — pasa el ≥5% de la T13 con holgura) y **25**
# cambian de fecha o de motivo de salida (``docs/trail_arm_t54_2026-08-28.md`` §7).
#
# La causa no es de la 54: es de cualquier familia donde la regla es una **barrera
# condicional**. Un trailing armado que nunca dispara deja la salida idéntica, y
# lo mismo vale para el take-profit que no se toca (T23), el stop que no se perfora
# (T26/T34/T37) y el cap de tenencia al que otra salida se adelanta (T51). La
# cruzada es una **cota superior** de la efectiva, y hasta acá nada decía cuán
# floja es esa cota en cada corrida.
#
# EL ORDEN IMPORTA, y es la parte fina. La cruzada se computa sobre el **baseline**
# ⇒ se puede mirar *antes* de congelar el pre-registro, y por eso la 58 la usa para
# FIJAR la grilla (``announce_grid``). La efectiva exige **haber corrido el brazo**
# ⇒ es un sanity **post-corrida** y no puede fijar nada: un pre-registro que la pida
# como criterio de grilla está pidiendo un número que todavía no existe.
#
# LA DECISIÓN DE LA 62, escrita para que no quede implícita:
#
#   * El **gate sigue siendo la cruzada**, con el ≥5% de la T13. Ese umbral se
#     calibró sobre la cruzada; leerlo sobre la efectiva sería mover el listón con
#     un número que nadie midió, y encima hacia atrás sobre veredictos publicados.
#   * La efectiva entra como **AVISO declarado**, no como criterio — con UNA
#     excepción que no necesita calibración ninguna: la **efectiva CERO**. Un brazo
#     que no cambia NI UNA salida no es "no significativo": es el baseline con otro
#     nombre en la única punta que importa, y un veredicto ahí sería sobre nada.
#     Es el mismo ``inert`` de la 58 un nivel más abajo, y por eso ``inert`` es la
#     única propiedad de acá que se puede leer como terminante.
#   * Poner un umbral **positivo** sobre la efectiva exige medir antes su **poder**
#     —cuántas salidas cambiadas hacen falta para detectar un efecto de tamaño
#     dado—, que no está medido para este eje. Sin esa medición cualquier número
#     sería especulativo, que es justo lo que la regla 2 prohíbe. Queda dicho como
#     lo que falta, no como lo que se hizo.
#
# El aviso de "flaca" reusa ``GRID_MIN_POPULATION`` **a propósito y como aviso**:
# es el listón que la corrida ya declaró haber pasado por la cruzada, así que
# medirlo también sobre la efectiva es la comparación que hace visible la brecha,
# sin introducir una constante nueva.


@dataclass(frozen=True)
class EffectivePopulation:
    """Cuántas salidas cambia **de verdad** un brazo, contra cuántas podría tocar.

    ``n_common`` son los trades que el baseline y el brazo comparten (misma clave
    ``(ticker, entrada)``): los únicos sobre los que la pregunta *"¿cambió la
    salida?"* tiene sentido, porque en los demás no hay con qué comparar.
    ``n_crossed`` es la población **cruzada** del brazo —los trades que el umbral
    alcanza— y ``n_changed_in_crossed`` cuántos de ésos cambiaron: la razón entre
    los dos es lo que la 54 midió como 13×."""

    n_common: int
    n_changed: int
    n_crossed: int = 0
    n_changed_in_crossed: int = 0
    min_share: float = GRID_MIN_POPULATION
    label: str = "salidas"

    @property
    def share(self) -> float:
        """Población **efectiva**: la fracción de trades comunes que cambia de salida."""
        return self.n_changed / self.n_common if self.n_common else 0.0

    @property
    def crossed_share(self) -> float:
        """La **cota superior**: la fracción de comunes que el umbral alcanza a tocar."""
        return self.n_crossed / self.n_common if self.n_common else 0.0

    @property
    def realization(self) -> float | None:
        """Qué fracción de la cota se **realiza**. ``None`` si no se declaró cruzada.

        Es el número de la 54 dado vuelta: 25/336 = 7,4% ⇒ la cota sobrestima 13×."""
        if not self.n_crossed:
            return None
        return self.n_changed_in_crossed / self.n_crossed

    @property
    def inert(self) -> bool:
        """No cambia **ninguna** salida ⇒ el baseline con otro nombre. Es el único
        estado de acá que se puede leer como terminante (ver el bloque de arriba)."""
        return self.n_common > 0 and self.n_changed == 0

    @property
    def thin(self) -> bool:
        """Cambia algo, pero menos que el listón que la cruzada ya declaró pasar.

        **No es un gate**: el ≥5% se calibró sobre la cruzada. Es el aviso que hace
        visible la brecha entre las dos poblaciones. Sin trades comunes es ``False``:
        ahí no hay muestra flaca, hay muestra inexistente, y lo dice el otro aviso."""
        return self.n_common > 0 and not self.inert and self.share < self.min_share

    def warnings(self) -> list[str]:
        """Los avisos que el banner grita. Vacío ⇒ el brazo mueve lo que toca."""
        if not self.n_common:
            return [
                "AVISO: NINGÚN trade en común entre el baseline y el brazo — la "
                "población efectiva no se puede medir (T62)."
            ]
        out: list[str] = []
        if self.inert:
            out.append(
                "AVISO: el brazo no cambia NI UNA salida — es el baseline con otro "
                "nombre en la punta que importa, y un veredicto sería sobre nada "
                "(T62; el INERTE de la 58 un nivel más abajo)."
            )
        elif self.thin:
            out.append(
                f"AVISO: población EFECTIVA {100 * self.share:.2f}% — por debajo del "
                f"{100 * self.min_share:.0f}% que la cruzada declara pasar. NO es un "
                f"gate (ese umbral se calibró sobre la cruzada), pero un Δ chico acá "
                f"se lee *casi no se ejecutó*, no *el mecanismo no sirve* (T62)."
            )
        r = self.realization
        if r == 0.0:
            out.append(
                f"AVISO: de los {self.n_crossed} trades que CRUZAN el umbral no cambia "
                f"de salida NINGUNO — la población cruzada de este brazo es cota "
                f"superior de cero (T62)."
            )
        elif r is not None and r < 1.0:
            out.append(
                f"AVISO: la población cruzada SOBRESTIMA {1 / r:.1f}× lo que el brazo "
                f"mueve ({self.n_changed_in_crossed} de {self.n_crossed} cruzados "
                f"cambian de salida) — es una cota superior, no la muestra efectiva (T62)."
            )
        return out

    def lines(self) -> list[str]:
        out = [
            f"Población EFECTIVA — {self.label} que cambian, sobre "
            f"{self.n_common} trades comunes (sanity POST-CORRIDA, T62):",
            f"  cruzada (cota sup.) {self.n_crossed:>6}  {100 * self.crossed_share:>7.2f}%",
            f"  efectiva            {self.n_changed:>6}  {100 * self.share:>7.2f}%",
        ]
        r = self.realization
        if r is not None:
            out.append(
                f"  realizada           {self.n_changed_in_crossed:>6}  {100 * r:>7.2f}% de la cruzada"
            )
        out.extend("  " + w for w in self.warnings())
        return out

    def as_dict(self) -> dict[str, Any]:
        """El descriptivo, para el JSON de la corrida."""
        return {
            "n_common": self.n_common,
            "n_changed": self.n_changed,
            "share": self.share,
            "n_crossed": self.n_crossed,
            "n_changed_in_crossed": self.n_changed_in_crossed,
            "realization": self.realization,
            "inert": self.inert,
            "thin": self.thin,
            "min_share": self.min_share,
            "warnings": self.warnings(),
        }

    def __str__(self) -> str:
        return "\n".join(self.lines())


def effective_population(
    base_exits: Mapping[Any, Any],
    cand_exits: Mapping[Any, Any],
    *,
    crossed: Iterable[Any] = (),
    min_share: float = GRID_MIN_POPULATION,
    label: str = "salidas",
) -> EffectivePopulation:
    """La población **efectiva** de un brazo: cuántas salidas cambia de verdad.

    ``base_exits`` y ``cand_exits`` mapean la clave del trade —``(ticker, entrada)``
    en todos los runners de la serie— a la **firma de la salida** que el runner
    considere: la ``(fecha, motivo)`` de la 54 es la más estricta que se usó. Se
    comparan con ``!=``, así que qué cuenta como *cambiar de salida* lo decide el
    runner y queda visible en su código, no acá.

    ``crossed`` son las claves de la población **cruzada** (las que el umbral toca),
    para poder reportar cuánto de esa cota se realiza. Es opcional: sin ella el
    helper igual da la efectiva, sólo que sin el factor de sobrestimación.

    Es pura: no importa ``portfolio_sim``, no toca el disco y no pega a la red.
    """
    keys = set(crossed)
    comunes = [k for k in base_exits if k in cand_exits]
    cambiados = [k for k in comunes if base_exits[k] != cand_exits[k]]
    return EffectivePopulation(
        n_common=len(comunes),
        n_changed=len(cambiados),
        n_crossed=sum(1 for k in keys if k in base_exits and k in cand_exits),
        n_changed_in_crossed=sum(1 for k in cambiados if k in keys),
        min_share=min_share,
        label=label,
    )


def announce_effective(
    base_exits: Mapping[Any, Any],
    cand_exits: Mapping[Any, Any],
    *,
    crossed: Iterable[Any] = (),
    min_share: float = GRID_MIN_POPULATION,
    label: str = "salidas",
    file: TextIO | None = None,
) -> EffectivePopulation:
    """Mide la población efectiva, **la imprime** y la devuelve.

    Es el **tercer** momento del harness, y va en ese orden a propósito:
    ``announce()`` declara la config antes de simular, ``announce_grid()`` declara
    la muestra de la grilla apenas hay baseline y **antes** de correr los brazos, y
    éste declara —ya con el brazo corrido— cuánto de esa muestra se realizó. No se
    puede adelantar: la efectiva **no existe** hasta que el brazo corrió, y por eso
    no puede entrar como criterio de un pre-registro congelado.
    """
    pop = effective_population(base_exits, cand_exits, crossed=crossed, min_share=min_share, label=label)
    print("\n".join(pop.lines()) + "\n", file=file if file is not None else sys.stdout)
    return pop


# ── Ventanas de los artefactos, POR UNIVERSO — re-ancladas en la Tarea 68 ────
#
# La ventana con la que se miden las constantes de reproducción de los runners
# (T37, T39 §5.2, 45 §5.3, 47 §5.4, 49 §5.2, 51, 54). La ventana de los artefactos
# es **RODANTE** —está anclada al refresh, no a una fecha fija—, así que cuando se
# los refresca esta constante deja de coincidir y los sanity de reproducción pasan
# a ``REPRO_INDETERMINATE``: la acción correcta ahí es **re-anclar** (re-correr y
# re-publicar el número con la ventana nueva), **no** buscar un bug de cañería.
#
# **Son DOS, una por universo, y ésa es la lección de la 68.** El ancla anterior
# —``WINDOW_REFRESH_2026_08_09`` = ``2016-07-11..2026-08-07``— era una sola para
# los dos universos, y eso ya no se sostiene: medidas después del refresh de la 30,
# la ventana viva y la legacy **difieren en el start**. Es exactamente el defecto
# que la **52** corrigió para la población —un ancla tiene que declarar *sobre qué
# universo* se midió— un eje más allá.
#
# **Y el ancla anterior estaba, además, construida sobre un artefacto CONGELADO**
# (tarea 30): su ``end`` venía de los 503 artefactos sanos y su ``start`` del
# ``10y`` de TSM, parado desde el 2026-07-09. ``artifact_window`` agrega
# ``min(starts)..max(ends)``, y eso lo hacía invisible. De ahí sale el guard de
# frescura (``announce_artifacts``), que ahora corre **antes** de cada harness.
#
# **OJO con el ``start`` de la ventana VIVA: lo fija AVB**, que es la excepción de
# refresh declarada en ``ARTIFACT_REFRESH_EXCEPTIONS`` (su ``10y`` es la escala sana
# contra la que se detecta el split fantasma del ``2y``). O sea que la ventana viva
# depende a propósito de un artefacto que no se refresca. Queda dicho acá para que
# no se re-descubra dentro de seis meses: si algún día AVB se refresca, este ancla
# se mueve **sola** y hay que re-anclar de nuevo.
WINDOW_REFRESH_2026_09_01_LIVE = ArtifactWindow("2016-08-08", "2026-09-01", 2514)
WINDOW_REFRESH_2026_09_01_LEGACY = ArtifactWindow("2016-09-01", "2026-09-01", 2513)

# Las POBLACIONES sobre las que se midieron esas mismas constantes (Tarea 52). La
# ventana sola no alcanza para acusar a la cañería: el smoke de la 37 corrió sobre
# el universo legacy con la ventana de siempre y los tres chequeos salieron `FALLA`
# — misma ventana, otra muestra. Cada ancla declara ahora también su universo, y un
# desajuste sobre otro universo sale `REPRO_NA` en vez de invalidar la corrida.
#
# No declaran ``n_entries``, y la razón CORREGIDA es ésta (tarea 87). El comentario
# que estaba acá decía que compararlas *"acusaría por un desvío de config y no de
# muestra"*, y **eso es falso en las dos mitades**:
#
#   1. **Comparar no puede acusar nunca.** Un desajuste de entradas hace
#      ``same_population=False`` y cae en ``INDETERMINADO``. Declarar ``n_entries``
#      sólo puede mover **FALLA → INDETERMINADO**, jamás al revés. La mitigación
#      iba exactamente al revés de su objetivo declarado.
#   2. **"Las entradas dependen de `cap_days`/gates" es falso en 6 de los 8 sitios**:
#      ahí ``entries = buy_entries(bars_by, sigs_by, warmup)`` depende sólo de
#      barras, señales y warmup; ``cap_days``/``max_positions``/``capital`` van a la
#      **simulación**, no a la construcción de entradas.
#
# La razón real por la que siguen sin declararlas es de **implementación**: siete
# runners con construcciones de entrada distintas comparten ``POPULATION_LIVE_ACCT2``,
# así que no hay un número compartido correcto — habría que declararlas **por
# runner**, al lado de cada ``REPRO_*_CAGR``. Mientras tanto, la consecuencia
# peligrosa está tapada por los dos lados: ``reproduction_check`` **ya no acusa** sin
# poder comparar entradas (tarea 87) y el escenario que llegaba hasta acá —store de
# señales corto— **aborta antes** (tarea 86).
#
# Sí declaran la **huella del conjunto**, que es la otra mitad del defecto: sin ella,
# cambiar un ticker por otro dejaba ``127 == 127`` y la corrida seguía afirmando
# "MISMA muestra". Medidas el 2026-09-02 sobre los archivos de universo, que no se
# tocan desde `c40482a` (tarea 27) — o sea, los mismos con los que se midieron las
# constantes de reproducción en la 68.
POPULATION_LIVE_ACCT2 = ArtifactPopulation(LIVE_UNIVERSE_FILE, 127, None, "b88c89385ebc")
POPULATION_LEGACY_41 = ArtifactPopulation(LEGACY_UNIVERSE_FILE, 41, None, "dc8e4d0e59ec")


# ── Un solo dueño por cache-dir — Tarea 59 (HARNESS-CONCURRENT) ──────────────
#
# Cerrando la 51 pasó esto, en vivo: la corrida cortada de una sesion anterior
# seguia viva cuando se lanzo la nueva. Las dos escribieron el mismo cache-dir y
# el mismo artefacto de salida — el log quedo entrelazado (dos writers con
# offsets propios sobre un archivo truncado) y el JSON final lo escribieron las
# dos. Se descarto ese cache y se re-corrio con un solo proceso; la corrida
# limpia dio identica campo por campo, asi que aquel veredicto no quedo
# contaminado. Pero eso fue **conducta**, no defensa.
#
# Lo caro es que **nada lo detecta despues**: un `.pkl` mezclado se lee como un
# `PortfolioResult` cualquiera y entra a un veredicto sin dejar rastro. Un
# harness que memoiza no puede depender de que el operador se acuerde de mirar si
# hay otro proceso vivo.
#
# La primitiva es un **lock de archivo exclusivo**, no un PID guardado: si el
# dueño se muere —o lo matan a mitad de corrida— el sistema operativo suelta el
# lock solo, asi que no hay locks rancios que limpiar a mano. El PID se guarda
# aparte y **sólo para el mensaje de error**: sirve para nombrar al culpable, no
# para decidir.


class CacheDirBusy(RuntimeError):
    """Otro proceso vivo ya es dueño de este ``--cache-dir``."""


_LOCK_FILE = ".harness.lock"
_OWNER_FILE = ".harness.owner"

# Locks tomados por ESTE proceso: {ruta resuelta: file object}. Cumple dos
# funciones — mantiene vivo el descriptor (si se lo lleva el GC, el sistema
# operativo suelta el lock) y vuelve idempotente un segundo pedido del mismo
# proceso sobre el mismo dir, que si no chocaria contra si mismo.
_held_locks: dict[str, object] = {}


def _lock_exclusive(fh) -> bool:
    """Toma un lock exclusivo NO bloqueante sobre ``fh``. False si esta tomado."""
    # Los módulos se aliasan a `Any` a propósito: typeshed marca `fcntl` como
    # exclusivo de Unix y `msvcrt` de Windows, así que mypy sólo ve los atributos
    # del sistema donde corre y en el otro los reporta como inexistentes. Un
    # `# type: ignore` sería peor: con `warn_unused_ignores` quedaría marcado como
    # sobrante en LA OTRA plataforma, o sea que el archivo no podría estar limpio
    # en las dos a la vez.
    try:
        import fcntl

        unix: Any = fcntl
    except ImportError:
        import msvcrt

        win: Any = msvcrt
        try:
            fh.seek(0)
            win.locking(fh.fileno(), win.LK_NBLCK, 1)
            return True
        except OSError:
            return False
    try:
        unix.flock(fh.fileno(), unix.LOCK_EX | unix.LOCK_NB)
        return True
    except OSError:
        return False


def _read_owner(cache_dir: Path) -> dict:
    """Datos del dueño actual, o ``{}``. Se lee sin lock: es sólo para el mensaje."""
    try:
        return json.loads((cache_dir / _OWNER_FILE).read_text(encoding="utf-8"))
    except Exception:
        return {}


def describe_owner(cache_dir: str | Path) -> str:
    """Frase humana con quién es dueño del cache-dir (para el error y el log)."""
    info = _read_owner(Path(cache_dir))
    if not info:
        return "otro proceso (sin datos de dueño)"
    return "pid {pid} en {host}, desde {desde} — {cmd}".format(
        pid=info.get("pid", "?"),
        host=info.get("host", "?"),
        desde=info.get("desde", "?"),
        cmd=info.get("cmd", "?"),
    )


def lock_cache_dir(cache_dir: str | Path) -> Path:
    """Toma el cache-dir para este proceso, o levanta ``CacheDirBusy``.

    Se suelta solo: el descriptor vive lo que vive el proceso y el sistema
    operativo libera el lock al terminar, **incluso si la corrida se cae o la
    matan**. Por eso no hay que limpiar nada a mano y no existen locks rancios.

    Idempotente dentro del mismo proceso: pedir dos veces el mismo dir devuelve
    el mismo lock en vez de chocar contra uno mismo.
    """
    d = Path(cache_dir)
    d.mkdir(parents=True, exist_ok=True)
    key = str(d.resolve())
    if key in _held_locks:
        return d

    # Sin context manager a propósito: el descriptor tiene que SOBREVIVIR a esta
    # función, porque es lo que mantiene el lock. Un `with` lo cerraría al salir y
    # soltaría el cache-dir — exactamente lo contrario de lo que la tarea 59 hace.
    fh = open(d / _LOCK_FILE, "a+b")  # noqa: SIM115
    try:
        fh.seek(0, os.SEEK_END)
        if fh.tell() == 0:
            fh.write(b"\0")
            fh.flush()
        if not _lock_exclusive(fh):
            fh.close()
            raise CacheDirBusy(
                f"El cache-dir {d} ya lo esta usando {describe_owner(d)}. Dos corridas sobre "
                "el mismo cache se pisan el `.tmp` y el artefacto, y un pickle "
                "mezclado se lee despues como un resultado cualquiera. Usar otro "
                "--cache-dir, o esperar a que la otra corrida termine."
            )
    except CacheDirBusy:
        raise
    except OSError as exc:  # disco lleno, permisos, FS sin locks…
        # Fail-open declarado: no poder tomar el lock no puede impedir correr un
        # harness. Se avisa fuerte y se sigue — al reves seria un guard nuevo que
        # rompe corridas buenas, que es el defecto que la 52 tuvo que desarmar.
        print(
            f"AVISO: no se pudo tomar el lock de {d} ({exc}). Se sigue sin "
            "proteccion de concurrencia: verificar a mano que no haya otra "
            "corrida viva sobre este cache-dir.",
            file=sys.stderr,
        )
        return d

    _held_locks[key] = fh
    # El dueño es el LOCK, no este archivo: si no se puede escribir, el cache-dir
    # sigue tomado igual y lo único que se pierde es el nombre en el mensaje.
    with contextlib.suppress(OSError):
        (d / _OWNER_FILE).write_text(
            json.dumps(
                {
                    "pid": os.getpid(),
                    "host": socket.gethostname(),
                    "desde": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "cmd": " ".join(sys.argv[:3]),
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    return d
