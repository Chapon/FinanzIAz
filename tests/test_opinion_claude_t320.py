"""Tarea 320 — opinión de Claude en la pestaña Análisis, vía Claude Code con la suscripción.

Sin red y sin Claude: el ``runner`` es falso. Lo que se fija:
* el comando va AISLADO (sin herramientas, sin MCP, sin sesión, con prompt propio, sin ``--bare``,
  que exige una API key) y corre FUERA del repo (si no, Claude Code carga el ``CLAUDE.md``);
* ningún caso dudoso se presenta como opinión: sin Claude Code, demora, salida no-JSON, error del
  CLI o una respuesta fuera del esquema → ``OpinionError`` con el motivo;
* no se manda la posición del usuario;
* el registro es uno por ticker y día (para medir sin contar dos veces), y el texto de Claude se
  escapa antes de pintarlo.
"""

from __future__ import annotations

import json
import subprocess
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from analysis import opinion_claude as oc

_REPO = Path(__file__).resolve().parent.parent

_BUENA = {
    "recomendacion": "MANTENER",
    "confianza": 40,
    "tesis": "Tendencia alcista de fondo con momentum agotándose.",
    "riesgos": ["Volatilidad alta"],
    "cambiaria_opinion": ["Que supere la resistencia"],
    "datos_faltantes": [],
}


def _salida(op=None, **extra) -> str:
    d = {"type": "result", "subtype": "success", "is_error": False, "result": "", "structured_output": op}
    d.update(extra)
    return json.dumps(d)


class _Runner:
    def __init__(self, stdout="", returncode=0, stderr="", exc=None):
        self.stdout, self.returncode, self.stderr, self.exc = stdout, returncode, stderr, exc
        self.llamadas: list[dict] = []

    def __call__(self, cmd, **kw):
        self.llamadas.append({"cmd": cmd, **kw})
        if self.exc:
            raise self.exc
        return SimpleNamespace(stdout=self.stdout, stderr=self.stderr, returncode=self.returncode)


def _df(n=300):
    idx = pd.bdate_range("2025-06-02", periods=n)
    close = pd.Series(np.linspace(100, 160, n), index=idx)
    return pd.DataFrame(
        {"Open": close, "High": close * 1.01, "Low": close * 0.99, "Close": close, "Volume": 1e6}
    )


# ── El comando ───────────────────────────────────────────────────────────────


def test_el_comando_va_aislado():
    cmd = oc.comando("claude.exe")
    assert cmd[:2] == ["claude.exe", "-p"]
    i = cmd.index("--tools")
    assert cmd[i + 1] == "", "sin herramientas: opina sólo con los datos"
    for flag in ("--strict-mcp-config", "--no-session-persistence", "--system-prompt", "--json-schema"):
        assert flag in cmd
    assert cmd[cmd.index("--output-format") + 1] == "json"
    assert json.loads(cmd[cmd.index("--json-schema") + 1]) == oc.ESQUEMA
    assert cmd[cmd.index("--model") + 1] == oc.MODELO
    assert "--bare" not in cmd, "--bare exige ANTHROPIC_API_KEY: no usa la suscripción"


def test_corre_FUERA_del_repo_y_manda_los_datos_por_stdin():
    r = _Runner(stdout=_salida(_BUENA))
    oc.pedir_opinion({"ticker": "MU", "precio": 1063.0}, exe="claude.exe", runner=r)
    llamada = r.llamadas[0]
    cwd = Path(llamada["cwd"]).resolve()
    assert _REPO not in cwd.parents and cwd != _REPO
    assert '"ticker": "MU"' in llamada["input"]


def test_una_respuesta_valida_es_una_opinion():
    op = oc.pedir_opinion({"ticker": "MU"}, exe="x", runner=_Runner(stdout=_salida(_BUENA)))
    assert (op.recomendacion, op.confianza, op.modelo) == ("MANTENER", 40, oc.MODELO)


# ── Ningún caso dudoso es una opinión ────────────────────────────────────────


def test_sin_claude_code_lo_dice(monkeypatch):
    monkeypatch.setattr(oc, "ubicar_claude", lambda: None)
    with pytest.raises(oc.OpinionError, match="No se encontró Claude Code"):
        oc.pedir_opinion({}, runner=_Runner())


