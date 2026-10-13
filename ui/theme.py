"""رنگ‌ها، استایل (QSS)، آیکون‌ها و تم تیره/روشن."""
import sys
from string import Template

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QIcon, QPainter, QPalette, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication

LIGHT = dict(
    bg="#f4f5f7", surface="#ffffff", surface2="#f8f9fb", hover="#f1f3f6", border="#e4e7ec", border2="#d5dae1",
    text="#101828", text2="#344054", muted="#667085", faint="#98a2b3",
    accent="#2563eb", accent_hover="#1d4ed8", accent_soft="#eef4ff", accent_text="#1d4ed8",
    danger="#d92d20", danger_soft="#fef3f2", success="#079455", success_soft="#ecfdf3",
    warning="#dc6803", warning_soft="#fffaeb", sel="#e0eaff", shadow="#1018280f",
    chart="#2563eb", chart_soft="#bfd3fe", grid="#eef0f3",
)
DARK = dict(
    bg="#0e1014", surface="#16191f", surface2="#1b1f26", hover="#20252d", border="#252a33", border2="#323844",
    text="#eceef2", text2="#c9ced8", muted="#8d96a5", faint="#5f6878",
    accent="#4c8dff", accent_hover="#6aa0ff", accent_soft="#17233a", accent_text="#8db4ff",
    danger="#f0605a", danger_soft="#2a1618", success="#2fbf7a", success_soft="#11261c",
    warning="#f2a33a", warning_soft="#2a2012", sel="#1c2c4a", shadow="#00000040",
    chart="#4c8dff", chart_soft="#24406e", grid="#20252d",
)

FONT_FAMILY = "Segoe UI"


class Theme:
    mode = "light"
    c = LIGHT
    listeners = []

    @classmethod
    def is_dark(cls):
        return cls.mode == "dark"

    @classmethod
    def color(cls, key):
        return QColor(cls.c[key])


def system_prefers_dark():
    try:
        return QApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
    except Exception:  # noqa: BLE001
        return False


def setup_font(app):
    global FONT_FAMILY
    fams = set(QFontDatabase.families())
    for f in ("Vazirmatn", "Vazir", "IRANSansX", "Segoe UI"):
        if f in fams:
            FONT_FAMILY = f
            break
    font = QFont(FONT_FAMILY, 10)
    font.setHintingPreference(QFont.PreferNoHinting)
    font.setStyleStrategy(QFont.PreferAntialias)
    app.setFont(font)


