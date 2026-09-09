"""ACCT1-DEFAULTS (tarea 99) — qué cuenta mira un runner cuando nadie se lo dice.

Siete runners tenían ``--account`` con ``default=1``, y la cuenta 1 está **pausada**
desde el 2026-07-01. La forma peligrosa es que **no fallan**: esa cuenta tiene 91
fills reales congelados, así que devolvían un replay completo y plausible de una
cuenta muerta — sin un error, sin un aviso, sin un cero sospechoso.

Es el defecto que la tarea **70** cerró para los jobs de fondo, un directorio más
allá. La lección que se fija acá no es el arreglo puntual sino la de la
**población**: la 70 arregló *"los jobs de fondo"* y estos siete quedaron afuera
porque el conjunto se definió por **dónde se encontró el defecto** y no por la
propiedad que lo hace un defecto — *elegir cuenta con un literal*. El mismo patrón
dejó cuatro ``measure_*`` fuera del guard de cohorte de la 76 (tarea 101).

Por eso el test que más vale es ``test_ningun_runner_hardcodea_una_cuenta``: barre
``scripts/`` con **AST** y no con grep, y falla cuando aparece el próximo.

**Tarea 128 — y la lección volvió a fallar un nivel más abajo.** Ese barrido leía
el default con ``getattr(kw.value, "value", "<no-literal>")``: cuando el default es
un nombre —una constante de módulo— y no un literal, devolvía una *cadena*, que no
es ``int`` y por lo tanto **pasaba por aprobada**. El guard escrito para que la
población no se defina por dónde se encontró el defecto tenía su propio agujero por
el que pasó ``run_universe_screen_validation.py`` (``DEFAULT_ACCOUNT_ID = 1``), que
es el instrumento con el que se mide la tarea 129. Ahora el default se **resuelve**
y lo ilegible **hace fallar** el guard.
"""

from __future__ import annotations

import ast
import sqlite3
from pathlib import Path
from typing import NamedTuple

import pytest

from scripts.baseline_metrics import NoLiveAccount, resolve_account_id

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"


@pytest.fixture
def base_con_cuentas():
    """Una base en memoria con la 1 PAUSADA y la 2 activa — el estado real."""
    con = sqlite3.connect(":memory:")
    con.execute(
        "CREATE TABLE paper_accounts (id INTEGER PRIMARY KEY, name TEXT, initial_capital REAL, "
        "cash REAL, is_active INTEGER, allocation_mode TEXT, strategy TEXT, created_at TEXT)"
    )
    con.executemany(
        "INSERT INTO paper_accounts VALUES (?,?,?,?,?,?,?,?)",
        [
            (1, "Sim Principal", 50_000.0, 0.0, 0, "equal_weight", "auto", "2026-05-01"),
            (2, "Sim Segundo", 50_000.0, 0.0, 1, "equal_weight", "auto", "2026-07-01"),
        ],
    )
    return con


def test_sin_flag_resuelve_la_cuenta_VIVA_no_la_1(base_con_cuentas):
    """El corazón del arreglo: el default deja de ser un literal."""
    assert resolve_account_id(base_con_cuentas) == 2


def test_un_flag_explicito_se_respeta_aunque_apunte_a_una_pausada(base_con_cuentas, capsys):
    """Mandó el operador — pero **no en silencio**.

    Es la decisión de diseño 1 de la tarea 70: reproducir un número histórico sobre
    la cuenta 1 es legítimo, y el silencio es lo que dejó correr el defecto dos meses.
    """
    assert resolve_account_id(base_con_cuentas, 1) == 1
    err = capsys.readouterr().err
    assert "PAUSADA" in err
    assert "Sim Principal" in err


def test_un_flag_explicito_a_la_viva_no_grita(base_con_cuentas, capsys):
    """El aviso tiene que discriminar, o se vuelve ruido que nadie lee."""
    assert resolve_account_id(base_con_cuentas, 2) == 2
    assert capsys.readouterr().err == ""


def test_una_cuenta_inexistente_LEVANTA_en_vez_de_adivinar(base_con_cuentas):
    """Devolver un default acá sería reintroducir el defecto con otro número."""
    with pytest.raises(NoLiveAccount, match="no existe"):
        resolve_account_id(base_con_cuentas, 99)


def test_sin_ninguna_cuenta_activa_LEVANTA(base_con_cuentas):
    """Un runner que no sabe sobre qué cuenta mide no debe elegir una."""
    base_con_cuentas.execute("UPDATE paper_accounts SET is_active = 0")
    with pytest.raises(NoLiveAccount, match="is_active=1"):
        resolve_account_id(base_con_cuentas)


