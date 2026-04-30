"""
IQON-inspired dark theme for FinanzIAs.
Deep black background, green accents, card-based layout.
"""

# ── Palette ────────────────────────────────────────────────────────────────
BG_BASE      = "#0a0b0d"   # main background
BG_SIDEBAR   = "#0f1012"   # sidebar
BG_CARD      = "#111318"   # cards
BG_CARD_HVR  = "#161a20"   # card hover
BG_ELEVATED  = "#1a1d23"   # inputs, elevated
BORDER       = "#1e2128"   # subtle border
BORDER_LT    = "#2a2f3a"   # lighter border

ACCENT       = "#4ade80"   # green accent (active, positive)
ACCENT_DIM   = "#22c55e"   # slightly dimmer green
ACCENT_BG    = "#0d2818"   # green tinted bg
BLUE         = "#60a5fa"   # gauge / chart blue
PURPLE       = "#a78bfa"   # network chart
YELLOW       = "#fbbf24"   # warning
RED          = "#f87171"   # negative / danger

TEXT_1       = "#f1f5f9"   # primary text
TEXT_2       = "#94a3b8"   # secondary / labels
TEXT_3       = "#4b5563"   # muted / disabled

NAV_ACTIVE_BG   = "#0f2a1a"
NAV_ACTIVE_TEXT = "#4ade80"
NAV_HOVER_BG    = "#13161c"

