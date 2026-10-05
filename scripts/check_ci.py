"""¿El CI quedó verde en el commit pusheado? — la mitad del cierre que el done no puede ver (tarea 300).

Los cuatro comandos del done corren en Windows **antes** del commit. Lo que sólo rompe en Linux
(separadores de path, mayúsculas, permisos, locale) lo ve únicamente el CI, que corre **después**
del push. Tres veces el CI quedó rojo mientras las tareas se cerraban en verde, y nadie lo leyó:

- **106:** el job `lint` rojo, trece tareas;
- **175/176:** el job `pytest` rojo 35 corridas, 36 tareas (la 176 agregó el cuarto comando y
  **descartó** leer el CI, porque avisa con retraso uno);
- **300:** el job `pytest` rojo 19 corridas, 17 tareas — un test con rutas de Windows literales.

Así que la tarea **no se da por cerrada** hasta que este script dice verde sobre el commit
pusheado. Es la regla 1 de `CLAUDE.md`, y el paso del cierre en `/ship` y en `git-workflow`.

Uso::

    python scripts/check_ci.py                 # el CI de HEAD, como está ahora
    python scripts/check_ci.py --esperar       # espera a que termine (al cerrar una tarea)
    python scripts/check_ci.py --ultimo        # el último run TERMINADO en main (al abrir una)

Salida: ``0`` verde · ``1`` rojo (o cancelado) · ``2`` no se sabe: sin red, sin run para ese
commit, HEAD sin pushear, la API limitada, o se agotó la espera. **Un 2 no es un verde**: el
cierre lo dice así (*«CI sin verificar»*) y la próxima tarea arranca con ``--ultimo``.

Usa la API **pública** de Actions, sin ``gh auth`` (60 requests/hora por IP): cada consulta son
1-3 requests, y la espera consulta cada ``--intervalo`` segundos.

**Sin el filtro ``branch`` de la API (tarea 307).** ``…/workflows/ci.yml/runs?branch=main`` devolvía,
de forma intermitente, un subconjunto **atrasado** de los runs: el 2026-10-05 ``--ultimo`` dijo
*«CI 48430cd (2026-09-08): VERDE»* con ``main`` un mes más adelante (``total_count`` 135, 357 y 395
contra 493 sin el filtro). Así que la rama se filtra acá (``head_branch`` y ``event == push``), y
``--ultimo`` compara el sha del run contra ``origin/main``: si no es ése, sólo vale cuando el run de
``origin/main`` todavía está en curso (el retraso uno de siempre); si no, es *no se sabe*.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_API = "https://api.github.com"
WORKFLOW = "ci.yml"
RAMA = "main"

VERDE, ROJO, NO_SE_SABE = 0, 1, 2

Fetch = Callable[[str], object]


class SinRespuesta(RuntimeError):
    """La API no contestó algo usable (sin red, 403 por cuota, 404)."""


def _fetch_json(url: str) -> object:
    req = urllib.request.Request(
        url, headers={"Accept": "application/vnd.github+json", "User-Agent": "finanzias-check-ci"}
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise SinRespuesta(f"HTTP {e.code} en {url}") from e
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise SinRespuesta(f"{type(e).__name__}: {e}") from e


def repo_de_origin(url: str) -> str | None:
    """``owner/repo`` desde la URL de ``origin`` (https o ssh), o ``None`` si no es de GitHub."""
    m = re.search(r"github\.com[:/]+([^/]+/[^/]+?)(?:\.git)?/?$", url.strip())
    return m.group(1) if m else None


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=_REPO, capture_output=True, text=True, check=True
    ).stdout.strip()


def de_la_rama(runs: list[dict]) -> list[dict]:
    """Los runs de un push a ``RAMA``. Se filtra acá porque el ``branch=`` de la API no es confiable
    (tarea 307), y por ``event`` porque un pull request desde una rama ``main`` de un fork también
    trae ``head_branch == "main"``."""
    return [r for r in runs if r.get("head_branch") == RAMA and r.get("event", "push") == "push"]


def run_de_commit(runs: list[dict], sha: str) -> dict | None:
    """El run más reciente del workflow para ``sha`` (re-ejecutar un job crea otro intento)."""
    propios = [r for r in runs if r.get("head_sha") == sha]
    return (
        max(propios, key=lambda r: (r.get("run_attempt") or 0, r.get("created_at") or ""))
        if propios
        else None
    )


def ultimo_terminado(runs: list[dict]) -> dict | None:
    terminados = [r for r in runs if r.get("status") == "completed"]
    return max(terminados, key=lambda r: r.get("created_at") or "") if terminados else None


def veredicto(run: dict | None) -> int:
    """Verde sólo con ``success``. Un run sin terminar, o que no existe, es «no se sabe»."""
    if run is None or run.get("status") != "completed":
        return NO_SE_SABE
    return VERDE if run.get("conclusion") == "success" else ROJO


def tests_que_fallaron(anotaciones: list[dict]) -> list[str]:
    """Las líneas ``FAILED …`` / ``ERROR …`` del resumen de pytest que GitHub guarda como anotación."""
    out: list[str] = []
    for a in anotaciones:
        for linea in str(a.get("message", "")).splitlines():
            linea = linea.strip()
            if re.match(r"^(FAILED|ERROR) \S", linea) and linea not in out:
                out.append(linea)
    return out


def detalle_del_rojo(repo: str, run: dict, fetch: Fetch) -> list[str]:
    """Qué jobs fallaron y, de cada uno, los tests. Best-effort: si la API no contesta, se dice."""
    lineas: list[str] = []
    try:
        jobs = fetch(f"{_API}/repos/{repo}/actions/runs/{run['id']}/jobs")
        for job in jobs.get("jobs", []):  # type: ignore[union-attr]
            if job.get("conclusion") in ("success", "skipped"):
                continue
            # `mypy (best-effort)` tiene `continue-on-error`: sale `failure` y no tumba el run. La
            # API no expone el flag, así que se marca por el nombre que el workflow le pone.
            nota = " (best-effort: no bloquea)" if "best-effort" in str(job.get("name", "")) else ""
            lineas.append(f"  job {job.get('name')!r}: {job.get('conclusion')}{nota}")
            anot = fetch(f"{_API}/repos/{repo}/check-runs/{job['id']}/annotations")
            lineas += [f"    {t}" for t in tests_que_fallaron(anot if isinstance(anot, list) else [])]
    except (SinRespuesta, KeyError, AttributeError, TypeError) as e:
        lineas.append(f"  (no se pudo leer el detalle: {e})")
    return lineas


def consultar(
    repo: str,
    sha: str | None,
    *,
    fetch: Fetch = _fetch_json,
    esperar: bool = False,
    timeout_s: float = 900.0,
    intervalo_s: float = 45.0,
    dormir: Callable[[float], None] = time.sleep,
    reloj: Callable[[], float] = time.monotonic,
    out=print,
    sha_main: str | None = None,
) -> int:
    """Consulta (y opcionalmente espera) el CI de ``sha``; con ``sha=None``, el último terminado.

    ``sha_main`` (sólo con ``sha=None``) es ``origin/main``: si el último run terminado no es de
    ese commit y tampoco hay un run de ese commit en curso, la lista que devolvió la API está
    atrasada y el veredicto es *no se sabe* (tarea 307).
    """
    url = f"{_API}/repos/{repo}/actions/workflows/{WORKFLOW}/runs?per_page=30"
    if sha:
        url += f"&head_sha={sha}"
    limite = reloj() + timeout_s
    while True:
        try:
            datos = fetch(url)
            runs = de_la_rama(datos.get("workflow_runs", []) if isinstance(datos, dict) else [])
        except SinRespuesta as e:
            out(f"CI: no se sabe — la API no contestó ({e}). NO es un verde.")
            return NO_SE_SABE
        run = run_de_commit(runs, sha) if sha else ultimo_terminado(runs)
        v = veredicto(run)
        if v != NO_SE_SABE or not esperar or reloj() >= limite:
            break
        estado = "sin run todavía" if run is None else f"{run.get('status')}"
        out(f"CI de {sha[:7] if sha else 'main'}: {estado} — reintento en {intervalo_s:.0f} s")
        dormir(intervalo_s)

    if run is None:
        que = f"el commit {sha[:7]}" if sha else f"`{RAMA}`"
        out(f"CI: no se sabe — no hay ningún run de {WORKFLOW} para {que}. NO es un verde.")
        return NO_SE_SABE
    nota = ""
    if not sha and sha_main and run.get("head_sha") != sha_main:
        en_curso = run_de_commit(runs, sha_main)
        if en_curso is None or en_curso.get("status") == "completed":
            out(
                f"CI: no se sabe — el último run que devolvió la API es de {run.get('head_sha', '')[:7]} "
                f"({run.get('created_at')}) y `{RAMA}` está en {sha_main[:7]}, sin run en curso: la lista "
                "llegó atrasada o ese commit no tiene run. NO es un verde."
            )
            return NO_SE_SABE
        nota = f" — el run de {sha_main[:7]} (`{RAMA}`) sigue en curso; éste es el anterior"
    cab = f"CI {run.get('head_sha', '')[:7]} ({run.get('created_at')}){nota}: "
    if v == NO_SE_SABE:
        out(
            cab
            + f"{run.get('status')} — no terminó{' dentro de la espera' if esperar else ''}. NO es un verde."
        )
        out(f"  {run.get('html_url', '')}")
        return NO_SE_SABE
    if v == VERDE:
        out(cab + "VERDE")
        return VERDE
    out(cab + f"ROJO ({run.get('conclusion')}) — {run.get('html_url', '')}")
    for linea in detalle_del_rojo(repo, run, fetch):
        out(linea)
    return ROJO


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    modo = ap.add_mutually_exclusive_group()
    modo.add_argument("--esperar", action="store_true", help="esperar a que el run de HEAD termine")
    modo.add_argument("--ultimo", action="store_true", help="el último run terminado en main (retraso uno)")
    ap.add_argument("--sha", help="commit a consultar (default: HEAD)")
    ap.add_argument("--timeout", type=float, default=900.0, help="segundos máximos de espera (default 900)")
    ap.add_argument("--intervalo", type=float, default=45.0, help="segundos entre consultas (default 45)")
    args = ap.parse_args(argv)

    try:
        repo = repo_de_origin(_git("remote", "get-url", "origin"))
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"CI: no se sabe — no se pudo leer `origin` ({e}).")
        return NO_SE_SABE
    if not repo:
        print("CI: no se sabe — `origin` no es un repo de GitHub.")
        return NO_SE_SABE

    sha = None
    sha_main = None
    if args.ultimo:
        try:
            sha_main = _git("rev-parse", f"origin/{RAMA}")
        except subprocess.CalledProcessError:
            print(f"CI: no se sabe — no se pudo leer origin/{RAMA} para comparar el último run.")
            return NO_SE_SABE
    else:
        # Tarea 318: un sha abreviado se resuelve acá; la API compara contra el completo, y con
        # `--sha ecc1a07` la respuesta era «no hay ningún run», que no es lo mismo que no saber.
        try:
            sha = (
                _git("rev-parse", "--verify", f"{args.sha}^{{commit}}")
                if args.sha
                else _git("rev-parse", "HEAD")
            )
        except subprocess.CalledProcessError:
            print(f"CI: no se sabe — `{args.sha}` no es un commit de este repo.")
            return NO_SE_SABE
        if not args.sha:
            try:
                remoto = _git("rev-parse", f"origin/{RAMA}")
            except subprocess.CalledProcessError:
                remoto = ""
            if remoto != sha:
                print(
                    f"CI: no se sabe — HEAD ({sha[:7]}) no es origin/{RAMA} ({remoto[:7] or '?'}): "
                    "pusheá antes de leer el CI del cierre."
                )
                return NO_SE_SABE
    return consultar(
        repo, sha, esperar=args.esperar, timeout_s=args.timeout, intervalo_s=args.intervalo, sha_main=sha_main
    )


if __name__ == "__main__":
    sys.exit(main())
