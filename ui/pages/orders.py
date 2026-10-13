"""صفحه‌ی سفارش‌های لیون."""
import webbrowser

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QMenu, QProgressBar, QSplitter, QVBoxLayout, QWidget

from db import ORDER_IGNORED, ORDER_IN_STOCK, ORDER_PENDING
from ..theme import icon
from ..widgets import (Button, Card, Col, DataTable, PageHeader, SearchBox, Segment, confirm, first_part, fmt_int,
                       label, toast)

STATE = {ORDER_PENDING: ("در انتظار تصمیم", "warning"), ORDER_IN_STOCK: ("وارد انبار شد", "success"),
         ORDER_IGNORED: ("وارد نمی‌شود", "muted")}


class OrdersPage(QWidget):
    def __init__(self, app):
        super().__init__()
        self.app, self.db = app, app.db
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(14)
        self.header = PageHeader("سفارش‌های لیون", "سفارش‌ها از حساب کاربری شما در lionelectronic.ir خوانده می‌شوند")
        self.sync_btn = Button("بررسی سفارش‌های جدید", "refresh", "Primary", tip="F5")
        self.sync_btn.clicked.connect(lambda: app.start_sync())
        self.header.add(self.sync_btn)
        root.addWidget(self.header)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        self.progress.hide()
        root.addWidget(self.progress)

        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.search = SearchBox("جستجوی شماره سفارش یا پارت نامبر…")
        self.search.setFixedWidth(300)
        self.search.changed.connect(self.apply_filter)
        self.seg = Segment([("all", "همه"), ("pending", "در انتظار"), ("stock", "وارد شده"), ("ignored", "وارد نمی‌شود")])
        self.seg.changed.connect(lambda _: self.apply_filter())
        bar.addWidget(self.search)
        bar.addWidget(self.seg)
        bar.addStretch(1)
        for text, ic, kind, fn, tip in [
            ("ورود به انبار", "download", "Primary", self.to_stock, "Ctrl+Enter"),
            ("وارد نشود", "x", None, self.ignore, None),
            ("لغو ورود", "history", None, self.undo, None),
            ("مشاهده در سایت", "external", None, self.open_site, None)]:
            b = Button(text, ic, kind, tip)
            b.clicked.connect(fn)
            bar.addWidget(b)
        root.addLayout(bar)

        split = QSplitter(Qt.Vertical)
        split.setChildrenCollapsible(False)
        split.setHandleWidth(12)
        cols = [Col("order_code", "شماره سفارش", 120, "center", "num"),
                Col("order_date", "تاریخ", 150, "center"),
                Col("status", "وضعیت در سایت", 170, "center"),
                Col("total", "مبلغ", 170, "center"),
                Col("item_count", "اقلام", 70, "center", "int"),
                Col("state", "انبار", 150, "center", pill=lambda r: STATE.get(r["added_to_stock"], ("", "muted"))),
                Col("spacer", "", 10, stretch=True)]
        self.orders = DataTable(cols, empty_text="سفارشی نیست — «بررسی سفارش‌های جدید» را بزنید")
        self.orders.sortByColumn(1, Qt.DescendingOrder)   # جدیدترین سفارش بالا
        self.orders.selection_changed.connect(self.show_items)
        self.orders.activated_row.connect(lambda r: self.open_site())
        self.orders.context_menu.connect(self.menu)
        self.orders.typed.connect(lambda ch: (self.search.setFocus(), self.search.setText(self.search.text() + ch)))
        c1 = Card()
        c1.lay.setContentsMargins(1, 4, 1, 1)
        c1.lay.addWidget(self.orders)
        split.addWidget(c1)

        c2 = Card()
        c2.lay.setContentsMargins(1, 10, 1, 1)
        self.items_title = label("اقلام سفارش", "H2")
        self.items_title.setContentsMargins(14, 0, 14, 6)
        c2.lay.addWidget(self.items_title)

        def item_style(row, key):
            if key == "stock_now":
                return "muted"
            return None
        icols = [Col("part_number", "پارت نامبر", 190),
                 Col("desc", "توضیحات", 300, stretch=True),
                 Col("quantity", "تعداد", 70, "center", "int"),
                 Col("unit_price", "فی (ریال)", 120, "center", "money"),
                 Col("total_price", "جمع (ریال)", 130, "center", "money", hide=2),
                 Col("stock_now", "موجودی فعلی", 100, "center", "int", hide=1)]
        self.items = DataTable(icols, item_style, empty_text="یک سفارش را انتخاب کنید")
        self.items.activated_row.connect(self.goto_part)
        c2.lay.addWidget(self.items)
        split.addWidget(c2)
        split.setSizes([420, 300])
        root.addWidget(split, 1)
        self.status = label("", "Faint")
        root.addWidget(self.status)

        from ..widgets import shortcut
        shortcut(self, ["Ctrl+Return", "Ctrl+Enter"], self.to_stock)
        shortcut(self, "Delete", self.delete)

    def set_syncing(self, on, text=""):
        self.progress.setVisible(on)
        self.sync_btn.setEnabled(not on)
        self.sync_btn.setText("در حال بررسی…" if on else "بررسی سفارش‌های جدید")
        if text:
            self.status.setText(text)

    def refresh(self):
        rows = []
        pns = {}
        for o in self.db.list_orders():
            r = dict(o)
            r["state"] = STATE.get(o["added_to_stock"], ("",))[0]
            rows.append(r)
        for it in self.db.q("SELECT order_id, part_number FROM lion_order_items"):
            pns.setdefault(it["order_id"], []).append(it["part_number"].lower())
        for r in rows:
            r["_hay"] = f"{r['order_code']} {' '.join(pns.get(r['id'], []))}".lower()
        self.orders.set_rows(rows)
        self.apply_filter()
        self.show_items()

    def apply_filter(self):
        q = self.search.text().strip().lower()
        st = {"all": None, "pending": ORDER_PENDING, "stock": ORDER_IN_STOCK, "ignored": ORDER_IGNORED}[self.seg.value]
        self.orders.set_filter(lambda r: (not q or q in r["_hay"]) and (st is None or r["added_to_stock"] == st))

    def show_items(self):
        rows = self.orders.selected_rows()
        if len(rows) != 1:
            self.items.set_rows([], keep_selection=False)
            self.items_title.setText("اقلام سفارش" if not rows else f"{len(rows)} سفارش انتخاب شده")
            return
        o = rows[0]
        self.items_title.setText(f"اقلام سفارش {o['order_code']}   ·   {o['order_date'] or ''}")
        items = []
        for it in self.db.order_items(o["id"]):
            r = dict(it)
            r["desc"] = first_part(it["description"])
            p = self.db.find_part(it["part_number"])
            r["stock_now"] = p["quantity"] if p else 0
            r["part_id"] = p["id"] if p else None
            items.append(r)
        self.items.set_rows(items, keep_selection=False)

    def goto_part(self, row):
        if row.get("part_id"):
            self.app.show_part(row["part_id"])

    def _sel(self):
        rows = self.orders.selected_rows()
        if not rows:
            toast(self, "ابتدا سفارش را انتخاب کنید")
        return rows

    def to_stock(self):
        rows = [r for r in self._sel() if r["added_to_stock"] != ORDER_IN_STOCK]
        if not rows:
            return
        touched = []
        for r in rows:
            touched += self.db.add_order_to_stock(r["id"])
        self.app.data_changed()
        toast(self, f"{len(rows)} سفارش ({len(touched)} قلم) وارد انبار شد")
        self.app.enrich(list(set(touched)), quiet=True)

    def ignore(self):
        rows = [r for r in self._sel() if r["added_to_stock"] == ORDER_PENDING]
        for r in rows:
            self.db.set_order_state(r["id"], ORDER_IGNORED)
        if rows:
            self.app.data_changed()
            toast(self, f"{len(rows)} سفارش «وارد نمی‌شود» علامت خورد")
        else:
            toast(self, "فقط سفارش‌های «در انتظار تصمیم» قابل این کار هستند")

    def undo(self):
        rows = [r for r in self._sel() if r["added_to_stock"] == ORDER_IN_STOCK]
        if not rows:
            return
        if confirm(self, "لغو ورود به انبار", f"اقلام {len(rows)} سفارش از موجودی انبار کم شود؟", "کم کن", True):
            n = sum(self.db.remove_order_from_stock(r["id"]) for r in rows)
            self.app.data_changed()
            toast(self, f"ورود {len(rows)} سفارش ({n} قلم) لغو شد")

    def open_site(self):
        for r in self._sel()[:5]:
            if r["url"]:
                webbrowser.open(r["url"])

    def delete(self):
        rows = self._sel()
        if rows and confirm(self, "حذف از لیست", f"{len(rows)} سفارش از این لیست حذف شود؟\n"
                            "موجودی انبار تغییری نمی‌کند و در بررسی بعدی دوباره دریافت می‌شوند.", "حذف", True):
            self.db.delete_orders([r["id"] for r in rows])
            self.app.data_changed()

    def menu(self, pos):
        if not self.orders.selected_rows():
            return
        m = QMenu(self)
        m.addAction(icon("download", size=16), "ورود به انبار\tCtrl+Enter", self.to_stock)
        m.addAction(icon("x", size=16), "وارد نشود", self.ignore)
        m.addAction(icon("history", size=16), "لغو ورود به انبار", self.undo)
        m.addAction(icon("external", size=16), "مشاهده در سایت", self.open_site)
        m.addSeparator()
        m.addAction(icon("trash", size=16), "حذف از لیست\tDelete", self.delete)
        m.exec(pos)
