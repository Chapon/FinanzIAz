"""Tarea 405 (NUBE-SIN-VERIFICAR) — el aviso de una corrida fallida del recolector de la nube.

``correr_lote`` **no levanta nunca** (lo registra todo en la ``Corrida``), así que el
``Errors`` de Lambda no ve una corrida sin universo ni una que no corrió ningún ticker. El
aviso sale de una línea ``RECOLECTOR_FALLA`` que el handler imprime, un filtro de métrica del
template sobre esa marca y una alarma que publica en un tópico SNS con el mail de Chapa. Más
dos alarmas sobre las métricas de la Lambda: ``Errors`` (lo que ``correr_lote`` no alcanza a
registrar: un import roto, el timeout) e ``Invocations`` (el horario dejó de disparar).

Lo que acá no se puede probar —que la alarma de verdad dispare el mail— es la acción manual
de la 405: una invocación de prueba con un lote fuera de rango. Este archivo fija que esa
invocación **sí** produce la línea que el filtro cuenta.
"""

from __future__ import annotations

import ast
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts import recolector_nube as rn

ROOT = Path(__file__).resolve().parent.parent
T0 = datetime(2026, 11, 6, 22, 30, tzinfo=timezone.utc)


def _corrida(**kw):
    c = rn.Corrida(lote=2, lotes=5, inicio=T0)
    for k, v in kw.items():
        setattr(c, k, v)
    return c


# ── Qué cuenta como falla ────────────────────────────────────────────────────


def test_una_corrida_sana_NO_avisa_aunque_un_ticker_toque_el_techo():
    c = _corrida(pedidos=["A", "B", "C"], corridos=["A", "B"], techo=["C"])
    assert rn.motivo_de_falla(c) is None and rn.linea_de_falla(c) is None


def test_un_lote_vacio_sin_error_NO_avisa():
    """Un universo más chico que los lotes deja lotes sin tickers: no es una falla."""
    assert rn.linea_de_falla(_corrida()) is None


@pytest.mark.parametrize(
    "kw, fragmento",
    [
        ({"error": "sin universo publicado (ítem universo/vivo vacío o ausente)"}, "sin universo"),
        ({"pedidos": ["A", "B"], "techo": ["A"], "sin_correr": ["B"]}, "ningún ticker corrido de 2"),
        (
            {"pedidos": ["A"], "corridos": ["A"], "errores_escritura": ["A: ClientError"]},
            "errores de escritura 1",
        ),
    ],
)
def test_cada_falla_sale_con_la_marca_el_lote_y_el_motivo(kw, fragmento):
    linea = rn.linea_de_falla(_corrida(**kw))
    assert linea is not None
    assert linea.startswith(f"{rn.MARCA_FALLA} lote 3/5: ")
    assert fragmento in linea


class _Tabla:
    def __init__(self, universo=None):
        self.items = {}
        if universo is not None:
            self.items[("universo", "vivo")] = {
                "pk": "universo",
                "sk": "vivo",
                "tickers": list(universo),
                "publicado_at": "2026-11-06T20:00:00",
                "origen": "manual",
            }

    def get_item(self, Key):
        it = self.items.get((Key["pk"], Key["sk"]))
        return {"Item": it} if it else {}

    def put_item(self, Item, ConditionExpression=None):
        self.items[(Item["pk"], Item["sk"])] = Item


def test_la_prueba_manual_un_lote_fuera_de_rango_produce_la_linea_que_cuenta_el_filtro():
    """Es el evento de la acción manual de la 405: ``{"lote": 9, "lotes": 5}``."""
    c = rn.correr_lote(9, 5, tabla=_Tabla(["AAPL", "MSFT"]), fuentes=(), reloj=lambda: T0)
    linea = rn.linea_de_falla(c)
    assert linea is not None and linea.startswith(rn.MARCA_FALLA) and "fuera de rango" in linea


def test_sin_universo_publicado_tambien_avisa():
    c = rn.correr_lote(0, 5, tabla=_Tabla(), fuentes=(), reloj=lambda: T0)
    assert rn.linea_de_falla(c).startswith(rn.MARCA_FALLA)


