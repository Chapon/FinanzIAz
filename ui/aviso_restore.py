"""Aviso del restore programado al abrir la ventana (tarea 295).

El restore se aplica en ``main.py`` antes de abrir la base, cuando todavía no hay
ventana; el resultado se guarda y se muestra acá, una vez que la ventana está a la vista.
Sin esto el éxito y la falla quedaban sólo en el log, que no se lee (la lección de la
197 y la 234).
"""

from __future__ import annotations

from PyQt6.QtWidgets import QMessageBox, QWidget

from database.backup import RestoreAlArrancar


def mostrar_resultado_del_restore(parent: QWidget | None, resultado: RestoreAlArrancar | None) -> None:
    """Nada si no había restore programado; información si se aplicó; error si falló."""
    if resultado is None:
        return
    titulo, texto = resultado.aviso()
    if resultado.aplicado:
        QMessageBox.information(parent, titulo, texto)
    else:
        QMessageBox.critical(parent, titulo, texto)