QSS = Template("""
* { font-family: "$font"; }
QWidget { color: $text; font-size: 10pt; }
QMainWindow, #Root, QDialog { background: $bg; }
QToolTip { background: $surface; color: $text; border: 1px solid $border2; border-radius: 6px; padding: 6px 8px; }

/* ---------- sidebar ---------- */
#Sidebar { background: $surface; border-left: 1px solid $border; }
#Brand { font-size: 14pt; font-weight: 700; color: $text; }
#BrandSub { color: $muted; font-size: 9pt; }
#NavButton { text-align: right; padding: 0 12px; border: none; border-radius: 8px; color: $text2;
             font-size: 10.5pt; min-height: 38px; background: transparent; }
#NavButton:hover { background: $hover; }
#NavButton:checked { background: $accent_soft; }
#NavText { color: $text2; font-size: 10.5pt; background: transparent; }
#NavText[active="true"] { color: $accent_text; font-weight: 600; }
#NavBadge { background: $danger; color: white; border-radius: 9px; font-size: 8pt; font-weight: 700;
            padding: 0 6px; min-height: 18px; max-height: 18px; min-width: 8px; }
#SideFooter { color: $faint; font-size: 8.5pt; }

/* ---------- typography ---------- */
#H1 { font-size: 17pt; font-weight: 700; color: $text; }
#H2 { font-size: 11.5pt; font-weight: 700; color: $text; }
#Muted { color: $muted; }
#Faint { color: $faint; font-size: 9pt; }
#Mono { font-family: "Consolas", "Cascadia Mono"; }
#Link { color: $accent_text; }

/* ---------- cards ---------- */
#Card { background: $surface; border: 1px solid $border; border-radius: 12px; }
#StatTitle { color: $muted; font-size: 9pt; }
#StatValue { color: $text; font-size: 17pt; font-weight: 700; }
#StatHint { color: $faint; font-size: 8.5pt; }
#Pill { background: $surface2; border: 1px solid $border; border-radius: 10px; padding: 1px 8px; color: $text2; font-size: 9pt; }
#PillAccent { background: $accent_soft; border-radius: 10px; padding: 1px 8px; color: $accent_text; font-size: 9pt; }
#PillDanger { background: $danger_soft; border-radius: 10px; padding: 1px 8px; color: $danger; font-size: 9pt; }
#PillSuccess { background: $success_soft; border-radius: 10px; padding: 1px 8px; color: $success; font-size: 9pt; }
#PillWarning { background: $warning_soft; border-radius: 10px; padding: 1px 8px; color: $warning; font-size: 9pt; }
#Divider { background: $border; max-height: 1px; min-height: 1px; border: none; }

/* ---------- buttons ---------- */
QPushButton { background: $surface; color: $text2; border: 1px solid $border2; border-radius: 8px;
              padding: 0 14px; min-height: 34px; font-weight: 500; }
QPushButton:hover { background: $hover; }
QPushButton:pressed { background: $border; }
QPushButton:disabled { color: $faint; background: $surface2; border-color: $border; }
QPushButton#Primary { background: $accent; color: white; border: 1px solid $accent; }
QPushButton#Primary:hover { background: $accent_hover; border-color: $accent_hover; }
QPushButton#Primary:disabled { background: $border2; border-color: $border2; color: $surface; }
QPushButton#Danger { background: $surface; color: $danger; border: 1px solid $border2; }
QPushButton#Danger:hover { background: $danger_soft; border-color: $danger; }
QPushButton#Ghost { background: transparent; border: none; color: $text2; }
QPushButton#Ghost:hover { background: $hover; }
QPushButton#Icon { background: transparent; border: none; min-width: 34px; max-width: 34px; padding: 0; }
QPushButton#Icon:hover { background: $hover; }
QPushButton::menu-indicator { width: 0; }

/* ---------- inputs ---------- */
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit, QTextEdit {
    background: $surface; border: 1px solid $border2; border-radius: 8px; padding: 0 10px;
    min-height: 34px; selection-background-color: $accent; selection-color: white; }
QPlainTextEdit, QTextEdit { padding: 6px 10px; }
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus, QPlainTextEdit:focus, QTextEdit:focus {
    border: 1px solid $accent; }
QLineEdit:disabled { color: $faint; background: $surface2; }
QLineEdit#Search { background: $surface; padding-right: 10px; }
QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button { width: 0; border: none; }
QComboBox::drop-down { border: none; width: 26px; }
QComboBox::down-arrow { image: none; width: 0; }
QComboBox QAbstractItemView { background: $surface; border: 1px solid $border2; border-radius: 8px; padding: 4px;
    selection-background-color: $sel; selection-color: $text; outline: none; }
QCheckBox { spacing: 8px; }
QCheckBox::indicator { width: 18px; height: 18px; border-radius: 5px; border: 1px solid $border2; background: $surface; }
QCheckBox::indicator:hover { border-color: $accent; }
QCheckBox::indicator:checked { background: $accent; border-color: $accent; image: url($check_icon); }

/* ---------- tables ---------- */
QTableView, QTreeView, QListView { background: $surface; alternate-background-color: $surface2; border: none;
    gridline-color: transparent; selection-background-color: $sel; selection-color: $text; outline: none; }
QTableView::item, QTreeView::item { padding: 0 8px; border: none; }
QTableView::item:hover, QTreeView::item:hover { background: $hover; }
QTableView::item:selected, QTreeView::item:selected, QListView::item:selected { background: $sel; color: $text; }
QHeaderView { background: $surface; border: none; }
QHeaderView::section { background: $surface; color: $muted; border: none; border-bottom: 1px solid $border;
    padding: 0 8px; min-height: 36px; font-weight: 600; font-size: 9pt; }
QHeaderView::section:hover { color: $text; }
QHeaderView::up-arrow, QHeaderView::down-arrow { width: 0; height: 0; }
QTableCornerButton::section { background: $surface; border: none; }
QTreeView::branch { background: transparent; }
QTreeView::branch:has-children:closed { image: url($chev_closed); }
QTreeView::branch:has-children:open { image: url($chev_open); }

/* ---------- scrollbars ---------- */
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: $border2; border-radius: 3px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: $faint; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 2px; }
QScrollBar::handle:horizontal { background: $border2; border-radius: 3px; min-width: 30px; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
QScrollArea { background: transparent; border: none; }
#ScrollBody { background: transparent; }

/* ---------- misc ---------- */
QMenu { background: $surface; border: 1px solid $border2; border-radius: 10px; padding: 6px; }
QMenu::item { padding: 7px 14px; border-radius: 6px; }
QMenu::item:selected { background: $hover; }
QMenu::separator { height: 1px; background: $border; margin: 4px 6px; }
QMenu::icon { padding-right: 8px; }
QSplitter::handle { background: transparent; }
QProgressBar { background: $border; border: none; border-radius: 2px; max-height: 4px; }
QProgressBar::chunk { background: $accent; border-radius: 2px; }
QTabBar::tab { background: transparent; padding: 8px 14px; border: none; color: $muted; font-weight: 600; }
QTabBar::tab:selected { color: $accent_text; border-bottom: 2px solid $accent; }
QTabWidget::pane { border: none; }
#Segment { background: $surface2; border: 1px solid $border; border-radius: 9px; }
#Segment QPushButton { border: none; background: transparent; min-height: 28px; border-radius: 7px; color: $muted; padding: 0 12px; }
#Segment QPushButton:checked { background: $surface; color: $text; border: 1px solid $border2; }
#Toast { background: $text; color: $bg; border-radius: 10px; padding: 10px 16px; font-weight: 500; }
#Kbd { background: $surface2; border: 1px solid $border2; border-bottom-width: 2px; border-radius: 5px;
       padding: 1px 7px; font-family: "Consolas"; font-size: 9pt; color: $text2; }
#Photo { background: white; border: 1px solid $border; border-radius: 10px; }
#EmptyTitle { font-size: 12pt; font-weight: 700; color: $text2; }
""")

