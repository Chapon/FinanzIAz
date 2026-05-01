"""
Settings tab — all toggles are now wired to config/settings_manager.py
and persist across sessions.
"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QScrollArea, QPushButton, QMessageBox
)
from PyQt6.QtCore import Qt, pyqtSignal
from ui.widgets import (
    SettingsRow, NumericSettingsRow, ChoiceSettingsRow,
    HSeparator, SectionHeader,
)
from ui.styles import PALETTE
from config.settings_manager import settings


class SettingsTab(QWidget):
    # Emitted when a setting changes; MainWindow listens for side-effects
    setting_changed = pyqtSignal(str, bool)   # key, new_value

    # Emitted when rsi_alerts is turned ON so MainWindow can run the scan
    rsi_scan_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: dict[str, SettingsRow] = {}
        self._numeric_rows: dict[str, NumericSettingsRow] = {}
        self._choice_rows: dict[str, ChoiceSettingsRow] = {}
        self._build_ui()

    # ── Build ─────────────────────────────────────────────────────────────────

    def _build_ui(self):
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        container = QWidget()
        container.setStyleSheet(f"background-color: {PALETTE['bg']};")
        scroll.setWidget(container)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

        root = QVBoxLayout(container)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(20)

        root.addWidget(SectionHeader("Ajustes de la Aplicación"))
        root.addWidget(HSeparator())

        root.addWidget(self._section("GENERAL", [
            ("notif",        "Notificaciones al disparar alertas",
             "Muestra una notificación cuando una alerta de precio se activa."),
            ("auto_refresh", "Actualizar precios automáticamente",
             "Refresca los precios del portafolio cada 60 segundos."),
            ("default_home", "Abrir en Home al iniciar",
             "Si está apagado, la app abre directamente en Portafolio."),
            ("confirm_sell", "Pedir confirmación al vender",
             "Muestra un diálogo extra de confirmación antes de ejecutar una venta."),
        ]))

        root.addWidget(self._section("DATOS DE MERCADO", [
            ("cache",       "Caché de precios (5 min)",
             "Reutiliza el precio guardado si fue actualizado hace menos de 5 min. "
             "Desactivar para obtener precios en tiempo real (más llamadas a la API)."),
            ("pre_market",  "Mostrar precios pre/post mercado",
             "Muestra etiquetas 'Pre-market' y 'After-hours' en la barra de estado."),
            ("perf_log",    "Guardar historial de rendimiento",
             "Guarda snapshots diarios del valor del portafolio (función futura)."),
        ]))

        root.addWidget(self._section("ANÁLISIS TÉCNICO", [
            ("bb",          "Bollinger Bands en gráficos",
             "Muestra las bandas de Bollinger (±2σ) superpuestas en el gráfico de precio."),
            ("sma_cross",   "Señales SMA50/200 (Golden/Death Cross)",
             "Incluye la señal de cruce de medias móviles en el análisis ponderado."),
            ("rsi_alerts",  "Alertar RSI extremo (< 30 / > 70)",
             "Al activar: escanea el portafolio actual y notifica posiciones con RSI extremo."),
        ]))

        root.addWidget(self._section("REPORTES", [
            ("tx_history",  "Incluir historial de transacciones",
             "Agrega una sección con el detalle de compras/ventas en PDF y Excel."),
            ("pdf_dark",    "Tema oscuro en PDF",
             "Genera el PDF con fondo oscuro. Desactivar para tema claro (más apto para imprimir)."),
        ]))

        root.addWidget(self._guardrails_section())
        root.addWidget(self._analysis_section())

        root.addStretch()

        # Reset button
        reset_row = QHBoxLayout()
        reset_row.addStretch()
        reset_btn = QPushButton("Restablecer valores por defecto")
        reset_btn.setObjectName("danger")
        reset_btn.clicked.connect(self._on_reset)
        reset_row.addWidget(reset_btn)
        root.addLayout(reset_row)

    def _section(self, title: str, settings_list: list) -> QFrame:
        card = QFrame()
        card.setObjectName("card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(0)

        lbl = QLabel(title)
        lbl.setStyleSheet(
            f"color: {PALETTE['text3']}; font-size: 10px; font-weight: 700; "
            f"letter-spacing: 1px; margin-bottom: 10px;"
        )
        layout.addWidget(lbl)

        for i, item in enumerate(settings_list):
            key, label, tooltip = item
            row = SettingsRow(key, label, settings.get(key), tooltip=tooltip)
            row.toggled.connect(self._on_toggle)
            self._rows[key] = row
            layout.addWidget(row)
            if i < len(settings_list) - 1:
                layout.addWidget(HSeparator())

        return card

    def _guardrails_section(self) -> QFrame:
        """
        Paper-trading execution guardrails. Mixed bool + numeric inputs,
        so this section is hand-rolled rather than going through _section.
        """
        card = QFrame()
        card.setObjectName("card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(0)

        lbl = QLabel("GUARDRAILS PAPER TRADING")
        lbl.setStyleSheet(
            f"color: {PALETTE['text3']}; font-size: 10px; font-weight: 700; "
            f"letter-spacing: 1px; margin-bottom: 10px;"
        )
        layout.addWidget(lbl)

        # 1) Solo ejecutar con mercado abierto (bool)
        bool_row = SettingsRow(
            "paper_enforce_market_hours",
            "Solo ejecutar con mercado abierto",
            settings.get("paper_enforce_market_hours"),
            tooltip="El motor rechaza fills si NYSE está cerrada, "
                    "incluso si el escaneo se disparó manualmente o desde el cron diario.",
        )
        bool_row.toggled.connect(self._on_toggle)
        self._rows["paper_enforce_market_hours"] = bool_row
        layout.addWidget(bool_row)
        layout.addWidget(HSeparator())

        # 2) Período mínimo de holding (int, minutos)
        holding_row = NumericSettingsRow(
            "paper_min_holding_minutes",
            "Período mínimo de holding",
            settings.get("paper_min_holding_minutes"),
            value_type="int", suffix="min",
            minimum=0, maximum=43_200, step=15,
            tooltip="No vender una posición abierta hace menos de N minutos. "
                    "Evita el flapping comprar→vender en pocos minutos. "
                    "0 = desactivado.",
        )
        holding_row.value_changed.connect(self._on_numeric_change)
        self._numeric_rows["paper_min_holding_minutes"] = holding_row
        layout.addWidget(holding_row)
        layout.addWidget(HSeparator())

        # 3) Cooldown anti-flap (int, minutos)
        flap_row = NumericSettingsRow(
            "paper_anti_flap_minutes",
            "Cooldown anti-flap tras vender",
            settings.get("paper_anti_flap_minutes"),
            value_type="int", suffix="min",
            minimum=0, maximum=43_200, step=15,
            tooltip="No re-comprar un ticker vendido en los últimos N minutos. "
                    "0 = desactivado.",
        )
        flap_row.value_changed.connect(self._on_numeric_change)
        self._numeric_rows["paper_anti_flap_minutes"] = flap_row
        layout.addWidget(flap_row)
        layout.addWidget(HSeparator())

        # 4) Tamaño mínimo de orden (float, USD)
        minsize_row = NumericSettingsRow(
            "paper_min_trade_dollars",
            "Tamaño mínimo de orden",
            settings.get("paper_min_trade_dollars"),
            value_type="float", suffix="USD",
            minimum=0.0, maximum=100_000.0, step=10.0, decimals=2,
            tooltip="Bloquea BUYs por debajo de este notional para evitar "
                    "que el round-trip cost se coma el edge esperado. "
                    "0 = desactivado.",
        )
        minsize_row.value_changed.connect(self._on_numeric_change)
        self._numeric_rows["paper_min_trade_dollars"] = minsize_row
        layout.addWidget(minsize_row)

        return card

    def _analysis_section(self) -> QFrame:
        """
        Tuning del análisis técnico/ML que corre el scanner de paper trading.
        """
        card = QFrame()
        card.setObjectName("card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(0)

        lbl = QLabel("ANÁLISIS PAPER TRADING")
        lbl.setStyleSheet(
            f"color: {PALETTE['text3']}; font-size: 10px; font-weight: 700; "
            f"letter-spacing: 1px; margin-bottom: 10px;"
        )
        layout.addWidget(lbl)

        # Histórico que el scanner pasa a analyze() / XGBoost.
        # Yahoo Finance solo acepta valores discretos: 1y, 2y, 5y, 10y.
        period_row = ChoiceSettingsRow(
            "paper_history_period",
            "Histórico para analyze() / XGBoost",
            settings.get("paper_history_period"),
            choices=[
                ("1y",  "1 año"),
                ("2y",  "2 años"),
                ("5y",  "5 años"),
                ("10y", "10 años"),
            ],
            tooltip="Cantidad de historial que el scanner usa para entrenar "
                    "XGBoost y calcular indicadores técnicos en cada escaneo. "
                    "2 años es el sweet spot — 1 año tiene validación demasiado "
                    "chica, 5+ años arrastra regímenes viejos.",
        )
        period_row.value_changed.connect(self._on_choice_change)
        self._choice_rows["paper_history_period"] = period_row
        layout.addWidget(period_row)

        return card

    # ── Handlers ──────────────────────────────────────────────────────────────

    def _on_toggle(self, key: str, value: bool):
        settings.set(key, value)
        self.setting_changed.emit(key, value)

        if key == "rsi_alerts" and value:
            self.rsi_scan_requested.emit()

    def _on_numeric_change(self, key: str, value: float):
        """Persist numeric setting; cast back to int for int-typed rows."""
        row = self._numeric_rows.get(key)
        if row is not None and getattr(row, "_is_int", False):
            settings.set(key, int(value))
        else:
            settings.set(key, float(value))

    def _on_choice_change(self, key: str, value: str):
        """Persist a dropdown selection (always stored as string)."""
        settings.set(key, str(value))

    def _on_reset(self):
        reply = QMessageBox.question(
            self, "Restablecer ajustes",
            "¿Restablecer todos los ajustes a sus valores por defecto?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        defaults = settings.reset()
        # Update all toggle widgets to reflect defaults
        for key, row in self._rows.items():
            row.toggle.setChecked(defaults.get(key, False))
        # Update all numeric widgets too
        for key, nrow in self._numeric_rows.items():
            nrow.set_value(defaults.get(key, 0))
        # Update all choice (dropdown) widgets too
        for key, crow in self._choice_rows.items():
            crow.set_value(defaults.get(key, ""))

        QMessageBox.information(self, "Ajustes", "Valores por defecto restablecidos.")

    def reload_from_settings(self):
        """Sync all toggles + numeric + choice inputs with current saved values."""
        for key, row in self._rows.items():
            row.toggle.setChecked(settings.get(key))
        for key, nrow in self._numeric_rows.items():
            nrow.set_value(settings.get(key, 0))
        for key, crow in self._choice_rows.items():
            crow.set_value(settings.get(key, ""))
