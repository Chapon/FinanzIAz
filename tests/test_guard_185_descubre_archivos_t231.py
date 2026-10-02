"""Tarea 231 — el guard de la 185 descubre los ARCHIVOS, no sólo las claves.

La auditoría de desvíos del 2026-09-27 (`docs/auditoria_desvios_2026-09-27.md` [D-1]) encontró
que `tests/test_espejos_direccion_faltante_t185.py` barría por AST las claves del `SCHEMA`,
pero sólo dentro de una **tupla literal de cinco archivos**. Seis perillas de decisión vivían
afuera, y una —`price_second_opinion_enabled`— tiene el encendido pendiente: con ON el motor
deja de comprar nombres con precio en disputa y encola la venta por señal, y ni un espejo, ni
un desvío, ni el guard lo habrían dicho.

Estos tests fijan las tres cosas que la tarea cambió:

1. la población de archivos se **descubre** (mutación en el sentido del falso positivo: una
   lectura nueva fuera de los cinco archivos viejos tiene que aparecer);
2. la segunda opinión tiene espejo y desvío **condicional**, listos antes de que se prenda;
3. el intervalo del scan dejó de ser un literal adentro de un texto.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import analysis.harness_config as hc
from analysis.harness_config import LIVE_MAX_POSITIONS, LIVE_WATCHLIST_SIZE, HarnessConfig, deviations_keyed
from tests.test_espejos_direccion_faltante_t185 import (
    archivos_del_camino_vivo,
    claves_del_camino_vivo,
)

_REPO = Path(__file__).resolve().parent.parent

# Los cinco archivos que la tupla literal enumeraba antes de la tarea.
_LOS_CINCO_VIEJOS = {
    "paper_trading/engine.py",
    "paper_trading/gates.py",
    "paper_trading/strategies.py",
    "analysis/technical.py",
    "analysis/ml_signals.py",
}


def _repo_falso(tmp_path: Path, rel: str, clave: str) -> Path:
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        f'from config.settings_manager import settings\nX = settings.get("{clave}")\n', encoding="utf-8"
    )
    return tmp_path


# ── 1. La población se descubre ─────────────────────────────────────────────


# Literal A PROPÓSITO, y no `_RAICES`: parametrizar sobre la variable que se chequea hace que
# achicar las raíces achique también este test, que seguiría verde (tarea 110/101).
@pytest.mark.parametrize("raiz", ["paper_trading", "data", "analysis"])
def test_una_lectura_NUEVA_en_cualquier_raiz_aparece(tmp_path, raiz):
    """**La mutación del kill-criteria, en el sentido del falso positivo.** Con la tupla literal,
    un `settings.get(...)` en un módulo nuevo quedaba invisible y el guard seguía en verde."""
    repo = _repo_falso(tmp_path, f"{raiz}/sub/modulo_nuevo.py", "price_second_opinion_enabled")
    leidas = claves_del_camino_vivo(repo)
    assert leidas == {"price_second_opinion_enabled": {f"{raiz}/sub/modulo_nuevo.py"}}


def test_lo_que_queda_FUERA_de_las_raices_no_se_barre(tmp_path):
    """La contraprueba: las exclusiones escritas (`ui/`, `scripts/`, `config/`) son de verdad
    exclusiones, así que el test de arriba no pasa por barrer todo el disco."""
    repo = _repo_falso(tmp_path, "ui/panel.py", "price_second_opinion_enabled")
    assert claves_del_camino_vivo(repo) == {}


def test_la_poblacion_real_incluye_los_archivos_que_la_auditoria_encontro_afuera():
    archivos = set(archivos_del_camino_vivo())
    assert {"data/yahoo_finance.py", "paper_trading/universe.py"} <= archivos
    assert archivos >= _LOS_CINCO_VIEJOS, "la población nueva perdió alguno de los cinco de antes"
    assert len(archivos) > 3 * len(_LOS_CINCO_VIEJOS), (
        f"sólo {len(archivos)} archivos: ¿cambiaron las raíces?"
    )


def test_las_perillas_del_hallazgo_las_ve_el_guard():
    """Las seis de la auditoría. Si alguna deja de verse, el hallazgo vuelve a abrirse."""
    leidas = claves_del_camino_vivo()
    for clave in (
        "price_second_opinion_enabled",
        "price_sanity_band_pct",
        "paper_universe_min_adv_dollars",
        "paper_universe_fundamentals_enabled",
        "paper_universe_min_negative_years",
        "paper_universe_revenue_floor_dollars",
    ):
        assert clave in leidas, clave


# ── 2. La segunda opinión: espejo y desvío condicional ──────────────────────


def _cfg() -> HarnessConfig:
    return HarnessConfig(LIVE_MAX_POSITIONS, "x.txt", LIVE_WATCHLIST_SIZE)


def test_con_la_segunda_opinion_APAGADA_no_se_declara_nada():
    assert hc.LIVE_PRICE_SECOND_OPINION_ENABLED is False
    assert "second_opinion" not in {d.clave for d in deviations_keyed(_cfg())}


def test_con_la_segunda_opinion_PRENDIDA_el_desvio_aparece_y_dice_las_dos_conductas(monkeypatch):
    """Lo que el texto tiene que decir es lo que hace el engine (`engine.py`, tarea 201): la
    compra se bloquea y la venta por señal se encola; y que la frecuencia no está medida."""
    monkeypatch.setattr(hc, "LIVE_PRICE_SECOND_OPINION_ENABLED", True)
    texto = {d.clave: d.texto for d in deviations_keyed(_cfg())}["second_opinion"]
    assert "NO compra" in texto
    assert "ENCOLA la venta" in texto
    assert "NO medida" in texto


# ── 3. El intervalo del scan sale del espejo ────────────────────────────────


def test_LIVE_EXIT_EVAL_DESC_se_deriva_del_espejo_y_no_de_un_literal():
    """Por AST y no por substring: un `"scan ~15 min"` literal contiene el mismo texto que el
    derivado, así que buscar el número aprobaría justo el defecto que se está sacando."""
    arbol = ast.parse((_REPO / "analysis" / "harness_config.py").read_text(encoding="utf-8"))
    asignaciones = [
        n.value
        for n in ast.walk(arbol)
        if isinstance(n, ast.Assign)
        and any(getattr(t, "id", None) == "LIVE_EXIT_EVAL_DESC" for t in n.targets)
    ]
    assert len(asignaciones) == 1
    valor = asignaciones[0]
    # Desde la tarea 265 el texto lo arma `desc_eval_vivo(...)` (agrega la frecuencia EFECTIVA,
    # medida y fechada); el f-string con el espejo del intervalo vive adentro de esa función.
    # Lo que este guard cuida no cambió: que no sea un literal y que el intervalo salga del espejo.
    assert isinstance(valor, (ast.JoinedStr, ast.Call)), "LIVE_EXIT_EVAL_DESC volvió a ser un literal"
    if isinstance(valor, ast.Call):
        nombre_fn = getattr(valor.func, "id", None)
        fn = next(n for n in ast.walk(arbol) if isinstance(n, ast.FunctionDef) and n.name == nombre_fn)
        valor = fn
    nombres = {n.id for n in ast.walk(valor) if isinstance(n, ast.Name)}
    assert "LIVE_SCAN_INTERVAL_MINUTES" in nombres
    assert f"~{hc.LIVE_SCAN_INTERVAL_MINUTES} min" in hc.LIVE_EXIT_EVAL_DESC
