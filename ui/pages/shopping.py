"""لیست خرید: کم‌موجودها و کمبود پروژه‌ها، آماده‌ی سفارش از لیون."""
import csv
import webbrowser
from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QCompleter, QFileDialog, QHBoxLayout, QMenu, QVBoxLayout, QWidget

import appinfo
from lion_client import CART_URL, product_id_from_link, search_url
from ..dialogs import PartSearchInput, FormDialog, line, spin
from ..theme import icon
from ..widgets import Button, Card, Col, DataTable, PageHeader, confirm, first_part, fmt_int, fmt_money, label, shortcut, toast


def domain(url):
    from urllib.parse import urlparse
    return urlparse(url).netloc.replace("www.", "") or url


def buy_url(r):
    """لینک خرید قطعه: صفحه‌ی محصول لیون یا هر لینک دیگری که برای قطعه ثبت شده."""
    link = (r.get("purchase_link") or "").strip()
    return link if link.startswith("http") else None


def buy_pill(r):
    link = (r.get("purchase_link") or "").strip()
    if r.get("lion_pid"):
        if r.get("cart_at"):
            return ("لیون · در سبد ✓", "success")
        if (r.get("lion_moq") or 1) > r["quantity"]:
            return (f"لیون · حداقل {r['lion_moq']} ↗", "warning")
        return ("لیون ↗", "accent")
    if link.startswith("http"):
        return (f"{domain(link)} ↗", "accent")
    if link:
        return (link[:22], "muted")
    return ("لینک ندارد", "muted")


