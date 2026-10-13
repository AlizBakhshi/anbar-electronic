"""ویجت‌های مشترک: جدول سریع (Model/View)، کارت آمار، اعلان، دیالوگ پایه و…"""
from PySide6.QtCore import (QAbstractTableModel, QEasingCurve, QModelIndex, QPropertyAnimation, QRect, QSize,
                            QSortFilterProxyModel, Qt, QTimer, Signal)
from PySide6.QtGui import QAction, QColor, QFont, QKeySequence, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QAbstractItemView, QDialog, QFrame, QGraphicsOpacityEffect, QHBoxLayout, QHeaderView,
                               QLabel, QLayout, QLineEdit, QPushButton, QSizePolicy, QStyle, QStyledItemDelegate, QTableView,
                               QVBoxLayout, QWidget)

from .theme import Theme, icon, set_dark_titlebar

SortRole = Qt.UserRole + 1
RowRole = Qt.UserRole + 2
PillRole = Qt.UserRole + 3


# ------------------------------------------------------------------ formatting
def fmt_int(v):
    try:
        return f"{int(round(float(v or 0))):,}"
    except (TypeError, ValueError):
        return str(v or "")


def fmt_money(v):
    v = float(v or 0)
    return f"{int(round(v)):,}" if v else "—"


def fmt_compact(v):
    v = float(v or 0)
    for div, suf in ((1e9, " میلیارد"), (1e6, " میلیون"), (1e3, " هزار")):
        if abs(v) >= div:
            x = v / div
            return (f"{x:,.1f}".rstrip("0").rstrip(".")) + suf
    return f"{int(v):,}"


def first_part(text):
    """توضیحات فاکتور «فارسی | انگلیسی» است؛ در جدول بخش اول کافی است."""
    return (text or "").split(" | ")[0]


# ------------------------------------------------------------------ table model
class Col:
    def __init__(self, key, title, width=100, align="start", kind="text", stretch=False, fmt=None, pill=None, hide=0):
        self.key, self.title, self.width, self.kind, self.stretch = key, title, width, kind, stretch
        self.hide = hide  # ترتیب پنهان شدن در عرض کم (۱ = اول از همه)؛ ۰ = همیشه دیده شود
        self.fmt = fmt
        self.pill = pill  # تابع row -> (متن، نوع رنگ) برای نمایش به‌صورت برچسب
        self.align = {"start": Qt.AlignRight, "center": Qt.AlignHCenter, "end": Qt.AlignLeft}[align] | Qt.AlignVCenter


class TableModel(QAbstractTableModel):
    def __init__(self, columns, row_style=None, parent=None):
        super().__init__(parent)
        self.cols = columns
        self.rows = []
        self.row_style = row_style  # row -> "danger" | "muted" | "success" | None
        self._cache = {}  # (row, col, role) -> مقدار؛ رسم دوباره‌ی جدول فقط از حافظه می‌خواند
        Theme.listeners.append(self._cache.clear)

    def set_rows(self, rows):
        self.beginResetModel()
        self.rows = [dict(r) for r in rows]
        self._cache.clear()
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return len(self.cols)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal:
            if role == Qt.DisplayRole:
                return self.cols[section].title
            if role == Qt.TextAlignmentRole:
                return self.cols[section].align
        return None

    _MISS = object()

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        key = (index.row(), index.column(), role)
        v = self._cache.get(key, self._MISS)
        if v is self._MISS:
            v = self._data(index, role)
            self._cache[key] = v
        return v

    def _data(self, index, role):
        row = self.rows[index.row()]
        col = self.cols[index.column()]
        val = row.get(col.key)
        if role == Qt.DisplayRole:
            if col.pill:
                return None
            if col.fmt:
                return col.fmt(row)
            if col.kind == "int":
                return fmt_int(val)
            if col.kind == "money":
                return fmt_money(val)
            return "" if val is None else str(val)
        if role == SortRole:
            if col.kind in ("int", "money", "num"):
                try:
                    return float(val or 0)
                except (TypeError, ValueError):
                    return 0.0
            if col.pill:
                return col.pill(row)[0]
            return (col.fmt(row) if col.fmt else str(val or "")).lower()
        if role == PillRole and col.pill:
            return col.pill(row)
        if role == Qt.TextAlignmentRole:
            return col.align
        if role == Qt.ForegroundRole and self.row_style:
            st = self.row_style(row, col.key)
            if st:
                return Theme.color({"danger": "danger", "muted": "faint", "success": "success",
                                    "warning": "warning", "accent": "accent_text"}[st])
        if role == Qt.FontRole and col.kind in ("int", "money") and col.key in ("quantity", "stock"):
            f = QFont()
            f.setWeight(QFont.DemiBold)
            return f
        if role == Qt.ToolTipRole and col.kind == "text" and val and len(str(val)) > 40:
            return str(val).replace(" | ", "\n")
        if role == RowRole:
            return row
        return None