# ── Main Stylesheet ────────────────────────────────────────────────────────
DARK_THEME = f"""
/* ─ Global ─────────────────────────────────────────────────────────────── */
QMainWindow, QDialog, QWidget {{
    background-color: {BG_BASE};
    color: {TEXT_1};
    font-family: 'Segoe UI', 'Inter', 'Arial', sans-serif;
    font-size: 13px;
}}

QScrollArea, QScrollArea > QWidget > QWidget {{
    background-color: transparent;
    border: none;
}}

QSplitter::handle {{
    background: {BORDER};
    width: 1px;
}}

/* ─ Cards ───────────────────────────────────────────────────────────────── */
QFrame#card {{
    background-color: {BG_CARD};
    border: 1px solid {BORDER};
    border-radius: 12px;
}}
QFrame#card:hover {{
    border: 1px solid {BORDER_LT};
    background-color: {BG_CARD_HVR};
}}

QFrame#card_flat {{
    background-color: {BG_CARD};
    border: 1px solid {BORDER};
    border-radius: 12px;
}}

/* ─ Sidebar ─────────────────────────────────────────────────────────────── */
QFrame#sidebar {{
    background-color: {BG_SIDEBAR};
    border-right: 1px solid {BORDER};
    border-radius: 0px;
}}

QPushButton#nav_item {{
    background-color: transparent;
    color: {TEXT_2};
    border: none;
    border-radius: 20px;
    padding: 9px 16px;
    text-align: left;
    font-size: 13px;
    font-weight: 500;
}}
QPushButton#nav_item:hover {{
    background-color: {NAV_HOVER_BG};
    color: {TEXT_1};
}}
QPushButton#nav_item_active {{
    background-color: {ACCENT};
    color: #000000;
    border: none;
    border-radius: 20px;
    padding: 9px 16px;
    text-align: left;
    font-size: 13px;
    font-weight: 700;
}}
QPushButton#nav_item_active:hover {{
    background-color: #6ee7a0;
    color: #000000;
}}

QPushButton#nav_sub {{
    background-color: transparent;
    color: {TEXT_3};
    border: none;
    border-radius: 6px;
    padding: 7px 14px 7px 28px;
    text-align: left;
    font-size: 12px;
}}
QPushButton#nav_sub:hover {{
    color: {TEXT_2};
    background-color: {NAV_HOVER_BG};
}}
QPushButton#nav_sub_active {{
    background-color: transparent;
    color: {ACCENT};
    border: none;
    border-radius: 6px;
    padding: 7px 14px 7px 28px;
    text-align: left;
    font-size: 12px;
    font-weight: 600;
}}

/* ─ Buttons ─────────────────────────────────────────────────────────────── */
QPushButton {{
    background-color: {BG_ELEVATED};
    color: {TEXT_1};
    border: 1px solid {BORDER_LT};
    border-radius: 8px;
    padding: 8px 16px;
    font-size: 13px;
    font-weight: 500;
}}
QPushButton:hover {{
    background-color: {BORDER_LT};
    border-color: {TEXT_3};
}}
QPushButton:pressed {{
    background-color: {BG_CARD};
}}

QPushButton#primary {{
    background-color: {ACCENT};
    color: #000000;
    border: none;
    border-radius: 20px;
    padding: 8px 22px;
    font-weight: 700;
    font-size: 13px;
    letter-spacing: 0.3px;
}}
QPushButton#primary:hover {{
    background-color: #6ee7a0;
    color: #000000;
}}
QPushButton#primary:pressed {{
    background-color: {ACCENT_DIM};
}}

QPushButton#danger {{
    background-color: #3d1515;
    color: {RED};
    border: 1px solid #5a2020;
}}
QPushButton#danger:hover {{
    background-color: #5a1f1f;
}}

QPushButton#success {{
    background-color: {ACCENT_BG};
    color: {ACCENT};
    border: 1px solid #1a4a2a;
    border-radius: 20px;
    font-weight: 600;
    padding: 8px 20px;
}}
QPushButton#success:hover {{
    background-color: #0f3320;
    color: {ACCENT};
}}

QPushButton#ghost {{
    background-color: transparent;
    color: {TEXT_2};
    border: 1px solid {BORDER_LT};
    border-radius: 8px;
    padding: 8px 16px;
}}
QPushButton#ghost:hover {{
    color: {TEXT_1};
    background-color: {BG_ELEVATED};
}}

/* ─ Inputs ──────────────────────────────────────────────────────────────── */
QLineEdit, QTextEdit, QPlainTextEdit {{
    background-color: {BG_ELEVATED};
    color: {TEXT_1};
    border: 1px solid {BORDER_LT};
    border-radius: 8px;
    padding: 9px 13px;
    font-size: 13px;
    selection-background-color: {ACCENT_BG};
}}
QLineEdit:focus, QTextEdit:focus {{
    border-color: {ACCENT};
    outline: none;
}}
QLineEdit::placeholder {{ color: {TEXT_3}; }}

QComboBox {{
    background-color: {BG_ELEVATED};
    color: {TEXT_1};
    border: 1px solid {BORDER_LT};
    border-radius: 8px;
    padding: 8px 12px;
    font-size: 13px;
}}
QComboBox:focus {{ border-color: {ACCENT}; }}
QComboBox::drop-down {{ border: none; width: 28px; }}
QComboBox::down-arrow {{ width: 12px; height: 12px; }}
QComboBox QAbstractItemView {{
    background-color: {BG_CARD};
    color: {TEXT_1};
    border: 1px solid {BORDER_LT};
    selection-background-color: {ACCENT_BG};
    selection-color: {ACCENT};
    outline: none;
}}

QDoubleSpinBox, QSpinBox {{
    background-color: {BG_ELEVATED};
    color: {TEXT_1};
    border: 1px solid {BORDER_LT};
    border-radius: 8px;
    padding: 8px 12px;
    font-size: 13px;
}}
QDoubleSpinBox:focus, QSpinBox:focus {{ border-color: {ACCENT}; }}
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button,
QSpinBox::up-button, QSpinBox::down-button {{
    background-color: {BORDER_LT};
    border: none;
    border-radius: 4px;
    width: 18px;
}}

/* ─ Tables ──────────────────────────────────────────────────────────────── */
QTableWidget {{
    background-color: {BG_CARD};
    alternate-background-color: {BG_BASE};
    color: {TEXT_1};
    gridline-color: {BORDER};
    border: 1px solid {BORDER};
    border-radius: 12px;
    selection-background-color: {NAV_ACTIVE_BG};
    selection-color: {TEXT_1};
    outline: none;
}}
QTableWidget::item {{
    padding: 10px 14px;
    border: none;
}}
QTableWidget::item:selected {{
    background-color: {NAV_ACTIVE_BG};
    color: {TEXT_1};
}}
QHeaderView::section {{
    background-color: {BG_BASE};
    color: {TEXT_3};
    padding: 10px 14px;
    border: none;
    border-bottom: 1px solid {BORDER};
    font-size: 11px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.8px;
}}
QHeaderView {{ background-color: {BG_BASE}; border-radius: 12px; }}

/* ─ Labels ──────────────────────────────────────────────────────────────── */
QLabel {{ color: {TEXT_1}; background-color: transparent; }}
QLabel#muted   {{ color: {TEXT_2}; font-size: 12px; }}
QLabel#micro   {{ color: {TEXT_3}; font-size: 11px; }}
QLabel#title   {{ font-size: 22px; font-weight: 700; color: {TEXT_1}; }}
QLabel#h2      {{ font-size: 16px; font-weight: 700; color: {TEXT_1}; }}
QLabel#subtitle {{ font-size: 13px; font-weight: 600; color: {TEXT_2}; }}
QLabel#positive {{ color: {ACCENT}; font-weight: 700; }}
QLabel#negative {{ color: {RED};    font-weight: 700; }}
QLabel#warning  {{ color: {YELLOW}; font-weight: 600; }}
QLabel#dot_green {{ color: {ACCENT}; font-size: 10px; }}
QLabel#dot_red   {{ color: {RED};    font-size: 10px; }}
QLabel#dot_gray  {{ color: {TEXT_3}; font-size: 10px; }}

/* ─ GroupBox ────────────────────────────────────────────────────────────── */
QGroupBox {{
    border: 1px solid {BORDER};
    border-radius: 10px;
    margin-top: 14px;
    padding: 10px 12px;
    color: {TEXT_3};
    font-size: 11px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.8px;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 8px;
    color: {TEXT_3};
}}

/* ─ ScrollBars ──────────────────────────────────────────────────────────── */
QScrollBar:vertical {{
    background: transparent;
    width: 6px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {BORDER_LT};
    border-radius: 3px;
    min-height: 24px;
}}
QScrollBar::handle:vertical:hover {{ background: {TEXT_3}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}

QScrollBar:horizontal {{
    background: transparent;
    height: 6px;
}}
QScrollBar::handle:horizontal {{
    background: {BORDER_LT};
    border-radius: 3px;
}}

/* ─ StatusBar ───────────────────────────────────────────────────────────── */
QStatusBar {{
    background-color: {BG_SIDEBAR};
    color: {TEXT_3};
    border-top: 1px solid {BORDER};
    font-size: 11px;
    padding: 2px 12px;
}}

/* ─ Dialogs ─────────────────────────────────────────────────────────────── */
QDialog {{
    background-color: {BG_CARD};
    border: 1px solid {BORDER_LT};
    border-radius: 14px;
}}
QDialogButtonBox QPushButton {{
    min-width: 90px;
    padding: 9px 20px;
}}

/* ─ Tooltips ────────────────────────────────────────────────────────────── */
QToolTip {{
    background-color: {BG_ELEVATED};
    color: {TEXT_1};
    border: 1px solid {BORDER_LT};
    border-radius: 6px;
    padding: 5px 10px;
    font-size: 12px;
}}

/* ─ CheckBox ────────────────────────────────────────────────────────────── */
QCheckBox {{ color: {TEXT_1}; spacing: 8px; }}
QCheckBox::indicator {{
    width: 16px; height: 16px;
    border: 1px solid {BORDER_LT};
    border-radius: 4px;
    background-color: {BG_ELEVATED};
}}
QCheckBox::indicator:checked {{
    background-color: {ACCENT};
    border-color: {ACCENT};
}}

/* ─ RadioButton ─────────────────────────────────────────────────────────── */
QRadioButton {{ color: {TEXT_1}; spacing: 8px; }}
QRadioButton::indicator {{
    width: 16px; height: 16px;
    border: 1px solid {BORDER_LT};
    border-radius: 8px;
    background-color: {BG_ELEVATED};
}}
QRadioButton::indicator:checked {{
    background-color: {ACCENT};
    border-color: {ACCENT};
}}

/* ─ ProgressBar ─────────────────────────────────────────────────────────── */
QProgressBar {{
    background-color: {BG_ELEVATED};
    border: none;
    border-radius: 4px;
    height: 6px;
    text-align: center;
    font-size: 11px;
    color: transparent;
}}
QProgressBar::chunk {{
    background-color: {ACCENT};
    border-radius: 4px;
}}

/* ─ Misc ────────────────────────────────────────────────────────────────── */
QFrame#separator {{ background-color: {BORDER}; max-height: 1px; }}
QFrame#vline     {{ background-color: {BORDER}; max-width: 1px; }}
"""

