"""Tarea 150 (GS-REVTAG) — el top line de un banco de inversión deja de ser invisible.

**El defecto.** `REVENUE_CONCEPTS` probaba cinco tags us-gaap y **ninguno está** en los
facts de Goldman Sachs, que reporta su línea como ``RevenuesNetOfInterestExpense``
($58.283B, medido 2026-09-11). Con eso GS quedaba en ``revenue_latest = None``.

**Por qué eso no era inocuo, aunque GS estuviera conservado.** ``_fragile_fundamentals``
lee la ausencia de revenue como *debajo del piso* — y eso es **deliberado**: es la
excepción que existe para agarrar a MLTX, un biotech clínico que no reporta ningún tag de
revenue (validado 2026-07-02: NI −227M/−118M). Lo único que salvaba a GS era que su
``NetIncomeLoss`` es fuertemente positivo, porque la regla exige **primero** la evidencia
de pérdidas sostenidas. O sea: **inmune por accidente**. El día que un banco de inversión
reporte dos años seguidos de pérdida GAAP —que no es exótico— salía de los candidatos a
BUY **sin decir nada**.

**La decisión fue de Chapa, entre tres opciones medidas** (ver
`docs/gs_revtag_t150_2026-09-11.md`): eligió la **(a)**, ampliar la lista. Las tres
pasaban el kill-criteria sobre el universo vivo, así que no discriminaba; lo que decidió
fue que la (c) —no leer la ausencia como pre-revenue— cambia **qué puede excluir el
screen** para todos los nombres, para arreglar uno, y debilita el único verdadero-positivo
que el screen tiene demostrado.

**Lo que estos tests fijan, y el más importante no es el obvio:** que el orden de la lista
es parte del contrato. El parser corta en el primer concepto que resuelve, así que los dos
nuevos van **al final** — prependerlos le cambiaría el revenue a los cinco nombres que ya
resolvían con ``Revenues``. Medido sobre los 127 del universo vivo: el número se movió en
**uno solo**, GS (``None`` → 58.283e9).
"""

from __future__ import annotations

from data.edgar_fundamentals import REVENUE_CONCEPTS, parse_fundamental_facts
from paper_trading.universe import UniverseThresholds, screen_candidate

# Los dos que la (a) agregó, con el nombre de quien los necesita.
_NUEVOS = ("RevenuesNetOfInterestExpense", "PremiumsEarnedNet")

# El piso y la ventana de pérdidas vivos, para que el montaje no invente política.
_TH = UniverseThresholds(
    min_adv_dollars=0.0, fundamentals_enabled=True, min_negative_years=2, revenue_floor=10_000_000.0
)


def _anual(end: str, val: float) -> dict:
    """Una fila anual reconocible por `_looks_annual` (frame CY)."""
    return {"end": end, "val": val, "frame": f"CY{end[:4]}"}


def _facts(net_income: list[tuple[str, float]], revenue: dict[str, list[tuple[str, float]]]):
    """Payload `companyfacts` mínimo: NI + los conceptos de revenue que se le pasen."""
    gaap: dict = {"NetIncomeLoss": {"units": {"USD": [_anual(e, v) for e, v in net_income]}}}
    for concepto, filas in revenue.items():
        gaap[concepto] = {"units": {"USD": [_anual(e, v) for e, v in filas]}}
    return {"entityName": "TEST", "facts": {"us-gaap": gaap}}


# ── La lista: contenido y ORDEN ───────────────────────────────────────────────


def test_los_dos_conceptos_nuevos_estan_en_la_lista():
    for c in _NUEVOS:
        assert c in REVENUE_CONCEPTS, f"{c} salió de REVENUE_CONCEPTS: se deshizo la (a) de la 150"


def test_los_nuevos_van_AL_FINAL_y_eso_es_el_contrato():
    """**El test que importa más, y no es el obvio.** `parse_fundamental_facts` corta en el
    primer concepto que resuelve. Si alguien mueve `RevenuesNetOfInterestExpense` adelante
    de `Revenues`, los cinco nombres que hoy resuelven con `Revenues` —C, BAC, JPM, WFC,
    SCHW— empiezan a devolver **otro número**, en silencio y sin que ningún veredicto
    cambie (los dos están muy arriba del piso). Apendear sólo puede AGREGAR resolución."""
    for c in _NUEVOS:
        assert REVENUE_CONCEPTS.index(c) > REVENUE_CONCEPTS.index("Revenues"), (
            f"{c} quedó ANTES de `Revenues`: le cambia el revenue a quien ya resolvía"
        )


def test_la_lista_no_tiene_duplicados():
    """Un duplicado no rompe nada —el parser corta antes— pero vuelve mentiroso al test de
    orden de arriba, que usa `.index()` (devuelve la PRIMERA aparición)."""
    assert len(REVENUE_CONCEPTS) == len(set(REVENUE_CONCEPTS))