class FilterProxy(QSortFilterProxyModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.predicate = None
        self.setSortRole(SortRole)
        self.setSortCaseSensitivity(Qt.CaseInsensitive)

    def set_predicate(self, fn):
        self.predicate = fn
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row, source_parent):
        if self.predicate is None:
            return True
        return self.predicate(self.sourceModel().rows[source_row])


class PillDelegate(QStyledItemDelegate):
    """متن به شکل برچسب گرد رنگی."""

    def paint(self, painter, option, index):
        pill = index.data(PillRole)
        if not pill:
            return super().paint(painter, option, index)
        self.initStyleOption(option, index)
        option.text = ""
        option.widget.style().drawControl(QStyle.CE_ItemViewItem, option, painter, option.widget)
        text, kind = pill
        if not text:
            return
        c = Theme.c
        bg, fg = {"accent": ("accent_soft", "accent_text"), "danger": ("danger_soft", "danger"),
                  "success": ("success_soft", "success"), "warning": ("warning_soft", "warning"),
                  "muted": ("surface2", "muted")}.get(kind, ("surface2", "text2"))
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        f = QFont(option.font)
        f.setPointSizeF(f.pointSizeF() - 0.8)
        f.setWeight(QFont.DemiBold)
        painter.setFont(f)
        fm = painter.fontMetrics()
        w = fm.horizontalAdvance(text) + 18
        h = fm.height() + 6
        r = option.rect
        x = r.center().x() - w // 2
        rect = QRect(x, r.center().y() - h // 2, w, h)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(c[bg]))
        painter.drawRoundedRect(rect, h / 2, h / 2)
        painter.setPen(QColor(c[fg]))
        painter.drawText(rect, Qt.AlignCenter, text)
        painter.restore()


class DataTable(QTableView):
    """جدول سریع با مرتب‌سازی، فیلتر، منوی راست‌کلیک و پیام خالی بودن."""
    activated_row = Signal(dict)
    selection_changed = Signal()
    typed = Signal(str)
    context_menu = Signal(object)  # QPoint (global)

    def __init__(self, columns, row_style=None, multi=True, empty_text="موردی برای نمایش نیست", parent=None):
        super().__init__(parent)
        self.cols = columns
        self.model_ = TableModel(columns, row_style, self)
        self.proxy = FilterProxy(self)
        self.proxy.setSourceModel(self.model_)
        self.setModel(self.proxy)
        self.empty_text = empty_text
        self.setSortingEnabled(True)
        self.setAlternatingRowColors(True)
        self.setShowGrid(False)
        self.setWordWrap(False)
        self.setTextElideMode(Qt.ElideRight)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection if multi else QAbstractItemView.SingleSelection)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.verticalScrollBar().setSingleStep(18)
        self.setMouseTracking(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(lambda p: self.context_menu.emit(self.viewport().mapToGlobal(p)))
        vh = self.verticalHeader()
        vh.setVisible(False)
        vh.setSectionResizeMode(QHeaderView.Fixed)
        vh.setDefaultSectionSize(38)
        hh = self.horizontalHeader()
        hh.setHighlightSections(False)
        hh.setSectionsMovable(False)
        hh.setMinimumSectionSize(48)
        hh.setDefaultAlignment(Qt.AlignRight | Qt.AlignVCenter)
        for i, c in enumerate(columns):
            if c.stretch:
                hh.setSectionResizeMode(i, QHeaderView.Stretch)
            else:
                hh.setSectionResizeMode(i, QHeaderView.Interactive)
                self.setColumnWidth(i, c.width)
            if c.pill:
                self.setItemDelegateForColumn(i, PillDelegate(self))
        self.min_stretch = 180
        self.doubleClicked.connect(lambda idx: self.activated_row.emit(idx.data(RowRole)))
        self.selectionModel().selectionChanged.connect(lambda *a: self.selection_changed.emit())

    # --- data
    def set_rows(self, rows, keep_selection=True):
        sel = {r["id"] for r in self.selected_rows()} if keep_selection else set()
        current = self.currentIndex().data(RowRole)
        cur_id = current["id"] if current else None
        sb = self.verticalScrollBar().value()
        self.setUpdatesEnabled(False)
        self.model_.set_rows(rows)
        if sel or cur_id:
            self.select_ids(sel, cur_id)
        self.verticalScrollBar().setValue(sb)
        self.setUpdatesEnabled(True)

    def select_ids(self, ids, current_id=None):
        from PySide6.QtCore import QItemSelection, QItemSelectionModel
        selection = QItemSelection()
        cur = None
        for r in range(self.proxy.rowCount()):
            idx = self.proxy.index(r, 0)
            rid = idx.data(RowRole)["id"]
            if rid in ids:
                selection.select(idx, self.proxy.index(r, self.proxy.columnCount() - 1))
            if rid == current_id:
                cur = idx
        sm = self.selectionModel()
        sm.select(selection, QItemSelectionModel.ClearAndSelect)
        if cur is not None:
            sm.setCurrentIndex(cur, QItemSelectionModel.NoUpdate)

    def set_filter(self, fn):
        self.proxy.set_predicate(fn)

    def selected_rows(self):
        rows = [i.data(RowRole) for i in self.selectionModel().selectedRows()]
        return [r for r in rows if r]

    def current_row(self):
        rows = self.selected_rows()
        if len(rows) == 1:
            return rows[0]
        idx = self.currentIndex()
        return idx.data(RowRole) if idx.isValid() and rows else (rows[0] if rows else None)

    def visible_count(self):
        return self.proxy.rowCount()

    def select_row(self, r):
        from PySide6.QtCore import QItemSelectionModel
        if 0 <= r < self.proxy.rowCount():
            idx = self.proxy.index(r, 0)
            self.selectionModel().setCurrentIndex(
                idx, QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows)

    def select_first(self):
        self.select_row(0)

    # --- events
    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.fit_columns()

    def fit_columns(self):
        """ستون‌های کم‌اهمیت را وقتی جا نیست پنهان می‌کند تا ستون اصلی فشرده نشود."""
        avail = self.viewport().width()
        order = sorted([i for i, c in enumerate(self.cols) if c.hide], key=lambda i: self.cols[i].hide)
        hidden = set()
        def need():
            return sum(c.width for i, c in enumerate(self.cols) if not c.stretch and i not in hidden) + self.min_stretch
        for i in order:
            if need() <= avail:
                break
            hidden.add(i)
        for i, c in enumerate(self.cols):
            self.setColumnHidden(i, i in hidden)

    def keyPressEvent(self, e):
        text = e.text()
        if e.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Plus, Qt.Key_Minus, Qt.Key_Equal, Qt.Key_Delete,
                       Qt.Key_F2, Qt.Key_Slash):
            e.ignore()  # به صفحه سپرده می‌شود
            return
        if text and text.isprintable() and not e.modifiers() & (Qt.ControlModifier | Qt.AltModifier) and text not in "+-=/":
            self.typed.emit(text)
            return
        super().keyPressEvent(e)

    def paintEvent(self, e):
        super().paintEvent(e)
        if self.proxy.rowCount() == 0:
            p = QPainter(self.viewport())
            p.setPen(Theme.color("faint"))
            p.drawText(self.viewport().rect(), Qt.AlignCenter, self.empty_text)


