"""پروژه‌ها و BOM: موجودی کافی؟ کمبودها؟ ساخت برد و کسر از انبار."""
import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCompleter, QFileDialog, QHBoxLayout, QMenu, QPlainTextEdit, QSplitter, QVBoxLayout,
                               QWidget)

import importer
from ..dialogs import PartSearchInput, FormDialog, ImportDialog, line, spin
from ..theme import icon
from ..widgets import (Button, Card, Col, DataTable, PageHeader, confirm, first_part, fmt_int, fmt_money, label,
                       shortcut, toast)


def bom_status(r):
    if not r.get("part_id"):
        return ("در انبار تعریف نشده", "muted")
    short = r["need"] - (r["stock"] or 0)
    if short > 0:
        return (f"کمبود {fmt_int(short)}", "danger")
    return ("کافی", "success")


class ProjectsPage(QWidget):
    def __init__(self, app):
        super().__init__()
        self.app, self.db = app, app.db
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(14)
        header = PageHeader("پروژه‌ها و BOM", "لیست قطعات هر برد؛ کمبودها را ببینید و با ساخت، از انبار کسر کنید")
        b_new = Button("پروژه‌ی جدید", "plus", "Primary")
        b_new.clicked.connect(self.new_project)
        header.add(b_new)
        root.addWidget(header)

        split = QSplitter(Qt.Horizontal)
        split.setChildrenCollapsible(False)
        split.setHandleWidth(12)

        left = Card()
        left.lay.setContentsMargins(1, 4, 1, 1)
        self.projects = DataTable([Col("name", "پروژه", 160, stretch=True),
                                   Col("item_count", "اقلام", 60, "center", "int")],
                                  multi=False, empty_text="هنوز پروژه‌ای نساخته‌اید")
        self.projects.selection_changed.connect(self.show_project)
        self.projects.activated_row.connect(lambda r: self.edit_project())
        self.projects.context_menu.connect(self.project_menu)
        left.lay.addWidget(self.projects)
        left.setMinimumWidth(190)
        split.addWidget(left)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(12)
        top = QHBoxLayout()
        tl = QVBoxLayout()
        tl.setSpacing(2)
        self.p_title = label("یک پروژه را انتخاب کنید", "H2")
        self.p_desc = label("", "Muted", wrap=True)
        tl.addWidget(self.p_title)
        tl.addWidget(self.p_desc)
        top.addLayout(tl, 1)
        top.addWidget(label("تعداد برد:", "Muted"))
        self.boards = spin(1, 10000, 1)
        self.boards.setFixedWidth(90)
        self.boards.valueChanged.connect(self.show_bom)
        top.addWidget(self.boards)
        rl.addLayout(top)

        pills = QHBoxLayout()
        pills.setSpacing(6)
        self.pill_items = label("", "Pill")
        self.pill_short = label("", "PillDanger")
        self.pill_ok = label("", "PillSuccess")
        self.pill_cost = label("", "Pill")
        for p in (self.pill_items, self.pill_ok, self.pill_short, self.pill_cost):
            pills.addWidget(p)
        pills.addStretch(1)
        rl.addLayout(pills)

        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.actions = []
        for text, ic, kind, fn, tip in [
            ("افزودن", "plus", None, self.add_item, "افزودن قطعه به BOM (Enter)"),
            ("ایمپورت", "upload", None, self.import_bom, "ایمپورت BOM از اکسل/CSV (Ctrl+I)"),
            ("کمبودها → خرید", "cart", None, self.shortages_to_shopping, "افزودن کمبودها به لیست خرید"),
            ("ساخت برد", "wrench", "Primary", self.build, "کسر قطعه‌های BOM از انبار")]:
            b = Button(text, ic, kind, tip)
            b.clicked.connect(fn)
            bar.addWidget(b)
            self.actions.append(b)
        bar.addStretch(1)
        rm = Button("", "trash", "Danger", "حذف ردیف (Delete)")
        rm.clicked.connect(self.remove_items)
        bar.addWidget(rm)
        self.actions.append(rm)
        rl.addLayout(bar)

        cols = [Col("part_number", "پارت نامبر", 180),
                Col("desc", "توضیحات", 240, stretch=True),
                Col("quantity", "در هر برد", 80, "center", "int"),
                Col("need", "لازم", 70, "center", "int", hide=3),
                Col("stock", "موجودی", 75, "center", "int"),
                Col("status", "وضعیت", 150, "center", pill=bom_status),
                Col("unit_price", "قیمت واحد (ریال)", 110, "center", "money", hide=4),
                Col("line_total", "جمع (ریال)", 120, "center", "money"),
                Col("location", "محل", 90, hide=2),
                Col("designators", "مرجع‌ها", 140, hide=1)]
        self.bom = DataTable(cols, lambda r, k: "muted" if k in ("location", "designators") else None,
                             empty_text="BOM خالی است — «افزودن قطعه» یا «ایمپورت BOM»")
        self.bom.activated_row.connect(self.edit_item)
        self.bom.context_menu.connect(self.bom_menu)
        c = Card()
        c.lay.setContentsMargins(1, 4, 1, 1)
        c.lay.addWidget(self.bom)
        rl.addWidget(c, 1)
        split.addWidget(right)
        split.setSizes([260, 900])
        root.addWidget(split, 1)
        shortcut(self, "Ctrl+I", self.import_bom)
        self.project = None

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Return, Qt.Key_Enter) and not e.modifiers():
            self.add_item()
        elif e.key() == Qt.Key_Delete:
            self.remove_items() if self.bom.hasFocus() else self.delete_project()
        else:
            super().keyPressEvent(e)

    # ------------------------------------------------------------------ projects
    def refresh(self):
        self.projects.set_rows(self.db.list_projects())
        if not self.projects.selected_rows():
            self.projects.select_first()
        self.show_project()

    def show_project(self):
        rows = self.projects.selected_rows()
        self.project = self.db.q1("SELECT * FROM projects WHERE id=?", (rows[0]["id"],)) if rows else None
        for b in self.actions:
            b.setEnabled(self.project is not None)
        self.boards.setEnabled(self.project is not None)
        if not self.project:
            self.p_title.setText("یک پروژه را انتخاب کنید" if self.projects.model_.rows else "اولین پروژه را بسازید")
            self.p_desc.setText("")
            self.bom.set_rows([])
            for p in (self.pill_items, self.pill_short, self.pill_ok, self.pill_cost):
                p.hide()
            return
        self.p_title.setText(self.project["name"])
        self.p_desc.setText(self.project["description"] or "")
        self.p_desc.setVisible(bool(self.project["description"]))
        self.show_bom()

    def show_bom(self):
        if not self.project:
            return
        n = self.boards.value()
        rows, short, ok, cost = [], 0, 0, 0.0
        for b in self.db.bom(self.project["id"]):
            r = dict(b)
            r["desc"] = first_part(b["part_desc"])
            r["need"] = b["quantity"] * n
            r["stock"] = b["stock"] if b["part_id"] else 0
            r["unit_price"] = b["unit_price"] or 0
            r["line_total"] = r["unit_price"] * r["need"]   # برای تعداد بردِ انتخاب‌شده
            st = bom_status(r)[1]
            short += st != "success"
            ok += st == "success"
            cost += (b["unit_price"] or 0) * b["quantity"]
            rows.append(r)
        self.bom.set_rows(rows)
        self.pill_items.setText(f"{len(rows)} قلم")
        self.pill_ok.setText(f"کافی: {ok}")
        self.pill_short.setText(f"کمبود/ناموجود: {short}")
        no_price = sum(1 for r in rows if not r["unit_price"])
        self.pill_cost.setText(f"هزینه‌ی هر برد ≈ {fmt_money(cost)} ریال" +
                               (f"  ·  {n} برد ≈ {fmt_money(cost * n)} ریال" if n > 1 else "") +
                               (f"  ·  {no_price} قلم بدون قیمت" if no_price else ""))
        self.pill_items.show()
        self.pill_ok.setVisible(ok > 0)
        self.pill_short.setVisible(short > 0)
        self.pill_cost.setVisible(cost > 0)

    def _project_form(self, title, name="", desc=""):
        n = line(name, "مثلاً برد کنترلر موتور v2")
        d = QPlainTextEdit(desc)
        d.setFixedHeight(70)
        d.setPlaceholderText("توضیحات (اختیاری)")
        f = FormDialog(self, title, [("name", "نام پروژه", n), ("desc", "توضیحات", d)])
        f.validator = lambda v: "نام پروژه را بنویسید" if not v["name"] else None
        return f.values() if f.exec() else None

    def new_project(self):
        v = self._project_form("پروژه‌ی جدید")
        if v:
            pid = self.db.save_project(v["name"], v["desc"])
            self.app.data_changed()
            self.projects.select_ids({pid}, pid)

    def edit_project(self):
        if not self.project:
            return
        v = self._project_form("ویرایش پروژه", self.project["name"], self.project["description"] or "")
        if v:
            self.db.save_project(v["name"], v["desc"], self.project["id"])
            self.app.data_changed()

    def delete_project(self):
        if self.project and confirm(self, "حذف پروژه", f"پروژه‌ی «{self.project['name']}» و BOM آن حذف شود؟\n"
                                    "موجودی انبار تغییری نمی‌کند.", "حذف", True):
            self.db.delete_project(self.project["id"])
            self.app.data_changed()

    def project_menu(self, pos):
        if not self.project:
            return
        m = QMenu(self)
        m.addAction(icon("edit", size=16), "ویرایش", self.edit_project)
        m.addAction(icon("trash", size=16), "حذف پروژه", self.delete_project)
        m.exec(pos)

    # ------------------------------------------------------------------ BOM
    def _pn_input(self, text=""):
        return PartSearchInput(self.db, text, "پارت نامبر یا بخشی از توضیحات (از انبار یا جدید)")

    def add_item(self):
        if not self.project:
            return
        f = FormDialog(self, "افزودن قطعه به BOM", [
            ("pn", "پارت نامبر", self._pn_input()),
            ("qty", "تعداد در هر برد", spin(1, 100000, 1)),
            ("des", "مرجع‌ها (اختیاری)", line("", "مثلاً R1, R2, R5"))])
        f.validator = lambda v: "پارت نامبر را بنویسید" if not v["pn"] else None
        if f.exec():
            v = f.values()
            self.db.add_bom_item(self.project["id"], v["pn"], v["qty"], v["des"])
            self.app.data_changed()

    def edit_item(self, row):
        f = FormDialog(self, "ویرایش ردیف BOM", [
            ("pn", "پارت نامبر", self._pn_input(row["part_number"])),
            ("qty", "تعداد در هر برد", spin(row["quantity"], 100000, 1)),
            ("des", "مرجع‌ها", line(row["designators"] or ""))])
        if f.exec():
            v = f.values()
            self.db.update_bom_item(row["id"], part_number=v["pn"], quantity=v["qty"], designators=v["des"])
            self.app.data_changed()

    def remove_items(self):
        rows = self.bom.selected_rows()
        if rows and confirm(self, "حذف از BOM", f"{len(rows)} ردیف از BOM حذف شود؟", "حذف", True):
            self.db.delete_bom_items([r["id"] for r in rows])
            self.app.data_changed()

    def bom_menu(self, pos):
        rows = self.bom.selected_rows()
        if not rows:
            return
        m = QMenu(self)
        if len(rows) == 1:
            m.addAction(icon("edit", size=16), "ویرایش ردیف", lambda: self.edit_item(rows[0]))
            if rows[0].get("part_id"):
                m.addAction(icon("box", size=16), "نمایش در انبار", lambda: self.app.show_part(rows[0]["part_id"]))
        m.addAction(icon("cart", size=16), "افزودن به لیست خرید", lambda: self.shortages_to_shopping(rows))
        m.addSeparator()
        m.addAction(icon("trash", size=16), "حذف\tDelete", self.remove_items)
        m.exec(pos)

    def import_bom(self):
        if not self.project:
            return
        path, _ = QFileDialog.getOpenFileName(self, "فایل BOM (اکسل یا CSV)", "", "BOM (*.xlsx *.xlsm *.csv *.txt)")
        if not path:
            return
        try:
            headers, rows = importer.read_table(path)
        except Exception as e:  # noqa: BLE001
            toast(self, f"خواندن فایل ناموفق بود: {e}")
            return
        guess = importer.guess_mapping(headers, importer.BOM_FIELDS)
        d = ImportDialog(self, os.path.basename(path), headers, rows, importer.BOM_FIELDS, guess,
                         title=f"ایمپورت BOM به «{self.project['name']}»")
        if not d.exec():
            return
        mp, n = d.mapping, 0
        for row in rows:
            pn = importer.cell(row, mp, "part_number")
            if not pn:
                continue
            des = importer.cell(row, mp, "designators")
            qty = importer.to_int(importer.cell(row, mp, "quantity"), 0) if "quantity" in mp else 0
            qty = qty or importer.count_designators(des) or 1
            self.db.add_bom_item(self.project["id"], pn, qty, des, importer.cell(row, mp, "note"))
            n += 1
        self.app.data_changed()
        toast(self, f"{n} ردیف به BOM اضافه شد")

    def shortages_to_shopping(self, rows=None):
        rows = rows if isinstance(rows, list) else self.bom.model_.rows
        n = 0
        for r in rows:
            short = r["need"] - (r["stock"] or 0)
            if short > 0:
                self.db.add_shopping(r["part_number"], short, f"پروژه {self.project['name']}")
                n += 1
        self.app.data_changed()
        toast(self, f"{n} قلم به لیست خرید اضافه شد" if n else "کمبودی وجود ندارد")

    def build(self):
        if not self.project:
            return
        n = self.boards.value()
        rows = self.bom.model_.rows
        short = [r for r in rows if bom_status(r)[1] != "success"]
        msg = f"برای ساخت {n} عدد «{self.project['name']}»، قطعه‌های BOM از انبار کسر شود؟"
        if short:
            msg += f"\n\n⚠ {len(short)} قلم کمبود دارد یا در انبار تعریف نشده؛ موجودی آن‌ها ممکن است منفی شود."
        if confirm(self, "ساخت و کسر از انبار", msg, "کسر از انبار", danger=bool(short)):
            self.db.build_project(self.project["id"], n)
            self.app.data_changed()
            toast(self, f"قطعه‌های {n} برد از انبار کسر شد")
