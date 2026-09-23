"""CUENTA-VIVA-APP (tarea 70) — los jobs de fondo corrían sobre la cuenta PAUSADA.

Hasta el 2026-09-01, **los siete** call sites con alcance de cuenta del lado app
tenían el literal `1` como default —dashboard, rebuild de `surprise_profiles`,
harvest de catalysts y cuatro herederos— y **ninguno miraba `is_active`**. La
cuenta 1 está pausada desde el 2026-07-01, así que durante dos meses el dashboard
se re-estampó a diario con una cartera congelada y el harvest recolectó para 52
tickers en vez de 128 — **79 nombres del universo vivo sin una sola noticia en 45
días**, y esa cobertura no se recupera (`data/news_sources.py:477`, `days_back=7`).

Del lado harness esto estaba resuelto desde la tarea 27 (`LIVE_ACCOUNT_ID`). Acá
el arreglo **no es poner `2`**: eso es el mismo defecto con otro número, y el
próximo cambio de cuenta lo reabre. Se resuelve **contra la DB**.
"""

from __future__ import annotations

import logging

from paper_trading.account import create_account, live_account_id


def _cuenta(nombre: str, *, activa: bool):
    acct = create_account(name=nombre, initial_capital=50_000.0)
    from database.models import session_scope
    from paper_trading.models import PaperAccount

    with session_scope() as s:
        row = s.query(PaperAccount).filter(PaperAccount.id == acct.id).first()
        row.is_active = activa
    return acct.id


# ── La resolución ────────────────────────────────────────────────────────────


def test_sin_flag_resuelve_la_cuenta_ACTIVA_no_la_primera(test_db):
    """El corazón del arreglo: el default deja de ser un literal. Hoy **ningún**
    flag está seteado, así que todos los jobs tomaban el `1` hardcodeado."""
    pausada = _cuenta("Pausada", activa=False)
    viva = _cuenta("Viva", activa=True)
    assert pausada < viva  # la pausada es la de menor id, como en producción
    assert live_account_id() == viva


def test_sin_ninguna_cuenta_activa_devuelve_None_y_el_job_NO_corre(test_db, caplog):
    """Un job de fondo que no sabe sobre qué cuenta opera **no debe elegir una**.
    No correr es la respuesta correcta, y se avisa."""
    _cuenta("Pausada", activa=False)
    with caplog.at_level(logging.WARNING, logger="paper_trading.account"):
        assert live_account_id() is None
    assert any("is_active=1" in r.getMessage() for r in caplog.records)


def test_con_varias_activas_elige_la_de_menor_id_y_avisa(test_db, caplog):
    """Ambigüedad, no error: se elige determinísticamente y se declara."""
    a = _cuenta("Una", activa=True)
    b = _cuenta("Otra", activa=True)
    with caplog.at_level(logging.WARNING, logger="paper_trading.account"):
        assert live_account_id() == min(a, b)
    assert any("cuentas activas" in r.getMessage() for r in caplog.records)


# ── El flag explícito ────────────────────────────────────────────────────────


def test_un_flag_explicito_se_respeta(test_db, monkeypatch):
    """Si el operador lo seteó, mandó él."""
    _cuenta("Viva", activa=True)
    pausada = _cuenta("Pausada", activa=False)
    from config.settings_manager import settings

    monkeypatch.setattr(settings, "get", lambda k, d=None: pausada if k == "mi_flag" else d)
    assert live_account_id("mi_flag") == pausada


def test_pero_si_apunta_a_una_PAUSADA_lo_grita(test_db, monkeypatch, caplog):
    """**El silencio es lo que dejó correr esto dos meses.** Se respeta la
    decisión del operador, pero no puede quedarse callado."""
    _cuenta("Viva", activa=True)
    pausada = _cuenta("Pausada", activa=False)
    from config.settings_manager import settings

    monkeypatch.setattr(settings, "get", lambda k, d=None: pausada if k == "mi_flag" else d)
    with caplog.at_level(logging.WARNING, logger="paper_trading.account"):
        live_account_id("mi_flag")
    msg = " ".join(r.getMessage() for r in caplog.records)
    assert "PAUSADA" in msg and "tarea 70" in msg


