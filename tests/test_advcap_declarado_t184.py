"""Tarea 184 (ADVCAP-SIN-DECLARAR) — el cap de liquidez por ADV está prendido en vivo y se declara.

**Qué pasaba.** `paper_adv_cap_pct` vale **0.05** en la cuenta viva desde el 2026-06-09 (T7.1,
por el caso MLTX) y **0.0** en el schema. `engine.py` trima cada BUY a ese porcentaje del ADV$
reciente. Ningún runner lo modela, no tenía espejo `LIVE_*` y ninguna clave de
`deviations_keyed()` lo nombraba: la 185 lo dejó visible como `FALTA_ESPEJO`.

**De las dos salidas que el kill-criteria ofrecía se eligió declararlo**, y el motivo es de
precedente, no de gusto: el screen E1b (131) y el escalado por régimen (95) se declaran **aunque
hoy no muerdan**, con el número medido al lado. Escribir *«no hace falta modelarlo»* en un test
habría dejado al banner callado justo en el caso para el que el cap se prendió — un ilíquido que
entra a la watchlist.

**Lo que este archivo fija:**

1. El desvío aparece con el cap prendido en vivo y **desaparece** con el cap apagado.
2. Los números del texto **salen de las constantes**, comparados como valor parseado y no como
   substring: un `"5%" in texto` lo satisface también una línea que diga *«no es 5%»*
   ([[cross-check-por-substring-acepta-lo-contrario]]).
3. El capital contra el que se mide el margen es el default **real** del simulador y de los
   runners, no un literal que coincide por casualidad.
4. **La medición contra los frames**, en la dirección que importa: la declaración nunca promete
   **más** margen que el medido. Si un refresh sube el mínimo, la declaración queda conservadora
   y esto sigue verde; si entra un ilíquido y lo baja, se pone rojo.

**El instrumento se valida antes que el número** ([[validar-el-instrumento-antes-del-numero]]):
la medición resuelve la ruta con la misma función que **escribe** los parquet. Re-derivar el
ticker del nombre del archivo es el defecto de la tarea 190 —`BRK-B` se guarda como `BRK_B`—, y
el test del instrumento usa justamente un ticker con guión.
"""

from __future__ import annotations

import ast
import inspect
import re
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import analysis.harness_config as hc
from analysis.harness_config import (
    LIVE_MAX_POSITIONS,
    LIVE_WATCHLIST_SIZE,
    HarnessConfig,
    deviations,
    deviations_keyed,
)
from analysis.portfolio_sim import simulate_portfolio
from config.settings_manager import DEFAULTS
from data import parquet_cache

_REPO = Path(__file__).resolve().parent.parent


def _cfg(**kw) -> HarnessConfig:
    return HarnessConfig(LIVE_MAX_POSITIONS, "x.txt", LIVE_WATCHLIST_SIZE, **kw)


def _textos_adv(cfg: HarnessConfig) -> list[str]:
    return [d.texto for d in deviations_keyed(cfg) if d.clave == "adv_cap"]


# ── 1. Se declara cuando está prendido, y sólo entonces ─────────────────────


def test_la_config_viva_declara_el_cap_UNA_vez():
    assert len(_textos_adv(_cfg())) == 1


def test_el_banner_lo_muestra():
    """La clave no alcanza: lo que lee el autor de un pre-registro es el banner."""
    assert hc.adv_cap_desc() in hc.config_banner(_cfg())
    assert hc.adv_cap_desc() in deviations(_cfg())


def test_con_el_cap_APAGADO_en_vivo_no_se_declara(monkeypatch):
    """La contraprueba: un desvío que se emite siempre, pase lo que pase en vivo, no declara
    nada — sería ruido con forma de declaración."""
    monkeypatch.setattr(hc, "LIVE_ADV_CAP_PCT", 0.0)
    assert _textos_adv(_cfg()) == []


# ── 2. Los números del texto salen de las constantes ────────────────────────


