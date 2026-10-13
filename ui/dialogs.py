"""دیالوگ‌ها: قطعه، ورود/خروج، سفارش‌های جدید، ایمپورت، کپچا، میانبرها و…"""
import base64
import webbrowser

from PySide6.QtCore import QEvent, QStringListModel, Qt, QThread, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QCheckBox, QComboBox, QCompleter, QDialog, QDoubleSpinBox, QGridLayout, QHBoxLayout,
                               QLabel, QLineEdit, QListWidget, QListWidgetItem, QPlainTextEdit, QSpinBox,
                               QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget, QAbstractItemView, QHeaderView)

import appinfo
import lion_client as lion
from db import SUPPLIER_LION
from .theme import Theme
from .widgets import tokens_match, BaseDialog, Button, Divider, fmt_int, fmt_money, label, toast


# ------------------------------------------------------------------ inputs
def line(text="", placeholder="", ltr=False):
    e = QLineEdit(text or "")
    e.setPlaceholderText(placeholder)
    if ltr:
        e.setLayoutDirection(Qt.LeftToRight)
        e.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    return e


def combo(values, current="", placeholder="", ltr=False):
    c = QComboBox()
    c.setEditable(True)
    c.setInsertPolicy(QComboBox.NoInsert)
    c.addItems([""] + list(values))
    c.setCurrentText(current or "")
    c.lineEdit().setPlaceholderText(placeholder)
    comp = QCompleter(list(values), c)
    comp.setCaseSensitivity(Qt.CaseInsensitive)
    comp.setFilterMode(Qt.MatchContains)
    c.setCompleter(comp)
    if ltr:
        c.setLayoutDirection(Qt.LeftToRight)
    return c


def spin(value=0, maximum=10_000_000, minimum=0):
    s = QSpinBox()
    s.setRange(minimum, maximum)
    s.setValue(int(value or 0))
    s.setGroupSeparatorShown(True)
    s.setButtonSymbols(QSpinBox.NoButtons)
    s.setAlignment(Qt.AlignCenter)
    return s


def money_spin(value=0):
    s = QDoubleSpinBox()
    s.setRange(0, 1e13)
    s.setDecimals(0)
    s.setValue(float(value or 0))
    s.setGroupSeparatorShown(True)
    s.setButtonSymbols(QDoubleSpinBox.NoButtons)
    s.setAlignment(Qt.AlignCenter)
    s.setSuffix(" ریال")
    return s


class CategoryPicker(QComboBox):
    """انتخاب دسته با جستجو در مسیر کامل (مثلاً «ceramic»)."""

    def __init__(self, db, current_id=None):
        super().__init__()
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.NoInsert)
        self.setMaxVisibleItems(14)
        self.setLayoutDirection(Qt.LeftToRight)
        self.lineEdit().setPlaceholderText("جستجوی دسته، مثلاً Ceramic")
        self.reload(db, current_id)

    def reload(self, db, current_id=None):
        cats = sorted(db.categories().values(), key=lambda c: c["path"].lower())
        self.clear()
        self.addItem("", None)
        for c in cats:
            self.addItem(c["path"], c["id"])
        comp = QCompleter([c["path"] for c in cats], self)
        comp.setCaseSensitivity(Qt.CaseInsensitive)
        comp.setFilterMode(Qt.MatchContains)
        comp.setMaxVisibleItems(12)
        self.setCompleter(comp)
        self.set_id(current_id)

    def set_id(self, cat_id):
        i = self.findData(cat_id) if cat_id else 0
        self.setCurrentIndex(max(i, 0))

    def value(self):
        text = self.currentText().strip()
        if not text:
            return None
        i = self.findText(text)
        return self.itemData(i) if i >= 0 else self.currentData()


