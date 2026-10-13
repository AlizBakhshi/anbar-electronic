"""بازبینی تطابق‌های غیردقیق قطعه‌های عمومی با محصولات لیون."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QHBoxLayout, QHeaderView, QTableWidget,
                               QTableWidgetItem, QWidget)

from .widgets import BaseDialog, Button, label


def _cand_text(it, note):
    price = f"{int(it['price']):,} ریال" if it.get("price") else "بدون قیمت"
    stock = "" if it.get("stock") is None else ("  ·  ناموجود" if it["stock"] <= 0 else f"  ·  موجودی {it['stock']:,}")
    return f"{it['pn']}  ·  {price}  ·  حداقل {it.get('moq') or 1}{stock}" + (f"  ·  {note}" if note else "")


class MatchReviewDialog(BaseDialog):
    """rows: [{"part_id", "part_number", "status", "cands": [(item, exact, note)]}]"""

    def __init__(self, parent, rows, applied):
        sub = (f"{applied} قطعه تطابق دقیق داشتند و خودکار به لیون وصل شدند. "
               "موارد زیر را بررسی کنید؛ پیشنهاد اول ارزان‌ترین گزینه‌ی سازگار است.")
        super().__init__(parent, "تطبیق قطعه‌های عمومی با لیون", sub, 1080)
        self.rows = rows
        t = QTableWidget(len(rows), 4)
        t.setHorizontalHeaderLabels(["", "قطعه‌ی شما", "معادل پیشنهادی در لیون", "وضعیت"])
        t.verticalHeader().setVisible(False)
        t.setSelectionMode(QAbstractItemView.NoSelection)
        t.setEditTriggers(QAbstractItemView.NoEditTriggers)
        t.setShowGrid(False)
        t.verticalHeader().setDefaultSectionSize(40)
        h = t.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.Fixed)
        t.setColumnWidth(0, 40)
        h.setSectionResizeMode(1, QHeaderView.Interactive)
        t.setColumnWidth(1, 260)
        h.setSectionResizeMode(2, QHeaderView.Stretch)
        h.setSectionResizeMode(3, QHeaderView.Fixed)
        t.setColumnWidth(3, 110)
        t.setMinimumHeight(min(520, 44 * len(rows) + 44))
        self.checks, self.combos = [], []
        for i, r in enumerate(rows):
            chk = QCheckBox()
            box = QWidget()
            bl = QHBoxLayout(box)
            bl.setContentsMargins(10, 0, 0, 0)
            bl.addWidget(chk)
            t.setCellWidget(i, 0, box)
            pn = QTableWidgetItem(r["part_number"])
            pn.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            t.setItem(i, 1, pn)
            if r["cands"]:
                cb = QComboBox()
                cb.setLayoutDirection(Qt.LeftToRight)
                for it, exact, note in r["cands"][:25]:
                    cb.addItem(_cand_text(it, note), it)
                    cb.setItemData(cb.count() - 1, it.get("desc", ""), Qt.ToolTipRole)
                t.setCellWidget(i, 2, cb)
                cb.currentIndexChanged.connect(lambda _=0, c=chk: c.setChecked(True))
            else:
                chk.setEnabled(False)
                na = QTableWidgetItem("معادلی در لیون پیدا نشد")
                na.setForeground(Qt.gray)
                t.setItem(i, 2, na)
                cb = None
            st = QTableWidgetItem({"compatible": "سازگار", "none": "ندارد"}.get(r["status"], r["status"]))
            st.setTextAlignment(Qt.AlignCenter)
            t.setItem(i, 3, st)
            self.checks.append(chk)
            self.combos.append(cb)
        self.body.addWidget(t)
        tools = QHBoxLayout()
        a = Button("انتخاب همه")
        n = Button("هیچ‌کدام")
        for b, v in ((a, True), (n, False)):
            b.setAutoDefault(False)
            b.clicked.connect(lambda _=False, v=v: [c.setChecked(v) for c in self.checks if c.isEnabled()])
            tools.addWidget(b)
        tools.addStretch(1)
        tools.addWidget(label("نام قطعه‌های شما عوض نمی‌شود؛ فقط لینک، قیمت، عکس و پارت نامبر لیون اضافه می‌شود.", "Faint"))
        self.body.addLayout(tools)
        self.add_buttons("وصل کردن انتخاب‌شده‌ها", "بستن", ok_icon="check")
        self.chosen = []

    def on_ok(self):
        self.chosen = [(r["part_id"], cb.currentData()) for r, chk, cb in zip(self.rows, self.checks, self.combos)
                       if cb is not None and chk.isChecked()]
        self.accept()