# ------------------------------------------------------------------ layout helpers
def hbox(*widgets, spacing=8, margins=(0, 0, 0, 0), stretch_at=None):
    lay = QHBoxLayout()
    lay.setSpacing(spacing)
    lay.setContentsMargins(*margins)
    for i, w in enumerate(widgets):
        if w is None:
            lay.addStretch(1)
        elif isinstance(w, int):
            lay.addSpacing(w)
        elif isinstance(w, QLayout):
            lay.addLayout(w)
        else:
            lay.addWidget(w)
    return lay


def vbox(*widgets, spacing=8, margins=(0, 0, 0, 0)):
    lay = QVBoxLayout()
    lay.setSpacing(spacing)
    lay.setContentsMargins(*margins)
    for w in widgets:
        if w is None:
            lay.addStretch(1)
        elif isinstance(w, int):
            lay.addSpacing(w)
        elif isinstance(w, QLayout):
            lay.addLayout(w)
        else:
            lay.addWidget(w)
    return lay


def label(text="", obj=None, wrap=False):
    l = QLabel(text)
    if obj:
        l.setObjectName(obj)
    l.setWordWrap(wrap)
    return l


class Button(QPushButton):
    def __init__(self, text="", icon_name=None, kind=None, tip=None, parent=None):
        super().__init__((" " + text) if (icon_name and text) else text, parent)
        self.icon_name = icon_name
        self.kind = kind
        if kind:
            self.setObjectName(kind)
        if tip:
            self.setToolTip(tip)
        self.setCursor(Qt.PointingHandCursor)
        self.refresh_icon()
        Theme.listeners.append(self.refresh_icon)

    def refresh_icon(self):
        if self.icon_name:
            color = "#ffffff" if self.kind == "Primary" else Theme.c["danger"] if self.kind == "Danger" else Theme.c["text2"]
            self.setIcon(icon(self.icon_name, color=color, size=16))
            self.setIconSize(QSize(16, 16))


