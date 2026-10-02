# Auditoría — seguridad — 2026-10-02

Tarea **272**. Primera revisión de seguridad del repo. READ-ONLY. Kill-criteria congelado en `docs/auditoria_tanda_killcriteria_2026-10-02.md` §1.

## 1. Alcance real

**Mirado:**
- **La historia entera de git** (`git log -p --all --text`, unas 464k líneas), con un barrido de patrones de secreto: tokens de Slack `xox*`, keys de AWS, tokens de GitHub, keys `sk-`, claves privadas, asignaciones `api_key`/`token`/`secret`/`password` a literales largos, y webhooks de Slack.
  - **Instrumento validado:** detecta 3 de 3 secretos sintéticos.
  - **Corregido en el camino:** la primera pasada cortó en *«Binary file matches»* y estaba incompleta; se repitió con `-a`.
- **Sumideros peligrosos** en el código no-test: `eval`, `exec`, `shell=True`, `os.system`, `pickle`/`yaml.load`, y SQL armado con f-string o `%`.
- **Los dos workflows de `.github/`:** triggers, permisos y secretos.
- **El log vivo** (`finanzias.log`, `.log.1`), buscando valores de credenciales.
- **Datos personales** en archivos versionados.
- **Los archivos sensibles versionados** (`.db`, `settings.json` del usuario, `.pem`, `credentials`).

**NO mirado:**
- Dependencias con CVE conocidos. Motivo: va en `dependencias` (§7 de la tanda).
- La seguridad de los servicios de terceros y de la máquina.
- El contenido de los backups. Motivo: están fuera del repo, y su integridad va en `operacion`.

## 2. Hallazgos

### [S-2] La API key de Finnhub queda en texto plano en el log, dentro de las URLs de las excepciones de `requests`
Severidad: **MEDIUM** · Confianza: **ALTA**

**Ubicación:** los llamados a Finnhub de `data/news_sources.py` (y cualquier proveedor que mande la key como query string, `?token=`).

**Evidencia:** `grep -c 'token=[A-Za-z0-9]{12,}'` da **240** líneas en `finanzias.log` y **208** en `.log.1`. Ejemplo, con el valor enmascarado:

```
MaxRetryError: HTTPSConnectionPool(host='finnhub.io', ...): Max retries exceeded with url: /api/v1/company-news?symbol=ABBV&from=2026-09-15&to=2026-09-22&token=<REDACTADO>
```

**Razonamiento:** cuando un pedido falla, `urllib3`/`requests` arman el mensaje con la URL completa, y el `log.exception` del llamador la escribe tal cual.

**Impacto:** el log está fuera del repo (`~/.finanzias/`), pero es lo primero que se comparte cuando algo falla: se pega en un chat, se adjunta a un issue o se manda a un agente. La key viaja con él.

**Acción:**
1. Mandar la key por header (Finnhub acepta `X-Finnhub-Token`) o enmascarar `token=` con un filtro de logging.
2. Revisar si Tiingo y otros proveedores hacen lo mismo.
3. **Rotar la key es decisión de Chapa.**

→ tarea **276**.

### [S-1] El primer segmento del token de Slack (el id del workspace) está versionado en un repo público
Severidad: **LOW** · Confianza: **ALTA**

**Ubicación:** `scripts/setup_slack.py:54`, un docstring: `xoxb-3770039559041-… — muestra solo el prefijo`.

**Evidencia:**
- El token vivo de `SLACK_BOT_TOKEN` empieza con ese prefijo (comparado sin imprimir el token).
- Está versionado desde `c5a69b4` (2026-05-23).

**Razonamiento:** un token `xoxb` es `xoxb-<workspace>-<bot>-<secreto>`. Lo versionado es sólo el identificador del workspace: **no es una credencial** y no permite nada por sí solo. El segmento secreto no aparece en ninguna revisión.

**Impacto:** chico. Identifica el workspace en un repo público.

**Acción:** reemplazar el ejemplo por un prefijo ficticio (`xoxb-0000…`).

→ tarea **276**, en el mismo enunciado.

## 3. Barrido limpio en lo demás

- **Secretos en la historia:** fuera de S-1, ninguno. Las keys de Tiingo, Finnhub y Slack se leen del entorno (`data/news_sources.py:472`, `data/providers.py:209/319/346`, `scripts/setup_slack.py:128`); `setup_slack.py` sólo lee el token e indica cargarlo con `setx`, y no escribe ningún archivo.
- **Sumideros:**
  - los `exec()` son de diálogos de Qt;
  - el SQL con f-string arma placeholders `?` (`scripts/archive_price_cache.py:102`) o usa constantes de una migración (`alembic/versions/0012…`);
  - el único `pickle.loads` (`scripts/run_stop_value_t37.py:250`) lee un cache que escribe el mismo script.

  Ninguna entrada externa llega a un sumidero.
- **Entradas no confiables:**
  - El texto de las noticias entra al prompt de qwen. Una inyección puede cambiar una **clasificación** o el **briefing**, que son display (la 255 y la 258 midieron que el tono no predice). Nada de la salida del LLM se ejecuta ni decide una orden.
  - El CSV importado se parsea a números y tickers.
- **Workflows:**
  - `ci.yml` corre en `pull_request` (no `pull_request_target`), con `contents: read`.
  - El probe de la 196 es `workflow_dispatch` y sólo expone `SEC_EDGAR_USER_AGENT`.
  - Ningún job corre código de un PR ajeno con permisos de escritura.
- **Archivos sensibles:** no hay `.db`, settings del usuario, logs ni claves versionados. `.claude/settings.json` es la config de permisos del proyecto.
- **El email personal en `setup_github.ps1`:** no es un hallazgo. Los 645 commits del repo ya lo llevan como autor, así que el archivo no expone nada que no esté público.
- **El commit `39455b5`** (*«Agent host session … baseline checkpoint»*, 2026-09-02) existe sólo como objeto local, en ninguna rama publicada (`git ls-remote` muestra sólo `main`).

## 4. Hallazgos rechazados

- Ninguno. La primera pasada del barrido de historia se **descartó como instrumento**, no como hallazgo: cortaba en contenido binario.

## 5. Mapeo hallazgo → tarea

| hallazgo | tarea |
|---|---|
| S-2 | 276 |
| S-1 | 276 |
