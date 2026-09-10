"""Tarea 158 (PITUNIV-DEFAULT) — el productor del store PIT defaulteaba al cohorte legacy.

``scripts/precompute_pit_signals.py`` es **el** script que hay que correr después de
refrescar el cohorte, y su ``DEFAULT_UNIVERSE`` decía ``data/harness_universe_41_10y.txt``:
41 tickers, de los cuales **39** están en el universo vivo de 127. Correrlo sin
``--universe`` —la forma natural— dejaba **88 tickers vivos sin señales nuevas**, y
después el guard de cobertura de la tarea 86 frenaba las corridas sin decir por qué.
Es la forma exacta de la **70** y la **99**: un default apuntando a una población que
dejó de ser la viva, que **no falla — produce un resultado plausible sobre la muestra
equivocada**.

**Por qué estuvo meses invisible, y qué se arregló además del default.** Nueve runners
más repetían ese mismo literal, y en ellos es **legítimo**: son los harness congelados
(T7→T13, T23, R2, walkforward) que corren con ``LEGACY_MAX_POSITIONS`` y
``LEGACY_FILL_MODE`` sobre la población de su veredicto publicado. Leyendo el código, el
default podrido y los nueve legítimos se veían **idénticos**. Ahora las tres poblaciones
se nombran en ``harness_config`` y cada script referencia el **símbolo**, así que la
intención es legible y este guard puede ser un predicado en vez de una lista.

**Lo que este guard NO puede ver, y va declarado.** Su población son las constantes de
módulo cuyo nombre dice ``UNIVERSE`` y cuyo valor es una **ruta**. Un universo escrito
como lista inline queda afuera: ``scripts/tp_mult_sweep_2026-07-22.py`` tiene los 41
tickers a mano. Se verificó el 2026-09-10 que ese conjunto es **exactamente** el del
archivo legacy (41/41), o sea que hoy no hay desvío escondido ahí — pero es una
verificación de una vez, no un invariante que este archivo sostenga.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from analysis.harness_config import (
    LEGACY_UNIVERSE_FILE,
    LIVE_UNIVERSE_FILE,
    POPULATION_LEGACY_41,
    POPULATION_LIVE_ACCT2,
    SP500_UNIVERSE_FILE,
    universe_fingerprint,
)
from scripts.precompute_pit_signals import build_parser, parse_universe_file

_REPO = Path(__file__).resolve().parent.parent
_PAQUETES = ("scripts", "paper_trading", "analysis", "ui", "data", "config", "alerts", "database")

# Las tres poblaciones declaradas, por símbolo. Un símbolo nuevo acá es una decisión
# explícita —"esta es otra población"—, que es justo lo que el literal repetido escondía.
_DECLARADAS = {
    "LIVE_UNIVERSE_FILE": LIVE_UNIVERSE_FILE,
    "LEGACY_UNIVERSE_FILE": LEGACY_UNIVERSE_FILE,
    "SP500_UNIVERSE_FILE": SP500_UNIVERSE_FILE,
}

# De qué población habla cada script, ``archivo:constante`` → símbolo. **No se deriva del
# código**: es la decisión que el literal repetido volvía invisible, y por eso se declara.
_POBLACION_POR_SCRIPT: dict[str, str] = {
    # El productor del store PIT — el arreglo de la 158. Es el único que habla del VIVO,
    # porque es el único cuyo trabajo es dejar el store al día para lo que se corra hoy.
    "scripts/precompute_pit_signals.py:DEFAULT_UNIVERSE": "LIVE_UNIVERSE_FILE",
    # Los harness CONGELADOS: corren con ``LEGACY_FILL_MODE``/``LEGACY_MAX_POSITIONS``
    # sobre la población de su veredicto publicado. Moverles el universo no es
    # "actualizar un default": es invalidar el veredicto sin re-correrlo.
    "scripts/run_scaleout_replay_t7.py:DEFAULT_UNIVERSE": "LEGACY_UNIVERSE_FILE",
    "scripts/run_meta_label_t9.py:DEFAULT_UNIVERSE": "LEGACY_UNIVERSE_FILE",
    "scripts/run_sizing_exposure_t10_t20.py:DEFAULT_UNIVERSE": "LEGACY_UNIVERSE_FILE",
    "scripts/run_anomaly_replay_t11b.py:DEFAULT_UNIVERSE": "LEGACY_UNIVERSE_FILE",
    "scripts/run_ent1_replay_t13.py:DEFAULT_UNIVERSE": "LEGACY_UNIVERSE_FILE",
    "scripts/run_tp_cal_replay_t23.py:DEFAULT_UNIVERSE": "LEGACY_UNIVERSE_FILE",
    "scripts/run_market_regime_r2.py:DEFAULT_UNIVERSE": "LEGACY_UNIVERSE_FILE",
    "scripts/run_walkforward_power.py:DEFAULT_UNIVERSE": "LEGACY_UNIVERSE_FILE",
    # El T45 corre sobre el vivo, pero además **reproduce** el veredicto del T11b sobre
    # el cohorte legacy (§5.3(b)): esa constante es del lado de la reproducción.
    "scripts/run_anom_profile_t45.py:REPRO_LEGACY_UNIVERSE": "LEGACY_UNIVERSE_FILE",
    # El T12 necesitaba la sección cruzada ancha del S&P 500 para los clusters de
    # insiders — otra población, también congelada por su veredicto.
    "scripts/run_insider_cluster_replay_t12.py:DEFAULT_UNIVERSE": "SP500_UNIVERSE_FILE",
}


def _parece_ruta_de_universo(valor: object) -> bool:
    return isinstance(valor, str) and valor.endswith(".txt")


def _constantes_de_universo() -> list[tuple[str, str, ast.expr]]:
    """``(archivo, nombre, nodo)`` de cada constante de módulo con ``UNIVERSE`` en el nombre.

    Por **AST** y sobre los ocho paquetes, no por grep sobre una lista de archivos: un
    runner nuevo nace adentro del barrido (la lección de las tareas 128 y 147).
    """
    out: list[tuple[str, str, ast.expr]] = []
    for paquete in _PAQUETES:
        for p in sorted((_REPO / paquete).rglob("*.py")):
            try:
                arbol = ast.parse(p.read_text(encoding="utf-8"))
            except SyntaxError:  # pragma: no cover
                continue
            for n in arbol.body:
                if not isinstance(n, ast.Assign):
                    continue
                for t in n.targets:
                    if isinstance(t, ast.Name) and "UNIVERSE" in t.id:
                        out.append((p.relative_to(_REPO).as_posix(), t.id, n.value))
    return out


def _resuelto(nodo: ast.expr) -> str | None:
    """La ruta que la constante nombra, o ``None`` si no es una ruta de universo."""
    if isinstance(nodo, ast.Constant) and _parece_ruta_de_universo(nodo.value):
        return nodo.value
    if isinstance(nodo, ast.Name):
        return _DECLARADAS.get(nodo.id)
    return None


# ── El arreglo ───────────────────────────────────────────────────────────────


def test_el_default_del_productor_es_la_poblacion_VIVA():
    """El corazón de la tarea, y medido **contra el ancla**, no contra un string.

    Comparar ``DEFAULT_UNIVERSE == LIVE_UNIVERSE_FILE`` sería preguntarle al archivo por
    sí mismo. La referencia es ``POPULATION_LIVE_ACCT2`` —cuya huella re-verifica
    ``test_las_anclas_declaran_la_huella_de_su_universo_real`` contra el archivo del
    repo, y cuyo tamaño re-verifica la 89 contra la watchlist de la DB—, así que esto
    afirma sobre el **conjunto de tickers**, que es lo que el script va a recomputar.
    """
    default = build_parser().parse_args([]).universe
    assert universe_fingerprint(default) == POPULATION_LIVE_ACCT2.tickers_fp
    assert len(parse_universe_file(_REPO / default)) == POPULATION_LIVE_ACCT2.n_tickers


def test_el_default_del_productor_NO_es_el_cohorte_legacy():
    """La contraprueba del de arriba: el defecto concreto que había, nombrado.

    Las dos poblaciones se solapan en 39 de 41, así que un chequeo por **cantidad**
    (``> 100``) también lo hubiera visto — pero uno por conjunto ve además el caso que
    viene después: un universo del tamaño correcto con los tickers cambiados.
    """
    default = build_parser().parse_args([]).universe
    assert universe_fingerprint(default) != POPULATION_LEGACY_41.tickers_fp
    vivos = set(parse_universe_file(_REPO / default))
    legacy = set(parse_universe_file(_REPO / LEGACY_UNIVERSE_FILE))
    # 87 desde el 2026-09-10: AVB salió del universo vivo (tarea 156) y era uno de los
    # que estaban sólo en el vivo. Eran 88 con 127 tickers; la intersección no se movió
    # (39 de 41: `AAPL` y `LIN` siguen siendo los únicos legacy-only).
    assert len(vivos - legacy) == 87, "cambió el solapamiento: re-medir el enunciado de la 158"
    assert len(legacy - vivos) == 2, "AAPL y LIN eran los únicos legacy-only"


def test_mut_si_el_default_vuelve_al_legacy_el_guard_ACUSA(monkeypatch):
    """Prueba por mutación: el default vive en un global que el parser lee al armarse,
    así que apuntarlo al legacy reproduce exactamente el defecto de la 158."""
    import scripts.precompute_pit_signals as mod

    monkeypatch.setattr(mod, "DEFAULT_UNIVERSE", LEGACY_UNIVERSE_FILE)
    default = mod.build_parser().parse_args([]).universe
    assert universe_fingerprint(default) == POPULATION_LEGACY_41.tickers_fp
    assert universe_fingerprint(default) != POPULATION_LIVE_ACCT2.tickers_fp


def test_un_universo_explicito_sigue_mandando():
    """El default cambia; el flag no. Es lo que deja correr el cohorte congelado."""
    args = build_parser().parse_args(["--universe", LEGACY_UNIVERSE_FILE])
    assert args.universe == LEGACY_UNIVERSE_FILE


# ── El predicado ─────────────────────────────────────────────────────────────


def test_ninguna_constante_de_modulo_clava_una_ruta_de_universo():
    """Un literal repetido vuelve **indistinguible** el default podrido del congelado.

    Las rutas se declaran en ``analysis/harness_config.py`` y el resto las referencia por
    símbolo. Este es el predicado que la 158 deja instalado: no *"¿este archivo dice el
    universo viejo?"* sino *"¿hay alguna constante de universo que no salga de las tres
    declaradas?"*.
    """
    culpables = [
        f"{arch}: {nombre} = {nodo.value!r}"
        for arch, nombre, nodo in _constantes_de_universo()
        if isinstance(nodo, ast.Constant)
        and _parece_ruta_de_universo(nodo.value)
        and arch != "analysis/harness_config.py"
    ]
    assert not culpables, (
        "estas constantes clavan una ruta de universo. Importá el símbolo de "
        "analysis.harness_config (LIVE_/LEGACY_/SP500_UNIVERSE_FILE) — tarea 158:\n  "
        + "\n  ".join(culpables)
    )


def test_el_barrido_encuentra_la_familia_entera():
    """Contraprueba: que el de arriba no pase porque el barrido **no miró nada**.

    Si un rename o un ``ast`` que falla vaciaran la población, el test del predicado
    quedaría verde sobre cero constantes — el modo de falla de la 110 y la 101.
    """
    encontradas = {arch for arch, _, _ in _constantes_de_universo()}
    for esperado in (
        "scripts/precompute_pit_signals.py",
        "scripts/run_scaleout_replay_t7.py",
        "scripts/run_walkforward_power.py",
        "scripts/run_insider_cluster_replay_t12.py",
        "analysis/harness_config.py",
    ):
        assert esperado in encontradas, f"{esperado} salió del barrido"
    assert len(_constantes_de_universo()) >= 12


@pytest.mark.parametrize("nombre,ruta", sorted(_DECLARADAS.items()))
def test_cada_poblacion_declarada_existe_y_es_parseable(nombre, ruta):
    """Una declaración que apunta a un archivo que no está es una lista disfrazada."""
    path = _REPO / ruta
    assert path.exists(), f"{nombre} apunta a {ruta}, que no existe"
    tickers = parse_universe_file(path)
    assert len(tickers) == len(set(tickers)) > 20


def test_cada_script_declara_de_que_poblacion_habla():
    """**Medido, no supuesto**: la migración a símbolos no movió a nadie de muestra.

    Y no alcanza con resolver el símbolo y compararlo contra el ancla de *ese* archivo:
    eso pasaría igual de verde con un runner congelado apuntando al vivo, porque estaría
    preguntándole al archivo por sí mismo ([[guard-no-puede-usar-de-verdad-lo-que-chequea]]).
    Qué población le toca a cada script es una **decisión**, así que va declarada — y la
    tabla se exige **completa en las dos direcciones** contra lo que el barrido
    encuentra: un runner nuevo obliga a decidir, y una fila huérfana acusa.
    """
    hallados = {
        f"{arch}:{nombre}": nodo
        for arch, nombre, nodo in _constantes_de_universo()
        if arch != "analysis/harness_config.py" and _resuelto(nodo) is not None
    }
    assert set(hallados) == set(_POBLACION_POR_SCRIPT), (
        "la clasificación quedó desalineada con el barrido.\n"
        f"  sin declarar: {sorted(set(hallados) - set(_POBLACION_POR_SCRIPT))}\n"
        f"  huérfanas:    {sorted(set(_POBLACION_POR_SCRIPT) - set(hallados))}"
    )
    for clave, nodo in hallados.items():
        esperado = _POBLACION_POR_SCRIPT[clave]
        assert isinstance(nodo, ast.Name) and nodo.id == esperado, (
            f"{clave} declara {getattr(nodo, 'id', ast.dump(nodo))} y debería ser {esperado}"
        )


def test_las_dos_poblaciones_ancladas_son_distinguibles():
    """Contraprueba del de arriba: las huellas que separan vivo de legacy existen y
    difieren. Sin esto, la tabla podría estar clasificando dos nombres del mismo
    conjunto y nadie se enteraría."""
    assert universe_fingerprint(LIVE_UNIVERSE_FILE) == POPULATION_LIVE_ACCT2.tickers_fp
    assert universe_fingerprint(LEGACY_UNIVERSE_FILE) == POPULATION_LEGACY_41.tickers_fp
    assert POPULATION_LIVE_ACCT2.tickers_fp != POPULATION_LEGACY_41.tickers_fp


def test_el_productor_hermano_ya_defaulteaba_al_vivo():
    """``precompute_pit_risk_score.py`` es el otro productor del store y **ya** estaba
    bien: la 158 era del hermano, y esto lo fija para que no se copie el defecto al
    revés (la 69 ya vivió una copia de patrón entre estos dos)."""
    import scripts.precompute_pit_risk_score as risk

    src = ast.parse((_REPO / "scripts" / "precompute_pit_risk_score.py").read_text(encoding="utf-8"))
    assert risk.LIVE_UNIVERSE_FILE == LIVE_UNIVERSE_FILE
    defaults = [
        n
        for n in ast.walk(src)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr == "add_argument"
        and any(isinstance(a, ast.Constant) and a.value == "--universe" for a in n.args)
    ]
    assert defaults, "dejó de tener --universe"
    for call in defaults:
        kw = {k.arg: k.value for k in call.keywords}
        assert isinstance(kw.get("default"), ast.Name) and kw["default"].id == "LIVE_UNIVERSE_FILE"