# ------------------------------------------------------------------ icons (stroke style, 24x24)
ICONS = {
    "box": '<path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/><path d="M3.3 7 12 12l8.7-5"/><path d="M12 22V12"/>',
    "download": '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="m7 10 5 5 5-5"/><path d="M12 15V3"/>',
    "upload": '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="m17 8-5-5-5 5"/><path d="M12 3v12"/>',
    "layers": '<path d="m12 2 10 5-10 5L2 7z"/><path d="m2 17 10 5 10-5"/><path d="m2 12 10 5 10-5"/>',
    "cart": '<circle cx="8" cy="21" r="1"/><circle cx="19" cy="21" r="1"/><path d="M2 2h2l2.7 12.4a2 2 0 0 0 2 1.6h9.7a2 2 0 0 0 2-1.6L22 7H5.1"/>',
    "chart": '<path d="M3 3v18h18"/><path d="M18 17V9"/><path d="M13 17V5"/><path d="M8 17v-3"/>',
    "history": '<path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/><path d="M12 7v5l4 2"/>',
    "settings": '<path d="M20 7h-9"/><path d="M14 17H5"/><circle cx="17" cy="17" r="3"/><circle cx="7" cy="7" r="3"/>',
    "sun": '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M6.3 17.7l-1.4 1.4M19.1 4.9l-1.4 1.4"/>',
    "moon": '<path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"/>',
    "plus": '<path d="M5 12h14"/><path d="M12 5v14"/>',
    "minus": '<path d="M5 12h14"/>',
    "search": '<circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/>',
    "refresh": '<path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"/><path d="M8 16H3v5"/>',
    "printer": '<path d="M6 9V2h12v7"/><path d="M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2"/><rect x="6" y="14" width="12" height="8"/>',
    "trash": '<path d="M3 6h18"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>',
    "edit": '<path d="M17 3a2.85 2.85 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z"/>',
    "external": '<path d="M15 3h6v6"/><path d="M10 14 21 3"/><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>',
    "check": '<path d="M20 6 9 17l-5-5"/>',
    "x": '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
    "keyboard": '<rect x="2" y="4" width="20" height="16" rx="2"/><path d="M6 8h.01M10 8h.01M14 8h.01M18 8h.01M8 12h.01M12 12h.01M16 12h.01M7 16h10"/>',
    "qr": '<rect x="3" y="3" width="5" height="5" rx="1"/><rect x="16" y="3" width="5" height="5" rx="1"/><rect x="3" y="16" width="5" height="5" rx="1"/><path d="M21 16h-3a2 2 0 0 0-2 2v3"/><path d="M21 21v.01M12 7v3a2 2 0 0 1-2 2H7M3 12h.01M12 3h.01M12 16v.01M16 12h1M21 12v.01M12 21v-1"/>',
    "folder": '<path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"/>',
    "copy": '<rect x="8" y="8" width="14" height="14" rx="2"/><path d="M4 16a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2"/>',
    "wrench": '<path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/>',
    "alert": '<path d="m21.7 18-8-14a2 2 0 0 0-3.5 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.7-3"/><path d="M12 9v4"/><path d="M12 17h.01"/>',
    "file": '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/>',
    "tag": '<path d="M12.6 2.6A2 2 0 0 0 11.2 2H4a2 2 0 0 0-2 2v7.2a2 2 0 0 0 .6 1.4l8.7 8.7a2.4 2.4 0 0 0 3.4 0l6.6-6.6a2.4 2.4 0 0 0 0-3.4z"/><circle cx="7.5" cy="7.5" r=".5"/>',
    "chev_left": '<path d="m15 18-6-6 6-6"/>',
    "chev_down": '<path d="m6 9 6 6 6-6"/>',
    "sparkle": '<path d="M12 3l1.9 5.8L20 10l-6.1 1.2L12 17l-1.9-5.8L4 10l6.1-1.2z"/>',
    "eye": '<path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z"/><circle cx="12" cy="12" r="3"/>',
    "archive": '<rect x="2" y="3" width="20" height="5" rx="1"/><path d="M4 8v11a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8"/><path d="M10 12h4"/>',
    "grid": '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18M3 15h18M9 3v18M15 3v18"/>',
    "shelf": '<path d="M3 3v18M21 3v18M3 9h18M3 15h18M3 21h18"/><rect x="6" y="5" width="4" height="4"/><rect x="13" y="11" width="5" height="4"/>',
    "map": '<path d="M14.1 6 9.9 4 3 7v13l6.9-3 4.2 2L21 16V3z"/><path d="M9.9 4v13M14.1 6v13"/>',
    "merge": '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M12 3v6M12 15v6M8 12h8M14 10l2 2-2 2M10 10l-2 2 2 2"/>',
    "inbox": '<path d="M22 12h-6l-2 3h-4l-2-3H2"/><path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/>',
}

