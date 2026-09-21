"""Tarea 211 — el cortafuegos de red también corta en un **subproceso**.

**La mitad que le faltaba a la 209.** Aquel corte vive en un fixture ``autouse`` con
``monkeypatch``, o sea **en memoria de este proceso**. Un subproceso hereda el entorno
pero no los parches, así que salía a internet igual. Es la forma exacta de la **108**:
``_guard_real_db`` rebindeaba la DB acá y los hijos se quedaban con la ruta de
producción —creando ``finanzias.db`` en un checkout limpio y dejando el job ``pytest``
del CI **rojo 12 corridas**— hasta que el aislamiento se movió a una variable de entorno,
que es lo único que un hijo hereda solo.

**Cuánto costaba hoy: nada, y por eso la tarea era BAJA.** Seis archivos de la suite
abren subprocesos y **ninguno** toca la red; el barrido de la 209 lo midió. Lo que se
cierra no es una fuga abierta sino la propiedad que hace útil al cortafuegos: que nadie
tenga que acordarse.

**Todo lo de acá se prueba lanzando un intérprete de verdad**, porque un subproceso
falso no prueba nada sobre un subproceso. Ninguno sale a internet: el que debería quedar
bloqueado se verifica por el nombre de la excepción, y el que debería quedar exento se
verifica mirando si el parche está puesto, sin llegar a conectar.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap

import pytest

from tests.conftest import VAR_ENTORNO, _cortafuegos

# Un hijo que pregunta si `socket.connect` quedó parcheado, sin intentar conectarse.
# Es lo que permite correr esto en el CI y con la máquina sin internet.
_HIJO_MIRA_EL_PARCHE = """
import socket
print("PARCHEADO" if socket.socket.connect.__name__ != "connect" else "LIMPIO")
"""

# Un hijo que intenta salir de verdad, e imprime QUIÉN lo frenó.
_HIJO_INTENTA_SALIR = """
import socket
try:
    socket.socket().connect(("finnhub.io", 443))
except Exception as e:
    print(type(e).__name__)
else:
    print("CONECTO")
