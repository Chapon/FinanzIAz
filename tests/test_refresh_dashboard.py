"""Tests del refresh in-app del dashboard (trigger 7 del PaperScheduler).

El snapshot se regenera 1×/día al abrir + tras cada scan (decisión "Ambos",
Chapa 2026-07-12), reemplazando la tarea del Windows Task Scheduler que corría
``refresh_dashboard.py`` a las 8:00. Acá se testea la inyección de ``const
DATA`` y los guards de targets, sin red ni DB real (``build_payload`` mockeado).
"""

from pathlib import Path

import pytest

import scripts.refresh_dashboard as rd

ARTIFACT_HTML = """<html>
<script>
const DATA = {"old": true};
</script>
</html>
"""


@pytest.fixture
def fake_targets(tmp_path, monkeypatch):
    """DB + artifact en tmp; ``build_payload`` mockeado (no pega a la DB real)."""
    db = tmp_path / "finanzias.db"
    db.write_text("", encoding="utf-8")
    artifact = tmp_path / "index.html"
    artifact.write_text(ARTIFACT_HTML, encoding="utf-8")
    monkeypatch.setattr(
        rd,
        "build_payload",
        lambda db_path, account_id: {
            "positions": [1, 2, 3],
            "generated_at": "2026-07-12T10:00:00",
        },
    )
    # El snapshot de respaldo va a tmp, no al repo.
    monkeypatch.setattr(rd, "REPO", tmp_path)
    return db, artifact


def test_targets_ready_true_when_both_exist(fake_targets):
    db, artifact = fake_targets
    assert rd.targets_ready(artifact=artifact, db_path=db) is True


def test_targets_ready_false_without_artifact(tmp_path):
    db = tmp_path / "finanzias.db"
    db.write_text("", encoding="utf-8")
    assert rd.targets_ready(artifact=tmp_path / "nope.html", db_path=db) is False


def test_targets_ready_false_without_db(tmp_path):
    artifact = tmp_path / "index.html"
    artifact.write_text(ARTIFACT_HTML, encoding="utf-8")
    assert rd.targets_ready(artifact=artifact, db_path=tmp_path / "no.db") is False


def test_refresh_injects_data_line(fake_targets):
    db, artifact = fake_targets
    res = rd.refresh_dashboard(artifact=artifact, account_id=1, db_path=db)
    assert res["ok"] is True
    assert res["positions"] == 3
    assert res["generated_at"] == "2026-07-12T10:00:00"

    html = artifact.read_text(encoding="utf-8")
    assert '"positions": [1, 2, 3]' in html  # snapshot nuevo inyectado
    assert '{"old": true}' not in html  # la línea vieja se reemplazó
    # Snapshot de respaldo escrito al lado del repo (tmp en el test).
    assert (Path(res["artifact"])).exists()
    assert (db.parent / "dashboard_snapshot.json").exists()


def test_refresh_missing_artifact_is_not_fatal(tmp_path):
    db = tmp_path / "finanzias.db"
    db.write_text("", encoding="utf-8")
    res = rd.refresh_dashboard(artifact=tmp_path / "nope.html", account_id=1, db_path=db)
    assert res["ok"] is False
    assert "artifact" in res["reason"]


def test_refresh_missing_db_is_not_fatal(tmp_path):
    res = rd.refresh_dashboard(artifact=tmp_path / "x.html", db_path=tmp_path / "no.db")
    assert res["ok"] is False
    assert "DB" in res["reason"]


def test_refresh_no_data_line_is_not_fatal(tmp_path, monkeypatch):
    db = tmp_path / "finanzias.db"
    db.write_text("", encoding="utf-8")
    artifact = tmp_path / "index.html"
    original = "<html>sin línea DATA</html>"
    artifact.write_text(original, encoding="utf-8")
    monkeypatch.setattr(rd, "build_payload", lambda db_path, account_id: {"positions": []})
    monkeypatch.setattr(rd, "REPO", tmp_path)

    res = rd.refresh_dashboard(artifact=artifact, db_path=db)
    assert res["ok"] is False
    assert "esperaba 1" in res["reason"]
    assert artifact.read_text(encoding="utf-8") == original  # no lo tocó
