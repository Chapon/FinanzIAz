"""
CSV importer for FinanzIAs.
Supports Yahoo Finance export format and a generic fallback format.

Yahoo Finance CSV columns (typical):
  Symbol, Current Price, Date, Time, Change, Open, High, Low, Volume,
  Trade Date, Purchase Price, Quantity, Commission, High Limit, Low Limit, Comment

Generic fallback (minimum required columns):
  ticker/symbol, quantity/shares, price/buy_price/purchase_price

La fecha de compra (tarea 308)
------------------------------
Hasta la 308 ninguna fecha se leía: la transacción quedaba con la hora de la importación, y las
seis posiciones importadas de «Mis Acciones» figuraban compradas el 2026-04-14 03:19 (AAPL a
$203,30 un día que cerró a $258,37). Los dividendos cobrados de Portfolio se cuentan desde esa
fecha. Ahora se lee ``Trade Date`` (y sus alias). **Ojo con ``Date``:** en el export de Yahoo es
la fecha de la **cotización**, no de la compra; ``date``/``fecha`` a secas sólo se aceptan en el
formato genérico, donde no hay otra columna de fecha.

Formatos: ``YYYYMMDD`` (el de Yahoo), ``YYYY-MM-DD`` y ``DD/MM/YYYY``. Una fecha con barras en la
que día y mes son los dos ≤ 12 es **ambigua** (``03/04/2026``: ¿3 de abril o 4 de marzo?) y no se
adivina: queda sin fecha y se avisa. Una fecha futura, igual.

Compras y ventas (tarea 324)
----------------------------
El export de una cartera de Yahoo trae ``Transaction Type`` (``BUY``/``SELL``), y hasta la 324
se ignoraba: **cada venta entraba como una compra**. Ahora va en ``ImportRow.tipo``. Y en un
archivo con esa columna, una fila sin cantidad es un ticker de la cartera **sin lotes** (TSLA
en el CSV de Chapa), no una watchlist: se omite, en vez de inventarle una compra de 1 acción
al precio actual.
"""

import contextlib
import csv
import io
import re
from dataclasses import dataclass, field
from datetime import date


@dataclass
class ImportRow:
    ticker: str
    quantity: float
    buy_price: float
    commission: float = 0.0
    notes: str = ""
    is_watchlist: bool = False  # True when imported from a watchlist (qty was 0)
    raw: dict = field(default_factory=dict)
    trade_date: date | None = None  # la fecha de compra del CSV; None = no vino o no se pudo leer
    tipo: str = "BUY"  # "BUY" | "SELL" — tarea 324


@dataclass
class ImportResult:
    rows: list[ImportRow]
    skipped: list[dict]  # rows that couldn't be parsed
    warnings: list[str]
    source_format: str  # "yahoo_finance" | "generic"


# Column name aliases (lowercased)
_TICKER_ALIASES = {"symbol", "ticker", "stock", "código", "codigo"}
_QTY_ALIASES = {"quantity", "shares", "cantidad", "qty", "number of shares"}
_PRICE_ALIASES = {
    "purchase price",
    "buy price",
    "buy_price",
    "precio compra",
    "precio de compra",
    "average cost",
    "avg cost",
    "cost basis",
    "price",
    "precio",
}
_CURRENT_PRICE_ALIASES = {"current price", "precio actual", "last price", "last"}
_FEE_ALIASES = {"commission", "comisión", "comision", "fee", "fees"}
_NOTES_ALIASES = {"comment", "notes", "nota", "notas", "description"}
_TRADE_DATE_ALIASES = {
    "trade date",
    "purchase date",
    "date acquired",
    "acquired",
    "fecha de compra",
    "fecha compra",
    "fecha de operacion",
    "fecha de operación",
}
_TIPO_ALIASES = {"transaction type", "type", "tipo", "operacion", "operación", "side"}
_TIPOS = {"BUY": "BUY", "SELL": "SELL", "COMPRA": "BUY", "VENTA": "SELL"}
# Sólo en el formato genérico: en el de Yahoo, `Date` es la fecha de la cotización.
_GENERIC_DATE_ALIASES = {"date", "fecha"}

# Prefixes that identify indices or non-tradeable symbols to skip
_INDEX_PREFIXES = ("^",)


def _normalize(col: str) -> str:
    return col.strip().lower().replace("_", " ").replace("-", " ")