"""


def _correr_hijo(codigo: str, env: dict | None = None) -> str:
    r = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(codigo)],
        capture_output=True,
        text=True,
        timeout=60,
        env=env if env is not None else os.environ.copy(),
    )
    assert r.returncode == 0, f"el hijo murió: {r.stderr[-800:]}"
    return r.stdout.strip()


# ── El corte llega al hijo ───────────────────────────────────────────────────


def test_un_subproceso_hereda_el_cortafuegos():
    """**El test de la tarea.** El hijo arranca con el parche puesto, sin hacer nada."""
    assert _correr_hijo(_HIJO_MIRA_EL_PARCHE) == "PARCHEADO"


def test_un_subproceso_no_llega_a_internet():
    """Y el parche **muerde**: no alcanza con que esté puesto.

    Se afirma sobre el nombre de la excepción y no sobre el mensaje: si la máquina no
    tuviera red saldría un ``OSError``/``gaierror``, y entonces el test estaría pasando
    sin haber probado el corte.
    """
    assert _correr_hijo(_HIJO_INTENTA_SALIR) == "RedBloqueadaEnLaSuite"


def test_sin_la_variable_el_hijo_sale_intacto():
    """Contraprueba: el ``sitecustomize`` **no hace nada** si la variable no está.

    Es lo que sostiene el escape por marcador, y también lo que evita que este
    directorio en el ``PYTHONPATH`` le cambie el comportamiento a algún proceso ajeno.
    """
    env = os.environ.copy()
    env.pop(VAR_ENTORNO, None)
    assert _correr_hijo(_HIJO_MIRA_EL_PARCHE, env=env) == "LIMPIO"


@pytest.mark.network
def test_un_test_MARCADO_no_le_pasa_el_corte_a_su_hijo():
    """El escape vale para las dos mitades, y esa decisión no es obvia.

    Un test que se marca ``network`` porque necesita la API real la va a necesitar igual
    si el fetch lo hace un subproceso; un escape que cubriera sólo al padre sería una
    trampa. El fixture **borra** la variable en los tests marcados, así que el hijo la
    hereda ausente.

    No se conecta a nada: mira el parche. Va marcado ``network`` a propósito —es lo que
    se está probando—, así que se saltea en la corrida normal, y por eso el caso también
    está cubierto sin marcador en ``test_sin_la_variable_el_hijo_sale_intacto``.
    """
    assert VAR_ENTORNO not in os.environ
    assert _correr_hijo(_HIJO_MIRA_EL_PARCHE) == "LIMPIO"


def test_la_variable_esta_puesta_en_un_test_normal():
    """El otro lado del anterior, sin marcador y sin lanzar nada."""
    assert os.environ.get(VAR_ENTORNO) == "1"


# ── El PYTHONPATH se AGREGA, no se pisa ────────────────────────


def test_el_pythonpath_previo_sobrevive():
    """**Esto lo pidió una mutación que quedó verde.**

    ``PYTHONPATH`` está **vacío** en esta máquina, así que "agregar" y "pisar" dan el
    mismo resultado y una mutación que reemplace el join por ``[directorio]`` pasa
    desapercibida. Por eso el armado vive en ``pythonpath_con``, que es pura: acá se le
    pasa un valor previo inventado y se afirma que sigue estando.

    No es higiene: ``PYTHONPATH`` es del entorno de Chapa, y pisarlo desde la suite le
    cambiaría la resolución de imports a todo subproceso que ella lance.
    """
    previo = os.pathsep.join(["/ya/estaba", "/y/esto/tambien"])
    salida = _cortafuegos.pythonpath_con("/el/nuevo", previo, os.pathsep)

    partes = salida.split(os.pathsep)
    assert partes == ["/ya/estaba", "/y/esto/tambien", "/el/nuevo"], (
        "lo previo tiene que sobrevivir Y el nuevo tiene que ir AL FINAL, para no "
        "ganarle la prioridad a lo que el entorno ya resolvía"
    )


@pytest.mark.parametrize("previo", [None, "", "   "])
def test_sin_pythonpath_previo_no_queda_un_separador_suelto(previo):
    """Un ``PYTHONPATH`` que empieza con el separador significa *el cwd*, y eso es otra cosa.

    El caso de esta máquina (variable ausente) es justo el que un join ingenuo rompe:
    ``sep.join(["", dir])`` da ``";dir"``, que en Python mete el **directorio actual** en
    el path de todo hijo. Se fija para las tres formas de "no había nada".
    """
    salida = _cortafuegos.pythonpath_con("/el/nuevo", previo, os.pathsep)
    assert not salida.startswith(os.pathsep), salida
    assert salida.strip(os.pathsep) == salida.strip()


# ── El escape del marcador borra la variable DE VERDAD ────────────────


def test_el_delenv_del_escape_no_es_un_no_op(pytester):
    """**La otra mutación que quedó verde, y por qué.**

    En la primera versión la variable la ponía el fixture con ``monkeypatch.setenv``, que
    se deshace al terminar cada test — así que al empezar un test marcado ``network`` ya
    estaba **ausente** y el ``delenv`` no hacía nada: sacarlo no rompía ningún test. Ahora
    la variable se pone **al importar el conftest**, con lo cual el escape del marcador
    *es* el ``delenv``.

    Se prueba con un pytest anidado porque hay que observar el entorno **adentro** de un
    test marcado, y este proceso ya decidió el suyo. No se conecta a nada.
    """
    pytester.makeconftest(
        f"""
        import sys
        sys.path.insert(0, {str(_raiz())!r})
        from tests.conftest import _cortafuegos_de_red  # noqa: F401 — autouse real

        def pytest_configure(config):
            config.addinivalue_line('markers', 'network: pega a la API real')
        """
    )
    pytester.makepyfile(
        """
        import os
        import pytest

        VAR = "FINANZIAS_BLOQUEAR_RED"

        @pytest.mark.network
        def test_marcado_no_ve_la_variable():
            assert VAR not in os.environ

        def test_sin_marcar_si_la_ve():
            assert os.environ.get(VAR) == "1"
        """
    )
    res = pytester.runpytest_subprocess("-p", "no:cacheprovider")
    res.assert_outcomes(passed=2)


def _raiz():
    from pathlib import Path

    return Path(__file__).resolve().parent.parent


# ── Una sola implementación, no dos ──────────────────────────────────────────


def test_el_padre_y_el_hijo_usan_LA_MISMA_implementacion():
    """Dos copias del mismo corte divergen — es lo que pasó en la 207.

    Ahí ``collect_all`` y los ``collect_*`` públicos eran dos caminos, y cuando se movió
    la costura uno quedó sin el veredicto y tres tests salieron a la API real. Acá el
    fixture del padre y el ``sitecustomize`` del hijo llaman a ``instalar`` del mismo
    módulo, y esto lo fija por identidad en vez de por parecido.
    """
    import importlib

    site = importlib.import_module("sitecustomize")
    fuente = importlib.import_module("cortafuegos_red")

    assert site.__file__.endswith(os.path.join("_cortafuegos", "sitecustomize.py"))
    assert fuente.instalar is _cortafuegos.instalar, (
        "el sitecustomize importa `cortafuegos_red` por su cuenta: si esa resolución "
        "apuntara a otro archivo, padre e hijo estarían cortando con dos copias"
    )


def test_el_sitecustomize_no_levanta_nunca():
    """``site.py`` lo corre al arrancar el intérprete: una excepción ensucia TODO hijo.

    Se ejercita el peor caso —la variable puesta y el módulo del corte **no importable**,
    porque el directorio salió del path— y se verifica que el hijo igual arranca y corre
    su programa. Sin esto, el ``try`` mudo del ``sitecustomize`` es una afirmación sin
    contraprueba.
    """
    env = os.environ.copy()
    env[VAR_ENTORNO] = "1"
    # Sólo el `sitecustomize` en el path, sin `cortafuegos_red` al lado.
    env["PYTHONPATH"] = str(_dir_solo_sitecustomize())
    r = subprocess.run(
        [sys.executable, "-c", "print('VIVO')"],
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
    )
    assert r.returncode == 0, r.stderr[-800:]
    assert r.stdout.strip() == "VIVO"
    assert "Traceback" not in r.stderr, (
        "el sitecustomize dejó un traceback en el arranque del hijo: eso aparece en "
        f"TODO subproceso de la suite.\n{r.stderr[-800:]}"
    )


def _dir_solo_sitecustomize():
    """Copia el ``sitecustomize.py`` a un tmp **sin** su módulo de al lado."""
    import shutil
    import tempfile
    from pathlib import Path

    destino = Path(tempfile.mkdtemp(prefix="t211_"))
    shutil.copy(Path(_cortafuegos.__file__).parent / "sitecustomize.py", destino)
    return destino
