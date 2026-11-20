"""
Con qué código corre la app — **tarea 433**.

La app corre lo que haya en el árbol de trabajo, WIP sin commitear incluido: el 2026-11-11 la
opinión de MU salió del WIP de la 425, con un ``version_datos`` que ``HEAD`` no tenía, y nada
registraba con qué código había salido. Este módulo lo dice: el commit de ``HEAD`` y los ``.py``
modificados o sin trackear. ``main.py`` lo loguea al arrancar, la barra de estado lo avisa si hay
WIP, y cada opinión de Claude lo guarda.

Se toma **una vez por proceso** (:func:`al_arrancar`). Pero un módulo que se importa tarde —el de
la opinión se importa en el primer pedido— carga el árbol de **ese** momento: el 2026-11-20 la opinión
de NVDA salió con la opinión de la 440 y la pestaña del arranque, registrada como el commit del
arranque sin WIP (la 449). Por eso :func:`mezclado` compara el arranque con el árbol de ahora.
Fail-open: sin ``git`` (o fuera de un repo) el commit es ``None`` y no se afirma nada.
"""

from __future__ import annotations

import functools
import subprocess
from dataclasses import dataclass

from config.entorno import ROOT


@dataclass(frozen=True)
class EstadoDelCodigo:
    commit: str | None  # el sha completo de HEAD; None si no se pudo leer
    modificados: tuple[str, ...] = ()  # .py con cambios sin commitear, o sin trackear

    @property
    def wip(self) -> bool:
        return bool(self.modificados)

    @property
    def corto(self) -> str:
        return self.commit[:7] if self.commit else "?"

    def resumen(self, maximo: int = 5) -> str:
        """Una línea para el log y la barra de estado."""
        if not self.wip:
            return f"commit {self.corto}"
        lista = ", ".join(self.modificados[:maximo])
        resto = f" y {len(self.modificados) - maximo} más" if len(self.modificados) > maximo else ""
        return f"commit {self.corto} + WIP sin commitear en {len(self.modificados)} .py ({lista}{resto})"


def _git(root: str, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
        timeout=10,
        # La app no tiene consola: sin esto, cada `git` abre y cierra una ventana negra.
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    ).stdout


def modificados_de_porcelana(salida: str) -> tuple[str, ...]:
    """Los ``.py`` de ``git status --porcelain=v1 -z``: modificados, agregados o sin trackear.

    Con ``-z`` cada entrada termina en NUL y un renombre (``R``/``C``) trae el origen en la
    entrada siguiente, que se saltea. Un ``.py`` borrado no corre: no cuenta.
    """
    out: list[str] = []
    partes = salida.split("\0")
    i = 0
    while i < len(partes):
        entrada = partes[i]
        i += 1
        if len(entrada) < 4:
            continue
        xy, ruta = entrada[:2], entrada[3:]
        if "R" in xy or "C" in xy:
            i += 1
        if "D" in xy or not ruta.endswith(".py"):
            continue
        out.append(ruta)
    return tuple(sorted(set(out)))


def estado_del_codigo(root: str = ROOT) -> EstadoDelCodigo:
    try:
        commit = _git(root, "rev-parse", "HEAD").strip() or None
        porcelana = _git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    except (OSError, subprocess.SubprocessError, UnicodeDecodeError):
        return EstadoDelCodigo(None)
    return EstadoDelCodigo(commit, modificados_de_porcelana(porcelana))


def mezclado(arranque: EstadoDelCodigo, ahora: EstadoDelCodigo) -> bool:
    """¿Cambió el árbol desde que arrancó la app? Entonces lo que se importó después puede ser de
    otro código que el del arranque (la 449). Sin git en alguno de los dos, no se afirma nada."""
    if not arranque.commit or not ahora.commit:
        return False
    return arranque.commit != ahora.commit or arranque.modificados != ahora.modificados


@functools.lru_cache(maxsize=1)
def al_arrancar() -> EstadoDelCodigo:
    """El estado del código de este proceso, tomado la primera vez que se pide."""
    return estado_del_codigo()


def loguear_arranque(log, estado: EstadoDelCodigo) -> None:
    """La línea del arranque: WARNING si hay WIP (lo que corre no pasó por el done), INFO si no."""
    if estado.wip:
        log.warning(
            "FinanzIAs corre WIP sin commitear, que no pasó por el done (tarea 433): %s", estado.resumen()
        )
    else:
        log.info("Código: %s", estado.resumen())
