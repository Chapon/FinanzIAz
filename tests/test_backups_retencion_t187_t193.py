"""Tareas 187 (política de backups sueltos) y 193 (la rotación se comía los diarios).

**187 — decisión de Chapa (2026-09-12):** los backups sueltos `.db` se conservan **30 días**
desde la fecha de su nombre; lo que no es `.db` (`settings_pre_*.json`, `pit_*.json`) es
evidencia y **no se toca nunca**.

**193 — lo que apareció al aplicarla.** `rotate_backups(keep=7)` contaba **todos** los
`finanzias_*.db` y borraba los primeros **por orden alfabético**. `finanzias_2026-…` ordena antes
que `finanzias_pre_…`, así que la rotación borraba **diarios** para hacerles lugar a los sueltos:
con los 5 sueltos que había en `backups/`, quedaban **2** diarios —exactamente lo que había— y
con 7, el daily que la app crea al arrancar **se borraba en el mismo arranque**.

**Por qué los tests de la 143 no lo veían:** creaban los backups con `reason=f"r{i}"`, una sola
población. El defecto necesita las dos mezcladas, que es lo que arma cada test de acá.
"""

from __future__ import annotations

from datetime import date

import pytest

import database.backup as bk

HOY = date(2026, 9, 12)

SUELTOS_DE_HOY = [
    "finanzias_pre_e5_20260701_035340.db",  # 73 días
    "finanzias_pre_0007_20260709_205753.db",  # 65 días
    "finanzias_post_t77_20260902_142641.db",  # 10 días
    "finanzias_pre_t81_20260902_140200.db",
    "finanzias_pre_manuales_20260907.db",
]
EVIDENCIA = ["settings_pre_soff_t2.0_20260827_195731.json", "pit_AVB__10y__w250_pre_t156_20260910.json"]


@pytest.fixture
def dir_backups(tmp_path, monkeypatch):
    d = tmp_path / "backups"
    d.mkdir()
    monkeypatch.setattr(bk, "BACKUP_DIR", d)
    monkeypatch.setattr(bk, "DB_STEM", "finanzias")
    return d


def _crear(d, nombres):
    for n in nombres:
        (d / n).write_bytes(b"x")


def _diarios(n: int, desde: int = 1) -> list[str]:
    return [f"finanzias_2026-09-{dia:02d}_10-00-00_daily.db" for dia in range(desde, desde + n)]


# ── 193: la rotación cuenta sólo los diarios ────────────────────────────────


def test_con_los_sueltos_de_hoy_quedan_SIETE_diarios_y_ningun_suelto_borrado(dir_backups):
    """El caso medido: antes quedaban 2 diarios."""
    _crear(dir_backups, SUELTOS_DE_HOY + _diarios(9))

    assert bk.rotate_backups(keep=7) == 2
    assert [p.name for p in bk.list_daily_backups()] == _diarios(7, desde=3)
    assert all((dir_backups / n).exists() for n in SUELTOS_DE_HOY)


def test_con_SIETE_sueltos_el_daily_de_hoy_sobrevive_a_su_propio_arranque(dir_backups):
    """El peor caso de la 193: con 7 sueltos, el daily recién creado era el primero en irse."""
    _crear(dir_backups, [*SUELTOS_DE_HOY, "finanzias_pre_x_20260910.db", "finanzias_pre_y_20260911.db"])
    hoy = _diarios(1, desde=12)[0]
    _crear(dir_backups, [hoy])

    bk.rotate_backups(keep=7)

    assert (dir_backups / hoy).exists()


def test_los_backups_de_la_UI_no_son_diarios(dir_backups):
    """`backup_database(reason=…)` escribe `finanzias_<ts>_<reason>.db`: los de la UI
    (`manual`, `pre-delete-account`) comparten el prefijo fechado con los diarios y NO son
    diarios. Rotarlos juntos era parte del defecto."""
    ui = ["finanzias_2026-09-01_09-00-00_manual.db", "finanzias_2026-09-01_09-00-01_pre-delete-account.db"]
    _crear(dir_backups, ui + _diarios(8))

    assert bk.rotate_backups(keep=7) == 1
    assert all((dir_backups / n).exists() for n in ui)