class ShoppingPage(QWidget):
    def __init__(self, app):
        super().__init__()
        self.app, self.db = app, app.db
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(14)
        self.header = PageHeader("لیست خرید", "قطعه‌هایی که باید سفارش داده شوند")
        b_low = Button("افزودن کم‌موجودها", "alert", tip="قطعه‌هایی که از حداقل موجودی کمترند")
        b_low.clicked.connect(self.add_low)
        self.cart_btn = Button("افزودن به سبد خرید لیون", "cart", "Primary",
                               tip="قطعه‌های انتخاب‌شده (یا همه) که لینک لیون دارند، با همین تعداد به سبد خرید حساب شما اضافه می‌شوند")
        self.cart_btn.clicked.connect(self.add_to_lion_cart)
        b_add = Button("افزودن قطعه", "plus", tip="Enter")
        b_add.clicked.connect(self.add)
        self.header.add(b_low, b_add, self.cart_btn)
        root.addWidget(self.header)
        from PySide6.QtWidgets import QProgressBar
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.hide()
        root.addWidget(self.progress)

        bar = QHBoxLayout()
        bar.setSpacing(8)
        for text, ic, fn, tip in [("باز کردن لینک‌ها", "external", self.open_links, "Ctrl+O"),
                                  ("کپی لیست", "copy", self.copy, "Ctrl+C"),
                                  ("خروجی اکسل", "file", self.export, None)]:
            b = Button(text, ic, tip=tip)
            b.clicked.connect(fn)
            bar.addWidget(b)
        bar.addStretch(1)
        self.summary = label("", "Muted")
        bar.addWidget(self.summary)
        done = Button("خریده شد / حذف", "check", "Danger", "Delete")
        done.clicked.connect(self.remove)
        bar.addWidget(done)
        root.addLayout(bar)

        cols = [Col("part_number", "پارت نامبر", 190),
                Col("desc", "توضیحات", 260, stretch=True),
                Col("quantity", "تعداد خرید", 90, "center", "int"),
                Col("stock", "موجودی", 75, "center", "int", hide=3),
                Col("min_quantity", "حداقل", 65, "center", "int", hide=1),
                Col("est", "برآورد (ریال)", 120, "center", "money", hide=2),
                Col("lion", "لینک", 150, "center", pill=buy_pill),
                Col("source", "دلیل", 150, "center", pill=lambda r: (r["source"] or "", "accent" if "پروژه" in (r["source"] or "") else "warning" if r["source"] == "کم‌موجود" else "muted"))]
        self.table = DataTable(cols, empty_text="لیست خرید خالی است 🎉")
        self.table.activated_row.connect(self.edit)
        self.table.clicked.connect(self.on_click)
        self.table.entered.connect(self.on_hover)
        self.table.context_menu.connect(self.menu)
        c = Card()
        c.lay.setContentsMargins(1, 4, 1, 1)
        c.lay.addWidget(self.table)
        root.addWidget(c, 1)
        self.lion_note = label("وقتی سفارش لیون وارد انبار شود، قطعه‌های آن خودکار از این لیست حذف می‌شوند.", "Faint")
        root.addWidget(self.lion_note)
        shortcut(self, "Ctrl+C", self.copy)
        shortcut(self, "Ctrl+O", self.open_links)

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Return, Qt.Key_Enter) and not e.modifiers():
            self.add()
        elif e.key() == Qt.Key_Delete:
            self.remove()
        else:
            super().keyPressEvent(e)

    def refresh(self):
        lion = appinfo.lion_enabled(self.db)
        self.cart_btn.setVisible(lion)
        self.lion_note.setVisible(lion)
        rows = []
        total = 0
        for s in self.db.shopping_list():
            r = dict(s)
            r["desc"] = first_part(s["description"])
            r["stock"] = s["stock"] or 0
            r["est"] = (s["unit_price"] or 0) * s["quantity"]
            r["lion_pid"] = product_id_from_link(s["purchase_link"])
            total += r["est"]
            rows.append(r)
        self.table.set_rows(rows)
        self.summary.setText(f"{len(rows)} قلم  ·  برآورد {fmt_money(total)} ریال" if rows else "")

    def _pn_input(self, text=""):
        return PartSearchInput(self.db, text, "پارت نامبر یا بخشی از توضیحات")

    def add(self):
        f = FormDialog(self, "افزودن به لیست خرید", [
            ("pn", "پارت نامبر", self._pn_input()), ("qty", "تعداد", spin(1, 1000000, 1)),
            ("note", "یادداشت", line("", "اختیاری"))])
        f.validator = lambda v: "پارت نامبر را بنویسید" if not v["pn"] else None
        if f.exec():
            v = f.values()
            self.db.add_shopping(v["pn"], v["qty"], "دستی", v["note"])
            self.app.data_changed()

    def edit(self, row):
        f = FormDialog(self, "ویرایش", [("qty", "تعداد خرید", spin(row["quantity"], 1000000, 1)),
                                        ("note", "یادداشت", line(row["note"] or ""))], subtitle=row["part_number"])
        if f.exec():
            v = f.values()
            self.db.update_shopping(row["id"], quantity=v["qty"], note=v["note"])
            self.app.data_changed()

    def add_low(self):
        low = self.db.low_stock_parts()
        for p in low:
            self.db.add_shopping(p["part_number"], p["min_quantity"] - p["quantity"], "کم‌موجود")
        self.app.data_changed()
        toast(self, f"{len(low)} قطعه‌ی کم‌موجود اضافه شد" if low else
              "قطعه‌ی کم‌موجودی نیست (حداقل موجودی را در ویرایش قطعه تعیین کنید)")

    def remove(self):
        rows = self.table.selected_rows()
        if rows:
            self.db.delete_shopping([r["id"] for r in rows])
            self.app.data_changed()
            toast(self, f"{len(rows)} قلم از لیست خرید حذف شد")

    def _rows(self):
        return self.table.selected_rows() or self.table.model_.rows

    def on_click(self, index):
        """کلیک روی ستون «خرید» = باز شدن لینک خرید همان قطعه."""
        if self.table.cols[index.column()].key != "lion":
            return
        from ..widgets import RowRole
        r = index.data(RowRole)
        url = buy_url(r) if r else None
        if url:
            webbrowser.open(url)
            toast(self, f"باز شد: {domain(url)}")

    def on_hover(self, index):
        from ..widgets import RowRole
        r = index.data(RowRole)
        link = self.table.cols[index.column()].key == "lion" and r and buy_url(r)
        self.table.viewport().setCursor(Qt.PointingHandCursor if link else Qt.ArrowCursor)
        self.table.setToolTip(link or "")

    def open_links(self):
        rows = self._rows()
        if len(rows) > 8 and not confirm(self, "باز کردن لینک‌ها", f"{len(rows)} صفحه در مرورگر باز شود؟"):
            return
        for r in rows:
            link = r["purchase_link"] or ""
            webbrowser.open(buy_url(r) or search_url(r["part_number"]))

    def copy(self):
        rows = self._rows()
        QApplication.clipboard().setText("\n".join(f"{r['part_number']}\t{r['quantity']}" for r in rows))
        toast(self, f"{len(rows)} ردیف کپی شد")

    def export(self):
        path, _ = QFileDialog.getSaveFileName(self, "ذخیره", f"shopping_{datetime.now():%Y%m%d}.csv", "CSV (*.csv)")
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["پارت نامبر", "تعداد", "توضیحات", "موجودی", "برآورد (ریال)", "دلیل", "لینک"])
            for r in self._rows():
                w.writerow([r["part_number"], r["quantity"], r["description"], r["stock"], int(r["est"]),
                            r["source"], r["purchase_link"] or search_url(r["part_number"])])
        toast(self, "فایل ذخیره شد")

    def add_to_lion_cart(self):
        from ..dialogs import CaptchaDialog
        from ..widgets import info
        from ..workers import CartWorker
        rows = self.table.selected_rows() or self.table.model_.rows
        ready = [r for r in rows if r.get("lion_pid")]
        missing = [r["part_number"] for r in rows if not r.get("lion_pid")]
        if not ready:
            info(self, "سبد خرید لیون", "هیچ‌کدام از این قطعه‌ها لینک محصول لیون ندارند.\n"
                 "در صفحه‌ی انبار، روی قطعه راست‌کلیک کنید و «دریافت اطلاعات و قیمت از لیون» را بزنید.")
            return
        user, pwd = self.db.get_setting("lion_user"), self.db.get_setting("lion_pass")
        if not user or not pwd:
            toast(self, "ابتدا نام کاربری و رمز لیون را در تنظیمات وارد کنید")
            return
        total = sum((r["unit_price"] or 0) * max(r["quantity"], r.get("lion_moq") or 1) for r in ready)
        again = [r for r in ready if r.get("cart_at")]
        msg = (f"{len(ready)} قلم با تعداد لیست خرید به سبد خرید حساب لیون شما اضافه شود؟\n"
               f"برآورد: {fmt_money(total)} ریال")
        raised = [r for r in ready if r.get("lion_moq") and r["lion_moq"] > r["quantity"]]
        if raised:
            msg += (f"\n\n{len(raised)} قلم کمتر از حداقل سفارش لیون است و تا حداقل افزایش می‌یابد "
                    "(مثلاً " + "، ".join(f"{r['part_number']}: {r['quantity']}→{r['lion_moq']}" for r in raised[:3]) + ").")
        if again:
            msg += f"\n\n⚠ {len(again)} قلم قبلاً به سبد اضافه شده‌اند و تعدادشان دوباره اضافه می‌شود."
        if missing:
            msg += f"\n\n{len(missing)} قلم لینک لیون ندارند و رد می‌شوند."
        msg += "\n\nخرید انجام نمی‌شود؛ فقط سبد پر می‌شود و پرداخت را خودتان در سایت انجام می‌دهید."
        if not confirm(self, "افزودن به سبد خرید لیون", msg, "افزودن به سبد"):
            return
        items = [(r["id"], r["part_number"], r["lion_pid"], int(r["quantity"]), r["purchase_link"]) for r in ready]
        w = CartWorker(user, pwd, items)
        self.worker = w
        self.cart_btn.setEnabled(False)
        self.progress.setRange(0, len(items))
        self.progress.setValue(0)
        self.progress.show()

        def on_progress(i, n, text):
            self.progress.setValue(i)
            if text:
                self.summary.setText(text)

        def on_captcha(img):
            d = CaptchaDialog(self, img)
            w.provide_captcha(d.code.text().strip() if d.exec() else "")

        w.progress.connect(on_progress)
        w.need_captcha.connect(on_captcha)
        w.done.connect(lambda res, err: self.cart_done(res, err, missing))
        w.start()

    def cart_done(self, results, error, missing):
        from ..widgets import BaseDialog
        self.progress.hide()
        self.cart_btn.setEnabled(True)
        self.app.data_changed()
        ok = [r for r in results if r[2]]
        bad = [r for r in results if not r[2]]
        d = BaseDialog(self, "سبد خرید لیون", "" if not error else error, 520)
        lines = []
        if ok:
            lines.append(f"✓ {len(ok)} قلم به سبد خرید اضافه شد.")
        for _, pn, _, m in bad:
            lines.append(f"✗ {pn}: {m}")
        if missing:
            lines.append(f"— {len(missing)} قلم بدون لینک لیون رد شد: " + "، ".join(missing[:8]) + ("…" if len(missing) > 8 else ""))
        d.body.addWidget(label("\n".join(lines) or "چیزی اضافه نشد.", "Muted", wrap=True))
        if ok:
            b = Button("باز کردن سبد خرید در مرورگر", "external", "Primary")
            b.clicked.connect(lambda: (webbrowser.open(CART_URL), d.accept()))
            d.footer.addWidget(b)
        d.add_buttons("بستن", None)
        d.exec()

    def menu(self, pos):
        rows = self.table.selected_rows()
        if not rows:
            return
        m = QMenu(self)
        if len(rows) == 1:
            m.addAction(icon("edit", size=16), "ویرایش تعداد", lambda: self.edit(rows[0]))
            if rows[0].get("part_id"):
                m.addAction(icon("box", size=16), "نمایش در انبار", lambda: self.app.show_part(rows[0]["part_id"]))
        if appinfo.lion_enabled(self.db):
            m.addAction(icon("cart", size=16), "افزودن به سبد خرید لیون", self.add_to_lion_cart)
        m.addAction(icon("external", size=16), "باز کردن لینک خرید", self.open_links)
        m.addAction(icon("copy", size=16), "کپی", self.copy)
        m.addSeparator()
        m.addAction(icon("check", size=16), "خریده شد / حذف\tDelete", self.remove)
        m.exec(pos)