@pytest.mark.parametrize(
    "runner,motivo",
    [
        (_Runner(exc=subprocess.TimeoutExpired("claude", 1)), "no respondió"),
        (_Runner(exc=FileNotFoundError("claude.exe")), "No se pudo ejecutar"),
        (_Runner(stdout="no es json", returncode=1, stderr="boom"), "no devolvió JSON"),
        (_Runner(stdout=_salida(_BUENA, is_error=True, result="sin cuota")), "sin cuota"),
        (_Runner(stdout=_salida(_BUENA), returncode=2), "error"),
        (_Runner(stdout=_salida(None)), "formato pedido"),
        (_Runner(stdout=_salida({**_BUENA, "recomendacion": "HOLD"})), "Recomendación inválida"),
        (_Runner(stdout=_salida({**_BUENA, "confianza": 150})), "Confianza inválida"),
        (_Runner(stdout=_salida({**_BUENA, "tesis": "  "})), "sin tesis"),
        (_Runner(stdout=_salida({**_BUENA, "riesgos": "uno solo"})), "riesgos"),
    ],
)
def test_lo_dudoso_es_OpinionError(runner, motivo):
    with pytest.raises(oc.OpinionError, match=motivo):
        oc.pedir_opinion({}, exe="x", runner=runner)


# ── Los datos ────────────────────────────────────────────────────────────────


def test_los_datos_traen_el_analisis_y_NO_la_posicion():
    from analysis.technical import analyze

    df = _df()
    res = analyze("TST", df, enable_xgboost=False)
    datos = oc.armar_datos(
        "tst",
        df,
        res,
        {"name": "Test Inc", "sector": "Tech"},
        {"recommendations": [{"period": "0m"}], "price_targets": {"mean": 170}},
        [{"titulo": "x"}] * 40,
        {"support": 150, "resistance": 165},
    )
    assert datos["ticker"] == "TST" and datos["precio"] == pytest.approx(160.0)
    assert {i["indicador"] for i in datos["indicadores"]} >= {"RSI", "MACD"}
    assert datos["retornos_pct"]["20d"] is not None and datos["soporte"] == 150
    assert len(datos["noticias"]) == oc.MAX_NOTICIAS
    texto = json.dumps(datos).lower()
    for prohibido in ("shares", "acciones_en_cartera", "avg_cost", "posicion", "cantidad"):
        assert prohibido not in texto, f"se mandaría la posición del usuario: {prohibido}"


# ── El ejecutable ────────────────────────────────────────────────────────────


