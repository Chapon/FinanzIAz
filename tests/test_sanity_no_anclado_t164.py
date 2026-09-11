"""Tarea 164, pata (a) — cada umbral de SANITY dice si un refresh lo mueve.

**El hallazgo que abrió esto.** El re-anclaje de la T68 toca las constantes **ancladas** —un
número publicado con su ventana y su población, que se re-mide cuando la muestra se mueve— y
nadie mira los umbrales de **sanity**, que se comparan contra un literal escrito en el runner.
El refresh del 2026-09-09 movió tres de ellos y dejó **INVÁLIDAS** dos corridas con veredicto
publicado VÁLIDO (T37 y T47), sin que nada lo registrara: la verificación de la 157 declaró
*«los diecisiete sanity de reproducción pasan a OK»*, que es cierto y **angosto**.

**La distinción que hace útil a este inventario, y que no es obvia:**

* un umbral de **criterio** (`KILL_*`) fijo es **correcto**. El veredicto cambia con la
  muestra y eso es honesto — es justamente para lo que un criterio se pre-registra. Mover el
  umbral para que una corrida pase es el defecto; que el número medido cambie, no.
* un umbral de **sanity** comparado contra una **magnitud de alpha** —*«el oráculo le gana al
  control por ≥ X pp»*— es un **ancla no declarada**. Si la muestra nueva tiene menos alpha,
  el instrumento pierde resolución sin que nada esté roto, y la corrida se declara inválida
  por un número que nadie re-midió. **Ésos son los que hay que re-mirar en cada refresh.**

Por eso el guard barre `SANITY_*` y **no** `KILL_*`, y cada entrada declara su **clase**:

``magnitud``
    Se compara contra una diferencia en **pp de CAGR/maxDD**. El refresh la mueve. Va al
    checklist de re-anclaje.
``fraccion``
    Una **proporción** de trades o de población (*«el brazo muerde ≥10%»*). También depende de
    la muestra, pero mide *si el brazo hace algo*, no *cuánta alpha hay*: mucho más estable, y
    cuando falla el diagnóstico es distinto (el brazo no muerde).
``construccion``
    No es un umbral sobre un resultado: es un parámetro del montaje (un percentil, el brazo de
    referencia, la tasa de ruina inyectada). Un refresh no lo toca.
``anclado``
    Ya es un número publicado con ventana y población: lo cubre el re-anclaje de la T68.
``tolerancia``
    El ±ε de un anclado. Se mueve con su ancla, no por su cuenta.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
_RUNNERS = _REPO / "scripts"

MAGNITUD = "magnitud"
FRACCION = "fraccion"
CONSTRUCCION = "construccion"
ANCLADO = "anclado"
TOLERANCIA = "tolerancia"

# ── El inventario, medido el 2026-09-11 ──────────────────────────────────────
# Clave: `archivo:CONSTANTE`. Una constante nueva de sanity no entra al repo sin decidir su
# clase, que es justamente la decisión que no existía.
INVENTARIO: dict[str, str] = {
    # — magnitudes de alpha: LAS QUE EL REFRESH MUEVE ———————————————————————
    "run_anom_profile_t45.py:SANITY_ORACLE_MIN_DCAGR": MAGNITUD,  # oráculo ≥ +20 pp
    "run_anom_regime_t38.py:SANITY_ORACLE_EDGE": MAGNITUD,  # +20 pp
    "run_rank_neutral_t39.py:SANITY_ORACLE_EDGE": MAGNITUD,  # +5 pp
    "run_ranking_t21.py:SANITY_ORACLE_EDGE": MAGNITUD,  # +5 pp
    "run_stop_cal_replay_t26.py:SANITY_ORACLE_EDGE": MAGNITUD,  # +5 pp
    "run_stop_loosen_t34.py:SANITY_ORACLE_VS_RANDOM_CAGR": MAGNITUD,  # +1.50 pp
    "run_stop_loosen_t34.py:SANITY_ORACLE_VS_RANDOM_DD": MAGNITUD,  # −5.00 pp
    "run_stop_price_replay_t26b.py:SANITY_ORACLE_VS_RANDOM_CAGR": MAGNITUD,
    "run_stop_price_replay_t26b.py:SANITY_ORACLE_VS_RANDOM_DD": MAGNITUD,
    "run_stop_value_t37.py:SANITY_ORACLE_VS_RANDOM_CAGR": MAGNITUD,
    "run_stop_value_t37.py:SANITY_ORACLE_VS_RANDOM_DD": MAGNITUD,
    "run_stop_value_t37.py:SANITY_RUIN_MIN_DAMAGE": MAGNITUD,  # la ruina tiene que doler ≥2 pp
    # — fracciones de población ————————————————————————————————————————————
    "run_anom_regime_t38.py:SANITY_MIN_TRADE_DIFF": FRACCION,
    "run_anom_regime_t38.py:SANITY_MIN_CAPITAL_DIFF": FRACCION,
    "run_ent1_replay_t13.py:SANITY_MIN_TIMESTOP_POP": FRACCION,
    "run_ent1_replay_t13.py:SANITY_MAX_CAP_SHARE": FRACCION,
    "run_event_timestop_t51.py:SANITY_MIN_POPULATION": FRACCION,
    "run_event_timestop_t51.py:SANITY_MIN_TRADE_DIFF": FRACCION,
    "run_prio_event_t49.py:SANITY_MIN_TRADE_DIFF": FRACCION,
    "run_rank_neutral_t39.py:SANITY_MIN_TRADE_DIFF": FRACCION,
    "run_ranking_t21.py:SANITY_MIN_TRADE_DIFF": FRACCION,
    "run_stop_cal_replay_t26.py:SANITY_MIN_STOP_SHARE": FRACCION,
    "run_stop_cal_replay_t26.py:SANITY_MIN_TRADE_DIFF": FRACCION,
    "run_stop_loosen_t34.py:SANITY_MIN_TRADE_DIFF": FRACCION,
    "run_stop_price_replay_t26b.py:SANITY_MIN_TRADE_DIFF": FRACCION,
    "run_stop_value_t37.py:SANITY_MIN_TRADE_DIFF": FRACCION,
    "run_trail_arm_t54.py:SANITY_MIN_POPULATION": FRACCION,
    "run_trail_arm_t54.py:SANITY_MIN_TRADE_DIFF": FRACCION,
    # — parámetros del montaje ——————————————————————————————————————————————
    "run_anom_regime_t38.py:SANITY_RANDOM_PCTILE": CONSTRUCCION,
    "run_event_timestop_t51.py:SANITY_ORACLE_PCTILE": CONSTRUCCION,
    "run_prio_event_t49.py:SANITY_ORACLE_PCTILE": CONSTRUCCION,
    "run_stop_value_t37.py:SANITY_RUIN_HIGH_RATE": CONSTRUCCION,  # la tasa que se INYECTA
    "run_tp_cal_replay_t23.py:SANITY_ARM": CONSTRUCCION,
    "run_tp_cal_replay_t23.py:SANITY_TP": CONSTRUCCION,
    # — ya anclados (los cubre el re-anclaje de la T68) ————————————————————
    "run_prio_event_t49.py:SANITY_T33_CAGR": ANCLADO,
    "run_prio_event_t49.py:SANITY_T45_ANALYZE": ANCLADO,
    "run_prio_event_t49.py:SANITY_T45_MERGED_PRIO": ANCLADO,
    "run_rank_neutral_t39.py:SANITY_T33_CAGR": ANCLADO,
    # — tolerancias de un anclado ——————————————————————————————————————————
    "run_prio_event_t49.py:SANITY_TOL": TOLERANCIA,
    "run_rank_neutral_t39.py:SANITY_T33_TOL": TOLERANCIA,
}

# Los que el refresh mueve y por lo tanto van al checklist de re-anclaje.
A_RE_MIRAR_EN_CADA_REFRESH = {k for k, v in INVENTARIO.items() if v == MAGNITUD}


def _constantes_de_sanity() -> dict[str, object]:
    """``{archivo:CONSTANTE: valor}`` de cada constante de módulo con ``SANITY`` en el nombre.

    Por AST sobre los `scripts/run_*.py`. Se excluyen los no-escalares (un dict de mapeo no
    es un umbral) y los `KILL_*`, que son **criterios** y están fuera del alcance por la razón
    escrita en el docstring del módulo.
    """
    out: dict[str, object] = {}
    for p in sorted(_RUNNERS.glob("run_*.py")):
        arbol = ast.parse(p.read_text(encoding="utf-8"))
        for n in arbol.body:
            if not isinstance(n, ast.Assign):
                continue
            for t in n.targets:
                if not isinstance(t, ast.Name) or "SANITY" not in t.id:
                    continue
                if not isinstance(n.value, ast.Constant):
                    continue  # `_ESTADO_DE_SANITY` es un dict de mapeo, no un umbral
                out[f"{p.name}:{t.id}"] = n.value.value
    return out


# ── El invariante ────────────────────────────────────────────────────────────


def test_cada_umbral_de_sanity_declara_si_un_refresh_lo_mueve():
    """**El guard que la 164 deja.** Una constante de sanity nueva obliga a decidir su clase;
    sin eso, el próximo refresh vuelve a invalidar corridas sin que nada lo registre."""
    halladas = set(_constantes_de_sanity())
    sin_clasificar = halladas - set(INVENTARIO)
    assert not sin_clasificar, (
        "estos umbrales de sanity no declaran si un refresh los mueve (tarea 164). Clasificalos "
        "en INVENTARIO: 'magnitud' si se compara contra pp de CAGR/maxDD (va al checklist de "
        f"re-anclaje), 'fraccion', 'construccion', 'anclado' o 'tolerancia':\n  {sorted(sin_clasificar)}"
    )


def test_el_inventario_no_tiene_entradas_FANTASMA():
    """La contraprueba: una entrada que ya no matchea nada es una promesa vencida, y deja al
    test de arriba pasando sobre una población más chica de la que cree."""
    halladas = set(_constantes_de_sanity())
    fantasmas = set(INVENTARIO) - halladas
    assert not fantasmas, f"estas entradas ya no existen en ningún runner: {sorted(fantasmas)}"


def test_el_barrido_encuentra_la_poblacion_ENTERA():
    """Contraprueba del barrido: si un rename o un `ast` que falla lo vaciaran, los dos tests
    de arriba quedarían verdes sobre cero constantes — el modo de falla de la 110 y la 101."""
    halladas = _constantes_de_sanity()
    assert len(halladas) >= 38, f"el barrido encontró sólo {len(halladas)}"
    assert len({k.split(":")[0] for k in halladas}) >= 13, "dejó de ver runners"
    # y tiene que ver las dos que el refresh del 2026-09-09 movió de verdad
    for clave in (
        "run_stop_value_t37.py:SANITY_ORACLE_VS_RANDOM_DD",
        "run_stop_price_replay_t26b.py:SANITY_ORACLE_VS_RANDOM_CAGR",
    ):
        assert clave in halladas, f"{clave} salió del barrido"


@pytest.mark.parametrize("clase", [MAGNITUD, FRACCION, CONSTRUCCION, ANCLADO, TOLERANCIA])
def test_cada_clase_tiene_al_menos_un_miembro(clase):
    """Una clase vacía no es una clasificación: o sobra la clase, o falta clasificar."""
    assert [k for k, v in INVENTARIO.items() if v == clase], f"la clase {clase} quedó vacía"


def test_ninguna_clase_inventada():
    assert set(INVENTARIO.values()) <= {MAGNITUD, FRACCION, CONSTRUCCION, ANCLADO, TOLERANCIA}


# ── Los que van al checklist de re-anclaje ───────────────────────────────────


def test_el_checklist_del_refresh_NOMBRA_a_los_de_clase_magnitud():
    """**La pata que cierra el agujero.** El mensaje de `refresh_cohort.py` es el checklist
    que el operador lee después de refrescar, y decía sólo *«las constantes de reproducción»*.
    Los de clase `magnitud` también se mueven y nadie los re-mira — es lo que dejó al T37 y al
    T47 inválidos el 2026-09-09.
    """
    txt = (_RUNNERS / "refresh_cohort.py").read_text(encoding="utf-8")
    assert "SANITY_ORACLE" in txt, "el checklist no nombra los umbrales de sanity de alpha"
    assert "tarea 164" in txt or "T164" in txt


def test_los_de_magnitud_son_los_que_se_compara_contra_pp():
    """Contraprueba de la clasificación: los 12 de clase `magnitud` tienen que ser valores
    chicos en fracción de CAGR/maxDD (0.015 = 1.5 pp), no porcentajes de población ni
    percentiles. Si alguien clasifica un 95 como `magnitud`, esto lo caza."""
    halladas = _constantes_de_sanity()
    for clave in A_RE_MIRAR_EN_CADA_REFRESH:
        v = halladas[clave]
        assert isinstance(v, float), f"{clave} = {v!r} no es una fracción"
        assert 0.0 < v <= 0.5, f"{clave} = {v}: una magnitud de alpha no puede valer eso"


def test_los_PCTILE_no_son_magnitudes():
    """El error simétrico: un percentil (95) clasificado como magnitud mandaría a re-medir
    algo que el refresh no mueve, y el checklist se llenaría de ruido."""
    for clave, clase in INVENTARIO.items():
        if "PCTILE" in clave:
            assert clase == CONSTRUCCION, f"{clave} está clasificado como {clase}"
