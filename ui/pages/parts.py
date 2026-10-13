"""صفحه‌ی انبار قطعات: درخت دسته‌ها، جدول، پنل جزئیات و میانبرها."""
import json
import os
import webbrowser

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QApplication, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QMenu,
                               QScrollArea, QSplitter, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

import images
import importer
from db import to_jalali
import appinfo
from lion_client import search_url
from ..charts import Sparkline
from ..dialogs import ImportDialog, PartDialog, StockDialog
from ..theme import Theme, icon
from ..widgets import (tokens_match, BaseDialog, Button, Card, Col, DataTable, Divider, FlowLayout, PageHeader, SearchBox, Segment, confirm, first_part,
                       fmt_int, fmt_money, label, toast)

ALL, NONE = "all", "none"


def norm(text):
    return (text or "").lower().replace("ي", "ی").replace("ك", "ک")


def purchase_label(link):
    link = link or ""
    if "lionelectronic" in link or "لیون" in link:
        return "لیون"
    if link.startswith("http"):
        return link.split("/")[2].replace("www.", "")
    return link


class DetailPanel(QFrame):
    def __init__(self, page):
        super().__init__()
        self.page = page
        self.setObjectName("Card")
        self.setMinimumWidth(340)
        self.setMaximumWidth(520)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.NoFrame)
        outer.addWidget(scroll)
        body = QWidget()
        body.setObjectName("ScrollBody")
        scroll.setWidget(body)
        self.lay = QVBoxLayout(body)
        self.lay.setContentsMargins(18, 16, 18, 14)
        self.lay.setSpacing(8)

        # ---- empty
        self.empty = QWidget()
        el = QVBoxLayout(self.empty)
        el.setContentsMargins(0, 40, 0, 0)
        el.setSpacing(6)
        self.empty_icon = QLabel()
        self.empty_icon.setAlignment(Qt.AlignCenter)
        el.addWidget(self.empty_icon)
        t = label("قطعه‌ای انتخاب نشده", "EmptyTitle")
        t.setAlignment(Qt.AlignCenter)
        el.addWidget(t)
        h = label("روی یک قطعه کلیک کنید.\nEnter = قطعه‌ی جدید   ·   + ورود   ·   − خروج", "Faint", wrap=True)
        h.setAlignment(Qt.AlignCenter)
        el.addWidget(h)
        self.lay.addWidget(self.empty)

        # ---- multi
        self.multi = QWidget()
        ml = QVBoxLayout(self.multi)
        ml.setContentsMargins(0, 0, 0, 0)
        ml.setSpacing(10)
        self.multi_title = label("", "H2")
        self.multi_info = label("", "Muted", wrap=True)
        ml.addWidget(self.multi_title)
        ml.addWidget(self.multi_info)
        for text, ic, fn, kind in [("لیبل قفسه (تا ۳ قطعه)", "tag", page.shelf_label, None),
                                   ("افزودن به لیست خرید", "cart", page.add_to_shopping, None),
                                   ("چاپ برچسب", "printer", page.print_labels, None),
                                   ("حذف", "trash", page.delete, "Danger")]:
            b = Button(text, ic, kind)
            b.clicked.connect(fn)
            ml.addWidget(b)
        self.lay.addWidget(self.multi)

        # ---- single
        self.single = QWidget()
        sl = QVBoxLayout(self.single)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(8)
        self.photo = QLabel()
        self.photo.setObjectName("Photo")
        self.photo.setAlignment(Qt.AlignCenter)
        self.photo.setFixedHeight(150)
        self.photo.setCursor(Qt.PointingHandCursor)
        self.photo.setToolTip("کلیک = نمایش بزرگ‌تر")
        self.photo.mousePressEvent = lambda e: self.show_photo()
        sl.addWidget(self.photo)
        top = QHBoxLayout()
        self.pn = label("", "H2")
        self.pn.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.pn.setLayoutDirection(Qt.LeftToRight)
        self.pn.setWordWrap(True)
        copy = Button("", "copy", "Icon", tip="کپی پارت نامبر (Ctrl+C)")
        copy.clicked.connect(page.copy_pn)
        edit = Button("", "edit", "Icon", tip="ویرایش (F2)")
        edit.clicked.connect(page.edit)
        top.addWidget(self.pn, 1)
        top.addWidget(copy)
        top.addWidget(edit)
        sl.addLayout(top)
        self.desc = label("", "Muted", wrap=True)
        self.desc.setTextInteractionFlags(Qt.TextSelectableByMouse)
        sl.addWidget(self.desc)
        self.pills_box = QWidget()
        self.pills = FlowLayout(self.pills_box)
        sl.addWidget(self.pills_box)

        stock = QFrame()
        stock.setObjectName("Card")
        stl = QHBoxLayout(stock)
        stl.setContentsMargins(14, 10, 10, 10)
        col = QVBoxLayout()
        col.setSpacing(0)
        col.addWidget(label("موجودی", "StatTitle"))
        self.qty = label("", "StatValue")
        col.addWidget(self.qty)
        stl.addLayout(col, 1)
        self.btn_in = Button("", "plus", tip="ورود (+)")
        self.btn_out = Button("", "minus", tip="خروج (−)")
        for b in (self.btn_in, self.btn_out):
            b.setFixedSize(40, 40)
        self.btn_in.clicked.connect(lambda: page.move(1))
        self.btn_out.clicked.connect(lambda: page.move(-1))
        stl.addWidget(self.btn_in)
        stl.addWidget(self.btn_out)
        sl.addWidget(stock)

        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(8)
        self.fields = {}
        for i, (key, title) in enumerate([("location", "محل نگهداری"), ("min", "حداقل موجودی"),
                                          ("price", "قیمت واحد (ریال)"), ("value", "ارزش موجودی (ریال)")]):
            box = QVBoxLayout()
            box.setSpacing(1)
            box.addWidget(label(title, "Faint"))
            v = label("—")
            v.setWordWrap(True)
            v.setTextFormat(Qt.RichText)
            v.linkActivated.connect(lambda href: self.page.app.show_drawer(int(href)))
            v.setToolTip("کلیک روی کد = نمایش کشو در قفسه")
            box.addWidget(v)
            self.fields[key] = v
            grid.addLayout(box, i // 2, i % 2)
        sl.addLayout(grid)

        self.price_box = QWidget()
        pl = QVBoxLayout(self.price_box)
        pl.setContentsMargins(0, 4, 0, 0)
        pl.setSpacing(4)
        ph = QHBoxLayout()
        ph.addWidget(label("تاریخچه‌ی قیمت", "Faint"))
        ph.addStretch(1)
        self.price_change = label("", "Pill")
        ph.addWidget(self.price_change)
        pl.addLayout(ph)
        self.spark = Sparkline()
        pl.addWidget(self.spark)
        sl.addWidget(self.price_box)

        links = QHBoxLayout()
        self.ds_btn = Button("دیتاشیت", "file")
        self.buy_btn = Button("صفحه‌ی خرید", "external")
        self.ds_btn.clicked.connect(lambda: self._open("datasheet"))
        self.buy_btn.clicked.connect(lambda: self._open("buy"))
        links.addWidget(self.ds_btn)
        links.addWidget(self.buy_btn)
        sl.addLayout(links)

        self.specs = label("", "Faint", wrap=True)
        self.specs.setTextInteractionFlags(Qt.TextSelectableByMouse)
        sl.addWidget(self.specs)

        sl.addWidget(Divider())
        sl.addWidget(label("آخرین ورود و خروج‌ها", "Faint"))
        self.tx = QVBoxLayout()
        self.tx.setSpacing(4)
        sl.addLayout(self.tx)
        self.lay.addWidget(self.single)
        self.lay.addStretch(1)
        self.part = None
        Theme.listeners.append(self._icons)
        self._icons()
        self.show_none()

    def _icons(self):
        self.empty_icon.setPixmap(icon("box", "faint", 40).pixmap(40, 40))

    def set_photo(self, p):
        path = images.thumb_path(p["id"]) if images.has_thumb(p["id"]) else None
        if not path:
            self.photo.hide()
            return
        from PySide6.QtGui import QPixmap
        pm = QPixmap(path)
        ratio = self.devicePixelRatioF()
        pm = pm.scaled(int(140 * ratio), int(140 * ratio), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        pm.setDevicePixelRatio(ratio)
        self.photo.setPixmap(pm)
        self.photo.show()

    def show_photo(self):
        if self.part:
            PhotoDialog(self, self.part).exec()

    def _open(self, which):
        p = self.part
        if not p:
            return
        if which == "datasheet" and p["datasheet"]:
            webbrowser.open(p["datasheet"])
        elif which == "buy":
            link = p["purchase_link"] or ""
            webbrowser.open(link if link.startswith("http") else search_url(p["part_number"]))

    def show_none(self):
        self.part = None
        self.empty.show()
        self.multi.hide()
        self.single.hide()

    def show_multi(self, rows):
        self.part = None
        self.empty.hide()
        self.single.hide()
        self.multi.show()
        self.multi_title.setText(f"{len(rows)} قطعه انتخاب شده")
        qty = sum(r["quantity"] for r in rows)
        val = sum(r["value"] for r in rows)
        self.multi_info.setText(f"مجموع موجودی: {fmt_int(qty)}\nارزش: {fmt_money(val)} ریال")

    def show_part(self, row):
        db = self.page.db
        p = db.get_part(row["id"])
        if not p:
            return self.show_none()
        self.part = p
        self.empty.hide()
        self.multi.hide()
        self.single.show()
        self.pn.setText(p["part_number"])
        self.set_photo(p)
        desc = (p["description"] or "").replace(" | ", "\n")
        self.desc.setText(desc)
        self.desc.setVisible(bool(desc))
        while self.pills.count():
            w = self.pills.takeAt(0).widget()
            if w:
                w.deleteLater()
        cat = db.categories().get(p["category_id"])
        for text, kind in [(cat["short"] if cat else "", "PillAccent"), (p["package"], "Pill"),
                           (p["manufacturer"], "Pill"), (f"لیون: {p['lion_pn']}" if p["lion_pn"] else "", "PillSuccess")]:
            if text:
                l = label(text, kind)
                l.setToolTip(cat["path"] if cat and text == cat["short"] else text)
                self.pills.addWidget(l)
        self.pills_box.setVisible(self.pills.count() > 0)
        self.pills.invalidate()
        q = p["quantity"]
        color = Theme.c["danger"] if q <= 0 else Theme.c["warning"] if q < p["min_quantity"] else Theme.c["text"]
        self.qty.setText(f"<span style='color:{Theme.c['warning']}'>؟</span>&nbsp;<span style='font-size:9pt; "
                         f"color:{Theme.c['warning']}'>شمارش نشده (کلید =)</span>" if p["needs_count"]
                         else f"<span style='color:{color}'>{fmt_int(q)}</span>")
        locs = db.part_locations(p["id"])
        links = [f"<a href='{l['drawer_id']}' style='color:{Theme.c['accent_text']}; text-decoration:none'>"
                 f"<b>{l['code']}</b></a>" for l in locs]
        if p["location"]:
            links.append(p["location"])
        self.fields["location"].setText("، ".join(links) or "—")
        self.fields["min"].setText(fmt_int(p["min_quantity"]) if p["min_quantity"] else "—")
        self.fields["price"].setText(fmt_money(p["unit_price"]))
        self.fields["value"].setText(fmt_money(max(q, 0) * (p["unit_price"] or 0)))
        hist = db.price_history(p["id"])
        pts = [(to_jalali(h["created_at"], False), h["price"]) for h in hist]
        self.spark.set_points(pts)
        self.price_box.setVisible(len(pts) >= 2)
        if len(pts) >= 2 and pts[0][1]:
            ch = (pts[-1][1] - pts[0][1]) / pts[0][1] * 100
            self.price_change.setText(f"{ch:+.0f}٪")
            self.price_change.setObjectName("PillDanger" if ch > 0 else "PillSuccess" if ch < 0 else "Pill")
            self.price_change.style().unpolish(self.price_change)
            self.price_change.style().polish(self.price_change)
        self.ds_btn.setVisible(bool(p["datasheet"]))
        has_link = (p["purchase_link"] or "").startswith("http")
        self.buy_btn.setText("صفحه‌ی خرید" if has_link else "جستجو در لیون")
        self.buy_btn.setVisible(has_link or appinfo.lion_enabled(self.db))
        specs = {}
        try:
            specs = json.loads(p["specs"] or "{}")
        except ValueError:
            pass
        self.specs.setText("<br>".join(f"<b>{k}</b>: {v}" for k, v in list(specs.items())[:8]))
        self.specs.setVisible(bool(specs))
        while self.tx.count():
            w = self.tx.takeAt(0).widget()
            if w:
                w.deleteLater()
        trs = db.part_transactions(p["id"], 4)
        if not trs:
            self.tx.addWidget(label("سابقه‌ای نیست", "Faint"))
        for t in trs:
            ch = t["change"]
            c = Theme.c["success"] if ch > 0 else Theme.c["danger"]
            l = label(f"<span style='color:{c}; font-weight:600'>{'+' if ch > 0 else ''}{ch}</span>"
                      f"&nbsp;&nbsp;<span style='color:{Theme.c['muted']}'>{to_jalali(t['created_at'], False)}"
                      f"&nbsp;·&nbsp;{t['reason'] or ''}</span>")
            l.setWordWrap(True)
            self.tx.addWidget(l)


class PhotoDialog(BaseDialog):
    """عکس بزرگ‌تر: اول عکس ذخیره‌شده، بعد نسخه‌ی باکیفیت از سایت."""

    def __init__(self, parent, part):
        super().__init__(parent, part["part_number"], first_part(part["description"]), 560)
        from PySide6.QtGui import QPixmap
        self.view = QLabel()
        self.view.setObjectName("Photo")
        self.view.setAlignment(Qt.AlignCenter)
        self.view.setFixedSize(500, 500)
        if images.has_thumb(part["id"]):
            self.view.setPixmap(QPixmap(images.thumb_path(part["id"])).scaled(
                500, 500, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self.body.addWidget(self.view, 0, Qt.AlignCenter)
        self.status = label("در حال دریافت نسخه‌ی باکیفیت…" if part["image_url"] else "", "Faint")
        self.footer_left.addWidget(self.status)
        if part["purchase_link"] and part["purchase_link"].startswith("http"):
            b = Button("صفحه‌ی محصول", "external")
            b.setAutoDefault(False)
            b.clicked.connect(lambda: webbrowser.open(part["purchase_link"]))
            self.footer_left.addWidget(b)
        self.add_buttons("بستن", None)
        self.worker = None
        if part["image_url"]:
            from ..workers import ImageWorker
            self.worker = ImageWorker(part["image_url"], 1000)
            self.worker.done.connect(self.on_big)
            self.worker.start()

    def on_big(self, data):
        from PySide6.QtGui import QPixmap
        if not data:
            self.status.setText("دریافت نسخه‌ی بزرگ ممکن نشد (نمایش عکس ذخیره‌شده)")
            return
        pm = QPixmap()
        pm.loadFromData(data)
        ratio = self.devicePixelRatioF()
        pm = pm.scaled(int(500 * ratio), int(500 * ratio), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        pm.setDevicePixelRatio(ratio)
        self.view.setPixmap(pm)
        self.status.setText("")

    def done(self, r):
        if self.worker and self.worker.isRunning():
            self.worker.done.disconnect()
            self.worker.wait(100)
        super().done(r)


class PartsPage(QWidget):
    def __init__(self, app):
        super().__init__()
        self.app, self.db = app, app.db
        self.cat_filter = ALL
        self.stock_filter = "all"
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(14)

        self.header = PageHeader("انبار قطعات", "")
        b_import = Button("ایمپورت اکسل", "upload", tip="Ctrl+I")
        b_import.clicked.connect(self.import_excel)
        b_labels = Button("برچسب و QR", "qr", tip="برچسب تکی قطعه (Ctrl+P)")
        b_labels.clicked.connect(self.print_labels)
        b_shelf = Button("لیبل قفسه", "tag", tip="لیبل کشو از ۱ تا ۳ قطعه‌ی انتخاب‌شده (Ctrl+L)")
        b_shelf.clicked.connect(self.shelf_label)
        b_new = Button("قطعه‌ی جدید", "plus", "Primary", tip="Enter")
        b_new.clicked.connect(self.add)
        self.header.add(b_import, b_labels, b_shelf, b_new)
        root.addWidget(self.header)

        bar = QHBoxLayout()
        bar.setSpacing(10)
        self.search = SearchBox("جستجو در پارت نامبر، توضیحات، محل، پکیج…  ( / )")
        self.search.setFixedWidth(360)
        self.search.changed.connect(self.apply_filter)
        self.search.returnPressed.connect(self.focus_table)
        self.seg = Segment([("all", "همه"), ("low", "کم‌موجود"), ("empty", "ناموجود"), ("count", "شمارش‌نشده")])
        self.seg.changed.connect(self.set_stock_filter)
        self.tree_btn = Button("دسته‌ها", "folder")
        self.tree_btn.setCheckable(True)
        self.tree_btn.setChecked(self.db.get_setting("show_tree", "1") == "1")
        self.tree_btn.toggled.connect(self.toggle_tree)
        self.count = label("", "Muted")
        bar.addWidget(self.search)
        bar.addWidget(self.seg)
        bar.addWidget(self.tree_btn)
        bar.addStretch(1)
        bar.addWidget(self.count)
        root.addLayout(bar)

        self.split = QSplitter(Qt.Horizontal)
        self.split.setChildrenCollapsible(False)
        self.split.setHandleWidth(12)

        # درخت دسته‌ها
        self.tree_card = Card()
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setColumnCount(2)
        self.tree.setIndentation(14)
        self.tree.setRootIsDecorated(True)
        self.tree.setUniformRowHeights(True)
        self.tree.setFrameShape(QFrame.NoFrame)
        self.tree.itemSelectionChanged.connect(self.on_tree)
        tl = self.tree_card.lay
        tl.setContentsMargins(6, 10, 6, 6)
        hdr = label("دسته‌بندی‌ها", "StatTitle")
        hdr.setContentsMargins(10, 0, 10, 6)
        tl.addWidget(hdr)
        tl.addWidget(self.tree)
        self.tree_card.setMinimumWidth(180)

        cols = [
            Col("part_number", "پارت نامبر", 160),
            Col("desc", "توضیحات", 280, stretch=True),
            Col("cat", "دسته", 150, hide=3),
            Col("package", "پکیج", 90, hide=2),
            Col("location", "محل", 90, hide=4),
            Col("quantity", "موجودی", 74, "center", "int",
                fmt=lambda r: "؟" if r["needs_count"] else fmt_int(r["quantity"])),
            Col("unit_price", "قیمت واحد", 100, "center", "money", hide=5),
            Col("buy", "خرید از", 70, "center", hide=1),
        ]

        def style(row, key):
            if key == "quantity":
                if row["needs_count"]:
                    return "warning"
                if row["quantity"] <= 0:
                    return "danger"
                if row["min_quantity"] and row["quantity"] < row["min_quantity"]:
                    return "warning"
            if key in ("cat", "buy", "location", "package"):
                return "muted"
            return None

        self.table = DataTable(cols, style, empty_text="قطعه‌ای پیدا نشد")
        self.table.selection_changed.connect(self.on_select)
        self.table.activated_row.connect(lambda r: self.edit())
        self.table.typed.connect(self.type_to_search)
        self.table.context_menu.connect(self.menu)
        self.table_card = Card()
        self.table_card.lay.setContentsMargins(1, 4, 1, 1)
        self.table_card.lay.addWidget(self.table)

        self.detail = DetailPanel(self)
        self.split.addWidget(self.tree_card)
        self.split.addWidget(self.table_card)
        self.split.addWidget(self.detail)
        self.split.setStretchFactor(0, 0)
        self.split.setStretchFactor(1, 1)
        self.split.setStretchFactor(2, 0)
        self.split.setSizes([220, 800, 400])
        saved = self.db.get_setting("parts_split")
        if saved:
            from PySide6.QtCore import QByteArray
            self.split.restoreState(QByteArray.fromBase64(saved.encode()))
        self.split.splitterMoved.connect(lambda *_: self.db.set_setting(
            "parts_split", bytes(self.split.saveState().toBase64()).decode()))
        root.addWidget(self.split, 1)
        self.tree_card.setVisible(self.tree_btn.isChecked())

        from ..widgets import shortcut
        shortcut(self, "Ctrl+C", self.copy_pn)
        shortcut(self, "Ctrl+B", self.add_to_shopping)
        shortcut(self, "Ctrl+P", self.print_labels)
        shortcut(self, "Ctrl+L", self.shelf_label)
        shortcut(self, "Ctrl+I", self.import_excel)
        self.rows = []

    # ------------------------------------------------------------------ data
    def refresh(self):
        cats = self.db.categories()
        rows = []
        locs = self.db.locations_map()
        for p in self.db.list_parts():
            cat = cats.get(p["category_id"])
            r = dict(p)
            codes = locs.get(p["id"], [])
            r["location"] = "، ".join(["\u2066" + c + "\u2069" for c in codes] + ([p["location"]] if p["location"] else []))
            r["desc"] = first_part(p["description"])
            r["cat"] = cat["name"] if cat else ""
            r["cat_path"] = cat["path"] if cat else ""
            r["buy"] = purchase_label(p["purchase_link"])
            r["value"] = max(p["quantity"], 0) * (p["unit_price"] or 0)
            r["_hay"] = norm(" ".join(str(x or "") for x in (
                p["part_number"], p["description"], r["location"], p["package"], p["manufacturer"], r["cat_path"],
                p["lion_pn"])))
            rows.append(r)
        self.rows = rows
        self.table.set_rows(rows)
        self.build_tree()
        self.apply_filter()
        self.on_select()

    def build_tree(self):
        cats = self.db.categories()
        counts = {}
        none = 0
        for r in self.rows:
            cid = r["category_id"]
            if cid not in cats:
                none += 1
                continue
            cur, guard = cid, 0
            while cur in cats and guard < 6:
                counts[cur] = counts.get(cur, 0) + 1
                cur = cats[cur]["parent_id"]
                guard += 1
        self.tree.blockSignals(True)
        self.tree.clear()

        def mk(parent, text, n, key):
            it = QTreeWidgetItem(parent, [text, str(n)])
            it.setData(0, Qt.UserRole, key)
            it.setTextAlignment(1, Qt.AlignLeft | Qt.AlignVCenter)
            it.setForeground(1, Theme.color("faint"))
            return it

        top_all = mk(self.tree, "همه‌ی قطعات", len(self.rows), ALL)
        items = {ALL: top_all}
        if none:
            items[NONE] = mk(self.tree, "بدون دسته", none, NONE)
        children = {}
        for c in cats.values():
            if c["id"] in counts:
                children.setdefault(c["parent_id"], []).append(c)

        def add(parent_item, parent_id):
            for c in sorted(children.get(parent_id, []), key=lambda c: -counts[c["id"]]):
                it = mk(parent_item, c["name"], counts[c["id"]], c["id"])
                items[c["id"]] = it
                add(it, c["id"])
        add(self.tree, None)
        self.tree.header().setStretchLastSection(False)
        from PySide6.QtWidgets import QHeaderView
        self.tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        sel = items.get(self.cat_filter) or top_all
        if self.cat_filter not in items:
            self.cat_filter = ALL
        sel.setSelected(True)
        p = sel.parent()
        while p:
            p.setExpanded(True)
            p = p.parent()
        self.tree.blockSignals(False)

    def on_tree(self):
        it = self.tree.currentItem() or (self.tree.selectedItems() or [None])[0]
        self.cat_filter = it.data(0, Qt.UserRole) if it else ALL
        self.apply_filter()

    def set_stock_filter(self, key):
        self.stock_filter = key
        self.apply_filter()

    def apply_filter(self):
        tokens = norm(self.search.text()).split()
        cat_ids = None
        if self.cat_filter not in (ALL, NONE):
            cat_ids = self.db.category_descendants(self.cat_filter)
        cats = self.db.categories()
        sf, cf = self.stock_filter, self.cat_filter

        def pred(r):
            if tokens and not tokens_match(tokens, r["_hay"]):
                return False
            if cf == NONE and r["category_id"] in cats:
                return False
            if cat_ids is not None and r["category_id"] not in cat_ids:
                return False
            if sf == "low" and not (r["min_quantity"] and r["quantity"] < r["min_quantity"]):
                return False
            if sf == "empty" and (r["quantity"] > 0 or r["needs_count"]):
                return False
            if sf == "count" and not r["needs_count"]:
                return False
            return True
        self.table.set_filter(pred)
        n = self.table.visible_count()
        self.count.setText(f"{fmt_int(n)} از {fmt_int(len(self.rows))} قطعه" if n != len(self.rows) else f"{fmt_int(n)} قطعه")
        st = self.db.stats()
        self.header.sub.setText(f"{fmt_int(st['n'])} قلم  ·  {fmt_int(st['qty'])} عدد  ·  ارزش {fmt_money(st['value'])} ریال")
        self.header.sub.show()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.tree_card.setVisible(self.tree_btn.isChecked() and self.width() > 960)

    def toggle_tree(self, on):
        self.tree_card.setVisible(on and self.width() > 960)
        self.db.set_setting("show_tree", "1" if on else "0")

    def on_select(self):
        rows = self.table.selected_rows()
        if not rows:
            self.detail.show_none()
        elif len(rows) == 1:
            self.detail.show_part(rows[0])
        else:
            self.detail.show_multi(rows)

    # ------------------------------------------------------------------ keyboard
    def focus_search(self, text=""):
        self.search.setFocus()
        if text:
            self.search.setText(self.search.text() + text)
        else:
            self.search.selectAll()

    def type_to_search(self, ch):
        self.search.setFocus()
        self.search.setText(self.search.text() + ch)

    def focus_table(self):
        self.table.setFocus()
        if not self.table.selected_rows():
            self.table.select_first()

    def keyPressEvent(self, e):
        k = e.key()
        if self.search.hasFocus():
            return super().keyPressEvent(e)
        if k in (Qt.Key_Return, Qt.Key_Enter) and not e.modifiers():
            self.add()
        elif k == Qt.Key_Plus:
            self.move(1)
        elif k == Qt.Key_Minus:
            self.move(-1)
        elif k == Qt.Key_Equal:
            self.move(0)
        elif k == Qt.Key_F2:
            self.edit()
        elif k == Qt.Key_Delete:
            self.delete()
        elif k == Qt.Key_Slash:
            self.focus_search()
        else:
            super().keyPressEvent(e)

    # ------------------------------------------------------------------ actions
    def selected_one(self):
        rows = self.table.selected_rows()
        if len(rows) != 1:
            toast(self, "یک قطعه را انتخاب کنید" if not rows else "فقط یک قطعه را انتخاب کنید")
            return None
        return self.db.get_part(rows[0]["id"])

    def add(self):
        d = PartDialog(self, self.db)
        ok = d.exec()
        if ok and getattr(d, "goto_existing", None):
            self.app.show_part(d.goto_existing)
            return
        if ok and d.result_data:
            pid = self.db.save_part(d.result_data)
            self._save_codes(pid, d.result_data)
            self.app.data_changed()
            self.table.select_ids({pid}, pid)
            self.table.scrollTo(self.table.currentIndex())
            toast(self, f"قطعه‌ی {d.result_data['part_number']} اضافه شد")
            self.app.enrich([pid], quiet=True)

    def edit(self):
        p = self.selected_one()
        if not p:
            return
        d = PartDialog(self, self.db, p)
        if d.exec() and d.result_data and getattr(d, "merge_into", None):
            data = dict(d.result_data)
            data["part_number"] = p["part_number"]  # اول تغییرات روی خودش، بعد ادغام
            self.db.save_part(data, p["id"])
            self._save_codes(p["id"], data)
            target = d.merge_into
            self.db.merge_parts(p["id"], target)
            self.app.data_changed()
            self.app.show_part(target)
            toast(self, f"دو قطعه در «{d.result_data['part_number']}» ادغام شدند")
            return
        if d.result_data:
            self.db.save_part(d.result_data, p["id"])
            self._save_codes(p["id"], d.result_data)
            if d.lookup_done:
                self.app.enrich([p["id"]], quiet=True)
            self.app.data_changed()
            toast(self, "تغییرات ذخیره شد")

    def _save_codes(self, pid, data):
        bad = self.db.set_part_location_codes(pid, data.get("location_codes", []))
        if bad:
            toast(self, "این کدها قفسه/خانه‌ی معتبر ندارند: " + "، ".join("\u2066" + b + "\u2069" for b in bad))

    def move(self, mode):
        p = self.selected_one()
        if not p:
            return
        reasons = [r["name"] for r in self.db.list_projects()]
        d = StockDialog(self, p, mode, reasons)
        if d.exec() and d.result_data:
            change, reason = d.result_data
            if mode == 0 and not reason:
                reason = "شمارش انبار"
            idx = self.table.currentIndex().row()
            if change:
                self.db.change_stock(p["id"], change, reason, "manual")
            if mode == 0 or p["needs_count"]:
                self.db.set_needs_count(p["id"], False)
            self.app.data_changed()
            if mode == 0 and self.stock_filter == "count":
                self.table.select_row(min(idx, self.table.visible_count() - 1))
                if not self.table.visible_count():
                    toast(self, "همه‌ی قطعه‌ها شمارش شدند 👌")
                    return
            word = "ورود" if change > 0 else "خروج"
            toast(self, f"{word} {abs(change)} عدد {p['part_number']} ثبت شد")
            self.table.setFocus()

    def delete(self):
        rows = self.table.selected_rows()
        if not rows:
            return
        msg = (f"قطعه‌ی «{rows[0]['part_number']}» و سوابق ورود و خروجش حذف شود؟" if len(rows) == 1
               else f"{len(rows)} قطعه‌ی انتخاب‌شده و سوابق ورود و خروجشان حذف شوند؟")
        if confirm(self, "حذف قطعه", msg, "حذف", danger=True):
            self.db.delete_parts([r["id"] for r in rows])
            images.delete_thumbs([r["id"] for r in rows])
            self.app.data_changed()
            toast(self, f"{len(rows)} قطعه حذف شد")

    def copy_pn(self):
        rows = self.table.selected_rows()
        if rows:
            QApplication.clipboard().setText("\n".join(r["part_number"] for r in rows))
            toast(self, "پارت نامبر کپی شد")

    def add_to_shopping(self):
        rows = self.table.selected_rows()
        if not rows:
            return
        for r in rows:
            need = max(1, (r["min_quantity"] or 0) - r["quantity"])
            self.db.add_shopping(r["part_number"], need, "دستی")
        self.app.data_changed()
        toast(self, f"{len(rows)} قطعه به لیست خرید اضافه شد")

    def print_labels(self):
        rows = self.table.selected_rows()
        if not rows:
            toast(self, "قطعه‌هایی را که برچسب می‌خواهند انتخاب کنید")
            return
        from labels import LabelDialog
        from ..theme import FONT_FAMILY
        import ui.theme as th
        LabelDialog(self, self.db, [self.db.get_part(r["id"]) for r in rows], th.FONT_FAMILY).exec()

    def merge_selected(self):
        rows = self.table.selected_rows()
        if len(rows) != 2:
            return
        from ..widgets import BaseDialog
        from PySide6.QtWidgets import QRadioButton
        d = BaseDialog(self, "ادغام دو قطعه", "کدام پارت نامبر بماند؟ قطعه‌ی دیگر در آن ادغام و حذف می‌شود؛ "
                       "موجودی‌ها جمع و محل‌ها، تاریخچه، BOM و لیست خرید منتقل می‌شود.", 520)
        radios = []
        for r in rows:
            p = self.db.get_part(r["id"])
            locs = "، ".join(l["code"] for l in self.db.part_locations(p["id"])) or "بدون محل"
            qty = "شمارش نشده" if p["needs_count"] else f"{p['quantity']} عدد"
            rb = QRadioButton(f"{p['part_number']}    ({qty}  ·  {locs})")
            rb.setLayoutDirection(Qt.LeftToRight)
            d.body.addWidget(rb)
            radios.append((rb, p["id"]))
        # پیش‌فرض: قطعه‌ای که لینک لیون یا موجودی دارد
        best = max(rows, key=lambda r: ("lionelectronic" in (r.get("purchase_link") or ""), r["quantity"]))
        for rb, pid in radios:
            rb.setChecked(pid == best["id"])
        d.add_buttons("ادغام", "انصراف", ok_icon="check")
        if d.exec():
            keep = next(pid for rb, pid in radios if rb.isChecked())
            drop = next(pid for rb, pid in radios if not rb.isChecked())
            self.db.merge_parts(drop, keep)
            self.app.data_changed()
            self.app.show_part(keep)
            toast(self, "دو قطعه ادغام شدند")

    def shelf_label(self):
        rows = self.table.selected_rows()
        if len(rows) > 3:
            toast(self, "برای لیبل قفسه حداکثر ۳ قطعه انتخاب کنید")
            return
        from labels import ShelfLabelDialog
        d = ShelfLabelDialog(self, self.db, [self.db.get_part(r["id"]) for r in rows])
        d.exec()
        if getattr(d, "saved_drawer", False):
            self.app.data_changed()

    def menu(self, pos):
        rows = self.table.selected_rows()
        if not rows:
            return
        m = QMenu(self)
        if len(rows) == 1:
            m.addAction(icon("plus", size=16), "ورود به انبار\t+", lambda: self.move(1))
            m.addAction(icon("minus", size=16), "خروج از انبار\t−", lambda: self.move(-1))
            m.addAction(icon("check", size=16), "اصلاح موجودی (شمارش)\t=", lambda: self.move(0))
            m.addAction(icon("edit", size=16), "ویرایش\tF2", self.edit)
            m.addSeparator()
            p = self.db.get_part(rows[0]["id"])
            if (p["purchase_link"] or "").startswith("http"):
                m.addAction(icon("external", size=16), "صفحه‌ی خرید", lambda: webbrowser.open(p["purchase_link"]))
            elif appinfo.lion_enabled(self.db):
                m.addAction(icon("external", size=16), "جستجو در لیون",
                            lambda: webbrowser.open(search_url(p["part_number"])))
            if p["datasheet"]:
                m.addAction(icon("file", size=16), "دیتاشیت", lambda: webbrowser.open(p["datasheet"]))
        if len(rows) == 2:
            m.addAction(icon("layers", size=16), "ادغام این دو قطعه…", self.merge_selected)
        m.addAction(icon("copy", size=16), "کپی پارت نامبر\tCtrl+C", self.copy_pn)
        m.addAction(icon("cart", size=16), "افزودن به لیست خرید\tCtrl+B", self.add_to_shopping)
        m.addAction(icon("qr", size=16), "چاپ برچسب\tCtrl+P", self.print_labels)
        if len(rows) <= 3:
            m.addAction(icon("tag", size=16), "لیبل قفسه\tCtrl+L", self.shelf_label)
        if appinfo.lion_enabled(self.db):
            m.addAction(icon("search", size=16), "یافتن معادل در لیون (مقاومت، خازن، …)",
                        lambda: self.app.match_passives([r["id"] for r in rows]))
            m.addAction(icon("sparkle", size=16), "دریافت اطلاعات و قیمت از لیون",
                        lambda: self.app.enrich([r["id"] for r in rows], update_price=True))
        m.addSeparator()
        m.addAction(icon("trash", color=Theme.c["danger"], size=16),
                    "حذف" + (f" ({len(rows)} مورد)" if len(rows) > 1 else "") + "\tDelete", self.delete)
        m.exec(pos)

    # ------------------------------------------------------------------ import
    def import_excel(self):
        path, _ = QFileDialog.getOpenFileName(self, "انتخاب فایل اکسل یا CSV", "",
                                              "Excel / CSV (*.xlsx *.xlsm *.csv *.txt)")
        if not path:
            return
        try:
            headers, rows = importer.read_table(path)
        except Exception as e:  # noqa: BLE001
            toast(self, f"خواندن فایل ناموفق بود: {e}")
            return
        if not headers:
            toast(self, "فایل خالی است")
            return
        guess = importer.guess_mapping(headers, importer.PART_FIELDS)
        d = ImportDialog(self, os.path.basename(path), headers, rows, importer.PART_FIELDS, guess,
                         options=[("exists", "اگر قطعه از قبل وجود دارد", [
                             ("add", "تعداد به موجودی اضافه شود"), ("set", "موجودی جایگزین شود"),
                             ("skip", "رد شود")])], title="ایمپورت قطعه‌ها از فایل")
        if not d.exec():
            return
        mp, mode = d.mapping, d.option_values["exists"]
        added = updated = skipped = 0
        cell = importer.cell
        for row in rows:
            pn = cell(row, mp, "part_number")
            if not pn:
                continue
            qty = importer.to_int(cell(row, mp, "quantity"), 0) if "quantity" in mp else 0
            existing = self.db.find_part(pn)
            if existing:
                if mode == "skip":
                    skipped += 1
                    continue
                change = qty if mode == "add" else qty - existing["quantity"]
                if change:
                    self.db.change_stock(existing["id"], change, "ایمپورت از فایل", "import", commit=False)
                upd = {}
                for k in ("description", "location", "package", "manufacturer", "purchase_link"):
                    v = cell(row, mp, k)
                    if v and not (existing[k] or ""):
                        upd[k] = v
                if upd:
                    self.db.update_part_fields(existing["id"], **upd)
                updated += 1
            else:
                self.db.save_part({
                    "part_number": pn, "description": cell(row, mp, "description"),
                    "location": cell(row, mp, "location"), "package": cell(row, mp, "package"),
                    "manufacturer": cell(row, mp, "manufacturer"), "purchase_link": cell(row, mp, "purchase_link"),
                    "min_quantity": importer.to_int(cell(row, mp, "min_quantity"), 0),
                    "unit_price": importer.to_float(cell(row, mp, "unit_price"), 0), "quantity": qty,
                    "category_id": None, "datasheet": ""})
                added += 1
        self.db.conn.commit()
        self.app.data_changed()
        toast(self, f"{added} قطعه‌ی جدید، {updated} به‌روزرسانی، {skipped} رد شد")
        if added:
            self.app.enrich(None, quiet=True)
