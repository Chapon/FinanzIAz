"""Tarea 382 — fundamentals point-in-time desde EDGAR: lo que se sabía en cada fecha, y nada más.

Payloads sintéticos con la forma de ``companyfacts``: sin red.
"""

from __future__ import annotations

from data.fundamentos_pit import (
    Fundamentos,
    es_extranjera,
    parse_registros,
    unir,
)


def _dur(end, val, filed, form="10-K", fp="FY", start=None):
    y = int(end[:4])
    return {"start": start or f"{y}-01-01", "end": end, "val": val, "filed": filed, "form": form, "fp": fp}


def _inst(end, val, filed, form="10-K"):
    return {"end": end, "val": val, "filed": filed, "form": form, "fp": "FY"}


def _payload(tags: dict[str, list[dict]], unidad="USD", tax="us-gaap") -> dict:
    return {"facts": {tax: {t: {"units": {unidad: es}} for t, es in tags.items()}}}


def _fund(payload) -> Fundamentos:
    return unir("X", [(1, payload)])


def test_un_dato_no_existe_antes_de_su_filed_ni_el_mismo_dia():
    f = _fund(_payload({"NetIncomeLoss": [_dur("2019-12-31", 100.0, "2020-02-20")]}))
    assert f.serie("ganancia_neta", "2020-02-20") == []  # el mismo día no: se presenta después del cierre
    assert f.serie("ganancia_neta", "2020-02-21") == [("2019-12-31", 100.0)]


def test_un_numero_reexpresado_vale_desde_que_se_presenta_y_no_antes():
    """El 10-K del año siguiente trae el 2019 como comparativo, corregido a 90."""
    f = _fund(
        _payload(
            {
                "NetIncomeLoss": [
                    _dur("2019-12-31", 100.0, "2020-02-20"),
                    _dur("2019-12-31", 90.0, "2021-02-20"),
                ]
            }
        )
    )
    assert f.serie("ganancia_neta", "2020-06-01") == [("2019-12-31", 100.0)]
    assert f.serie("ganancia_neta", "2021-03-01") == [("2019-12-31", 90.0)]


def test_la_enmienda_10KA_cuenta_desde_su_fecha():
    f = _fund(
        _payload(
            {
                "NetIncomeLoss": [
                    _dur("2019-12-31", 100.0, "2020-02-20"),
                    _dur("2019-12-31", 95.0, "2020-05-10", form="10-K/A"),
                ]
            }
        )
    )
    assert f.serie("ganancia_neta", "2020-05-10") == [("2019-12-31", 100.0)]
    assert f.serie("ganancia_neta", "2020-05-11") == [("2019-12-31", 95.0)]


def test_la_cascada_es_por_anio_no_por_empresa():
    """Antes de 2018 el revenue va en SalesRevenueNet y después en RevenueFromContract…

    Elegir un solo tag por empresa (el primero de la cascada que tenga algo) daría dos años.
    """
    f = _fund(
        _payload(
            {
                "SalesRevenueNet": [
                    _dur("2016-12-31", 10.0, "2017-02-01"),
                    _dur("2017-12-31", 11.0, "2018-02-01"),
                ],
                "RevenueFromContractWithCustomerExcludingAssessedTax": [
                    _dur("2018-12-31", 12.0, "2019-02-01"),
                    _dur("2019-12-31", 13.0, "2020-02-01"),
                ],
            }
        )
    )
    assert [v for _, v in f.serie("revenue", "2021-01-01")] == [10.0, 11.0, 12.0, 13.0]


def test_en_el_mismo_anio_manda_el_tag_preferido_aunque_se_haya_presentado_antes():
    f = _fund(
        _payload(
            {
                "Revenues": [_dur("2019-12-31", 100.0, "2020-02-01")],
                "SalesRevenueNet": [_dur("2019-12-31", 999.0, "2021-02-01")],
            }
        )
    )
    assert f.serie("revenue", "2022-01-01") == [("2019-12-31", 100.0)]


def test_ganancia_bruta_directa_o_ventas_menos_costo():
    f = _fund(
        _payload(
            {
                "Revenues": [
                    _dur("2018-12-31", 100.0, "2019-02-01"),
                    _dur("2019-12-31", 200.0, "2020-02-01"),
                ],
                "CostOfRevenue": [
                    _dur("2018-12-31", 60.0, "2019-02-01"),
                    _dur("2019-12-31", 150.0, "2020-02-01"),
                ],
                "GrossProfit": [_dur("2019-12-31", 55.0, "2020-02-01")],
            }
        )
    )
    # 2018 sin GrossProfit: 100 − 60. 2019 con GrossProfit: el reportado (55), no 200 − 150.
    assert f.serie("ganancia_bruta", "2021-01-01") == [("2018-12-31", 40.0), ("2019-12-31", 55.0)]


def test_solo_entran_datos_anuales():
    p = _payload(
        {
            "NetIncomeLoss": [
                _dur("2019-12-31", 100.0, "2020-02-20"),
                _dur("2019-06-30", 40.0, "2019-08-01", form="10-Q", fp="Q2", start="2019-04-01"),
                _dur("2019-12-31", 30.0, "2020-02-20", start="2019-10-01"),  # el Q4 dentro del 10-K
            ],
            "StockholdersEquity": [
                _inst("2019-12-31", 500.0, "2020-02-20"),
                _inst("2019-06-30", 450.0, "2019-08-01", form="10-Q"),
            ],
        }
    )
    regs = parse_registros(p)
    assert sorted((r.concepto, r.val) for r in regs) == [("ganancia_neta", 100.0), ("patrimonio", 500.0)]


def test_los_dos_cik_se_unen_y_se_deduplican():
    viejo = _payload(
        {"NetIncomeLoss": [_dur("2018-12-31", 1.0, "2019-02-01"), _dur("2019-12-31", 2.0, "2020-02-01")]}
    )
    nuevo = _payload(
        {"NetIncomeLoss": [_dur("2019-12-31", 2.0, "2020-02-01"), _dur("2020-12-31", 3.0, "2021-02-01")]}
    )
    f = unir("XOM", [(2115436, nuevo), (34088, viejo)])
    assert [v for _, v in f.serie("ganancia_neta", "2022-01-01")] == [1.0, 2.0, 3.0]
    assert len([r for r in f.registros if r.end == "2019-12-31"]) == 1
    assert f.ciks == (2115436, 34088)


def test_extranjera_por_ifrs_o_por_20F():
    assert es_extranjera(
        _payload({"Revenue": [_dur("2019-12-31", 1.0, "2020-04-01", form="20-F")]}, tax="ifrs-full")
    )
    assert es_extranjera(_payload({"Revenues": [_dur("2019-12-31", 1.0, "2020-04-01", form="20-F")]}))
    assert not es_extranjera(_payload({"Revenues": [_dur("2019-12-31", 1.0, "2020-02-01")]}))


def test_la_moneda_que_no_es_la_esperada_no_entra():
    """TSM reporta en dólares taiwaneses: mezclarlos con dólares rompería todo cociente."""
    p = {
        "facts": {
            "ifrs-full": {
                "Revenue": {"units": {"TWD": [_dur("2019-12-31", 1e12, "2020-04-01", form="20-F")]}}
            }
        }
    }
    assert parse_registros(p) == []


def test_ida_y_vuelta_por_json():
    f = _fund(_payload({"NetIncomeLoss": [_dur("2019-12-31", 100.0, "2020-02-20")]}))
    g = Fundamentos.de_json(f.a_json())
    assert g.serie("ganancia_neta", "2021-01-01") == f.serie("ganancia_neta", "2021-01-01")
    assert g.registros == f.registros
