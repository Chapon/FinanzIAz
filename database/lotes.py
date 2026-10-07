"""Libro de lotes de la cartera real: splits, FIFO y ganancia realizada (tarea 324). Puro.

Lo que mira la vista desplegable de Portfolio (tarea 325) y lo que usa la importación de un
CSV con historia —compras **y ventas**— para armar cada posición.

Los splits
----------
Yahoo Finance no tiene splits en su cartera: el de NVDA 10:1 (2024-06-10) quedó cargado como
una **venta** de 12 a $1200 y una **compra** de 120 a $120, las dos con la nota «Stock Split».
Tomado literal, eso inventa una ganancia realizada de +$3.438 que no existió y deja el costo
en $120 por acción, cuando el real es $89,85. ``detectar_splits`` reconoce el par y lo
convierte en un ajuste de los movimientos **anteriores** (cantidad × ratio, precio ÷ ratio):
quedan las fechas reales de compra y la realizada es cero. Decidido por Chapa el 2026-10-07.

El par se acepta sólo si **todo** cierra: las dos notas dicen *split*, la compra es de 0 a 7
días después de la venta, la venta es exactamente la tenencia de ese momento, y el nocional de
las dos patas coincide (±1%). Si algo no cierra, el par queda literal y se avisa: adivinar un
split es peor que mostrar lo que dice el archivo.

Ajustar las cantidades viejas es además lo que piden los demás consumidores: los cierres y
los dividendos de yfinance vienen ajustados por split, así que el valor diario de Home y los
dividendos cobrados salen bien con las cantidades ajustadas.

FIFO
----
Una venta consume los lotes más viejos primero (la convención de Yahoo, que es la que ve
Chapa). La comisión de un lote se prorratea con sus acciones. La realizada de una venta es
``cantidad × precio − comisión de la venta − costo de los lotes consumidos (con su comisión)``;
la de una compra es la de la parte de ese lote que ya se vendió — las dos columnas de Yahoo.
El costo por acción de los lotes abiertos **no** incluye comisiones, igual que
``Position.avg_buy_price``.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date

# Por debajo de esto, una cantidad es cero (hay acciones fraccionarias).
_TOL = 1e-6
# Días entre la venta y la compra de un par de split que carga Yahoo (NVDA: 07/06 → 10/06).
_SPLIT_MAX_DIAS = 7
# Diferencia relativa tolerada entre el nocional de la venta y el de la compra de un split.
_SPLIT_TOL_NOCIONAL = 0.01


@dataclass
class Movimiento:
    fecha: date
    tipo: str  # "BUY" | "SELL"
    cantidad: float
    precio: float
    comision: float = 0.0
    nota: str = ""


@dataclass
class Split:
    fecha: date
    ratio: float  # acciones nuevas por cada vieja (10.0 en NVDA)


@dataclass
class Lote:
    fecha: date
    cantidad: float  # la que queda abierta
    precio: float
    comision: float  # la parte de la comisión que corresponde a lo que queda abierto


@dataclass
class FilaLibro:
    mov: Movimiento
    realizado: float | None  # None: una compra de la que no se vendió nada
    costo: float  # base del %: compra, cantidad × precio; venta, el costo (con comisión) de lo que consumió

    @property
    def realizado_pct(self) -> float | None:
        if self.realizado is None or self.costo <= 0:
            return None
        return self.realizado / self.costo * 100.0


@dataclass
class LibroTicker:
    filas: list[FilaLibro]  # en el orden en que se aplicaron
    lotes: list[Lote]  # los abiertos, del más viejo al más nuevo
    error: str | None = None  # p. ej. una venta de más acciones que las que había

    @property
    def cantidad(self) -> float:
        return sum(lo.cantidad for lo in self.lotes)

    @property
    def costo_promedio(self) -> float:
        q = self.cantidad
        return sum(lo.cantidad * lo.precio for lo in self.lotes) / q if q > _TOL else 0.0

    @property
    def realizado(self) -> float:
        return sum(f.realizado for f in self.filas if f.mov.tipo == "SELL" and f.realizado is not None)

    @property
    def abierta(self) -> bool:
        return self.cantidad > _TOL

    @property
    def fecha_lote_mas_viejo(self) -> date | None:
        return self.lotes[0].fecha if self.lotes else None


def _orden(m: Movimiento) -> tuple:
    # Mismo día: la compra antes que la venta (no se puede vender lo que todavía no se compró).
    return (m.fecha, 0 if m.tipo == "BUY" else 1)


def _es_split(m: Movimiento) -> bool:
    return "split" in (m.nota or "").lower()


def detectar_splits(movs: list[Movimiento]) -> tuple[list[Movimiento], list[Split], list[str]]:
    """``(movimientos sin los pares de split, splits, avisos)``. Ver el docstring del módulo."""
    orden = sorted(movs, key=_orden)
    usados: set[int] = set()
    splits: list[Split] = []
    avisos: list[str] = []
    for i, venta in enumerate(orden):
        if venta.tipo != "SELL" or not _es_split(venta) or i in usados:
            continue
        compra_idx = next(
            (
                j
                for j, c in enumerate(orden)
                if j not in usados
                and c.tipo == "BUY"
                and _es_split(c)
                and 0 <= (c.fecha - venta.fecha).days <= _SPLIT_MAX_DIAS
            ),
            None,
        )
        if compra_idx is None:
            avisos.append(f"venta del {venta.fecha} marcada split sin su compra: queda como venta")
            continue
        compra = orden[compra_idx]
        tenencia = sum(
            (m.cantidad if m.tipo == "BUY" else -m.cantidad)
            for k, m in enumerate(orden)
            if k not in usados and k not in (i, compra_idx) and _orden(m) < _orden(venta)
        )
        n_venta, n_compra = venta.cantidad * venta.precio, compra.cantidad * compra.precio
        if abs(tenencia - venta.cantidad) > _TOL:
            avisos.append(
                f"split del {compra.fecha}: la venta ({venta.cantidad:g}) no es la tenencia "
                f"({tenencia:g}); queda como venta y compra"
            )
            continue
        if n_venta <= 0 or abs(n_venta - n_compra) / n_venta > _SPLIT_TOL_NOCIONAL:
            avisos.append(
                f"split del {compra.fecha}: el nocional no cierra (${n_venta:,.2f} vs "
                f"${n_compra:,.2f}); queda como venta y compra"
            )
            continue
        usados.update((i, compra_idx))
        splits.append(Split(fecha=compra.fecha, ratio=compra.cantidad / venta.cantidad))
    resto = [m for k, m in enumerate(orden) if k not in usados]
    return resto, splits, avisos


def ajustar_por_splits(movs: list[Movimiento], splits: list[Split]) -> list[Movimiento]:
    """Lleva cada movimiento anterior a un split a acciones de hoy, y lo dice en la nota."""
    out = []
    for m in movs:
        ratio = 1.0
        for s in splits:
            if m.fecha < s.fecha:
                ratio *= s.ratio
        if ratio == 1.0:
            out.append(m)
            continue
        fechas = ", ".join(f"{s.ratio:g}:1 del {s.fecha.isoformat()}" for s in splits if m.fecha < s.fecha)
        nota = f"Ajustado por split {fechas} (original: {m.cantidad:g} a ${m.precio:,.2f})"
        if m.nota:
            nota = f"{m.nota} · {nota}"
        out.append(replace(m, cantidad=m.cantidad * ratio, precio=m.precio / ratio, nota=nota))
    return out


def libro_fifo(movs: list[Movimiento]) -> LibroTicker:
    """Aplica los movimientos de **un** ticker en orden y devuelve lotes abiertos y realizadas."""
    lotes: list[Lote] = []
    filas: list[FilaLibro] = []
    # realizada acumulada de cada compra, por índice de fila
    por_compra: dict[int, float] = {}
    lote_fila: list[int] = []  # índice de fila de la compra que originó cada lote abierto
    for m in sorted(movs, key=_orden):
        if m.tipo == "BUY":
            lotes.append(Lote(m.fecha, m.cantidad, m.precio, m.comision or 0.0))
            lote_fila.append(len(filas))
            # El % de una compra va sobre el costo SIN comisión y el de una venta sobre el costo
            # con comisiones: así lo calcula Yahoo (NVDA: lote de 7 → +74,48%; la venta → +31,36%).
            filas.append(FilaLibro(m, None, m.cantidad * m.precio))
            continue
        disponible = sum(lo.cantidad for lo in lotes)
        if m.cantidad - disponible > _TOL:
            return LibroTicker(
                filas,
                lotes,
                error=f"venta del {m.fecha} de {m.cantidad:g} acciones con {disponible:g} en cartera",
            )
        resta, costo = m.cantidad, 0.0
        while resta > _TOL and lotes:
            lo = lotes[0]
            q = min(lo.cantidad, resta)
            parte = q / lo.cantidad
            com = lo.comision * parte
            costo_q = q * lo.precio + com
            ingreso_q = q * m.precio - (m.comision or 0.0) * (q / m.cantidad)
            fila_c = lote_fila[0]
            por_compra[fila_c] = por_compra.get(fila_c, 0.0) + (ingreso_q - costo_q)
            costo += costo_q
            lo.cantidad -= q
            lo.comision -= com
            resta -= q
            if lo.cantidad <= _TOL:
                lotes.pop(0)
                lote_fila.pop(0)
        ingreso = m.cantidad * m.precio - (m.comision or 0.0)
        filas.append(FilaLibro(m, ingreso - costo, costo))
    for k, r in por_compra.items():
        filas[k].realizado = r
    return LibroTicker(filas, lotes)


@dataclass
class PosicionArmada:
    ticker: str
    movimientos: list[Movimiento]  # ya ajustados por split: los que se guardan
    libro: LibroTicker
    splits: list[Split] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)


def armar_posiciones(movs_por_ticker: dict[str, list[Movimiento]]) -> list[PosicionArmada]:
    """Splits + FIFO para cada ticker. Un ticker con error lo dice en ``libro.error``."""
    out = []
    for ticker in sorted(movs_por_ticker):
        resto, splits, avisos = detectar_splits(movs_por_ticker[ticker])
        ajustados = ajustar_por_splits(resto, splits)
        out.append(PosicionArmada(ticker, ajustados, libro_fifo(ajustados), splits, avisos))
    return out
