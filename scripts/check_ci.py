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

Salida: ``0`` verde · ``1`` rojo (o cancelado con algún job) · ``2`` no se sabe: sin red, sin run
para ese commit, HEAD sin pushear, la API limitada, se agotó la espera, un run **atascado** o uno
que **nunca arrancó**. **Un 2 no es un verde**: el cierre lo dice así (*«CI sin verificar»*) y la
próxima tarea arranca con ``--ultimo``.

**Un run que GitHub nunca arrancó (tarea 430).** Los runs del 2026-11-11 quedaron huérfanos en un
incidente de GitHub: sin ningún job, uno ``queued`` días enteros y el otro ``cancelled`` cuatro
días después. Este script los leía como «en curso» —``--ultimo`` dio VERDE del commit anterior
cuatro días, y después ROJO del cancelado, sin detalle—. Ahora un run sin terminar, **sin jobs** y
más viejo que ``ATASCADO_S`` es *atascado* (no se sabe, con la hora), también cuando el anterior
está en verde; un ``cancelled`` sin jobs es *nunca arrancó* (no se sabe, no un rojo de los tests);
y ``--ultimo`` dice cuántos commits de ``main`` no tienen un run terminado.

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
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_API = "https://api.github.com"
WORKFLOW = "ci.yml"
RAMA = "main"

VERDE, ROJO, NO_SE_SABE = 0, 1, 2

# Un run normal crea sus jobs en segundos y termina en ~10-15 min. Sin ningún job a la hora, GitHub
# no lo va a arrancar: es *atascado* (tarea 430). Los del 2026-11-11 llevaban días.
ATASCADO_S = 3600.0

Fetch = Callable[[str], object]


class SinRespuesta(RuntimeError):
    """La API no contestó algo usable (sin red, 403 por cuota, 404)."""


class SinRed(SinRespuesta):
    """No llegó ninguna respuesta (SSL, timeout, sin conexión): puede ser pasajero (tarea 400)."""


def _contexto_ssl() -> ssl.SSLContext:
    """El almacén de ``certifi`` si está, y el del sistema si no (tarea 403).

    GitHub sirve a veces una cadena que termina en *USERTrust ECC*, y el almacén de Windows no la
    tiene: Windows baja esas raíces a demanda sólo para su propia pila TLS (``curl`` nunca falló).
    """
    try:
        import certifi
    except ImportError:
        return ssl.create_default_context()
    return ssl.create_default_context(cafile=certifi.where())


def _fetch_json(url: str) -> object:
    req = urllib.request.Request(
        url, headers={"Accept": "application/vnd.github+json", "User-Agent": "finanzias-check-ci"}
    )
    try:
        with urllib.request.urlopen(req, timeout=20, context=_contexto_ssl()) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise SinRespuesta(f"HTTP {e.code} en {url}") from e
    except (urllib.error.URLError, OSError) as e:
        raise SinRed(f"{type(e).__name__}: {e}") from e
    except ValueError as e:
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


def edad_s(run: dict, ahora: datetime) -> float | None:
    """Segundos desde que se creó el run, o ``None`` si no trae una fecha legible."""
    try:
        creado = datetime.fromisoformat(str(run.get("created_at")).replace("Z", "+00:00"))
    except ValueError:
        return None
    if creado.tzinfo is None:
        creado = creado.replace(tzinfo=timezone.utc)
    return (ahora - creado).total_seconds()


def jobs_del_run(repo: str, run: dict, fetch: Fetch) -> list | None:
    """Los jobs que GitHub le creó al run, o ``None`` si la API no contestó algo usable."""
    try:
        datos = fetch(f"{_API}/repos/{repo}/actions/runs/{run['id']}/jobs")
    except (SinRespuesta, KeyError):
        return None
    if not isinstance(datos, dict) or not isinstance(datos.get("jobs", []), list):
        return None
    return datos.get("jobs") or []


def atascado(repo: str, run: dict, fetch: Fetch, ahora: datetime) -> str | None:
    """Por qué el run está *atascado* (tarea 430), o ``None`` si no lo está.

    Sin terminar, más viejo que ``ATASCADO_S`` y sin jobs. Si los jobs no se pueden leer, también
    —un run «en curso» hace más de una hora sin poder ver nada de él no se lee como el retraso uno
    de siempre (el principio de la 300: lo dudoso no presta un verde)—. Los jobs se piden sólo para
    un run viejo: el caso normal no gasta requests.
    """
    if run.get("status") == "completed":
        return None
    edad = edad_s(run, ahora)
    if edad is None or edad <= ATASCADO_S:
        return None
    jobs = jobs_del_run(repo, run, fetch)
    if jobs is None:
        return "sin poder leer sus jobs"
    return "sin ningún job" if not jobs else None


