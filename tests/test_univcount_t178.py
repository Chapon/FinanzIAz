"""Tarea 178 (UNIVCOUNT-VIEJO) — los conteos del universo de referencia salen de un lugar derivado.

**Qué pasaba.** `analysis/harness_config.py` describía el universo de referencia como *«la
watchlist de la cuenta viva recortada a los tickers con artefacto PIT (127/128; falta ASML)»*.
Era exacto el 2026-09-08 y lo rompió la **156** al sacar AVB: watchlist 127, universo 126. El
header del propio archivo de universo ya decía **126/127**, porque lo escribe el script que lo
regenera; el comentario lo había escrito una persona.

**Y había un segundo, de la misma clase:** el docstring del módulo decía en presente *«La cuenta
viva es la 2: 10 slots y 128 tickers»*, escrito el 2026-08-12 (tarea 27). Queda fechado y
apuntando a las constantes, que son las que se re-verifican contra la DB (89 y 99).

**Qué fija este archivo.** El conteo vive en **un** lugar —el header del archivo de universo— y
acá se **deriva**: `N/M` contra el archivo y la constante, y la lista *«Sin PIT»* contra la
diferencia. Y el código deja de repetirlo: un `NNN/NNN` en `harness_config.py` es rojo, y un
*«N slots y M tickers»* sólo pasa si coincide con las constantes vivas **o** está fechado.
Es el criterio de la **135** y la **138**: un conteo a mano caduca solo; una fecha no.
"""

from __future__ import annotations

import io
import re
import tokenize
from pathlib import Path

import pytest

import analysis.harness_config as hc

_REPO = Path(__file__).resolve().parent.parent
_HC = _REPO / "analysis" / "harness_config.py"
_FECHA = re.compile(r"\b20\d\d-\d\d-\d\d\b")


def _header(path: Path) -> tuple[int, int, list[str]]:
    texto = path.read_text(encoding="utf-8-sig")
    m = re.search(r"^# (\d+)/(\d+) tickers de la watchlist\.(?: Sin PIT: ([^.]+)\.)?$", texto, re.MULTILINE)
    assert m, f"{path.name}: el header dejó de declarar el conteo — ¿cambió `refresh_live_universe.py`?"
    sin_pit = [t.strip() for t in m.group(3).split(",")] if m.group(3) else []
    return int(m.group(1)), int(m.group(2)), sin_pit


# ── 1. El conteo vive en el header, y el header se deriva ───────────────────


def test_el_header_del_universo_dice_lo_que_el_archivo_TIENE():
    path = _REPO / hc.LIVE_UNIVERSE_FILE
    n, m, sin_pit = _header(path)

    assert n == len(hc.parse_universe_file(path)), "el header no coincide con los tickers del archivo"
    assert m == hc.LIVE_WATCHLIST_SIZE, (
        f"el header dice {m} de watchlist y `LIVE_WATCHLIST_SIZE` es {hc.LIVE_WATCHLIST_SIZE}: "
        "uno de los dos quedó viejo — regenerar con `scripts/refresh_live_universe.py`"
    )
    assert len(sin_pit) == m - n, f"la lista «Sin PIT» ({sin_pit}) no explica la diferencia {m} − {n}"
    assert not set(sin_pit) & set(hc.parse_universe_file(path)), "un ticker «sin PIT» está en el universo"


def test_el_parser_del_header_no_acepta_lo_que_no_es(tmp_path):
    """Contraprueba del instrumento: con un header que no cierra, el test de arriba tiene que
    poder ponerse rojo — no alcanza con que el regex matchee."""
    p = tmp_path / "u.txt"
    p.write_text("# 3/5 tickers de la watchlist. Sin PIT: ASML.\nAAA\nBBB\nCCC\n", encoding="utf-8")
    n, m, sin_pit = _header(p)
    assert (n, m, sin_pit) == (3, 5, ["ASML"])
    assert len(sin_pit) != m - n  # el caso que el test real rechaza

    p.write_text("# 3/3 tickers de la watchlist.\nAAA\nBBB\nCCC\n", encoding="utf-8")
    assert _header(p) == (3, 3, [])


# ── 2. El código no repite el conteo ────────────────────────────────────────


