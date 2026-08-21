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


def artifact_window(bars_by: "dict[str, list]") -> ArtifactWindow | None:
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


# Estados de ``reproduction_check``.
REPRO_OK = "OK"
REPRO_FAIL = "FALLA"
REPRO_INDETERMINATE = "INDETERMINADO"


def reproduction_check(
    measured: float | None,
    expected: float,
    *,
    tol: float,
    current: ArtifactWindow | None = None,
    measured_on: ArtifactWindow | str | None = None,
) -> tuple[str, str]:
    """Sanity de reproducción **consciente de la ventana** (Tarea 48).

    Devuelve ``(estado, motivo)`` con tres estados posibles:

    * ``REPRO_OK`` — el número reproduce dentro de ``tol``.
    * ``REPRO_FAIL`` — no reproduce **y la ventana es la misma** con la que se
      midió ``expected`` ⇒ cambió algo en la cañería, que es exactamente lo que el
      sanity existe para detectar. La corrida es INVÁLIDA.
    * ``REPRO_INDETERMINATE`` — no reproduce **y la ventana se movió** ⇒ el chequeo
      **no puede distinguir** un cambio de cañería de un refresh de artefactos, así
      que no afirma ninguna de las dos cosas. Quien corra tiene que re-medir la
      referencia sobre la ventana nueva antes de sacar conclusiones.

    ``measured_on`` es la ventana con la que se midió ``expected``. Si no se la
    declara, un desajuste no puede atribuirse y también sale ``INDETERMINADO``:
    **el default es no acusar a la cañería sin evidencia**.
    """
    if measured is None:
        return REPRO_FAIL, "no se midió el brazo de reproducción"
    if abs(measured - expected) <= tol:
        return REPRO_OK, f"{measured:.4f} vs {expected:.4f} (tol {tol:.4f})"
    same_window = (
        measured_on is not None
        and current is not None
        and str(measured_on) == str(current)
    )
    detail = f"{measured:.4f} vs {expected:.4f} esperado (tol {tol:.4f})"
    if same_window:
        return REPRO_FAIL, f"{detail} — MISMA ventana ({current}) ⇒ cambió la cañería"
    movida = (f"la ventana se movió ({measured_on} → {current})" if measured_on
              else "la referencia no declara sobre qué ventana se midió")
    return (
        REPRO_INDETERMINATE,
        f"{detail} — {movida}: el chequeo no distingue cañería de refresh de "
        f"artefactos (tarea 48). Re-medí la referencia sobre la ventana actual "
        f"({current}) antes de sacar conclusiones.",
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
    window: "ArtifactWindow | None" = None


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
    live_gates: bool = False,
    window: "ArtifactWindow | None" = None,
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
        live_gates=live_gates,
        window=window,
    )
    print(config_banner(cfg) + "\n", file=file if file is not None else sys.stdout)
    return cfg


# La ventana con la que se midieron TODAS las constantes de reproducción que hoy
# viven en los runners (T39 §5.2, 47 §5.4, 45 §5.3, 49 §5.2). Medida el 2026-08-20
# sobre los dos universos —vivo y legacy— con ``artifact_window``; los parquet se
# refrescaron el **2026-08-09**. Cuando se los refresque de nuevo, esta constante
# deja de coincidir y los sanity de reproducción pasan a ``REPRO_INDETERMINATE``:
# la acción correcta ahí es **re-anclar las constantes** (re-correr y re-publicar
# el número con la ventana nueva), no buscar un bug de cañería.
WINDOW_REFRESH_2026_08_09 = ArtifactWindow("2016-07-11", "2026-08-07", 2514)