def _find_col(headers: list[str], aliases: set) -> str | None:
    """Return the first header that matches any alias."""
    for h in headers:
        if _normalize(h) in aliases:
            return h
    return None


def parse_trade_date(texto: str, hoy: date | None = None) -> tuple[date | None, str | None]:
    """``(fecha, None)`` o ``(None, motivo)``. Vacío ⇒ ``(None, None)``: no es un error."""
    t = (texto or "").strip()
    if not t:
        return None, None
    hoy = hoy or date.today()
    fecha = None
    try:
        if re.fullmatch(r"\d{8}", t):
            fecha = date(int(t[:4]), int(t[4:6]), int(t[6:]))
        elif re.fullmatch(r"\d{4}-\d{1,2}-\d{1,2}", t):
            a, m, d = (int(x) for x in t.split("-"))
            fecha = date(a, m, d)
        elif m_ := re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", t):
            d, m, a = (int(x) for x in m_.groups())
            if d <= 12 and m <= 12 and d != m:
                return None, f"fecha ambigua '{t}' (¿día/mes o mes/día?)"
            if m > 12:  # sólo puede ser mes/día
                d, m = m, d
            fecha = date(a, m, d)
    except ValueError:
        return None, f"fecha inválida '{t}'"
    if fecha is None:
        return None, f"formato de fecha no reconocido '{t}'"
    if fecha > hoy:
        return None, f"fecha futura '{t}'"
    return fecha, None


