"""قفسه‌ها: هر نوع قفسه (کابینت کشویی، قفسه‌ی طبقه‌ای، جعبه‌ی خانه‌خانه، جعبه‌ی تکی) با چیدمان دلخواه،
ادغام خانه‌ها، چند ناحیه (اتاق/انبار) و اشیای آزاد در نقشه (میز، دیوار، نوشته)."""
import math

from PySide6.QtCore import QPointF, QRectF, Qt, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (QComboBox, QDoubleSpinBox, QFrame, QHBoxLayout, QLabel, QMenu, QPushButton, QScrollArea,
                               QSplitter, QStackedWidget, QToolTip, QVBoxLayout, QWidget)

from db import Database
from ..dialogs import BaseDialog, EnterToSave, FormDialog, MultiInput, combo, line, spin
from ..theme import Theme, icon
from ..widgets import (tokens_match, Button, Card, PageHeader, SearchBox, Segment, confirm, first_part, fmt_int, label, shortcut,
                       toast)

KIND_UNIT = {"drawers": "کشو", "shelf": "جعبه", "organizer": "قسمت", "box": "جعبه"}
KIND_HINT = {
    "drawers": "کابینت با کشوهای کوچک در ردیف و ستون (مثل کابینت قطعات).",
    "shelf": "قفسه با چند طبقه؛ روی هر طبقه چند جعبه یا سبد.",
    "organizer": "جعبه‌ی درب‌دار با خانه‌های داخلی (ارگانایزر).",
    "box": "یک جعبه یا کارتن تکی؛ می‌تواند تا ۳ بخش داشته باشد.",
}
COLORS = ["", "#2563eb", "#0e9384", "#079455", "#ca8504", "#dc6803", "#d92d20", "#7c3aed", "#667085"]


def ltr(t):
    """کد/متن لاتین داخل جمله‌ی فارسی درست نمایش داده شود (LRI … PDI)."""
    return "⁦" + str(t) + "⁩"


def norm(t):
    return (t or "").lower().replace("ي", "ی").replace("ك", "ک")


def kind_of(cab):
    return (cab["kind"] if cab["kind"] in KIND_UNIT else "drawers") if cab else "drawers"


def unit_word(cab):
    return KIND_UNIT[kind_of(cab)]


def cab_title(cab):
    return f"قفسه {cab['number']}" + (f" · {cab['name']}" if cab["name"] else "")


def drawer_is_empty(d):
    return d is None or (not d.get("title") and not any(l["main"] or l["sub"] for l in d["labels"])
                         and not any(d.get("parts", {}).values()))


def spans(d):
    return ((d.get("row_span") or 1), (d.get("col_span") or 1)) if d else (1, 1)


def comp_text(d, i):
    """متن اصلی/فرعی بخش i (از ۱)؛ اگر برچسب خالی است، پارت نامبر قطعه."""
    lab = d["labels"][i - 1]
    main, sub = lab["main"], lab["sub"]
    parts = d.get("parts", {}).get(i, [])
    if not main and parts:
        main = parts[0]["part_number"] + (f" +{len(parts) - 1}" if len(parts) > 1 else "")
    return main, sub


def tooltip_html(code, d, with_qty=True):
    lines = [f"<b>{ltr(code)}</b>  {d.get('title') or ''}"]
    for i in range(1, d["comps"] + 1):
        parts = d.get("parts", {}).get(i, [])
        if with_qty:
            txt = ", ".join(f"{pp['part_number']} ({'؟' if pp['needs_count'] else fmt_int(pp['quantity'])})" for pp in parts)
        else:
            txt = ", ".join(pp["part_number"] for pp in parts)
        txt = txt or " ".join(x for x in comp_text(d, i) if x) or "—"
        lines.append(f"{i}: {ltr(txt)}")
    return "<br>".join(lines)


class ColorSwatches(QWidget):
    """انتخاب رنگ از چند رنگ آماده (اولی = بدون رنگ)."""

    def __init__(self, current=""):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self.btns = {}
        for col in COLORS:
            b = QPushButton("" if col else "—")
            b.setCheckable(True)
            b.setFixedSize(26, 26)
            b.setCursor(Qt.PointingHandCursor)
            b.setToolTip("بدون رنگ" if not col else col)
            b.clicked.connect(lambda _=False, c=col: self.set(c))
            lay.addWidget(b)
            self.btns[col] = b
        lay.addStretch(1)
        self.set(current or "")

    def set(self, col):
        self.value = col if col in self.btns else ""
        for c, b in self.btns.items():
            on = c == self.value
            ring = Theme.c["text"] if on else Theme.c["border2"]
            bg = c or Theme.c["surface2"]
            b.setChecked(on)
            b.setStyleSheet(f"QPushButton {{ background:{bg}; border:{3 if on else 1}px solid {ring}; border-radius:13px;"
                            f" color:{Theme.c['muted']}; padding:0; min-height:0; min-width:0; }}")


