"""Tarea 137 (CORPUS-FACTOR-VIEJO) — el corpus no afirma un valor vivo que nadie contrasta.

`.claude/skills/backtest-replay-harness/SKILL.md` decía *«Preferir el mecanismo ya
validado. Si existe un overlay shipeado (**hoy: el factor 0.50 de T20**), el candidato
primario es el que lo reusa»*. Escrito el 2026-08-19; el factor vivo es **0.25** desde
el 2026-09-07.

**No era una cita histórica.** La palabra es *«hoy»* y la frase **manda a reusar** ese
mecanismo al diseñar el próximo pre-registro, en el archivo que se lee **antes** de
congelarlo. Un candidato primario armado sobre un factor que ya no corre nace
desalineado con la cuenta viva.

**Y prueba que el barrido a ojo del paso 4 de `/ship` falla más de lo que dice:** ese
paso registra que el barrido del 2026-09-07 *«cazó el `SettingSpec`, la referencia y el
espejo, y dejó pasar la nota de R2b»*. Dejó pasar **dos** — ésta también. **2 de 5**, y
sólo una quedó documentada.

Dos chequeos, y los dos son *hacer mecánica la parte mecánica*:

1. **La tabla de `SETTINGS_REFERENCE.md` se contrasta contra el schema**, fila por
   fila. Son valores de `Default`, así que la fuente de verdad es ``DEFAULTS`` y la
   comparación no necesita leer nada a ojo.
2. **Una afirmación en presente sobre un número tiene que estar registrada.** Es el
   caso del *«hoy: 0.50»*, que **no nombra ninguna clave** —dice *«el factor 0.50 de
   T20»*— así que ningún chequeo por adyacencia de clave lo habría visto. El tell es la
   palabra *«hoy»*.

**El falso positivo que hay que evitar, y es la razón de que esto no sea un grep
ingenuo:** el corpus **cita valores viejos a propósito**. `SETTINGS_REFERENCE.md` dice
*«Bajó de 0.50 a 0.25 el 2026-09-07»* y eso es **correcto**: es historia, fechada. Un
chequeo que acuse esa línea estaría rompiendo los textos que están bien. Por eso el
registro pide **motivo escrito** en vez de prohibir el número.

**Y el precio de eso está medido, no supuesto.** El registro bendice el **párrafo**
entero, así que una afirmación nueva escrita *adentro de un párrafo ya registrado* se
le escapa. Probado por mutación: reintroducir *«hoy: el factor 0.50 de T20»* en el
mismo ítem que **cita** ese defecto **no dispara** —para un guard de texto, la prosa
que cita un defecto es indistinguible del defecto, que es la lección de la 128 y la
135— mientras que la misma afirmación en un párrafo nuevo **sí** dispara. Achicar la
granularidad a ventanas alrededor de cada *«hoy»* se probó y **no** arregla ese caso
concreto, porque la cita y el defecto conviven en la misma frase: lo que lo cubre es
que el número vivo se lea del fuente (`LIVE_REGIME_SCALE_FACTOR`), que es lo que la
línea arreglada ahora manda a hacer.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from config.settings_manager import DEFAULTS

_REPO = Path(__file__).resolve().parent.parent
_REFERENCE = _REPO / "docs" / "SETTINGS_REFERENCE.md"

# El corpus operativo, igual que en `test_corpus_operativo_t72.py`.
_CORPUS = [
    _REPO / "CLAUDE.md",
    *sorted((_REPO / ".claude").rglob("*.md")),
    _REFERENCE,
]

_FILA = re.compile(r"^\|\s*`([a-z0-9_]+)`\s*\|\s*`([^`]+)`", re.M)

# Claves que `SETTINGS_REFERENCE.md` documenta y que **no están en el schema**: el
# código las lee con `settings.get(clave, fallback)` y el fallback vive inline, así que
# el default documentado es una copia a mano que puede derivar en silencio. Hoy las
# cinco coinciden con su fallback (verificado 2026-09-09) — es latente, y va como
# **tarea 154**, no tapado acá.
_SIN_SCHEMA: dict[str, str] = {
    "price_sanity_band_pct": "leída con fallback inline en data/yahoo_finance.py (tarea 154)",
    "scale_drift_tolerance_pct": "leída con fallback inline en data/yahoo_finance.py (tarea 154)",
    "catalyst_hourly_harvest_enabled": "leída con fallback inline en paper_trading/scheduler.py (tarea 154)",
    "catalyst_hourly_harvest_minutes": "leída con fallback inline en paper_trading/scheduler.py (tarea 154)",
    "catalyst_refresh_on_open": "leída con fallback inline en paper_trading/scheduler.py (tarea 154)",
}

# Afirmaciones en presente sobre un número, con su motivo. Registrarla es la decisión
# que antes no existía: o el número se verifica contra el fuente, o se dice por qué no
# caduca. La forma del registro copia a `_NO_SON_CONSTANTES` de la tarea 72.
_CLAIMS_EN_PRESENTE: dict[str, str] = {
    "auditoria/SKILL.md:|r| > 0.58": "estadística histórica de una muestra vieja; el «hoy» de ese bloque es del ANCLA, no del número",
    "backtest-replay-harness/SKILL.md:devuelve **0.81%**": "VERIFICADA abajo contra SANITY_T33_CAGR, que es donde vive el número",
    "fair-value-feature/SKILL.md:−0.05": "el coeficiente que CLAUDE.md declara explícitamente que la regla NO usa (regla 3)",
    "SETTINGS_REFERENCE.md:Bajó de 0.50 a 0.25 el 2026-09-07": "cita histórica FECHADA, y correcta: es el cambio de la tarea 115",
    "backtest-replay-harness/SKILL.md:factor **0.50**": "la cita del defecto que la 137 arregló; el valor vivo lo manda a leer de LIVE_REGIME_SCALE_FACTOR",
    "backtest-replay-harness/SKILL.md:12.89% | **12.77%**": "tabla «publicado vs hoy» de un re-anclaje, que existe precisamente para mostrar la deriva",
}


def _valor(s: str):
    """El literal documentado, ya sin comillas de markdown."""
    s = s.strip().strip('"')
    if s in ("True", "False"):
        return s == "True"
    for conv in (int, float):
        try:
            return conv(s)
        except ValueError:
            continue
    return s


# ── (1) la tabla contra el schema ────────────────────────────────────────────


def _filas_documentadas() -> list[tuple[str, str]]:
    return _FILA.findall(_REFERENCE.read_text(encoding="utf-8"))


def test_la_referencia_documenta_el_default_REAL_de_cada_flag():
    """La parte enteramente mecánica: nadie tiene que leer esta tabla a ojo.

    Es el mismo criterio que la tarea **130** aplicó a los espejos `LIVE_*`: el repo
    afirma algo y **algo lo contrasta**, en vez de depender de que el próximo barrido
    manual no se saltee la fila.
    """
    malas = []
    for clave, doc in _filas_documentadas():
        if clave in _SIN_SCHEMA:
            continue
        if clave not in DEFAULTS:
            malas.append(f"{clave}: documentada pero no está en el schema ni en _SIN_SCHEMA")
            continue
        esperado, escrito = DEFAULTS[clave], _valor(doc)
        if isinstance(escrito, float) and isinstance(esperado, int | float):
            ok = abs(escrito - float(esperado)) < 1e-9
        else:
            ok = escrito == esperado
        if not ok:
            malas.append(f"{clave}: doc dice {doc!r} y el schema dice {esperado!r}")

    assert not malas, (
        "`docs/SETTINGS_REFERENCE.md` documenta un default que el schema no tiene "
        "(tarea 137):\n  " + "\n  ".join(malas)
    )


def test_la_tabla_no_esta_vacia():
    """Contraprueba: un barrido que no encontró filas pasa igual de verde."""
    assert len(_filas_documentadas()) >= 40


def test_cada_clave_sin_schema_tiene_motivo_escrito():
    """Una excepción sin motivo es una lista disfrazada de predicado."""
    assert all(m.strip() for m in _SIN_SCHEMA.values())
    documentadas = {c for c, _ in _filas_documentadas()}
    assert not (fantasmas := set(_SIN_SCHEMA) - documentadas), (
        f"estas claves ya no las documenta la referencia: {sorted(fantasmas)}"
    )


# ── (2) las afirmaciones en presente ─────────────────────────────────────────

_HOY = re.compile(r"\bhoy\b", re.IGNORECASE)
_DECIMAL = re.compile(r"\d+[.,]\d+")


def _afirmaciones_en_presente() -> list[tuple[str, str]]:
    """``(ubicación, párrafo)`` de cada bloque del corpus con «hoy» y un decimal.

    **Por párrafo y no por línea, y lo aprendí fallando.** La primera versión miraba
    línea por línea, y la cita que yo mismo escribí al arreglar el defecto quedó
    partida en dos —*«Acá decía «hoy: el»* en una y *«factor 0.50»* en la siguiente—
    así que **se le escapaba entera**. En markdown el ancho de línea es arbitrario: un
    guard que dependa de él tiene un agujero del tamaño de un `reflow`.
    """
    out = []
    for p in _CORPUS:
        if not p.exists():
            continue
        etiqueta = p.name if p.parent == _REPO or p.parent.name == "docs" else f"{p.parent.name}/{p.name}"
        for bloque in re.split(r"\n\s*\n", p.read_text(encoding="utf-8")):
            if _HOY.search(bloque) and _DECIMAL.search(bloque):
                out.append((etiqueta, " ".join(bloque.split())))
    return out


def test_toda_afirmacion_en_presente_sobre_un_numero_esta_registrada():
    """**El chequeo que habría cazado el «hoy: el factor 0.50».**

    No busca claves —esa frase no nombraba ninguna— sino la forma *«hoy … N,NN»*, que
    es como se escribe una afirmación sobre el valor vivo. Cada una tiene que estar en
    `_CLAIMS_EN_PRESENTE` con su motivo: o se verifica contra el fuente, o se dice por
    qué no caduca.
    """
    sin_registrar = [
        f"{etiqueta}: {ln.strip()[:110]}"
        for etiqueta, ln in _afirmaciones_en_presente()
        if not any(frag.split(":", 1)[1] in ln for frag in _CLAIMS_EN_PRESENTE if frag.startswith(etiqueta))
    ]
    assert not sin_registrar, (
        "estas líneas del corpus afirman un número **en presente** y nada las contrasta "
        "(tarea 137). Registrala en `_CLAIMS_EN_PRESENTE` con el motivo, o sacá el "
        "número —que suele ser lo correcto, como en la tarea 135:\n  " + "\n  ".join(sin_registrar)
    )


def test_el_registro_no_tiene_entradas_FANTASMA():
    """Si una entrada del registro ya no matchea nada, la afirmación se fue: sacala.

    Sin esto el registro crece y el guard se afloja sin que nadie lo note — que es
    exactamente cómo envejeció el párrafo de la tarea 135.
    """
    lineas = _afirmaciones_en_presente()
    fantasmas = [
        frag
        for frag in _CLAIMS_EN_PRESENTE
        if not any(frag.startswith(e) and frag.split(":", 1)[1] in ln for e, ln in lineas)
    ]
    assert not fantasmas, f"entradas del registro que ya no matchean nada: {fantasmas}"


@pytest.mark.parametrize("frag", list(_CLAIMS_EN_PRESENTE))
def test_cada_claim_registrado_dice_por_que(frag):
    assert _CLAIMS_EN_PRESENTE[frag].strip()


def test_el_unico_claim_VERIFICABLE_se_verifica_de_verdad():
    """Registrar no es contrastar, y donde se puede contrastar hay que hacerlo.

    La skill dice *«hoy devuelve **0.81%**»* del sanity de la T33, y ese número **vive
    en una constante** (`SANITY_T33_CAGR`), así que no hace falta creerle a la prosa.
    El resto del registro son citas históricas o coeficientes que la regla no usa: no
    tienen un fuente contra el cual medirse, y eso es lo que el motivo escrito declara.
    """
    from scripts.run_prio_event_t49 import SANITY_T33_CAGR

    txt = (_REPO / ".claude" / "skills" / "backtest-replay-harness" / "SKILL.md").read_text(encoding="utf-8")
    assert f"{100 * SANITY_T33_CAGR:.2f}%" in txt, (
        f"la skill cita un valor del sanity T33 distinto de SANITY_T33_CAGR "
        f"({100 * SANITY_T33_CAGR:.2f}%) — es el defecto de la 137 otra vez"
    )
