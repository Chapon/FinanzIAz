"""
Settings tab — all toggles are now wired to config/settings_manager.py
and persist across sessions.
"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QScrollArea, QPushButton, QMessageBox
)
from PyQt6.QtCore import Qt, pyqtSignal
from ui.widgets import SettingsRow, HSeparator, SectionHeader
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

    # ── Handlers ──────────────────────────────────────────────────────────────

    def _on_toggle(self, key: str, value: bool):
        settings.set(key, value)
        self.setting_changed.emit(key, value)

        if key == "rsi_alerts" and value:
            self.rsi_scan_requested.emit()

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

        QMessageBox.information(self, "Ajustes", "Valores por defecto restablecidos.")

    def reload_from_settings(self):
        """Sync all toggles with current saved values (call after external changes)."""
        for key, row in self._rows.items():
            row.toggle.setChecked(settings.get(key))