def test_con_varias_activas_toma_la_de_menor_id_y_avisa(base_con_cuentas, capsys):
    """Ambigüedad, no error: se elige de forma determinística y se dice."""
    base_con_cuentas.execute("UPDATE paper_accounts SET is_active = 1")
    assert resolve_account_id(base_con_cuentas) == 1
    assert "2 cuentas activas" in capsys.readouterr().err


# ── El test de POBLACIÓN, que es el que caza al próximo ───────────────────────
#
# **Tarea 128.** Hasta acá el lector devolvía la *cadena* ``"<no-literal>"`` cuando
# el default no era un literal, y el guard sólo acusaba con ``isinstance(default,
# int)``: o sea que **el fallo de lectura se leía como aprobación**. Por ese
# agujero pasó ``run_universe_screen_validation.py``, que define
# ``DEFAULT_ACCOUNT_ID = 1`` en su propio módulo — el instrumento con el que se
# mide la tarea 129 apuntaba a la cuenta pausada, y los cinco archivos de test
# relevantes corrían en verde con el defecto adentro.
#
# El arreglo **no** es sumar el archivo a una lista: eso es exactamente lo que
# hizo la 70 y por lo que estos siete quedaron afuera. El lector ahora **resuelve**
# el nombre —asignación de módulo, y ``from X import`` siguiendo al archivo que lo
# define— y cuando no puede devuelve ``ILEGIBLE``, que **hace fallar el guard**:
# un guard que no pudo mirar no aprueba. Ver [[guard-no-puede-usar-de-verdad-lo-que-chequea]].

_ROOT = _SCRIPTS.parent


class _Ilegible:
    """Centinela: el guard **no pudo** resolver este default.

    Es un objeto propio y no la cadena de antes a propósito. ``"<no-literal>"`` era
    un *valor*, y como no es ``int`` se colaba por el ``if`` del guard igual que
    un ``None`` legítimo. Lo ilegible tiene que ser un estado distinto de lo
    aprobado, o el guard aprueba lo que no leyó.
    """

    def __repr__(self) -> str:
        return "<ilegible>"


ILEGIBLE = _Ilegible()

# El **único** id de cuenta que un default puede traer sin ser un literal elegido
# en el repo: el espejo declarado de la cuenta viva. No es una excepción por
# archivo —cualquier script puede usarlo, y por eso sigue siendo un predicado y no
# una lista— y lo sostiene ``test_el_espejo_de_la_cuenta_viva_es_la_activa``, que
# lo re-verifica contra ``is_active`` en vez de creerle.
_ESPEJO_VIVO = ("analysis.harness_config", "LIVE_ACCOUNT_ID")
_ESPEJO_FUENTE = f"import:{_ESPEJO_VIVO[0]}.{_ESPEJO_VIVO[1]}"


class DefaultDeCuenta(NamedTuple):
    flag: str
    valor: object  # el valor resuelto, o ``ILEGIBLE``
    fuente: str  # "literal" | "modulo:NOMBRE" | "import:mod.NOMBRE" | "ilegible"


def _asignacion_de_modulo(arbol: ast.Module, nombre: str) -> ast.expr | None:
    """El valor asignado a ``nombre`` **a nivel de módulo** (la última gana)."""
    encontrado: ast.expr | None = None
    for nodo in arbol.body:
        if isinstance(nodo, ast.Assign):
            if any(isinstance(t, ast.Name) and t.id == nombre for t in nodo.targets):
                encontrado = nodo.value
        elif (
            isinstance(nodo, ast.AnnAssign)
            and nodo.value is not None
            and isinstance(nodo.target, ast.Name)
            and nodo.target.id == nombre
        ):
            encontrado = nodo.value
    return encontrado


def _importado_desde(arbol: ast.Module, nombre: str) -> tuple[str, str] | None:
    """``(modulo, nombre_original)`` del ``from X import nombre``, si lo hay.

    Devuelve el nombre **original** y no el local para que un ``as`` no lo pierda.
    """
    for nodo in ast.walk(arbol):
        if not (isinstance(nodo, ast.ImportFrom) and nodo.module and not nodo.level):
            continue
        for alias in nodo.names:
            if (alias.asname or alias.name) == nombre:
                return nodo.module, alias.name
    return None


