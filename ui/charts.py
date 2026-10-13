"""نمودارهای سبک با QPainter (میله‌ای ماهانه، میله‌ای افقی، اسپارک‌لاین قیمت)."""
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QToolTip, QWidget

from .theme import Theme
from .widgets import fmt_compact, fmt_int

JALALI_MONTHS = ["فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
                 "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند"]


def rounded_top_rect(rect, r):
    """میله با گوشه‌های گرد فقط در سر میله (r=4)."""
    r = min(r, rect.width() / 2, rect.height())
    path = QPainterPath()
    path.moveTo(rect.left(), rect.bottom())
    path.lineTo(rect.left(), rect.top() + r)
    path.quadTo(rect.left(), rect.top(), rect.left() + r, rect.top())
    path.lineTo(rect.right() - r, rect.top())
    path.quadTo(rect.right(), rect.top(), rect.right(), rect.top() + r)
    path.lineTo(rect.right(), rect.bottom())
    path.closeSubpath()
    return path


class MonthlyBarChart(QWidget):
    """data: [('1405/07', value)] — زمان از چپ به راست."""

    def __init__(self, unit="ریال", parent=None):
        super().__init__(parent)
        self.data, self.unit, self.hover = [], unit, -1
        self.setMouseTracking(True)
        self.setMinimumHeight(240)
        self.setLayoutDirection(Qt.LeftToRight)
        self._bars = []

    def set_data(self, data):
        self.data = data
        self.hover = -1
        self.update()

    @staticmethod
    def month_label(key):
        try:
            y, m = key.split("/")
            return JALALI_MONTHS[int(m) - 1]
        except (ValueError, IndexError):
            return key

    def paintEvent(self, e):
        """محور زمان راست‌به‌چپ: قدیمی‌ترین ماه سمت راست."""
        c = Theme.c
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        axis_w, top, bottom = 78, 24, 30
        plot = QRectF(8, top, w - axis_w - 16, h - top - bottom)
        vmax = max([v for _, v in self.data] + [0])
        small = QFont(self.font())
        small.setPointSizeF(8.5)
        p.setFont(small)
        if vmax <= 0:
            p.setPen(QColor(c["faint"]))
            p.drawText(self.rect(), Qt.AlignCenter, "هنوز خریدی ثبت نشده")
            return
        step = self._nice_step(vmax / 4)
        ticks = int(-(-vmax // step))
        top_v = step * ticks
        for i in range(ticks + 1):
            y = plot.bottom() - plot.height() * i / ticks
            if i:
                p.setPen(QPen(QColor(c["grid"]), 1))
                p.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
            p.setPen(QColor(c["faint"]))
            p.drawText(QRectF(plot.right() + 8, y - 9, axis_w, 18), Qt.AlignLeft | Qt.AlignVCenter,
                       fmt_compact(step * i))
        n = len(self.data)
        slot = plot.width() / n
        bw = min(30.0, slot * 0.56)
        self._bars = []
        imax = max(range(n), key=lambda i: self.data[i][1])
        for i, (key, v) in enumerate(self.data):
            sx = plot.right() - slot * (i + 1)
            x = sx + (slot - bw) / 2
            bh = plot.height() * v / top_v
            rect = QRectF(x, plot.bottom() - bh, bw, bh)
            self._bars.append(QRectF(sx, plot.top(), slot, plot.height() + bottom))
            if v > 0:
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(c["chart"]) if self.hover in (-1, i) else QColor(c["chart_soft"]))
                p.drawPath(rounded_top_rect(rect, 4))
            p.setPen(QColor(c["text"] if i == self.hover else c["muted"]))
            p.drawText(QRectF(sx, plot.bottom() + 6, slot, 20), Qt.AlignHCenter | Qt.AlignTop, self.month_label(key))
            if v > 0 and ((i == imax and self.hover == -1) or i == self.hover):
                p.setPen(QColor(c["text2"]))
                p.drawText(QRectF(x - 50, rect.top() - 20, bw + 100, 18), Qt.AlignHCenter | Qt.AlignBottom,
                           fmt_compact(v))
        p.setPen(QPen(QColor(c["border2"]), 1))
        p.drawLine(QPointF(plot.left(), plot.bottom()), QPointF(plot.right(), plot.bottom()))

    @staticmethod
    def _nice_step(raw):
        import math
        exp = 10 ** math.floor(math.log10(raw))
        for m in (1, 2, 2.5, 5, 10):
            if m * exp >= raw:
                return m * exp
        return 10 * exp

    def mouseMoveEvent(self, e):
        idx = next((i for i, r in enumerate(self._bars) if r.contains(e.position())), -1)
        if idx != self.hover:
            self.hover = idx
            self.update()
            if idx >= 0:
                key, v = self.data[idx]
                QToolTip.showText(e.globalPosition().toPoint(),
                                  f"{self.month_label(key)} {key.split('/')[0]}\n{fmt_int(v)} {self.unit}", self)
            else:
                QToolTip.hideText()

    def leaveEvent(self, e):
        self.hover = -1
        self.update()


class HBarList(QWidget):
    """لیست میله‌ای افقی راست‌چین: [(نام، مقدار، توضیح)]"""

    def __init__(self, value_fmt=fmt_compact, unit="ریال", parent=None):
        super().__init__(parent)
        self.unit = unit
        self.data, self.fmt, self.hover = [], value_fmt, -1
        self.setMouseTracking(True)
        self.row_h = 34
        self._rows = []

    def set_data(self, data):
        self.data = data
        self.setMinimumHeight(max(80, self.row_h * len(data) + 8))
        self.update()

    def paintEvent(self, e):
        c = Theme.c
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w = self.width()
        if not self.data:
            p.setPen(QColor(c["faint"]))
            p.drawText(self.rect(), Qt.AlignCenter, "داده‌ای نیست")
            return
        vmax = max(v for _, v, _ in self.data) or 1
        name_w = min(220, w * 0.38)
        val_w = 90
        bar_area = w - name_w - val_w - 16
        self._rows = []
        for i, (name, v, hint) in enumerate(self.data):
            y = 4 + i * self.row_h
            row = QRectF(0, y, w, self.row_h)
            self._rows.append(row)
            if i == self.hover:
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(c["hover"]))
                p.drawRoundedRect(row.adjusted(0, 1, 0, -1), 6, 6)
            p.setPen(QColor(c["text2"]))
            p.drawText(QRectF(w - name_w, y, name_w - 8, self.row_h), Qt.AlignRight | Qt.AlignVCenter,
                       p.fontMetrics().elidedText(name, Qt.ElideRight, int(name_w - 8)))
            bl = bar_area * v / vmax
            bar = QRectF(w - name_w - 8 - bl, y + self.row_h / 2 - 5, max(bl, 2), 10)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(c["chart"] if self.hover in (-1, i) else c["chart_soft"]))
            p.drawRoundedRect(bar, 4, 4)
            p.setPen(QColor(c["muted"]))
            p.drawText(QRectF(0, y, val_w, self.row_h), Qt.AlignLeft | Qt.AlignVCenter, self.fmt(v))

    def mouseMoveEvent(self, e):
        idx = next((i for i, r in enumerate(self._rows) if r.contains(e.position())), -1)
        if idx != self.hover:
            self.hover = idx
            self.update()
            if idx >= 0:
                name, v, hint = self.data[idx]
                QToolTip.showText(e.globalPosition().toPoint(), f"{name}\n{fmt_int(v)} {self.unit}" + (f"\n{hint}" if hint else ""), self)

    def leaveEvent(self, e):
        self.hover = -1
        self.update()


