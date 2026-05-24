"""
Create / edit dialog for paper-trading accounts.

Self-contained QDialog — no dependency on the rest of ``paper_tab.py``.
Hosted under ``ui/paper/`` so the orchestrator file stays readable.
"""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QSpinBox,
    QVBoxLayout,
)

from paper_trading.account import create_account, update_account_config
from ui.styles import PALETTE


class PaperAccountDialog(QDialog):
    """Create or edit a paper-trading account.

    Pass ``account=None`` to create a new one, or a detached ``PaperAccount``
    to edit an existing one (``name`` and ``initial_capital`` become
    read-only because changing them after orders have been placed would
    invalidate the equity history).
    """

    _STRATEGY_LABELS = {
        "analyze_single": "Análisis ticker a ticker",
        "portfolio_engine": "Motor de portafolio (rebalance)",
    }
    _MODE_LABELS = {
        "auto": "Automático (ejecuta directo)",
        "manual": "Manual (requiere aprobación)",
    }
    _ALLOC_LABELS = {
        "equal_weight": "Equal Weight",
        "signal_weighted": "Ponderado por señal",
        "inverse_vol": "Inverse Volatility",
        "fixed_amount": "Monto fijo por posición",
        "vol_target": "Volatility Target",
        "kelly_fractional": "Kelly fraccional",
    }

    def __init__(self, account=None, parent=None):
        super().__init__(parent)
        self.account = account
        self.setWindowTitle("Editar cuenta paper" if account else "Nueva cuenta paper")
        self.setMinimumWidth(460)
        self._build_ui()
        if account is not None:
            self._load_from(account)

    # ── UI construction ──────────────────────────────────────────────────────
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(14)

        form = QFormLayout()
        form.setSpacing(10)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Ej: Sim Principal")
        form.addRow("Nombre *", self.name_edit)

        self.desc_edit = QLineEdit()
        self.desc_edit.setPlaceholderText("Descripción opcional")
        form.addRow("Descripción", self.desc_edit)

        self.strategy_combo = QComboBox()
        for k in ("analyze_single", "portfolio_engine"):
            self.strategy_combo.addItem(self._STRATEGY_LABELS[k], userData=k)
        self.strategy_combo.currentIndexChanged.connect(self._sync_strategy_visibility)
        form.addRow("Estrategia", self.strategy_combo)

        self.mode_combo = QComboBox()
        for k in ("auto", "manual"):
            self.mode_combo.addItem(self._MODE_LABELS[k], userData=k)
        form.addRow("Modo de ejecución", self.mode_combo)

        self.alloc_combo = QComboBox()
        for k in (
            "equal_weight",
            "signal_weighted",
            "inverse_vol",
            "fixed_amount",
            "vol_target",
            "kelly_fractional",
        ):
            self.alloc_combo.addItem(self._ALLOC_LABELS[k], userData=k)
        self.alloc_combo.currentIndexChanged.connect(self._sync_alloc_visibility)
        self.alloc_hint = QLabel("")
        self.alloc_hint.setStyleSheet(f"color: {PALETTE['text3']}; font-size: 11px;")
        self.alloc_hint.setWordWrap(True)
        form.addRow("Asignación", self.alloc_combo)
        form.addRow("", self.alloc_hint)

        self.max_pos_spin = QSpinBox()
        self.max_pos_spin.setRange(1, 50)
        self.max_pos_spin.setValue(5)
        form.addRow("Máx. posiciones", self.max_pos_spin)

        self.fixed_amt_spin = QDoubleSpinBox()
        self.fixed_amt_spin.setRange(0.0, 10_000_000.0)
        self.fixed_amt_spin.setDecimals(2)
        self.fixed_amt_spin.setSingleStep(100.0)
        self.fixed_amt_spin.setValue(5_000.0)
        self.fixed_amt_spin.setPrefix("$ ")
        form.addRow("Monto fijo por posición", self.fixed_amt_spin)

        self.initial_cap_spin = QDoubleSpinBox()
        self.initial_cap_spin.setRange(100.0, 100_000_000.0)
        self.initial_cap_spin.setDecimals(2)
        self.initial_cap_spin.setSingleStep(1_000.0)
        self.initial_cap_spin.setValue(50_000.0)
        self.initial_cap_spin.setPrefix("$ ")
        form.addRow("Capital inicial", self.initial_cap_spin)

        self.commission_spin = QDoubleSpinBox()
        self.commission_spin.setRange(0.0, 0.05)
        self.commission_spin.setDecimals(4)
        self.commission_spin.setSingleStep(0.0005)
        self.commission_spin.setValue(0.001)
        self.commission_spin.setSuffix("  (fracción)")
        form.addRow("Comisión", self.commission_spin)

        self.slippage_spin = QDoubleSpinBox()
        self.slippage_spin.setRange(0.0, 0.05)
        self.slippage_spin.setDecimals(4)
        self.slippage_spin.setSingleStep(0.0005)
        self.slippage_spin.setValue(0.0005)
        self.slippage_spin.setSuffix("  (fracción)")
        form.addRow("Slippage", self.slippage_spin)

        self.drift_spin = QDoubleSpinBox()
        self.drift_spin.setRange(0.01, 2.00)
        self.drift_spin.setDecimals(2)
        self.drift_spin.setSingleStep(0.05)
        self.drift_spin.setValue(0.25)
        self.drift_spin.setSuffix("  (ej. 0.25 = 25%)")
        form.addRow("Drift threshold", self.drift_spin)

        self.monthly_check = QCheckBox("Rebalance mensual de seguridad")
        self.monthly_check.setChecked(True)
        form.addRow("", self.monthly_check)

        self.active_check = QCheckBox("Cuenta activa (scheduler la escanea)")
        self.active_check.setChecked(True)
        form.addRow("", self.active_check)

        self.slack_check = QCheckBox("Notificar órdenes a Slack")
        self.slack_check.setChecked(True)
        self.slack_check.setToolTip(
            "Si está activo, esta cuenta envía un resumen a Slack cuando genera "
            "órdenes (requiere el interruptor general en Ajustes → Notificaciones "
            "Slack). Desactivá esto para silenciar solo esta cuenta."
        )
        form.addRow("", self.slack_check)

        root.addLayout(form)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self._accept)
        btns.rejected.connect(self.reject)
        root.addWidget(btns)

        self._sync_alloc_visibility()
        self._sync_strategy_visibility()

    # ── Reactivity helpers ───────────────────────────────────────────────────
    def _sync_alloc_visibility(self) -> None:
        is_fixed = self.alloc_combo.currentData() == "fixed_amount"
        self.fixed_amt_spin.setEnabled(is_fixed)

    def _sync_strategy_visibility(self) -> None:
        """``analyze_single`` honours only the volatility-based sizing modes
        (Volatility Target / Kelly fraccional); for the other modes it falls
        back to an equal cash split. Keep the combo enabled but show a hint so
        the user knows which modes actually change its behaviour."""
        is_analyze_single = self.strategy_combo.currentData() == "analyze_single"
        self.alloc_combo.setEnabled(True)
        if is_analyze_single:
            self.alloc_hint.setText(
                "analyze_single solo aplica Volatility Target y Kelly fraccional; "
                "con los demás modos reparte el cash disponible en partes iguales "
                "entre los BUY candidates."
            )
        else:
            self.alloc_hint.setText("")
        # Re-evaluate fixed_amount enablement.
        self._sync_alloc_visibility()

    # ── Edit-mode population ─────────────────────────────────────────────────
    def _load_from(self, acct) -> None:
        self.name_edit.setText(acct.name or "")
        self.name_edit.setReadOnly(True)
        self.desc_edit.setText(acct.description or "")

        def _set_combo(combo: QComboBox, key: str) -> None:
            for i in range(combo.count()):
                if combo.itemData(i) == key:
                    combo.setCurrentIndex(i)
                    return

        _set_combo(self.strategy_combo, acct.strategy)
        _set_combo(self.mode_combo, acct.mode)
        _set_combo(self.alloc_combo, acct.allocation_mode)
        self.max_pos_spin.setValue(int(acct.max_positions))
        self.fixed_amt_spin.setValue(float(acct.fixed_amount))
        self.initial_cap_spin.setValue(float(acct.initial_capital))
        self.initial_cap_spin.setEnabled(False)  # initial capital is immutable
        self.commission_spin.setValue(float(acct.commission))
        self.slippage_spin.setValue(float(acct.slippage))
        self.drift_spin.setValue(float(acct.drift_threshold))
        self.monthly_check.setChecked(bool(acct.monthly_rebalance))
        self.active_check.setChecked(bool(acct.is_active))
        # NULL (legacy) → notify ON, coherente con el comportamiento previo.
        self.slack_check.setChecked(acct.slack_notify is None or bool(acct.slack_notify))
        self._sync_alloc_visibility()

    # ── Submit ───────────────────────────────────────────────────────────────
    def _accept(self) -> None:
        name = self.name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Error", "El nombre es requerido.")
            return

        strategy = self.strategy_combo.currentData() or "analyze_single"
        mode = self.mode_combo.currentData() or "auto"
        alloc = self.alloc_combo.currentData() or "equal_weight"

        try:
            if self.account is None:
                create_account(
                    name=name,
                    description=self.desc_edit.text().strip(),
                    strategy=strategy,
                    mode=mode,
                    allocation_mode=alloc,
                    max_positions=self.max_pos_spin.value(),
                    fixed_amount=self.fixed_amt_spin.value(),
                    initial_capital=self.initial_cap_spin.value(),
                    commission=self.commission_spin.value(),
                    slippage=self.slippage_spin.value(),
                    drift_threshold=self.drift_spin.value(),
                    monthly_rebalance=self.monthly_check.isChecked(),
                    slack_notify=self.slack_check.isChecked(),
                )
            else:
                update_account_config(
                    self.account.id,
                    description=self.desc_edit.text().strip(),
                    strategy=strategy,
                    mode=mode,
                    allocation_mode=alloc,
                    max_positions=self.max_pos_spin.value(),
                    fixed_amount=self.fixed_amt_spin.value(),
                    commission=self.commission_spin.value(),
                    slippage=self.slippage_spin.value(),
                    drift_threshold=self.drift_spin.value(),
                    monthly_rebalance=self.monthly_check.isChecked(),
                    is_active=self.active_check.isChecked(),
                    slack_notify=self.slack_check.isChecked(),
                )
        except ValueError as e:
            QMessageBox.warning(self, "Error", str(e))
            return
        except Exception as e:
            QMessageBox.critical(self, "Error", f"No se pudo guardar la cuenta:\n{e}")
            return

        self.accept()
