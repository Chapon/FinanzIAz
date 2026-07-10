"""
Settings tab — all toggles are now wired to config/settings_manager.py
and persist across sessions.
"""

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from config.settings_manager import settings
from ui.styles import PALETTE
from ui.widgets import (
    ChoiceSettingsRow,
    HSeparator,
    NumericSettingsRow,
    SectionHeader,
    SettingsRow,
)


class SettingsTab(QWidget):
    # Emitted when a setting changes; MainWindow listens for side-effects
    setting_changed = pyqtSignal(str, bool)  # key, new_value

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

        root.addWidget(
            self._section(
                "GENERAL",
                [
                    (
                        "notif",
                        "Notificaciones al disparar alertas",
                        "Muestra una notificación cuando una alerta de precio se activa.",
                    ),
                    (
                        "auto_refresh",
                        "Actualizar precios automáticamente",
                        "Refresca los precios del portafolio cada 60 segundos.",
                    ),
                    (
                        "default_home",
                        "Abrir en Home al iniciar",
                        "Si está apagado, la app abre directamente en Portafolio.",
                    ),
                    (
                        "confirm_sell",
                        "Pedir confirmación al vender",
                        "Muestra un diálogo extra de confirmación antes de ejecutar una venta.",
                    ),
                ],
            )
        )

        root.addWidget(
            self._section(
                "DATOS DE MERCADO",
                [
                    (
                        "cache",
                        "Caché de precios (5 min)",
                        "Reutiliza el precio guardado si fue actualizado hace menos de 5 min. "
                        "Desactivar para obtener precios en tiempo real (más llamadas a la API).",
                    ),
                    (
                        "pre_market",
                        "Mostrar precios pre/post mercado",
                        "Muestra etiquetas 'Pre-market' y 'After-hours' en la barra de estado.",
                    ),
                    (
                        "perf_log",
                        "Guardar historial de rendimiento",
                        "Guarda snapshots diarios del valor del portafolio (función futura).",
                    ),
                ],
            )
        )

        root.addWidget(
            self._section(
                "ANÁLISIS TÉCNICO",
                [
                    (
                        "bb",
                        "Bollinger Bands en gráficos",
                        "Muestra las bandas de Bollinger (±2σ) superpuestas en el gráfico de precio.",
                    ),
                    (
                        "sma_cross",
                        "Señales SMA50/200 (Golden/Death Cross)",
                        "Incluye la señal de cruce de medias móviles en el análisis ponderado.",
                    ),
                    (
                        "rsi_alerts",
                        "Alertar RSI extremo (< 30 / > 70)",
                        "Al activar: escanea el portafolio actual y notifica posiciones con RSI extremo.",
                    ),
                ],
            )
        )

        root.addWidget(
            self._section(
                "REPORTES",
                [
                    (
                        "tx_history",
                        "Incluir historial de transacciones",
                        "Agrega una sección con el detalle de compras/ventas en PDF y Excel.",
                    ),
                    (
                        "pdf_dark",
                        "Tema oscuro en PDF",
                        "Genera el PDF con fondo oscuro. Desactivar para tema claro (más apto para imprimir).",
                    ),
                ],
            )
        )

        root.addWidget(self._guardrails_section())
        root.addWidget(self._analysis_section())
        root.addWidget(self._commission_section())
        root.addWidget(self._notifications_section())

        root.addStretch()

        # ── Backup / restore card ────────────────────────────────────────
        root.addWidget(self._backup_card())

        # Reset button
        reset_row = QHBoxLayout()
        reset_row.addStretch()
        reset_btn = QPushButton("Restablecer valores por defecto")
        reset_btn.setObjectName("danger")
        reset_btn.clicked.connect(self._on_reset)
        reset_row.addWidget(reset_btn)
        root.addLayout(reset_row)

    # ── Backup card ──────────────────────────────────────────────────────────

    def _backup_card(self) -> QFrame:
        """Card with manual backup, list of snapshots, and restore button."""
        card = QFrame()
        card.setObjectName("card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(10)

        title = QLabel("BASE DE DATOS")
        title.setStyleSheet(
            f"color: {PALETTE['text2']}; font-size: 11px; font-weight: 700; letter-spacing: 0.6px;"
        )
        layout.addWidget(title)

        desc = QLabel(
            "La app guarda un backup automático cada día en "
            "<code>~/.finanzias/backups/</code> (últimos 7). "
            "También podés crear/restaurar manualmente."
        )
        desc.setObjectName("muted")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        self._backup_list_label = QLabel("")
        self._backup_list_label.setObjectName("muted")
        self._backup_list_label.setStyleSheet("font-family: monospace; font-size: 11px;")
        self._backup_list_label.setWordWrap(True)
        layout.addWidget(self._backup_list_label)
        self._refresh_backup_list()

        btn_row = QHBoxLayout()
        backup_btn = QPushButton("📦 Crear backup ahora")
        backup_btn.clicked.connect(self._on_backup_now)
        restore_btn = QPushButton("↶ Restaurar...")
        restore_btn.setObjectName("danger")
        restore_btn.clicked.connect(self._on_restore)
        btn_row.addWidget(backup_btn)
        btn_row.addWidget(restore_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        return card

    def _refresh_backup_list(self) -> None:
        try:
            from database.backup import list_backups

            paths = list_backups()
        except Exception:
            paths = []
        if not paths:
            self._backup_list_label.setText("(sin backups todavía)")
            return
        # Show the 5 most recent.
        recent = paths[-5:][::-1]
        lines = []
        for p in recent:
            try:
                size_kb = p.stat().st_size // 1024
                lines.append(f"• {p.name}    {size_kb} KB")
            except Exception:
                lines.append(f"• {p.name}")
        suffix = f"\n(+{len(paths) - len(recent)} más)" if len(paths) > len(recent) else ""
        self._backup_list_label.setText("\n".join(lines) + suffix)

    def _on_backup_now(self) -> None:
        from database.backup import backup_database

        path = backup_database(reason="manual")
        if path is None:
            QMessageBox.warning(self, "Error", "No se pudo crear el backup. Revisá el log.")
            return
        QMessageBox.information(
            self,
            "Backup creado",
            f"Backup guardado en:\n{path}",
        )
        self._refresh_backup_list()

    def _on_restore(self) -> None:
        from database.backup import list_backups, restore_database

        paths = list_backups()
        if not paths:
            QMessageBox.information(self, "Sin backups", "No hay backups disponibles.")
            return
        # Pick by name, newest first.
        from PyQt6.QtWidgets import QInputDialog

        names = [p.name for p in paths[::-1]]
        choice, ok = QInputDialog.getItem(
            self,
            "Restaurar backup",
            "Elegí qué backup restaurar (la base actual se guardará como <name>.before-restore):",
            names,
            0,
            False,
        )
        if not ok:
            return
        # Resolve back to Path
        idx = names.index(choice)
        target = paths[::-1][idx]

        confirm = QMessageBox.question(
            self,
            "Confirmar restore",
            f"¿Reemplazar la base de datos actual con:\n\n{target.name}?\n\n"
            "Cerrá manualmente el portafolio antes de continuar.\n"
            "Esta acción no se puede deshacer (la copia previa se guarda).",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        ok = restore_database(target)
        if ok:
            QMessageBox.information(
                self,
                "Restore exitoso",
                "Base restaurada. Reiniciá la app para que los cambios surtan efecto.",
            )
        else:
            QMessageBox.critical(
                self,
                "Error",
                "No se pudo restaurar el backup. Revisá el log para detalles.",
            )
        self._refresh_backup_list()

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
            value_type="int",
            suffix="min",
            minimum=0,
            maximum=43_200,
            step=15,
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
            value_type="int",
            suffix="min",
            minimum=0,
            maximum=43_200,
            step=15,
            tooltip="No re-comprar un ticker vendido en los últimos N minutos. 0 = desactivado.",
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
            value_type="float",
            suffix="USD",
            minimum=0.0,
            maximum=100_000.0,
            step=10.0,
            decimals=2,
            tooltip="Bloquea BUYs por debajo de este notional para evitar "
            "que el round-trip cost se coma el edge esperado. "
            "0 = desactivado.",
        )
        minsize_row.value_changed.connect(self._on_numeric_change)
        self._numeric_rows["paper_min_trade_dollars"] = minsize_row
        layout.addWidget(minsize_row)
        layout.addWidget(HSeparator())

        # 5) Anti-whipsaw: ventana de pérdida (int, días)
        whip_days_row = NumericSettingsRow(
            "paper_whipsaw_lookback_days",
            "Anti-whipsaw: ventana de pérdida",
            settings.get("paper_whipsaw_lookback_days"),
            value_type="int",
            suffix="días",
            minimum=0,
            maximum=90,
            step=1,
            tooltip="Si el último ciclo cerrado (BUY→SELL) del ticker terminó "
            "en pérdida hace menos de N días, no permitir re-comprarlo. "
            "0 = desactivado.",
        )
        whip_days_row.value_changed.connect(self._on_numeric_change)
        self._numeric_rows["paper_whipsaw_lookback_days"] = whip_days_row
        layout.addWidget(whip_days_row)
        layout.addWidget(HSeparator())

        # 6) Anti-whipsaw: pérdida mínima a bloquear (float, %)
        whip_loss_row = NumericSettingsRow(
            "paper_whipsaw_min_loss_pct",
            "Anti-whipsaw: pérdida mínima a bloquear",
            settings.get("paper_whipsaw_min_loss_pct"),
            value_type="float",
            suffix="%",
            minimum=0.0,
            maximum=100.0,
            step=0.5,
            decimals=2,
            tooltip="Solo bloquear si la pérdida del último ciclo fue peor que -X%. "
            "0 = bloquear cualquier pérdida dentro de la ventana.",
        )
        whip_loss_row.value_changed.connect(self._on_numeric_change)
        self._numeric_rows["paper_whipsaw_min_loss_pct"] = whip_loss_row
        layout.addWidget(whip_loss_row)

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
                ("1y", "1 año"),
                ("2y", "2 años"),
                ("5y", "5 años"),
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

    def _commission_section(self) -> QFrame:
        """
        Comisiones de Broker — elige el plan IBKR Pro que el motor aplica a
        nuevos fills. ``legacy`` mantiene el campo % por cuenta para back-compat.
        """
        card = QFrame()
        card.setObjectName("card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(0)

        lbl = QLabel("COMISIONES BROKER (IBKR PRO)")
        lbl.setStyleSheet(
            f"color: {PALETTE['text3']}; font-size: 10px; font-weight: 700; "
            f"letter-spacing: 1px; margin-bottom: 10px;"
        )
        layout.addWidget(lbl)

        plan_row = ChoiceSettingsRow(
            "ibkr_commission_plan",
            "Plan IBKR Pro",
            settings.get("ibkr_commission_plan"),
            choices=[
                ("tiered", "Tiered ($0.0035/share + fees)"),
                ("fixed", "Fixed ($0.005/share, fees bundled)"),
                ("legacy", "Legacy % por cuenta"),
            ],
            tooltip=(
                "Modelo que usa el motor para calcular la comisión de "
                "cada fill nuevo.\n"
                "• Tiered: $0.0035/share, mínimo $0.35, tope 1%, + SEC/"
                "FINRA en ventas + exchange fee de ruteo.\n"
                "• Fixed: $0.005/share, mínimo $1, tope 1% — incluye "
                "exchange/clearing pero NO regulatorios.\n"
                "• Legacy: usa el campo 'commission' (%) de cada cuenta. "
                "Útil si tenés cuentas calibradas con el modelo viejo."
            ),
        )
        plan_row.value_changed.connect(self._on_choice_change)
        self._choice_rows["ibkr_commission_plan"] = plan_row
        layout.addWidget(plan_row)

        return card

    def _notifications_section(self) -> QFrame:
        """
        Notificaciones a Slack (T12). Master switch global + selector de qué
        órdenes notificar. El canal y el bot token se configuran aparte
        (env var SLACK_BOT_TOKEN + scripts/setup_slack.py) por seguridad —
        el token NUNCA se guarda acá. El opt-out por cuenta vive en el
        diálogo de cada cuenta.
        """
        card = QFrame()
        card.setObjectName("card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(0)

        lbl = QLabel("NOTIFICACIONES SLACK")
        lbl.setStyleSheet(
            f"color: {PALETTE['text3']}; font-size: 10px; font-weight: 700; "
            f"letter-spacing: 1px; margin-bottom: 10px;"
        )
        layout.addWidget(lbl)

        # 1) Master switch (bool)
        enabled_row = SettingsRow(
            "slack_notifications_enabled",
            "Notificar órdenes a Slack",
            settings.get("slack_notifications_enabled"),
            tooltip="Interruptor general. Al activarlo, cada escaneo que genere "
            "órdenes envía un resumen al canal de Slack configurado. "
            "Requiere SLACK_BOT_TOKEN en el entorno y un canal "
            "(corré scripts/setup_slack.py la primera vez).",
        )
        enabled_row.toggled.connect(self._on_toggle)
        self._rows["slack_notifications_enabled"] = enabled_row
        layout.addWidget(enabled_row)
        layout.addWidget(HSeparator())

        # 2) Qué órdenes notificar (choice)
        notify_on_row = ChoiceSettingsRow(
            "slack_notify_on",
            "Qué órdenes notificar",
            settings.get("slack_notify_on"),
            choices=[
                ("both", "Pendientes y ejecutadas"),
                ("pending", "Solo pendientes (para aprobar)"),
                ("filled", "Solo ejecutadas (filled)"),
            ],
            tooltip="Filtra qué órdenes disparan el aviso. En modo manual las "
            "órdenes quedan 'pendientes' (para aprobar); en modo auto se "
            "ejecutan ('filled'). 'Ambas' es el default.",
        )
        notify_on_row.value_changed.connect(self._on_choice_change)
        self._choice_rows["slack_notify_on"] = notify_on_row
        layout.addWidget(notify_on_row)
        layout.addWidget(HSeparator())

        # 3) Aviso de outage de datos (NET1) — independiente del master de órdenes.
        outage_row = SettingsRow(
            "slack_data_outage_enabled",
            "Avisar por Slack si Yahoo se cae",
            settings.get("slack_data_outage_enabled"),
            tooltip="Cuando Yahoo deja de responder de forma sostenida (el breaker "
            "escala a nivel ≥2), manda un aviso al canal (y otro al recuperarse) "
            "para saber que los precios están congelados y los stops no se "
            "actualizan. Independiente del interruptor de órdenes; usa el mismo "
            "token/canal. No hace nada sin token configurado (fail-open).",
        )
        outage_row.toggled.connect(self._on_toggle)
        self._rows["slack_data_outage_enabled"] = outage_row
        layout.addWidget(outage_row)

        hint = QLabel(
            "El canal y el token se configuran con scripts/setup_slack.py "
            "(el token se lee de la variable de entorno SLACK_BOT_TOKEN, nunca "
            "se guarda en disco). Para apagar una cuenta puntual, usá el check "
            "'Notificar órdenes a Slack' en el diálogo de esa cuenta."
        )
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {PALETTE['text3']}; font-size: 11px; margin-top: 8px;")
        layout.addWidget(hint)

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
            self,
            "Restablecer ajustes",
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
