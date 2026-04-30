"""
CSV importer for FinanzIAs.
Supports Yahoo Finance export format and a generic fallback format.

Yahoo Finance CSV columns (typical):
  Symbol, Current Price, Date, Time, Change, Open, High, Low, Volume,
  Trade Date, Purchase Price, Quantity, Commission, High Limit, Low Limit, Comment

Generic fallback (minimum required columns):
  ticker/symbol, quantity/shares, price/buy_price/purchase_price
"""
import csv
import io
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ImportRow:
    ticker: str
    quantity: float
    buy_price: float
    commission: float = 0.0
    notes: str = ""
    is_watchlist: bool = False   # True when imported from a watchlist (qty was 0)
    raw: dict = field(default_factory=dict)


@dataclass
class ImportResult:
    rows: list[ImportRow]
    skipped: list[dict]       # rows that couldn't be parsed
    warnings: list[str]
    source_format: str        # "yahoo_finance" | "generic"


# Column name aliases (lowercased)
_TICKER_ALIASES         = {"symbol", "ticker", "stock", "código", "codigo"}
_QTY_ALIASES            = {"quantity", "shares", "cantidad", "qty", "number of shares"}
_PRICE_ALIASES          = {"purchase price", "buy price", "buy_price", "precio compra",
                            "precio de compra", "average cost", "avg cost", "cost basis",
                            "price", "precio"}
_CURRENT_PRICE_ALIASES  = {"current price", "precio actual", "last price", "last"}
_FEE_ALIASES            = {"commission", "comisión", "comision", "fee", "fees"}
_NOTES_ALIASES          = {"comment", "notes", "nota", "notas", "description"}

# Prefixes that identify indices or non-tradeable symbols to skip
_INDEX_PREFIXES = ("^",)


def _normalize(col: str) -> str:
    return col.strip().lower().replace("_", " ").replace("-", " ")


def _find_col(headers: list[str], aliases: set) -> Optional[str]:
    """Return the first header that matches any alias."""
    for h in headers:
        if _normalize(h) in aliases:
            return h
    return None


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
    col_ticker  = _find_col(headers, _TICKER_ALIASES)
    col_qty     = _find_col(headers, _QTY_ALIASES)
    col_price   = _find_col(headers, _PRICE_ALIASES)
    col_current = _find_col(headers, _CURRENT_PRICE_ALIASES)
    col_fee     = _find_col(headers, _FEE_ALIASES)
    col_notes   = _find_col(headers, _NOTES_ALIASES)

    if not col_ticker:
        return ImportResult([], [], ["No se encontró columna de ticker/símbolo en el CSV."], source_format)
    if not col_price:
        warnings.append(
            "No se encontró columna de precio de compra. "
            "Se usará 0.00 — podés editarlo después en cada posición."
        )

    for line_num, row in enumerate(reader, start=2):
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

        # ── Watchlist mode ────────────────────────────────────────────────────
        # When qty=0 and purchase_price=0 but current_price is available,
        # treat as a watchlist entry: qty=1, price=current_price.
        is_watchlist = False
        if qty <= 0 or price <= 0:
            current_price_val = 0.0
            if col_current:
                cp_str = raw.get(col_current, "").replace(",", "").replace("$", "").strip()
                try:
                    current_price_val = float(cp_str) if cp_str else 0.0
                except ValueError:
                    pass
            if current_price_val > 0:
                qty = 1.0
                price = current_price_val
                is_watchlist = True
            else:
                reason = "Cantidad y precio = 0 (watchlist sin precio actual)" if qty <= 0 else f"Cantidad <= 0: {qty}"
                skipped.append({"line": line_num, "reason": reason, "raw": raw})
                continue
        # ─────────────────────────────────────────────────────────────────────

        # Parse commission
        fee = 0.0
        if col_fee:
            fee_str = raw.get(col_fee, "0").replace(",", "").replace("$", "").strip()
            try:
                fee = float(fee_str) if fee_str else 0.0
            except ValueError:
                pass

        notes = raw.get(col_notes, "") if col_notes else ""

        rows.append(ImportRow(
            ticker=ticker,
            quantity=qty,
            buy_price=price,
            commission=fee,
            notes=notes,
            is_watchlist=is_watchlist,
            raw=raw,
        ))

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
    return ImportResult([], [], [f"No se pudo leer el archivo con las codificaciones soportadas."], "unknown")