def _comentarios_y_docstrings(path: Path) -> list[tuple[int, str]]:
    """(línea, texto) de cada **bloque** de comentarios y cada string que ocupa un statement.

    Los comentarios en líneas consecutivas se unen en un solo bloque: una cita que se parte en
    dos líneas (``*«(127/128; falta`` / ``ASML)»*``) token por token no tiene sus comillas
    cerradas, y el detector la acusaba. Lo cazó la primera corrida, sobre la corrección de la
    propia tarea.
    """
    fuente = path.read_text(encoding="utf-8")
    out: list[tuple[int, str]] = []
    previo = None
    for tok in tokenize.generate_tokens(io.StringIO(fuente).readline):
        if tok.type == tokenize.COMMENT:
            linea_previa, texto_previo = out[-1] if out else (None, "")
            if (
                out
                and texto_previo.startswith("#")
                and tok.start[0] == linea_previa + texto_previo.count("\n") + 1
            ):
                out[-1] = (linea_previa, f"{texto_previo}\n{tok.string}")
            else:
                out.append((tok.start[0], tok.string))
        elif tok.type == tokenize.STRING and (
            previo is None or previo.type in (tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT, tokenize.NL)
        ):
            out.append((tok.start[0], tok.string))
        if tok.type not in (tokenize.COMMENT, tokenize.NL):
            previo = tok
    return out


_CITA = re.compile(r"«[^»]*»")
_REF_TAREA = re.compile(r"\b(?:tareas?|la|las|T)\s*$", re.IGNORECASE)


def _conteos_ratio(texto: str) -> list[str]:
    """Los ``NNN/NNN`` que afirman un conteo.

    Dos exclusiones, y las dos las pidió el propio test la primera vez que corrió:

    * **Las citas** (``«…»``). La corrección de este mismo comentario cita el texto viejo, y un
      detector que la acusa es el defecto de [[cross-check-por-substring-acepta-lo-contrario]]
      al revés: rojo sobre la línea que cuenta que el conteo se fue.
    * **Las referencias a tareas.** Decía *«tres dígitos a cada lado = conteo»* y el repo ya
      tiene tareas de tres dígitos: *Tarea 115/119* salía como conteo.
    """
    sin_citas = _CITA.sub("«»", texto)
    out = []
    for m in re.finditer(r"(?<![\d/])\d{3}/\d{3}(?![\d/])", sin_citas):
        if not _REF_TAREA.search(sin_citas[max(0, m.start() - 12) : m.start()]):
            out.append(m.group(0))
    return out


def test_harness_config_no_escribe_la_razon_universo_watchlist():
    hallados = [(n, r) for n, t in _comentarios_y_docstrings(_HC) for r in _conteos_ratio(t)]
    assert not hallados, (
        f"conteos NNN/NNN escritos a mano en harness_config.py: {hallados}. El conteo vive en el "
        "header del archivo de universo, que este test deriva"
    )


def test_slots_y_tickers_coinciden_con_lo_vivo_o_estan_FECHADOS():
    """*«N slots y M tickers»* en presente es una afirmación sobre la cuenta viva. Pasa si es
    verdad hoy o si dice cuándo lo fue **en la misma oración**.

    La primera versión buscaba la fecha en los 120 caracteres previos, y la mutación que
    restaura el texto original pasaba **verde**: la oración anterior termina en *«pausada desde
    el 2026-07-01»*, así que había una fecha cerca que no fechaba nada."""
    fuera: list[str] = []
    for _, texto in _comentarios_y_docstrings(_HC):
        for m in re.finditer(r"(\d+) slots y (\d+) tickers", texto):
            vivo = (int(m.group(1)), int(m.group(2))) == (hc.LIVE_MAX_POSITIONS, hc.LIVE_WATCHLIST_SIZE)
            inicio = max(texto.rfind(". ", 0, m.start()), texto.rfind(".\n", 0, m.start()))
            fechado = _FECHA.search(texto[inicio + 1 : m.end()])
            if not (vivo or fechado):
                fuera.append(m.group(0))
    assert not fuera, f"conteos de la cuenta viva sin fecha que ya no coinciden: {fuera}"


@pytest.mark.parametrize(
    ("texto", "rojo"),
    [
        ("# recortada a los tickers con artefacto PIT (127/128; falta ASML).", True),
        ("# 126/127 tickers de la watchlist", True),
        ("# Acá decía *«(127/128; falta ASML)»* y lo rompió la 156", False),
        ("# **De qué población sale ese 21-36% — Tarea 115/119.**", False),
        ("# las tareas 63/64 y 29/30/31", False),
        ("# ver 2026-06-01/05", False),
    ],
)
def test_el_detector_de_razones_distingue_conteos_de_tareas(texto, rojo):
    assert bool(_conteos_ratio(texto)) is rojo
