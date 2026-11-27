"""
Equity-curve chart widget for the paper-trading tab.

Used to live as ``_EquityCurveChart`` inside ``paper_tab.py`` — extracted
into its own module so it can be tested in isolation and reused (e.g. by
a future "compare two accounts" view).
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterable
from datetime import date, datetime, time, timedelta, timezone, tzinfo
from zoneinfo import ZoneInfo

import matplotlib

matplotlib.use("QtAgg")
import matplotlib.dates as mdates
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from PyQt6.QtWidgets import QVBoxLayout, QWidget

from ui.styles import CHART_STYLE, PALETTE


def build_benchmark_overlay(
    snapshots: list,
    spy_pairs: list[tuple[str, float]] | None,
    initial_capital: float | None = None,
) -> list[tuple[datetime, float]]:
    """Normaliza SPY al CAPITAL de la cuenta sobre la ventana de los snapshots (V1).

    ``snapshots``: ``PaperEquitySnapshot`` ascendentes (``.snapshot_at``,
    ``.total_equity``). ``spy_pairs``: ``[(YYYY-MM-DD, close)]``. Devuelve
    ``[(datetime, valor)]`` por cada barra SPY dentro de ``[primer, último]``
    snapshot, escalada para arrancar en el capital → una línea comparable en las
    mismas unidades ($) que la curva de equity. ``[]`` si falta data.

    **Ancla igual que la tarjeta VS SPY (tarea 223), y antes no.** Esta línea tenía las
    dos asimetrías que arregló esa tarea, copiadas: escalaba contra
    ``snapshots[0].total_equity`` —que es el capital **menos** la fricción del primer
    scan, porque el snapshot se estampa después de los fills— y tomaba como base el
    primer close **en o después** del primer snapshot, o sea la rueda siguiente cuando
    ese snapshot cae fuera de una (el de la cuenta 2 es un sábado). Que el gráfico y la
    tarjeta anclen distinto es peor que cualquiera de las dos por separado: son el mismo
    número dibujado en dos lugares.

    Con el capital de base la línea de SPY arranca en $50.000 mientras la equity arranca
    en $49.977 — ese hueco **es** el costo de entrada, y verlo es el punto.
    ``initial_capital=None`` cae en la equity del primer snapshot, que es el
    comportamiento viejo, para los llamadores que no lo tengan a mano.

    Función pura (sin Qt) para poder testear la alineación sin event loop.
    """
    if not snapshots or not spy_pairs:
        return []
    try:
        start_eq = float(snapshots[0].total_equity)
        start_day = snapshots[0].snapshot_at.date().isoformat()
        end_day = snapshots[-1].snapshot_at.date().isoformat()
    except (AttributeError, TypeError, ValueError):
        return []
    if initial_capital is not None and float(initial_capital) > 0:
        start_eq = float(initial_capital)
    if start_eq <= 0:
        return []
    pairs = sorted(spy_pairs)
    # Mismo par de helpers que `_benchmark_panel`, y en el mismo orden: el close con el
    # que está marcada la equity del primer snapshot es el PREVIO; la rueda siguiente
    # queda de fallback para cuando la serie empieza después de la cuenta.
    from analysis.metrics_panel import _ancla_de_spy

    base, _anclaje = _ancla_de_spy(pairs, start_day)
    if not base or base <= 0:
        return []
    scale = start_eq / base
    out: list[tuple[datetime, float]] = []
    for d, c in pairs:
        if d < start_day or d > end_day:
            continue
        with contextlib.suppress(ValueError):
            out.append((cierre_de_la_rueda(d), c * scale))
    return out


def cierre_de_la_rueda(dia: str | date) -> datetime:
    """El cierre de una rueda, 16:00 de Nueva York, en UTC sin zona como ``snapshot_at`` (tarea 476).

    Es donde va el punto de SPY de ese día: con el close de la rueda está marcada la equity
    del scan de las 16:05 ET. Iba a la medianoche UTC del día, que es antes de la apertura y,
    con el eje en la hora de Buenos Aires, la noche del día anterior.
    """
    d = dia if isinstance(dia, date) else date.fromisoformat(str(dia)[:10])
    return datetime.combine(d, time(16), tzinfo=_NUEVA_YORK).astimezone(timezone.utc).replace(tzinfo=None)


def overlay_is_stale(snapshots: list, spy_pairs: list[tuple[str, float]] | None) -> bool:
    """True si el último close de SPY quedó desactualizado vs el último snapshot.

    Reusa el umbral/lógica de ``metrics_panel`` (tarea 22) para no dibujar la
    línea corta como si fuera actual. Función pura (sin Qt). ``False`` ante datos
    faltantes o fechas inválidas — en la duda, no se marca stale.
    """
    if not snapshots or not spy_pairs:
        return False
    from analysis.metrics_panel import BENCHMARK_STALE_BDAYS, benchmark_stale_bdays

    try:
        ref_day = snapshots[-1].snapshot_at.date().isoformat()
    except (AttributeError, TypeError, ValueError):
        return False
    spy_last = max(d for d, _ in spy_pairs)
    return benchmark_stale_bdays(spy_last, ref_day) > BENCHMARK_STALE_BDAYS


def overlay_empieza_tarde(snapshots: list, spy_pairs: list[tuple[str, float]] | None) -> bool:
    """True si la serie de SPY **empieza después** del primer snapshot (tarea 225).

    El espejo de ``overlay_is_stale``, y hace falta por una razón que no es simetría
    decorativa: con la serie corta por el inicio, ``_ancla_de_spy`` cae en la primera
    rueda disponible y la línea queda escalada para que SPY **valga el capital** en una
    fecha en la que la cuenta ya se había movido. O sea que el gráfico afirma que iban
    empatados en un día en el que no lo iban — y eso, a diferencia de una línea que
    arranca tarde, **no se ve**.

    Función pura (sin Qt). ``False`` ante datos faltantes o fechas inválidas: en la duda
    no se suprime nada, igual que su espejo.
    """
    if not snapshots or not spy_pairs:
        return False
    from analysis.metrics_panel import BENCHMARK_STALE_BDAYS, benchmark_start_gap_bdays

    try:
        ref_day = snapshots[0].snapshot_at.date().isoformat()
    except (AttributeError, TypeError, ValueError):
        return False
    spy_first = min(d for d, _ in spy_pairs)
    return benchmark_start_gap_bdays(spy_first, ref_day) > BENCHMARK_STALE_BDAYS


_NUEVA_YORK = ZoneInfo("America/New_York")

# El eje X (tarea 476). Los datos siguen en UTC sin zona —``snapshot_at``, las bandas de la
# 475, los cierres de SPY—, y lo que pasa a la hora local es el eje: el localizador pone las
# marcas en las medianoches y en las horas locales, y el formateador las rotula en esa zona.
# El formato depende de lo que separa a las marcas: en una curva de meses, «08/2026»; de
# días, «24/11»; de horas, «21:00», con la fecha en el cambio de día («01/07») y el día
# entero en el desplazamiento del eje («01/07/2026»).
_FORMATOS_DEL_EJE = ["%Y", "%m/%Y", "%d/%m", "%H:%M", "%H:%M", "%S"]
_FORMATOS_EN_EL_CERO = ["", "%Y", "%d/%m", "%d/%m", "%H:%M", "%H:%M"]
_FORMATOS_DEL_DESPLAZAMIENTO = ["", "", "%m/%Y", "%d/%m/%Y", "%d/%m/%Y", "%d/%m/%Y %H:%M"]


def zona_local() -> tzinfo:
    """La zona del sistema, con sus cambios de horario: la de ``ui.time_utils.fmt_local`` (tarea 476)."""
    from dateutil.tz import tzlocal

    return tzlocal()


def tramos_sin_scan(snapshots_utc: Iterable, ruedas: Iterable) -> list[tuple[datetime, datetime, int]]:
    """Los días hábiles sin ningún scan, agrupados en tramos, en las coordenadas del gráfico (tarea 475).

    Chapa pidió ver en la curva los días en que la app no corrió: entre dos scans la curva
    dibuja una recta, y se lee como si la cuenta hubiera operado. Un snapshot es un
    ``run_scan`` completado (tarea 265), y la app escanea al arrancar, cada 15 minutos con el
    mercado abierto y a las 16:05 ET, así que una rueda sin ningún snapshot es una rueda en la
    que la app no estuvo abierta. Validado contra ``finanzias.log`` el 2026-11-27: en los
    tramos que el log cubre, la app no escribió ni una línea.

    ``snapshots_utc``: los ``snapshot_at`` de **todos** los snapshots de la cuenta (UTC sin
    zona, ``datetime`` o ISO), **también** los de posiciones a costo (tarea 376): la curva los
    saca, pero son un scan que corrió.
    ``ruedas``: los días con rueda (``date`` o ``"AAAA-MM-DD"``). En la pestaña son los de la
    serie de SPY: el proyecto no tiene calendario NYSE, y un día que no está —un feriado, o
    cualquiera después del último cierre— no se marca.

    El día es el de **Nueva York**, como en ``cobertura_de_scan``: un arranque a las 00:40 de
    Buenos Aires es un scan de las 22:40 ET del día anterior. Sólo se miran las ruedas
    **entre** el primer y el último día con scan: antes la cuenta no existía, y después
    todavía no se sabe. Dos ruedas sin scan van en el mismo tramo si entre ellas no hay
    ninguna rueda ni ningún día con scan: un fin de semana sin snapshots las une, y uno con la
    app abierta las corta.

    Devuelve ``[(inicio, fin, ruedas)]``. ``inicio`` es la medianoche de Nueva York del primer
    día y ``fin`` la del día siguiente al último, en UTC sin zona, porque el eje del gráfico
    es ``snapshot_at``. ``ruedas`` es cuántos días hábiles cubre el tramo. Función pura (sin Qt).
    """

    def _dia(ts) -> date:
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts[:26])
        return ts.replace(tzinfo=timezone.utc).astimezone(_NUEVA_YORK).date()

    def _medianoche(d: date) -> datetime:
        return datetime.combine(d, time(0), tzinfo=_NUEVA_YORK).astimezone(timezone.utc).replace(tzinfo=None)

    con_scan = {_dia(ts) for ts in snapshots_utc if ts is not None}
    if not con_scan:
        return []
    primero, ultimo = min(con_scan), max(con_scan)
    dias = sorted({r if isinstance(r, date) else date.fromisoformat(str(r)[:10]) for r in ruedas})
    tramos: list[list[date]] = []
    abierto = False
    for d in dias:
        if not primero < d < ultimo:
            continue
        if d in con_scan:
            abierto = False
            continue
        previa = tramos[-1][-1] if abierto else None
        if previa is not None and not any(
            previa + timedelta(days=k) in con_scan for k in range(1, (d - previa).days)
        ):
            tramos[-1].append(d)
        else:
            tramos.append([d])
        abierto = True
    return [(_medianoche(t[0]), _medianoche(t[-1] + timedelta(days=1)), len(t)) for t in tramos]


def etiqueta_sin_scan(ruedas: int) -> str:
    """El rótulo de las bandas en la leyenda (tarea 475): dice de dónde sale el «cerrada»."""
    dias = "1 día hábil" if ruedas == 1 else f"{ruedas} días hábiles"
    return f"App cerrada ({dias} sin scan)"


class EquityCurveChart(QWidget):
    """
    Minimal line chart for the equity curve. Supports incremental updates
    when a new snapshot is appended to an existing series, falling back to
    a full redraw when the data identity changes (account switch, history
    rewrite, etc.).
    """

    def __init__(self, parent=None, zona: tzinfo | None = None):
        super().__init__(parent)
        # La zona en la que se rotula el eje X (tarea 476); los datos no se convierten.
        self.zona = zona if zona is not None else zona_local()
        for k, v in CHART_STYLE.items():
            with contextlib.suppress(Exception):
                matplotlib.rcParams[k] = v  # type: ignore[index]  # matplotlib tipa las claves con un Literal
        self.figure = Figure(figsize=(8, 3), tight_layout=True)
        self.figure.patch.set_facecolor(str(CHART_STYLE["figure.facecolor"]))
        self.canvas = FigureCanvas(self.figure)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.canvas)
        self.ax = self.figure.add_subplot(111)
        self._style_axes()
        self._render_empty()

        # Incremental-update state
        self._line = None  # Line2D artist (kept between refreshes)
        self._fill = None  # PolyCollection from fill_between
        self._plotted_count = 0  # number of snapshots in last render
        self._first_xs = None  # first snapshot timestamp (series identity key)

    # ── Styling helpers ──────────────────────────────────────────────────────
    def _style_axes(self) -> None:
        self.ax.set_facecolor(str(CHART_STYLE["axes.facecolor"]))
        self.ax.tick_params(colors=CHART_STYLE["xtick.color"], labelsize=9)
        for spine in ("top", "right"):
            self.ax.spines[spine].set_visible(False)
        for spine in ("bottom", "left"):
            self.ax.spines[spine].set_color(str(CHART_STYLE["axes.edgecolor"]))
        self.ax.grid(
            True,
            color=CHART_STYLE["grid.color"],
            alpha=CHART_STYLE["grid.alpha"],
            linewidth=0.5,
        )

    def _render_empty(self) -> None:
        self.ax.clear()
        self._style_axes()
        self.ax.text(
            0.5,
            0.5,
            "Sin datos de equity todavía.",
            transform=self.ax.transAxes,
            color=PALETTE["text3"],
            ha="center",
            va="center",
            fontsize=11,
        )
        self.ax.set_xticks([])
        self.ax.set_yticks([])
        self.canvas.draw()

    # ── Public API ───────────────────────────────────────────────────────────
    def set_data(
        self,
        snapshots: list,
        benchmark: list[tuple[datetime, float]] | None = None,
        benchmark_aviso: str | None = None,
        sin_scan: list[tuple[datetime, datetime, int]] | None = None,
    ) -> None:
        """Render the equity curve from a list of ``PaperEquitySnapshot``.

        ``sin_scan`` (tarea 475): los tramos de ruedas sin ningún scan, como los da
        :func:`tramos_sin_scan`. Se pintan como bandas rojas traslúcidas detrás de la curva,
        porque ahí la curva es una recta entre dos scans y no algo que la cuenta hizo. Con
        tramos, el redibujo es completo, igual que con benchmark.

        ``benchmark`` (opcional, V1): línea SPY normalizada a la equity inicial,
        ``[(datetime, valor)]`` — se dibuja punteada para comparar el modelo vs
        el mercado. Cuando hay benchmark siempre se hace un full redraw (para
        redibujar la línea y su leyenda).

        ``benchmark_aviso`` (tareas 22 y 225): si la línea de SPY no se puede dibujar
        honestamente, el **texto** que se anota en su lugar. Era un ``bool`` llamado
        ``benchmark_stale`` con el cartel *«SPY desactualizado»* hardcodeado adentro, y
        eso alcanzaba mientras hubiera un solo motivo. Con el segundo —la serie que
        empieza **después** que la cuenta— reusar ese booleano habría pintado
        *«desactualizado»* sobre el caso **contrario**, que es la clase de afirmación
        que dirige mal y que este repo viene sacando una por una. El llamador dice qué
        pasó; el chart sólo lo escribe.
        """
        if not snapshots:
            if self._plotted_count > 0:
                self._line = None
                self._fill = None
                self._plotted_count = 0
                self._first_xs = None
                self._render_empty()
            return

        xs = [s.snapshot_at for s in snapshots]
        ys = [float(s.total_equity) for s in snapshots]

        # Incremental update when appending to the same series; full redraw otherwise.
        # Con benchmark (o su marcador de stale) forzamos full redraw.
        same_series = (
            not benchmark
            and not benchmark_aviso
            and not sin_scan
            and self._line is not None
            and self._plotted_count > 0
            and len(snapshots) >= self._plotted_count
            and self._first_xs == xs[0]
        )

        if same_series:
            self._incremental_update(xs, ys)
        else:
            self._full_redraw(xs, ys, benchmark, benchmark_aviso, sin_scan)

        self._plotted_count = len(snapshots)
        self._first_xs = xs[0]

    # ── Drawing internals ────────────────────────────────────────────────────
    def _full_redraw(
        self,
        xs: list,
        ys: list,
        benchmark: list[tuple[datetime, float]] | None = None,
        benchmark_aviso: str | None = None,
        sin_scan: list[tuple[datetime, datetime, int]] | None = None,
    ) -> None:
        self.ax.clear()
        self._style_axes()
        # Días sin scan (tarea 475): detrás de todo, y un solo rótulo para todas las bandas.
        if sin_scan:
            rotulo = etiqueta_sin_scan(sum(n for _, _, n in sin_scan))
            for i, (inicio, fin, _n) in enumerate(sin_scan):
                self.ax.axvspan(
                    inicio,
                    fin,
                    color=PALETTE["red"],
                    alpha=0.3,
                    linewidth=0,
                    zorder=0,
                    label=rotulo if i == 0 else "_nolegend_",
                )
        (self._line,) = self.ax.plot(xs, ys, color=PALETTE["accent"], linewidth=1.8, label="Equity")
        self._fill = self.ax.fill_between(
            xs,
            ys,
            min(ys),
            color=PALETTE["accent"],
            alpha=0.12,
        )
        if len(ys) > 1:
            self.ax.axhline(
                ys[0],
                color=PALETTE["text3"],
                linestyle="--",
                linewidth=0.6,
                alpha=0.7,
            )
        # Overlay SPY (V1): mismo eje $, normalizado al capital de la cuenta.
        # Si la línea no se puede dibujar honestamente —SPY desactualizado (tarea 22) o
        # una serie que empieza después que la cuenta (tarea 225)— se anota el motivo y
        # NO se dibuja: una línea corta se lee como si fuera la comparación completa.
        if benchmark_aviso:
            self.ax.text(
                0.01,
                0.98,
                benchmark_aviso,
                transform=self.ax.transAxes,
                ha="left",
                va="top",
                fontsize=8,
                color=PALETTE.get("text3", "#6B7280"),
            )
        elif benchmark:
            bx = [d for d, _ in benchmark]
            by = [v for _, v in benchmark]
            self.ax.plot(
                bx,
                by,
                color=PALETTE.get("text2", "#9AA4B2"),
                linewidth=1.2,
                linestyle="--",
                alpha=0.9,
                label="SPY (normalizado)",
            )
        if (benchmark and not benchmark_aviso) or sin_scan:
            # Con aviso, la esquina de arriba a la izquierda es del aviso.
            self.ax.legend(loc="upper right" if benchmark_aviso else "upper left", fontsize=8, frameon=False)
        self.ax.set_ylabel("Equity ($)", color=PALETTE["text2"], fontsize=10)
        self._formatear_eje_x()
        self.canvas.draw()

    def _formatear_eje_x(self) -> None:
        """Las marcas del eje X en la hora local, con un formato según el rango (tarea 476).

        Rotulaba ``%d/%m %H:%M`` en UTC, que es como matplotlib lee un datetime sin zona: la
        marca «01/07 00:00» era el 30/06 a las 21:00 en Buenos Aires.
        """
        localizador = mdates.AutoDateLocator(tz=self.zona)
        self.ax.xaxis.set_major_locator(localizador)
        self.ax.xaxis.set_major_formatter(
            mdates.ConciseDateFormatter(
                localizador,
                tz=self.zona,
                formats=_FORMATOS_DEL_EJE,
                zero_formats=_FORMATOS_EN_EL_CERO,
                offset_formats=_FORMATOS_DEL_DESPLAZAMIENTO,
            )
        )

    def _incremental_update(self, xs: list, ys: list) -> None:
        self._line.set_data(xs, ys)
        if self._fill is not None:
            self._fill.remove()
        self._fill = self.ax.fill_between(
            xs,
            ys,
            min(ys),
            color=PALETTE["accent"],
            alpha=0.12,
        )
        self.ax.relim()
        self.ax.autoscale_view()
        self.canvas.draw_idle()

    # ── Lifecycle ────────────────────────────────────────────────────────────
    def cleanup(self) -> None:
        """Drop references to matplotlib artists so the figure can be GC'd."""
        with contextlib.suppress(Exception):
            self.figure.clear()
        self._line = None
        self._fill = None
        self._plotted_count = 0
        self._first_xs = None

    def closeEvent(self, event):
        self.cleanup()
        super().closeEvent(event)
