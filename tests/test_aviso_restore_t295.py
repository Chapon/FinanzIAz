"""Tarea 295 — el restore programado avisa en pantalla si se aplicó o falló.

``docs/auditoria_tanda_2026-10-03.md`` [H-1]: ``main.py`` descartaba el resultado de
``apply_pending_restore`` y el éxito y la falla iban sólo al log. Chapa pedía volver a un
backup, reiniciaba y no tenía cómo saber sobre qué base había arrancado.

Los casos de falla están elegidos para que **difieran entre sí** y del éxito: el backup
que desaparece y el que se rompe fallan antes de copiar (la base no se tocó); la copia
que falla deja la base posiblemente a medias, y el aviso no puede decir lo mismo.
"""

from __future__ import annotations

import ast
import sqlite3
from pathlib import Path

import pytest

pytest.importorskip("PyQt6.QtWidgets")

import database.backup as bk
import ui.aviso_restore as aviso


@pytest.fixture
def live(tmp_path, monkeypatch):
    live = tmp_path / "finanzias.db"
    monkeypatch.setattr(bk, "DB_PATH", str(live))
    monkeypatch.setattr(bk, "DB_DIR", tmp_path)
    monkeypatch.setattr(bk, "BACKUP_DIR", tmp_path / "backups")
    monkeypatch.setattr(bk, "DB_STEM", live.stem)
    _base(live, 3)
    return live


@pytest.fixture
def mostrados(monkeypatch):
    vistos: list[tuple[str, str, str]] = []
    monkeypatch.setattr(aviso.QMessageBox, "information", lambda p, t, x: vistos.append(("info", t, x)))
    monkeypatch.setattr(aviso.QMessageBox, "critical", lambda p, t, x: vistos.append(("error", t, x)))
    return vistos


def _base(path: Path, n: int) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(path))
    c.execute("CREATE TABLE t (id INTEGER PRIMARY KEY)")
    c.executemany("INSERT INTO t DEFAULT VALUES", [()] * n)
    c.commit()
    c.close()
    return path


def _programado(live: Path) -> Path:
    backup = _base(live.parent / "backups" / "finanzias_2026-10-01_10-00-00_daily.db", 10)
    assert bk.schedule_restore(backup)
    return backup


def test_APLICADO_avisa_con_el_nombre_del_backup(live, mostrados):
    backup = _programado(live)
    resultado = bk.apply_pending_restore()
    aviso.mostrar_resultado_del_restore(None, resultado)

    assert [m[0] for m in mostrados] == ["info"]
    assert backup.name in mostrados[0][2]


def test_backup_que_DESAPARECIO_avisa_error_y_que_la_base_no_se_toco(live, mostrados):
    _programado(live).unlink()
    resultado = bk.apply_pending_restore()
    aviso.mostrar_resultado_del_restore(None, resultado)

    assert resultado.aplicado is False and resultado.base_intacta is True
    assert "ya no existe" in resultado.motivo
    tipo, titulo, texto = mostrados[0]
    assert tipo == "error" and "FALLÓ" in titulo
    assert "no se tocó" in texto


def test_backup_que_se_ROMPIO_despues_de_programar_avisa_otro_motivo(live, mostrados):
    _programado(live).write_bytes(b"esto ya no es una base sqlite" * 100)
    resultado = bk.apply_pending_restore()

    assert resultado.aplicado is False and resultado.base_intacta is True
    assert "integridad" in resultado.motivo


def test_falla_DE_LA_COPIA_no_afirma_que_la_base_quedo_intacta(live, mostrados, monkeypatch):
    _programado(live)
    monkeypatch.setattr(bk, "restore_database", lambda b: False)
    resultado = bk.apply_pending_restore()
    aviso.mostrar_resultado_del_restore(None, resultado)

    assert resultado.aplicado is False and resultado.base_intacta is False
    texto = mostrados[0][2]
    assert "no se tocó" not in texto
    assert "a medias" in texto


def test_sin_restore_programado_no_se_muestra_nada(live, mostrados):
    aviso.mostrar_resultado_del_restore(None, bk.apply_pending_restore())
    assert mostrados == []


def test_main_GUARDA_el_resultado_y_lo_muestra_despues_de_abrir_la_ventana():
    """Lo que faltaba era esto: el resultado se calculaba y se tiraba."""
    src = (Path(__file__).resolve().parent.parent / "main.py").read_text(encoding="utf-8")
    fn = next(n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.FunctionDef) and n.name == "main")

    asignado = [
        n.targets[0].id
        for n in ast.walk(fn)
        if isinstance(n, ast.Assign)
        and isinstance(n.value, ast.Call)
        and getattr(n.value.func, "id", None) == "apply_pending_restore"
    ]
    assert len(asignado) == 1, "main.py no guarda el resultado de apply_pending_restore"

    muestra = [
        n
        for n in ast.walk(fn)
        if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "mostrar_resultado_del_restore"
    ]
    assert len(muestra) == 1
    assert [getattr(a, "id", None) for a in muestra[0].args][1] == asignado[0]

    show = min(
        n.lineno for n in ast.walk(fn) if isinstance(n, ast.Call) and getattr(n.func, "attr", None) == "show"
    )
    assert muestra[0].lineno > show, "el aviso tiene que salir con la ventana ya abierta"
