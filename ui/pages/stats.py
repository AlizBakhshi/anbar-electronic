"""صفحه‌ی آمار."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QScrollArea, QVBoxLayout, QWidget

from ..charts import HBarList, MonthlyBarChart
from ..widgets import Card, PageHeader, Segment, StatCard, first_part, fmt_compact, fmt_int, label


class StatsPage(QWidget):
    def __init__(self, app):
        super().__init__()
        self.app, self.db = app, app.db
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        outer.addWidget(scroll)
        body = QWidget()
        body.setObjectName("ScrollBody")
        scroll.setWidget(body)
        root = QVBoxLayout(body)
        root.setContentsMargins(0, 0, 8, 0)
        root.setSpacing(16)
        root.addWidget(PageHeader("آمار", "نمای کلی انبار و خریدها"))

        grid = QGridLayout()
        grid.setSpacing(12)
        self.k_parts = StatCard("اقلام انبار", "box")
        self.k_value = StatCard("ارزش انبار", "tag", "success")
        self.k_low = StatCard("کم‌موجود / ناموجود", "alert", "danger")
        self.k_spent = StatCard("خرید از لیون", "cart", "warning")
        for i, w in enumerate((self.k_parts, self.k_value, self.k_low, self.k_spent)):
            grid.addWidget(w, 0, i)
        root.addLayout(grid)

        # خرید ماهانه
        c = Card(padding=18)
        h = QHBoxLayout()
        tl = QVBoxLayout()
        tl.setSpacing(2)
        self.month_title = label("خرید ماهانه", "H2")
        tl.addWidget(self.month_title)
        self.month_sub = label("", "Muted")
        tl.addWidget(self.month_sub)
        h.addLayout(tl, 1)
        self.range = Segment([("6", "۶ ماه"), ("12", "۱۲ ماه"), ("24", "۲۴ ماه")], "12")
        self.range.changed.connect(lambda _: self.refresh())
        h.addWidget(self.range, 0, Qt.AlignTop)
        c.lay.addLayout(h)
        c.lay.addSpacing(10)
        self.month_chart = MonthlyBarChart(unit="تومان")
        c.lay.addWidget(self.month_chart)
        root.addWidget(c)

        row = QHBoxLayout()
        row.setSpacing(12)
        c1 = Card(padding=18)
        c1.lay.addWidget(label("ارزش موجودی به تفکیک دسته", "H2"))
        c1.lay.addWidget(label("تومان — دسته‌های اصلی", "Muted"))
        c1.lay.addSpacing(8)
        self.cat_chart = HBarList(unit="تومان")
        c1.lay.addWidget(self.cat_chart)
        c1.lay.addStretch(1)
        row.addWidget(c1, 1)
        c2 = Card(padding=18)
        c2.lay.addWidget(label("پرمصرف‌ترین قطعه‌ها", "H2"))
        c2.lay.addWidget(label("خروج از انبار در ۱۲ ماه گذشته (عدد)", "Muted"))
        c2.lay.addSpacing(8)
        self.used_chart = HBarList(value_fmt=lambda v: f"{fmt_int(v)} عدد", unit="عدد")
        c2.lay.addWidget(self.used_chart)
        c2.lay.addStretch(1)
        row.addWidget(c2, 1)
        root.addLayout(row)

        c3 = Card(padding=18)
        c3.lay.addWidget(label("باارزش‌ترین موجودی‌ها", "H2"))
        c3.lay.addWidget(label("موجودی × قیمت واحد", "Muted"))
        c3.lay.addSpacing(8)
        self.value_chart = HBarList(unit="تومان")
        c3.lay.addWidget(self.value_chart)
        root.addWidget(c3)
        root.addStretch(1)

    def refresh(self):
        import appinfo
        lion = appinfo.lion_enabled(self.db)
        s = self.db.stats()
        n_orders, spent = self.db.order_totals()
        inn, out = self.db.movement_since(30)
        self.k_parts.set(fmt_int(s["n"]), f"{fmt_int(s['qty'])} عدد قطعه")
        self.k_value.set(fmt_compact(s["value"] / 10), "تومان")
        self.k_low.set(f"{fmt_int(s['low'])} / {fmt_int(s['empty'])}", "زیر حداقل / موجودی صفر")
        months = int(self.range.value)
        if lion:
            self.k_spent.title_lbl.setText("خرید از لیون")
            self.k_spent.set(fmt_compact(spent / 10), f"تومان در {fmt_int(n_orders)} سفارش")
            self.month_title.setText("خرید ماهانه از لیون")
            data = [(k, v / 10) for k, v in self.db.monthly_purchases(months)]  # ریال -> تومان
        else:
            data = [(k, v / 10) for k, v in self.db.monthly_inflow(months)]
            self.k_spent.title_lbl.setText("ورودی ۳۰ روز اخیر")
            self.k_spent.set(fmt_int(inn), "عدد قطعه وارد انبار شده")
            self.month_title.setText("ارزش ورودی ماهانه به انبار")
        self.month_chart.set_data(data)
        total = sum(v for _, v in data)
        self.month_sub.setText(f"جمع {months} ماه اخیر: {fmt_int(total)} تومان   ·   در ۳۰ روز اخیر "
                               f"{fmt_int(inn)} عدد ورود و {fmt_int(out)} عدد خروج")
        cats = self.db.value_by_top_category()
        top = cats[:8]
        if len(cats) > 8:
            top.append(("سایر", sum(v for _, v, _ in cats[8:]), sum(n for _, _, n in cats[8:])))
        self.cat_chart.set_data([(name, v / 10, f"{n} قلم") for name, v, n in top if v > 0])
        self.used_chart.set_data([(r["part_number"], r["used"], first_part(r["description"]))
                                  for r in self.db.top_consumed()])
        self.value_chart.set_data([(r["part_number"], r["value"] / 10,
                                    f"{fmt_int(r['quantity'])} عدد × {fmt_int((r['unit_price'] or 0) / 10)} تومان")
                                   for r in self.db.top_value() if r["value"] > 0])