def test_un_flag_que_apunta_a_una_cuenta_inexistente_cae_a_la_viva(test_db, caplog, monkeypatch):
    viva = _cuenta("Viva", activa=True)
    from config.settings_manager import settings

    monkeypatch.setattr(settings, "get", lambda k, d=None: 9999 if k == "mi_flag" else d)
    with caplog.at_level(logging.WARNING, logger="paper_trading.account"):
        assert live_account_id("mi_flag") == viva
    assert any("no existe" in r.getMessage() for r in caplog.records)


def test_un_error_de_DB_no_rompe_el_scan(monkeypatch, caplog):
    """Fail-safe, mismo criterio que los guards de la 59 y la 64: un guard nuevo
    que rompe un scan es peor que el problema que resuelve."""
    import paper_trading.account as acc

    def _boom(**_kw):
        raise RuntimeError("DB caida")

    monkeypatch.setattr(acc, "list_accounts", _boom)
    with caplog.at_level(logging.ERROR, logger="paper_trading.account"):
        assert live_account_id() is None


# ── El cableado: los siete call sites ────────────────────────────────────────


# Las dos únicas constantes de módulo con un id de cuenta que el proyecto acepta, con
# su motivo. Cualquier otra es el defecto de la tarea 70 volviendo.
_IDS_DECLARADOS: dict[str, str] = {
    "LIVE_ACCOUNT_ID": (
        "el espejo declarado de la cuenta viva; lo re-verifica contra `is_active` "
        "`test_account_defaults_t99.py::test_el_espejo_de_la_cuenta_viva_es_la_activa`"
    ),
    "LEGACY_ACCOUNT_ID": (
        "la cuenta 1 (PAUSADA), que es la que heredaron los harness T7→T13: es "
        "**historia** de una comparación congelada, no configuración — mismo criterio "
        "que los BASELINE_* de la tarea 134"
    ),
}

_PAQUETES = ("scripts", "paper_trading", "analysis", "ui", "data", "config", "alerts", "database")


def _constantes_de_cuenta() -> list[tuple[str, str, object]]:
    """``(archivo, nombre, valor)`` de cada constante de módulo con ``ACCOUNT_ID``.

    Por **AST** y sobre **todo** el proyecto, no por texto sobre tres archivos.
    """
    import ast
    from pathlib import Path

    raiz = Path(__file__).resolve().parent.parent
    out = []
    for paquete in _PAQUETES:
        for p in sorted((raiz / paquete).rglob("*.py")):
            try:
                arbol = ast.parse(p.read_text(encoding="utf-8"))
            except SyntaxError:  # pragma: no cover
                continue
            for n in arbol.body:
                if not isinstance(n, ast.Assign):
                    continue
                for t in n.targets:
                    if isinstance(t, ast.Name) and "ACCOUNT_ID" in t.id:
                        valor = n.value.value if isinstance(n.value, ast.Constant) else "<no-literal>"
                        out.append((p.relative_to(raiz).as_posix(), t.id, valor))
    return out


# Constantes `*ACCOUNT_ID` que se declaran **sin usarse**, con el motivo (tarea 229).
# Una excepción sin motivo escrito es una lista disfrazada; la clave es `archivo:nombre`
# y no sólo el nombre, porque `DEFAULT_ACCOUNT_ID` existe en tres archivos y en dos de
# ellos SÍ tiene que estar cableado.
_IDS_SOLO_DECLARATIVOS: dict[str, str] = {
    "analysis/harness_config.py:LEGACY_ACCOUNT_ID": (
        "documenta de qué cuenta heredaron su config los harness T7→T13. No es un "
        "parámetro de nada —esos runners corren sobre el cohorte, no sobre una cuenta—, "
        "así que no hay dónde cablearla; su hermana `LEGACY_MAX_POSITIONS` sí lo es y la "
        "leen cuatro runners, y esa asimetría es justamente lo que había que decidir"
    ),
}


def _usos_en_el_modulo(arbol, nombre: str) -> int:
    """Cuántas veces se **lee** ``nombre`` en ese árbol (sin contar la asignación)."""
    import ast

    return sum(
        1
        for n in ast.walk(arbol)
        if isinstance(n, ast.Name) and n.id == nombre and isinstance(n.ctx, ast.Load)
    )