def test_un_concepto_nuevo_adelante_SI_cambiaria_el_numero():
    """Contraprueba del test de orden: demuestra que el peligro que declara es real, en vez
    de afirmarlo. Con los dos conceptos presentes, quien resuelve es el que está antes."""
    payload = _facts(
        net_income=[("2025-12-31", 1e9)],
        revenue={
            "Revenues": [("2025-12-31", 100e9)],
            "RevenuesNetOfInterestExpense": [("2025-12-31", 58e9)],
        },
    )
    assert parse_fundamental_facts(payload, ticker="BANCO").revenue_latest == 100e9

    import data.edgar_fundamentals as ef

    original = ef.REVENUE_CONCEPTS
    try:
        ef.REVENUE_CONCEPTS = ("RevenuesNetOfInterestExpense", *original)
        invertido = ef.parse_fundamental_facts(payload, ticker="BANCO").revenue_latest
    finally:
        ef.REVENUE_CONCEPTS = original
    assert invertido == 58e9, "prepender tiene que cambiar el número, o el test de orden no protege nada"


# ── El caso GS, y la regresión que la tarea arregla ──────────────────────────


def test_el_top_line_de_un_banco_de_inversion_RESUELVE():
    """La forma exacta de los facts de GS: sólo `RevenuesNetOfInterestExpense`, ninguno de
    los cinco originales. Medido en vivo el 2026-09-11: $58.283B."""
    payload = _facts(
        net_income=[("2025-12-31", 17.176e9)],
        revenue={"RevenuesNetOfInterestExpense": [("2025-12-31", 58.283e9)]},
    )
    assert parse_fundamental_facts(payload, ticker="GS").revenue_latest == 58.283e9


def test_un_banco_con_PERDIDAS_SOSTENIDAS_y_top_line_NO_se_excluye():
    """**La regresión que la 150 arregla, montada en su escenario.** Con la lista vieja este
    banco quedaba EXCLUIDO: dos años de pérdida + `revenue_latest = None` leído como debajo
    del piso. Con la lista ampliada su top line resuelve muy arriba del piso y la pata de
    fragilidad no muerde. Es el modo de falla latente del enunciado, hecho caso."""
    facts = parse_fundamental_facts(
        _facts(
            net_income=[("2026-12-31", -3.0e9), ("2025-12-31", -1.5e9)],
            revenue={"RevenuesNetOfInterestExpense": [("2026-12-31", 40e9)]},
        ),
        ticker="GS",
    )
    assert facts.revenue_latest == 40e9
    veredicto = screen_candidate("GS", adv_dollars=None, facts=facts, thresholds=_TH)
    assert veredicto.included, f"excluido con top line resuelto: {veredicto.detail}"


def test_con_la_lista_VIEJA_ese_mismo_banco_SI_se_excluia():
    """Contraprueba del de arriba: sin esto, el test anterior pasaría igual si la pata de
    fragilidad estuviera apagada, y no probaría que la lista es lo que lo salva."""
    import data.edgar_fundamentals as ef

    original = ef.REVENUE_CONCEPTS
    try:
        ef.REVENUE_CONCEPTS = tuple(c for c in original if c not in _NUEVOS)
        facts = ef.parse_fundamental_facts(
            _facts(
                net_income=[("2026-12-31", -3.0e9), ("2025-12-31", -1.5e9)],
                revenue={"RevenuesNetOfInterestExpense": [("2026-12-31", 40e9)]},
            ),
            ticker="GS",
        )
    finally:
        ef.REVENUE_CONCEPTS = original
    assert facts.revenue_latest is None
    veredicto = screen_candidate("GS", adv_dollars=None, facts=facts, thresholds=_TH)
    assert veredicto.excluded, "con la lista vieja tenía que excluirse: si no, el enunciado era falso"
    assert "sin revenue reportado" in veredicto.detail


# ── El control que ninguna opción podía perder ───────────────────────────────


def test_MLTX_sigue_excluido_con_la_lista_AMPLIADA():
    """El kill-criteria de la tarea. La forma de MLTX: pérdidas sostenidas y **ningún** tag
    de revenue (medido: cero conceptos us-gaap con `Revenue` en el nombre). Ampliar la lista
    no puede salvarlo, porque lo que lo excluye es que no reporta nada — y eso es lo que la
    opción (a) conserva y la (c) hubiera puesto en juego."""
    facts = parse_fundamental_facts(
        _facts(net_income=[("2026-12-31", -227.3e6), ("2025-12-31", -118.9e6)], revenue={}),
        ticker="MLTX",
    )
    assert facts.revenue_latest is None
    veredicto = screen_candidate("MLTX", adv_dollars=None, facts=facts, thresholds=_TH)
    assert veredicto.excluded
    assert "sin revenue reportado" in veredicto.detail


def test_una_aseguradora_resuelve_con_PremiumsEarnedNet():
    """El segundo concepto de la (a), que entró por diseño y no por un caso vivo: hoy ningún
    nombre del universo lo necesita (C lo reporta pero resuelve antes con `Revenues`). Queda
    con test para que su presencia en la lista no sea un adorno sin ejercitar."""
    facts = parse_fundamental_facts(
        _facts(net_income=[("2025-12-31", 5e9)], revenue={"PremiumsEarnedNet": [("2025-12-31", 30e9)]}),
        ticker="ASEG",
    )
    assert facts.revenue_latest == 30e9