def test_el_handler_imprime_la_linea_de_falla():
    """``lambda_handler`` no se puede correr sin AWS: se fija que llame a ``linea_de_falla``
    y que imprima su resultado."""
    arbol = ast.parse((ROOT / "scripts" / "recolector_nube.py").read_text(encoding="utf-8"))
    (handler,) = [n for n in arbol.body if isinstance(n, ast.FunctionDef) and n.name == "lambda_handler"]
    llamadas = {
        n.func.id for n in ast.walk(handler) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    }
    assert "linea_de_falla" in llamadas
    impresos = [
        a.id
        for n in ast.walk(handler)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "print"
        for a in n.args
        if isinstance(a, ast.Name)
    ]
    asignada = next(
        t.id
        for n in ast.walk(handler)
        if isinstance(n, ast.Assign)
        and isinstance(n.value, ast.Call)
        and isinstance(n.value.func, ast.Name)
        and n.value.func.id == "linea_de_falla"
        for t in n.targets
    )
    assert asignada in impresos


# ── El template ──────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def cfn():
    return json.loads((ROOT / "infra" / "recolector_nube.cfn.json").read_text(encoding="utf-8"))


def _de_tipo(cfn, tipo):
    return {k: r for k, r in cfn["Resources"].items() if r["Type"] == tipo}


def test_el_filtro_cuenta_EXACTAMENTE_la_marca_del_recolector_en_su_log_group(cfn):
    (f,) = _de_tipo(cfn, "AWS::Logs::MetricFilter").values()
    p = f["Properties"]
    assert p["FilterPattern"] == f'"{rn.MARCA_FALLA}"'
    assert p["LogGroupName"] == {"Ref": "Logs"}
    (m,) = p["MetricTransformations"]
    assert m["MetricValue"] == "1"


def test_el_topico_manda_al_mail_de_la_alerta(cfn):
    (t,) = _de_tipo(cfn, "AWS::SNS::Topic").values()
    assert t["Properties"]["Subscription"] == [{"Protocol": "email", "Endpoint": {"Ref": "AlertaEmail"}}]


def test_las_tres_alarmas_publican_en_el_topico(cfn):
    (topico,) = _de_tipo(cfn, "AWS::SNS::Topic")
    alarmas = _de_tipo(cfn, "AWS::CloudWatch::Alarm")
    assert len(alarmas) == 3
    assert len(alarmas) <= 10, "10 alarmas estándar son gratis por cuenta"
    for a in alarmas.values():
        assert a["Properties"]["AlarmActions"] == [{"Ref": topico}]


def test_la_alarma_de_corrida_fallida_mira_la_metrica_del_filtro(cfn):
    (f,) = _de_tipo(cfn, "AWS::Logs::MetricFilter").values()
    (m,) = f["Properties"]["MetricTransformations"]
    a = cfn["Resources"]["AlarmaCorridaFallida"]["Properties"]
    assert (a["Namespace"], a["MetricName"]) == (m["MetricNamespace"], m["MetricName"])
    assert a["ComparisonOperator"] == "GreaterThanOrEqualToThreshold" and a["Threshold"] == 1
    # Sin línea de falla no hay dato: eso es "anduvo", no "alarma".
    assert a["TreatMissingData"] == "notBreaching"


def test_las_alarmas_de_la_lambda_miran_ESTA_funcion(cfn):
    for nombre, metrica in (("AlarmaErrores", "Errors"), ("AlarmaSinInvocaciones", "Invocations")):
        p = cfn["Resources"][nombre]["Properties"]
        assert (p["Namespace"], p["MetricName"]) == ("AWS/Lambda", metrica)
        assert p["Dimensions"] == [{"Name": "FunctionName", "Value": {"Ref": "Recolector"}}]


def test_sin_invocaciones_no_dispara_un_fin_de_semana_y_si_cuatro_dias_sin_correr(cfn):
    """Lambda no publica ``Invocations`` en cero: sin invocaciones no hay dato, y el dato
    faltante tiene que contar como alarma. Con períodos diarios (alineados al día UTC), un
    fin de semana deja tres seguidos sin dato —sábado, domingo y el lunes hasta el primer
    lote a las 17:30 de Nueva York—, así que la alarma necesita cuatro."""
    p = cfn["Resources"]["AlarmaSinInvocaciones"]["Properties"]
    assert p["TreatMissingData"] == "breaching"
    assert p["ComparisonOperator"] == "LessThanThreshold" and p["Threshold"] == 1
    assert p["Period"] == 86400
    assert p["DatapointsToAlarm"] == p["EvaluationPeriods"] == 4
    # Los horarios siguen siendo de lunes a viernes: si pasaran a correr menos días, el
    # hueco crece y la alarma da falsos positivos.
    horarios = _de_tipo(cfn, "AWS::Scheduler::Schedule").values()
    assert all(h["Properties"]["ScheduleExpression"].endswith("? * MON-FRI *)") for h in horarios)