def _importadores_de(nombre: str, modulo: str) -> list[str]:
    """Módulos del proyecto que hacen ``from <modulo> import <nombre>``.

    Importar la constante **es** usarla: `harvest_catalysts.DEFAULT_ACCOUNT_ID` no se lee
    en su propio archivo y lo consume `build_surprise_profiles`, que es legítimo. Se
    compara el **módulo** y no sólo el nombre: sin eso, un único
    ``from scripts.harvest_catalysts import DEFAULT_ACCOUNT_ID`` haría pasar por usadas a
    las tres constantes homónimas — lo comprobé escribiendo el barrido, que en su primera
    versión daba exactamente ese falso negativo.
    """
    import ast
    from pathlib import Path

    raiz = Path(__file__).resolve().parent.parent
    out: list[str] = []
    for paquete in _PAQUETES:
        for p in sorted((raiz / paquete).rglob("*.py")):
            rel = p.relative_to(raiz).as_posix()
            if rel.replace("/", ".").removesuffix(".py") == modulo:
                continue
            try:
                arbol = ast.parse(p.read_text(encoding="utf-8"))
            except SyntaxError:  # pragma: no cover
                continue
            for n in ast.walk(arbol):
                if (
                    isinstance(n, ast.ImportFrom)
                    and n.module == modulo
                    and any(a.name == nombre for a in n.names)
                ):
                    out.append(rel)
                    break
    return out


def _constantes_muertas() -> list[str]:
    """``archivo:nombre`` de cada constante de cuenta que **nadie lee** (tarea 229)."""
    import ast
    from pathlib import Path

    raiz = Path(__file__).resolve().parent.parent
    muertas = []
    for arch, nombre, _valor in _constantes_de_cuenta():
        if f"{arch}:{nombre}" in _IDS_SOLO_DECLARATIVOS:
            continue
        arbol = ast.parse((raiz / arch).read_text(encoding="utf-8"))
        if _usos_en_el_modulo(arbol, nombre):
            continue
        if _importadores_de(nombre, arch.replace("/", ".").removesuffix(".py")):
            continue
        muertas.append(f"{arch}:{nombre}")
    return muertas


def test_ninguna_constante_de_modulo_clava_un_id_de_cuenta():
    """Regresión del arreglo de la 70, **reescrita como predicado** (tarea 147).

    Estaba escrito ``assert "DEFAULT_ACCOUNT_ID = 1" not in txt`` sobre una lista
    parametrizada de **tres** archivos, y fallaba en las dos direcciones:

    * **falso negativo** — cualquier archivo nuevo nace afuera de la lista. Es por
      donde pasó la tarea **128**: `run_universe_screen_validation.py` tenía ese
      literal exacto y **no estaba** en los tres;
    * **falso positivo** — el mismo patrón, escribiendo el docstring de la 128, acusó
      a una línea de **prosa** que citaba el defecto arreglado. Grep no distingue
      código de comentario.

    Ahora es AST sobre ocho paquetes, y las dos constantes legítimas están declaradas
    **por símbolo** con su motivo, no por archivo.
    """
    culpables = [
        f"{arch}: {nombre} = {valor!r}"
        for arch, nombre, valor in _constantes_de_cuenta()
        if isinstance(valor, int) and not isinstance(valor, bool) and nombre not in _IDS_DECLARADOS
    ]
    assert not culpables, (
        "estas constantes de módulo clavan un id de cuenta. El default tiene que ser "
        "None y resolverse contra `is_active` (tareas 70, 99 y 147):\n  " + "\n  ".join(culpables)
    )


def test_los_tres_jobs_de_fondo_siguen_defaulteando_a_None():
    """Contraprueba: que el de arriba no pase porque el barrido **no miró nada**.

    Éstos son los tres que la 70 arregló, y el `None` es el arreglo. Si el barrido
    dejara de encontrarlos —un rename, un `ast` que falla— el test de arriba pasaría
    igual de verde sobre una población vacía.
    """
    encontrados = {
        arch: valor for arch, nombre, valor in _constantes_de_cuenta() if nombre == "DEFAULT_ACCOUNT_ID"
    }
    for esperado in ("scripts/harvest_catalysts.py", "scripts/news_feed.py", "scripts/dashboard_data.py"):
        assert esperado in encontrados, f"{esperado} dejó de declarar DEFAULT_ACCOUNT_ID"
        assert encontrados[esperado] is None, f"{esperado} volvió a clavar un id"


