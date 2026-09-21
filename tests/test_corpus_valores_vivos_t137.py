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

**Precisión sobre ese párrafo, porque la tarea 214 SÍ adoptó ventanas.** Lo de arriba
sigue en pie y no se contradice: las ventanas no arreglan *«una afirmación nueva escrita
adentro de un párrafo ya registrado»*, y eso sigue sin cubrirse. La 214 las usa para el
problema **opuesto** —un bloque que acusa de más porque una lista de markdown no tiene
líneas en blanco entre ítems— y no cambia la granularidad del **registro**, que sigue
bendiciendo el párrafo entero. O sea: dos defectos distintos, y la ventana sólo resuelve
el segundo.
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

# Claves que `SETTINGS_REFERENCE.md` documenta y que **no están en el schema**.
#
# **Está vacío, y eso es el resultado de la tarea 154.** Tenía cinco: el código las
# leía con `settings.get(clave, fallback)` y el fallback vivía al lado del call site,
# así que no salían en la pestaña Settings, su default documentado era una copia a mano
# que podía derivar en silencio, y eran las únicas cinco filas de la referencia que
# este guard no podía contrastar. Al declararlas en el `SCHEMA` con **el mismo valor**,
# la excepción se vació — que es la señal de que la brecha se cerró y no de que se tapó.
#
# Si alguna vuelve a aparecer acá, la pregunta correcta no es *«¿le pongo el motivo?»*
# sino *«¿por qué este flag no está en el schema?»*.
_SIN_SCHEMA: dict[str, str] = {}

