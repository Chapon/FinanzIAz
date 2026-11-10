"""
¿Cuánto cuesta el pipeline de noticias y quién usa lo que produce? — **tarea 413** (spike).

Saca los números del informe ``docs/noticias_costo_beneficio_t413_2026-11-10.md`` de dos
lugares, los dos en sólo lectura:

- la DB (``news_events``, ``paper_orders``, ``paper_watchlist``, ``claude_opinions``),
  abierta en sólo lectura (``readonly_uri``, tarea 191);
- el log de la app (``~/.finanzias/finanzias.log``, hora local), del que salen las corridas
  del harvest y del clasificador.

No pega a la red, no escribe nada y no cablea nada.

Uso:
    python scripts/measure_news_cost_benefit_t413.py
    python scripts/measure_news_cost_benefit_t413.py --db copia.db --log copia.log --json
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from database.readonly import readonly_uri  # tarea 191

DEFAULT_DB = _ROOT / "finanzias.db"
DEFAULT_LOG = Path.home() / ".finanzias" / "finanzias.log"
CUENTA_VIVA = 2

_TS = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")
_HARVEST = re.compile(
    r"Harvest: (\d+)(?:/\d+)? tickers(?: en (\d+)s)? \| news \+(\d+) \(dup (\d+)\) \| "
    r"estimates \+(\d+) \(dup (\d+)\)"
)
_CLASSIFY_START = re.compile(r"scripts\.classify_catalysts: classifying with")
_CLASSIFY_END = re.compile(r"Classify: scanned (\d+) \| classified (\d+)")


def _ts(linea: str) -> datetime | None:
    m = _TS.match(linea)
    return datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S") if m else None


def _titulo(t: str) -> str:
    return " ".join((t or "").lower().split())


def medir_log(path: Path) -> dict:
    """Corridas del harvest y del clasificador, y días con la app abierta."""
    harvests: list[dict] = []
    clasif: list[dict] = []
    dias_log: set[str] = set()
    inicio_clasif: datetime | None = None
    ultimo_disparo = "manual"
    with path.open(encoding="utf-8", errors="replace") as fh:
        for linea in fh:
            ts = _ts(linea)
            if ts is None:
                continue
            dias_log.add(ts.date().isoformat())
            if "hourly catalyst harvest starting" in linea:
                ultimo_disparo = "horario"
            elif "daily catalyst refresh starting" in linea:
                ultimo_disparo = "diario"
            m = _HARVEST.search(linea)
            if m and "[dry-run]" not in linea:
                tick, seg, nuevas, dup, est_n, est_d = m.groups()
                harvests.append(
                    {
                        "ts": ts,
                        "disparo": ultimo_disparo,
                        "tickers": int(tick),
                        "segundos": int(seg) if seg else None,
                        "nuevas": int(nuevas),
                        "dup": int(dup),
                        "est_nuevas": int(est_n),
                        "est_dup": int(est_d),
                    }
                )
                ultimo_disparo = "manual"
            if _CLASSIFY_START.search(linea):
                inicio_clasif = ts
            m = _CLASSIFY_END.search(linea)
            if m:
                seg = (ts - inicio_clasif).total_seconds() if inicio_clasif else None
                clasif.append({"ts": ts, "clasificadas": int(m.group(2)), "segundos": seg})
                inicio_clasif = None

    recibidas = sum(h["nuevas"] + h["dup"] for h in harvests)
    nuevas = sum(h["nuevas"] for h in harvests)
    con_seg = [h["segundos"] for h in harvests if h["segundos"] is not None]
    por_disparo: dict[str, dict] = {}
    for d in ("diario", "horario", "manual"):
        hs = [h for h in harvests if h["disparo"] == d]
        segs = [h["segundos"] for h in hs if h["segundos"] is not None]
        por_disparo[d] = {
            "corridas": len(hs),
            "nuevas": sum(h["nuevas"] for h in hs),
            "recibidas": sum(h["nuevas"] + h["dup"] for h in hs),
            "est_nuevas": sum(h["est_nuevas"] for h in hs),
            "est_recibidas": sum(h["est_nuevas"] + h["est_dup"] for h in hs),
            "con_duracion": len(segs),
            "horas_medidas": round(sum(segs) / 3600, 2),
            "mediana_s": statistics.median(segs) if segs else None,
        }
    medidas = [c for c in clasif if c["segundos"] is not None and c["clasificadas"] > 0]
    n_med = sum(c["clasificadas"] for c in medidas)
    s_med = sum(c["segundos"] for c in medidas)
    dias_harvest = {h["ts"].date().isoformat() for h in harvests}
    return {
        "desde": min(dias_log) if dias_log else None,
        "hasta": max(dias_log) if dias_log else None,
        "dias_con_log": len(dias_log),
        "dias_con_harvest": len(dias_harvest),
        "harvest": {
            "corridas": len(harvests),
            "recibidas": recibidas,
            "nuevas": nuevas,
            "pct_nuevas": round(100 * nuevas / recibidas, 1) if recibidas else None,
            "con_duracion": len(con_seg),
            "horas_medidas": round(sum(con_seg) / 3600, 2),
            "mediana_s": statistics.median(con_seg) if con_seg else None,
            "por_disparo": por_disparo,
        },
        "clasificacion": {
            "corridas": len(clasif),
            "clasificadas": sum(c["clasificadas"] for c in clasif),
            "corridas_medidas": len(medidas),
            "clasificadas_medidas": n_med,
            "horas_medidas": round(s_med / 3600, 1),
            "s_por_noticia": round(s_med / n_med, 2) if n_med else None,
        },
    }


def _tenencia(con: sqlite3.Connection, cuenta: int) -> dict[str, list[tuple[str, str | None]]]:
    """``{ticker: [(abierta, cerrada|None)]}`` de la cuenta, a partir de las órdenes llenadas."""
    filas = con.execute(
        "SELECT ticker, side, fill_shares, filled_at FROM paper_orders "
        "WHERE account_id=? AND status='filled' AND filled_at IS NOT NULL ORDER BY filled_at",
        (cuenta,),
    ).fetchall()
    shares: dict[str, float] = defaultdict(float)
    abiertas: dict[str, str] = {}
    out: dict[str, list[tuple[str, str | None]]] = defaultdict(list)
    for tick, side, n, cuando in filas:
        antes = shares[tick]
        shares[tick] += (n or 0) if side == "BUY" else -(n or 0)
        if antes <= 1e-9 < shares[tick]:
            abiertas[tick] = cuando
        elif antes > 1e-9 >= shares[tick] and tick in abiertas:
            out[tick].append((abiertas.pop(tick), cuando))
    for tick, desde in abiertas.items():
        out[tick].append((desde, None))
    return out


def medir_db(path: Path) -> dict:
    con = sqlite3.connect(readonly_uri(path), uri=True)
    q = con.execute
    total = q("SELECT COUNT(*) FROM news_events").fetchone()[0]
    rango = q("SELECT MIN(fetched_at), MAX(fetched_at) FROM news_events").fetchone()
    tickers = q("SELECT COUNT(DISTINCT ticker) FROM news_events").fetchone()[0]
    bytes_txt = q(
        "SELECT SUM(LENGTH(title)+COALESCE(LENGTH(content),0)+COALESCE(LENGTH(url),0)) FROM news_events"
    ).fetchone()[0]
    por_fuente = {
        s: {"filas": n, "mb": round((b or 0) / 1e6, 1), "desde": d, "hasta": h, "clasif": c}
        for s, n, b, d, h, c in q(
            "SELECT source, COUNT(*), "
            "SUM(LENGTH(title)+COALESCE(LENGTH(content),0)+COALESCE(LENGTH(url),0)), "
            "MIN(fetched_at), MAX(fetched_at), SUM(event_type IS NOT NULL) "
            "FROM news_events GROUP BY source ORDER BY COUNT(*) DESC"
        )
    }

    # Lo que sólo trae cada fuente: (ticker, título normalizado) que no aparece en otra.
    fuentes_de: dict[tuple[str, str], set[str]] = defaultdict(set)
    filas = q("SELECT ticker, title, source, event_type, fetched_at FROM news_events").fetchall()
    for tick, tit, src, _et, _f in filas:
        fuentes_de[(tick, _titulo(tit))].add(src)
    unicas: Counter = Counter()
    for tick, tit, src, _et, _f in filas:
        if fuentes_de[(tick, _titulo(tit))] == {src}:
            unicas[src] += 1
    for s in por_fuente:
        por_fuente[s]["solo_esta_fuente"] = unicas[s]
    titulos_distintos = len(fuentes_de)

    por_tipo = dict(
        q(
            "SELECT COALESCE(event_type,'(sin clasificar)'), COUNT(*) FROM news_events "
            "GROUP BY 1 ORDER BY 2 DESC"
        ).fetchall()
    )
    por_clasificador = dict(
        q(
            "SELECT COALESCE(classified_by,'(null)'), COUNT(*) FROM news_events GROUP BY 1 ORDER BY 2 DESC"
        ).fetchall()
    )
    sin_clasif = q("SELECT COUNT(*), MIN(fetched_at) FROM news_events WHERE event_type IS NULL").fetchone()

    # Latencia publicada→vista, en horas, por fuente.
    latencia: dict[str, dict] = {}
    lat_por_fuente: dict[str, list[float]] = defaultdict(list)
    for src, pub, fet in q(
        "SELECT source, published_at, fetched_at FROM news_events "
        "WHERE published_at IS NOT NULL AND fetched_at IS NOT NULL"
    ):
        try:
            h = (datetime.fromisoformat(fet[:19]) - datetime.fromisoformat(pub[:19])).total_seconds() / 3600
        except ValueError:
            continue
        lat_por_fuente[src].append(h)
    for src, hs in lat_por_fuente.items():
        hs.sort()
        latencia[src] = {
            "n": len(hs),
            "mediana_h": round(statistics.median(hs), 1),
            "pct_mas_de_7_dias": round(100 * sum(h > 24 * 7 for h in hs) / len(hs), 1),
        }
    sec_viejos = q(
        "SELECT substr(published_at,1,4), COUNT(*) FROM news_events WHERE source='sec_8k' "
        "GROUP BY 1 ORDER BY 1"
    ).fetchall()

    # ¿Cuántas noticias son de un ticker que la cuenta viva tenía en cartera ese día?
    tenencia = _tenencia(con, CUENTA_VIVA)
    en_cartera = 0
    for tick, _tit, _src, _et, fet in filas:
        for desde, hasta in tenencia.get(tick, ()):
            if fet and desde[:19] <= fet[:19] and (hasta is None or fet[:19] <= hasta[:19]):
                en_cartera += 1
                break
    tickers_tenidos = len(tenencia)
    watch = {r[0] for r in q("SELECT ticker FROM paper_watchlist WHERE account_id=?", (CUENTA_VIVA,))}
    fuera_watch = q(
        "SELECT COUNT(*) FROM news_events WHERE ticker NOT IN "
        "(SELECT ticker FROM paper_watchlist WHERE account_id=?)",
        (CUENTA_VIVA,),
    ).fetchone()[0]

    # ¿Qué tan vieja estaba la noticia cuando qwen la clasificó? (la pestaña abre en 1 día)
    edad = q(
        "SELECT COUNT(*), "
        "SUM(julianday(classified_at)-julianday(COALESCE(published_at,fetched_at)) > 1), "
        "SUM(julianday(classified_at)-julianday(COALESCE(published_at,fetched_at)) > 3) "
        "FROM news_events WHERE classified_by='ollama-7n' AND classified_at IS NOT NULL"
    ).fetchone()
    opiniones = q("SELECT COUNT(*), MIN(fecha), MAX(fecha) FROM claude_opinions").fetchone()
    con.close()
    return {
        "news_events": {
            "filas": total,
            "desde": rango[0],
            "hasta": rango[1],
            "tickers": tickers,
            "mb_texto": round((bytes_txt or 0) / 1e6, 1),
            "titulos_distintos": titulos_distintos,
            "por_fuente": por_fuente,
            "por_tipo": por_tipo,
            "por_clasificador": por_clasificador,
            "sin_clasificar": sin_clasif[0],
            "sin_clasificar_mas_vieja": sin_clasif[1],
            "latencia": latencia,
            "sec_8k_por_anio_publicado": dict(sec_viejos),
        },
        "uso": {
            "filas_de_ticker_en_cartera": en_cartera,
            "pct_en_cartera": round(100 * en_cartera / total, 1) if total else None,
            "tickers_que_estuvieron_en_cartera": tickers_tenidos,
            "watchlist_viva": len(watch),
            "filas_fuera_de_la_watchlist_viva": fuera_watch,
            "opiniones_claude": {"n": opiniones[0], "desde": opiniones[1], "hasta": opiniones[2]},
            "qwen7n_clasificadas": edad[0],
            "qwen7n_con_mas_de_1_dia": edad[1],
            "qwen7n_con_mas_de_3_dias": edad[2],
        },
    }


def acuerdo_heuristica(path: Path) -> dict:
    """La heurística de la pestaña (``classify_missing``) contra qwen, sobre lo que qwen clasificó.

    Sólo las filas de la escala de 7 niveles (``classified_by='ollama-7n'``), que son las que
    tienen ``sentiment_score``. Compara lo que muestra la pestaña: el tipo y el tono −3…+3.
    """
    from analysis.news_digest import tone_level
    from data.catalyst_classifier import heuristic_classify

    con = sqlite3.connect(readonly_uri(path), uri=True)
    filas = con.execute(
        "SELECT title, source, ticker, event_type, sentiment, sentiment_score FROM news_events "
        "WHERE classified_by='ollama-7n'"
    ).fetchall()
    con.close()
    n = tipo = signo = cerca = tono_q_no0 = tono_h_no0 = 0
    for tit, src, tick, et, sent, score in filas:
        h = heuristic_classify(tit, None, src, tick)
        tq = tone_level(score, sent)
        th = tone_level(h.sentiment_score, h.sentiment)
        n += 1
        tipo += h.event_type == et
        signo += (tq > 0) - (tq < 0) == (th > 0) - (th < 0)
        cerca += abs(tq - th) <= 1
        tono_q_no0 += tq != 0
        tono_h_no0 += th != 0
    pct = lambda x: round(100 * x / n, 1) if n else None
    return {
        "n": n,
        "pct_mismo_tipo": pct(tipo),
        "pct_mismo_signo_de_tono": pct(signo),
        "pct_tono_a_1_nivel": pct(cerca),
        "pct_tono_no_neutro_qwen": pct(tono_q_no0),
        "pct_tono_no_neutro_heuristica": pct(tono_h_no0),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--log", type=Path, default=DEFAULT_LOG)
    ap.add_argument("--json", action="store_true", help="salida JSON (si no, JSON indentado)")
    args = ap.parse_args(argv)
    out = {
        "db": medir_db(args.db),
        "log": medir_log(args.log),
        "heuristica_vs_qwen": acuerdo_heuristica(args.db),
    }
    print(json.dumps(out, ensure_ascii=False, indent=None if args.json else 2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