# ── Chart style (passed to matplotlib rcParams) ────────────────────────────
CHART_STYLE = {
    "figure.facecolor":  BG_CARD,
    "axes.facecolor":    BG_CARD,
    "axes.edgecolor":    BORDER,
    "axes.labelcolor":   TEXT_2,
    "xtick.color":       TEXT_3,
    "ytick.color":       TEXT_3,
    "grid.color":        BORDER,
    "grid.alpha":        0.6,
    "text.color":        TEXT_1,
    "lines.color":       BLUE,
}

SIGNAL_COLORS = {
    # Yahoo Finance 5-level system
    "Strong Buy":   "#22c55e",   # bright green
    "Buy":          "#4ade80",   # light green
    "Hold":         "#fbbf24",   # gold / yellow
    "Underperform": "#fb923c",   # orange
    "Sell":         "#f87171",   # red
    # Legacy keys kept for backward compatibility
    "BUY":     ACCENT,
    "SELL":    RED,
    "HOLD":    YELLOW,
    "NEUTRAL": TEXT_3,
}

# Export palette for use in widgets
PALETTE = {
    "bg":         BG_BASE,
    "sidebar":    BG_SIDEBAR,
    "card":       BG_CARD,
    "elevated":   BG_ELEVATED,
    "border":     BORDER,
    "border_lt":  BORDER_LT,
    "accent":     ACCENT,
    "accent_bg":  ACCENT_BG,
    "blue":       BLUE,
    "purple":     PURPLE,
    "yellow":     YELLOW,
    "red":        RED,
    "text1":      TEXT_1,
    "text2":      TEXT_2,
    "text3":      TEXT_3,
    "nav_active": NAV_ACTIVE_BG,
}
