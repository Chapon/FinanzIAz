"""
Ingester de los **SEC Form 345 quarterly datasets** → transacciones de insider
normalizadas (``InsiderTx``). Enabler del backtest de la **Tarea 12 (FORM4)**.

Pre-registro: ``docs/insider_cluster_prereg_t12_2026-07-24.md`` §3.1.

Por qué esta fuente (decisión de calidad, orden de Chapa 2026-06-25)
-------------------------------------------------------------------
Los Insider Transactions Data Sets de la SEC son un zip **por trimestre** con TSV
normalizados (``SUBMISSION`` / ``REPORTINGOWNER`` / ``NONDERIV_TRANS``). Frente a
full-text search (miles de requests rate-limited) o parsear el XML de cada Form 4
uno por uno (decenas de miles de fetches para 10y × S&P 500), el bulk es **una
descarga por trimestre** y ya viene parseado. La columna ``FILING_DATE`` es la
fecha oficial de disclosure → **point-in-time**, sin sesgo de revisión.

Reproducible y offline tras la descarga: los zips se bajan a ``data/form345/``
(gitignored, como ``data/pit_signals/``) y esto los normaliza a un artefacto local
``insider_txs.json`` (``{ticker: [tx, ...]}``) que consume el harness. NO toca
``finanzias.db``.

La **lógica de parseo/join/filtro es pura** (``parse_form345_tables``) y se testea
offline con TSV sintéticos. La descarga es un wrapper fino y guardado (nunca hunde
el resto de los trimestres si uno falla). Los nombres exactos de columna del
dataset se resuelven por header (tolerante a variaciones) y se fijan contra el dato
real en la primera corrida con red (etapa ``backtest-runner``).

Uso:
    python scripts/ingest_form345.py --start 2016q1 --end 2026q2 \
        --universe data/sp500_universe.txt --dest data/form345
"""

from __future__ import annotations

import argparse
import io
import json
import logging
import sys
import zipfile
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

from analysis.insider_cluster import InsiderTx

log = logging.getLogger("ingest_form345")

# La ruta del dataset en sec.gov. Se puede overridear por CLI si la SEC la mueve;
# se verifica contra el dato real en la primera corrida con red.
FORM345_URL_TEMPLATE = (
    "https://www.sec.gov/files/structureddata/data/insider-transactions-data-sets/{year}q{q}_form345.zip"
)

_MONTHS = {
    "JAN": 1,
    "FEB": 2,
    "MAR": 3,
    "APR": 4,
    "MAY": 5,
    "JUN": 6,
    "JUL": 7,
    "AUG": 8,
    "SEP": 9,
    "OCT": 10,
    "NOV": 11,
    "DEC": 12,
}
_TRUTHY = {"1", "Y", "YES", "TRUE", "T"}


# ── Parseo puro (offline-testable) ───────────────────────────────────────────


def _split_tsv(text: str) -> tuple[list[str], list[list[str]]]:
    """(header_uppercase, filas). Tolera CRLF y líneas vacías finales."""
    lines = [ln for ln in text.replace("\r\n", "\n").replace("\r", "\n").split("\n") if ln != ""]
    if not lines:
        return [], []
    header = [h.strip().upper() for h in lines[0].split("\t")]
    rows = [ln.split("\t") for ln in lines[1:]]
    return header, rows


def _col(header: list[str], *candidates: str) -> int | None:
    """Índice de la primera columna cuyo nombre (uppercase) matchea un candidato."""
    for cand in candidates:
        c = cand.upper()
        if c in header:
            return header.index(c)
    return None


def _get(row: list[str], idx: int | None) -> str:
    if idx is None or idx < 0 or idx >= len(row):
        return ""
    return row[idx].strip()


def _parse_form345_date(s: str) -> str | None:
    """``DD-MON-YYYY`` o ISO ``YYYY-MM-DD`` → ISO ``YYYY-MM-DD``. None si no parsea."""
    s = (s or "").strip()
    if not s:
        return None
    # ISO ya normalizado
    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        try:
            y, m, d = int(s[0:4]), int(s[5:7]), int(s[8:10])
            return f"{y:04d}-{m:02d}-{d:02d}"
        except ValueError:
            return None
    # DD-MON-YYYY (formato clásico de los datasets DERA)
    parts = s.split("-")
    if len(parts) == 3 and parts[1].upper() in _MONTHS:
        try:
            d = int(parts[0])
            m = _MONTHS[parts[1].upper()]
            y = int(parts[2])
            return f"{y:04d}-{m:02d}-{d:02d}"
        except ValueError:
            return None
    return None


def _to_float(s: str) -> float:
    try:
        return float(str(s).replace(",", "").strip())
    except (ValueError, AttributeError):
        return float("nan")


