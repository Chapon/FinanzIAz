"""Abrir una base SQLite **sólo para leer** sin dejar rastro — tarea 191.

Nueve scripts que sólo hacen ``SELECT`` abrían con ``sqlite3.connect(path)``, o sea en
lectura-escritura. Uno de ellos (``run_exposure_cap_replay``) tiene como default el backup más
nuevo de ``backups/``, y otro (``run_catalyst_exit_veto_backtest``) pide en su ayuda que se lo
corra sobre un backup. Un backup es, por definición, algo que no se toca.

**``mode=ro`` solo no alcanza, y está medido.** Sobre una base en modo WAL, una conexión
``mode=ro`` **crea** ``-shm`` y ``-wal`` al lado y **no los borra al cerrar** —no puede
checkpointear—, mientras que una conexión read-write sí los limpia. Es exactamente el rastro que
la tarea 188 encontró en dos backups, dejado por el smoke test de la suite, que los abría en
solo lectura. ``immutable=1`` le dice a SQLite que el archivo no cambia: no toma locks ni crea
side files.

**Por qué ``immutable`` no es incondicional:** sobre la DB **viva** ignora el WAL, que es donde
están los commits recientes, y leería un estado viejo sin avisar. Por eso se aplica sólo a una
base que vive en un directorio ``backups`` — los que produce ``database/backup.py`` con la API de
backup de SQLite, que deja todo en el archivo principal.

**Lo que queda dicho:** sobre la DB viva con la app **cerrada**, la conexión ``mode=ro`` deja un
``-wal`` vacío y un ``-shm`` al lado de ``finanzias.db``. Es inocuo —la próxima apertura
read-write de la app los recupera—, y es el precio de que un script de lectura no pueda escribir.
"""

from __future__ import annotations

from pathlib import Path


def readonly_uri(db: str | Path) -> str:
    """URI para ``sqlite3.connect(..., uri=True)``: ``mode=ro``, más ``immutable=1`` en un backup."""
    p = Path(db).resolve()
    inmutable = "backups" in p.parts
    return f"file:{p.as_posix()}?mode=ro" + ("&immutable=1" if inmutable else "")