def test_ubicar_claude_prefiere_la_variable_y_si_no_la_extension_mas_nueva(tmp_path, monkeypatch):
    monkeypatch.setattr(oc.shutil, "which", lambda name: None)
    monkeypatch.setattr(oc.Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.delenv("FINANZIAS_CLAUDE_EXE", raising=False)
    assert oc.ubicar_claude() is None
    for v in ("2.1.9", "2.1.289", "2.0.500"):
        d = (
            tmp_path
            / ".vscode"
            / "extensions"
            / f"anthropic.claude-code-{v}-win32-x64"
            / "resources"
            / "native-binary"
        )
        d.mkdir(parents=True)
        (d / "claude.exe").write_text("")
    assert "2.1.289" in oc.ubicar_claude(), "por versión, no alfabético (2.1.9 < 2.1.289)"
    propio = tmp_path / "mio.exe"
    propio.write_text("")
    monkeypatch.setenv("FINANZIAS_CLAUDE_EXE", str(propio))
    assert oc.ubicar_claude() == str(propio)


# ── El registro ──────────────────────────────────────────────────────────────


def _op(rec="MANTENER", conf=40):
    return oc.Opinion(rec, conf, "tesis", ["r"], ["c"], [], oc.MODELO, 12.3)


def test_una_por_ticker_y_dia_y_se_recupera(test_db):
    from database.models import ClaudeOpinion, session_scope

    hoy, ayer = date(2026, 10, 5), date(2026, 10, 4)
    oc.guardar("mu", _op("COMPRAR", 70), {"precio": 1000.0}, hoy=ayer)
    oc.guardar("MU", _op("MANTENER", 40), {"precio": 1063.0}, hoy=hoy)
    oc.guardar("MU", _op("VENDER", 55), {"precio": 1050.0}, hoy=hoy)  # pedirla de nuevo: reemplaza
    with session_scope() as s:
        filas = s.query(ClaudeOpinion).order_by(ClaudeOpinion.fecha).all()
        assert [(f.fecha, f.recomendacion, f.precio) for f in filas] == [
            ("2026-10-04", "COMPRAR", 1000.0),
            ("2026-10-05", "VENDER", 1050.0),
        ]
        assert json.loads(filas[1].datos_json) == {"precio": 1050.0}
    op, _cuando = oc.opinion_de_hoy("mu", hoy=hoy)
    assert (op.recomendacion, op.confianza) == ("VENDER", 55)
    assert oc.opinion_de_hoy("MU", hoy=date(2026, 10, 6)) is None


# ── La tarjeta ───────────────────────────────────────────────────────────────


def test_el_texto_de_claude_se_escapa():
    from ui.analysis.opinion_card import html_de

    op = oc.Opinion("COMPRAR", 60, "<script>x</script> & más", ["<b>r</b>"], [], [], oc.MODELO, 1.0)
    h = html_de(op)
    assert "<script>" not in h and "&lt;script&gt;" in h and "&lt;b&gt;r&lt;/b&gt;" in h


def test_el_worker_devuelve_el_error_esperable_sin_excepcion(monkeypatch):
    from ui.analysis.opinion_card import OpinionWorker

    def falla(datos):
        raise oc.OpinionError("Claude no respondió en 240 s.")

    monkeypatch.setattr(oc, "pedir_opinion", falla)
    w = OpinionWorker("MU", lambda: {"ticker": "MU"})
    assert w.do_work() == (False, "Claude no respondió en 240 s.")


def test_una_opinion_larga_no_aplasta_el_panel():
    """Con la opinión real de MU (tesis de 6 oraciones, 4 riesgos) la tarjeta crecía sin techo."""
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication

    from ui.analysis.opinion_card import CUERPO_MAX_ALTO, OpinionCard

    _app = QApplication.instance() or QApplication([])
    card = OpinionCard()
    card.mostrar(oc.Opinion("MANTENER", 40, "x " * 800, ["r"] * 4, ["c"] * 3, ["f"] * 2, oc.MODELO, 1.0))
    assert card.cuerpo_scroll.maximumHeight() == CUERPO_MAX_ALTO
    assert _app is not None


# ── El entorno del proceso (tarea 322) ───────────────────────────────────────


def test_claude_se_lanza_SIN_api_key_ni_variables_de_sesion(monkeypatch):
    """Lo que falló en la app: con ANTHROPIC_API_KEY en el entorno, Claude Code la usa antes que el
    login de la suscripción (401). Y las CLAUDE_CODE_* de una sesión autentican por la sesión padre:
    por eso la verificación de la 320, hecha adentro de una sesión, anduvo."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-xxx")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "tok")
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv("CLAUDE_CODE_CHILD_SESSION", "1")
    monkeypatch.setenv("CLAUDE_CODE_MESSAGING_TOKEN", "t")
    monkeypatch.setenv("FINANZIAS_ALGO", "queda")
    r = _Runner(stdout=_salida(_BUENA))
    oc.pedir_opinion({}, exe="x", runner=r)
    env = r.llamadas[0]["env"]
    assert env is not None, "sin env explícito el proceso hereda la key"
    prohibidas = [k for k in env if k.startswith(("ANTHROPIC_", "CLAUDECODE", "CLAUDE_CODE_"))]
    assert prohibidas == []
    assert env["FINANZIAS_ALGO"] == "queda", "el resto del entorno se conserva (PATH, HOME…)"


def test_el_401_explica_que_hacer():
    r = _Runner(stdout=_salida(_BUENA, is_error=True, result="Failed to authenticate. API Error: 401"))
    with pytest.raises(oc.OpinionError, match=r"login de claude.ai"):
        oc.pedir_opinion({}, exe="x", runner=r)
