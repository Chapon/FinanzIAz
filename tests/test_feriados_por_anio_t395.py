"""Tarea 395 — el script de cobertura de scan no mide un año sin feriados NYSE cargados.

Tenía escritos los de 2026, con ``--hasta`` = hoy: desde el 1/1/2027 cada feriado de 2027 habría
contado como un día hábil sin scan, en silencio.
"""

from __future__ import annotations

from datetime import date

import pytest

from scripts import medir_cobertura_de_scan_t265 as m


def test_con_mlk_2027_se_niega_y_dice_que_falta(capsys, tmp_path):
    rc = m.main(["--desde", "2026-12-01", "--hasta", "2027-01-20", "--db", str(tmp_path / "no.db")])
    assert rc == 2
    err = capsys.readouterr().err
    assert "2027" in err and "feriados" in err


def test_feriados_para_un_rango_de_2026():
    f = m.feriados_para("2026-07-01", "2026-11-30")
    assert date(2026, 11, 26) in f and date(2026, 1, 19) in f


def test_feriados_para_un_anio_sin_cargar():
    with pytest.raises(ValueError, match="2027"):
        m.feriados_para("2026-12-01", "2027-01-20")


def test_los_cargados_son_los_de_2026():
    assert set(m.FERIADOS_NYSE) == {2026} and len(m.FERIADOS_NYSE[2026]) == 10
