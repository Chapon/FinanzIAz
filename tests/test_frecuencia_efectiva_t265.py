"""Tarea 265 — el desvío ``barrier_eval`` dice la frecuencia EFECTIVA del vivo, no la de la perilla.

El defecto (``docs/auditoria_operacion_2026-10-02.md`` [H-1]): el texto afirmaba *«precio
corriente intradía (scan ~15 min)»* y el comentario *«más cerca de touch»*, por la perilla
``paper_scan_interval_minutes``. El registro (``paper_equity_snapshots``) mostraba 22 de 66 días
hábiles sin ningún scan y 34 sin ninguno en sesión, entre julio y octubre de 2026: esos días el
vivo no evalúa ni al close. La regla de la 233: un número de estado lleva fecha o se deriva.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime

import analysis.harness_config as hc
from analysis.harness_config import cobertura_de_scan, desc_eval_vivo

# Lunes 2026-09-14 a jueves 2026-09-17; el miércoles se declara feriado para el test.
LUN, MAR, MIE, JUE = date(2026, 9, 14), date(2026, 9, 15), date(2026, 9, 16), date(2026, 9, 17)


def test_cuenta_dias_sin_scan_y_sin_scan_EN_SESION():
    snaps = [
        datetime(2026, 9, 14, 15, 0),  # lunes 11:00 NY: en sesión
        datetime(2026, 9, 15, 23, 0),  # martes 19:00 NY: hubo scan, pero fuera de sesión
        # jueves: ninguno
    ]
    c = cobertura_de_scan(snaps, LUN, JUE, feriados={MIE})
    assert c == {"habiles": 3, "sin_scan": 1, "sin_scan_en_sesion": 2}


def test_la_fecha_es_la_de_nueva_york_y_no_la_UTC():
    """02:00 UTC del martes es lunes 22:00 en Nueva York: el martes queda SIN scan.

    Con el rango lunes-martes este caso no distinguía (con o sin conversión daba «1 día sin
    scan», sólo que otro día); por eso el rango es el martes solo.
    """
    assert cobertura_de_scan([datetime(2026, 9, 15, 2, 0)], MAR, MAR)["sin_scan"] == 1


def test_la_SESION_es_la_de_nueva_york():
    """19:00 UTC son las 15:00 en Nueva York: dentro de la sesión (sin convertir, fuera)."""
    assert cobertura_de_scan([datetime(2026, 9, 14, 19, 0)], LUN, LUN)["sin_scan_en_sesion"] == 0


def test_acepta_los_snapshots_como_texto_de_sqlite():
    c = cobertura_de_scan(["2026-09-14 15:00:00.123456"], LUN, LUN)
    assert c == {"habiles": 1, "sin_scan": 0, "sin_scan_en_sesion": 0}


def test_el_texto_lleva_el_numero_y_la_fecha():
    t = desc_eval_vivo(
        {"habiles": 66, "sin_scan": 22, "sin_scan_en_sesion": 34}, "2026-07-01", "2026-10-02", "2026-10-02"
    )
    assert "34 de 66 días hábiles" in t and "medido el 2026-10-02" in t and "no evalúa ni al close" in t
    assert f"~{hc.LIVE_SCAN_INTERVAL_MINUTES} min" in t


def test_el_desvio_usa_la_frecuencia_medida():
    assert (
        desc_eval_vivo(
            hc.SCAN_COBERTURA, hc.SCAN_COBERTURA_DESDE, hc.SCAN_COBERTURA_HASTA, hc.SCAN_COBERTURA_MEDIDA
        )
        == hc.LIVE_EXIT_EVAL_DESC
    )
    assert "no evalúa ni al close" in hc.LIVE_EXIT_EVAL_DESC


def test_el_script_mide_desde_la_db(tmp_path, capsys):
    from scripts.medir_cobertura_de_scan_t265 import main

    db = tmp_path / "f.db"
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE paper_accounts (id INTEGER, is_active INTEGER)")
    c.execute("CREATE TABLE paper_equity_snapshots (account_id INTEGER, snapshot_at TEXT)")
    c.execute("INSERT INTO paper_accounts VALUES (2, 1)")
    c.execute("INSERT INTO paper_equity_snapshots VALUES (2, '2026-09-14 15:00:00')")
    c.commit()
    c.close()
    assert main(["--desde", "2026-09-14", "--hasta", "2026-09-15", "--db", str(db)]) == 0
    out = capsys.readouterr().out
    assert "'habiles': 2" in out and "'sin_scan': 1" in out
