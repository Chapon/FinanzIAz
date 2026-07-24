"""
Tests de ``analysis.insider_cluster`` (detector de cluster de insiders) y del
parseo puro de ``scripts.ingest_form345`` — Tarea 12 (FORM4).
Pre-registro: ``docs/insider_cluster_prereg_t12_2026-07-24.md``.

Qué fijan (detector):
1. Dispara cuando ≥ C insiders DISTINTOS compran open-market en la ventana W.
2. NO dispara con < C distintos; **distinct por CIK** (varias líneas del mismo
   owner cuentan como uno).
3. Ventana W: insiders repartidos fuera de la ventana no clusterizan; el borde
   exacto (span = W días) sí.
4. Filtro de código: ventas (S), grants (A), ejercicios (M) y disposiciones
   (acq_disp=D) NO cuentan; NaN en shares/price se descarta.
5. Point-in-time: el ``event_date`` es la ``filing_date`` del filing que cruza a C.
6. Dedup/re-arm: una continuación dentro de la ventana no emite otro evento; un
   cluster genuinamente nuevo (tras la ventana, incluso same-day) sí re-dispara.
7. ``require_officer`` (arm senior): exige ≥1 officer en la ventana.
8. ``total_dollars`` / ``n_insiders`` correctos; orden determinista (date, ticker).
9. Fail-safe: entrada vacía / fecha inválida → sin crash.

Qué fijan (ingester puro):
10. Join SUBMISSION×REPORTINGOWNER×NONDERIV por accession; date DD-MON-YYYY e ISO;
    flag officer por columna o por texto de relación; filtro por universo; filas
    sin submission descartadas; columnas faltantes toleradas.
"""

from __future__ import annotations

import math

from analysis.insider_cluster import (
    ClusterParams,
    InsiderTx,
    build_cluster_events,
    passes_purchase_filter,
)
from scripts.ingest_form345 import _parse_form345_date, _quarters, parse_form345_tables


# ── Builders sintéticos ──────────────────────────────────────────────────────


def _tx(
    *,
    ticker="ABC",
    filing="2022-01-10",
    cik="1",
    code="P",
    ad="A",
    shares=100.0,
    price=10.0,
    acc=None,
    officer=False,
    director=False,
):
    return InsiderTx(
        issuer_ticker=ticker,
        filing_date=filing,
        owner_cik=cik,
        trans_code=code,
        acq_disp=ad,
        shares=shares,
        price=price,
        accession=acc or f"{ticker}-{cik}-{filing}",
        is_officer=officer,
        is_director=director,
    )


def _cluster(ticker="ABC", dates=("2022-01-01", "2022-01-05", "2022-01-10")):
    """Un cluster limpio: un cik distinto por fecha."""
    return [_tx(ticker=ticker, cik=str(i + 1), filing=d) for i, d in enumerate(dates)]


# ── Detector ─────────────────────────────────────────────────────────────────


def test_fires_with_three_distinct_insiders():
    events = build_cluster_events(_cluster())
    assert len(events) == 1
    ev = events[0]
    assert ev.ticker == "ABC"
    assert ev.event_date == "2022-01-10"   # PIT: la 3ra filing, la que cruza a C
    assert ev.n_insiders == 3


def test_no_fire_with_two_distinct():
    txs = [_tx(cik="1", filing="2022-01-01"), _tx(cik="2", filing="2022-01-05")]
    assert build_cluster_events(txs) == []


def test_distinct_by_cik_not_by_filing():
    # 3 filings pero solo 2 owners → no dispara con C=3.
    txs = [
        _tx(cik="1", filing="2022-01-01"),
        _tx(cik="1", filing="2022-01-03", acc="dup"),
        _tx(cik="2", filing="2022-01-05"),
    ]
    assert build_cluster_events(txs) == []


def test_window_boundary_outside_does_not_cluster():
    # Repartidos de modo que nunca hay 3 en ninguna ventana de 15 días.
    txs = [
        _tx(cik="1", filing="2022-01-01"),
        _tx(cik="2", filing="2022-01-14"),
        _tx(cik="3", filing="2022-01-30"),
    ]
    assert build_cluster_events(txs) == []


def test_window_boundary_exact_span_fires():
    # Span exacto de 15 días (01-01 .. 01-15) → los 3 caen en la ventana de 01-15.
    txs = _cluster(dates=("2022-01-01", "2022-01-08", "2022-01-15"))
    events = build_cluster_events(txs)
    assert len(events) == 1
    assert events[0].event_date == "2022-01-15"