def _is_officer(rel_text: str, flag: str) -> bool:
    if flag.strip().upper() in _TRUTHY:
        return True
    return "OFFICER" in (rel_text or "").upper()


def _is_director(rel_text: str, flag: str) -> bool:
    if flag.strip().upper() in _TRUTHY:
        return True
    return "DIRECTOR" in (rel_text or "").upper()


def parse_form345_tables(
    submission_text: str,
    owner_text: str,
    nonderiv_text: str,
    *,
    universe: set[str] | None = None,
) -> list[InsiderTx]:
    """Joinea SUBMISSION × REPORTINGOWNER × NONDERIV_TRANS por ``ACCESSION_NUMBER``
    y emite una ``InsiderTx`` por línea no-derivativa.

    NO aplica el filtro ``P/A`` (eso lo hace el detector, §2 del pre-registro) — emite
    todas las transacciones no-derivativas para acumular el dato (variantes futuras).
    Si ``universe`` se pasa, filtra a issuers con ticker en el set (uppercase).
    Función pura: sin red, sin DB. Tolerante a columnas faltantes.
    """
    s_head, s_rows = _split_tsv(submission_text)
    o_head, o_rows = _split_tsv(owner_text)
    n_head, n_rows = _split_tsv(nonderiv_text)

    # SUBMISSION: accession → (ticker, filing_date_iso)
    s_acc = _col(s_head, "ACCESSION_NUMBER")
    s_date = _col(s_head, "FILING_DATE")
    s_sym = _col(s_head, "ISSUERTRADINGSYMBOL", "ISSUER_TRADING_SYMBOL")
    submissions: dict[str, tuple[str, str]] = {}
    for row in s_rows:
        acc = _get(row, s_acc)
        if not acc:
            continue
        ticker = _get(row, s_sym).upper()
        fdate = _parse_form345_date(_get(row, s_date))
        if not ticker or fdate is None:
            continue
        if universe is not None and ticker not in universe:
            continue
        submissions[acc] = (ticker, fdate)

    # REPORTINGOWNER: accession → (owner_cik, is_officer, is_director)
    o_acc = _col(o_head, "ACCESSION_NUMBER")
    o_cik = _col(o_head, "RPTOWNERCIK", "RPTOWNER_CIK")
    o_rel = _col(o_head, "RPTOWNER_RELATIONSHIP", "RPTOWNER_RELATION", "RPTOWNER_TITLE")
    o_isoff = _col(o_head, "RPTOWNER_ISOFFICER", "ISOFFICER")
    o_isdir = _col(o_head, "RPTOWNER_ISDIRECTOR", "ISDIRECTOR")
    owners: dict[str, tuple[str, bool, bool]] = {}
    for row in o_rows:
        acc = _get(row, o_acc)
        if not acc or acc in owners:  # un owner primario por accession (el primero)
            continue
        cik = _get(row, o_cik)
        rel = _get(row, o_rel)
        owners[acc] = (
            cik,
            _is_officer(rel, _get(row, o_isoff)),
            _is_director(rel, _get(row, o_isdir)),
        )

    # NONDERIV_TRANS: una InsiderTx por fila, joineada a submission + owner.
    t_acc = _col(n_head, "ACCESSION_NUMBER")
    t_code = _col(n_head, "TRANS_CODE")
    t_ad = _col(n_head, "TRANS_ACQUIRED_DISP_CD", "TRANS_ACQUIRED_DISP_CODE")
    t_sh = _col(n_head, "TRANS_SHARES")
    t_pr = _col(n_head, "TRANS_PRICEPERSHARE", "TRANS_PRICE_PER_SHARE")
    out: list[InsiderTx] = []
    for row in n_rows:
        acc = _get(row, t_acc)
        sub = submissions.get(acc)
        if sub is None:
            continue
        ticker, fdate = sub
        cik, is_off, is_dir = owners.get(acc, ("", False, False))
        out.append(
            InsiderTx(
                issuer_ticker=ticker,
                filing_date=fdate,
                owner_cik=cik,
                trans_code=_get(row, t_code).upper(),
                acq_disp=_get(row, t_ad).upper(),
                shares=_to_float(_get(row, t_sh)),
                price=_to_float(_get(row, t_pr)),
                accession=acc,
                is_officer=is_off,
                is_director=is_dir,
            )
        )
    return out


# ── Descarga + CLI (wrapper fino, guardado — no unit-tested por red) ──────────


def _parse_quarter(tag: str) -> tuple[int, int]:
    """'2016q1' → (2016, 1)."""
    tag = tag.strip().lower()
    if "q" not in tag:
        raise ValueError(f"trimestre inválido: {tag!r} (esperado 'YYYYqN')")
    y, q = tag.split("q", 1)
    return int(y), int(q)