@pytest.mark.parametrize("pct", [0.05, 0.10, 0.01])
def test_el_porcentaje_del_texto_es_el_del_ESPEJO(monkeypatch, pct):
    monkeypatch.setattr(hc, "LIVE_ADV_CAP_PCT", pct)
    m = re.search(r"Gate 3b, (\d+)% del ADV\$", _textos_adv(_cfg())[0])
    assert m, "el texto dejó de declarar el porcentaje"
    assert int(m.group(1)) == round(100 * pct)


def _umbral_y_multiplo(texto: str) -> tuple[float, int]:
    umbral = re.search(r"entrada de más de \$([\d.]+)M", texto)
    multiplo = re.search(r"(\d+)× el capital inicial default", texto)
    assert umbral and multiplo, "el texto dejó de declarar el umbral o el múltiplo"
    return float(umbral.group(1)) * 1e6, int(multiplo.group(1))


@pytest.mark.parametrize("factor", [1.0, 0.1, 3.0])
def test_umbral_y_multiplo_se_DERIVAN_y_no_se_escriben(monkeypatch, factor):
    """Mutar el mínimo medido tiene que mover los dos números del texto. Escritos a mano, un
    re-anclaje actualiza uno y deja el otro."""
    monkeypatch.setattr(hc, "ADV_CAP_MIN_ADV_DOLLARS", hc.ADV_CAP_MIN_ADV_DOLLARS * factor)
    umbral, multiplo = _umbral_y_multiplo(hc.adv_cap_desc())
    esperado = hc.LIVE_ADV_CAP_PCT * hc.ADV_CAP_MIN_ADV_DOLLARS
    assert umbral == pytest.approx(esperado, abs=5_000)  # el texto redondea a $0,01M
    assert multiplo == round(esperado / hc.ADV_CAP_DEFAULT_CAPITAL)


# ── 3. El capital es el de verdad ────────────────────────────────────────────


def test_el_capital_declarado_es_el_default_del_SIMULADOR():
    default = inspect.signature(simulate_portfolio).parameters["initial_capital"].default
    assert default == hc.ADV_CAP_DEFAULT_CAPITAL


def _defaults_de_capital_en_runners() -> dict[str, float]:
    """``--capital`` de cada runner, por AST. La población se descubre, no se enumera."""
    encontrados: dict[str, float] = {}
    for path in sorted((_REPO / "scripts").glob("*.py")):
        arbol = ast.parse(path.read_text(encoding="utf-8"))
        for nodo in ast.walk(arbol):
            if not (
                isinstance(nodo, ast.Call)
                and isinstance(nodo.func, ast.Attribute)
                and nodo.func.attr == "add_argument"
                and nodo.args
                and isinstance(nodo.args[0], ast.Constant)
                and nodo.args[0].value == "--capital"
            ):
                continue
            for kw in nodo.keywords:
                if kw.arg == "default":
                    encontrados[path.name] = ast.literal_eval(kw.value)
    return encontrados


def test_ningun_runner_corre_con_OTRO_capital_default():
    """El margen del texto se mide contra el capital default: un runner que lo cambie mide
    contra otro número y la declaración dejaría de ser cierta para él."""
    capitales = _defaults_de_capital_en_runners()
    assert len(capitales) >= 5, f"el barrido encontró demasiado pocos runners: {capitales}"
    distintos = {n: c for n, c in capitales.items() if c != hc.ADV_CAP_DEFAULT_CAPITAL}
    assert not distintos, f"runners con otro --capital default: {distintos}"


# ── 4. La medición contra los frames ────────────────────────────────────────


