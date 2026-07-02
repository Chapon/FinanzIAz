"""
Tests del parser de fundamentals EDGAR XBRL (E1b).

Puros y offline: construyen payloads ``companyfacts`` a mano y verifican que
``parse_fundamental_facts`` extraiga solo períodos ANUALES, dedupe por fin de
año fiscal prefiriendo el valor framed, caiga a conceptos de revenue
alternativos y degrade a facts vacíos ante basura (→ fail open aguas arriba).
El fetch de red nunca se toca (la suite bloquea red).
"""

from __future__ import annotations

from data.edgar_fundamentals import (
    FundamentalFacts,
    _annual_series,
    _looks_annual,
    clear_facts_cache,
    get_fundamental_facts,
    parse_fundamental_facts,
)


def _entry(end: str, val: float, **kw) -> dict:
    e = {"end": end, "val": val}
    e.update(kw)
    return e


def _payload(net_income=None, revenue=None, revenue_concept="Revenues", entity="ACME"):
    gaap: dict = {}
    if net_income is not None:
        gaap["NetIncomeLoss"] = {"units": {"USD": net_income}}
    if revenue is not None:
        gaap[revenue_concept] = {"units": {"USD": revenue}}
    return {"entityName": entity, "facts": {"us-gaap": gaap}}


# ── _looks_annual ─────────────────────────────────────────────────────────────


def test_looks_annual_accepts_calendar_year_frame():
    assert _looks_annual(_entry("2023-12-31", 100, frame="CY2023"))


def test_looks_annual_rejects_quarterly_and_instant_frames():
    assert not _looks_annual(_entry("2023-03-31", 10, frame="CY2023Q1"))
    assert not _looks_annual(_entry("2023-12-31", 10, frame="CY2023Q4I"))


def test_looks_annual_accepts_fy_on_10k_without_frame():
    assert _looks_annual(_entry("2023-12-31", 100, fp="FY", form="10-K"))
    assert _looks_annual(_entry("2023-12-31", 100, fp="FY", form="20-F"))


def test_looks_annual_rejects_interim_periods():
    assert not _looks_annual(_entry("2023-09-30", 100, fp="Q3", form="10-Q"))


def test_looks_annual_duration_fallback():
    # ~1 año de span + fp FY, sin frame ni form reconocible → anual.
    assert _looks_annual(_entry("2022-12-31", 100, start="2022-01-01", fp="FY"))
    # Span corto (un trimestre) no cuenta como anual aunque diga FY.
    assert not _looks_annual(_entry("2022-03-31", 100, start="2022-01-01", fp="FY"))


# ── _annual_series ────────────────────────────────────────────────────────────


def test_annual_series_dedup_prefers_framed_value():
    entries = [
        _entry("2023-12-31", -55, fp="FY", form="10-K/A"),  # unframed (amended)
        _entry("2023-12-31", -50, frame="CY2023"),  # framed → authoritative
    ]
    out = _annual_series(entries, max_years=4)
    assert out == (("2023-12-31", -50.0),)


def test_annual_series_most_recent_first_and_truncates():
    entries = [
        _entry("2020-12-31", -20, frame="CY2020"),
        _entry("2023-12-31", -50, frame="CY2023"),
        _entry("2021-12-31", -30, frame="CY2021"),
        _entry("2022-12-31", -40, frame="CY2022"),
    ]
    out = _annual_series(entries, max_years=2)
    assert out == (("2023-12-31", -50.0), ("2022-12-31", -40.0))


def test_annual_series_ignores_quarterly_and_garbage():
    entries = [
        _entry("2023-03-31", 10, frame="CY2023Q1"),  # quarter → skip
        {"end": "2023-12-31"},  # no val → skip
        {"val": 5, "frame": "CY2023"},  # no end → skip
        "not-a-dict",
        _entry("2023-12-31", 99, frame="CY2023"),
    ]
    assert _annual_series(entries, max_years=4) == (("2023-12-31", 99.0),)


# ── parse_fundamental_facts ───────────────────────────────────────────────────


def test_parse_extracts_net_income_and_revenue():
    payload = _payload(
        net_income=[
            _entry("2022-12-31", -40_000_000, frame="CY2022"),
            _entry("2023-12-31", -50_000_000, frame="CY2023"),
        ],
        revenue=[_entry("2023-12-31", 2_000_000, frame="CY2023")],
    )
    facts = parse_fundamental_facts(payload, ticker="MLTX")
    assert facts.ticker == "MLTX"
    assert facts.net_income_recent == [-50_000_000.0, -40_000_000.0]
    assert facts.revenue_latest == 2_000_000.0
    assert facts.has_data


def test_parse_revenue_concept_fallback():
    payload = _payload(
        net_income=[_entry("2023-12-31", 10, frame="CY2023")],
        revenue=[_entry("2023-12-31", 123_000_000, frame="CY2023")],
        revenue_concept="RevenueFromContractWithCustomerExcludingAssessedTax",
    )
    facts = parse_fundamental_facts(payload)
    assert facts.revenue_latest == 123_000_000.0


def test_parse_empty_and_garbage_return_empty_facts():
    for bad in (None, {}, {"facts": {}}, {"facts": {"us-gaap": {}}}, {"facts": 123}):
        facts = parse_fundamental_facts(bad, ticker="X")
        assert isinstance(facts, FundamentalFacts)
        assert not facts.has_data
        assert facts.net_income_recent == []
        assert facts.revenue_latest is None


def test_parse_uses_entity_name_when_ticker_blank():
    facts = parse_fundamental_facts(_payload(entity="MoonLake"), ticker="")
    assert facts.ticker == "MoonLake"


# ── get_fundamental_facts (cache) ─────────────────────────────────────────────


def test_get_fundamental_facts_caches_per_process(monkeypatch):
    clear_facts_cache()
    calls = {"n": 0}

    def fake_fetch(ticker, **kw):
        calls["n"] += 1
        return _payload(net_income=[_entry("2023-12-31", -1, frame="CY2023")])

    import data.edgar_fundamentals as ef

    monkeypatch.setattr(ef, "fetch_company_facts", fake_fetch)
    a = get_fundamental_facts("ZZZ")
    b = get_fundamental_facts("ZZZ")
    assert calls["n"] == 1  # second call served from cache
    assert a == b
    clear_facts_cache()
    get_fundamental_facts("ZZZ")
    assert calls["n"] == 2  # cache cleared → refetched