class Card(QFrame):
    def __init__(self, parent=None, padding=0):
        super().__init__(parent)
        self.setObjectName("Card")
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(padding, padding, padding, padding)
        self.lay.setSpacing(0)


def wrap_card(widget, padding=1):
    c = Card(padding=padding)
    c.lay.addWidget(widget)
    return c


class StatCard(Card):
    def __init__(self, title, icon_name, tone="accent", parent=None):
        super().__init__(parent)
        self.icon_name, self.tone = icon_name, tone
        self.lay.setContentsMargins(16, 14, 16, 14)
        top = QHBoxLayout()
        top.setSpacing(10)
        self.ico = QLabel()
        self.ico.setFixedSize(34, 34)
        self.ico.setAlignment(Qt.AlignCenter)
        t = QLabel(title)
        t.setObjectName("StatTitle")
        self.title_lbl = t
        top.addWidget(self.ico)
        top.addWidget(t, 1)
        self.value = QLabel("0")
        self.value.setObjectName("StatValue")
        self.hint = QLabel("")
        self.hint.setObjectName("StatHint")
        self.lay.addLayout(top)
        self.lay.addSpacing(8)
        self.lay.addWidget(self.value)
        self.lay.addWidget(self.hint)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.refresh_icon()
        Theme.listeners.append(self.refresh_icon)

    def refresh_icon(self):
        fg = {"accent": "accent", "danger": "danger", "success": "success", "warning": "warning"}[self.tone]
        bg = fg + "_soft"
        self.ico.setPixmap(icon(self.icon_name, color=Theme.c[fg if fg != "accent" else "accent_text"], size=18).pixmap(18, 18))
        self.ico.setStyleSheet(f"background:{Theme.c[bg]}; border-radius:9px;")

    def set(self, value, hint=""):
        self.value.setText(value)
        self.hint.setText(hint)
        self.hint.setVisible(bool(hint))


