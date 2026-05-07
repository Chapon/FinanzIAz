"""
Lightweight i18n shim for FinanzIAs.

The codebase currently has ~600+ Spanish strings hard-coded in UI files.
A full migration to Qt Linguist (.ts/.qm) is invasive — out of scope for
this iteration. This module provides the *plumbing* so call sites can be
migrated incrementally and the eventual switch to gettext / Qt Linguist is
just a swap of the ``_`` implementation, not a global find-and-replace.

Public API
----------
``_(text)``           Translate ``text`` to the active language. Defaults
                      to identity (returns the string unchanged) until a
                      real catalog is wired up.
``set_language(code)``  Change active language; ``code`` ∈ {"es", "en"}.
``current_language()``  Return the active language code.
``register_catalog(code, mapping)``  Register a small in-memory catalog
                      (used by tests / the future translation tooling).

Migration recipe
----------------
Wherever you previously wrote ``"Agregar Acción"``, write
``_("Agregar Acción")``. The string remains Spanish at the call site
(so context is preserved) and identity-translation means nothing breaks.
When a real ``en`` catalog is added, those calls will pick it up.
"""
from __future__ import annotations

import threading
from typing import Optional

# Default language is Spanish — that's what the app currently ships in.
_DEFAULT_LANG = "es"

_lock = threading.Lock()
_lang = _DEFAULT_LANG
_catalogs: dict[str, dict[str, str]] = {
    "es": {},   # identity (no translation needed; original strings are Spanish)
    "en": {},   # to be populated when an English catalog is built
}


def set_language(code: str) -> None:
    """Activate ``code`` (e.g. 'es', 'en'). Falls back silently to default."""
    global _lang
    if not isinstance(code, str):
        return
    with _lock:
        _lang = code if code in _catalogs else _DEFAULT_LANG


def current_language() -> str:
    return _lang


def register_catalog(code: str, mapping: dict[str, str]) -> None:
    """
    Register a translation catalog. Mapping is ``{source_text: translation}``.
    Call once at app startup (or in tests). Existing keys are overwritten.
    """
    if not isinstance(code, str) or not isinstance(mapping, dict):
        return
    with _lock:
        existing = _catalogs.setdefault(code, {})
        existing.update({str(k): str(v) for k, v in mapping.items()})


def translate(text: str) -> str:
    """Return ``text`` rendered in the current language. Falls back to source."""
    if not isinstance(text, str):
        return text
    cat = _catalogs.get(_lang) or {}
    return cat.get(text, text)


# Conventional alias used at every call site.
_ = translate