# ── 187: los sueltos vencen a los 30 días, por la fecha del nombre ──────────


def test_con_el_directorio_de_hoy_vencen_EXACTAMENTE_pre_e5_y_pre_0007(dir_backups):
    """La decisión aplicada al estado real del 2026-09-12."""
    _crear(dir_backups, SUELTOS_DE_HOY + EVIDENCIA + _diarios(2, desde=11))

    borrados = bk.prune_adhoc_backups(today=HOY)

    assert sorted(p.name for p in borrados) == sorted(SUELTOS_DE_HOY[:2])
    quedan = {p.name for p in dir_backups.iterdir()}
    assert set(SUELTOS_DE_HOY[2:]) | set(EVIDENCIA) | set(_diarios(2, desde=11)) == quedan


def test_la_poda_NUNCA_toca_un_diario_aunque_sea_viejo(dir_backups):
    viejos = ["finanzias_2026-01-01_10-00-00_daily.db"]
    _crear(dir_backups, viejos)
    assert bk.prune_adhoc_backups(today=HOY) == []
    assert (dir_backups / viejos[0]).exists()


def test_la_poda_NUNCA_toca_la_evidencia_que_no_es_db(dir_backups):
    viejos = ["settings_pre_algo_20250101.json", "pit_X__10y__w250_pre_t1_20250101.json"]
    _crear(dir_backups, viejos)
    assert bk.prune_adhoc_backups(today=HOY) == []
    assert all((dir_backups / n).exists() for n in viejos)


def test_un_nombre_sin_fecha_legible_se_CONSERVA(dir_backups):
    raros = ["finanzias_pre_sin_fecha.db", "finanzias_pre_20261399.db"]  # el segundo no es una fecha
    _crear(dir_backups, raros)
    assert bk.prune_adhoc_backups(today=HOY) == []


def test_la_edad_sale_del_NOMBRE_y_no_del_mtime(dir_backups):
    """El mtime de un backup no es su edad: el smoke test de la suite abría backups y les movía
    la fecha (tarea 188). Un suelto de julio tocado hoy sigue vencido."""
    import os
    import time

    viejo = dir_backups / "finanzias_pre_e5_20260701_035340.db"
    viejo.write_bytes(b"x")
    ahora = time.time()
    os.utime(viejo, (ahora, ahora))

    assert bk.adhoc_backups_vencidos(today=HOY) == [viejo]


@pytest.mark.parametrize(("dias", "vence"), [(30, False), (31, True)])
def test_el_borde_de_los_30_dias(dir_backups, dias, vence):
    from datetime import timedelta

    fecha = (HOY - timedelta(days=dias)).strftime("%Y%m%d")
    _crear(dir_backups, [f"finanzias_pre_borde_{fecha}.db"])
    assert bool(bk.adhoc_backups_vencidos(today=HOY)) is vence


def test_la_poda_se_lleva_los_side_files(dir_backups):
    base = "finanzias_pre_e5_20260701_035340.db"
    _crear(dir_backups, [base, base + "-wal", base + "-shm"])
    bk.prune_adhoc_backups(today=HOY)
    assert list(dir_backups.iterdir()) == []


def test_el_arranque_de_la_app_rota_Y_poda(dir_backups, monkeypatch):
    """La política corre donde corre la rotación: en `maybe_rotate_daily`, al abrir la app. Si
    sólo existiera la función, los backups de la UI —que hasta la 193 rotaban de rebote— se
    acumularían sin techo."""
    llamadas = []
    monkeypatch.setattr(bk, "_today_already_backed_up", lambda: True)
    monkeypatch.setattr(bk, "rotate_backups", lambda keep: llamadas.append(("rotar", keep)))
    monkeypatch.setattr(bk, "prune_adhoc_backups", lambda *a, **k: llamadas.append(("podar",)) or [])

    bk.maybe_rotate_daily(keep=7)

    assert llamadas == [("rotar", 7), ("podar",)]