# Afirmaciones en presente sobre un número, con su motivo. Registrarla es la decisión
# que antes no existía: o el número se verifica contra el fuente, o se dice por qué no
# caduca. La forma del registro copia a `_NO_SON_CONSTANTES` de la tarea 72.
_CLAIMS_EN_PRESENTE: dict[str, str] = {
    "auditoria/SKILL.md:|r| > 0.58": "estadística histórica de una muestra vieja; el «hoy» de ese bloque es del ANCLA, no del número",
    "backtest-replay-harness/SKILL.md:devuelve **0.46%**": "VERIFICADA abajo contra SANITY_T33_CAGR, que es donde vive el número (re-anclado 2026-09-09, tarea 157: era 0.81%)",
    "fair-value-feature/SKILL.md:−0.05": "el coeficiente que CLAUDE.md declara explícitamente que la regla NO usa (regla 3)",
    "SETTINGS_REFERENCE.md:Bajó de 0.50 a 0.25 el 2026-09-07": "cita histórica FECHADA, y correcta: es el cambio de la tarea 115",
    "backtest-replay-harness/SKILL.md:factor **0.50**": "la cita del defecto que la 137 arregló; el valor vivo lo manda a leer de LIVE_REGIME_SCALE_FACTOR",
    "backtest-replay-harness/SKILL.md:12.89% | **12.77%**": "tabla «publicado vs hoy» de un re-anclaje, que existe precisamente para mostrar la deriva",
    # La entrada de `CLAUDE.md:aunque hoy no hay ninguno` vivió acá entre la 209 y la
    # **214**, y se fue porque dejó de hacer falta: era el falso positivo del
    # acoplamiento —su «hoy» estaba a **2741** caracteres de los decimales que lo
    # disparaban, que son de otra regla— y con la ventana ya no casa. Lo detectó el
    # propio `test_el_registro_no_tiene_entradas_FANTASMA`, no una lectura.
    "SETTINGS_REFERENCE.md:que hoy coincide **por casualidad**": (
        "tarea 179: la fila de `atr_tp_mult` afirma que el literal del harness (4.0) coincide "
        "HOY con el valor vivo, y eso es el hallazgo, no un dato de color — es el `FALTA_ESPEJO` "
        "de la 185. VERIFICADA por `test_los_FALTA_ESPEJO_son_los_que_la_auditoria_reporto`, que "
        "se pone rojo si se le da espejo y nadie actualiza esta fila"
    ),
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


#: A qué distancia máxima (en caracteres del bloque normalizado) un «hoy» y un decimal
#: cuentan como **la misma afirmación** (tarea 214).
#:
#: **Calibrado contra la población, no elegido.** Medidas las distancias mínimas de los
#: ocho bloques que el guard marcaba el 2026-09-21: las **siete** afirmaciones reales
#: —las registradas abajo con su motivo— están a **6, 10, 15, 17, 29, 29 y 76**; la
#: octava, el falso positivo que abrió esta tarea, a **2741**. Las dos poblaciones están
#: separadas **36×** y 300 cae en el medio: ~4× por encima del peor caso verdadero
#: (margen para una oración más larga) y ~9× por debajo del falso.
_VENTANA_HOY_DECIMAL = 300


def _afirmaciones_en_presente() -> list[tuple[str, str]]:
    """``(ubicación, párrafo)`` de cada bloque del corpus con «hoy» **cerca de** un decimal.

    **Por párrafo y no por línea, y lo aprendí fallando.** La primera versión miraba
    línea por línea, y la cita que yo mismo escribí al arreglar el defecto quedó
    partida en dos —*«Acá decía «hoy: el»* en una y *«factor 0.50»* en la siguiente—
    así que **se le escapaba entera**. En markdown el ancho de línea es arbitrario: un
    guard que dependa de él tiene un agujero del tamaño de un `reflow`.

    **Pero el péndulo se había pasado de largo (tarea 214).** El remedio para *«la línea
    es arbitraria»* no es *«el bloque entero»*: una lista numerada de markdown **no tiene
    líneas en blanco entre ítems**, así que las tres reglas de `CLAUDE.md` eran UN bloque
    y un «hoy» de la regla 1 se apareaba con un decimal de la regla 3, que habla de otra
    cosa. Ahora los dos tienen que estar a menos de ``_VENTANA_HOY_DECIMAL`` caracteres —
    la distancia es la que dice si son la misma afirmación, y no el ancho de línea ni el
    largo del bloque, que son los dos arbitrarios.

    **Por qué importa acusar de menos acá:** el guard fallaba hacia el lado seguro, pero
    registrar de más **desgasta el registro**. Cuando ``_CLAIMS_EN_PRESENTE`` se llena de
    entradas cuyo motivo es *«no aplica»*, deja de servir para lo que se hizo.
    """
    out = []
    for p in _CORPUS:
        if not p.exists():
            continue
        etiqueta = p.name if p.parent == _REPO or p.parent.name == "docs" else f"{p.parent.name}/{p.name}"
        for bloque in re.split(r"\n\s*\n", p.read_text(encoding="utf-8")):
            normalizado = " ".join(bloque.split())
            if _hoy_cerca_de_un_decimal(normalizado):
                out.append((etiqueta, normalizado))
    return out


def _hoy_cerca_de_un_decimal(texto: str) -> bool:
    """¿Hay un «hoy» a menos de ``_VENTANA_HOY_DECIMAL`` de algún decimal? (tarea 214)

    Se compara contra **todos** los pares y no contra el primero de cada uno: un bloque
    puede tener varios «hoy» y varios números, y basta con que **uno** de los pares esté
    cerca para que haya una afirmación que registrar.
    """
    decimales = [m.start() for m in _DECIMAL.finditer(texto)]
    if not decimales:
        return False
    return any(abs(h.start() - d) <= _VENTANA_HOY_DECIMAL for h in _HOY.finditer(texto) for d in decimales)


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


# ── (3) la ventana del apareo (tarea 214) ────────────────────────────────────


def test_un_hoy_LEJOS_de_un_decimal_no_dispara():
    """**El falso positivo que abrió la 214.**

    Las tres reglas de `CLAUDE.md` son ítems consecutivos de una lista numerada, o sea
    que markdown **no las separa con línea en blanco** y el splitter las ve como UN
    bloque. Un «hoy» de la regla 1 se apareaba con los decimales de la regla 3, que
    hablan de otra cosa — y había que registrarlo aunque no afirmara ningún número.
    """
    lejano = "hoy no hay ninguno. " + ("relleno " * 60) + "el coeficiente es −0.05"
    assert len(lejano) > _VENTANA_HOY_DECIMAL, "el caso de prueba tiene que estar LEJOS"
    assert not _hoy_cerca_de_un_decimal(lejano)


def test_un_hoy_CERCA_de_un_decimal_sigue_disparando():
    """La otra dirección, que es la que no se puede perder: el guard tiene que acusar."""
    assert _hoy_cerca_de_un_decimal("el overlay shipeado hoy: el factor 0.50 de T20")


def test_la_cita_que_motivo_el_cambio_a_PARRAFO_sigue_cazandose():
    """**Contraprueba del agujero original** — el que el paso de línea a párrafo cerró.

    La cita del *«factor 0.50»* quedó partida en dos líneas por un reflow. Si la ventana
    la dejara escapar, la 214 habría reabierto el defecto que la 137 arregló, y esto
    estaría cambiando un falso positivo por un falso **negativo**, que es mucho peor.
    """
    partida = "Si existe un overlay shipeado (**hoy: el\nfactor 0.50 de T20**), el candidato"
    assert _hoy_cerca_de_un_decimal(" ".join(partida.split()))


def test_la_ventana_cae_entre_sus_dos_limites_MEDIDOS():
    """El valor no es libre: lo acotan las dos poblaciones medidas el 2026-09-21.

    Por abajo, tiene que dejar pasar la peor afirmación **real** (76 caracteres); por
    arriba, tiene que rechazar el falso positivo (2741). Si alguien mueve el número
    fuera de ese rango se entera acá y no descubriendo que el guard dejó de acusar.
    """
    peor_verdadero, falso_positivo = 76, 2741
    assert peor_verdadero < _VENTANA_HOY_DECIMAL, (
        f"con {_VENTANA_HOY_DECIMAL} se perdería la afirmación real más larga medida "
        f"({peor_verdadero} caracteres)"
    )
    assert falso_positivo > _VENTANA_HOY_DECIMAL, (
        f"con {_VENTANA_HOY_DECIMAL} vuelve a casar el acoplamiento de la lista de "
        f"`CLAUDE.md` ({falso_positivo} caracteres)"
    )


def test_sin_decimal_no_dispara_aunque_haya_hoy():
    """El «hoy» solo no es nada: lo que se persigue es la afirmación sobre un NÚMERO."""
    assert not _hoy_cerca_de_un_decimal("hoy la cuenta viva es la 2 y no tiene decimales")


def test_el_registro_no_tiene_entradas_FANTASMA_por_la_ventana():
    """Achicar el apareo puede dejar entradas registradas sin nada que bendecir.

    Ya lo cubre `test_el_registro_no_tiene_entradas_FANTASMA`, y de hecho **fue el que
    detectó** que la entrada de `CLAUDE.md` sobraba tras este cambio — no una lectura.
    Esto lo deja dicho al lado de la ventana, que es donde alguien que la toque va a
    mirar: bajar `_VENTANA_HOY_DECIMAL` sin re-correr el corpus deja basura en el
    registro, y registrar de más es justo lo que la 214 vino a evitar.
    """
    bloques = [b for _, b in _afirmaciones_en_presente()]
    huerfanas = [frag for frag in _CLAIMS_EN_PRESENTE if not any(frag.split(":", 1)[1] in b for b in bloques)]
    assert not huerfanas, huerfanas