def _resolver(
    nodo: ast.expr,
    arbol: ast.Module,
    path: Path,
    raiz: Path,
    visitados: set[tuple[Path, str]],
) -> tuple[object, str]:
    """``(valor, fuente)`` de un nodo de default. ``ILEGIBLE`` si no se pudo leer."""
    if isinstance(nodo, ast.Constant):
        return nodo.value, "literal"
    if not isinstance(nodo, ast.Name):
        return ILEGIBLE, "ilegible"

    simbolo = nodo.id
    if (path, simbolo) in visitados:  # un ciclo es ilegible, no aprobado
        return ILEGIBLE, "ilegible"
    visitados.add((path, simbolo))

    asignado = _asignacion_de_modulo(arbol, simbolo)
    if asignado is not None:
        valor, _ = _resolver(asignado, arbol, path, raiz, visitados)
        return valor, f"modulo:{simbolo}"

    origen = _importado_desde(arbol, simbolo)
    if origen is not None:
        modulo, original = origen
        otro = raiz.joinpath(*modulo.split(".")).with_suffix(".py")
        if otro.is_file():
            try:
                arbol2 = ast.parse(otro.read_text(encoding="utf-8"))
            except SyntaxError:  # pragma: no cover — un módulo roto ya lo caza la suite
                return ILEGIBLE, "ilegible"
            asignado2 = _asignacion_de_modulo(arbol2, original)
            if asignado2 is not None:
                valor, _ = _resolver(asignado2, arbol2, otro, raiz, visitados)
                return valor, f"import:{modulo}.{original}"
    return ILEGIBLE, "ilegible"


def _defaults_de_cuenta(path: Path, raiz: Path | None = None) -> list[DefaultDeCuenta]:
    """Los defaults de cada ``add_argument`` de cuenta. Por AST, no grep.

    Con grep esto se escapa apenas alguien parta la llamada en varias líneas —que
    es justo lo que hizo `ruff format` con estos mismos archivos.
    """
    raiz = raiz if raiz is not None else _ROOT
    try:
        arbol = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:  # pragma: no cover — un script roto ya lo caza la suite
        return []
    out: list[DefaultDeCuenta] = []
    for nodo in ast.walk(arbol):
        if not (isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Attribute)):
            continue
        if nodo.func.attr != "add_argument" or not nodo.args:
            continue
        primero = nodo.args[0]
        if not (isinstance(primero, ast.Constant) and isinstance(primero.value, str)):
            continue
        flag = primero.value
        if flag not in ("--account", "--account-id"):
            continue
        for kw in nodo.keywords:
            if kw.arg == "default":
                valor, fuente = _resolver(kw.value, arbol, path, raiz, set())
                out.append(DefaultDeCuenta(flag, valor, fuente))
    return out


def culpables(paths: list[Path], raiz: Path | None = None) -> list[str]:
    """Los defaults que este guard **no puede aprobar**, con el motivo.

    Dos motivos, y el segundo es la tarea 128: el id hardcodeado (lo de siempre) y
    el default que **no se pudo leer** — que antes pasaba por aprobado.
    """
    out: list[str] = []
    for py in paths:
        for d in _defaults_de_cuenta(py, raiz):
            if d.valor is ILEGIBLE:
                out.append(
                    f"{py.name}: {d.flag} — el guard NO pudo resolver el default, "
                    "así que no lo aprueba (tarea 128)"
                )
            elif d.fuente == _ESPEJO_FUENTE:
                continue  # el espejo declarado de la cuenta viva, re-verificado abajo
            elif isinstance(d.valor, int) and not isinstance(d.valor, bool):
                out.append(f"{py.name}: {d.flag} default={d.valor} ({d.fuente})")
    return out


def test_ningun_runner_hardcodea_una_cuenta():
    """Ningún ``--account`` puede tener un id de cuenta como default.

    Éste es el test que importa: el arreglo puntual de los siete envejece, pero el
    invariante —*nadie elige cuenta con un literal*— es el que evita que la lista
    vuelva a crecer por el costado, que es exactamente cómo estos siete quedaron
    afuera de la tarea 70. Desde la 128 el invariante cubre también el caso en que
    el id llega por un nombre en vez de por un literal.
    """
    assert not (malos := culpables(sorted(_SCRIPTS.glob("*.py")))), (
        "estos runners eligen cuenta con un id hardcodeado (o con un default que el "
        "guard no puede leer); el default tiene que ser None y resolverse contra "
        "`is_active` (tareas 99 y 128):\n  " + "\n  ".join(malos)
    )


