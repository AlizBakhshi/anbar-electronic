"""چاپ برچسب قطعه با QR (چاپگر برچسب یا برگه‌ی A4) و خروجی PDF."""
import qrcode
from PySide6.QtCore import QMarginsF, QPointF, QRectF, QSizeF, Qt
from PySide6.QtGui import QColor, QFont, QPageLayout, QPageSize, QPainter, QPen, QTextOption
from PySide6.QtPrintSupport import QPrintDialog, QPrinter, QPrintPreviewDialog
from PySide6.QtWidgets import QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QSpinBox, QWidget

from ui.widgets import BaseDialog, Button, label, toast

# (کلید، عنوان، عرض mm، ارتفاع mm، ستون‌ها در A4 یا None برای چاپگر برچسب)
PRESETS = [
    ("roll50x30", "چاپگر برچسب ۵۰×۳۰ میلی‌متر", 50, 30, None),
    ("roll40x25", "چاپگر برچسب ۴۰×۲۵ میلی‌متر", 40, 25, None),
    ("roll60x40", "چاپگر برچسب ۶۰×۴۰ میلی‌متر", 60, 40, None),
    ("a4_3x8", "برگه A4 — ۳ ستون × ۸ ردیف (۷۰×۳۷)", 70, 37, 3),
    ("a4_4x10", "برگه A4 — ۴ ستون × ۱۰ ردیف (۴۸×۲۷)", 48.5, 27, 4),
]


def qr_matrix(text):
    q = qrcode.QRCode(border=0, error_correction=qrcode.constants.ERROR_CORRECT_M)
    q.add_data(text)
    q.make(fit=True)
    return q.get_matrix()


def draw_qr(p, rect, text):
    m = qr_matrix(text)
    n = len(m)
    cell = min(rect.width(), rect.height()) / n
    p.save()
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("black"))
    for y, row in enumerate(m):
        for x, v in enumerate(row):
            if v:
                p.drawRect(QRectF(rect.x() + x * cell, rect.y() + y * cell, cell + 0.01, cell + 0.01))
    p.restore()


def draw_label(p, r, part, cats, font_family):
    """یک برچسب در مستطیل r (واحد: پیکسل دستگاه)."""
    pad = r.height() * 0.08
    inner = r.adjusted(pad, pad, -pad, -pad)
    qr_size = inner.height()
    # QR سمت چپ، متن سمت راست
    draw_qr(p, QRectF(inner.left(), inner.top(), qr_size, qr_size), part["part_number"])
    text_rect = QRectF(inner.left() + qr_size + pad, inner.top(), inner.width() - qr_size - pad, inner.height())
    h = text_rect.height()
    p.setPen(QColor("black"))
    pn_font = QFont("Consolas", 1)
    pn_font.setBold(True)
    pn_font.setPixelSize(max(6, int(h * 0.2)))
    p.setFont(pn_font)
    fm = p.fontMetrics()
    pn = fm.elidedText(part["part_number"], Qt.ElideRight, int(text_rect.width()))
    p.drawText(QRectF(text_rect.left(), text_rect.top(), text_rect.width(), h * 0.26),
               Qt.AlignLeft | Qt.AlignVCenter, pn)
    body = QFont(font_family, 1)
    body.setPixelSize(max(5, int(h * 0.125)))
    p.setFont(body)
    desc = (part["description"] or "").split(" | ")[0]
    opt = QTextOption(Qt.AlignRight | Qt.AlignTop)
    opt.setWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
    opt.setTextDirection(Qt.RightToLeft)
    p.drawText(QRectF(text_rect.left(), text_rect.top() + h * 0.28, text_rect.width(), h * 0.42), desc, opt)
    small = QFont(font_family, 1)
    small.setPixelSize(max(5, int(h * 0.12)))
    small.setBold(True)
    p.setFont(small)
    bits = []
    if part["package"]:
        bits.append(part["package"])
    if part["location"]:
        bits.append(part["location"])
    cat = cats.get(part["category_id"])
    foot = "  ·  ".join(bits) or (cat["name"] if cat else "")
    p.drawText(QRectF(text_rect.left(), text_rect.bottom() - h * 0.24, text_rect.width(), h * 0.24),
               Qt.AlignRight | Qt.AlignVCenter, p.fontMetrics().elidedText(foot, Qt.ElideRight, int(text_rect.width())))
    p.setPen(QColor("#bbbbbb"))
    p.setBrush(Qt.NoBrush)


