"""
Helpers de formateo de fechas/horas para la UI.

Todos los timestamps en la DB se guardan como **naive UTC** (ver
``database.models.utcnow_naive``). Si se formatean directo con
``strftime`` el usuario ve hora UTC, lo cual en Argentina (UTC-3)
implica un desfasaje de 3 horas — ej.: una orden ejecutada a las
11:10 ART se ve como 14:10. Este módulo centraliza la conversión
naive-UTC → zona local del sistema para que todas las pestañas
muestren la hora "del reloj de pared".
"""

from __future__ import annotations

from datetime import datetime, timezone


def fmt_local(dt: datetime | None, fmt: str = "%d/%m %H:%M") -> str:
    """
    Formatea un ``datetime`` naive-UTC en la zona horaria local del sistema.

    Si ``dt`` es ``None`` devuelve ``"—"``. Si ya viene tz-aware se respeta su
    tzinfo; si es naive se asume UTC (que es como la app persiste todo).

    Parameters
    ----------
    dt : datetime | None
        Timestamp a formatear. Naive se interpreta como UTC.
    fmt : str
        ``strftime`` format string. Default ``"%d/%m %H:%M"``.

    Returns
    -------
    str
        El timestamp formateado en hora local, o ``"—"`` si ``dt`` es ``None``.
    """
    if dt is None:
        return "—"
    aware = dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)
    # ``astimezone()`` sin argumento convierte a la zona local del sistema.
    return aware.astimezone().strftime(fmt)