class SearchBox(QLineEdit):
    def __init__(self, placeholder="جستجو…", parent=None):
        super().__init__(parent)
        self.setObjectName("Search")
        self.setPlaceholderText(placeholder)
        self.setClearButtonEnabled(True)
        self.act = self.addAction(icon("search", "faint", 16), QLineEdit.LeadingPosition)
        Theme.listeners.append(lambda: self.act.setIcon(icon("search", "faint", 16)))
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(120)
        self.textChanged.connect(lambda: self._timer.start())

    @property
    def changed(self):
        return self._timer.timeout

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape and self.text():
            self.clear()
            return
        if e.key() == Qt.Key_Down:
            self.focusNextChild()
            return
        super().keyPressEvent(e)


class Segment(QFrame):
    changed = Signal(str)

    def __init__(self, options, current=None, parent=None):
        """options: [(key, title)]"""
        super().__init__(parent)
        self.setObjectName("Segment")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(3, 3, 3, 3)
        lay.setSpacing(2)
        self.btns = {}
        for key, title in options:
            b = QPushButton(title)
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, k=key: self.set(k, emit=True))
            lay.addWidget(b)
            self.btns[key] = b
        self.set(current or options[0][0])

    def set(self, key, emit=False):
        self.value = key
        for k, b in self.btns.items():
            b.setChecked(k == key)
        if emit:
            self.changed.emit(key)