class LabelDialog(BaseDialog):
    def __init__(self, parent, db, parts, font_family):
        super().__init__(parent, "چاپ برچسب قطعه", f"{len(parts)} قطعه انتخاب شده — QR هر برچسب پارت نامبر است "
                         "و با اسکنر بارکد در برنامه جستجو می‌شود.", 480)
        self.db, self.parts, self.font_family = db, parts, font_family
        self.preset = QComboBox()
        for key, title, *_ in PRESETS:
            self.preset.addItem(title, key)
        last = db.get_setting("label_preset", "roll50x30")
        self.preset.setCurrentIndex(max(0, self.preset.findData(last)))
        self.copies = QSpinBox()
        self.copies.setRange(1, 50)
        self.copies.setButtonSymbols(QSpinBox.NoButtons)
        self.copies.setAlignment(Qt.AlignCenter)
        self.border = QCheckBox("کادر دور برچسب (برای برش برگه A4)")
        self.border.setChecked(True)
        self.body.addLayout(self.field("نوع برچسب", self.preset))
        self.body.addLayout(self.field("تعداد از هر قطعه", self.copies))
        self.body.addWidget(self.border)
        pdf = Button("ذخیره PDF", "file")
        pdf.setAutoDefault(False)
        pdf.clicked.connect(self.save_pdf)
        self.footer_left.addWidget(pdf)
        self.add_buttons("پیش‌نمایش و چاپ", "انصراف", ok_icon="printer")

    def spec(self):
        key = self.preset.currentData()
        self.db.set_setting("label_preset", key)
        return next(p for p in PRESETS if p[0] == key)

    def make_printer(self, pdf_path=None):
        _, _, w, h, cols = self.spec()
        pr = QPrinter(QPrinter.HighResolution)
        if pdf_path:
            pr.setOutputFormat(QPrinter.PdfFormat)
            pr.setOutputFileName(pdf_path)
        if cols:
            pr.setPageSize(QPageSize(QPageSize.A4))
            pr.setPageMargins(QMarginsF(0, 0, 0, 0), QPageLayout.Millimeter)
        else:
            size = QPageSize(QSizeF(min(w, h), max(w, h)), QPageSize.Millimeter, "label", QPageSize.ExactMatch)
            pr.setPageLayout(QPageLayout(size, QPageLayout.Landscape if w > h else QPageLayout.Portrait,
                                         QMarginsF(0, 0, 0, 0), QPageLayout.Millimeter))
            pr.setFullPage(True)
        return pr

    def paint(self, printer):
        _, _, w_mm, h_mm, cols = self.spec()
        cats = self.db.categories()
        items = [p for p in self.parts for _ in range(self.copies.value())]
        p = QPainter(printer)
        p.setRenderHint(QPainter.Antialiasing)
        dpm = printer.resolution() / 25.4
        page = printer.pageLayout().fullRectPixels(printer.resolution())
        if cols:
            rows = int((page.height() / dpm - 8) // h_mm)
            per_page = cols * rows
            x0 = (page.width() / dpm - cols * w_mm) / 2
            y0 = (page.height() / dpm - rows * h_mm) / 2
        else:
            per_page = 1
        for i, part in enumerate(items):
            if i and i % per_page == 0:
                printer.newPage()
            if cols:
                k = i % per_page
                r = QRectF((x0 + (k % cols) * w_mm) * dpm, (y0 + (k // cols) * h_mm) * dpm, w_mm * dpm, h_mm * dpm)
            else:
                # اگر درایور چاپگر اندازه‌ی برچسب را نپذیرفت، برچسب متناسب در صفحه جا می‌شود
                k_ = min(1.0, page.width() / (w_mm * dpm), page.height() / (h_mm * dpm))
                r = QRectF(0, 0, w_mm * dpm * k_, h_mm * dpm * k_)
            draw_label(p, r, part, cats, self.font_family)
            if self.border.isChecked() and cols:
                p.setPen(QColor("#c8c8c8"))
                p.drawRect(r)
        p.end()

    def on_ok(self):
        self._printer = pr = self.make_printer()
        dlg = QPrintPreviewDialog(pr, self)
        dlg.setWindowTitle("پیش‌نمایش برچسب‌ها")
        dlg.resize(900, 700)
        dlg.paintRequested.connect(self.paint)
        if dlg.exec():
            self.accept()

    def save_pdf(self):
        path, _ = QFileDialog.getSaveFileName(self, "ذخیره PDF", "labels.pdf", "PDF (*.pdf)")
        if not path:
            return
        self.paint(self.make_printer(path))
        toast(self, "فایل PDF ذخیره شد")


# ------------------------------------------------------------------ برچسب قفسه/کشو (هم‌سبک برچسب‌های فعلی)
DRAWER_PRESETS = [
    ("d49x24", "۴۹×۲۴ میلی‌متر (برچسب فعلی قفسه‌ها)", 49, 24),
    ("d45x25", "۴۵×۲۵ میلی‌متر", 45, 25),
    ("d50x28", "۵۰×۲۸ میلی‌متر", 50, 28),
    ("d40x22", "۴۰×۲۲ میلی‌متر", 40, 22),
]

TITLE_KEYWORDS = [
    ("capacitor", "Capacitor"), ("resistor", "Resistor"), ("inductor", "Inductor"), ("ferrite", "Ferrite Bead"),
    ("crystal", "Crystal"), ("oscillator", "Crystal"), ("mosfet", "Mosfet"), ("transistor", "Transistor"),
    ("diode", "Diode"), ("rectifier", "Diode"), ("led", "LED"), ("regulator", "Regulator"), ("relay", "Relay"),
    ("terminal", "Terminal"), ("connector", "Connector"), ("header", "Header"), ("switch", "Switch"),
    ("fuse", "Fuse"), ("sensor", "Sensor"), ("display", "Display"), ("module", "Module"), ("mcu", "MCU"),
    ("microcontroller", "MCU"), ("potentiometer", "Potentiometer"), ("buzzer", "Buzzer"), ("antenna", "Antenna"),
    ("cable", "Cable"), ("optocoupler", "IC"), ("integrated circuits", "IC"), ("ics", "IC"),
]


def guess_title(db, part):
    """سرتیتر مناسب: اول از کشویی که قطعه در آن است، بعد از دسته‌ی لیون، بعد از توضیحات."""
    locs = db.part_locations(part["id"])
    for l in locs:
        if l["title"]:
            return l["title"]
    cat = db.categories().get(part["category_id"])
    hay = " ".join((cat["path"] if cat else "", part["description"] or "")).lower()
    for kw, title in TITLE_KEYWORDS:
        if kw in hay:
            return title
    return cat["chain"][-1] if cat else ""


def guess_texts(db, part):
    """(متن اصلی، متن کوچک) برای خانه‌ی قطعه: از برچسب کشو اگر هست، وگرنه پارت نامبر و پکیج."""
    for l in db.part_locations(part["id"]):
        d = db.get_drawer(l["drawer_id"])
        if d:
            lab = d["labels"][l["comp"] - 1]
            if lab["main"]:
                return lab["main"], lab["sub"]
    return part["part_number"], part["package"] or ""


def _fit_font(p, family, text, max_w, max_h, bold=True, start=None):
    f = QFont(family, 1)
    f.setBold(bold)
    size = int(start or max_h)
    while size > 4:
        f.setPixelSize(size)
        p.setFont(f)
        fm = p.fontMetrics()
        if fm.horizontalAdvance(text) <= max_w and fm.height() <= max_h * 1.2:
            break
        size -= 1
    return f


def draw_drawer_label(p, r, drawer, code="", with_qr=False, show_code=True):
    """r: مستطیل برچسب. سرتیتر بالا، زیر آن ۱ تا ۳ خانه با متن اصلی (درشت) و متن کوچک.
    drawer: {"title", "comps", "labels": [{"main", "sub"}×3], "parts"(اختیاری)}"""
    p.save()
    p.setLayoutDirection(Qt.LeftToRight)
    pen = QPen(QColor("black"))
    pen.setWidthF(max(1.0, r.height() * 0.014))
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    inner = r.adjusted(r.width() * 0.035, r.height() * 0.07, -r.width() * 0.035, -r.height() * 0.07)
    p.drawRect(inner)
    head_h = inner.height() * 0.30
    p.drawLine(QPointF(inner.left(), inner.top() + head_h), QPointF(inner.right(), inner.top() + head_h))
    pad = inner.height() * 0.04
    left_w = right_w = 0.0
    if with_qr and code:
        qs = head_h - pad * 2
        draw_qr(p, QRectF(inner.left() + pad * 1.5, inner.top() + pad, qs, qs), code)
        left_w = qs + pad * 2
    if show_code and code:
        cf = QFont("Consolas", 1)
        cf.setPixelSize(max(4, int(head_h * 0.30)))
        p.setFont(cf)
        right_w = p.fontMetrics().horizontalAdvance(code) + pad * 3
        p.drawText(QRectF(inner.right() - right_w, inner.top(), right_w - pad * 1.5, head_h),
                   Qt.AlignRight | Qt.AlignVCenter, code)
    side = max(left_w, right_w)  # سرتیتر همیشه وسط برچسب بماند
    title = drawer.get("title") or ""
    tr = QRectF(inner.left() + side, inner.top(), inner.width() - side * 2, head_h)
    _fit_font(p, "Georgia", title, tr.width() - pad * 2, head_h * 0.6, True, head_h * 0.56)
    p.drawText(tr, Qt.AlignCenter, title)
    comps = max(1, min(3, drawer.get("comps") or 1))
    body = QRectF(inner.left(), inner.top() + head_h, inner.width(), inner.height() - head_h)
    cw = body.width() / comps
    # گام ۱: چیدمان و اندازه‌ی فونت هر خانه؛ گام ۲: کوچک‌ترین اندازه برای همه (یکدست مثل برچسب دست‌ساز)
    cells = []
    for i in range(comps):
        cell = QRectF(body.left() + cw * i, body.top(), cw, body.height())
        lab = drawer["labels"][i]
        main, sub = lab.get("main") or "", lab.get("sub") or ""
        if not main and drawer.get("parts", {}).get(i + 1):
            main = drawer["parts"][i + 1][0]["part_number"]
        box = cell.adjusted(pad * 1.5, pad * 1.5, -pad * 1.5, -pad * 1.5)
        main_r = QRectF(box.left(), box.top() + box.height() * 0.04, box.width(), box.height() * 0.58)
        sub_r = QRectF(box.left(), box.top() + box.height() * 0.62, box.width(), box.height() * 0.36)
        two_lines = comps > 1 and " " in main and len(main) > 6
        start = box.height() * 0.58 * (0.46 if comps == 1 else 0.40)
        fit_text = max(main.split(), key=len) if two_lines else main
        fit_h = main_r.height() * (0.45 if two_lines else 0.75)
        m_size = _fit_font(p, "Arial", fit_text, main_r.width(), fit_h, True, start).pixelSize() if main else 999
        s_size = _fit_font(p, "Arial", sub, sub_r.width(), sub_r.height() * 0.62, True, sub_r.height() * 0.5).pixelSize() if sub else 999
        cells.append((cell, box, main, sub, main_r, sub_r, two_lines, m_size, s_size))
    any_sub = any(c[3] for c in cells)
    m_all = min([c[7] for c in cells if c[2]] or [10])
    s_all = min([c[8] for c in cells if c[3]] or [10])
    for i, (cell, box, main, sub, main_r, sub_r, two_lines, _, _) in enumerate(cells):
        if i:
            p.drawLine(QPointF(cell.left(), cell.top()), QPointF(cell.left(), cell.bottom()))
        if not any_sub:
            main_r = box  # بدون متن کوچک، متن اصلی وسط خانه
        f = QFont("Arial", 1)
        f.setBold(True)
        f.setPixelSize(max(4, m_all))
        p.setFont(f)
        if two_lines:
            opt = QTextOption(Qt.AlignCenter)
            opt.setWrapMode(QTextOption.WordWrap)
            p.drawText(main_r, main, opt)
        else:
            p.drawText(main_r, Qt.AlignCenter, main)
        if sub:
            f.setPixelSize(max(4, s_all))
            p.setFont(f)
            p.drawText(sub_r, Qt.AlignHCenter | Qt.AlignTop, sub)
    p.restore()


def paint_label_sheet(printer, items, w_mm, h_mm, with_qr, show_code, sheet=True):
    """items: [(drawer-dict, code)] — روی A4 با خط برش، یا هر برچسب یک صفحه (چاپگر لیبل)."""
    p = QPainter(printer)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.TextAntialiasing)
    dpm = printer.resolution() / 25.4
    page = printer.pageLayout().fullRectPixels(printer.resolution())
    if sheet:
        margin = 8
        cols = max(1, int((page.width() / dpm - margin * 2) // w_mm))
        rows = max(1, int((page.height() / dpm - margin * 2) // h_mm))
        x0 = (page.width() / dpm - cols * w_mm) / 2
        y0 = (page.height() / dpm - rows * h_mm) / 2
        per = cols * rows
    for i, (drawer, code) in enumerate(items):
        if sheet:
            if i and i % per == 0:
                printer.newPage()
            k = i % per
            r = QRectF((x0 + (k % cols) * w_mm) * dpm, (y0 + (k // cols) * h_mm) * dpm, w_mm * dpm, h_mm * dpm)
            p.save()
            p.setPen(QPen(QColor("#cfcfcf"), 1, Qt.DashLine))
            p.drawRect(r)
            p.restore()
        else:
            if i:
                printer.newPage()
            k_ = min(1.0, page.width() / (w_mm * dpm), page.height() / (h_mm * dpm))
            r = QRectF(0, 0, w_mm * dpm * k_, h_mm * dpm * k_)
        draw_drawer_label(p, r, drawer, code, with_qr, show_code)
    p.end()


def make_label_printer(w_mm, h_mm, sheet=True, pdf_path=None):
    pr = QPrinter(QPrinter.HighResolution)
    if pdf_path:
        pr.setOutputFormat(QPrinter.PdfFormat)
        pr.setOutputFileName(pdf_path)
    if sheet:
        pr.setPageSize(QPageSize(QPageSize.A4))
        pr.setPageMargins(QMarginsF(0, 0, 0, 0), QPageLayout.Millimeter)
    else:
        size = QPageSize(QSizeF(min(w_mm, h_mm), max(w_mm, h_mm)), QPageSize.Millimeter, "label", QPageSize.ExactMatch)
        pr.setPageLayout(QPageLayout(size, QPageLayout.Landscape if w_mm > h_mm else QPageLayout.Portrait,
                                     QMarginsF(0, 0, 0, 0), QPageLayout.Millimeter))
        pr.setFullPage(True)
    return pr


class LabelPreview(QWidget):
    """پیش‌نمایش زنده‌ی برچسب با نسبت واقعی."""

    def __init__(self, w_mm=49, h_mm=24):
        super().__init__()
        self.w_mm, self.h_mm = w_mm, h_mm
        self.drawer, self.code, self.qr, self.show_code = None, "", False, True
        self.setMinimumHeight(190)

    def set(self, drawer, code, qr, show_code, w_mm, h_mm):
        self.drawer, self.code, self.qr, self.show_code = drawer, code, qr, show_code
        self.w_mm, self.h_mm = w_mm, h_mm
        self.update()

    def paintEvent(self, e):
        from ui.theme import Theme
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor(Theme.c["surface2"]))
        avail_w, avail_h = self.width() - 40, self.height() - 40
        scale = min(avail_w / self.w_mm, avail_h / self.h_mm)
        w, h = self.w_mm * scale, self.h_mm * scale
        r = QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 40))
        p.drawRoundedRect(r.translated(0, 3), 3, 3)
        p.setBrush(QColor("white"))
        p.drawRect(r)
        if self.drawer:
            draw_drawer_label(p, r, self.drawer, self.code, self.qr, self.show_code)
        p.setPen(QColor(Theme.c["faint"]))
        f = QFont(self.font())
        f.setPointSizeF(8)
        p.setFont(f)
        p.drawText(QRectF(0, r.bottom() + 4, self.width(), 18), Qt.AlignCenter, f"{self.w_mm:g} × {self.h_mm:g} mm")


class ShelfLabelDialog(BaseDialog):
    """ساخت لیبل قفسه از ۱ تا ۳ قطعه، با پیش‌نمایش زنده و صف چاپ."""

    def __init__(self, parent, db, parts=None, drawer=None, drawer_code=""):
        super().__init__(parent, "لیبل قفسه", "۱ تا ۳ قطعه انتخاب کنید؛ لیبل خودکار ساخته می‌شود و همه‌ی متن‌ها "
                         "قابل ویرایش است. چند لیبل را به صف اضافه کنید و یکجا چاپ کنید.", 980)
        from PySide6.QtWidgets import QCompleter, QGridLayout, QLineEdit, QListWidget, QVBoxLayout, QWidget
        from ui.dialogs import combo, line, spin
        from ui.widgets import Card, Segment
        self.db = db
        self.queue = []
        pn_list = db.part_numbers()

        main = QHBoxLayout()
        main.setSpacing(16)
        # ستون تنظیمات
        form = QVBoxLayout()
        form.setSpacing(10)
        top = QHBoxLayout()
        self.title = combo(sorted(set(db.drawer_titles()) | {t for _, t in TITLE_KEYWORDS}), "", "سرتیتر", ltr=True)
        top.addLayout(self.field("سرتیتر", self.title), 1)
        self.comps = Segment([("1", "۱ خانه"), ("2", "۲ خانه"), ("3", "۳ خانه")], "1")
        self.comps.changed.connect(self.on_comps)
        top.addLayout(self.field("تعداد خانه", self.comps))
        form.addLayout(top)

        slots_box = QWidget()
        slots_box.setLayoutDirection(Qt.LeftToRight)  # خانه‌ی ۱ سمت چپ لیبل
        slots = QHBoxLayout(slots_box)
        slots.setContentsMargins(0, 0, 0, 0)
        slots.setSpacing(8)
        self.slot_cards, self.pn, self.main_t, self.sub_t = [], [], [], []
        for i in range(3):
            c = Card(padding=10)
            c.setLayoutDirection(Qt.RightToLeft)
            c.lay.setSpacing(6)
            c.lay.addWidget(label(f"خانه‌ی {i + 1}", "StatTitle"))
            pn = line("", "قطعه (پارت نامبر)", ltr=True)
            comp = QCompleter(pn_list, pn)
            comp.setCaseSensitivity(Qt.CaseInsensitive)
            comp.setFilterMode(Qt.MatchContains)
            pn.setCompleter(comp)
            comp.activated[str].connect(lambda t, i=i: self.fill_slot(i, t))
            pn.editingFinished.connect(lambda i=i: self.fill_slot(i, self.pn[i].text()))
            m = line("", "متن اصلی", ltr=True)
            s_ = line("", "متن کوچک", ltr=True)
            for w in (m, s_):
                w.textChanged.connect(self.update_preview)
            c.lay.addWidget(pn)
            c.lay.addWidget(m)
            c.lay.addWidget(s_)
            slots.addWidget(c, 1)
            self.slot_cards.append(c)
            self.pn.append(pn)
            self.main_t.append(m)
            self.sub_t.append(s_)
        form.addWidget(slots_box)

        opts = QHBoxLayout()
        self.code = line(drawer_code, "کد خانه (اختیاری) مثل 3-B4", ltr=True)
        self.code.textChanged.connect(self.update_preview)
        opts.addLayout(self.field("کد خانه روی لیبل", self.code), 1)
        self.size = QComboBox()
        for key, t, *_ in DRAWER_PRESETS:
            self.size.addItem(t, key)
        self.size.setCurrentIndex(max(0, self.size.findData(db.get_setting("shelf_label", "d49x24"))))
        self.size.currentIndexChanged.connect(self.update_preview)
        opts.addLayout(self.field("اندازه", self.size), 1)
        form.addLayout(opts)
        chk = QHBoxLayout()
        self.show_code = QCheckBox("نمایش کد خانه")
        self.show_code.setChecked(db.get_setting("shelf_label_code", "1") == "1")
        self.qr = QCheckBox("QR کد خانه")
        self.qr.setChecked(db.get_setting("shelf_label_qr", "0") == "1")
        self.save_drawer = QCheckBox("ثبت در همین خانه (قطعه‌ها به این خانه‌ها منتقل/اضافه شوند)")
        self.save_drawer.setChecked(bool(drawer_code))
        for w in (self.show_code, self.qr):
            w.toggled.connect(self.update_preview)
            chk.addWidget(w)
        chk.addStretch(1)
        form.addLayout(chk)
        form.addWidget(self.save_drawer)
        form.addStretch(1)
        main.addLayout(form, 3)

        # ستون پیش‌نمایش و صف
        right = QVBoxLayout()
        right.setSpacing(8)
        self.preview = LabelPreview()
        prev_card = Card()
        prev_card.lay.addWidget(self.preview)
        right.addWidget(prev_card)
        qh = QHBoxLayout()
        qh.addWidget(label("صف چاپ", "StatTitle"))
        qh.addStretch(1)
        self.copies = spin(1, 50, 1)
        self.copies.setFixedWidth(64)
        qh.addWidget(label("تعداد:", "Faint"))
        qh.addWidget(self.copies)
        add = Button("افزودن به صف", "plus", tip="Ctrl+Enter")
        add.setAutoDefault(False)
        add.clicked.connect(self.add_to_queue)
        qh.addWidget(add)
        right.addLayout(qh)
        self.qlist = QListWidget()
        self.qlist.setMinimumHeight(140)
        self.qlist.setLayoutDirection(Qt.LeftToRight)
        right.addWidget(self.qlist)
        rm = Button("حذف از صف", "trash")
        rm.setAutoDefault(False)
        rm.clicked.connect(self.remove_from_queue)
        right.addWidget(rm, 0, Qt.AlignRight)
        main.addLayout(right, 2)
        self.body.addLayout(main)

        self.mode = QComboBox()
        self.mode.addItem("برگه‌ی A4 (با خط برش)", "sheet")
        self.mode.addItem("چاپگر لیبل (هر لیبل یک صفحه)", "roll")
        self.mode.setCurrentIndex(max(0, self.mode.findData(db.get_setting("shelf_label_mode", "sheet"))))
        self.footer_left.addWidget(self.mode)
        pdf = Button("ذخیره PDF", "file")
        pdf.setAutoDefault(False)
        pdf.clicked.connect(self.save_pdf)
        self.footer_left.addWidget(pdf)
        self.add_buttons("پیش‌نمایش و چاپ", "بستن", ok_icon="printer")
        from ui.widgets import shortcut
        shortcut(self, ["Ctrl+Return", "Ctrl+Enter"], self.add_to_queue)

        if drawer:
            self.load_drawer(drawer)
        elif parts:
            self.load_parts(parts)
        self.on_comps(self.comps.value)
        self.title.currentTextChanged.connect(self.update_preview)

    # ---------------------------------------------------------------- data
    def load_parts(self, parts):
        parts = list(parts)[:3]
        self.comps.set(str(max(1, len(parts))))
        for i, p in enumerate(parts):
            self.pn[i].setText(p["part_number"])
            m, s = guess_texts(self.db, p)
            self.main_t[i].setText(m)
            self.sub_t[i].setText(s)
        if parts:
            self.title.setCurrentText(guess_title(self.db, parts[0]))
            codes = [{l["code"].rsplit("-", 1)[0] if l["code"].count("-") == 2 else l["code"]
                      for l in self.db.part_locations(p["id"])} for p in parts]
            common = set.intersection(*codes) if codes and all(codes) else set()
            if common and not self.code.text():
                self.code.setText(sorted(common)[0])

    def load_drawer(self, d):
        self.title.setCurrentText(d.get("title") or "")
        self.comps.set(str(d.get("comps") or 1))
        parts = {}
        if d.get("id"):
            for pp in self.db.drawer_parts(d["id"]):
                parts.setdefault(pp["comp"], []).append(pp["part_number"])
        for i in range(3):
            self.main_t[i].setText(d["labels"][i]["main"])
            self.sub_t[i].setText(d["labels"][i]["sub"])
            self.pn[i].setText(", ".join(parts.get(i + 1, [])))

    def fill_slot(self, i, pn):
        p = self.db.find_part((pn or "").split(",")[0].strip())
        if not p:
            return
        if not self.main_t[i].text().strip() or self.main_t[i].property("auto"):
            m, s = guess_texts(self.db, p)
            self.main_t[i].setText(m)
            self.sub_t[i].setText(s)
            self.main_t[i].setProperty("auto", True)
        if not self.title.currentText().strip():
            self.title.setCurrentText(guess_title(self.db, p))

    def on_comps(self, v):
        n = int(v)
        for i, c in enumerate(self.slot_cards):
            c.setVisible(i < n)
        self.update_preview()

    def spec(self):
        key = self.size.currentData()
        return next(p for p in DRAWER_PRESETS if p[0] == key)

    def current(self):
        n = int(self.comps.value)
        labels = [{"main": self.main_t[i].text().strip(), "sub": self.sub_t[i].text().strip()} for i in range(3)]
        return {"title": self.title.currentText().strip(), "comps": n, "labels": labels}, self.code.text().strip()

    def update_preview(self, *_):
        d, code = self.current()
        _, _, w, h = self.spec()
        self.preview.set(d, code, self.qr.isChecked(), self.show_code.isChecked(), w, h)

    # ---------------------------------------------------------------- queue
    def add_to_queue(self):
        d, code = self.current()
        if not any(l["main"] for l in d["labels"][:d["comps"]]) and not d["title"]:
            toast(self, "لیبل خالی است")
            return
        self.persist_drawer()
        for _ in range(self.copies.value()):
            self.queue.append((d, code))
        text = f"{d['title']}  |  " + "  |  ".join(" ".join(x for x in (l["main"], l["sub"]) if x)
                                                  for l in d["labels"][:d["comps"]])
        self.qlist.addItem((f"{code}   " if code else "") + text + (f"   ×{self.copies.value()}" if self.copies.value() > 1 else ""))
        self.qlist.item(self.qlist.count() - 1).setData(Qt.UserRole, self.copies.value())
        toast(self, f"به صف اضافه شد — {len(self.queue)} لیبل در صف")
        # آماده برای لیبل بعدی
        for w in self.pn + self.main_t + self.sub_t:
            w.clear()
        self.title.setCurrentText("")
        self.copies.setValue(1)
        self.save_drawer.setChecked(False)
        self.code.clear()
        self.pn[0].setFocus()

    def remove_from_queue(self):
        row = self.qlist.currentRow()
        if row < 0:
            return
        start = sum(self.qlist.item(i).data(Qt.UserRole) for i in range(row))
        n = self.qlist.item(row).data(Qt.UserRole)
        del self.queue[start:start + n]
        self.qlist.takeItem(row)

    def persist_drawer(self):
        """اگر تیک «ثبت در همین خانه» خورده، برچسب و قطعه‌ها در کشو ذخیره شوند."""
        if not self.save_drawer.isChecked():
            return
        d, code = self.current()
        pc = self.db.parse_code(code)
        if not pc:
            toast(self, "کد خانه نامعتبر است؛ فقط چاپ می‌شود")
            return
        cab = self.db.q1("SELECT * FROM cabinets WHERE number=?", (pc[0],))
        if not cab or not (1 <= pc[1] <= cab["rows"]) or not (0 <= pc[2] < cab["cols"]):
            toast(self, f"قفسه‌ی {pc[0]} یا این خانه تعریف نشده؛ فقط چاپ می‌شود")
            return
        cur = self.db.drawer_at(cab["id"], pc[1], pc[2])   # خانه‌ی ادغام‌شده → خانه‌ی اصلی
        row, col = (cur["row"], cur["col"]) if cur else (pc[1], pc[2])
        did = self.db.save_drawer(cab["id"], row, col, d["title"], d["comps"], d["labels"])
        for i in range(d["comps"]):
            ids = []
            for pn in [t.strip() for t in self.pn[i].text().split(",") if t.strip()]:
                p = self.db.find_part(pn)
                if p:
                    ids.append(p["id"])
            if ids:
                self.db.set_comp_parts(did, i + 1, ids)
        self.saved_drawer = True

    def items_to_print(self):
        if self.queue:
            return self.queue
        d, code = self.current()
        self.persist_drawer()
        return [(d, code)] * self.copies.value()

    def remember(self):
        self.db.set_setting("shelf_label", self.size.currentData())
        self.db.set_setting("shelf_label_code", "1" if self.show_code.isChecked() else "0")
        self.db.set_setting("shelf_label_qr", "1" if self.qr.isChecked() else "0")
        self.db.set_setting("shelf_label_mode", self.mode.currentData())

    def _paint(self, printer, items):
        _, _, w, h = self.spec()
        paint_label_sheet(printer, items, w, h, self.qr.isChecked(), self.show_code.isChecked(),
                          self.mode.currentData() == "sheet")

    def on_ok(self):
        items = self.items_to_print()
        self.remember()
        _, _, w, h = self.spec()
        self._printer = pr = make_label_printer(w, h, self.mode.currentData() == "sheet")
        dlg = QPrintPreviewDialog(pr, self)
        dlg.setWindowTitle(f"پیش‌نمایش — {len(items)} لیبل")
        dlg.resize(900, 760)
        dlg.paintRequested.connect(lambda printer: self._paint(printer, items))
        if dlg.exec():
            self.accept()

    def save_pdf(self):
        path, _ = QFileDialog.getSaveFileName(self, "ذخیره PDF", "shelf_labels.pdf", "PDF (*.pdf)")
        if not path:
            return
        items = self.items_to_print()
        self.remember()
        _, _, w, h = self.spec()
        self._paint(make_label_printer(w, h, self.mode.currentData() == "sheet", path), items)
        toast(self, f"PDF با {len(items)} لیبل ذخیره شد")


class DrawerLabelDialog(BaseDialog):
    """چاپ یکجای لیبل همه‌ی کشوهای یک کابینت."""

    def __init__(self, parent, db, drawers, scope_text):
        super().__init__(parent, "چاپ لیبل خانه‌ها", f"{scope_text} — {len(drawers)} لیبل", 460)
        self.db, self.drawers = db, drawers
        self.preset = QComboBox()
        for key, title, *_ in DRAWER_PRESETS:
            self.preset.addItem(title, key)
        self.preset.setCurrentIndex(max(0, self.preset.findData(db.get_setting("shelf_label", "d49x24"))))
        self.show_code = QCheckBox("نمایش کد خانه")
        self.show_code.setChecked(db.get_setting("shelf_label_code", "1") == "1")
        self.qr = QCheckBox("QR کد خانه")
        self.qr.setChecked(db.get_setting("shelf_label_qr", "0") == "1")
        self.body.addLayout(self.field("اندازه‌ی لیبل", self.preset))
        row = QHBoxLayout()
        row.addWidget(self.show_code)
        row.addWidget(self.qr)
        row.addStretch(1)
        self.body.addLayout(row)
        self.mode = QComboBox()
        self.mode.addItem("برگه‌ی A4 (با خط برش)", "sheet")
        self.mode.addItem("چاپگر لیبل (هر لیبل یک صفحه)", "roll")
        self.mode.setCurrentIndex(max(0, self.mode.findData(db.get_setting("shelf_label_mode", "sheet"))))
        self.body.addLayout(self.field("نوع چاپ", self.mode))
        pdf = Button("ذخیره PDF", "file")
        pdf.setAutoDefault(False)
        pdf.clicked.connect(self.save_pdf)
        self.footer_left.addWidget(pdf)
        self.add_buttons("پیش‌نمایش و چاپ", "انصراف", ok_icon="printer")

    def spec(self):
        key = self.preset.currentData()
        self.db.set_setting("shelf_label", key)
        self.db.set_setting("shelf_label_code", "1" if self.show_code.isChecked() else "0")
        self.db.set_setting("shelf_label_qr", "1" if self.qr.isChecked() else "0")
        self.db.set_setting("shelf_label_mode", self.mode.currentData())
        return next(p for p in DRAWER_PRESETS if p[0] == key)

    def paint(self, printer):
        _, _, w, h = self.spec()
        paint_label_sheet(printer, self.drawers, w, h, self.qr.isChecked(), self.show_code.isChecked(),
                          self.mode.currentData() == "sheet")

    def make_printer(self, pdf_path=None):
        _, _, w, h = self.spec()
        return make_label_printer(w, h, self.mode.currentData() == "sheet", pdf_path)

    def on_ok(self):
        # چاپگر باید تا بسته شدن پیش‌نمایش زنده بماند (وگرنه پایتون پاکش می‌کند و برنامه کرش می‌کند)
        self._printer = self.make_printer()
        dlg = QPrintPreviewDialog(self._printer, self)
        dlg.setWindowTitle("پیش‌نمایش لیبل خانه‌ها")
        dlg.resize(900, 760)
        dlg.paintRequested.connect(self.paint)
        if dlg.exec():
            self.accept()

    def save_pdf(self):
        path, _ = QFileDialog.getSaveFileName(self, "ذخیره PDF", "drawer_labels.pdf", "PDF (*.pdf)")
        if path:
            self.paint(self.make_printer(path))
            toast(self, "فایل PDF ذخیره شد")
