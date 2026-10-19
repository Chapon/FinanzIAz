"""Tarea 355 (NUBE-RECOLECTOR-AWS) — el recolector de Lambda, sin AWS y sin red.

Tres piezas, y cada una con lo que su kill-criteria pide poder chequear antes de desplegar:

* **El handler** (``scripts/recolector_nube.py``) contra una tabla simulada que se porta
  como la de ``boto3`` en lo que importa: rechaza ``float`` y respeta la condición
  ``attribute_not_exists``. Fija el (d) del kill-criteria —``capturado_at`` es el de la
  recolección y no el de la escritura— y lo que sostiene el (c): un ticker colgado no se
  come el lote, y lo que no alcanzó a correr queda declarado.
* **El zip** (``scripts/build_recolector_nube.py``): importa sin ``database`` ni SQLAlchemy,
  y su ``_ticker`` es el de la app.
* **El template** (``infra/recolector_nube.cfn.json``): lo que haría que (b) —la factura en
  US$0,00— falle sin que nada lo avise: una VPC, una tabla on-demand, más capacidad que la
  gratuita, un permiso de más.
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
import zipfile
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from data import news_sources as ns
from data.news_sources import EstimateSnapshot, NewsItem, SourceOutcome
from scripts import recolector_nube as rn

ROOT = Path(__file__).resolve().parent.parent
T0 = datetime(2026, 10, 12, 21, 30, tzinfo=timezone.utc)


# ── La tabla simulada ────────────────────────────────────────────────────────


class _Condicional(Exception):
    response = {"Error": {"Code": "ConditionalCheckFailedException"}}


def _sin_floats(v, ruta="item"):
    """``boto3`` levanta ``TypeError`` con un float: la tabla simulada también."""
    if isinstance(v, float):
        raise TypeError(f"Float types are not supported. Use Decimal types instead ({ruta})")
    if isinstance(v, dict):
        for k, x in v.items():
            _sin_floats(x, f"{ruta}.{k}")
    elif isinstance(v, list):
        for i, x in enumerate(v):
            _sin_floats(x, f"{ruta}[{i}]")


class TablaFalsa:
    def __init__(self, universo=None, *, al_escribir=None):
        self.items: dict[tuple[str, str], dict] = {}
        self.al_escribir = al_escribir
        if universo is not None:
            self.items[("universo", "vivo")] = {
                "pk": "universo",
                "sk": "vivo",
                "tickers": list(universo),
                "publicado_at": "2026-10-12T20:00:00",
                "origen": "manual",
            }

    def get_item(self, Key):
        it = self.items.get((Key["pk"], Key["sk"]))
        return {"Item": it} if it else {}

    def put_item(self, Item, ConditionExpression=None):
        _sin_floats(Item)
        if self.al_escribir:
            self.al_escribir(Item)
        k = (Item["pk"], Item["sk"])
        if ConditionExpression == "attribute_not_exists(pk)" and k in self.items:
            raise _Condicional()
        self.items[k] = Item

    def de(self, prefijo):
        return {k: v for k, v in self.items.items() if k[0].startswith(prefijo)}


class Reloj:
    def __init__(self, t=T0):
        self.t = t

    def __call__(self):
        return self.t

    def avanzar(self, **kw):
        self.t += timedelta(**kw)


def _fuentes_falsas(monkeypatch, *, noticias=None, estimates=True, colgar=(), red_caida=False):
    """Reemplaza los colectores de ``data.news_sources``: los mismos nombres que usa la app."""
    noticias = noticias if noticias is not None else {}

    def _est(t):
        if red_caida:
            return [], SourceOutcome("yfinance_estimates", "failed", 0, "OSError: red")
        if t in colgar:
            import time

            time.sleep(5)
        if not estimates:
            return [], SourceOutcome("yfinance_estimates", "ok", 0)
        snaps = [
            EstimateSnapshot(t, "eps", "0q", 1.25, 7),
            EstimateSnapshot(t, "price_target", "current", 210.5, None),
        ]
        return snaps, SourceOutcome("yfinance_estimates", "ok", len(snaps))

    def _sec(t):
        if red_caida:
            return [], SourceOutcome("sec", "failed", 0, "OSError: red")
        return [], SourceOutcome("sec", "ok", 0)

    def _fh(t):
        if red_caida:
            return [], SourceOutcome("finnhub", "failed", 0, "OSError: red")
        items = noticias.get(t, [])
        return items, SourceOutcome("finnhub", "ok", len(items))

    def _yfn(t):  # pragma: no cover — si se llama, el test de fuentes lo caza
        raise AssertionError("yfinance_news no es fuente del recolector hasta la 362")

    monkeypatch.setattr(ns, "_yf_estimates", _est)
    monkeypatch.setattr(ns, "_sec_8k", _sec)
    monkeypatch.setattr(ns, "_finnhub_news", _fh)
    monkeypatch.setattr(ns, "_yf_news", _yfn)


def _noticia(t, titulo, publicada):
    return NewsItem(
        ticker=t, title=titulo, source="finnhub:Yahoo", url=f"https://x/{titulo}", published_at=publicada
    )


# ── Los lotes ────────────────────────────────────────────────────────────────


def test_cada_ticker_cae_en_exactamente_UN_lote():
    universo = [f"T{i:03d}" for i in range(127)]
    lotes = [rn.tickers_del_lote(universo, k, rn.LOTES) for k in range(rn.LOTES)]
    juntos = [t for lote in lotes for t in lote]
    assert sorted(juntos) == sorted(universo) and len(juntos) == len(set(juntos))
    assert [len(x) for x in lotes] == [26, 26, 25, 25, 25]


def test_el_lote_normaliza_y_deduplica():
    assert rn.tickers_del_lote([" aapl", "AAPL", "msft", ""], 0, 1) == ["AAPL", "MSFT"]


@pytest.mark.parametrize("lote, lotes", [(5, 5), (-1, 5), (0, 0)])
def test_un_lote_fuera_de_rango_levanta(lote, lotes):
    with pytest.raises(ValueError):
        rn.tickers_del_lote(["A"], lote, lotes)


# ── El consenso y la marca de captura (kill-criteria d) ──────────────────────


def test_el_consenso_se_escribe_por_ticker_y_dia_con_Decimal(monkeypatch):
    _fuentes_falsas(monkeypatch)
    tabla = TablaFalsa(["AAPL", "MSFT"])
    c = rn.correr_lote(0, 1, tabla=tabla, reloj=Reloj())

    assert c.error is None and c.corridos == ["AAPL", "MSFT"]
    it = tabla.items[("consenso#2026-10-12", "AAPL")]
    assert it["filas"][0] == {
        "metric": "eps",
        "period_label": "0q",
        "consensus_value": Decimal("1.25"),
        "num_analysts": 7,
    }
    assert it["filas"][1]["num_analysts"] is None
    assert it["expira"] == int((T0 + timedelta(days=90)).timestamp())


def test_capturado_at_es_el_de_la_RECOLECCION_no_el_de_la_escritura(monkeypatch):
    """(d): la escritura tarda —botocore reintenta un throttling solo— y la marca no se mueve."""
    n = _noticia("AAPL", "n", datetime(2026, 10, 12, 15, 0))
    _fuentes_falsas(monkeypatch, noticias={"AAPL": [n]})
    reloj = Reloj()
    tabla = TablaFalsa(["AAPL", "MSFT"], al_escribir=lambda item: reloj.avanzar(minutes=7))
    rn.correr_lote(0, 1, tabla=tabla, reloj=reloj)

    # AAPL: consenso y noticia con la MISMA marca, aunque entre las dos escrituras pasaron 7 min.
    assert tabla.items[("consenso#2026-10-12", "AAPL")]["capturado_at"] == "2026-10-12T21:30:00"
    assert tabla.items[("noticia#2026-10-12", n.content_hash())]["capturado_at"] == "2026-10-12T21:30:00"
    # MSFT se recolectó después de las dos escrituras de AAPL: su marca es la suya, no la del arranque.
    assert tabla.items[("consenso#2026-10-12", "MSFT")]["capturado_at"] == "2026-10-12T21:44:00"


def test_el_PRIMERO_del_dia_gana_como_en_la_app(monkeypatch):
    """Re-correr el lote el mismo día no pisa la captura: sólo completa lo que faltaba."""
    _fuentes_falsas(monkeypatch)
    tabla = TablaFalsa(["AAPL"])
    reloj = Reloj()
    rn.correr_lote(0, 1, tabla=tabla, reloj=reloj)
    reloj.avanzar(hours=1)
    c = rn.correr_lote(0, 1, tabla=tabla, reloj=reloj)

    assert tabla.items[("consenso#2026-10-12", "AAPL")]["capturado_at"] == "2026-10-12T21:30:00"
    assert (c.consenso_nuevos, c.consenso_ya_estaban) == (0, 1)


def test_un_ticker_sin_consenso_no_deja_item(monkeypatch):
    _fuentes_falsas(monkeypatch, estimates=False)
    tabla = TablaFalsa(["AAPL"])
    rn.correr_lote(0, 1, tabla=tabla, reloj=Reloj())
    assert tabla.de("consenso#") == {}


@pytest.mark.parametrize(
    "v, esperado",
    [
        (1.5, Decimal("1.5")),
        (None, None),
        (float("nan"), None),
        (float("inf"), None),
        ("x", None),
        (3, Decimal("3")),
    ],
)
def test_num_dynamo(v, esperado):
    assert rn.num_dynamo(v) == esperado


# ── Las noticias ─────────────────────────────────────────────────────────────


def test_las_noticias_van_por_content_hash_y_dentro_de_la_ventana(monkeypatch):
    nueva = _noticia("AAPL", "nueva", datetime(2026, 10, 12, 15, 0))
    vieja = _noticia("AAPL", "vieja", datetime(2026, 10, 5, 15, 0))
    sin_fecha = _noticia("AAPL", "sin fecha", None)
    _fuentes_falsas(monkeypatch, noticias={"AAPL": [nueva, vieja, sin_fecha]})
    tabla = TablaFalsa(["AAPL"])
    c = rn.correr_lote(0, 1, tabla=tabla, reloj=Reloj())

    escritas = tabla.de("noticia#2026-10-12")
    assert set(k[1] for k in escritas) == {nueva.content_hash(), sin_fecha.content_hash()}
    it = escritas[("noticia#2026-10-12", nueva.content_hash())]
    assert it["published_at"] == "2026-10-12T15:00:00" and it["source"] == "finnhub:Yahoo"
    assert (c.noticias_nuevas, c.noticias_fuera_de_ventana) == (2, 1)


def test_la_ventana_es_la_declarada():
    """Bajarla pierde noticias si la nube se saltea un día; subirla re-escribe la semana."""
    assert rn.VENTANA_NOTICIAS_DIAS == 3
    borde = _noticia("A", "x", T0.replace(tzinfo=None) - timedelta(days=3))
    afuera = _noticia("A", "y", T0.replace(tzinfo=None) - timedelta(days=3, seconds=1))
    assert rn.noticia_en_ventana(borde, T0) and not rn.noticia_en_ventana(afuera, T0)


# ── El techo y la red caída (kill-criteria c) ────────────────────────────────


def test_un_ticker_COLGADO_no_se_come_el_lote(monkeypatch):
    _fuentes_falsas(monkeypatch, colgar={"BBB"})
    tabla = TablaFalsa(["AAA", "BBB", "CCC"])
    c = rn.correr_lote(0, 1, tabla=tabla, reloj=Reloj(), techo_s=0.2)

    assert c.techo == ["BBB"]
    assert c.corridos == ["AAA", "CCC"]
    assert ("consenso#2026-10-12", "BBB") not in tabla.items


def test_lo_que_no_alcanza_a_correr_queda_DECLARADO(monkeypatch):
    _fuentes_falsas(monkeypatch)
    quedan = iter([1000.0, 1000.0, 10.0])
    tabla = TablaFalsa(["AAA", "BBB", "CCC", "DDD"])
    c = rn.correr_lote(0, 1, tabla=tabla, reloj=Reloj(), restante_s=lambda: next(quedan))

    assert c.corridos == ["AAA", "BBB"] and c.sin_correr == ["CCC", "DDD"]
    corrida = next(iter(tabla.de("corrida#").values()))
    assert (corrida["pedidos"], corrida["corridos"], corrida["sin_correr"]) == (4, 2, ["CCC", "DDD"])


def test_con_la_red_caida_termina_y_lo_dice(monkeypatch):
    _fuentes_falsas(monkeypatch, red_caida=True)
    tabla = TablaFalsa(["AAA", "BBB"])
    c = rn.correr_lote(0, 1, tabla=tabla, reloj=Reloj())

    assert c.error is None and c.corridos == ["AAA", "BBB"]
    assert c.fuentes["finnhub"] == {"con_items": 0, "failed": 2}
    assert tabla.de("consenso#") == {} and tabla.de("noticia#") == {}
    assert "finnhub con_items 0/failed 2" in c.resumen()


# ── La corrida: sobre qué corrió ─────────────────────────────────────────────


def test_la_corrida_declara_universo_lote_y_fuentes(monkeypatch):
    _fuentes_falsas(monkeypatch)
    tabla = TablaFalsa([f"T{i}" for i in range(10)])
    rn.correr_lote(1, 5, tabla=tabla, reloj=Reloj(), version="abc123 2026-10-12")

    ((clave, it),) = tabla.de("corrida#2026-10-12").items()
    assert clave[1] == "lote2de5#2026-10-12T21:30:00"
    assert (it["universo_n"], it["universo_origen"], it["pedidos"], it["corridos"]) == (10, "manual", 2, 2)
    assert it["fuentes"]["yfinance_estimates"] == {"con_items": 2, "ok": 2}
    assert it["version"] == "abc123 2026-10-12"


def test_sin_universo_no_recolecta_y_lo_registra(monkeypatch):
    _fuentes_falsas(monkeypatch)
    tabla = TablaFalsa(None)
    c = rn.correr_lote(0, 5, tabla=tabla, reloj=Reloj())

    assert c.error and "sin universo" in c.error and c.corridos == []
    assert len(tabla.de("corrida#")) == 1 and tabla.de("consenso#") == {}


def test_una_escritura_que_falla_no_hunde_al_resto(monkeypatch):
    _fuentes_falsas(monkeypatch)

    def _falla_aapl(item):
        if item["sk"] == "AAPL":
            raise RuntimeError("ProvisionedThroughputExceeded tras los reintentos")

    tabla = TablaFalsa(["AAPL", "MSFT"], al_escribir=_falla_aapl)
    c = rn.correr_lote(0, 1, tabla=tabla, reloj=Reloj())
    assert c.errores_escritura == ["AAPL: RuntimeError"]
    assert ("consenso#2026-10-12", "MSFT") in tabla.items


def test_las_fuentes_son_las_que_andan_desde_AWS():
    """``yfinance_news`` contesta 404 desde el 2026-10-01 (tarea 354); la 357 la repuso en la app y al recolector entra con la 362."""
    assert rn.FUENTES_DEFAULT == ("estimates", "sec", "finnhub")
    for f in rn.FUENTES_DEFAULT:
        assert callable(getattr(ns, rn._COLECTORES[f]))


# ── La key de Finnhub desde SSM ──────────────────────────────────────────────


class _SSM:
    def __init__(self, valor=None, falla=False):
        self.valor, self.falla, self.pedidos = valor, falla, []

    def get_parameter(self, Name, WithDecryption):
        self.pedidos.append((Name, WithDecryption))
        if self.falla:
            raise RuntimeError("AccessDenied")
        return {"Parameter": {"Value": self.valor}}


def test_la_key_de_finnhub_sale_de_SSM_descifrada(monkeypatch):
    monkeypatch.delenv("FINNHUB_API_KEY", raising=False)
    ssm = _SSM("k-123")
    assert rn._cargar_finnhub_key(ssm, "/finanzias/finnhub_api_key") is None
    assert ssm.pedidos == [("/finanzias/finnhub_api_key", True)]
    import os

    assert os.environ["FINNHUB_API_KEY"] == "k-123"


def test_sin_SSM_se_dice_el_motivo_y_no_levanta(monkeypatch):
    monkeypatch.delenv("FINNHUB_API_KEY", raising=False)
    assert rn._cargar_finnhub_key(_SSM(falla=True), "/p") == "SSM /p: RuntimeError"
    assert rn._cargar_finnhub_key(_SSM(), None) == "sin FINNHUB_PARAM"


# ── El zip ───────────────────────────────────────────────────────────────────


def test_el_shim_es_el_ticker_de_la_app():
    from scripts.build_recolector_nube import YAHOO_FINANCE, shim_yahoo_finance

    real = YAHOO_FINANCE.read_text(encoding="utf-8")
    shim = shim_yahoo_finance(real)
    fn_real = next(n for n in ast.parse(real).body if isinstance(n, ast.FunctionDef) and n.name == "_ticker")
    assert ast.get_source_segment(real, fn_real) in shim
    imports = [n for n in ast.parse(shim).body if isinstance(n, ast.Import | ast.ImportFrom)]
    assert [ast.unparse(n) for n in imports] == ["import yfinance as yf"]


def test_un_ticker_que_usa_algo_mas_que_yf_frena_el_build():
    from scripts.build_recolector_nube import shim_yahoo_finance

    with pytest.raises(SystemExit, match="_session"):
        shim_yahoo_finance("def _ticker(symbol):\n    return yf.Ticker(symbol, session=_session)\n")


def test_el_zip_importa_SIN_la_db(tmp_path):
    """Lo que hace viable reusar los colectores: el zip no arrastra ``database`` ni SQLAlchemy."""
    from scripts.build_recolector_nube import ARCHIVOS_DEL_REPO, SHIM, VERSION, armar_zip

    out = tmp_path / "r.zip"
    armar_zip(None, out, version="test")
    with zipfile.ZipFile(out) as zf:
        assert sorted(zf.namelist()) == sorted([*ARCHIVOS_DEL_REPO, SHIM, VERSION])
        zf.extractall(tmp_path / "x")

    codigo = (
        "import sys, recolector_nube, data.news_sources as ns, data.yahoo_finance as yh;"
        "assert 'database' not in sys.modules and 'sqlalchemy' not in sys.modules, sorted(sys.modules);"
        "assert yh.__file__.startswith(sys.argv[1]), yh.__file__;"
        "assert recolector_nube._version() == 'test'; print('ok')"
    )
    # El PYTHONPATH se hereda: trae el cortafuegos de red del hijo (tarea 211). El zip se
    # resuelve igual desde el cwd, que con `-c` va primero en sys.path.
    env = {**__import__("os").environ, "FINANZIAS_LOG_FILE": ":sin-archivo:"}
    r = subprocess.run(
        [sys.executable, "-c", codigo, str(tmp_path / "x")],
        cwd=tmp_path / "x",
        capture_output=True,
        text=True,
        env=env,
    )
    assert r.returncode == 0 and r.stdout.strip() == "ok", r.stderr[-2000:]


# ── El universo para la consola ──────────────────────────────────────────────


def test_el_item_universo_para_la_consola():
    from scripts.universo_para_nube import a_dynamodb_json, item_universo

    it = item_universo(["msft", "AAPL", "AAPL"], T0, "manual")
    assert it == {
        "pk": "universo",
        "sk": "vivo",
        "tickers": ["AAPL", "MSFT"],
        "publicado_at": "2026-10-12T21:30:00",
        "origen": "manual",
    }
    tipado = a_dynamodb_json(it)
    assert tipado["tickers"] == {"L": [{"S": "AAPL"}, {"S": "MSFT"}]}
    # Lo que escribe la consola es lo que lee el recolector.
    tabla = TablaFalsa()
    tabla.items[("universo", "vivo")] = it
    assert rn.leer_universo(tabla)["tickers"] == ["AAPL", "MSFT"]
    with pytest.raises(ValueError):
        item_universo([], T0, "manual")


# ── El template: lo que haría que la factura no sea US$0,00 ──────────────────


@pytest.fixture(scope="module")
def cfn():
    return json.loads((ROOT / "infra" / "recolector_nube.cfn.json").read_text(encoding="utf-8"))


def _de_tipo(cfn, tipo):
    return {k: r for k, r in cfn["Resources"].items() if r["Type"] == tipo}


def test_la_lambda_NO_va_en_una_VPC_y_respeta_el_techo(cfn):
    """§7.2: dentro de una VPC necesita NAT Gateway, ~US$32/mes."""
    (fn,) = _de_tipo(cfn, "AWS::Lambda::Function").values()
    p = fn["Properties"]
    assert "VpcConfig" not in p
    assert p["Timeout"] <= 900 and p["Runtime"] == "python3.12" and p["Architectures"] == ["x86_64"]
    modulo, funcion = p["Handler"].split(".")
    assert modulo == "recolector_nube" and callable(getattr(rn, funcion))
    env = p["Environment"]["Variables"]
    assert env["FINANZIAS_LOG_FILE"] == ":sin-archivo:" and env["TABLA"] == {"Ref": "Tabla"}


def test_la_tabla_es_PROVISIONADA_dentro_de_las_25_gratis_con_TTL(cfn):
    (t,) = _de_tipo(cfn, "AWS::DynamoDB::Table").values()
    p = t["Properties"]
    assert p["BillingMode"] == "PROVISIONED", "on-demand se cobra por pedido: no es always-free"
    cap = p["ProvisionedThroughput"]
    # 25 RCU y 25 WCU gratuitas, por cuenta (otra tabla provisionada se suma: ver el §12).
    assert cap["ReadCapacityUnits"] <= 25 and cap["WriteCapacityUnits"] <= 25
    assert "GlobalSecondaryIndexes" not in p, "un GSI consume capacidad aparte"
    assert p["TimeToLiveSpecification"] == {"AttributeName": "expira", "Enabled": True}
    assert [k["AttributeName"] for k in p["KeySchema"]] == ["pk", "sk"]
    assert p["TableName"] == rn.TABLA_DEFAULT


def _statements(rol):
    return [s for pol in rol["Properties"]["Policies"] for s in pol["PolicyDocument"]["Statement"]]


def test_el_rol_del_recolector_sólo_escribe_ESA_tabla(cfn):
    st = _statements(cfn["Resources"]["RolRecolector"])
    acciones = sorted(a for s in st for a in s["Action"])
    assert acciones == sorted(
        [
            "dynamodb:PutItem",
            "dynamodb:GetItem",
            "ssm:GetParameter",
            "logs:CreateLogStream",
            "logs:PutLogEvents",
        ]
    )
    assert all("*" not in json.dumps(s["Action"]) for s in st)
    dynamo = next(s for s in st if s["Action"][0].startswith("dynamodb:"))
    assert dynamo["Resource"] == {"Fn::GetAtt": ["Tabla", "Arn"]}


def test_el_usuario_de_la_app_sólo_lee_salvo_el_item_universo(cfn):
    (st_lectura, st_if) = _statements(cfn["Resources"]["LectorApp"])
    assert sorted(st_lectura["Action"]) == ["dynamodb:GetItem", "dynamodb:Query"]
    cond, si, no = st_if["Fn::If"]
    assert cond == "PublicaUniverso" and no == {"Ref": "AWS::NoValue"}
    assert si["Action"] == ["dynamodb:PutItem"]
    assert si["Condition"] == {"ForAllValues:StringEquals": {"dynamodb:LeadingKeys": ["universo"]}}
    assert cfn["Parameters"]["AppPublicaUniverso"]["Default"] == "no", "lo decide Chapa (356)"


def test_un_horario_por_lote_en_dias_habiles_y_escalonados(cfn):
    horarios = _de_tipo(cfn, "AWS::Scheduler::Schedule")
    assert len(horarios) == rn.LOTES
    entradas = sorted(json.loads(h["Properties"]["Target"]["Input"])["lote"] for h in horarios.values())
    assert entradas == list(range(rn.LOTES))
    assert all(json.loads(h["Properties"]["Target"]["Input"])["lotes"] == rn.LOTES for h in horarios.values())
    exprs = [h["Properties"]["ScheduleExpression"] for h in horarios.values()]
    assert all(e.endswith("? * MON-FRI *)") for e in exprs) and len(set(exprs)) == rn.LOTES


def test_hay_presupuesto_que_avisa_ante_el_primer_centavo(cfn):
    (b,) = _de_tipo(cfn, "AWS::Budgets::Budget").values()
    assert b["Properties"]["Budget"]["BudgetLimit"] == {"Amount": 1, "Unit": "USD"}
    (n,) = b["Properties"]["NotificationsWithSubscribers"]
    assert n["Notification"]["NotificationType"] == "ACTUAL" and n["Notification"]["Threshold"] == 1


def test_los_logs_no_se_guardan_para_siempre(cfn):
    (lg,) = _de_tipo(cfn, "AWS::Logs::LogGroup").values()
    assert lg["Properties"]["RetentionInDays"] <= 30
    assert lg["Properties"]["LogGroupName"].endswith(
        _de_tipo(cfn, "AWS::Lambda::Function")["Recolector"]["Properties"]["FunctionName"]
    )