class PageHeader(QWidget):
    def __init__(self, title, subtitle="", parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        tl = QVBoxLayout()
        tl.setSpacing(2)
        tl.addWidget(label(title, "H1"))
        self.sub = label(subtitle, "Muted")
        self.sub.setVisible(bool(subtitle))
        tl.addWidget(self.sub)
        lay.addLayout(tl)
        lay.addStretch(1)
        self.actions = QHBoxLayout()
        self.actions.setSpacing(8)
        lay.addLayout(self.actions)

    def add(self, *widgets):
        for w in widgets:
            self.actions.addWidget(w)


class Toast(QLabel):
    def __init__(self, parent, text, kind="ok"):
        super().__init__(text, parent)
        self.setObjectName("Toast")
        self.setWordWrap(True)
        self.setMaximumWidth(520)
        self.adjustSize()
        pw = parent.width()
        self.move((pw - self.width()) // 2, parent.height() - self.height() - 28)
        eff = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(eff)
        self.anim = QPropertyAnimation(eff, b"opacity", self)
        self.anim.setDuration(160)
        self.anim.setStartValue(0.0)
        self.anim.setEndValue(1.0)
        self.anim.setEasingCurve(QEasingCurve.OutCubic)
        self.show()
        self.raise_()
        self.anim.start()
        QTimer.singleShot(2600, self.fade_out)

    def fade_out(self):
        self.anim.setDirection(QPropertyAnimation.Backward)
        self.anim.finished.connect(self.deleteLater)
        self.anim.start()


_active_toast = [None]


def toast(widget, text, kind="ok"):
    win = widget.window()
    old = _active_toast[0]
    if old is not None:
        try:
            old.deleteLater()
        except RuntimeError:
            pass
    _active_toast[0] = Toast(win, text, kind)


# ------------------------------------------------------------------ dialogs
class BaseDialog(QDialog):
    def __init__(self, parent, title, subtitle="", width=460):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(width)
        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(24, 20, 24, 18)
        self.root.setSpacing(14)
        head = QVBoxLayout()
        head.setSpacing(2)
        head.addWidget(label(title, "H2"))
        if subtitle:
            head.addWidget(label(subtitle, "Muted", wrap=True))
        self.root.addLayout(head)
        self.body = QVBoxLayout()
        self.body.setSpacing(12)
        self.root.addLayout(self.body)
        self.footer = QHBoxLayout()
        self.footer.setSpacing(8)
        self.footer_left = QHBoxLayout()
        self.footer.addLayout(self.footer_left)
        self.footer.addStretch(1)
        self.root.addSpacing(4)
        self.root.addLayout(self.footer)

    def add_buttons(self, ok_text="ذخیره", cancel_text="انصراف", danger=False, ok_icon=None):
        self.ok_btn = Button(ok_text, ok_icon, "Danger" if danger else "Primary")
        self.ok_btn.setDefault(True)
        self.ok_btn.clicked.connect(self.on_ok)
        self.footer.addWidget(self.ok_btn)
        if cancel_text:
            c = Button(cancel_text)
            c.setAutoDefault(False)
            c.clicked.connect(self.reject)
            self.footer.addWidget(c)
        return self.ok_btn

    def on_ok(self):
        self.accept()

    def showEvent(self, e):
        set_dark_titlebar(self)
        super().showEvent(e)

    def field(self, title, widget, hint=None):
        box = QVBoxLayout()
        box.setSpacing(4)
        box.addWidget(label(title, "StatTitle"))
        box.addLayout(widget) if isinstance(widget, QLayout) else box.addWidget(widget)
        if hint:
            box.addWidget(label(hint, "Faint", wrap=True))
        return box


def confirm(parent, title, text, ok_text="تأیید", danger=False):
    d = BaseDialog(parent, title, width=420)
    d.body.addWidget(label(text, "Muted", wrap=True))
    d.add_buttons(ok_text, "انصراف", danger)
    return d.exec() == QDialog.Accepted


def info(parent, title, text):
    d = BaseDialog(parent, title, width=420)
    d.body.addWidget(label(text, "Muted", wrap=True))
    d.add_buttons("باشه", None)
    d.exec()


def shortcut(widget, keys, fn, context=Qt.WidgetWithChildrenShortcut):
    act = QAction(widget)
    act.setShortcuts([QKeySequence(k) for k in (keys if isinstance(keys, (list, tuple)) else [keys])])
    act.setShortcutContext(context)
    act.triggered.connect(lambda *_: fn())
    widget.addAction(act)
    return act


class Divider(QFrame):
    def __init__(self):
        super().__init__()
        self.setObjectName("Divider")
        self.setFrameShape(QFrame.NoFrame)


class FlowLayout(QLayout):
    """چیدمان شکستنی: ویجت‌ها کنار هم و در صورت کمبود جا، در خط بعد (راست‌به‌چپ)."""

    def __init__(self, parent=None, spacing=6):
        super().__init__(parent)
        self.items = []
        self.setSpacing(spacing)
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):
        self.items.append(item)

    def count(self):
        return len(self.items)

    def itemAt(self, i):
        return self.items[i] if 0 <= i < len(self.items) else None

    def takeAt(self, i):
        return self.items.pop(i) if 0 <= i < len(self.items) else None

    def expandingDirections(self):
        return Qt.Orientations(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do(QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do(rect, apply=True)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        w = max((it.minimumSize().width() for it in self.items), default=0)
        return QSize(min(w, 120), self.heightForWidth(max(w, 120)))

    def _do(self, rect, apply):
        rtl = self.parentWidget() is None or self.parentWidget().layoutDirection() == Qt.RightToLeft
        x = rect.right() if rtl else rect.left()
        y, line_h, sp = rect.top(), 0, self.spacing()
        for it in self.items:
            hint = it.sizeHint()
            w = min(hint.width(), rect.width())
            if rtl:
                if x - w + 1 < rect.left() and line_h:
                    x, y, line_h = rect.right(), y + line_h + sp, 0
                if apply:
                    it.setGeometry(QRect(x - w + 1, y, w, hint.height()))
                x -= w + sp
            else:
                if x + w - 1 > rect.right() and line_h:
                    x, y, line_h = rect.left(), y + line_h + sp, 0
                if apply:
                    it.setGeometry(QRect(x, y, w, hint.height()))
                x += w + sp
            line_h = max(line_h, hint.height())
        return y + line_h - rect.top()


def token_in(token, hay):
    """جستجوی یک کلمه: اگر با عدد شروع شود، وسط عدد دیگری پیدا نشود (1k ≠ 91k ، ولی 555 = NE555)."""
    if token[:1].isdigit():
        i = hay.find(token)
        while i != -1:
            if i == 0 or not hay[i - 1].isdigit() and hay[i - 1] != ".":
                return True
            i = hay.find(token, i + 1)
        return False
    return token in hay


def tokens_match(tokens, hay):
    return all(token_in(t, hay) for t in tokens)