def nunca_arranco(repo: str, run: dict, fetch: Fetch) -> bool:
    """Un ``cancelled`` sin ningún job: lo cancelaron antes de arrancar, no falló nada (tarea 430).
    Un ``startup_failure`` tampoco tiene jobs y **sí** es un rojo: el workflow no se pudo leer. Si los
    jobs no se pueden leer, sigue siendo el rojo de la 300."""
    if run.get("status") != "completed" or run.get("conclusion") != "cancelled":
        return False
    return jobs_del_run(repo, run, fetch) == []


def _contar_commits(desde: str, hasta: str) -> int | None:
    try:
        return int(_git("rev-list", "--count", f"{desde}..{hasta}"))
    except (subprocess.CalledProcessError, FileNotFoundError, ValueError):
        return None


_DESTRABAR = "Un push nuevo debería desplazarlo; si no, cancelalo en Actions y re-correlo."


def _horas(run: dict, ahora: datetime) -> str:
    edad = edad_s(run, ahora)
    return "" if edad is None else f", hace {edad / 3600:.0f} h"


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
    ahora: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    contar: Callable[[str, str], int | None] = _contar_commits,
) -> int:
    """Consulta (y opcionalmente espera) el CI de ``sha``; con ``sha=None``, el último terminado.

    ``sha_main`` (sólo con ``sha=None``) es ``origin/main``: si el último run terminado no es de
    ese commit y tampoco hay un run de ese commit en curso, la lista que devolvió la API está
    atrasada y el veredicto es *no se sabe* (tarea 307). Si el de ``origin/main`` está *atascado*,
    también (tarea 430): el anterior no dice nada de ``main``.
    """
    url = f"{_API}/repos/{repo}/actions/workflows/{WORKFLOW}/runs?per_page=30"
    if sha:
        url += f"&head_sha={sha}"
    limite = reloj() + timeout_s
    fallos = 0
    trabado: str | None = None
    while True:
        try:
            datos = fetch(url)
            runs = de_la_rama(datos.get("workflow_runs", []) if isinstance(datos, dict) else [])
        except SinRespuesta as e:
            fallos += 1
            # Tarea 400: un error de red pasajero (el SSL del 2026-10-26) no corta la espera. Una
            # respuesta HTTP sí: la cuota o un 404 no cambian en 15 minutos.
            if esperar and isinstance(e, SinRed) and reloj() < limite:
                out(f"CI: la API no contestó ({e}) — reintento en {intervalo_s:.0f} s")
                dormir(intervalo_s)
                continue
            veces = f", {fallos} veces seguidas" if fallos > 1 else ""
            out(f"CI: no se sabe — la API no contestó ({e}{veces}). NO es un verde.")
            return NO_SE_SABE
        fallos = 0
        run = run_de_commit(runs, sha) if sha else ultimo_terminado(runs)
        v = veredicto(run)
        # Tarea 430: esperar 15 min a un run que GitHub no va a arrancar no cambia nada.
        trabado = atascado(repo, run, fetch, ahora()) if v == NO_SE_SABE and run is not None else None
        if v != NO_SE_SABE or trabado or not esperar or reloj() >= limite:
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
        sin_run = contar(str(run.get("head_sha", "")), sha_main)
        pendientes = (
            f"\n  `{RAMA}` tiene {sin_run} commit(s) sin un run terminado (desde {run.get('head_sha', '')[:7]})."
            if sin_run
            else ""
        )
        motivo = atascado(repo, en_curso, fetch, ahora())
        if motivo:
            out(
                f"CI: no se sabe — el run de {sha_main[:7]} (`{RAMA}`) está ATASCADO: "
                f"{en_curso.get('status')} desde {en_curso.get('created_at')}{_horas(en_curso, ahora())}, "
                f"{motivo} (GitHub no lo arrancó: un incidente o un run huérfano). El anterior no dice nada "
                f"de `{RAMA}`. NO es un verde.{pendientes}\n  {en_curso.get('html_url', '')}\n  {_DESTRABAR}"
            )
            return NO_SE_SABE
        nota = f" — el run de {sha_main[:7]} (`{RAMA}`) sigue en curso; éste es el anterior"
        if pendientes:
            out(pendientes.strip("\n"))
    cab = f"CI {run.get('head_sha', '')[:7]} ({run.get('created_at')}){nota}: "
    if trabado:
        out(
            cab + f"ATASCADO — {run.get('status')}{_horas(run, ahora())}, {trabado}: GitHub no lo "
            "arrancó (un incidente o un run huérfano). NO es un verde."
        )
        out(f"  {run.get('html_url', '')}")
        out(f"  {_DESTRABAR}")
        return NO_SE_SABE
    if v == ROJO and nunca_arranco(repo, run, fetch):
        out(
            cab + "no se sabe — cancelado sin ningún job: el run nunca arrancó, no es un rojo de los tests. "
            "NO es un verde."
        )
        out(f"  {run.get('html_url', '')}")
        return NO_SE_SABE
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
