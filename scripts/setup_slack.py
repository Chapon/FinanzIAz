"""
Activa y prueba las notificaciones de Slack del motor (roadmap T12).

Qué hace
--------
1. Lee el bot token de la env var ``SLACK_BOT_TOKEN`` (NUNCA se guarda en
   disco ni en settings.json — solo vive en el entorno).
2. Manda un mensaje de prueba al canal vía ``chat.postMessage`` (la misma API
   que usa el motor) y muestra la respuesta exacta de Slack.
3. Si Slack responde OK, escribe en ``~/.finanzias/settings.json``:
       slack_channel               = <canal>
       slack_notify_on             = <pending|filled|both>
       slack_notifications_enabled = True
   Si la prueba falla, NO toca los settings (no se activa algo roto).

Uso
---
    # 1) seteá el token en el entorno (Windows, persistente para nuevos procesos):
    setx SLACK_BOT_TOKEN "xoxb-..."
    setx SLACK_CHANNEL   "#finanzias"      # opcional; si no, pasalo con --channel

    # 2) abrí una consola NUEVA (setx no afecta la consola actual) y corré:
    python scripts/setup_slack.py
    python scripts/setup_slack.py --channel "#finanzias" --notify-on both

Notas
-----
- El bot tiene que estar invitado al canal (`/invite @TuBot` en Slack), sino
  Slack devuelve ``not_in_channel`` y la prueba falla a propósito.
- El token se enmascara en pantalla; no se imprime entero.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Permitir ``python scripts/setup_slack.py`` desde la raíz del repo sin install.
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from integrations.slack import (
    NOTIFY_ON_CHOICES,
    SLACK_CHANNEL_ENV,
    SLACK_POST_MESSAGE_URL,
    SLACK_TOKEN_ENV,
)


def _mask(token: str) -> str:
    """xoxb-3770039559041-… — muestra solo el prefijo, oculta el secreto."""
    if not token:
        return "<vacío>"
    head = token[:14]
    return f"{head}…({len(token)} chars)"


def _send_test(token: str, channel: str) -> tuple[bool, str]:
    """
    POST de prueba a chat.postMessage. Devuelve (ok, detalle). A diferencia del
    ``post_to_slack`` del runtime (que es fail-open silencioso), acá queremos
    ver el error crudo de Slack para diagnosticar el setup.
    """
    try:
        import requests
    except ImportError:
        return False, "falta el paquete 'requests' (pip install requests)."

    text = (
        ":white_check_mark: *FinanzIAs* — prueba de notificaciones Slack OK. "
        "Si ves este mensaje, el bot token y el canal están bien configurados."
    )
    try:
        resp = requests.post(
            SLACK_POST_MESSAGE_URL,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json; charset=utf-8",
            },
            json={"channel": channel, "text": text},
            timeout=10,
        )
    except Exception as exc:
        return False, f"error de red: {exc}"

    try:
        payload = resp.json()
    except ValueError:
        return False, f"respuesta no-JSON (HTTP {resp.status_code})."

    if payload.get("ok"):
        return True, f"mensaje enviado al canal '{payload.get('channel', channel)}'."
    return False, f"Slack respondió error='{payload.get('error', 'desconocido')}'."


_ERROR_HINTS = {
    "not_in_channel": "Invitá el bot al canal: en Slack escribí  /invite @TuBot",
    "channel_not_found": "Revisá el nombre/ID del canal. Para canales privados usá el ID (Cxxxx).",
    "invalid_auth": "El token es inválido o fue revocado. Regeneralo en OAuth & Permissions.",
    "missing_scope": "A la app le falta el scope chat:write. Agregalo y reinstalá la app.",
    "token_revoked": "El token fue revocado. Generá uno nuevo y volvé a exportarlo.",
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Activa y prueba Slack para FinanzIAs.")
    parser.add_argument(
        "--channel",
        default=os.environ.get(SLACK_CHANNEL_ENV, ""),
        help=f"Canal destino (#nombre o ID). Default: env {SLACK_CHANNEL_ENV}.",
    )
    parser.add_argument(
        "--notify-on",
        default="both",
        choices=NOTIFY_ON_CHOICES,
        help="Qué órdenes notifican (default: both).",
    )
    parser.add_argument(
        "--no-activate",
        action="store_true",
        help="Solo probar el envío; no tocar settings.json.",
    )
    args = parser.parse_args()

    token = os.environ.get(SLACK_TOKEN_ENV, "")
    channel = args.channel.strip()

    print("FinanzIAs · setup de notificaciones Slack")
    print("-" * 60)
    print(f"Token ({SLACK_TOKEN_ENV}): {_mask(token)}")
    print(f"Canal              : {channel or '<vacío>'}")
    print(f"notify_on          : {args.notify_on}")
    print("-" * 60)

    if not token:
        print(f"ERROR: no está seteada la env var {SLACK_TOKEN_ENV}.")
        print('  Windows:  setx SLACK_BOT_TOKEN "xoxb-..."   (y abrí una consola NUEVA)')
        return 2
    if not channel:
        print(f"ERROR: falta el canal. Pasá --channel o seteá {SLACK_CHANNEL_ENV}.")
        return 2

    print("Enviando mensaje de prueba…")
    ok, detail = _send_test(token, channel)
    print(("  OK — " if ok else "  FALLÓ — ") + detail)

    if not ok:
        for code, hint in _ERROR_HINTS.items():
            if code in detail:
                print(f"  Sugerencia: {hint}")
                break
        print("\nNo se activaron los settings (la prueba no pasó).")
        return 1

    if args.no_activate:
        print("\n--no-activate: prueba OK, settings sin tocar.")
        return 0

    # Activar settings solo si la prueba pasó.
    from config.settings_manager import settings

    settings.set("slack_channel", channel)
    settings.set("slack_notify_on", args.notify_on)
    settings.set("slack_notifications_enabled", True)
    print("\nSettings activados en ~/.finanzias/settings.json:")
    print(f"  slack_channel               = {settings.get('slack_channel')}")
    print(f"  slack_notify_on             = {settings.get('slack_notify_on')}")
    print(f"  slack_notifications_enabled = {settings.get('slack_notifications_enabled')}")
    print("\nListo. El próximo run_scan que genere órdenes te va a avisar por Slack.")
    print("Recordá reiniciar la app si estaba abierta (toma el token al arrancar).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
