"""
Tests for the schema-validated settings manager (``config.settings_manager``).

Covers:
- Defaults are loaded when no file exists.
- Bad / corrupt JSON falls back gracefully.
- Per-key validation rejects out-of-range / wrong-type values.
- Choices and the HHMM custom validator both fire.
"""

from __future__ import annotations

import json

from config.settings_manager import DEFAULTS, _SettingsManager


def _new_manager(tmp_path, monkeypatch):
    monkeypatch.setattr("config.settings_manager._CONFIG_PATH", tmp_path / "settings.json")
    return _SettingsManager()


def test_defaults_loaded_when_no_file(tmp_path, monkeypatch):
    s = _new_manager(tmp_path, monkeypatch)
    for key, default in DEFAULTS.items():
        assert s.get(key) == default


def test_corrupt_json_falls_back_to_defaults(tmp_path, monkeypatch):
    cfg = tmp_path / "settings.json"
    cfg.write_text("this is not json{}", encoding="utf-8")
    monkeypatch.setattr("config.settings_manager._CONFIG_PATH", cfg)
    s = _SettingsManager()
    # Should not have raised; sane defaults available.
    assert s.get("notif") is True


def test_validation_rejects_wrong_type(tmp_path, monkeypatch):
    s = _new_manager(tmp_path, monkeypatch)
    assert s.set("paper_scan_interval_minutes", "fast") is False
    # Value must remain the default.
    assert s.get("paper_scan_interval_minutes") == DEFAULTS["paper_scan_interval_minutes"]


def test_validation_rejects_out_of_range(tmp_path, monkeypatch):
    s = _new_manager(tmp_path, monkeypatch)
    assert s.set("paper_scan_interval_minutes", 0) is False
    assert s.set("paper_scan_interval_minutes", 99_999) is False
    assert s.set("paper_scan_interval_minutes", 30) is True


def test_validation_choices_for_history_period(tmp_path, monkeypatch):
    s = _new_manager(tmp_path, monkeypatch)
    assert s.set("paper_history_period", "999y") is False
    assert s.set("paper_history_period", "1y") is True


def test_validation_hhmm_format(tmp_path, monkeypatch):
    s = _new_manager(tmp_path, monkeypatch)
    assert s.set("paper_daily_scan_time_et", "25:00") is False
    assert s.set("paper_daily_scan_time_et", "9:30") is False  # missing leading zero
    assert s.set("paper_daily_scan_time_et", "09:30") is True


def test_load_discards_invalid_keys_and_rewrites_file(tmp_path, monkeypatch):
    cfg = tmp_path / "settings.json"
    cfg.write_text(
        json.dumps(
            {
                "notif": True,
                "paper_scan_interval_minutes": "garbage",  # invalid → dropped
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("config.settings_manager._CONFIG_PATH", cfg)
    s = _SettingsManager()
    assert s.get("notif") is True
    assert s.get("paper_scan_interval_minutes") == DEFAULTS["paper_scan_interval_minutes"]
    # File on disk should have been rewritten without the bad key.
    on_disk = json.loads(cfg.read_text(encoding="utf-8"))
    assert on_disk["paper_scan_interval_minutes"] == DEFAULTS["paper_scan_interval_minutes"]


def test_bool_int_distinction(tmp_path, monkeypatch):
    """Don't accept ``True`` where an ``int`` is expected (bool is subclass of int)."""
    s = _new_manager(tmp_path, monkeypatch)
    assert s.set("paper_scan_interval_minutes", True) is False


def test_feature_toggles_sprint1_persist(tmp_path, monkeypatch):
    """Sprint 1: feature toggles (hmm, stacking, xgb, vol_overlay).
    (correlation_gate_enabled was removed in Sprint 3 — see
    docs/sprint2_kill_criteria.md.)"""
    s = _new_manager(tmp_path, monkeypatch)
    toggles = ["hmm_enabled", "stacking_enabled", "xgb_signal_enabled", "vol_overlay_enabled"]

    # All default to True
    for toggle in toggles:
        assert s.get(toggle) is True

    # All can be set to False
    for toggle in toggles:
        assert s.set(toggle, False) is True
        assert s.get(toggle) is False

    # Reload from disk — values persist
    s2 = _SettingsManager()
    for toggle in toggles:
        assert s2.get(toggle) is False

    # Can't set to non-bool
    assert s.set("hmm_enabled", "yes") is False
    assert s.get("hmm_enabled") is False  # unchanged
