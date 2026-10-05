"""Tarea 318 — cada job del CI tiene techo de tiempo, y ``check_ci.py --sha`` resuelve un sha abreviado.

Lo que pasó (2026-10-05): el job `pytest` de `ecc1a07` tardó 21 min contra ~4, y `ci.yml` no
declaraba `timeout-minutes` en ningún job (el default de GitHub es 6 h: un cuelgue deja el run
sin veredicto). Y `--sha ecc1a07` respondió *«no hay ningún run»* porque la API compara contra el
sha completo.

Sin `yaml`: PyYAML no está en `requirements`, y este test corre también en el CI.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from scripts import check_ci as cc

_CI = Path(__file__).resolve().parent.parent / ".github" / "workflows" / "ci.yml"


def jobs_y_techo(texto: str) -> dict[str, int | None]:
    """``{job: timeout-minutes}`` de los jobs bajo ``jobs:`` (dos espacios de sangría)."""
    cuerpo = texto.split("\njobs:\n", 1)[1]
    out: dict[str, int | None] = {}
    actual = None
    for linea in cuerpo.splitlines():
        if m := re.match(r"^  ([A-Za-z][\w-]*):\s*$", linea):
            actual = m.group(1)
            out[actual] = None
        elif actual and (m := re.match(r"^    timeout-minutes:\s*(\d+)", linea)):
            out[actual] = int(m.group(1))
    return out


def test_cada_job_del_CI_tiene_techo_de_tiempo():
    techos = jobs_y_techo(_CI.read_text(encoding="utf-8"))
    assert set(techos) >= {"lint", "typecheck", "audit", "tests"}, techos
    assert all(v for v in techos.values()), (
        f"jobs sin timeout-minutes: {[k for k, v in techos.items() if not v]}"
    )


def test_el_techo_de_pytest_deja_margen_sobre_el_run_mas_lento_medido():
    """21 min el 2026-10-05, en verde: un techo de 20 lo habría matado."""
    assert jobs_y_techo(_CI.read_text(encoding="utf-8"))["tests"] > 21


def test_CONTROL_el_parser_ve_un_job_sin_techo():
    texto = "on:\n  push:\njobs:\n  a:\n    runs-on: x\n    timeout-minutes: 5\n  b:\n    runs-on: x\n"
    assert jobs_y_techo(texto) == {"a": 5, "b": None}


def _main_con(monkeypatch, argv):
    completo = "e" * 40
    vistos: list = []

    def git(*args):
        if args[:2] == ("remote", "get-url"):
            return "https://github.com/dueno/repo.git"
        if args[:2] == ("rev-parse", "--verify"):
            if args[2].startswith("eeeeeee"):
                return completo
            raise subprocess.CalledProcessError(128, "git")
        raise AssertionError(args)

    monkeypatch.setattr(cc, "_git", git)
    monkeypatch.setattr(cc, "consultar", lambda repo, sha, **kw: vistos.append(sha) or cc.VERDE)
    return cc.main(argv), vistos, completo


def test_un_sha_ABREVIADO_se_consulta_completo(monkeypatch):
    rc, vistos, completo = _main_con(monkeypatch, ["--sha", "eeeeeee"])
    assert rc == cc.VERDE and vistos == [completo]


def test_un_sha_que_no_existe_es_no_se_sabe(monkeypatch, capsys):
    rc, vistos, _ = _main_con(monkeypatch, ["--sha", "zzzz"])
    assert rc == cc.NO_SE_SABE and vistos == [] and "no es un commit" in capsys.readouterr().out