def _quarters(start: str, end: str) -> list[tuple[int, int]]:
    y0, q0 = _parse_quarter(start)
    y1, q1 = _parse_quarter(end)
    out: list[tuple[int, int]] = []
    y, q = y0, q0
    while (y, q) <= (y1, q1):
        out.append((y, q))
        q += 1
        if q > 4:
            q, y = 1, y + 1
    return out


def _read_zip_member(zf: zipfile.ZipFile, name: str) -> str:
    """Lee un TSV del zip por nombre case-insensitive; '' si no está."""
    lname = name.lower()
    for member in zf.namelist():
        if member.lower().rsplit("/", 1)[-1] == lname:
            return zf.read(member).decode("utf-8", errors="replace")
    return ""


def ingest_quarter(
    year: int,
    q: int,
    *,
    universe: set[str] | None,
    session=None,
    url_template: str = FORM345_URL_TEMPLATE,
    cache_dir: Path | None = None,
) -> list[InsiderTx]:
    """Baja (o lee del cache) el zip del trimestre y devuelve sus InsiderTx.
    Guardado: cualquier fallo devuelve [] y loguea (no rompe el loop de trimestres)."""
    try:
        import requests  # noqa: F401

        url = url_template.format(year=year, q=q)
        blob: bytes | None = None
        cached: Path | None = None
        if cache_dir is not None:
            cached = cache_dir / f"{year}q{q}_form345.zip"
            if cached.exists():
                blob = cached.read_bytes()
        if blob is None:
            from data.news_sources import _sec_session

            sess = session or _sec_session()
            r = sess.get(url, timeout=60)
            r.raise_for_status()
            blob = r.content
            if cached is not None:
                cache_dir.mkdir(parents=True, exist_ok=True)
                cached.write_bytes(blob)
        with zipfile.ZipFile(io.BytesIO(blob)) as zf:
            sub = _read_zip_member(zf, "SUBMISSION.tsv")
            own = _read_zip_member(zf, "REPORTINGOWNER.tsv")
            non = _read_zip_member(zf, "NONDERIV_TRANS.tsv")
        return parse_form345_tables(sub, own, non, universe=universe)
    except Exception:
        log.exception("ingest_quarter %sq%s falló", year, q)
        return []


def _load_universe(path: str | None) -> set[str] | None:
    if not path:
        return None
    p = Path(path)
    if not p.exists():
        log.warning("universe file no encontrado: %s (sin filtro)", path)
        return None
    out: set[str] = set()
    for line in p.read_text(encoding="utf-8").splitlines():
        s = line.strip().upper()
        if s and not s.startswith("#"):
            out.add(s)
    return out or None


def write_artifact(txs: list[InsiderTx], out_path: Path) -> int:
    """Escribe ``{ticker: [tx_dict, ...]}`` a JSON. Devuelve el nº de transacciones."""
    by_ticker: dict[str, list[dict]] = {}
    for tx in txs:
        by_ticker.setdefault(tx.issuer_ticker, []).append(
            {
                "filing_date": tx.filing_date,
                "owner_cik": tx.owner_cik,
                "trans_code": tx.trans_code,
                "acq_disp": tx.acq_disp,
                "shares": tx.shares,
                "price": tx.price,
                "accession": tx.accession,
                "is_officer": tx.is_officer,
                "is_director": tx.is_director,
            }
        )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(by_ticker, separators=(",", ":")), encoding="utf-8")
    return len(txs)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(description="Ingester de los SEC Form 345 quarterly datasets")
    ap.add_argument("--start", required=True, help="trimestre inicial, ej. 2016q1")
    ap.add_argument("--end", required=True, help="trimestre final, ej. 2026q2")
    ap.add_argument("--universe", default=None, help="archivo de tickers (uno por línea) para filtrar")
    ap.add_argument("--dest", default="data/form345", help="carpeta de salida + cache de zips")
    ap.add_argument("--url-template", default=FORM345_URL_TEMPLATE)
    args = ap.parse_args(argv)

    dest = Path(args.dest)
    universe = _load_universe(args.universe)
    all_txs: list[InsiderTx] = []
    for year, q in _quarters(args.start, args.end):
        txs = ingest_quarter(
            year, q, universe=universe, url_template=args.url_template, cache_dir=dest / "raw"
        )
        log.info("%sq%s: %d transacciones no-derivativas", year, q, len(txs))
        all_txs.extend(txs)

    out_path = dest / "insider_txs.json"
    n = write_artifact(all_txs, out_path)
    tickers = len({tx.issuer_ticker for tx in all_txs})
    log.info("Escrito %s: %d transacciones sobre %d tickers", out_path, n, tickers)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