# ======================================================================== grid (نمای یک قفسه)
class CabinetGrid(QWidget):
    selected = Signal(int, int)       # row, col (خانه‌ی اصلی)
    activated = Signal(int, int)
    typed = Signal(str)
    context = Signal(int, int, object)

    HEAD, SIDE = 26, 30
    MIN = {"drawers": (118, 70), "shelf": (110, 86), "organizer": (96, 76), "box": (300, 190)}
    RATIO = {"drawers": 0.62, "shelf": 0.78, "organizer": 0.8, "box": 0.62}

    def __init__(self):
        super().__init__()
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setLayoutDirection(Qt.LeftToRight)  # چیدمان فیزیکی: ستون A سمت چپ
        self.cab, self.drawers, self.hits, self.cover = None, {}, set(), {}
        self.sel = None
        self.range_start = None   # انتخاب چند خانه با Shift یا کشیدن (برای ادغام)
        self.range_end = None
        self.hover = None

    @property
    def kind(self):
        return kind_of(self.cab)

    def set_data(self, cab, drawers, hits):
        changed = not self.cab or not cab or self.cab["id"] != cab["id"]
        self.cab, self.drawers, self.hits = cab, drawers, hits
        self.cover = Database.cover_map(drawers)
        if changed:
            self.range_start = self.range_end = None
        if self.sel and self.sel in self.cover:
            self.sel = self.cover[self.sel]
        if self.cab:
            mw, mh = self.MIN[self.kind]
            self.setMinimumSize(self.SIDE + cab["cols"] * mw + 8, self.HEAD + cab["rows"] * mh + 12)
        self.update()

    def cell_size(self):
        cols, rows = self.cab["cols"], self.cab["rows"]
        w = (self.width() - self.SIDE - 8) / cols
        if self.kind == "box":
            w = min(w, 460)
        h = (self.height() - self.HEAD - 12) / rows
        return w, min(h, w * self.RATIO[self.kind])

    def cell_rect(self, row, col):
        """مستطیل خانه‌ی اصلی در (row, col) با احتساب ادغام."""
        w, h = self.cell_size()
        rs, cs = spans(self.drawers.get((row, col)))
        return QRectF(self.SIDE + col * w, self.HEAD + (row - 1) * h, w * cs, h * rs)

    def anchor(self, row, col):
        return self.cover.get((row, col), (row, col))

    def at(self, pos):
        if not self.cab:
            return None
        w, h = self.cell_size()
        col = int((pos.x() - self.SIDE) // w)
        row = int((pos.y() - self.HEAD) // h) + 1
        if 0 <= col < self.cab["cols"] and 1 <= row <= self.cab["rows"]:
            return self.anchor(row, col)
        return None

    def select(self, row, col, emit=True, extend=False):
        row, col = self.anchor(row, col)
        if extend:
            self.range_start = self.range_start or self.sel or (row, col)
            self.range_end = (row, col)
        else:
            self.range_start = self.range_end = None
        self.sel = (row, col)
        self.update()
        if emit:
            self.selected.emit(row, col)

    def selection_box(self):
        """(row, col, row_span, col_span) محدوده‌ی انتخاب چندتایی؛ None اگر فقط یک خانه انتخاب است."""
        if not self.range_start or not self.range_end or self.range_start == self.range_end:
            return None
        cells = []
        for (r, c) in (self.range_start, self.range_end):
            rs, cs = spans(self.drawers.get((r, c)))
            cells += [(r, c), (r + rs - 1, c + cs - 1)]
        r0, r1 = min(r for r, _ in cells), max(r for r, _ in cells)
        c0, c1 = min(c for _, c in cells), max(c for _, c in cells)
        return r0, c0, r1 - r0 + 1, c1 - c0 + 1

    def in_range(self, row, col):
        box = self.selection_box()
        if not box:
            return False
        r0, c0, rs, cs = box
        return r0 <= row < r0 + rs and c0 <= col < c0 + cs

    def anchors(self):
        for row in range(1, self.cab["rows"] + 1):
            for col in range(self.cab["cols"]):
                if (row, col) not in self.cover:
                    yield row, col

    # ---------------------------------------------------------------- painting
    def paintEvent(self, e):
        if not self.cab:
            return
        c = Theme.c
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        p.setLayoutDirection(Qt.LeftToRight)
        base = QFont(self.font())
        fonts = self._fonts(base)
        p.setFont(fonts[3])
        w, h = self.cell_size()
        kind = self.kind
        cols, rows = self.cab["cols"], self.cab["rows"]
        body = QRectF(self.SIDE, self.HEAD, cols * w, rows * h)
        tint = self.cab["color"] or c["border2"]
        # سرستون‌ها و شماره‌ی ردیف‌ها
        if kind != "box":
            p.setPen(QColor(c["faint"]))
            for col in range(cols):
                p.drawText(QRectF(self.SIDE + col * w, 0, w, self.HEAD - 4), Qt.AlignCenter, Database.col_letter(col))
            for row in range(1, rows + 1):
                p.drawText(QRectF(0, self.HEAD + (row - 1) * h, self.SIDE - 6, h), Qt.AlignRight | Qt.AlignVCenter, str(row))
        # بدنه‌ی قفسه
        if kind == "organizer":
            p.setPen(QPen(QColor(tint), 2.5))
            p.setBrush(QColor(c["surface2"]))
            p.drawRoundedRect(body.adjusted(-3, -3, 3, 3), 9, 9)
        elif kind == "shelf":
            p.setPen(QPen(QColor(tint), 4, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(QPointF(body.left() - 2, body.top() - 2), QPointF(body.left() - 2, body.bottom() + 2))
            p.drawLine(QPointF(body.right() + 2, body.top() - 2), QPointF(body.right() + 2, body.bottom() + 2))
            for row in range(1, rows + 1):
                y = body.top() + row * h
                p.drawLine(QPointF(body.left() - 2, y), QPointF(body.right() + 2, y))
        elif self.cab["color"]:
            p.setPen(QPen(QColor(tint), 2))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(body.adjusted(-1, -1, 1, 1), 9, 9)
        for row, col in self.anchors():
            self._draw_unit(p, row, col, fonts)

    @staticmethod
    def _fonts(base):
        f_title = QFont(base)
        f_title.setPointSizeF(7.6)
        f_title.setBold(True)
        f_main = QFont(base)
        f_main.setBold(True)
        f_main.setPointSizeF(8.6)
        f_sub = QFont(base)
        f_sub.setPointSizeF(6.8)
        small = QFont(base)
        small.setPointSizeF(8)
        return f_title, f_main, f_sub, small

    def _draw_unit(self, p, row, col, fonts):
        c = Theme.c
        f_title, f_main, f_sub, small = fonts
        kind = self.kind
        full = self.cell_rect(row, col)
        if kind == "organizer":
            r, radius = full.adjusted(1.5, 1.5, -1.5, -1.5), 4
        elif kind == "shelf":
            r, radius = full.adjusted(5, 9, -5, -4), 5       # جعبه روی طبقه
        else:
            r, radius = full.adjusted(3, 3, -3, -3), 7
        d = self.drawers.get((row, col))
        empty = drawer_is_empty(d)
        is_sel = self.sel == (row, col)
        in_rng = self.in_range(row, col)
        hit = (row, col) in self.hits
        hov = self.hover == (row, col)
        code = Database.col_letter(col) + str(row)
        if empty:
            p.setPen(QPen(QColor(c["accent"] if (is_sel or in_rng) else c["border2"]), 1.5 if is_sel else 1, Qt.DashLine))
            p.setBrush(QColor(c["sel"] if in_rng else c["hover"] if hov else c["surface2"]))
            p.drawRoundedRect(r, radius, radius)
            p.setFont(small)
            p.setPen(QColor(c["faint"]))
            rs, cs = spans(d)
            text = "+" if hov else (code if kind != "box" else "خالی — دابل‌کلیک برای تعریف")
            if rs > 1 or cs > 1:
                text += f"  ({cs}×{rs})"
            p.drawText(r, Qt.AlignCenter, text)
            return
        bg = c["accent_soft"] if hit else c["sel"] if in_rng else c["hover"] if hov else c["surface"]
        p.setBrush(QColor(bg))
        p.setPen(QPen(QColor(c["accent"] if (is_sel or hit or in_rng) else c["border2"]), 2 if is_sel else 1))
        p.drawRoundedRect(r, radius, radius)
        if kind == "drawers":   # دستگیره‌ی کشو
            p.setPen(QPen(QColor(c["border2"]), 2, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(QPointF(r.center().x() - 8, r.bottom() - 4), QPointF(r.center().x() + 8, r.bottom() - 4))
        head = min(20.0, r.height() * 0.3)
        p.setPen(QPen(QColor(c["border"]), 1))
        p.drawLine(QPointF(r.left() + 6, r.top() + head), QPointF(r.right() - 6, r.top() + head))
        p.setFont(f_title)
        p.setPen(QColor(c["muted"]))
        tr = QRectF(r.left() + 6, r.top(), r.width() - 12, head)
        p.drawText(tr, Qt.AlignCenter, p.fontMetrics().elidedText(d.get("title") or "", Qt.ElideRight, int(tr.width() - 20)))
        if kind != "box":
            p.setFont(small)
            p.setPen(QColor(c["faint"]))
            p.drawText(QRectF(r.left() + 6, r.top(), 30, head), Qt.AlignLeft | Qt.AlignVCenter, code)
        comps = d["comps"]
        body = QRectF(r.left(), r.top() + head, r.width(), r.height() - head - (5 if kind == "drawers" else 0))
        cw = body.width() / comps
        for i in range(1, comps + 1):
            cell = QRectF(body.left() + cw * (i - 1), body.top(), cw, body.height())
            if i > 1:
                p.setPen(QPen(QColor(c["border"]), 1))
                p.drawLine(QPointF(cell.left(), cell.top() + 4), QPointF(cell.left(), cell.bottom() - 4))
            main, sub = comp_text(d, i)
            inner = cell.adjusted(3, 2, -3, -2)
            p.setFont(f_main)
            p.setPen(QColor(c["text"]))
            fm = p.fontMetrics()
            if sub:
                mr = QRectF(inner.left(), inner.top(), inner.width(), inner.height() * 0.6)
                sr = QRectF(inner.left(), inner.top() + inner.height() * 0.55, inner.width(), inner.height() * 0.42)
            else:
                mr, sr = inner, None
            p.drawText(mr, Qt.AlignCenter, fm.elidedText(main, Qt.ElideRight, int(mr.width())))
            if sr is not None:
                p.setFont(f_sub)
                p.setPen(QColor(c["faint"]))
                p.drawText(sr, Qt.AlignHCenter | Qt.AlignTop, p.fontMetrics().elidedText(sub, Qt.ElideRight, int(sr.width())))
            # نقطه‌ی وضعیت: نارنجی = شمارش نشده، قرمز = تمام شده
            parts = d.get("parts", {}).get(i, [])
            dot = None
            if any(pp["needs_count"] for pp in parts):
                dot = c["warning"]
            elif any(pp["quantity"] <= 0 or (pp["min_quantity"] and pp["quantity"] < pp["min_quantity"]) for pp in parts):
                dot = c["danger"]
            if dot:
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(dot))
                p.drawEllipse(QPointF(cell.right() - 7, cell.top() + 7), 3, 3)

    # ---------------------------------------------------------------- input
    def mousePressEvent(self, e):
        self.setFocus()
        hit = self.at(e.position())
        if hit:
            if e.button() == Qt.RightButton and self.in_range(*hit):
                self.context.emit(hit[0], hit[1], e.globalPosition().toPoint())
                return
            self.select(*hit, extend=bool(e.modifiers() & Qt.ShiftModifier))
            if e.button() == Qt.RightButton:
                self.context.emit(hit[0], hit[1], e.globalPosition().toPoint())

    def mouseDoubleClickEvent(self, e):
        hit = self.at(e.position())
        if hit:
            self.activated.emit(*hit)

    def mouseMoveEvent(self, e):
        hit = self.at(e.position())
        if e.buttons() & Qt.LeftButton and hit and self.sel and hit != self.range_end and hit != self.sel:
            # کشیدن موس روی چند خانه = انتخاب برای ادغام
            self.range_start = self.range_start or self.sel
            self.range_end = hit
            self.update()
        if hit != self.hover:
            self.hover = hit
            self.update()
            self.setCursor(Qt.PointingHandCursor if hit else Qt.ArrowCursor)
        if hit:
            d = self.drawers.get(hit)
            code = Database.drawer_code(self.cab["number"], *hit)
            if drawer_is_empty(d):
                QToolTip.showText(e.globalPosition().toPoint(), f"{ltr(code)} — خالی (دابل‌کلیک برای تعریف)", self)
            else:
                QToolTip.showText(e.globalPosition().toPoint(), tooltip_html(code, d), self)

    def leaveEvent(self, e):
        self.hover = None
        self.update()

    def keyPressEvent(self, e):
        if not self.cab:
            return
        row, col = self.sel or (1, 0)
        k = e.key()
        rs, cs = spans(self.drawers.get((row, col)))
        moves = {Qt.Key_Up: (-1, 0), Qt.Key_Down: (rs, 0), Qt.Key_Left: (0, -1), Qt.Key_Right: (0, cs)}
        if k in moves:
            dr, dc = moves[k]
            nr = min(max(1, row + dr), self.cab["rows"])
            nc = min(max(0, col + dc), self.cab["cols"] - 1)
            self.select(nr, nc, extend=bool(e.modifiers() & Qt.ShiftModifier))
        elif k in (Qt.Key_Return, Qt.Key_Enter) and self.sel:
            self.activated.emit(*self.sel)
        elif k == Qt.Key_Delete:
            e.ignore()
        elif k == Qt.Key_Escape and self.range_start:
            self.range_start = self.range_end = None
            self.update()
        elif e.text() and e.text().isprintable() and not e.modifiers() & Qt.ControlModifier:
            self.typed.emit(e.text())
        else:
            super().keyPressEvent(e)


# ======================================================================== overview (نقشه‌ی یک ناحیه)
class OverviewWidget(QWidget):
    """همه‌ی قفسه‌های یک ناحیه با چیدمان واقعی + میز/دیوار/نوشته؛ خانه‌های پیدا‌شده روشن و چشمک‌زن می‌شوند."""
    selected = Signal(int, int, int)    # cabinet_id, row, col
    activated = Signal(int, int, int)
    moved = Signal(int, float, float)   # cabinet_id, x, y (در حالت ویرایش چیدمان)
    item_geom = Signal(int, float, float, float, float)
    item_edit = Signal(int)
    item_delete = Signal(int)
    add_item = Signal(str, float, float)
    cab_edit = Signal(int)

    ASPECT = 1.45   # نسبت عرض به ارتفاع یک خانه
    MARGIN = 30
    HANDLE = 10

    def __init__(self):
        super().__init__()
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setLayoutDirection(Qt.LeftToRight)
        self.setMinimumSize(520, 380)
        self.cabs, self.data, self.hits, self.items = [], {}, {}, []
        self.sel = None          # (cab_id, row, col)
        self.searching = False
        self.edit_layout = False
        self.hover = None
        self._drag = None
        self._frozen = None
        self.phase = 0.0
        self.pulse = QVariantAnimation(self)
        self.pulse.setStartValue(0.0)
        self.pulse.setEndValue(1.0)
        self.pulse.setDuration(1100)
        self.pulse.setLoopCount(-1)
        self.pulse.valueChanged.connect(self._tick)

    def _tick(self, v):
        self.phase = float(v)
        self.update()

    def set_data(self, cabs, data, hits, searching, items=()):
        """cabs: [cabinet dicts]   data: {cab_id: drawers}   hits: {cab_id: set((row, col))}   items: [map_item]"""
        self.cabs, self.data, self.hits, self.searching = list(cabs), data, hits, searching
        self.items = [dict(i) for i in items]
        if searching and any(hits.get(c["id"]) for c in self.cabs):
            if self.pulse.state() != QVariantAnimation.Running:
                self.pulse.start()
        else:
            self.pulse.stop()
            self.phase = 0.0
        self.update()

    # ---------------------------------------------------------------- geometry
    def _bounds(self):
        xs = [((c["pos_x"] or 0), (c["pos_x"] or 0) + c["cols"]) for c in self.cabs]
        ys = [((c["pos_y"] or 0), (c["pos_y"] or 0) + c["rows"]) for c in self.cabs]
        xs += [(i["x"], i["x"] + i["w"]) for i in self.items]
        ys += [(i["y"], i["y"] + i["h"]) for i in self.items]
        if not xs:
            return 0, 10, 0, 6
        return min(a for a, _ in xs), max(b for _, b in xs), min(a for a, _ in ys), max(b for _, b in ys)

    def _scale(self):
        if self._frozen:
            return self._frozen
        x0, x1, y0, y1 = self._bounds()
        w = self.width() - self.MARGIN * 2
        h = self.height() - self.MARGIN * 2
        s = min(w / max(0.5, (x1 - x0) * self.ASPECT), h / max(0.5, (y1 - y0)), 90)
        ox = self.MARGIN + (w - (x1 - x0) * self.ASPECT * s) / 2 - x0 * self.ASPECT * s
        oy = self.MARGIN + (h - (y1 - y0) * s) / 2 - y0 * s
        return s, ox, oy

    def unit_rect(self, x, y, w, h):
        s, ox, oy = self._scale()
        return QRectF(ox + x * self.ASPECT * s, oy + y * s, w * self.ASPECT * s, h * s)

    def cab_rect(self, c):
        return self.unit_rect(c["pos_x"] or 0, c["pos_y"] or 0, c["cols"], c["rows"])

    def cell_rect(self, c, row, col):
        r = self.cab_rect(c)
        rs, cs = spans(self.data.get(c["id"], {}).get((row, col)))
        cw, ch = r.width() / c["cols"], r.height() / c["rows"]
        return QRectF(r.left() + col * cw, r.top() + (row - 1) * ch, cw * cs, ch * rs)

    def at(self, pos):
        for c in reversed(self.cabs):
            r = self.cab_rect(c)
            if r.adjusted(-4, -4, 4, 4).contains(pos):
                col = int((pos.x() - r.left()) / (r.width() / c["cols"]))
                row = int((pos.y() - r.top()) / (r.height() / c["rows"])) + 1
                row, col = min(max(row, 1), c["rows"]), min(max(col, 0), c["cols"] - 1)
                row, col = Database.cover_map(self.data.get(c["id"], {})).get((row, col), (row, col))
                return c, row, col
        return None

    def item_at(self, pos):
        for it in reversed(self.items):
            r = self.unit_rect(it["x"], it["y"], it["w"], it["h"])
            if r.adjusted(-3, -3, 3, 3).contains(pos):
                handle = QRectF(r.right() - self.HANDLE, r.bottom() - self.HANDLE, self.HANDLE + 3, self.HANDLE + 3)
                return it, handle.contains(pos)
        return None, False

    def to_units(self, pos):
        s, ox, oy = self._scale()
        return (pos.x() - ox) / (self.ASPECT * s), (pos.y() - oy) / s

    # ---------------------------------------------------------------- painting
    def paintEvent(self, e):
        c = Theme.c
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        p.setLayoutDirection(Qt.LeftToRight)
        if not self.cabs and not self.items:
            p.setPen(QColor(c["faint"]))
            p.setLayoutDirection(Qt.RightToLeft)
            p.drawText(self.rect(), Qt.AlignCenter,
                       "این ناحیه هنوز خالی است\n«قفسه‌ی جدید» را بزنید؛ با «ویرایش چیدمان» هم میز و دیوار اضافه کنید")
            return
        if self.edit_layout:
            self._grid(p)
        s, _, _ = self._scale()
        for it in self.items:
            self._draw_item(p, it, s)
        small = QFont(self.font())
        small.setPointSizeF(max(6.0, min(8.0, s * 0.22)))
        tiny = QFont(small)
        tiny.setPointSizeF(max(5.5, small.pointSizeF() - 0.8))
        glow = 0.5 - 0.5 * math.cos(self.phase * 2 * math.pi)
        for cab in self.cabs:
            self._draw_cab(p, cab, tiny, glow)

    def _grid(self, p):
        """شبکه‌ی راهنما در حالت ویرایش (هر خانه)."""
        s, ox, oy = self._scale()
        col = QColor(Theme.c["border"])
        p.setPen(QPen(col, 1, Qt.DotLine))
        step_x, step_y = self.ASPECT * s, s
        if step_y < 6:
            return
        x = ox % step_x
        while x < self.width():
            p.drawLine(QPointF(x, 0), QPointF(x, self.height()))
            x += step_x
        y = oy % step_y
        while y < self.height():
            p.drawLine(QPointF(0, y), QPointF(self.width(), y))
            y += step_y

    def _draw_item(self, p, it, s):
        c = Theme.c
        r = self.unit_rect(it["x"], it["y"], it["w"], it["h"])
        col = QColor(it["color"]) if it.get("color") else None
        f = QFont(self.font())
        f.setPointSizeF(max(6.5, min(10.0, s * 0.26)))
        if it["kind"] == "wall":
            p.setPen(Qt.NoPen)
            p.setBrush(col or QColor(c["border2"]))
            p.drawRoundedRect(r, 2, 2)
            txt_col = QColor(c["surface"])
        elif it["kind"] == "text":
            if self.edit_layout:
                p.setPen(QPen(QColor(c["border2"]), 1, Qt.DashLine))
                p.setBrush(Qt.NoBrush)
                p.drawRoundedRect(r, 4, 4)
            txt_col = col or QColor(c["text2"])
            f.setBold(True)
            f.setPointSizeF(max(7.0, min(16.0, s * 0.32 * min(it["h"], 2))))
        else:
            fill = QColor(col or QColor(c["muted"]))
            fill.setAlphaF(0.13)
            p.setBrush(fill)
            p.setPen(QPen(col or QColor(c["border2"]), 1.2, Qt.DashLine))
            p.drawRoundedRect(r, 6, 6)
            txt_col = col or QColor(c["muted"])
        if it.get("text"):
            p.setFont(f)
            p.setPen(txt_col)
            p.setLayoutDirection(Qt.RightToLeft)
            p.drawText(r.adjusted(4, 2, -4, -2), Qt.AlignCenter | Qt.TextWordWrap, it["text"])
            p.setLayoutDirection(Qt.LeftToRight)
        if self.edit_layout:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(c["accent"]))
            p.drawRoundedRect(QRectF(r.right() - self.HANDLE + 2, r.bottom() - self.HANDLE + 2, self.HANDLE - 3,
                                     self.HANDLE - 3), 2, 2)

    def _draw_cab(self, p, cab, tiny, glow):
        c = Theme.c
        cr = self.cab_rect(cab)
        hits = self.hits.get(cab["id"], set())
        drawers = self.data.get(cab["id"], {})
        cover = Database.cover_map(drawers)
        kind = kind_of(cab)
        tint = QColor(cab["color"]) if cab["color"] else QColor(c["border2"])
        # بدنه
        radius = 9 if kind == "organizer" else 6
        p.setPen(QPen(QColor(c["accent"]) if hits else tint, 2 if (hits or cab["color"]) else 1.2))
        p.setBrush(QColor(c["surface2"]))
        p.drawRoundedRect(cr.adjusted(-4, -4, 4, 4), radius, radius)
        if kind == "shelf":
            p.setPen(QPen(tint, 2))
            for row in range(1, cab["rows"] + 1):
                y = cr.top() + row * cr.height() / cab["rows"]
                p.drawLine(QPointF(cr.left() - 4, y + 1.5), QPointF(cr.right() + 4, y + 1.5))
        gap = 0.5 if kind == "organizer" else 1.5
        for row in range(1, cab["rows"] + 1):
            for col in range(cab["cols"]):
                if (row, col) in cover:
                    continue
                rr = self.cell_rect(cab, row, col).adjusted(gap, gap + (2 if kind == "shelf" else 0), -gap, -gap)
                d = drawers.get((row, col))
                empty = drawer_is_empty(d)
                hit = (row, col) in hits
                sel = self.sel == (cab["id"], row, col)
                hov = self.hover == (cab["id"], row, col)
                if hit:
                    p.setBrush(QColor(c["accent"]))
                    p.setPen(Qt.NoPen)
                else:
                    col_bg = QColor(c["surface"] if not empty else c["surface2"])
                    if self.searching:
                        col_bg.setAlphaF(0.45)
                    p.setBrush(col_bg)
                    p.setPen(QPen(QColor(c["border"]), 1, Qt.SolidLine if not empty else Qt.DotLine))
                if hov and not hit:
                    p.setBrush(QColor(c["hover"]))
                p.drawRoundedRect(rr, 3, 3)
                if hit:  # حلقه‌ی چشمک‌زن
                    ring = QColor(c["accent"])
                    ring.setAlphaF(0.55 * (1 - glow))
                    p.setBrush(Qt.NoBrush)
                    p.setPen(QPen(ring, 2 + 5 * glow))
                    p.drawRoundedRect(rr.adjusted(-2 - 3 * glow, -2 - 3 * glow, 2 + 3 * glow, 2 + 3 * glow), 5, 5)
                if sel:
                    p.setBrush(Qt.NoBrush)
                    p.setPen(QPen(QColor(c["text"]), 2.2))
                    p.drawRoundedRect(rr.adjusted(-1, -1, 1, 1), 3, 3)
                if not empty and rr.width() > 34 and rr.height() > 16:
                    p.setFont(tiny)
                    if hit:
                        p.setPen(QColor("white"))
                    else:
                        tc = QColor(c["muted"])
                        if self.searching:
                            tc.setAlphaF(0.5)
                        p.setPen(tc)
                    title = d.get("title") or comp_text(d, 1)[0]
                    p.drawText(rr.adjusted(2, 0, -2, 0), Qt.AlignCenter,
                               p.fontMetrics().elidedText(title, Qt.ElideRight, int(rr.width() - 4)))
        # شماره و نام قفسه
        badge = QRectF(cr.left() - 12, cr.top() - 12, 22, 22)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(c["accent"]) if hits else (QColor(cab["color"]) if cab["color"] else QColor(c["text2"])))
        p.drawEllipse(badge)
        f = QFont(self.font())
        f.setBold(True)
        f.setPointSizeF(8.5)
        p.setFont(f)
        p.setPen(QColor("white" if (hits or cab["color"]) else c["surface"]))
        p.drawText(badge, Qt.AlignCenter, str(cab["number"]))
        if cab["name"] and cr.width() > 60:
            f2 = QFont(self.font())
            f2.setPointSizeF(7.5)
            p.setFont(f2)
            p.setPen(QColor(c["muted"]))
            nr = QRectF(badge.right() + 4, cr.top() - 22, cr.width() - 60, 15)
            p.drawText(nr, Qt.AlignLeft | Qt.AlignVCenter,
                       p.fontMetrics().elidedText(cab["name"], Qt.ElideRight, int(nr.width())))
        if hits:
            p.setFont(f)
            hb = QRectF(cr.right() - 34, cr.top() - 12, 48, 20)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(c["accent"]))
            p.drawRoundedRect(hb, 10, 10)
            p.setPen(QColor("white"))
            p.drawText(hb, Qt.AlignCenter, "‏" + f"{len(hits)} {unit_word(cab)}")
        if self.edit_layout:
            p.setPen(QPen(QColor(c["accent"]), 1.5, Qt.DashLine))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(cr.adjusted(-7, -7, 7, 7), 8, 8)

    # ---------------------------------------------------------------- input
    def mousePressEvent(self, e):
        self.setFocus()
        pos = e.position()
        hit = self.at(pos)
        if self.edit_layout:
            if e.button() == Qt.RightButton:
                self._edit_menu(pos, e.globalPosition().toPoint(), hit)
                return
            self._frozen = self._scale()
            if hit:
                cab = hit[0]
                self._drag = ("cab", cab["id"], pos, cab["pos_x"] or 0, cab["pos_y"] or 0, 0, 0)
                return
            it, on_handle = self.item_at(pos)
            if it:
                self._drag = ("resize" if on_handle else "item", it["id"], pos, it["x"], it["y"], it["w"], it["h"])
            return
        if not hit:
            return
        cab, row, col = hit
        self.sel = (cab["id"], row, col)
        self.update()
        self.selected.emit(cab["id"], row, col)

    def _edit_menu(self, pos, gpos, hit):
        m = QMenu(self)
        if hit:
            cid = hit[0]["id"]
            m.addAction(icon("edit", size=16), "ویرایش این قفسه…", lambda: self.cab_edit.emit(cid))
        else:
            it, _ = self.item_at(pos)
            if it:
                iid = it["id"]
                m.addAction(icon("edit", size=16), "ویرایش…", lambda: self.item_edit.emit(iid))
                m.addAction(icon("trash", size=16), "حذف", lambda: self.item_delete.emit(iid))
            else:
                x, y = self.to_units(pos)
                for kind, text in Database.MAP_KINDS.items():
                    m.addAction(icon("plus", size=16), f"افزودن {text} اینجا",
                                lambda k=kind: self.add_item.emit(k, round(x * 2) / 2, round(y * 2) / 2))
        m.exec(gpos)

    def mouseMoveEvent(self, e):
        pos = e.position()
        if self._drag:
            what, oid, start, x0, y0, w0, h0 = self._drag
            s, _, _ = self._scale()
            dx = (pos.x() - start.x()) / (self.ASPECT * s)
            dy = (pos.y() - start.y()) / s

            def snap(v):
                return round(v * 2) / 2
            if what == "cab":
                for c in self.cabs:
                    if c["id"] == oid:
                        c["pos_x"], c["pos_y"] = snap(x0 + dx), snap(y0 + dy)
            else:
                for it in self.items:
                    if it["id"] == oid:
                        if what == "item":
                            it["x"], it["y"] = snap(x0 + dx), snap(y0 + dy)
                        else:
                            it["w"], it["h"] = max(0.5, snap(w0 + dx)), max(0.5, snap(h0 + dy))
            self.update()
            return
        hit = self.at(pos)
        key = (hit[0]["id"], hit[1], hit[2]) if hit else None
        cursor = Qt.ArrowCursor
        if self.edit_layout:
            if hit:
                cursor = Qt.SizeAllCursor
            else:
                it, on_handle = self.item_at(pos)
                cursor = Qt.SizeFDiagCursor if on_handle else Qt.SizeAllCursor if it else Qt.ArrowCursor
        elif hit:
            cursor = Qt.PointingHandCursor
        self.setCursor(cursor)
        if key != self.hover:
            self.hover = key
            self.update()
        if hit and not self.edit_layout:
            cab, row, col = hit
            d = self.data.get(cab["id"], {}).get((row, col))
            code = Database.drawer_code(cab["number"], row, col)
            if drawer_is_empty(d):
                QToolTip.showText(e.globalPosition().toPoint(), f"{ltr(code)} — خالی", self)
            else:
                QToolTip.showText(e.globalPosition().toPoint(), tooltip_html(code, d, with_qty=False), self)

    def mouseReleaseEvent(self, e):
        if self._drag:
            what, oid = self._drag[0], self._drag[1]
            self._drag = None
            if what == "cab":
                for c in self.cabs:
                    if c["id"] == oid:
                        self.moved.emit(oid, float(c["pos_x"]), float(c["pos_y"]))
            else:
                for it in self.items:
                    if it["id"] == oid:
                        self.item_geom.emit(oid, it["x"], it["y"], it["w"], it["h"])
        self._frozen = None
        self.update()

    def mouseDoubleClickEvent(self, e):
        pos = e.position()
        hit = self.at(pos)
        if self.edit_layout:
            if hit:
                self.cab_edit.emit(hit[0]["id"])
                return
            it, _ = self.item_at(pos)
            if it:
                self.item_edit.emit(it["id"])
            return
        if hit:
            self.activated.emit(hit[0]["id"], hit[1], hit[2])

    def leaveEvent(self, e):
        self.hover = None
        self.update()

    def keyPressEvent(self, e):
        search = self.window().findChild(QWidget, "StorageSearch")
        if e.text() and e.text().isprintable() and not e.modifiers() & Qt.ControlModifier and search:
            search.setFocus()
            search.setText(search.text() + e.text())
        elif e.key() in (Qt.Key_Return, Qt.Key_Enter) and self.sel:
            self.activated.emit(*self.sel)
        else:
            super().keyPressEvent(e)


# ======================================================================== dialogs
class CabinetDialog(BaseDialog, EnterToSave):
    def __init__(self, parent, db, cab=None, area_id=None):
        super().__init__(parent, "ویرایش قفسه" if cab else "قفسه‌ی جدید",
                         "شماره‌ی قفسه اول کد مکان است (مثلاً ۳ در ⁦3-B4-1⁩). ستون‌ها از چپ A، B، … و ردیف‌ها "
                         "از بالا ۱، ۲، … نام‌گذاری می‌شوند.", 560)
        used = [c["number"] for c in db.list_cabinets()]
        self.used = set(used) - ({cab["number"]} if cab else set())
        self.kind = Segment(list(Database.CAB_KINDS.items()), kind_of(cab) if cab else "drawers")
        self.kind.changed.connect(self.on_kind)
        self.body.addLayout(self.field("نوع", self.kind))
        self.hint = label("", "Faint", wrap=True)
        self.body.addWidget(self.hint)
        self.num = spin(cab["number"] if cab else (max(used or [0]) + 1), 999, 1)
        self.name = line(cab["name"] if cab else "", "مثلاً کنار میز، قفسه‌ی فلزی، جعبه‌ی آبی")
        self.cols = spin(cab["cols"] if cab else 5, 26, 1)
        self.rows = spin(cab["rows"] if cab else 8, 60, 1)
        row = QHBoxLayout()
        row.addLayout(self.field("شماره", self.num))
        self.f_cols = self.field("ستون‌ها (A، B، …)", self.cols)
        self.f_rows = self.field("ردیف‌ها / طبقه‌ها", self.rows)
        row.addLayout(self.f_cols)
        row.addLayout(self.f_rows)
        self.body.addLayout(row)
        self.body.addLayout(self.field("نام (اختیاری)", self.name))
        row2 = QHBoxLayout()
        self.area = QComboBox()
        for a in db.areas():
            self.area.addItem(a["name"], a["id"])
        self.area.setCurrentIndex(max(0, self.area.findData(cab["area_id"] if cab else area_id)))
        row2.addLayout(self.field("ناحیه", self.area), 1)
        self.color = ColorSwatches(cab["color"] if cab else "")
        row2.addLayout(self.field("رنگ", self.color), 2)
        self.body.addLayout(row2)
        self.err = label("", "PillDanger")
        self.err.hide()
        self.footer_left.addWidget(self.err)
        self.add_buttons("ذخیره", "انصراف", ok_icon="check")
        self.install_enter()
        self.on_kind(self.kind.value)
        self.name.setFocus()

    @staticmethod
    def _set_field_visible(lay, on):
        for i in range(lay.count()):
            w = lay.itemAt(i).widget()
            if w:
                w.setVisible(on)

    def on_kind(self, k):
        self.hint.setText(KIND_HINT[k])
        self._set_field_visible(self.f_cols, k != "box")
        self._set_field_visible(self.f_rows, k != "box")
        self.adjustSize()

    def values(self):
        k = self.kind.value
        return dict(number=self.num.value(), name=self.name.text().strip(),
                    rows=1 if k == "box" else self.rows.value(), cols=1 if k == "box" else self.cols.value(),
                    kind=k, area_id=self.area.currentData(), color=self.color.value or None)

    def on_ok(self):
        if self.num.value() in self.used:
            self.err.setText("این شماره برای قفسه‌ی دیگری است")
            self.err.show()
            return
        self.accept()


class MapItemDialog(BaseDialog, EnterToSave):
    def __init__(self, parent, item=None, kind="box"):
        super().__init__(parent, "ویرایش شیء نقشه" if item else "شیء جدید در نقشه",
                         "فقط برای جهت‌یابی در نقشه است. اندازه بر حسب «خانه» است و با کشیدن گوشه هم تغییر می‌کند.", 460)
        it = dict(item) if item else {"kind": kind, "text": "", "w": 8 if kind == "wall" else 4,
                                      "h": 0.5 if kind == "wall" else 2, "color": ""}
        self.kind = Segment(list(Database.MAP_KINDS.items()), it["kind"])
        self.body.addLayout(self.field("نوع", self.kind))
        self.text = line(it["text"], "مثلاً میز کار، هویه، مانیتور، در ورودی")
        self.body.addLayout(self.field("متن", self.text))
        row = QHBoxLayout()
        self.w = QDoubleSpinBox()
        self.h = QDoubleSpinBox()
        for sp, v in ((self.w, it["w"]), (self.h, it["h"])):
            sp.setRange(0.5, 200)
            sp.setSingleStep(0.5)
            sp.setDecimals(1)
            sp.setValue(float(v))
            sp.setAlignment(Qt.AlignCenter)
        row.addLayout(self.field("عرض", self.w))
        row.addLayout(self.field("ارتفاع", self.h))
        self.body.addLayout(row)
        self.color = ColorSwatches(it.get("color") or "")
        self.body.addLayout(self.field("رنگ", self.color))
        self.add_buttons("ذخیره", "انصراف", ok_icon="check")
        self.install_enter()
        self.text.setFocus()

    def on_ok(self):
        self.accept()


class DrawerDialog(BaseDialog, EnterToSave):
    def __init__(self, parent, db, cab, row, col, drawer):
        code = Database.drawer_code(cab["number"], row, col)
        unit = unit_word(cab)
        where = f"ستون {ltr(Database.col_letter(col))}، ردیف {row}" if kind_of(cab) != "box" else ""
        super().__init__(parent, f"{unit} {ltr(code)}",
                         f"{cab_title(cab)}{' — ' + where if where else ''}.   پارت نامبر جدید خودکار به انبار اضافه می‌شود.",
                         760)
        self.db, self.cab, self.row, self.col = db, cab, row, col
        d = drawer or {"title": "", "comps": 1, "labels": Database._labels({"labels": "[]"}), "id": None,
                       "row_span": 1, "col_span": 1}
        parts = {}
        if d.get("id"):
            for pp in db.drawer_parts(d["id"]):
                parts.setdefault(pp["comp"], []).append(pp["part_number"])
        top = QHBoxLayout()
        self.title = combo(db.drawer_titles(), d.get("title") or "", "مثلاً Capacitor", ltr=True)
        top.addLayout(self.field("سرتیتر برچسب", self.title), 1)
        self.comps = Segment([("1", "۱ بخش"), ("2", "۲ بخش"), ("3", "۳ بخش")], str(d.get("comps") or 1))
        self.comps.changed.connect(self.update_comps)
        top.addLayout(self.field(f"تقسیم {unit}", self.comps))
        # اندازه: چند خانه‌ی شبکه را بگیرد (ادغام)
        self.cs = spin(d.get("col_span") or 1, max(1, cab["cols"] - col), 1)
        self.rs = spin(d.get("row_span") or 1, max(1, cab["rows"] - row + 1), 1)
        self.orig_span = (self.rs.value(), self.cs.value())
        if cab["rows"] * cab["cols"] > 1:
            sz = QHBoxLayout()
            sz.setSpacing(6)
            for sp in (self.cs, self.rs):
                sp.setFixedWidth(54)
            sz.addWidget(self.cs)
            sz.addWidget(label("×", "Muted"))
            sz.addWidget(self.rs)
            top.addLayout(self.field("اندازه (ستون × ردیف)", sz))
            self.cs.setToolTip("چند خانه به سمت راست را بگیرد")
            self.rs.setToolTip("چند خانه به پایین را بگیرد")
        self.body.addLayout(top)
        cards_box = QWidget()
        cards_box.setLayoutDirection(Qt.LeftToRight)  # بخش ۱ سمت چپ، مثل کشوی واقعی
        cards = QHBoxLayout(cards_box)
        cards.setContentsMargins(0, 0, 0, 0)
        cards.setSpacing(10)
        self.cards, self.mains, self.subs, self.parts = [], [], [], []
        pn_list = db.part_numbers()
        for i in range(3):
            c = Card(padding=12)
            c.lay.setSpacing(6)
            c.setLayoutDirection(Qt.RightToLeft)
            c.lay.addWidget(label(f"بخش {i + 1}   ·   {ltr(f'{code}-{i + 1}')}", "StatTitle"))
            m = line(d["labels"][i]["main"], "متن اصلی، مثلاً 680µF", ltr=True)
            s = line(d["labels"][i]["sub"], "متن کوچک، مثلاً 10x10 10V", ltr=True)
            pi = MultiInput(pn_list, "پارت نامبرها (با کاما)")
            pi.setText(", ".join(parts.get(i + 1, [])))
            c.lay.addWidget(m)
            c.lay.addWidget(s)
            c.lay.addWidget(label("قطعه‌ها", "Faint"))
            c.lay.addWidget(pi)
            cards.addWidget(c, 1)
            self.cards.append(c)
            self.mains.append(m)
            self.subs.append(s)
            self.parts.append(pi)
        self.body.addWidget(cards_box)
        self.body.addWidget(label("اگر «متن اصلی» خالی بماند، روی برچسب پارت نامبر قطعه چاپ می‌شود. "
                                  "بخش ۱ سمت چپ است.", "Faint", wrap=True))
        self.err = label("", "PillDanger")
        self.err.hide()
        self.footer_left.addWidget(self.err)
        if d.get("id"):
            clr = Button(f"خالی کردن {unit}", "trash", "Danger")
            clr.setAutoDefault(False)
            clr.clicked.connect(self.clear)
            self.footer_left.addWidget(clr)
        self.add_buttons("ذخیره", "انصراف", ok_icon="check")
        self.install_enter()
        self.update_comps(self.comps.value)
        self.title.setFocus()
        self.drawer = d
        self.cleared = False
        self.created = []

    def update_comps(self, v):
        n = int(v)
        for i, c in enumerate(self.cards):
            c.setVisible(i < n)
        self.adjustSize()

    def clear(self):
        if confirm(self, f"خالی کردن {unit_word(self.cab)}",
                   "برچسب و قطعه‌های آن پاک شود؟ (خود قطعه‌ها از انبار حذف نمی‌شوند)", "خالی کن", True):
            self.db.clear_drawer(self.drawer["id"])
            self.cleared = True
            self.accept()

    def on_ok(self):
        span = (self.rs.value(), self.cs.value())
        if span != self.orig_span:
            if not self.db.set_drawer_span(self.cab["id"], self.row, self.col, *span):
                self.err.setText(f"داخل این محدوده {unit_word(self.cab)} پر دیگری هست؛ اول آن را خالی کنید")
                self.err.show()
                return
        n = int(self.comps.value)
        title = self.title.currentText().strip()
        labels = [{"main": self.mains[i].text().strip(), "sub": self.subs[i].text().strip()} for i in range(3)]
        did = self.db.save_drawer(self.cab["id"], self.row, self.col, title, n, labels)
        for i in range(n):
            ids = []
            for pn in self.parts[i].tokens():
                part = self.db.find_part(pn)
                if not part:
                    lab = labels[i]
                    desc = " ".join(x for x in (title, lab["main"], lab["sub"]) if x and x != pn)
                    pid = self.db.save_part({"part_number": pn, "description": desc, "quantity": 0})
                    self.db.set_needs_count(pid, True)
                    self.created.append(pid)
                else:
                    pid = part["id"]
                ids.append(pid)
            self.db.set_comp_parts(did, i + 1, ids)
        self.accept()


# ======================================================================== side panel
class DrawerPanel(QFrame):
    def __init__(self, page):
        super().__init__()
        self.page = page
        self.setObjectName("Card")
        self.setMinimumWidth(300)
        self.setMaximumWidth(420)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setFrameShape(QFrame.NoFrame)
        sc.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        outer.addWidget(sc)
        body = QWidget()
        body.setObjectName("ScrollBody")
        sc.setWidget(body)
        self.lay = QVBoxLayout(body)
        self.lay.setContentsMargins(18, 16, 18, 16)
        self.lay.setSpacing(8)
        self.show_empty()

    def _clear(self):
        while self.lay.count():
            it = self.lay.takeAt(0)
            if it.widget():
                it.widget().hide()
                it.widget().deleteLater()
            elif it.layout():
                self._clear_layout(it.layout())

    def _clear_layout(self, lay):
        while lay.count():
            it = lay.takeAt(0)
            if it.widget():
                it.widget().hide()
                it.widget().deleteLater()
            elif it.layout():
                self._clear_layout(it.layout())

    def show_empty(self, text="یک خانه را انتخاب کنید"):
        self._clear()
        ic = QLabel()
        ic.setPixmap(icon("archive", "faint", 40).pixmap(40, 40))
        ic.setAlignment(Qt.AlignCenter)
        ic.setContentsMargins(0, 40, 0, 0)
        self.lay.addWidget(ic)
        t = label(text, "EmptyTitle", wrap=True)
        t.setAlignment(Qt.AlignCenter)
        self.lay.addWidget(t)
        h = label("دابل‌کلیک یا Enter = تعریف/ویرایش\nفلش‌ها = جابه‌جایی\nShift+کلیک یا کشیدن = انتخاب چند خانه برای ادغام",
                  "Faint", wrap=True)
        h.setAlignment(Qt.AlignCenter)
        self.lay.addWidget(h)
        self.lay.addStretch(1)

    def show_drawer(self, cab, row, col, d):
        self._clear()
        unit = unit_word(cab)
        code = Database.drawer_code(cab["number"], row, col)
        top = QHBoxLayout()
        t = label(code, "H1")
        t.setLayoutDirection(Qt.LeftToRight)
        top.addWidget(t)
        top.addStretch(1)
        edit = Button("ویرایش", "edit", tip="Enter")
        edit.clicked.connect(lambda: self.page.edit_drawer(row, col, cab["id"]))
        top.addWidget(edit)
        self.lay.addLayout(top)
        rs, cs = spans(d)
        where = f"ستون {ltr(Database.col_letter(col))}، ردیف {row}" if kind_of(cab) != "box" else Database.CAB_KINDS["box"]
        size = f"  ·  {cs}×{rs} خانه" if (rs > 1 or cs > 1) else ""
        self.lay.addWidget(label(f"{cab_title(cab)}  ·  {where}{size}", "Muted", wrap=True))
        if drawer_is_empty(d):
            self.lay.addSpacing(10)
            self.lay.addWidget(label(f"این {unit} هنوز تعریف نشده.", "Muted"))
            b = Button(f"تعریف {unit}", "plus", "Primary")
            b.clicked.connect(lambda: self.page.edit_drawer(row, col, cab["id"]))
            self.lay.addWidget(b)
            self.lay.addStretch(1)
            return
        if d.get("title"):
            self.lay.addWidget(label(d["title"], "PillAccent"), 0, Qt.AlignRight)
        for i in range(1, d["comps"] + 1):
            c = Card(padding=12)
            c.lay.setSpacing(4)
            hdr = QHBoxLayout()
            hdr.addWidget(label(ltr(f"{code}-{i}" if d["comps"] > 1 else code), "StatTitle"))
            hdr.addStretch(1)
            main, sub = d["labels"][i - 1]["main"], d["labels"][i - 1]["sub"]
            hdr.addWidget(label(ltr(" · ".join(x for x in (main, sub) if x)), "Muted"))
            c.lay.addLayout(hdr)
            parts = d.get("parts", {}).get(i, [])
            if not parts:
                c.lay.addWidget(label("قطعه‌ای ثبت نشده", "Faint"))
            for pp in parts:
                b = QPushButton()
                b.setObjectName("Ghost")
                b.setCursor(Qt.PointingHandCursor)
                b.setToolTip("نمایش در انبار قطعات")
                bl = QHBoxLayout(b)
                bl.setContentsMargins(8, 0, 8, 0)
                pn = label(pp["part_number"])
                pn.setAttribute(Qt.WA_TransparentForMouseEvents)
                bl.addWidget(pn, 1)
                if pp["needs_count"]:
                    q = label("شمارش نشده", "PillWarning")
                elif pp["quantity"] <= 0:
                    q = label("تمام شده", "PillDanger")
                else:
                    q = label(f"{fmt_int(pp['quantity'])} عدد", "Pill")
                q.setAttribute(Qt.WA_TransparentForMouseEvents)
                bl.addWidget(q)
                b.clicked.connect(lambda _=False, pid=pp["id"]: self.page.app.show_part(pid))
                c.lay.addWidget(b)
                if pp["description"]:
                    dl = label(first_part(pp["description"]), "Faint", wrap=True)
                    dl.setContentsMargins(8, 0, 8, 0)
                    c.lay.addWidget(dl)
            self.lay.addWidget(c)
        row_b = QHBoxLayout()
        pr = Button(f"لیبل این {unit}", "tag", tip="Ctrl+L")
        pr.clicked.connect(lambda: self.page.print_labels("drawer"))
        row_b.addWidget(pr)
        row_b.addStretch(1)
        self.lay.addLayout(row_b)
        self.lay.addStretch(1)


# ======================================================================== page
class TabStrip(QFrame):
    """ردیف دکمه‌های انتخابی (برای ناحیه‌ها و قفسه‌ها) که با هر تغییر از نو ساخته می‌شود."""
    chosen = Signal(int)

    def __init__(self):
        super().__init__()
        self.setObjectName("Segment")
        self.lay = QHBoxLayout(self)
        self.lay.setContentsMargins(3, 3, 3, 3)
        self.lay.setSpacing(2)
        self.btns = {}

    def build(self, items):
        """items: [(id, text)]"""
        while self.lay.count():
            w = self.lay.takeAt(0).widget()
            if w:
                w.deleteLater()
        self.btns = {}
        for oid, text in items:
            b = QPushButton(text)
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, i=oid: self.chosen.emit(i))
            self.lay.addWidget(b)
            self.btns[oid] = b

    def set_current(self, oid):
        for i, b in self.btns.items():
            b.setChecked(i == oid)


class StoragePage(QWidget):
    def __init__(self, app):
        super().__init__()
        self.app, self.db = app, app.db
        self.cab_id = None
        self.area_id = None
        self.areas = []
        self.cabs, self.all_hits, self.drawers, self.hit_counts = {}, {}, {}, {}
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)
        self.header = PageHeader("قفسه‌ها", "")
        b_add = Button("قفسه‌ی جدید", "plus", "Primary")
        b_add.clicked.connect(self.add_cabinet)
        b_new = Button("لیبل جدید", "tag", tip="ساخت لیبل قفسه از ۱ تا ۳ قطعه (Ctrl+L)")
        b_new.clicked.connect(lambda: self.print_labels("new"))
        b_pr = Button("لیبل همه‌ی خانه‌ها", "printer", tip="لیبل همه‌ی خانه‌های قفسه‌ی انتخاب‌شده (Ctrl+P)")
        b_pr.clicked.connect(lambda: self.print_labels("cabinet"))
        self.header.add(b_add, b_new, b_pr)
        root.addWidget(self.header)

        bar = QHBoxLayout()
        bar.setSpacing(10)
        self.search = SearchBox("جستجوی قطعه یا برچسب…  (کد مثل ⁦3-B4⁩)")
        self.search.setObjectName("StorageSearch")
        self.search.setFixedWidth(320)
        self.search.changed.connect(self.refresh_grid)
        self.search.returnPressed.connect(self.jump_first_hit)
        bar.addWidget(self.search)
        self.view_seg = Segment([("overview", "نقشه"), ("cabinet", "یک قفسه")], self.db.get_setting("storage_view", "overview"))
        self.view_seg.changed.connect(self.set_view)
        bar.addWidget(self.view_seg)
        self.layout_btn = Button("ویرایش چیدمان", "edit", tip="قفسه‌ها و اشیا را با کشیدن جابه‌جا کنید؛ راست‌کلیک = افزودن")
        self.layout_btn.setCheckable(True)
        self.layout_btn.toggled.connect(self.toggle_layout_edit)
        bar.addWidget(self.layout_btn)
        self.add_obj_btn = Button("افزودن شیء", "plus", tip="میز، دیوار یا نوشته برای جهت‌یابی در نقشه")
        m = QMenu(self)
        for kind, text in Database.MAP_KINDS.items():
            m.addAction(text, lambda k=kind: self.new_map_item(k))
        self.add_obj_btn.setMenu(m)
        bar.addWidget(self.add_obj_btn)
        bar.addStretch(1)
        self.legend = label("", "Faint")
        bar.addWidget(self.legend)
        root.addLayout(bar)

        bar2 = QHBoxLayout()
        bar2.setSpacing(8)
        self.area_tabs = TabStrip()
        self.area_tabs.chosen.connect(self.set_area)
        bar2.addWidget(self.area_tabs)
        self.area_btn = Button("ناحیه‌ها", "map", tip="ناحیه = اتاق یا انباری با نقشه‌ی جدا")
        am = QMenu(self)
        am.addAction(icon("plus", size=16), "ناحیه‌ی جدید…", self.add_area)
        am.addAction(icon("edit", size=16), "تغییر نام این ناحیه…", self.rename_area)
        am.addSeparator()
        am.addAction(icon("trash", size=16), "حذف این ناحیه", self.delete_area)
        self.area_btn.setMenu(am)
        bar2.addWidget(self.area_btn)
        self.tabs = TabStrip()
        self.tabs.chosen.connect(self.set_cabinet)
        self.tabs_scroll = QScrollArea()
        self.tabs_scroll.setWidget(self.tabs)
        self.tabs_scroll.setWidgetResizable(True)
        self.tabs_scroll.setFrameShape(QFrame.NoFrame)
        self.tabs_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.tabs_scroll.setFixedHeight(46)
        bar2.addWidget(self.tabs_scroll, 1)
        self.edit_cab_btn = Button("", "edit", "Icon", tip="ویرایش قفسه")
        self.edit_cab_btn.clicked.connect(lambda: self.edit_cabinet())
        bar2.addWidget(self.edit_cab_btn)
        self.bar2_stretch = QWidget()
        bar2.addWidget(self.bar2_stretch, 1)
        root.addLayout(bar2)

        split = QSplitter(Qt.Horizontal)
        split.setChildrenCollapsible(False)
        split.setHandleWidth(12)
        grid_card = Card()
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setFrameShape(QFrame.NoFrame)
        self.grid = CabinetGrid()
        sc.setWidget(self.grid)
        self.overview = OverviewWidget()
        self.stack = QStackedWidget()
        self.stack.addWidget(self.overview)
        self.stack.addWidget(sc)
        self.grid_scroll = sc
        grid_card.lay.setContentsMargins(10, 10, 10, 10)
        self.result_line = label("", "Muted")
        self.result_line.setContentsMargins(6, 0, 6, 6)
        grid_card.lay.addWidget(self.result_line)
        grid_card.lay.addWidget(self.stack, 1)
        self.panel = DrawerPanel(self)
        split.addWidget(grid_card)
        split.addWidget(self.panel)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 0)
        split.setSizes([900, 340])
        root.addWidget(split, 1)

        self.grid.selected.connect(self.on_select)
        self.grid.activated.connect(lambda r, c: self.edit_drawer(r, c))
        self.grid.typed.connect(lambda ch: (self.search.setFocus(), self.search.setText(self.search.text() + ch)))
        self.grid.context.connect(self.menu)
        self.overview.selected.connect(self.on_overview_select)
        self.overview.activated.connect(self.open_in_cabinet)
        self.overview.moved.connect(lambda cid, x, y: self.db.set_cabinet_pos(cid, x, y))
        self.overview.item_geom.connect(lambda iid, x, y, w, h: self.db.set_map_item_geom(iid, x, y, w, h))
        self.overview.item_edit.connect(self.edit_map_item)
        self.overview.item_delete.connect(self.delete_map_item)
        self.overview.add_item.connect(lambda k, x, y: self.new_map_item(k, x, y))
        self.overview.cab_edit.connect(lambda cid: self.edit_cabinet(cid))
        self.set_view(self.view_seg.value, save=False)
        shortcut(self, "Ctrl+P", lambda: self.print_labels("cabinet"))
        shortcut(self, "Ctrl+L", lambda: self.print_labels("drawer" if self.grid.sel else "new"))

    # ---------------------------------------------------------------- views
    def set_view(self, key, save=True):
        self.view = key
        self.view_seg.set(key)
        self.stack.setCurrentIndex(0 if key == "overview" else 1)
        if key != "overview" and self.layout_btn.isChecked():
            self.layout_btn.setChecked(False)
        self._update_bar()
        if save:
            self.db.set_setting("storage_view", key)
            self.refresh_grid()

    def _update_bar(self):
        ov = getattr(self, "view", "overview") == "overview"
        has_cabs = bool(self.area_cab_ids())
        self.layout_btn.setVisible(ov)
        self.add_obj_btn.setVisible(ov and self.layout_btn.isChecked())
        self.tabs_scroll.setVisible(not ov and has_cabs)
        self.edit_cab_btn.setVisible(not ov and has_cabs)
        self.bar2_stretch.setVisible(ov or not has_cabs)

    def toggle_layout_edit(self, on):
        self.overview.edit_layout = on
        self.layout_btn.setText("پایان ویرایش" if on else "ویرایش چیدمان")
        self._update_bar()
        self.overview.update()
        if on:
            toast(self, "قفسه‌ها و اشیا را با موس بکشید؛ گوشه‌ی اشیا = تغییر اندازه، راست‌کلیک = افزودن/حذف")
        self.refresh()

    def on_overview_select(self, cid, row, col):
        cab = self.cabs.get(cid)
        if cab:
            self.cab_id = cid
            self.drawers = self.all_hits.get(cid, ({}, set()))[0]
            self.grid.sel = (row, col)
            self.panel.show_drawer(cab, row, col, self.drawers.get((row, col)))

    def open_in_cabinet(self, cid, row, col):
        self.cab_id = cid
        self.db.set_setting("storage_cab", cid)
        self.set_view("cabinet")
        self.grid.select(row, col)
        self.grid.setFocus()

    # ---------------------------------------------------------------- areas
    def area_cab_ids(self):
        return [cid for cid, c in self.cabs.items() if c["area_id"] == self.area_id]

    def set_area(self, aid):
        self.area_id = aid
        self.db.set_setting("storage_area", aid)
        ids = self.area_cab_ids()
        if self.cab_id not in ids:
            self.cab_id = ids[0] if ids else None
            self.grid.sel = None
        self.overview.sel = None
        self.build_tabs()
        self.refresh_grid()

    def add_area(self):
        f = FormDialog(self, "ناحیه‌ی جدید", [("name", "نام", line("", "مثلاً انبار پشتی، اتاق تعمیرات"))],
                       "هر ناحیه نقشه‌ی جدای خودش را دارد.")
        f.validator = lambda v: "نام را بنویسید" if not v["name"] else None
        if f.exec():
            aid = self.db.save_area(f.values()["name"])
            self.area_id = aid
            self.db.set_setting("storage_area", aid)
            self.refresh()
            toast(self, "ناحیه اضافه شد — حالا قفسه‌هایش را بسازید")

    def rename_area(self):
        a = next((a for a in self.areas if a["id"] == self.area_id), None)
        if not a:
            return
        f = FormDialog(self, "تغییر نام ناحیه", [("name", "نام", line(a["name"]))])
        f.validator = lambda v: "نام را بنویسید" if not v["name"] else None
        if f.exec():
            self.db.save_area(f.values()["name"], a["id"])
            self.refresh()

    def delete_area(self):
        if len(self.areas) <= 1:
            toast(self, "حداقل یک ناحیه لازم است")
            return
        a = next((a for a in self.areas if a["id"] == self.area_id), None)
        if a and confirm(self, "حذف ناحیه", f"ناحیه‌ی «{a['name']}» حذف شود؟ قفسه‌هایش به ناحیه‌ی دیگری منتقل می‌شوند "
                                            "و میز/دیوارهای نقشه‌اش پاک می‌شوند.", "حذف", True):
            self.db.delete_area(a["id"])
            self.area_id = None
            self.app.data_changed()

    # ---------------------------------------------------------------- map items
    def new_map_item(self, kind, x=None, y=None):
        if self.area_id is None:
            return
        d = MapItemDialog(self, None, kind)
        if d.exec():
            if x is None:
                x, y = self.db._free_pos(self.area_id)
            self.db.save_map_item(self.area_id, d.kind.value, d.text.text().strip(), x, y, d.w.value(), d.h.value(),
                                  d.color.value or None)
            self.refresh_grid()

    def edit_map_item(self, iid):
        it = next((i for i in self.overview.items if i["id"] == iid), None)
        if not it:
            return
        d = MapItemDialog(self, it)
        dele = Button("حذف", "trash", "Danger")
        dele.setAutoDefault(False)
        dele.clicked.connect(lambda: d.done(2))
        d.footer_left.insertWidget(0, dele)
        res = d.exec()
        if res == 2:
            self.db.delete_map_item(iid)
        elif res:
            self.db.save_map_item(self.area_id, d.kind.value, d.text.text().strip(), it["x"], it["y"], d.w.value(),
                                  d.h.value(), d.color.value or None, iid)
        self.refresh_grid()

    def delete_map_item(self, iid):
        self.db.delete_map_item(iid)
        self.refresh_grid()

    # ---------------------------------------------------------------- data
    def refresh(self):
        self.areas = self.db.areas()
        self.cabs = {c["id"]: c for c in self.db.list_cabinets()}
        area_ids = [a["id"] for a in self.areas]
        if self.area_id not in area_ids:
            saved = self.db.get_setting("storage_area")
            self.area_id = int(saved) if saved.isdigit() and int(saved) in area_ids else area_ids[0]
        if self.cab_id not in self.cabs:
            saved = self.db.get_setting("storage_cab")
            self.cab_id = int(saved) if saved.isdigit() and int(saved) in self.cabs else None
        if self.cab_id is not None and self.cabs[self.cab_id]["area_id"] != self.area_id:
            self.cab_id = None
        if self.cab_id is None:
            ids = self.area_cab_ids()
            self.cab_id = ids[0] if ids else None
        self.build_tabs()
        self.refresh_grid()

    def build_tabs(self):
        self.area_tabs.build([(a["id"], a["name"]) for a in self.areas])
        self.area_tabs.setVisible(len(self.areas) > 1)
        self.tabs.build([(cid, cab_title(self.cabs[cid])) for cid in self.area_cab_ids()])
        self._update_bar()

    def set_cabinet(self, cid):
        self.cab_id = cid
        self.overview.sel = None
        self.db.set_setting("storage_cab", cid)
        self.grid.sel = None
        self.refresh_grid()

    def matches(self, d, tokens, code):
        if not tokens:
            return False
        hay = [code.lower(), norm(d.get("title"))]
        for l in d["labels"]:
            hay += [norm(l["main"]), norm(l["sub"])]
        for plist in d.get("parts", {}).values():
            for pp in plist:
                hay += [norm(pp["part_number"]), norm(pp["description"])]
        return tokens_match(tokens, " ".join(hay))

    def refresh_grid(self):
        q = norm(self.search.text()).strip()
        tokens = q.split()
        self.hit_counts = {}
        all_hits = {}
        pc = Database.parse_code(q)
        for cid, cab in self.cabs.items():
            drawers = self.db.cabinet_drawers(cid)
            hits = set()
            for (row, col), d in drawers.items():
                if self.matches(d, tokens, Database.drawer_code(cab["number"], row, col).lower()):
                    hits.add((row, col))
            # جستجوی مستقیم کد (مثلاً 3-B4)
            if pc and pc[0] == cab["number"] and 1 <= pc[1] <= cab["rows"] and 0 <= pc[2] < cab["cols"]:
                hits.add(Database.cover_map(drawers).get((pc[1], pc[2]), (pc[1], pc[2])))
            self.hit_counts[cid] = len(hits)
            all_hits[cid] = (drawers, hits)
        self.all_hits = all_hits
        # اگر در ناحیه/قفسه‌ی فعلی چیزی پیدا نشد، به جایی برو که پیدا شده
        if tokens:
            area_hits = {}
            for cid, n in self.hit_counts.items():
                aid = self.cabs[cid]["area_id"]
                area_hits[aid] = area_hits.get(aid, 0) + n
            if not area_hits.get(self.area_id) and any(area_hits.values()):
                self.area_id = max(area_hits, key=area_hits.get)
                self.build_tabs()
            ids = self.area_cab_ids()
            if ids and (self.cab_id not in ids or not self.hit_counts.get(self.cab_id)):
                best = max(ids, key=lambda i: self.hit_counts.get(i, 0))
                if self.hit_counts.get(best) or self.cab_id not in ids:
                    self.cab_id = best
        for a in self.areas:
            n = sum(self.hit_counts.get(cid, 0) for cid, c in self.cabs.items() if c["area_id"] == a["id"])
            b = self.area_tabs.btns.get(a["id"])
            if b:
                b.setText(a["name"] + (f"   ({n})" if tokens and n else ""))
        self.area_tabs.set_current(self.area_id)
        for cid, b in self.tabs.btns.items():
            n = self.hit_counts.get(cid, 0)
            b.setText(cab_title(self.cabs[cid]) + (f"   ({n})" if tokens and n else ""))
        self.tabs.set_current(self.cab_id)
        ids = self.area_cab_ids()
        self.overview.set_data([dict(self.cabs[i]) for i in ids], {cid: all_hits[cid][0] for cid in ids},
                               {cid: all_hits[cid][1] for cid in ids}, bool(tokens),
                               self.db.map_items(self.area_id) if self.area_id else [])
        n_hits = sum(len(v[1]) for v in all_hits.values())
        n_cabs = sum(1 for v in all_hits.values() if v[1])
        if tokens:
            text = f"{n_hits} خانه در {n_cabs} قفسه پیدا شد — خانه‌های روشن را ببینید" if n_hits else "چیزی پیدا نشد"
        elif self.view == "overview" and (ids or self.overview.items):
            text = ("حالت ویرایش: قفسه‌ها و اشیا را بکشید؛ راست‌کلیک روی جای خالی = افزودن میز/دیوار/نوشته؛ "
                    "دابل‌کلیک = ویرایش" if self.layout_btn.isChecked()
                    else "نقشه — برای پیدا کردن قطعه جستجو کنید؛ دابل‌کلیک روی خانه = باز کردن آن")
        else:
            text = ""
        self.result_line.setText(text)
        self.result_line.setVisible(bool(text))
        total = sum(c["rows"] * c["cols"] - len(Database.cover_map(all_hits[cid][0])) for cid, c in self.cabs.items())
        used = sum(1 for cid in self.cabs for d in all_hits[cid][0].values() if not drawer_is_empty(d))
        self.header.sub.setText(f"{len(self.cabs)} قفسه  ·  {used} از {total} خانه تعریف شده" if self.cabs
                                else "قفسه‌ها، کشوها و جعبه‌هایتان را بسازید و مثل واقعیت بچینید")
        self.header.sub.show()
        cab = self.cabs.get(self.cab_id)
        if not cab:
            self.grid.set_data(None, {}, set())
            self.legend.setText("")
            self.panel.show_empty("قفسه‌ای نیست — «قفسه‌ی جدید» را بزنید" if not ids else "یک خانه را انتخاب کنید")
            self.stack.setCurrentIndex(0)
            return
        self.stack.setCurrentIndex(0 if self.view == "overview" else 1)
        self.drawers, hits = all_hits[self.cab_id]
        self.grid.set_data(cab, self.drawers, hits)
        filled = sum(1 for d in self.drawers.values() if not drawer_is_empty(d))
        cells = cab["rows"] * cab["cols"] - len(Database.cover_map(self.drawers))
        self.legend.setText(f"این قفسه: {filled} از {cells} {unit_word(cab)} پر   ·   "
                            "● نارنجی: شمارش نشده   ● قرمز: تمام/کم" if self.view == "cabinet" else "")
        if tokens and self.view == "overview":
            sel = self.overview.sel
            if not sel or sel[0] not in ids or sel[1:] not in all_hits.get(sel[0], ({}, set()))[1]:
                for cid in sorted(ids, key=lambda k: self.cabs[k]["number"]):
                    if all_hits[cid][1]:
                        r, c_ = sorted(all_hits[cid][1], key=lambda rc: (rc[1], rc[0]))[0]
                        self.overview.sel = (cid, r, c_)
                        self.on_overview_select(cid, r, c_)
                        break
            else:
                self.on_overview_select(*sel)
        elif tokens and hits and (self.grid.sel not in hits):
            first = sorted(hits, key=lambda rc: (rc[1], rc[0]))[0]
            self.grid.select(*first)
        elif self.view == "overview" and self.overview.sel and self.overview.sel[0] in ids:
            self.on_overview_select(*self.overview.sel)
        elif self.view == "cabinet" and self.grid.sel:
            self.on_select(*self.grid.sel)
        elif self.view == "cabinet" and kind_of(cab) == "box":
            self.grid.select(1, 0)
        else:
            self.panel.show_empty()

    def jump_first_hit(self):
        (self.overview if self.view == "overview" else self.grid).setFocus()

    def on_select(self, row, col):
        cab = self.cabs.get(self.cab_id)
        if cab:
            self.panel.show_drawer(cab, row, col, self.drawers.get((row, col)))

    def select_drawer(self, drawer_id):
        d = self.db.get_drawer(drawer_id)
        if not d:
            return
        self.search.clear()
        cab = self.db.get_cabinet(d["cabinet_id"])
        self.area_id = cab["area_id"]
        self.cab_id = cab["id"]
        self.refresh()
        self.grid.select(d["row"], d["col"])
        if self.view == "overview":
            self.overview.sel = (d["cabinet_id"], d["row"], d["col"])
            self.overview.hits = {d["cabinet_id"]: {(d["row"], d["col"])}}
            self.overview.searching = True
            self.overview.pulse.start()
            self.on_overview_select(d["cabinet_id"], d["row"], d["col"])
            self.result_line.setText(f"{unit_word(cab)} {ltr(Database.drawer_code(cab['number'], d['row'], d['col']))}")
            self.result_line.show()
            self.overview.setFocus()
        else:
            self.grid.setFocus()

    # ---------------------------------------------------------------- actions
    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Delete and self.grid.sel:
            d = self.drawers.get(self.grid.sel)
            if d and not drawer_is_empty(d) and confirm(self, "خالی کردن", "برچسب و قطعه‌های این خانه پاک شود؟",
                                                        "خالی کن", True):
                self.db.clear_drawer(d["id"])
                self.app.data_changed()
        else:
            super().keyPressEvent(e)

    def add_cabinet(self):
        d = CabinetDialog(self, self.db, None, self.area_id)
        if d.exec():
            v = d.values()
            cid = self.db.save_cabinet(v["number"], v["name"], v["rows"], v["cols"], kind=v["kind"],
                                       area_id=v["area_id"], color=v["color"])
            self.cab_id = cid
            self.area_id = v["area_id"]
            self.grid.sel = None
            self.app.data_changed()
            toast(self, f"قفسه‌ی {v['number']} اضافه شد" +
                  (" — برای جابه‌جایی در نقشه «ویرایش چیدمان» را بزنید" if self.view == "overview" else ""))

    def edit_cabinet(self, cid=None):
        cab = self.cabs.get(cid or self.cab_id)
        if not cab:
            return
        d = CabinetDialog(self, self.db, cab)
        dele = Button("حذف قفسه", "trash", "Danger")
        dele.setAutoDefault(False)
        dele.clicked.connect(lambda: d.done(2))
        d.footer_left.insertWidget(0, dele)
        res = d.exec()
        if res == 2:
            if confirm(self, "حذف قفسه", f"قفسه‌ی {cab['number']} و همه‌ی خانه‌هایش حذف شود؟ (قطعه‌ها از انبار حذف نمی‌شوند)",
                       "حذف", True):
                self.db.delete_cabinet(cab["id"])
                self.cab_id = None
                self.app.data_changed()
        elif res:
            v = d.values()
            filled_out = [x for x in self.db.cabinet_drawers(cab["id"]).values()
                          if not drawer_is_empty(x) and (x["row"] > v["rows"] or x["col"] >= v["cols"])]
            if filled_out and not confirm(self, "کوچک کردن قفسه",
                                          f"{len(filled_out)} خانه‌ی پر بیرون از اندازه‌ی جدید می‌افتد و پاک می‌شود. ادامه؟",
                                          "ادامه", True):
                return
            self.db.save_cabinet(v["number"], v["name"], v["rows"], v["cols"], cab["id"], kind=v["kind"],
                                 area_id=v["area_id"], color=v["color"])
            self.area_id = v["area_id"]
            self.cab_id = cab["id"]
            self.app.data_changed()

    def edit_drawer(self, row, col, cab_id=None):
        cab = self.cabs.get(cab_id or self.cab_id)
        if not cab:
            return
        self.cab_id = cab["id"]
        drawer = self.db.drawer_at(cab["id"], row, col)
        if drawer:
            row, col = drawer["row"], drawer["col"]
        dlg = DrawerDialog(self, self.db, cab, row, col, drawer)
        if dlg.exec():
            self.app.data_changed()
            if self.view == "cabinet":
                self.grid.select(row, col)
                self.grid.setFocus()
            if dlg.created:
                toast(self, f"{len(dlg.created)} قطعه‌ی جدید به انبار اضافه شد — تعدادشان را در «انبار قطعات» بشمارید")
                self.app.enrich(dlg.created, quiet=True)

    def merge_selection(self):
        box = self.grid.selection_box()
        cab = self.cabs.get(self.cab_id)
        if not box or not cab:
            return
        r0, c0, rs, cs = box
        if not self.db.set_drawer_span(cab["id"], r0, c0, rs, cs):
            toast(self, "داخل محدوده به‌جز خانه‌ی بالا-چپ، خانه‌ی پر هست؛ اول خالی‌اش کنید")
            return
        self.grid.range_start = self.grid.range_end = None
        self.grid.sel = (r0, c0)
        self.app.data_changed()
        toast(self, f"{cs}×{rs} خانه یکی شد")

    def split_drawer(self, row, col):
        self.db.set_drawer_span(self.cab_id, row, col, 1, 1)
        self.app.data_changed()

    def menu(self, row, col, pos):
        cab = self.cabs.get(self.cab_id)
        unit = unit_word(cab)
        d = self.drawers.get((row, col))
        m = QMenu(self)
        box = self.grid.selection_box()
        if box:
            m.addAction(icon("merge", size=16), f"یکی کردن {box[2] * box[3]} خانه‌ی انتخاب‌شده", self.merge_selection)
            m.addSeparator()
        m.addAction(icon("edit", size=16), f"ویرایش {unit}\tEnter", lambda: self.edit_drawer(row, col))
        if d and spans(d) != (1, 1):
            m.addAction(icon("grid", size=16), "جدا کردن خانه‌ها", lambda: self.split_drawer(row, col))
        if d and not drawer_is_empty(d):
            m.addAction(icon("tag", size=16), f"لیبل این {unit}\tCtrl+L", lambda: self.print_labels("drawer"))
            m.addSeparator()
            m.addAction(icon("trash", size=16), f"خالی کردن {unit}\tDelete",
                        lambda: (confirm(self, "خالی کردن", "برچسب و قطعه‌های این خانه پاک شود؟", "خالی کن", True)
                                 and (self.db.clear_drawer(d["id"]), self.app.data_changed())))
        if not box and cab and cab["rows"] * cab["cols"] > 1:
            m.addSeparator()
            hint = m.addAction("برای ادغام: Shift+کلیک یا کشیدن روی چند خانه")
            hint.setEnabled(False)
        m.exec(pos)

    def print_labels(self, scope):
        from labels import DrawerLabelDialog, ShelfLabelDialog
        if scope in ("drawer", "new"):
            d, code = None, ""
            if scope == "drawer" and self.grid.sel and self.cab_id in self.cabs:
                d = self.drawers.get(self.grid.sel)
                code = Database.drawer_code(self.cabs[self.cab_id]["number"], *self.grid.sel)
            dlg = ShelfLabelDialog(self, self.db, drawer=d if d and not drawer_is_empty(d) else None, drawer_code=code)
            dlg.exec()
            if getattr(dlg, "saved_drawer", False):
                self.app.data_changed()
            return
        cab = self.cabs.get(self.cab_id)
        if not cab:
            return
        items = [(d, Database.drawer_code(cab["number"], row, col))
                 for (row, col), d in sorted(self.drawers.items(), key=lambda kv: (kv[0][0], kv[0][1]))
                 if not drawer_is_empty(d)]
        if not items:
            toast(self, "خانه‌ی تعریف‌شده‌ای برای چاپ نیست")
            return
        DrawerLabelDialog(self, self.db, items, cab_title(cab)).exec()
