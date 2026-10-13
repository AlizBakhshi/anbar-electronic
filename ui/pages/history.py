"""تاریخچه‌ی ورود و خروج."""
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from db import to_jalali
from ..widgets import Card, Col, DataTable, PageHeader, SearchBox, Segment, first_part, label

SOURCES = {"manual": "دستی", "lion": "سفارش لیون", "project": "ساخت پروژه", "import": "ایمپورت"}


class HistoryPage(QWidget):
    def __init__(self, app):
        super().__init__()
        self.app, self.db = app, app.db
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(14)
        root.addWidget(PageHeader("ورود و خروج", "همه‌ی تغییرات موجودی انبار"))
        bar = QHBoxLayout()
        self.search = SearchBox("جستجوی پارت نامبر، توضیح، پروژه…")
        self.search.setFixedWidth(320)
        self.search.changed.connect(self.apply_filter)
        self.seg = Segment([("all", "همه"), ("in", "ورود"), ("out", "خروج")])
        self.seg.changed.connect(lambda _: self.apply_filter())
        self.count = label("", "Muted")
        bar.addWidget(self.search)
        bar.addWidget(self.seg)
        bar.addStretch(1)
        bar.addWidget(self.count)
        root.addLayout(bar)

        def style(row, key):
            if key == "qty_after" and row.get("qty_after") is not None and row["qty_after"] < 0:
                return "danger"
            if key in ("qty_before", "qty_after"):
                return None
            if key == "change_txt":
                return "success" if row["change"] > 0 else "danger"
            if key in ("date", "src"):
                return "muted"
            return None
        cols = [Col("date", "تاریخ", 140, "center"),
                Col("part_number", "پارت نامبر", 190),
                Col("kind", "نوع", 80, "center", pill=lambda r: ("ورود", "success") if r["change"] > 0 else ("خروج", "danger")),
                Col("qty_before", "موجودی قبل", 95, "center", "int"),
                Col("change_txt", "تغییر", 75, "center", fmt=lambda r: r["change_txt"]),
                Col("qty_after", "موجودی بعد", 95, "center", "int"),
                Col("reason", "توضیح", 240, hide=2),
                Col("src", "منبع", 110, "center", hide=1),
                Col("desc", "توضیحات قطعه", 200, stretch=True)]
        self.table = DataTable(cols, style, empty_text="هنوز ورود و خروجی ثبت نشده")
        self.table.activated_row.connect(lambda r: self.app.show_part(r["part_id"]))
        self.table.typed.connect(lambda ch: (self.search.setFocus(), self.search.setText(self.search.text() + ch)))
        c = Card()
        c.lay.setContentsMargins(1, 4, 1, 1)
        c.lay.addWidget(self.table)
        root.addWidget(c, 1)

    def refresh(self):
        rows = []
        for t in self.db.list_transactions():
            r = dict(t)
            r["date"] = to_jalali(t["created_at"])
            ch = t["change"]
            r["change_txt"] = f"+{ch}" if ch > 0 else f"−{abs(ch)}"
            r["src"] = SOURCES.get(t["source"], t["source"] or "")
            r["desc"] = first_part(t["description"])
            r["_hay"] = f"{t['part_number']} {t['reason'] or ''} {t['description'] or ''}".lower()
            rows.append(r)
        self.table.set_rows(rows)
        self.apply_filter()

    def apply_filter(self):
        q = self.search.text().strip().lower().split()
        mode = self.seg.value
        self.table.set_filter(lambda r: all(t in r["_hay"] for t in q) and
                              (mode == "all" or (mode == "in") == (r["change"] > 0)))
        self.count.setText(f"{self.table.visible_count()} رکورد")