def test_cada_id_declarado_dice_por_que():
    """Una excepción por símbolo sin motivo escrito es una lista disfrazada."""
    nombres = {n for _, n, _ in _constantes_de_cuenta()}
    for nombre, motivo in _IDS_DECLARADOS.items():
        assert len(motivo) > 40, f"{nombre} sin motivo escrito"
        assert nombre in nombres, f"{nombre} ya no existe: sacalo de _IDS_DECLARADOS"


# ── Que la constante se USE, y no sólo que esté declarada (tarea 229) ────────


def test_ninguna_constante_de_cuenta_esta_DECLARADA_Y_MUERTA():
    """El guard que faltaba, y el que habría cazado la **228** el 2026-09-01.

    Los dos tests de arriba miran que la constante **exista** y que su **valor** sea
    `None`. Ninguno mira que **se lea**, y ésa es la propiedad que importa: un
    `DEFAULT_ACCOUNT_ID = None` declarado y muerto aprueba los dos exactamente igual que
    uno cableado, mientras el módulo defaultea por su cuenta a otra cosa. Es
    [[guard-no-puede-usar-de-verdad-lo-que-chequea]]: el guard medía el artefacto barato
    de verificar en lugar de la propiedad.

    Así vivió la 228 durante 22 días — ``scripts/dashboard_data.py`` declaraba la
    constante con el valor correcto, argparse tenía su propio literal, y el CLI devolvía
    ``{"error": "account None not found"}`` con el guard en verde.

    **El barrido destapó dos más**, que es por lo que el alcance decía que era el primer
    paso y no el último: ``scripts/news_feed.py`` tenía la misma forma (cableada acá) y
    ``analysis/harness_config.py:LEGACY_ACCOUNT_ID`` está muerta a propósito (declarada
    en ``_IDS_SOLO_DECLARATIVOS`` con el motivo).
    """
    muertas = _constantes_muertas()
    assert not muertas, (
        "estas constantes de cuenta están declaradas y no las lee nadie, así que el "
        "módulo defaultea por otro lado y cambiarlas no hace nada (tareas 228 y 229). "
        "Cableala, o declarala en _IDS_SOLO_DECLARATIVOS con el motivo:\n  " + "\n  ".join(muertas)
    )


def test_el_guard_nuevo_CAZA_el_defecto_REAL_de_la_228():
    """Se valida contra el defecto que existió, no contra uno inventado.

    La forma fuerte sería leer el archivo de antes del commit de la 228, pero atar un
    test a un hash lo rompe en un clone shallow o en un export. Acá se **reconstruye** el
    estado viejo aplicando al archivo **real** la edición inversa exacta —volver
    ``default=DEFAULT_ACCOUNT_ID`` a ``default=None``— y se exige que el predicado lo
    acuse. Es fuente real, sin depender del historial.

    Es la forma que usó la **215** con la 213: un guard cuyo kill-criteria es poner en
    rojo el defecto concreto que lo motivó. Sin esto, un guard puede quedar verde sobre
    una población en la que el defecto ya no está y nadie sabría si alguna vez lo cazó.
    """
    import ast
    from pathlib import Path

    raiz = Path(__file__).resolve().parent.parent
    fuente = (raiz / "scripts" / "dashboard_data.py").read_text(encoding="utf-8")

    # La 228 cableó la constante en DOS lugares, así que la reconstrucción revierte los
    # dos. Que los `count` estén asserteados no es decoración: si alguien renombra o
    # reordena, una sustitución que no matchea reconstruiría un archivo idéntico al de
    # hoy y este test saldría verde sin haber probado nada — el falso negativo que la
    # 221 se comió en su propio barrido de mutación.
    reversos = [
        ("default=DEFAULT_ACCOUNT_ID,", "default=None,"),
        ("account_id: int | None = DEFAULT_ACCOUNT_ID", "account_id: int"),
    ]
    viejo = fuente
    for actual, previo in reversos:
        assert fuente.count(actual) == 1, f"cambió el cableado ({actual!r}): revisá esta reconstrucción"
        viejo = viejo.replace(actual, previo)

    assert _usos_en_el_modulo(ast.parse(fuente), "DEFAULT_ACCOUNT_ID") > 0, "el archivo de hoy la usa"
    assert _usos_en_el_modulo(ast.parse(viejo), "DEFAULT_ACCOUNT_ID") == 0, (
        "el guard NO caza el estado de antes de la 228: está midiendo otra cosa"
    )