class Sparkline(QWidget):
    """تاریخچه‌ی قیمت: [(تاریخ، قیمت)]"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.points = []
        self.setFixedHeight(44)
        self.setMouseTracking(True)
        self.setLayoutDirection(Qt.LeftToRight)

    def set_points(self, pts):
        self.points = pts
        self.setVisible(len(pts) >= 2)
        self.update()

    def _xy(self):
        w, h = self.width() - 8, self.height() - 10
        vals = [v for _, v in self.points]
        lo, hi = min(vals), max(vals)
        span = (hi - lo) or 1
        n = len(vals)
        return [QPointF(4 + w * i / (n - 1), 5 + h - h * (v - lo) / span) for i, v in enumerate(vals)]

    def paintEvent(self, e):
        if len(self.points) < 2:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        pts = self._xy()
        path = QPainterPath(pts[0])
        for q in pts[1:]:
            path.lineTo(q)
        p.setPen(QPen(QColor(Theme.c["chart"]), 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.drawPath(path)
        p.setBrush(QColor(Theme.c["chart"]))
        p.setPen(QPen(QColor(Theme.c["surface"]), 2))
        p.drawEllipse(pts[-1], 4, 4)

    def mouseMoveEvent(self, e):
        if len(self.points) < 2:
            return
        pts = self._xy()
        i = min(range(len(pts)), key=lambda k: abs(pts[k].x() - e.position().x()))
        d, v = self.points[i]
        QToolTip.showText(e.globalPosition().toPoint(), f"{d}\n{fmt_int(v)} ریال", self)