def test_code_filter_excludes_non_purchases():
    txs = [
        _tx(cik="1", code="S", filing="2022-01-01"),        # venta
        _tx(cik="2", code="A", filing="2022-01-05"),        # grant/award
        _tx(cik="3", code="M", filing="2022-01-08"),        # ejercicio de opción
        _tx(cik="4", code="P", ad="D", filing="2022-01-10"),  # P pero disposición
    ]
    assert build_cluster_events(txs) == []


def test_mixed_valid_and_invalid_counts_only_valid():
    # 2 compras válidas + 1 venta → solo 2 válidas → no dispara con C=3.
    txs = [
        _tx(cik="1", code="P", filing="2022-01-01"),
        _tx(cik="2", code="P", filing="2022-01-05"),
        _tx(cik="3", code="S", filing="2022-01-08"),
    ]
    assert build_cluster_events(txs) == []


def test_nan_shares_or_price_excluded():
    txs = [
        _tx(cik="1", filing="2022-01-01"),
        _tx(cik="2", filing="2022-01-05"),
        _tx(cik="3", filing="2022-01-08", price=float("nan")),  # inválida
    ]
    assert build_cluster_events(txs) == []


def test_continuation_within_window_does_not_refire():
    txs = _cluster() + [_tx(cik="4", filing="2022-01-12")]  # 4to dentro de la ventana
    events = build_cluster_events(txs)
    assert len(events) == 1
    assert events[0].event_date == "2022-01-10"


def test_new_cluster_after_window_refires():
    txs = _cluster(dates=("2022-01-01", "2022-01-05", "2022-01-10")) + _cluster(
        dates=("2022-03-01", "2022-03-05", "2022-03-10")
    )
    # segundo cluster reusa cik 1/2/3 pero está separado > W → cuenta como nuevo.
    events = build_cluster_events(txs)
    assert [e.event_date for e in events] == ["2022-01-10", "2022-03-10"]


def test_same_day_new_cluster_after_full_window_refires():
    # Edge: dispara, luego un cluster same-day 41 días después SIN filings
    # intermedios. El guard 'pasó una ventana entera' evita perderlo.
    txs = [
        _tx(cik="1", filing="2022-01-10"),
        _tx(cik="2", filing="2022-01-10", acc="a2"),
        _tx(cik="3", filing="2022-01-10", acc="a3"),
        _tx(cik="4", filing="2022-02-20"),
        _tx(cik="5", filing="2022-02-20", acc="b5"),
        _tx(cik="6", filing="2022-02-20", acc="b6"),
    ]
    events = build_cluster_events(txs)
    assert [e.event_date for e in events] == ["2022-01-10", "2022-02-20"]


def test_require_officer_arm():
    base = _cluster()  # ningún officer
    assert build_cluster_events(base, ClusterParams(require_officer=True)) == []
    with_officer = base[:2] + [_tx(cik="3", filing="2022-01-10", officer=True)]
    events = build_cluster_events(with_officer, ClusterParams(require_officer=True))
    assert len(events) == 1
    assert events[0].has_officer is True


def test_total_dollars_and_n_insiders():
    txs = [
        _tx(cik="1", filing="2022-01-01", shares=100, price=10),   # 1000
        _tx(cik="2", filing="2022-01-05", shares=200, price=5),    # 1000
        _tx(cik="3", filing="2022-01-10", shares=50, price=20),    # 1000
    ]
    ev = build_cluster_events(txs)[0]
    assert ev.n_insiders == 3
    assert math.isclose(ev.total_dollars, 3000.0)


def test_ordering_is_deterministic_by_date_then_ticker():
    txs = _cluster(ticker="ZZZ", dates=("2022-01-01", "2022-01-05", "2022-01-10")) + _cluster(
        ticker="AAA", dates=("2022-01-02", "2022-01-06", "2022-01-10")
    )
    events = build_cluster_events(txs)
    # Mismo event_date (01-10) → desempate alfabético por ticker.
    assert [(e.event_date, e.ticker) for e in events] == [
        ("2022-01-10", "AAA"),
        ("2022-01-10", "ZZZ"),
    ]


def test_empty_and_bad_dates_are_safe():
    assert build_cluster_events([]) == []
    bad = [
        _tx(cik="1", filing="not-a-date"),
        _tx(cik="2", filing=""),
        _tx(cik="3", filing="2022-13-99"),
    ]
    assert build_cluster_events(bad) == []