def test_cada_constante_solo_declarativa_dice_por_que_y_sigue_existiendo():
    """Misma regla que ``_IDS_DECLARADOS``: sin motivo escrito es una lista disfrazada.

    Y la otra dirección, que es la que evita que la lista se vuelva basura: si la
    constante dejó de existir —o alguien la cableó— la excepción sobra y hay que
    sacarla, o el guard queda con un agujero permanente por una entrada fantasma.
    """
    presentes = {f"{arch}:{nombre}" for arch, nombre, _ in _constantes_de_cuenta()}
    for clave, motivo in _IDS_SOLO_DECLARATIVOS.items():
        assert len(motivo) > 40, f"{clave} sin motivo escrito"
        assert clave in presentes, f"{clave} ya no existe: sacalo de _IDS_SOLO_DECLARATIVOS"
        arch, nombre = clave.rsplit(":", 1)
        import ast
        from pathlib import Path

        arbol = ast.parse((Path(__file__).resolve().parent.parent / arch).read_text(encoding="utf-8"))
        assert _usos_en_el_modulo(arbol, nombre) == 0, f"{clave} ahora SÍ se usa: sacalo de la lista"


def test_el_barrido_de_importadores_compara_el_MODULO_y_no_solo_el_nombre():
    """El falso negativo que tuvo la primera versión del barrido, fijado.

    ``DEFAULT_ACCOUNT_ID`` se declara en **tres** archivos. Mirando sólo el nombre
    importado, el único ``from scripts.harvest_catalysts import DEFAULT_ACCOUNT_ID`` de
    ``build_surprise_profiles`` daba por usadas a las tres — y el guard habría nacido
    ciego a la 228, que es lo que venía a cazar.
    """
    de_harvest = _importadores_de("DEFAULT_ACCOUNT_ID", "scripts.harvest_catalysts")
    de_news = _importadores_de("DEFAULT_ACCOUNT_ID", "scripts.news_feed")

    assert "scripts/build_surprise_profiles.py" in de_harvest
    assert de_news == [], "el import de harvest_catalysts se le está atribuyendo a news_feed"


def test_el_scheduler_resuelve_los_dos_jobs_contra_is_active():
    """Los dos jobs del scheduler (dashboard y rebuild de surprise) pasan por el
    mismo resolver, y **saltean** si no hay cuenta viva."""
    from pathlib import Path

    txt = (Path(__file__).resolve().parent.parent / "paper_trading" / "scheduler.py").read_text(
        encoding="utf-8"
    )
    assert 'settings.get("dashboard_refresh_account_id", 1)' not in txt
    assert 'settings.get("surprise_build_account_id", 1)' not in txt
    assert txt.count("_job_account_id(") >= 3  # la def + los dos jobs
    assert txt.count("if account_id is None:") >= 2  # los dos saltean


def test_el_harvest_sin_flag_usa_la_cuenta_viva(test_db):
    """La punta que más dolía: el universo del harvest sale de la cuenta viva."""
    from scripts.harvest_catalysts import resolve_account_id

    _cuenta("Pausada", activa=False)
    viva = _cuenta("Viva", activa=True)
    assert resolve_account_id() == viva
    assert resolve_account_id(123) == 123  # un id explícito se respeta


# ── El artifact del dashboard ────────────────────────────────────────────────


def test_el_artifact_neutro_gana_pero_el_legacy_es_el_fallback(monkeypatch, tmp_path):
    """El nombre `sim-principal` quedó mintiendo, pero cambiar la constante a secas
    habría hecho que `targets_ready()` diera False y el refresh se saltease **en
    silencio** — cambiar una falla silenciosa por otra."""
    import scripts.refresh_dashboard as rd

    neutro = tmp_path / "finanzias-dashboard" / "index.html"
    legacy = tmp_path / "finanzias-sim-principal-dashboard" / "index.html"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("x", encoding="utf-8")
    monkeypatch.setattr(rd, "ARTIFACT_NEUTRAL", neutro)
    monkeypatch.setattr(rd, "ARTIFACT_LEGACY", legacy)

    assert rd.default_artifact() == legacy  # hoy: sólo existe el legacy

    neutro.parent.mkdir(parents=True)
    neutro.write_text("x", encoding="utf-8")
    assert rd.default_artifact() == neutro  # el día que se renombre la carpeta