def test_el_espejo_de_la_cuenta_viva_es_la_activa():
    """Lo que hace honesta la única excepción del guard (tarea 128).

    ``culpables()`` deja pasar un default que resuelve a
    ``analysis.harness_config.LIVE_ACCOUNT_ID`` porque *no es un literal elegido en
    el repo, es el espejo declarado de la cuenta viva*. Ese argumento vale sólo si
    algo re-verifica el espejo — y no lo hacía nadie: ``LIVE_WATCHLIST_SIZE``, su
    vecino de bloque, tiene su re-verificación desde la 89, y ``LIVE_ACCOUNT_ID``
    consulta la watchlist **de la cuenta 2** sin preguntar nunca si la 2 sigue
    siendo la activa. Sin esto, aceptar el símbolo sería aprobar un literal con
    otro nombre.

    Se saltea igual que la 89 y por la misma lección de la 107: se pregunta por los
    **datos**, no por el archivo — la suite se fabrica una ``finanzias.db`` vacía
    por el camino (tarea 108) y ``mode=ro`` sobre ella conecta sin error.
    """
    from analysis.harness_config import LIVE_ACCOUNT_ID

    activas = _cuentas_activas_vivas(_ROOT / "finanzias.db")
    if activas is None:
        pytest.skip("sin paper_accounts en este entorno")
    assert LIVE_ACCOUNT_ID in activas, (
        f"LIVE_ACCOUNT_ID dice {LIVE_ACCOUNT_ID} y las cuentas con is_active=1 son "
        f"{activas}. El espejo quedó apuntando a una cuenta pausada: actualizarlo, y "
        "revisar qué runners lo usan de default (tarea 128)."
    )


def _cuentas_activas_vivas(db: Path) -> list[int] | None:
    """Los ids con ``is_active=1``, o ``None`` si **no hay con qué comparar**.

    Las tres formas de "no hay con qué comparar" —sin archivo, sin tabla, sin
    filas— devuelven ``None``; cualquier otra cosa es el estado real.
    """
    if not db.exists():
        return None
    con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    try:
        tabla = con.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'paper_accounts'"
        ).fetchone()
        if tabla is None:
            return None
        filas = con.execute("SELECT id FROM paper_accounts WHERE is_active = 1").fetchall()
    except sqlite3.DatabaseError:  # pragma: no cover — una DB ilegible no es drift
        return None
    finally:
        con.close()
    return [int(r[0]) for r in filas] or None


# ── Mutación del lector, clave por clave — Tarea 128 ─────────────────────────
#
# El guard viejo pasaba **verde** sobre los casos 2, 7, 8 y 9 de acá abajo, que son
# todas las formas en que un id de cuenta puede llegar sin ser un literal. Un guard
# que no se prueba contra su propio punto ciego se prueba contra lo que ya sabe.


def _con_default(tmp_path: Path, prologo: str, default: str) -> Path:
    py = tmp_path / "runner_sintetico.py"
    py.write_text(
        "import argparse\n\n"
        f"{prologo}\n\n"
        "def main():\n"
        "    p = argparse.ArgumentParser()\n"
        f"    p.add_argument('--account-id', type=int, default={default})\n",
        encoding="utf-8",
    )
    return py


def test_mut_un_literal_lo_acusa(tmp_path):
    """El caso de siempre, que ya cazaba la 99."""
    (malo,) = culpables([_con_default(tmp_path, "", "1")])
    assert "default=1" in malo and "literal" in malo


def test_mut_una_constante_de_modulo_con_un_id_lo_acusa(tmp_path):
    """**El defecto de la 128**, en su forma exacta: así estaba escrito el validador
    del screen (``DEFAULT_ACCOUNT_ID = 1``) y el guard lo daba por aprobado."""
    (malo,) = culpables([_con_default(tmp_path, "DEFAULT_ACCOUNT_ID = 1", "DEFAULT_ACCOUNT_ID")])
    assert "default=1" in malo and "modulo:DEFAULT_ACCOUNT_ID" in malo


def test_mut_una_constante_de_modulo_en_None_no_acusa(tmp_path):
    """La contraprueba: resolver el nombre no puede volverse un acusador de nombres."""
    assert not culpables([_con_default(tmp_path, "DEFAULT_ACCOUNT_ID = None", "DEFAULT_ACCOUNT_ID")])


def test_mut_una_constante_IMPORTADA_en_None_no_acusa(tmp_path):
    """Sigue el ``from X import`` hasta el archivo que lo define — y el módulo es el
    real del repo, así que este test también fija que ``harvest_catalysts`` siga
    en ``None`` (es el patrón que la 70 dejó)."""
    prologo = "from scripts.harvest_catalysts import DEFAULT_ACCOUNT_ID"
    assert not culpables([_con_default(tmp_path, prologo, "DEFAULT_ACCOUNT_ID")])