def test_custom_c_and_w():
    # C=2, W=5: dos insiders en 5 días disparan.
    txs = [_tx(cik="1", filing="2022-01-01"), _tx(cik="2", filing="2022-01-04")]
    events = build_cluster_events(txs, ClusterParams(min_insiders=2, window_days=5))
    assert len(events) == 1


def test_passes_purchase_filter_unit():
    assert passes_purchase_filter(_tx(code="P", ad="A")) is True
    assert passes_purchase_filter(_tx(code="S", ad="A")) is False
    assert passes_purchase_filter(_tx(code="P", ad="D")) is False
    assert passes_purchase_filter(_tx(code="P", ad="A", price=0)) is False
    assert passes_purchase_filter(_tx(code="P", ad="A", cik="")) is False


# ── Ingester (parseo puro) ───────────────────────────────────────────────────

_SUB = (
    "ACCESSION_NUMBER\tFILING_DATE\tISSUERTRADINGSYMBOL\n"
    "0001-A\t10-JAN-2022\tABC\n"
    "0002-A\t2022-01-11\tXYZ\n"
)
_OWN = (
    "ACCESSION_NUMBER\tRPTOWNERCIK\tRPTOWNER_RELATIONSHIP\tRPTOWNER_ISOFFICER\n"
    "0001-A\t111\tOfficer\t1\n"
    "0002-A\t222\tDirector\t0\n"
)
_NON = (
    "ACCESSION_NUMBER\tTRANS_CODE\tTRANS_ACQUIRED_DISP_CD\tTRANS_SHARES\tTRANS_PRICEPERSHARE\n"
    "0001-A\tP\tA\t100\t10.5\n"
    "0002-A\tS\tD\t50\t20\n"
)


def test_parse_joins_three_tables():
    txs = parse_form345_tables(_SUB, _OWN, _NON)
    assert len(txs) == 2
    by_t = {t.issuer_ticker: t for t in txs}
    a = by_t["ABC"]
    assert a.filing_date == "2022-01-10"     # DD-MON-YYYY → ISO
    assert a.owner_cik == "111"
    assert a.trans_code == "P" and a.acq_disp == "A"
    assert math.isclose(a.shares, 100.0) and math.isclose(a.price, 10.5)
    assert a.is_officer is True
    x = by_t["XYZ"]
    assert x.filing_date == "2022-01-11"     # ISO passthrough
    assert x.trans_code == "S"
    assert x.is_director is True and x.is_officer is False


def test_parse_universe_filter():
    txs = parse_form345_tables(_SUB, _OWN, _NON, universe={"ABC"})
    assert len(txs) == 1 and txs[0].issuer_ticker == "ABC"


def test_parse_drops_rows_without_submission():
    non = (
        "ACCESSION_NUMBER\tTRANS_CODE\tTRANS_ACQUIRED_DISP_CD\tTRANS_SHARES\tTRANS_PRICEPERSHARE\n"
        "9999-X\tP\tA\t100\t10\n"   # accession inexistente en SUBMISSION
    )
    assert parse_form345_tables(_SUB, _OWN, non) == []


def test_parse_officer_from_relationship_text_without_flag_column():
    own = (
        "ACCESSION_NUMBER\tRPTOWNERCIK\tRPTOWNER_RELATIONSHIP\n"
        "0001-A\t111\tOfficer, Director\n"
    )
    txs = parse_form345_tables(_SUB, own, _NON, universe={"ABC"})
    assert txs[0].is_officer is True
    assert txs[0].is_director is True


def test_parse_tolerates_empty_and_missing_columns():
    assert parse_form345_tables("", "", "") == []
    # NONDERIV sin columna de precio → shares/price NaN pero no crashea.
    non = "ACCESSION_NUMBER\tTRANS_CODE\tTRANS_ACQUIRED_DISP_CD\n0001-A\tP\tA\n"
    txs = parse_form345_tables(_SUB, _OWN, non, universe={"ABC"})
    assert len(txs) == 1
    assert math.isnan(txs[0].price)


def test_parse_date_formats():
    assert _parse_form345_date("02-JAN-2023") == "2023-01-02"
    assert _parse_form345_date("2023-01-02") == "2023-01-02"
    assert _parse_form345_date("garbage") is None
    assert _parse_form345_date("") is None


def test_quarters_range():
    assert _quarters("2016q1", "2016q4") == [(2016, 1), (2016, 2), (2016, 3), (2016, 4)]
    assert _quarters("2015q4", "2016q2") == [(2015, 4), (2016, 1), (2016, 2)]
    assert _quarters("2020q3", "2020q3") == [(2020, 3)]