def parse_csv(content: str) -> ImportResult:
    """
    Parse CSV content (as string) and return an ImportResult.
    Auto-detects Yahoo Finance format vs generic format.
    """
    rows: list[ImportRow] = []
    skipped: list[dict] = []
    warnings: list[str] = []

    # Detect dialect
    try:
        dialect = csv.Sniffer().sniff(content[:2048])
    except csv.Error:
        dialect = csv.excel

    reader = csv.DictReader(io.StringIO(content), dialect=dialect)
    if not reader.fieldnames:
        return ImportResult([], [], ["El archivo CSV está vacío o tiene formato inválido."], "unknown")

    headers = [h.strip() for h in reader.fieldnames if h]

    # Detect format
    yf_cols = {"symbol", "purchase price", "quantity"}
    lower_headers = {_normalize(h) for h in headers}
    is_yahoo = yf_cols.issubset(lower_headers)
    source_format = "yahoo_finance" if is_yahoo else "generic"

    # Map columns
    col_ticker = _find_col(headers, _TICKER_ALIASES)
    col_qty = _find_col(headers, _QTY_ALIASES)
    col_price = _find_col(headers, _PRICE_ALIASES)
    col_current = _find_col(headers, _CURRENT_PRICE_ALIASES)
    col_fee = _find_col(headers, _FEE_ALIASES)
    col_notes = _find_col(headers, _NOTES_ALIASES)
    col_date = _find_col(headers, _TRADE_DATE_ALIASES) or (
        None if is_yahoo else _find_col(headers, _GENERIC_DATE_ALIASES)
    )
    filas = list(reader)
    col_tipo = _find_col(headers, _TIPO_ALIASES)
    # Una watchlist de Yahoo puede traer la columna vacía en todas las filas: ahí sigue el modo
    # watchlist. Sólo un archivo con alguna operación cargada es una cartera con historia.
    if col_tipo and not any(
        (v or "").strip() for r in filas for k, v in r.items() if k and k.strip() == col_tipo
    ):
        col_tipo = None
    sin_fecha = 0

    if not col_ticker:
        return ImportResult([], [], ["No se encontró columna de ticker/símbolo en el CSV."], source_format)
    if not col_price:
        warnings.append(
            "No se encontró columna de precio de compra. "
            "Se usará 0.00 — podés editarlo después en cada posición."
        )

    for line_num, row in enumerate(filas, start=2):
        raw = {k.strip(): v.strip() for k, v in row.items() if k}

        ticker = raw.get(col_ticker, "").strip().upper()
        if not ticker or ticker in ("SYMBOL", "TICKER", "N/A", ""):
            skipped.append({"line": line_num, "reason": "Ticker vacío o encabezado", "raw": raw})
            continue

        # Skip market indices (^GSPC, ^SP500-45, etc.)
        if any(ticker.startswith(p) for p in _INDEX_PREFIXES):
            skipped.append({"line": line_num, "reason": f"Índice de mercado omitido: {ticker}", "raw": raw})
            continue

        # Parse quantity — may be empty in watchlist exports
        qty_str = raw.get(col_qty, "").replace(",", "").strip() if col_qty else ""
        try:
            qty = float(qty_str) if qty_str else 0.0
        except ValueError:
            qty = 0.0

        # Parse purchase price
        price = 0.0
        if col_price:
            price_str = raw.get(col_price, "").replace(",", "").replace("$", "").strip()
            try:
                price = float(price_str) if price_str else 0.0
            except ValueError:
                warnings.append(f"Línea {line_num}: precio inválido '{price_str}', se usará 0.00.")

        tipo = "BUY"
        if col_tipo:
            crudo = raw.get(col_tipo, "").strip().upper()
            if not crudo and qty <= 0:
                skipped.append({"line": line_num, "reason": f"{ticker} sin lotes en la cartera", "raw": raw})
                continue
            if crudo not in _TIPOS:
                skipped.append(
                    {"line": line_num, "reason": f"Tipo de operación desconocido '{crudo}'", "raw": raw}
                )
                continue
            tipo = _TIPOS[crudo]
            if qty <= 0 or price <= 0:
                skipped.append(
                    {
                        "line": line_num,
                        "reason": f"{ticker}: cantidad o precio inválido en una operación",
                        "raw": raw,
                    }
                )
                continue

        # ── Watchlist mode ────────────────────────────────────────────────────
        # When qty=0 and purchase_price=0 but current_price is available,
        # treat as a watchlist entry: qty=1, price=current_price.
        is_watchlist = False
        if (qty <= 0 or price <= 0) and not col_tipo:
            current_price_val = 0.0
            if col_current:
                cp_str = raw.get(col_current, "").replace(",", "").replace("$", "").strip()
                with contextlib.suppress(ValueError):
                    current_price_val = float(cp_str) if cp_str else 0.0
            if current_price_val > 0:
                qty = 1.0
                price = current_price_val
                is_watchlist = True
            else:
                reason = (
                    "Cantidad y precio = 0 (watchlist sin precio actual)"
                    if qty <= 0
                    else f"Cantidad <= 0: {qty}"
                )
                skipped.append({"line": line_num, "reason": reason, "raw": raw})
                continue
        # ─────────────────────────────────────────────────────────────────────

        # Parse commission
        fee = 0.0
        if col_fee:
            fee_str = raw.get(col_fee, "0").replace(",", "").replace("$", "").strip()
            with contextlib.suppress(ValueError):
                fee = float(fee_str) if fee_str else 0.0

        notes = raw.get(col_notes, "") if col_notes else ""

        trade_date = None
        if col_date:
            trade_date, motivo = parse_trade_date(raw.get(col_date, ""))
            if motivo:
                warnings.append(f"Línea {line_num} ({ticker}): {motivo}; queda con la fecha de hoy.")
        if trade_date is None and not is_watchlist:
            sin_fecha += 1

        rows.append(
            ImportRow(
                ticker=ticker,
                quantity=qty,
                buy_price=price,
                commission=fee,
                notes=notes,
                is_watchlist=is_watchlist,
                raw=raw,
                trade_date=trade_date,
                tipo=tipo,
            )
        )

    if sin_fecha:
        donde = (
            f"la columna '{col_date}'"
            if col_date
            else "ninguna columna de fecha de compra (p. ej. 'Trade Date')"
        )
        warnings.append(
            f"{sin_fecha} posición/es sin fecha de compra ({donde}): quedan con la fecha de hoy, "
            "y los dividendos cobrados se van a contar desde hoy."
        )

    if not rows and not skipped:
        warnings.append("El CSV no contiene filas de datos válidas.")

    return ImportResult(
        rows=rows,
        skipped=skipped,
        warnings=warnings,
        source_format=source_format,
    )


def parse_csv_file(path: str) -> ImportResult:
    """Read a CSV file from disk and parse it."""
    encodings = ["utf-8-sig", "utf-8", "latin-1", "cp1252"]
    for enc in encodings:
        try:
            with open(path, encoding=enc) as f:
                content = f.read()
            return parse_csv(content)
        except UnicodeDecodeError:
            continue
    return ImportResult([], [], ["No se pudo leer el archivo con las codificaciones soportadas."], "unknown")