def test_mut_el_espejo_de_la_cuenta_viva_no_acusa(tmp_path):
    """La única excepción, y es del **símbolo**, no del archivo: cualquier script
    puede usarlo. Lo que la hace honesta es
    ``test_el_espejo_de_la_cuenta_viva_es_la_activa``."""
    prologo = "from analysis.harness_config import LIVE_ACCOUNT_ID"
    assert not culpables([_con_default(tmp_path, prologo, "LIVE_ACCOUNT_ID")])


def test_mut_otro_entero_importado_del_MISMO_modulo_si_lo_acusa(tmp_path):
    """Que la excepción sea del símbolo y no de *venir de un import* — si no,
    alcanzaría con mover el literal a cualquier módulo para volverse invisible."""
    prologo = "from analysis.harness_config import LIVE_MAX_POSITIONS"
    (malo,) = culpables([_con_default(tmp_path, prologo, "LIVE_MAX_POSITIONS")])
    assert "import:analysis.harness_config.LIVE_MAX_POSITIONS" in malo


def test_mut_un_alias_no_pierde_el_simbolo(tmp_path):
    """``import ... as`` cambia el nombre local; el guard sigue al original."""
    prologo = "from analysis.harness_config import LIVE_MAX_POSITIONS as CUENTA"
    (malo,) = culpables([_con_default(tmp_path, prologo, "CUENTA")])
    assert "LIVE_MAX_POSITIONS" in malo


def test_mut_un_default_ILEGIBLE_lo_acusa(tmp_path):
    """**El corazón de la 128.** Antes esto devolvía la cadena ``"<no-literal>"``,
    que no es ``int``, así que el guard lo aprobaba. Un guard que no pudo mirar no
    aprueba: dice que no pudo."""
    (malo,) = culpables([_con_default(tmp_path, "", "os.environ.get('ACCT')")])
    assert "NO pudo resolver" in malo


def test_mut_un_ciclo_es_ILEGIBLE_y_no_aprobado(tmp_path):
    """Un ciclo de nombres no puede colgar el guard **ni** pasar por aprobado."""
    (malo,) = culpables([_con_default(tmp_path, "A = B\nB = A", "A")])
    assert "NO pudo resolver" in malo


def test_mut_None_literal_sigue_siendo_el_patron_aprobado(tmp_path):
    assert not culpables([_con_default(tmp_path, "", "None")])


def test_el_validador_del_screen_resuelve_contra_is_active():
    """Regresión del arreglo puntual (tarea 128), sobre el archivo real.

    El barrido de arriba ya lo cubre por población; esto fija además que el
    reemplazo sea el **patrón de la 99** —resolver contra ``is_active``— y no
    simplemente otro número.

    Se chequea por **AST y no por texto**, y no es cosmético: la primera versión de
    este test asserteaba ``"DEFAULT_ACCOUNT_ID = 1" not in txt`` y falló al escribir
    el docstring que **cita** el defecto arreglado. Es el mismo instrumento con el
    que ``test_ningun_script_defaultea_a_un_literal`` (tarea 70) mira tres archivos
    a mano: grep no distingue una línea de código de una línea de prosa.
    """
    py = _SCRIPTS / "run_universe_screen_validation.py"
    defaults = _defaults_de_cuenta(py)
    assert defaults, "dejó de declarar --account-id"
    assert all(d.valor is None for d in defaults), (
        f"el default tiene que ser None y resolverse contra is_active: {defaults}"
    )
    assert "resolve_account_id(" in py.read_text(encoding="utf-8")


def test_los_siete_runners_declaran_el_flag_y_lo_resuelven():
    """Contraprueba del anterior: que no pasen por estar vacíos.

    Un barrido que no encuentra nada porque **no miró nada** pasa igual de verde.
    Acá se fija que los siete sigan existiendo, sigan declarando el flag y sigan
    llamando al resolver.
    """
    esperados = {
        "run_exit_replay_t61.py",
        "run_atr_stop_recalib.py",
        "run_catalyst_exit_veto_backtest.py",
        "run_earnings_blackout_replay.py",
        "run_exposure_cap_replay.py",
        "run_risk_exit_autofill_replay.py",
        "analyze_expired_buys_financing.py",
    }
    for nombre in sorted(esperados):
        py = _SCRIPTS / nombre
        assert py.exists(), f"{nombre} desapareció — actualizá esta lista si fue a propósito"
        assert _defaults_de_cuenta(py), f"{nombre} dejó de declarar --account"
        assert "resolve_account_id(" in py.read_text(encoding="utf-8"), (
            f"{nombre} declara --account pero no lo resuelve contra `is_active` (tarea 99)"
        )