def _min_adv(
    tickers: list[str], directorio: Path, lookback: int
) -> tuple[tuple[float, str] | None, list[str]]:
    """El ADV$ de ``lookback`` ruedas más bajo de toda la ventana, y los tickers **sin frame**.

    Es ``recent_adv_dollars`` (media de Close×Volume) evaluado en **cada** rueda. La ruta sale
    de ``parquet_cache.path_for`` —la misma función que escribe— con el directorio pisado:
    re-derivarla del nombre del archivo pierde a ``BRK-B`` (tarea 190).

    Los faltantes se **devuelven** en vez de cortar: con un ``return None`` al primer faltante,
    el test de abajo se salteaba entero por un solo frame —la mutación de la ruta mal derivada
    lo mostró: *skipped*, no *failed*—, que es el defecto de la tarea 174.
    """
    minimo: tuple[float, str] | None = None
    faltan: list[str] = []
    for t in tickers:
        path = directorio / parquet_cache.path_for(t, hc.ARTIFACT_PERIOD, "1d").name
        if not path.exists():
            faltan.append(t)
            continue
        df = pd.read_parquet(path, columns=["Close", "Volume"])
        adv = (df["Close"].astype(float) * df["Volume"].astype(float)).rolling(lookback).mean()
        adv = adv[np.isfinite(adv) & (adv > 0)]
        if not adv.empty and (minimo is None or float(adv.min()) < minimo[0]):
            minimo = (float(adv.min()), t)
    return minimo, faltan


def test_el_INSTRUMENTO_ve_un_iliquido_con_guion(tmp_path):
    """Antes de creerle al número: un frame fino con un ticker con guión tiene que salir como
    mínimo. Con la ruta re-derivada del nombre del archivo, este frame no se encontraba."""
    idx = pd.bdate_range("2020-01-01", periods=60)
    grueso = pd.DataFrame({"Close": 100.0, "Volume": 1_000_000.0}, index=idx)
    fino = pd.DataFrame({"Close": 10.0, "Volume": 1_000.0}, index=idx)
    grueso.to_parquet(tmp_path / parquet_cache.path_for("AAA", hc.ARTIFACT_PERIOD, "1d").name)
    fino.to_parquet(tmp_path / parquet_cache.path_for("ZZ-B", hc.ARTIFACT_PERIOD, "1d").name)

    assert _min_adv(["AAA", "ZZ-B"], tmp_path, 20) == ((10_000.0, "ZZ-B"), [])
    assert _min_adv(["AAA", "FALTA"], tmp_path, 20) == ((100_000_000.0, "AAA"), ["FALTA"])


def test_la_declaracion_no_promete_MAS_margen_que_el_medido():
    """**El número de verdad, en la dirección que importa.** El mínimo declarado tiene que ser
    menor o igual al medido hoy: si un refresh lo sube, la declaración queda conservadora; si
    entra un ilíquido y lo baja, esto se pone rojo y hay que re-medir.

    Y el cap tiene que seguir siendo **inerte** contra el capital default con margen: una
    entrada nunca supera la equity, e incluso a 20% anual la cartera llega a ~6,2× el capital
    en los 10 años de la ventana, así que exigir 10× cubre a una cartera mejor que cualquiera."""
    tickers = hc.parse_universe_file(_REPO / hc.LIVE_UNIVERSE_FILE)
    medido, faltan = _min_adv(tickers, parquet_cache.get_parquet_dir(), DEFAULTS["paper_adv_lookback_days"])
    if len(faltan) == len(tickers):
        pytest.skip("sin ningún frame 10y del universo de referencia en este entorno")
    # Uno solo faltante NO saltea: sería medir el mínimo sobre otra población y llamarlo verde.
    assert not faltan, f"tickers del universo sin frame {hc.ARTIFACT_PERIOD}: {faltan}"
    assert medido is not None
    minimo, ticker = medido

    assert minimo + 1.0 >= hc.ADV_CAP_MIN_ADV_DOLLARS, (
        f"el mínimo medido bajó a ${minimo:,.0f} ({ticker}) y el texto declara "
        f"${hc.ADV_CAP_MIN_ADV_DOLLARS:,.0f}: re-medir y re-anclar las constantes ADV_CAP_*"
    )
    assert hc.LIVE_ADV_CAP_PCT * minimo > 10 * hc.ADV_CAP_DEFAULT_CAPITAL, (
        f"el cap dejó de ser inerte: muerde entradas de más de ${hc.LIVE_ADV_CAP_PCT * minimo:,.0f} "
        f"({ticker}) — ya no alcanza con declararlo, hay que modelarlo"
    )
