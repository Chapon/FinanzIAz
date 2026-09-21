"""El cortafuegos de red en un **subproceso** de la suite (tarea 211).

``site.py`` importa ``sitecustomize`` al arrancar **cualquier** intérprete, antes de
ejecutar nada del programa. Este directorio se agrega a ``PYTHONPATH`` desde
``tests/conftest.py``, y el entorno es lo único que un proceso hijo hereda solo — el
mismo argumento que la **108** usó para ``FINANZIAS_DB_PATH`` y la **148** para
``FINANZIAS_DISABLE_SLACK``.

**No hace nada salvo que la variable esté puesta.** Un intérprete que arranque con este
directorio en el path pero sin ``FINANZIAS_BLOQUEAR_RED`` sale intacto, que es lo que
permite que un test marcado ``network`` deje salir también a sus hijos: el fixture le
borra la variable y el hijo la hereda ausente.

**Y no puede levantar, nunca.** ``site.py`` corre esto durante el arranque del
intérprete: una excepción acá imprime un traceback en TODO proceso hijo de la suite y
ensucia la salida de tests que no tienen nada que ver. Por eso el cuerpo entero va en un
``try`` mudo — un cortafuegos que no se pudo instalar es un hueco, no un fallo del
programa que lo hospeda, y el que lo detecta es el test de la 211.

**Cuidado si alguna vez aparece otro ``sitecustomize``.** El intérprete importa **uno
solo**: el primero del ``sys.path``. Hoy no hay ninguno —verificado el 2026-09-20 en el
`.venv` y en el Anaconda—, pero si un paquete instala el suyo, éste lo tapa o queda
tapado según el orden. Si pasa, el arreglo es encadenar (importar el otro por ruta) y no
borrar éste.
"""

try:
    import os

    if os.environ.get("FINANZIAS_BLOQUEAR_RED"):
        from cortafuegos_red import instalar

        # `setattr` pelado y no `monkeypatch`: el hijo es un proceso de un solo uso, así
        # que no hay nada que deshacer. La lógica del corte es la MISMA función que usa
        # el fixture del padre — ver el docstring de `cortafuegos_red.instalar`.
        instalar(setattr)
except Exception:  # pragma: no cover — ver el docstring: acá no se puede levantar
    pass