class MultiInput(QLineEdit):
    """ورودی چندمقداری با کاما و تکمیل خودکار برای آخرین مقدار.
    words: لیست رشته‌ها؛ اگر «  —  » داشته باشند، فقط بخش قبل از آن درج می‌شود."""
    SEP = "  —  "

    def __init__(self, words, placeholder="", parent=None):
        super().__init__(parent)
        self.setPlaceholderText(placeholder)
        self.setLayoutDirection(Qt.LeftToRight)
        self.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.comp = QCompleter(list(words), self)
        self.comp.setCaseSensitivity(Qt.CaseInsensitive)
        self.comp.setFilterMode(Qt.MatchContains)
        self.comp.setMaxVisibleItems(12)
        self.comp.setWidget(self)
        self.comp.activated[str].connect(self.insert_completion)
        self.textEdited.connect(self.on_edit)

    def last_token(self):
        return self.text()[:self.cursorPosition()].split(",")[-1].strip()

    def on_edit(self, _):
        prefix = self.last_token()
        if len(prefix) < 1:
            self.comp.popup().hide()
            return
        self.comp.setCompletionPrefix(prefix)
        if self.comp.completionCount():
            r = self.cursorRect()
            r.setWidth(max(320, self.width() // 2))
            self.comp.complete(r)
        else:
            self.comp.popup().hide()

    def insert_completion(self, text):
        text = text.split(self.SEP)[0].strip()
        before = self.text()[:self.cursorPosition()]
        after = self.text()[self.cursorPosition():]
        head = before.rsplit(",", 1)[0] + ", " if "," in before else ""
        self.setText(head + text + ", " + after.lstrip(", "))
        self.setCursorPosition(len(head + text) + 2)

    def tokens(self):
        out = []
        for t in self.text().split(","):
            t = t.strip()
            if t and t.lower() not in [x.lower() for x in out]:
                out.append(t)
        return out


class PartSearchInput(QLineEdit):
    """فیلد پارت نامبر با جستجو مثل صفحه‌ی انبار: پارت نامبر، توضیحات، پکیج، سازنده، دسته و کد قفسه.
    کلمه‌ها با فاصله جدا می‌شوند و همه باید پیدا شوند؛ با انتخاب، فقط پارت نامبر درج می‌شود."""
    SEP = "   —   "

    def __init__(self, db, text="", placeholder="پارت نامبر یا بخشی از توضیحات…", parent=None):
        super().__init__(text or "", parent)
        from PySide6.QtCore import QStringListModel
        self.setPlaceholderText(placeholder)
        self.setLayoutDirection(Qt.LeftToRight)
        self.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        cats, locs = db.categories(), db.locations_map()
        self.items = []
        for p in db.list_parts():
            desc = (p["description"] or "").split(" | ")[0]
            cat = cats.get(p["category_id"])
            hay = " ".join(str(x or "") for x in (p["part_number"], p["description"], p["package"], p["manufacturer"],
                                                  cat["path"] if cat else "", " ".join(locs.get(p["id"], []))))
            stock = "؟" if p["needs_count"] else str(p["quantity"])
            self.items.append((p["part_number"], f"{p['part_number']}{self.SEP}{desc}   [{stock}]", self._norm(hay)))
        self.model = QStringListModel(self)
        self.comp = QCompleter(self.model, self)
        self.comp.setCompletionMode(QCompleter.UnfilteredPopupCompletion)
        self.comp.setMaxVisibleItems(12)
        self.comp.setWidget(self)
        self.comp.activated[str].connect(self.choose)
        self.textEdited.connect(self.on_edit)

    @staticmethod
    def _norm(t):
        return (t or "").lower().replace("ي", "ی").replace("ك", "ک").replace("µ", "u").replace("μ", "u")

    def on_edit(self, text):
        tokens = self._norm(text).split()
        if not tokens:
            self.comp.popup().hide()
            return
        first = tokens[0]
        hits = []
        for pn, disp, hay in self.items:
            if tokens_match(tokens, hay):
                pl = pn.lower()
                rank = 0 if pl.startswith(first) else 1 if first in pl else 2
                hits.append((rank, len(pn), disp))
        hits.sort()
        self.model.setStringList([h[2] for h in hits[:60]])
        if hits:
            r = self.rect()
            r.setWidth(max(self.width(), 560))
            self.comp.complete(r)
        else:
            self.comp.popup().hide()

    def choose(self, display):
        self.setText(display.split(self.SEP)[0].strip())
        self.comp.popup().hide()


class EnterToSave(QDialog):
    """Enter در هر فیلد = ذخیره؛ Shift+Enter در متن چندخطی = خط جدید."""

    def install_enter(self):
        for w in self.findChildren(QWidget):
            if isinstance(w, (QLineEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox, QComboBox)):
                w.installEventFilter(self)

    def eventFilter(self, obj, e):
        if e.type() == QEvent.KeyPress and e.key() in (Qt.Key_Return, Qt.Key_Enter):
            if isinstance(obj, QPlainTextEdit) and e.modifiers() & Qt.ShiftModifier:
                return False
            popup = obj.completer().popup() if hasattr(obj, "completer") and obj.completer() else None
            if popup is not None and popup.isVisible():
                return False
            if isinstance(obj, (MultiInput, PartSearchInput)) and obj.comp.popup().isVisible():
                return False
            if isinstance(obj, QComboBox) and obj.view().isVisible():
                return False
            self.on_ok()
            return True
        return False


# ------------------------------------------------------------------ lookup worker
class LookupWorker(QThread):
    done = Signal(object, str)

    def __init__(self, part_number, url=None):
        super().__init__()
        self.pn, self.url = part_number, url

    def run(self):
        try:
            exact = True
            url = self.url
            if not url:
                url, exact = lion.search_product(self.pn, allow_prefix=True)
            if not url:
                self.done.emit(None, "این پارت نامبر در سایت لیون پیدا نشد")
                return
            info = lion.fetch_product_info(url)
            info["_exact"] = exact
            info.get("specs", {}).pop("Part Number", None)
            self.done.emit(info, "")
        except Exception as e:  # noqa: BLE001
            self.done.emit(None, f"خطا در ارتباط با سایت: {e}")


# ------------------------------------------------------------------ part dialog
class PartDialog(BaseDialog, EnterToSave):
    def __init__(self, parent, db, part=None):
        title = "ویرایش قطعه" if part else "قطعه‌ی جدید"
        super().__init__(parent, title, "Enter = ذخیره   •   Esc = انصراف   •   Shift+Enter = خط جدید در توضیحات", 700)
        self.db, self.part = db, part
        p = dict(part) if part else {}
        self.worker = None

        self.pn = line(p.get("part_number"), "مثلاً STM32F103C8T6", ltr=True)
        self.lookup_btn = Button("دریافت از لیون", "sparkle", tip="پر کردن خودکار توضیحات، دسته، سازنده، پکیج و دیتاشیت از سایت لیون")
        self.lookup_btn.setAutoDefault(False)
        self.lookup_btn.clicked.connect(self.lookup)
        self.desc = QPlainTextEdit(p.get("description") or "")
        self.desc.setPlaceholderText("توضیحات قطعه")
        self.desc.setFixedHeight(74)
        self.desc.setTabChangesFocus(True)
        self.cat = CategoryPicker(db, p.get("category_id"))
        self.new_cat_btn = Button("", "plus", "Icon", tip="دسته‌ی جدید")
        self.new_cat_btn.setAutoDefault(False)
        self.new_cat_btn.clicked.connect(self.add_category)
        self.manu = combo(db.distinct("manufacturer"), p.get("manufacturer"), "سازنده", ltr=True)
        self.pkg = combo(db.distinct("package"), p.get("package"), "مثلاً SOT-23", ltr=True)
        codes = [f"{c}{MultiInput.SEP}{t}" if t else c for c, t in db.all_location_codes()]
        self.loc = MultiInput(codes + db.distinct("location"), "کد خانه مثل 3-B4-1 (چندتا با کاما) یا متن آزاد")
        cur_codes = [l["code"] for l in db.part_locations(part["id"])] if part else []
        self.loc.setText(", ".join(cur_codes + ([p["location"]] if p.get("location") else [])))
        self.qty = spin(p.get("quantity", 0))
        self.minq = spin(p.get("min_quantity", 0))
        self.price = money_spin(p.get("unit_price", 0))
        self.link = line(p.get("purchase_link"), "لینک صفحه‌ی خرید یا نام فروشگاه", ltr=True)
        self.lion_btn = Button("لیون", tip="فروشنده: لیون الکترونیک")
        self.lion_btn.setAutoDefault(False)
        self.lion_btn.clicked.connect(lambda: self.link.setText(self.link.text() if "lionelectronic" in self.link.text() else SUPPLIER_LION))
        self.open_btn = Button("", "external", "Icon", tip="باز کردن لینک")
        self.open_btn.setAutoDefault(False)
        self.open_btn.clicked.connect(lambda: self._open(self.link.text()))
        self.ds = line(p.get("datasheet"), "لینک دیتاشیت", ltr=True)

        g = QGridLayout()
        g.setHorizontalSpacing(14)
        g.setVerticalSpacing(12)
        pn_row = QHBoxLayout()
        pn_row.addWidget(self.pn, 1)
        pn_row.addWidget(self.lookup_btn)
        g.addLayout(self.field("پارت نامبر *", pn_row), 0, 0, 1, 2)
        g.addLayout(self.field("توضیحات", self.desc), 1, 0, 1, 2)
        cat_row = QHBoxLayout()
        cat_row.setSpacing(6)
        cat_row.addWidget(self.cat, 1)
        cat_row.addWidget(self.new_cat_btn)
        g.addLayout(self.field("دسته‌بندی", cat_row), 2, 0, 1, 2)
        g.addLayout(self.field("سازنده", self.manu), 3, 0)
        g.addLayout(self.field("پکیج", self.pkg), 3, 1)
        g.addLayout(self.field("محل نگهداری", self.loc), 4, 0)
        nums = QHBoxLayout()
        nums.setSpacing(10)
        if not part:
            nums.addLayout(self.field("موجودی اولیه", self.qty))
        nums.addLayout(self.field("حداقل موجودی", self.minq))
        g.addLayout(nums, 4, 1)
        g.addLayout(self.field("قیمت واحد", self.price), 5, 0)
        link_row = QHBoxLayout()
        link_row.setSpacing(6)
        link_row.addWidget(self.link, 1)
        link_row.addWidget(self.lion_btn)
        link_row.addWidget(self.open_btn)
        g.addLayout(self.field("لینک خرید", link_row), 5, 1)
        g.addLayout(self.field("دیتاشیت", self.ds), 6, 0, 1, 2)
        g.setColumnStretch(0, 1)
        g.setColumnStretch(1, 1)
        self.body.addLayout(g)
        self.err = label("", "PillDanger")
        self.err.hide()
        self.footer_left.addWidget(self.err)
        self.add_buttons("ذخیره", "انصراف", ok_icon="check")
        self.lookup_done = False
        lion_on = appinfo.lion_enabled(db)
        self.lookup_btn.setVisible(lion_on)
        self.lion_btn.setVisible(lion_on)
        self.install_enter()
        for e in (self.link, self.ds):
            e.setCursorPosition(0)
        self.pn.setFocus()
        self.result_data = None

    @staticmethod
    def _open(url):
        if url.startswith("http"):
            webbrowser.open(url)

    def add_category(self):
        d = CategoryEditDialog(self, self.db, parent_id=self.cat.value())
        if d.exec():
            self.cat.reload(self.db, d.saved_id)

    def lookup(self):
        pn = self.pn.text().strip()
        url = self.link.text().strip() if "lionelectronic.ir/products/" in self.link.text() else None
        if not pn and not url:
            self.show_err("اول پارت نامبر را بنویسید")
            return
        self.lookup_btn.setEnabled(False)
        self.lookup_btn.setText("در حال دریافت…")
        self.worker = LookupWorker(pn, url)
        self.worker.done.connect(self.on_lookup)
        self.worker.start()

    def on_lookup(self, info, err):
        self.lookup_btn.setEnabled(True)
        self.lookup_btn.setText("دریافت از لیون")
        if err or not info:
            self.show_err(err or "چیزی پیدا نشد")
            return
        self.err.hide()
        if info.get("categories"):
            self.db.upsert_categories(info["categories"])
            self.cat.reload(self.db, self.cat.value() or info.get("category_id"))
        if not self.desc.toPlainText().strip() and info.get("description"):
            self.desc.setPlainText(info["description"])
        for w, key in ((self.manu, "manufacturer"), (self.pkg, "package")):
            if not w.currentText().strip() and info.get(key):
                w.setCurrentText(info[key])
        if info.get("datasheet"):
            self.ds.setText(info["datasheet"])
        if info.get("price"):
            self.price.setValue(info["price"])
        self.lookup_done = True
        if not self.link.text().startswith("http") and info.get("url"):
            self.link.setText(info["url"])
        if info.get("part_number") and not self.pn.text().strip():
            self.pn.setText(info["part_number"])
        if not info.get("_exact", True) and info.get("part_number"):
            self.show_err(f"دقیقاً پیدا نشد؛ نزدیک‌ترین محصول لیون: {info['part_number']} — بررسی کنید")
        toast(self, "اطلاعات از سایت لیون دریافت شد" +
              (f" — قیمت ۱ عدد: {int(info['price']):,} ریال" if info.get("price") else " (قیمت در سایت نبود)"))

    def show_err(self, text):
        self.err.setText(text)
        self.err.show()

    def on_ok(self):
        pn = self.pn.text().strip()
        if not pn:
            self.show_err("پارت نامبر الزامی است")
            self.pn.setFocus()
            return
        other = self.db.find_part(pn)
        self.merge_into = None
        self.goto_existing = None
        if other and (not self.part or other["id"] != self.part["id"]):
            from .widgets import confirm
            locs = "، ".join(l["code"] for l in self.db.part_locations(other["id"])) or "بدون محل"
            qty = "شمارش نشده" if other["needs_count"] else f"{other['quantity']} عدد"
            if self.part:
                msg = (f"قطعه‌ی دیگری با پارت نامبر «{other['part_number']}» از قبل هست ({qty}، {locs}).\n\n"
                       f"این دو قطعه یکی شوند؟ موجودی‌ها جمع می‌شود و محل‌ها، تاریخچه، BOM و لیست خرید "
                       f"به آن قطعه منتقل می‌شود.")
                if confirm(self, "پارت نامبر تکراری", msg, "ادغام کن"):
                    self.merge_into = other["id"]
                else:
                    self.show_err("این پارت نامبر قبلاً ثبت شده")
                    return
            else:
                if confirm(self, "پارت نامبر تکراری", f"«{other['part_number']}» از قبل در انبار هست ({qty}، {locs}).\n"
                           "به همان قطعه بروید؟", "رفتن به قطعه"):
                    self.goto_existing = other["id"]
                    self.result_data = None
                    self.accept()
                    return
                self.show_err("این پارت نامبر قبلاً ثبت شده")
                return
        self.result_data = {
            "part_number": pn, "description": self.desc.toPlainText().strip(), "category_id": self.cat.value(),
            "manufacturer": self.manu.currentText().strip(), "package": self.pkg.currentText().strip(),
            "location": ", ".join(t for t in self.loc.tokens() if not self.db.parse_code(t)),
            "location_codes": [t for t in self.loc.tokens() if self.db.parse_code(t)],
            "quantity": self.qty.value(),
            "min_quantity": self.minq.value(), "unit_price": self.price.value(),
            "purchase_link": self.link.text().strip(), "datasheet": self.ds.text().strip(),
        }
        self.accept()


# ------------------------------------------------------------------ stock dialog
class StockDialog(BaseDialog, EnterToSave):
    """mode: 1 ورود، -1 خروج، 0 شمارش (تنظیم موجودی دقیق)"""

    def __init__(self, parent, part, mode, reasons=()):
        titles = {1: "ورود به انبار", -1: "خروج از انبار", 0: "اصلاح موجودی (شمارش)"}
        super().__init__(parent, titles[mode], width=420)
        self.part, self.mode = part, mode
        head = QHBoxLayout()
        pn = label(part["part_number"], "H2")
        pn.setLayoutDirection(Qt.LeftToRight)
        head.addWidget(pn)
        head.addStretch(1)
        head.addWidget(label(f"موجودی فعلی: {fmt_int(part['quantity'])}", "Pill"))
        self.body.addLayout(head)
        if part["description"]:
            d = label(part["description"].split(" | ")[0], "Muted", wrap=True)
            self.body.addWidget(d)

        self.qty = spin(part["quantity"] if mode == 0 else 1, minimum=0 if mode == 0 else 1)
        self.qty.setStyleSheet("font-size: 20pt; font-weight: 700; min-height: 52px;")
        minus = Button("", "minus", tip="کم (↓)")
        plus = Button("", "plus", tip="زیاد (↑)")
        for b, d in ((minus, -1), (plus, 1)):
            b.setFixedSize(52, 52)
            b.setAutoDefault(False)
            b.clicked.connect(lambda _=False, d=d: self.qty.setValue(self.qty.value() + d))
        row = QHBoxLayout()
        row.addWidget(plus)
        row.addWidget(self.qty, 1)
        row.addWidget(minus)
        self.body.addLayout(self.field("تعداد جدید" if mode == 0 else "تعداد", row))
        self.preview = label("", "Muted")
        self.body.addWidget(self.preview)
        self.reason = combo(reasons, "", "مثلاً نام پروژه یا دلیل")
        self.body.addLayout(self.field("توضیح (اختیاری)", self.reason))
        self.qty.valueChanged.connect(self.update_preview)
        self.update_preview()
        self.add_buttons("ثبت", "انصراف", danger=(mode == -1), ok_icon="check")
        self.install_enter()
        self.qty.setFocus()
        self.qty.selectAll()
        self.result_data = None

    def new_qty(self):
        q, cur = self.qty.value(), self.part["quantity"]
        return q if self.mode == 0 else cur + q * self.mode

    def update_preview(self):
        n = self.new_qty()
        color = Theme.c["danger"] if n < 0 else Theme.c["text2"]
        self.preview.setText(f"موجودی بعد از ثبت:  <b style='color:{color}'>{fmt_int(n)}</b>")

    def on_ok(self):
        change = self.new_qty() - self.part["quantity"]
        if change == 0 and self.mode != 0:
            self.reject()
            return
        self.result_data = (change, self.reason.currentText().strip())
        self.accept()


# ------------------------------------------------------------------ new orders
class NewOrdersDialog(BaseDialog):
    def __init__(self, parent, orders):
        super().__init__(parent, f"{len(orders)} سفارش جدید از لیون",
                         "تیک سفارش‌هایی را بزنید که باید به موجودی انبار اضافه شوند.", 560)
        self.list = QListWidget()
        self.list.setMinimumHeight(min(380, 64 * len(orders) + 8))
        self.list.setSpacing(2)
        for o in orders:
            it = QListWidgetItem(f"سفارش {o['order_code']}   ·   {o['status'] or ''}\n"
                                 f"{o['order_date'] or ''}   ·   {o['item_count']} قلم   ·   {o['total'] or ''}")
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Unchecked)
            it.setData(Qt.UserRole, o["id"])
            it.setSizeHint(it.sizeHint().expandedTo(it.sizeHint()))
            self.list.addItem(it)
        self.list.itemClicked.connect(lambda it: None)
        self.list.itemActivated.connect(
            lambda it: it.setCheckState(Qt.Unchecked if it.checkState() == Qt.Checked else Qt.Checked))
        self.body.addWidget(self.list)
        tools = QHBoxLayout()
        a = Button("انتخاب همه")
        n = Button("هیچ‌کدام")
        for b, st in ((a, Qt.Checked), (n, Qt.Unchecked)):
            b.setAutoDefault(False)
            b.clicked.connect(lambda _=False, st=st: [self.list.item(i).setCheckState(st) for i in range(self.list.count())])
            tools.addWidget(b)
        tools.addStretch(1)
        self.ignore_rest = QCheckBox("بقیه «وارد نمی‌شود» علامت بخورند")
        tools.addWidget(self.ignore_rest)
        self.body.addLayout(tools)
        self.add_buttons("ثبت", "بعداً تصمیم می‌گیرم", ok_icon="check")
        self.result_data = None

    def on_ok(self):
        chosen, rest = [], []
        for i in range(self.list.count()):
            it = self.list.item(i)
            (chosen if it.checkState() == Qt.Checked else rest).append(it.data(Qt.UserRole))
        self.result_data = (chosen, rest if self.ignore_rest.isChecked() else [])
        self.accept()


# ------------------------------------------------------------------ captcha
class CaptchaDialog(BaseDialog, EnterToSave):
    def __init__(self, parent, img_bytes):
        super().__init__(parent, "کد امنیتی سایت لیون", "کد داخل تصویر را وارد کنید.", 360)
        pm = QPixmap()
        pm.loadFromData(img_bytes)
        img = QLabel()
        img.setPixmap(pm)
        img.setAlignment(Qt.AlignCenter)
        self.body.addWidget(img)
        self.code = line("", "", ltr=True)
        self.code.setAlignment(Qt.AlignCenter)
        self.body.addWidget(self.code)
        self.add_buttons("تأیید", "انصراف")
        self.install_enter()
        self.code.setFocus()

    def on_ok(self):
        self.accept()


# ------------------------------------------------------------------ simple forms
class FormDialog(BaseDialog, EnterToSave):
    """فرم ساده: fields=[(key, title, widget)]"""

    def __init__(self, parent, title, fields, subtitle="", ok_text="ذخیره", width=440):
        super().__init__(parent, title, subtitle, width)
        self.widgets = {}
        for key, ftitle, w in fields:
            self.widgets[key] = w
            self.body.addLayout(self.field(ftitle, w))
        self.err = label("", "PillDanger")
        self.err.hide()
        self.footer_left.addWidget(self.err)
        self.add_buttons(ok_text, "انصراف", ok_icon="check")
        self.install_enter()
        if fields:
            fields[0][2].setFocus()
        self.validator = None

    def values(self):
        out = {}
        for k, w in self.widgets.items():
            if isinstance(w, QLineEdit):
                out[k] = w.text().strip()
            elif isinstance(w, QComboBox):
                out[k] = w.currentText().strip()
            elif isinstance(w, (QSpinBox, QDoubleSpinBox)):
                out[k] = w.value()
            elif isinstance(w, QPlainTextEdit):
                out[k] = w.toPlainText().strip()
        return out

    def on_ok(self):
        if self.validator:
            msg = self.validator(self.values())
            if msg:
                self.err.setText(msg)
                self.err.show()
                return
        self.accept()


# ------------------------------------------------------------------ import mapping
class ImportDialog(BaseDialog):
    """نگاشت ستون‌های فایل اکسل/CSV به فیلدهای برنامه."""

    def __init__(self, parent, filename, headers, rows, fields, guess, options=None, title="ایمپورت از فایل"):
        super().__init__(parent, title, f"فایل: {filename}   •   {len(rows)} ردیف", 820)
        self.fields = fields
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(8)
        self.combos = {}
        for i, (key, ftitle, required) in enumerate(fields):
            c = QComboBox()
            c.addItem("— استفاده نشود —", -1)
            for j, h in enumerate(headers):
                c.addItem(h or f"ستون {j + 1}", j)
            c.setCurrentIndex(c.findData(guess.get(key, -1)))
            self.combos[key] = c
            grid.addLayout(self.field(ftitle + (" *" if required else ""), c), i // 3, i % 3)
        self.body.addLayout(grid)
        self.options = {}
        if options:
            row = QHBoxLayout()
            for key, otitle, choices in options:
                c = QComboBox()
                for v, t in choices:
                    c.addItem(t, v)
                self.options[key] = c
                row.addLayout(self.field(otitle, c))
            row.addStretch(1)
            self.body.addLayout(row)
        self.body.addWidget(label("پیش‌نمایش", "StatTitle"))
        prev = QTableWidget(min(len(rows), 8), len(headers))
        prev.setHorizontalHeaderLabels([h or f"ستون {j + 1}" for j, h in enumerate(headers)])
        prev.verticalHeader().setVisible(False)
        prev.setEditTriggers(QAbstractItemView.NoEditTriggers)
        prev.setFixedHeight(240)
        prev.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        for r, row in enumerate(rows[:8]):
            for c_, v in enumerate(row[:len(headers)]):
                prev.setItem(r, c_, QTableWidgetItem("" if v is None else str(v)))
        self.body.addWidget(prev)
        self.err = label("", "PillDanger")
        self.err.hide()
        self.footer_left.addWidget(self.err)
        self.add_buttons("ایمپورت", "انصراف", ok_icon="upload")
        self.mapping = None

    def on_ok(self):
        mapping = {k: c.currentData() for k, c in self.combos.items() if c.currentData() is not None and c.currentData() >= 0}
        for key, ftitle, required in self.fields:
            if required and key not in mapping:
                self.err.setText(f"ستون «{ftitle}» را مشخص کنید")
                self.err.show()
                return
        self.mapping = mapping
        self.option_values = {k: c.currentData() for k, c in self.options.items()}
        self.accept()


# ------------------------------------------------------------------ shortcuts help
SHORTCUTS = [
    ("عمومی", [("Ctrl+1 … Ctrl+8", "رفتن به صفحه‌ها"), ("F5", "بررسی سفارش‌های جدید لیون (اگر روشن باشد)"),
               ("Ctrl+F  یا  /", "جستجو"), ("Ctrl+Shift+L", "تغییر تم تیره/روشن"), ("F1", "همین راهنما")]),
    ("قفسه‌ها", [("← ↑ → ↓", "جابه‌جایی بین خانه‌ها"), ("Enter / دابل‌کلیک", "تعریف یا ویرایش خانه"),
                 ("Shift+فلش / Shift+کلیک / کشیدن", "انتخاب چند خانه برای ادغام (بعد راست‌کلیک)"),
                 ("Delete", "خالی کردن خانه"), ("Ctrl+L", "لیبل خانه‌ی انتخاب‌شده"), ("Ctrl+P", "لیبل همه‌ی خانه‌های قفسه"),
                 ("تایپ / اسکن QR", "پیدا کردن خانه (مثلاً 3-B4)")]),
    ("انبار قطعات", [("Enter", "قطعه‌ی جدید"), ("+", "ورود به انبار"), ("−", "خروج از انبار"),
                     ("=", "اصلاح موجودی (شمارش)"), ("F2  یا  دابل‌کلیک", "ویرایش قطعه"), ("Delete", "حذف قطعه‌های انتخاب‌شده"),
                     ("Ctrl+B", "افزودن به لیست خرید"), ("Ctrl+P", "چاپ برچسب و QR"), ("Ctrl+L", "لیبل قفسه (۱ تا ۳ قطعه)"), ("Ctrl+C", "کپی پارت نامبر"),
                     ("Ctrl+I", "ایمپورت از اکسل"), ("Ctrl+A", "انتخاب همه"), ("شروع به تایپ", "جستجوی سریع / اسکنر بارکد")]),
    ("داخل فرم‌ها", [("Enter", "ذخیره"), ("Esc", "انصراف"), ("Shift+Enter", "خط جدید در توضیحات"),
                     ("↑ / ↓", "کم و زیاد کردن تعداد")]),
]


class ShortcutsDialog(BaseDialog):
    def __init__(self, parent):
        super().__init__(parent, "میانبرهای صفحه‌کلید", width=520)
        for group, items in SHORTCUTS:
            self.body.addWidget(label(group, "H2"))
            g = QGridLayout()
            g.setVerticalSpacing(6)
            for i, (keys, desc) in enumerate(items):
                k = label(keys, "Kbd")
                k.setLayoutDirection(Qt.LeftToRight)
                g.addWidget(label(desc), i, 0)
                g.addWidget(k, i, 1, Qt.AlignLeft)
            g.setColumnStretch(0, 1)
            self.body.addLayout(g)
        self.add_buttons("بستن", None)


# ------------------------------------------------------------------ categories (بدون لیون)
class CategoryEditDialog(BaseDialog, EnterToSave):
    """ساخت/ویرایش یک دسته‌ی دستی."""

    def __init__(self, parent, db, cat=None, parent_id=None):
        super().__init__(parent, "ویرایش دسته" if cat else "دسته‌ی جدید",
                         "دسته‌ها می‌توانند زیردسته داشته باشند، مثلاً Capacitors › Ceramic.", 440)
        self.db, self.cat = db, cat
        self.name = line(cat["name"] if cat else "", "مثلاً Capacitors یا خازن", ltr=False)
        self.body.addLayout(self.field("نام", self.name))
        self.parent_pick = CategoryPicker(db, cat["parent_id"] if cat else parent_id)
        if cat:   # دسته نمی‌تواند زیرمجموعه‌ی خودش باشد
            for cid in db.category_descendants(cat["id"]):
                i = self.parent_pick.findData(cid)
                if i > 0:
                    self.parent_pick.removeItem(i)
        self.body.addLayout(self.field("زیرمجموعه‌ی (خالی = دسته‌ی اصلی)", self.parent_pick))
        self.err = label("", "PillDanger")
        self.err.hide()
        self.footer_left.addWidget(self.err)
        self.add_buttons("ذخیره", "انصراف", ok_icon="check")
        self.install_enter()
        self.name.setFocus()
        self.saved_id = None

    def on_ok(self):
        name = self.name.text().strip()
        if not name:
            self.err.setText("نام را بنویسید")
            self.err.show()
            return
        self.saved_id = self.db.save_category(name, self.parent_pick.value(), self.cat["id"] if self.cat else None)
        self.accept()


class CategoryManagerDialog(BaseDialog):
    """درخت دسته‌ها با افزودن، تغییر نام، جابه‌جایی و حذف."""

    def __init__(self, parent, db):
        super().__init__(parent, "مدیریت دسته‌بندی‌ها",
                         "دسته‌های خودتان را بسازید. با حذف یک دسته، قطعه‌هایش بدون دسته می‌مانند (حذف نمی‌شوند).", 560)
        from PySide6.QtWidgets import QTreeWidget
        self.db = db
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["دسته", "قطعه‌ها"])
        self.tree.setMinimumHeight(380)
        self.tree.setColumnWidth(0, 360)
        self.tree.itemDoubleClicked.connect(lambda *_: self.edit())
        self.body.addWidget(self.tree)
        row = QHBoxLayout()
        for text, ic, fn in (("دسته‌ی اصلی", "plus", lambda: self.add(False)), ("زیردسته", "plus", lambda: self.add(True)),
                             ("ویرایش", "edit", self.edit), ("حذف", "trash", self.delete)):
            b = Button(text, ic, "Danger" if ic == "trash" else None)
            b.setAutoDefault(False)
            b.clicked.connect(fn)
            row.addWidget(b)
        row.addStretch(1)
        self.body.addLayout(row)
        self.add_buttons("بستن", None)
        self.reload()

    def reload(self, select_id=None):
        from PySide6.QtWidgets import QTreeWidgetItem
        cats = self.db.categories()
        counts = self.db.category_part_counts()
        self.tree.clear()
        items = {}
        for c in sorted(cats.values(), key=lambda c: (c["level"], c["name"].lower())):
            total = sum(counts.get(x, 0) for x in self.db.category_descendants(c["id"]))
            it = QTreeWidgetItem([c["name"], str(total) if total else ""])
            it.setData(0, Qt.UserRole, c["id"])
            parent = items.get(c["parent_id"])
            (parent.addChild(it) if parent else self.tree.addTopLevelItem(it))
            items[c["id"]] = it
        if select_id in items:
            self.tree.setCurrentItem(items[select_id])
            self.tree.scrollToItem(items[select_id])

    def current_id(self):
        it = self.tree.currentItem()
        return it.data(0, Qt.UserRole) if it else None

    def add(self, child):
        d = CategoryEditDialog(self, self.db, parent_id=self.current_id() if child else None)
        if d.exec():
            self.reload(d.saved_id)

    def edit(self):
        cid = self.current_id()
        if cid is None:
            return
        d = CategoryEditDialog(self, self.db, cat=self.db.categories()[cid])
        if d.exec():
            self.reload(cid)

    def delete(self):
        from .widgets import confirm
        cid = self.current_id()
        if cid is None:
            return
        c = self.db.categories()[cid]
        n = len(self.db.category_descendants(cid)) - 1
        if confirm(self, "حذف دسته", f"دسته‌ی «{c['path']}»" + (f" و {n} زیردسته‌اش" if n else "") + " حذف شود؟",
                   "حذف", True):
            self.db.delete_category(cid)
            self.reload()


STARTER_CATEGORIES = [
    ("Resistors", ["SMD", "Through Hole", "Potentiometers"]),
    ("Capacitors", ["Ceramic", "Electrolytic", "Tantalum", "Film"]),
    ("Inductors", []),
    ("Diodes", ["Rectifier", "Zener", "Schottky", "TVS"]),
    ("LEDs & Displays", []),
    ("Transistors", ["BJT", "MOSFET"]),
    ("ICs", ["Microcontrollers", "Power Management", "Op-Amps", "Logic", "Interface", "Memory"]),
    ("Crystals & Oscillators", []),
    ("Connectors", []),
    ("Switches & Relays", []),
    ("Sensors", []),
    ("Modules", []),
    ("Hardware & Tools", []),
]


def create_starter_categories(db):
    for name, children in STARTER_CATEGORIES:
        pid = db.save_category(name)
        for ch in children:
            db.save_category(ch, pid)


# ------------------------------------------------------------------ first run
class WelcomeDialog(BaseDialog):
    """راه‌اندازی اولیه‌ی نسخه‌ی عمومی."""

    def __init__(self, parent, db):
        super().__init__(parent, "به «انبار الکترونیک» خوش آمدید",
                         "چند تنظیم کوتاه؛ همه‌ی این‌ها بعداً در «تنظیمات» قابل تغییر است.", 560)
        from .widgets import Segment
        self.db, self.app = db, parent
        self.name = line(db.get_setting("shop_name"), "مثلاً انبار کارگاه رضا، آزمایشگاه الکترونیک")
        self.body.addLayout(self.field("نام کارگاه / انبار", self.name, "در بالای منو و عنوان پنجره نشان داده می‌شود."))
        self.theme = Segment([("system", "مطابق ویندوز"), ("light", "روشن"), ("dark", "تیره")], db.get_setting("theme", "system"))
        self.theme.changed.connect(lambda v: self.app.set_theme(v))
        self.body.addLayout(self.field("ظاهر", self.theme))
        self.body.addWidget(Divider())
        self.starter = QCheckBox("ساخت دسته‌بندی‌های پایه (مقاومت، خازن، آی‌سی، …)")
        self.starter.setChecked(not db.categories())
        self.starter.setVisible(not db.categories())
        self.body.addWidget(self.starter)
        self.lion = QCheckBox("از «لیون الکترونیک» خرید می‌کنم — سفارش‌ها و اطلاعات قطعه‌ها از سایت خوانده شود")
        self.lion.setChecked(appinfo.lion_enabled(db))
        self.body.addWidget(self.lion)
        self.lion_box = QWidget()
        lb = QHBoxLayout(self.lion_box)
        lb.setContentsMargins(24, 0, 0, 0)
        self.user = line(db.get_setting("lion_user"), "نام کاربری لیون", ltr=True)
        self.pwd = line(db.get_setting("lion_pass"), "رمز عبور", ltr=True)
        self.pwd.setEchoMode(QLineEdit.Password)
        lb.addWidget(self.user, 1)
        lb.addWidget(self.pwd, 1)
        self.body.addWidget(self.lion_box)
        self.lion_note = label("اطلاعات ورود فقط روی همین کامپیوتر ذخیره می‌شود. بدون حساب هم می‌شود اطلاعات قطعه‌ها را "
                               "از سایت گرفت.", "Faint", wrap=True)
        self.lion_note.setContentsMargins(24, 0, 0, 0)
        self.body.addWidget(self.lion_note)
        self.lion.toggled.connect(self.on_lion)
        self.on_lion(self.lion.isChecked())
        self.body.addWidget(Divider())
        self.cab = QCheckBox("حالا اولین قفسه را تعریف کنم")
        self.cab.setChecked(not db.list_cabinets())
        self.body.addWidget(self.cab)
        self.add_buttons("شروع", None, ok_icon="check")
        self.name.setFocus()
        self.make_cabinet = False

    def on_lion(self, on):
        self.lion_box.setVisible(on)
        self.lion_note.setVisible(on)
        if not self.db.categories():
            self.starter.setChecked(not on)   # با لیون، دسته‌ها از سایت می‌آیند
        self.adjustSize()

    def on_ok(self):
        self.db.set_setting("shop_name", self.name.text().strip())
        self.db.set_setting("lion_enabled", "1" if self.lion.isChecked() else "0")
        if self.lion.isChecked():
            self.db.set_setting("lion_user", self.user.text().strip())
            self.db.set_setting("lion_pass", self.pwd.text())
        if self.starter.isVisible() and self.starter.isChecked():
            create_starter_categories(self.db)
        self.make_cabinet = self.cab.isChecked()
        self.accept()

    def reject(self):   # بستن پنجره هم یعنی «شروع» با مقادیر فعلی
        self.on_ok()
