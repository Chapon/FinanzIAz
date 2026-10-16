"""Tarea 361 — el build del recolector verifica el zip que dejó, y pip no imprime un ERROR que no es.

En el despliegue de la 355 hubo que abrir el zip a mano para ver que no tuviera ``.pyd`` y
que estuvieran los paquetes; y pip imprimía «ERROR: pip's dependency resolver …» por
comparar lo bajado para Linux contra la Anaconda de Chapa.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts import build_recolector_nube as b

VERSIONES = {"yfinance": "1.4.1", "curl_cffi": "0.15.0"}


def _deps(tmp_path: Path, *, pyd: bool = False, so: bool = True, falta: str | None = None) -> Path:
    d = tmp_path / "pkg"
    for paquete, version in VERSIONES.items():
        if paquete == falta:
            continue
        info = d / f"{paquete}-{version}.dist-info"
        info.mkdir(parents=True)
        (info / "METADATA").write_text("x", encoding="utf-8")
    ext = d / "curl_cffi"
    ext.mkdir(parents=True, exist_ok=True)
    if so:
        (ext / "_wrapper.abi3.so").write_bytes(b"\x7fELF")
    if pyd:
        (ext / "_wrapper.pyd").write_bytes(b"MZ")
    return d


def _zip(tmp_path, **kw) -> Path:
    out = tmp_path / "r.zip"
    b.armar_zip(_deps(tmp_path, **kw), out, version="test")
    return out


def test_un_zip_bien_armado_no_tiene_problemas(tmp_path):
    assert b.verificar_zip(_zip(tmp_path), VERSIONES) == []


def test_un_zip_con_un_PYD_se_rechaza(tmp_path):
    problemas = b.verificar_zip(_zip(tmp_path, pyd=True), VERSIONES)
    assert len(problemas) == 1 and ".pyd" in problemas[0]


def test_un_zip_sin_SO_se_rechaza(tmp_path):
    assert any("ningún .so" in p for p in b.verificar_zip(_zip(tmp_path, so=False), VERSIONES))


def test_un_paquete_que_falta_o_en_otra_version_se_rechaza(tmp_path):
    assert b.verificar_zip(_zip(tmp_path, falta="yfinance"), VERSIONES) == ["falta yfinance==1.4.1"]
    otra = {**VERSIONES, "curl_cffi": "0.16.0"}
    assert b.verificar_zip(_zip(tmp_path / "otra"), otra) == ["falta curl_cffi==0.16.0"]


def test_un_archivo_del_repo_que_falta_se_rechaza(tmp_path, monkeypatch):
    out = _zip(tmp_path)
    monkeypatch.setitem(b.ARCHIVOS_DEL_REPO, "data/otro.py", Path("no-existe"))
    assert b.verificar_zip(out, VERSIONES) == ["falta data/otro.py"]


def test_main_falla_si_el_zip_esta_mal(tmp_path, monkeypatch, capsys):
    """El chequeo corta el build, no sólo imprime."""

    def _pip_falso(cmd, check):
        assert "--no-warn-conflicts" in cmd  # el flag que saca el ERROR de pip
        destino = Path(cmd[cmd.index("--target") + 1])
        for paquete, version in VERSIONES.items():
            (destino / f"{paquete}-{version}.dist-info").mkdir(parents=True)
        (destino / "_wrapper.pyd").write_bytes(b"MZ")

    monkeypatch.setattr(b, "pinned_versions", lambda texto, paquetes: dict(VERSIONES))
    monkeypatch.setattr(b.subprocess, "run", _pip_falso)
    monkeypatch.setattr(b, "_git_version", lambda: "test")

    rc = b.main(["--out", str(tmp_path / "r.zip")])

    assert rc == 1
    assert "ZIP MAL ARMADO" in capsys.readouterr().err


@pytest.mark.parametrize("nombre", ["Requests-2.34.2.dist-info", "requests-2.34.2.dist-info"])
def test_el_nombre_del_dist_info_se_normaliza(tmp_path, nombre):
    d = tmp_path / "pkg" / nombre
    d.mkdir(parents=True)
    (d / "METADATA").write_text("x", encoding="utf-8")  # un dir vacío no entra al zip
    (tmp_path / "pkg" / "x.so").write_bytes(b"\x7fELF")
    out = tmp_path / "r.zip"
    b.armar_zip(tmp_path / "pkg", out, version="test")
    assert b.verificar_zip(out, {"requests": "2.34.2"}) == []
