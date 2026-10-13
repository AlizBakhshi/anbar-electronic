"""تنظیمات."""
import os
import shutil
from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QFileDialog, QFrame, QHBoxLayout, QLineEdit, QScrollArea, QVBoxLayout, QWidget

import appinfo
from db import DB_PATH
from ..dialogs import CategoryManagerDialog, ShortcutsDialog, create_starter_categories, line
from ..widgets import Button, Card, PageHeader, Segment, confirm, label, toast

INTERVALS = [("0", "خاموش"), ("15", "۱۵ دقیقه"), ("30", "۳۰ دقیقه"), ("60", "۱ ساعت"), ("180", "۳ ساعت")]


class SettingsPage(QWidget):
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
        root.setSpacing(14)
        root.addWidget(PageHeader("تنظیمات"))
        body.setMaximumWidth(780)

        # عمومی
        c = self.card(root, "نام کارگاه / انبار", "در بالای منو و عنوان پنجره نشان داده می‌شود.")
        row = QHBoxLayout()
        self.shop = line("", appinfo.APP_NAME)
        save = Button("ذخیره", "check", "Primary")
        save.clicked.connect(self.save_name)
        self.shop.returnPressed.connect(self.save_name)
        row.addWidget(self.shop, 1)
        row.addWidget(save)
        c.lay.addLayout(row)

        c = self.card(root, "ظاهر", "")
        self.theme = Segment([("system", "مطابق ویندوز"), ("light", "روشن"), ("dark", "تیره")],
                             self.db.get_setting("theme", "system"))
        self.theme.changed.connect(self.app.set_theme)
        c.lay.addWidget(self.theme, 0, alignment=Qt.AlignRight)

        # دسته‌بندی
        c = self.card(root, "دسته‌بندی قطعه‌ها",
                      "دسته‌ها و زیردسته‌های خودتان را بسازید. اگر اتصال لیون روشن باشد، دسته‌های سایت لیون هم خودکار اضافه می‌شوند.")
        self.cat_info = label("", "Muted")
        c.lay.addWidget(self.cat_info)
        row = QHBoxLayout()
        b = Button("مدیریت دسته‌بندی‌ها", "layers", "Primary")
        b.clicked.connect(self.manage_categories)
        row.addWidget(b)
        self.starter_btn = Button("افزودن دسته‌های پایه", "plus", tip="مقاومت، خازن، دیود، ترانزیستور، آی‌سی، …")
        self.starter_btn.clicked.connect(self.add_starter)
        row.addWidget(self.starter_btn)
        row.addStretch(1)
        c.lay.addLayout(row)

        # لیون (اختیاری)
        c = self.card(root, "اتصال به لیون الکترونیک (اختیاری)",
                      "اگر از lionelectronic.ir خرید می‌کنید: سفارش‌ها خودکار خوانده می‌شوند، و دسته، سازنده، پکیج، دیتاشیت، "
                      "عکس و قیمت قطعه‌ها از سایت تکمیل می‌شود. بدون آن، برنامه کامل کار می‌کند.")
        self.lion_on = QCheckBox("استفاده از لیون الکترونیک")
        self.lion_on.toggled.connect(self.toggle_lion)
        c.lay.addWidget(self.lion_on)
        self.lion_box = QWidget()
        lb = QVBoxLayout(self.lion_box)
        lb.setContentsMargins(0, 8, 0, 0)
        lb.setSpacing(10)
        lb.addWidget(label("حساب کاربری (برای خواندن سفارش‌ها و سبد خرید) — فقط روی همین کامپیوتر ذخیره می‌شود.", "StatTitle"))
        self.user = line("", "نام کاربری", ltr=True)
        self.pwd = line("", "رمز عبور", ltr=True)
        self.pwd.setEchoMode(QLineEdit.Password)
        show = Button("", "eye", "Icon", tip="نمایش رمز")
        show.clicked.connect(lambda: self.pwd.setEchoMode(
            QLineEdit.Normal if self.pwd.echoMode() == QLineEdit.Password else QLineEdit.Password))
        save = Button("ذخیره", "check", "Primary")
        save.clicked.connect(self.save_account)
        row = QHBoxLayout()
        row.setSpacing(10)
        row.addWidget(self.user, 1)
        row.addWidget(self.pwd, 1)
        row.addWidget(show)
        row.addWidget(save)
        lb.addLayout(row)
        lb.addWidget(label("بررسی خودکار سفارش‌های جدید — ورود به انبار همیشه با تأیید شماست.", "StatTitle"))
        self.interval = Segment(INTERVALS, self.db.get_setting("auto_minutes", "30"))
        self.interval.changed.connect(self.save_interval)
        lb.addWidget(self.interval, 0, alignment=Qt.AlignRight)
        lb.addWidget(label("اطلاعات قطعه‌ها از سایت", "StatTitle"))
        row = QHBoxLayout()
        b1 = Button("به‌روزرسانی دسته‌بندی‌ها از سایت", "refresh")
        b1.clicked.connect(lambda: self.app.update_categories())
        b2 = Button("تکمیل اطلاعات قطعه‌های ناقص", "sparkle")
        b2.clicked.connect(lambda: self.app.enrich(None))
        b3 = Button("به‌روزرسانی همه + قیمت‌ها", "sparkle", tip="اطلاعات و قیمت ۱ عددِ همه‌ی قطعه‌ها از سایت لیون")
        b3.clicked.connect(lambda: self.app.enrich([p["id"] for p in self.db.list_parts()], update_price=True))
        for b in (b1, b2, b3):
            row.addWidget(b)
        row.addStretch(1)
        lb.addLayout(row)
        lb.addWidget(label("مقاومت، خازن، سلف، کریستال، LED و فیوزهای عمومی بر اساس مشخصات (مقدار، پکیج، تلرانس، "
                           "ولتاژ) با محصولات لیون تطبیق داده می‌شوند. تطابق دقیق خودکار وصل می‌شود؛ بقیه برای "
                           "بازبینی نمایش داده می‌شوند.", "Muted", wrap=True))
        row2 = QHBoxLayout()
        b4 = Button("تطبیق قطعه‌های عمومی با لیون", "sparkle")
        b4.clicked.connect(lambda: self.app.match_passives())
        b5 = Button("به‌روزرسانی کاتالوگ لیون و تطبیق", "refresh",
                    tip="کاتالوگ قیمت و موجودی پسیوهای لیون دوباره خوانده می‌شود (حدود ۱ دقیقه)")
        b5.clicked.connect(lambda: self.app.match_passives(refresh_catalog=True))
        row2.addWidget(b4)
        row2.addWidget(b5)
        row2.addStretch(1)
        lb.addLayout(row2)
        c.lay.addWidget(self.lion_box)

        # اطلاعات و پشتیبان
        c = self.card(root, "اطلاعات و پشتیبان‌گیری",
                      "همه‌ی اطلاعات (قطعه‌ها، قفسه‌ها، پروژه‌ها، تنظیمات) در یک فایل است. از آن نسخه بگیرید؛ "
                      "برای انتقال به کامپیوتر دیگر، پشتیبان را آنجا «بازگردانی» کنید.")
        self.path_lbl = label(os.path.dirname(DB_PATH), "Faint", wrap=True)
        self.path_lbl.setLayoutDirection(Qt.LeftToRight)
        self.path_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        c.lay.addWidget(self.path_lbl)
        row = QHBoxLayout()
        b = Button("تهیه‌ی نسخه‌ی پشتیبان", "download")
        b.clicked.connect(self.backup)
        r = Button("بازگردانی از پشتیبان", "upload")
        r.clicked.connect(self.restore)
        o = Button("باز کردن پوشه‌ی اطلاعات", "folder")
        o.clicked.connect(lambda: os.startfile(os.path.dirname(DB_PATH)) if hasattr(os, "startfile") else None)
        row.addWidget(b)
        row.addWidget(r)
        row.addWidget(o)
        row.addStretch(1)
        c.lay.addLayout(row)

        c = self.card(root, "راهنما", "")
        row = QHBoxLayout()
        b = Button("میانبرهای صفحه‌کلید", "keyboard", tip="F1")
        b.clicked.connect(lambda: ShortcutsDialog(self).exec())
        w = Button("راه‌اندازی اولیه", "sparkle", tip="دوباره نمایش پنجره‌ی خوش‌آمد")
        w.clicked.connect(self.app.welcome)
        row.addWidget(b)
        row.addWidget(w)
        row.addStretch(1)
        c.lay.addLayout(row)
        c.lay.addWidget(label(f"{appinfo.APP_NAME} — نسخه‌ی {appinfo.VERSION}", "Faint"))
        root.addStretch(1)
        self.load_values()

    def card(self, root, title, sub):
        c = Card(padding=18)
        c.lay.setSpacing(8)
        c.lay.addWidget(label(title, "H2"))
        if sub:
            c.lay.addWidget(label(sub, "Muted", wrap=True))
        c.lay.addSpacing(4)
        root.addWidget(c)
        return c

    def load_values(self):
        self.shop.setText(self.db.get_setting("shop_name"))
        self.theme.set(self.db.get_setting("theme", "system"))
        self.user.setText(self.db.get_setting("lion_user"))
        self.pwd.setText(self.db.get_setting("lion_pass"))
        self.interval.set(self.db.get_setting("auto_minutes", "30"))
        self.lion_on.blockSignals(True)
        self.lion_on.setChecked(appinfo.lion_enabled(self.db))
        self.lion_on.blockSignals(False)
        self.lion_box.setVisible(self.lion_on.isChecked())

    def refresh(self):
        cats = self.db.categories()
        parts = self.db.list_parts()
        with_cat = sum(1 for p in parts if p["category_id"] in cats)
        self.cat_info.setText(f"{len(cats)} دسته   ·   {with_cat} از {len(parts)} قطعه دسته‌بندی شده")
        self.starter_btn.setVisible(not cats)

    def save_name(self):
        self.db.set_setting("shop_name", self.shop.text().strip())
        self.app.apply_branding()
        toast(self, "ذخیره شد")

    def manage_categories(self):
        CategoryManagerDialog(self, self.db).exec()
        self.app.data_changed()

    def add_starter(self):
        create_starter_categories(self.db)
        self.app.data_changed()
        toast(self, "دسته‌های پایه اضافه شد — در «مدیریت دسته‌بندی‌ها» قابل ویرایش است")

    def toggle_lion(self, on):
        self.db.set_setting("lion_enabled", "1" if on else "0")
        self.lion_box.setVisible(on)
        self.app.apply_lion_visibility()
        toast(self, "اتصال به لیون روشن شد — نام کاربری و رمز را وارد کنید" if on else "اتصال به لیون خاموش شد")
        if on and not self.db.categories():
            self.app.update_categories(quiet=True)

    def save_account(self):
        self.db.set_setting("lion_user", self.user.text().strip())
        self.db.set_setting("lion_pass", self.pwd.text())
        toast(self, "اطلاعات حساب ذخیره شد")

    def save_interval(self, v):
        self.db.set_setting("auto_minutes", v)
        self.app.schedule_auto_sync()
        toast(self, "ذخیره شد")

    def backup(self):
        path, _ = QFileDialog.getSaveFileName(self, "ذخیره‌ی پشتیبان", f"warehouse_backup_{datetime.now():%Y%m%d_%H%M}.db",
                                              "SQLite (*.db)")
        if path:
            self.db.conn.commit()
            self.db.conn.execute("PRAGMA wal_checkpoint(FULL)")
            shutil.copyfile(DB_PATH, path)
            toast(self, "نسخه‌ی پشتیبان ذخیره شد")

    def restore(self):
        path, _ = QFileDialog.getOpenFileName(self, "انتخاب فایل پشتیبان", "", "SQLite (*.db)")
        if path and confirm(self, "بازگردانی", "همه‌ی اطلاعات فعلی با این فایل جایگزین می‌شود و برنامه بسته می‌شود. ادامه؟",
                            "بازگردانی", True):
            self.db.close()
            shutil.copyfile(path, DB_PATH)
            for ext in ("-wal", "-shm"):
                try:
                    os.remove(DB_PATH + ext)
                except OSError:
                    pass
            self.app.close()
