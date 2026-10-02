"""Rachas de scans fallidos, por cuenta (tarea 263).

Un ``run_scan`` que lanzaba una excepción no quedaba en el log ni llegaba a Slack: el worker
la convertía en una señal y la UI mostraba 10 segundos de barra de estado. Si el scan fallaba
siempre —una migración, un esquema, un import— la cuenta dejaba de operar y de correr stops
sin que nadie se enterara (``docs/auditoria_operacion_2026-10-02.md`` [H-2]).

Esto decide **cuándo avisar**, con el patrón del outage de Yahoo (NET1): un aviso con la
primera falla de una racha y otro con el primer scan que vuelve a completar. Las fallas del
medio no avisan: un scan cada 15 minutos que falla toda la noche no son 40 mensajes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from database.models import utcnow_naive


@dataclass
class _Racha:
    desde: datetime
    n: int = 0


@dataclass
class RachasDeScan:
    """Estado por cuenta. Puro salvo el reloj, que se inyecta para los tests."""

    _rachas: dict[int, _Racha] = field(default_factory=dict)

    def fallo(self, account_id: int, ahora: datetime | None = None) -> bool:
        """Registra una falla; ``True`` si es la PRIMERA de la racha (hay que avisar)."""
        r = self._rachas.get(account_id)
        if r is None:
            self._rachas[account_id] = _Racha(desde=ahora or utcnow_naive(), n=1)
            return True
        r.n += 1
        return False

    def exito(self, account_id: int, ahora: datetime | None = None) -> tuple[int, float] | None:
        """Registra un scan completo; si cerraba una racha, ``(fallas, minutos)``."""
        r = self._rachas.pop(account_id, None)
        if r is None:
            return None
        minutos = ((ahora or utcnow_naive()) - r.desde).total_seconds() / 60.0
        return r.n, minutos

    def en_falla(self, account_id: int) -> int:
        """Cuántas fallas lleva la racha abierta de la cuenta (0 = ninguna)."""
        r = self._rachas.get(account_id)
        return r.n if r else 0