_icon_cache = {}


def svg(name, color, size=18, stroke=2.0):
    body = ICONS[name]
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 24 24" '
            f'fill="none" stroke="{color}" stroke-width="{stroke}" stroke-linecap="round" stroke-linejoin="round">'
            f'{body}</svg>')


def pixmap(name, color, size=18, stroke=2.0):
    key = (name, color, size, stroke)
    if key in _icon_cache:
        return _icon_cache[key]
    ratio = QApplication.instance().devicePixelRatio() if QApplication.instance() else 1
    ratio = max(ratio, 2)
    pm = QPixmap(int(size * ratio), int(size * ratio))
    pm.fill(Qt.transparent)
    r = QSvgRenderer(QByteArray(svg(name, color, size, stroke).encode()))
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    r.render(p, QRectF(0, 0, size * ratio, size * ratio))
    p.end()
    pm.setDevicePixelRatio(ratio)
    _icon_cache[key] = pm
    return pm


def icon(name, color_key="text2", size=18, color=None):
    c = color or Theme.c[color_key]
    ic = QIcon(pixmap(name, c, size))
    return ic


def _icon_file(name, color):
    """فایل موقت PNG برای استفاده در QSS (تیک چک‌باکس و فلش درخت)."""
    import os
    import tempfile
    path = os.path.join(tempfile.gettempdir(), f"wh_{name}_{color.strip('#')}.png")
    if not os.path.exists(path):
        pixmap(name, color, 14, 2.6 if name == "check" else 2.2).save(path)
    return path.replace("\\", "/")


def apply_theme(app, mode):
    Theme.mode = mode
    Theme.c = DARK if mode == "dark" else LIGHT
    c = Theme.c
    app.setStyle("Fusion")
    pal = QPalette()
    pal.setColor(QPalette.Window, QColor(c["bg"]))
    pal.setColor(QPalette.Base, QColor(c["surface"]))
    pal.setColor(QPalette.AlternateBase, QColor(c["surface2"]))
    pal.setColor(QPalette.Text, QColor(c["text"]))
    pal.setColor(QPalette.WindowText, QColor(c["text"]))
    pal.setColor(QPalette.Button, QColor(c["surface"]))
    pal.setColor(QPalette.ButtonText, QColor(c["text"]))
    pal.setColor(QPalette.Highlight, QColor(c["sel"]))
    pal.setColor(QPalette.HighlightedText, QColor(c["text"]))
    pal.setColor(QPalette.PlaceholderText, QColor(c["faint"]))
    pal.setColor(QPalette.ToolTipBase, QColor(c["surface"]))
    pal.setColor(QPalette.ToolTipText, QColor(c["text"]))
    app.setPalette(pal)
    app.setStyleSheet(QSS.substitute(
        font=FONT_FAMILY, check_icon=_icon_file("check", "#ffffff"),
        chev_closed=_icon_file("chev_left", c["muted"]), chev_open=_icon_file("chev_down", c["muted"]), **c))
    for w in app.topLevelWidgets():
        set_dark_titlebar(w, mode == "dark")
    for fn in list(Theme.listeners):
        try:
            fn()
        except RuntimeError:
            Theme.listeners.remove(fn)


def set_dark_titlebar(widget, dark=None):
    """نوار عنوان ویندوز را با تم هماهنگ می‌کند."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        dark = Theme.is_dark() if dark is None else dark
        hwnd = int(widget.winId())
        value = ctypes.c_int(1 if dark else 0)
        for attr in (20, 19):
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(value), ctypes.sizeof(value)) == 0:
                break
    except Exception:  # noqa: BLE001
        pass
