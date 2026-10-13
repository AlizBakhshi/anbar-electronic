"""انبار الکترونیک — نقطه‌ی شروع برنامه (PySide6)."""
import os
import sys

from PySide6.QtCore import QByteArray, QSize, Qt, QTimer
from PySide6.QtGui import QGuiApplication, QIcon
from PySide6.QtWidgets import (QApplication, QFrame, QHBoxLayout, QLabel, QMainWindow, QPushButton, QStackedWidget,
                               QVBoxLayout, QWidget)

import appinfo
from db import Database, ORDER_IGNORED
from ui import theme as th
from ui.dialogs import CaptchaDialog, NewOrdersDialog, ShortcutsDialog, WelcomeDialog
from ui.pages.history import HistoryPage
from ui.pages.orders import OrdersPage
from ui.pages.parts import PartsPage
from ui.pages.projects import ProjectsPage
from ui.pages.settings import SettingsPage
from ui.pages.shopping import ShoppingPage
from ui.pages.storage import StoragePage
from ui.pages.stats import StatsPage
from ui.widgets import info, label, shortcut, toast
from ui.workers import CategoriesWorker, EnrichWorker, SyncWorker

NAV = [("parts", "انبار قطعات", "box"), ("storage", "قفسه‌ها", "archive"), ("orders", "سفارش‌های لیون", "inbox"), ("projects", "پروژه‌ها و BOM", "layers"),
       ("shopping", "لیست خرید", "cart"), ("stats", "آمار", "chart"), ("history", "ورود و خروج", "history"),
       ("settings", "تنظیمات", "settings")]


class NavButton(QPushButton):
    """دکمه‌ی منو: آیکون، متن و نشان شمارنده با چیدمان راست‌به‌چپ."""

    def __init__(self, text, icon_name):
        super().__init__()
        self.setObjectName("NavButton")
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.icon_name = icon_name
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 0, 10, 0)
        lay.setSpacing(10)
        self.ico = QLabel()
        self.ico.setFixedSize(18, 18)
        self.ico.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.txt = QLabel(text)
        self.txt.setObjectName("NavText")
        self.txt.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.badge = QLabel("")
        self.badge.setObjectName("NavBadge")
        self.badge.setAlignment(Qt.AlignCenter)
        self.badge.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.badge.hide()
        lay.addWidget(self.ico)
        lay.addWidget(self.txt, 1)
        lay.addWidget(self.badge)
        self.toggled.connect(lambda _: self.refresh_icon())
        self.refresh_icon()

    def refresh_icon(self):
        on = self.isChecked()
        self.ico.setPixmap(th.icon(self.icon_name, color=th.Theme.c["accent_text" if on else "muted"]).pixmap(18, 18))
        self.txt.setProperty("active", on)
        self.txt.style().unpolish(self.txt)
        self.txt.style().polish(self.txt)

    def set_badge(self, n):
        self.badge.setText(str(n) if n < 1000 else "999+")
        self.badge.setVisible(bool(n))


class MainWindow(QMainWindow):
    def __init__(self, db):
        super().__init__()
        self.db = db
        self.setWindowTitle(appinfo.shop_name(db))
        self.setMinimumSize(1100, 680)
        self.sync_worker = None
        self.enrich_worker = None
        self.cat_worker = None

        root = QWidget()
        root.setObjectName("Root")
        self.setCentralWidget(root)
        h = QHBoxLayout(root)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)

        side = QFrame()
        side.setObjectName("Sidebar")
        side.setFixedWidth(232)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(14, 22, 14, 14)
        sl.setSpacing(4)
        brand = QHBoxLayout()
        self.logo = QLabel()
        self.logo.setFixedSize(36, 36)
        self.logo.setAlignment(Qt.AlignCenter)
        bt = QVBoxLayout()
        bt.setSpacing(0)
        self.brand = label(appinfo.shop_name(db), "Brand")
        self.brand.setWordWrap(True)
        bt.addWidget(self.brand)
        bt.addWidget(label("مدیریت قطعات الکترونیک", "BrandSub"))
        brand.addWidget(self.logo)
        brand.addLayout(bt, 1)
        sl.addLayout(brand)
        sl.addSpacing(22)
        self.nav = {}
        for i, (key, text, ic) in enumerate(NAV):
            b = NavButton(text, ic)
            b.setToolTip(f"Ctrl+{i + 1}")
            b.clicked.connect(lambda _=False, k=key: self.show_page(k))
            sl.addWidget(b)
            self.nav[key] = b
        sl.addStretch(1)
        self.side_status = label("", "SideFooter", wrap=True)
        sl.addWidget(self.side_status)
        sl.addSpacing(6)
        row = QHBoxLayout()
        row.setSpacing(6)
        self.theme_btn = QPushButton()
        self.theme_btn.setObjectName("Ghost")
        self.theme_btn.setCursor(Qt.PointingHandCursor)
        self.theme_btn.setToolTip("تغییر تم (Ctrl+Shift+L)")
        self.theme_btn.clicked.connect(self.toggle_theme)
        keys = QPushButton()
        keys.setObjectName("Ghost")
        keys.setCursor(Qt.PointingHandCursor)
        keys.setToolTip("میانبرهای صفحه‌کلید (F1)")
        keys.clicked.connect(self.show_shortcuts)
        self.keys_btn = keys
        row.addWidget(self.theme_btn, 1)
        row.addWidget(keys)
        sl.addLayout(row)
        h.addWidget(side)

        self.stack = QStackedWidget()
        wrap = QWidget()
        wl = QVBoxLayout(wrap)
        wl.setContentsMargins(28, 24, 28, 20)
        wl.addWidget(self.stack)
        h.addWidget(wrap, 1)

        self.pages = {"parts": PartsPage(self), "storage": StoragePage(self), "orders": OrdersPage(self), "projects": ProjectsPage(self),
                      "shopping": ShoppingPage(self), "stats": StatsPage(self), "history": HistoryPage(self),
                      "settings": SettingsPage(self)}
        for p in self.pages.values():
            self.stack.addWidget(p)
        self.dirty = set(self.pages)
        self.current = None

        for i, (key, _, _) in enumerate(NAV):
            shortcut(self, f"Ctrl+{i + 1}", lambda k=key: self.show_page(k), Qt.ApplicationShortcut)
        shortcut(self, "F5", lambda: self.start_sync(), Qt.ApplicationShortcut)
        shortcut(self, "F1", self.show_shortcuts, Qt.ApplicationShortcut)
        shortcut(self, "Ctrl+Shift+L", self.toggle_theme, Qt.ApplicationShortcut)
        shortcut(self, "Ctrl+F", self.focus_search, Qt.ApplicationShortcut)

        th.Theme.listeners.append(self.refresh_chrome)
        self.refresh_chrome()
        self.auto_timer = QTimer(self)
        self.auto_timer.timeout.connect(lambda: self.start_sync(silent=True))
        self.apply_lion_visibility()
        last = self.db.get_setting("last_page", "parts")
        self.show_page(last if last in self.pages else "parts")
        self.update_badges()
        geo = self.db.get_setting("geometry")
        if geo:
            self.restoreGeometry(QByteArray.fromBase64(geo.encode()))
        else:
            self.resize(1360, 820)
        QTimer.singleShot(1500, self.first_run_tasks)

    # ------------------------------------------------------------------ chrome
    def refresh_chrome(self):
        dark = th.Theme.is_dark()
        self.theme_btn.setIcon(th.icon("sun" if dark else "moon", "muted"))
        self.theme_btn.setText("  تم روشن" if dark else "  تم تیره")
        self.keys_btn.setIcon(th.icon("keyboard", "muted"))
        self.logo.setPixmap(th.icon("box", color="#ffffff", size=20).pixmap(20, 20))
        self.logo.setStyleSheet(f"background:{th.Theme.c['accent']}; border-radius:10px;")
        for b in self.nav.values():
            b.refresh_icon()
        th.set_dark_titlebar(self, dark)
        page = self.pages.get(self.current)
        if page:
            page.update()
            self.dirty = set(self.pages)
            self.refresh_page(self.current)

    # ------------------------------------------------------------------ branding / optional Lion
    def apply_branding(self):
        name = appinfo.shop_name(self.db)
        self.brand.setText(name)
        self.setWindowTitle(name)

    def lion_on(self):
        return appinfo.lion_enabled(self.db)

    def apply_lion_visibility(self):
        """صفحه‌ی سفارش‌های لیون و کارهای خودکار لیون فقط وقتی اتصال لیون روشن است."""
        on = self.lion_on()
        self.nav["orders"].setVisible(on)
        if not on and self.current == "orders":
            self.show_page("parts")
        self.schedule_auto_sync()
        self.dirty = set(self.pages)
        if self.current:
            self.refresh_page(self.current)

    def show_page(self, key):
        if key == "orders" and not self.lion_on():
            key = "parts"
        self.current = key
        for k, b in self.nav.items():
            b.setChecked(k == key)
        page = self.pages[key]
        self.stack.setCurrentWidget(page)
        if key in self.dirty:
            self.refresh_page(key)
        self.db.set_setting("last_page", key)

    def refresh_page(self, key):
        self.pages[key].refresh()
        self.dirty.discard(key)

    def data_changed(self):
        self.dirty = set(self.pages)
        self.refresh_page(self.current)
        self.update_badges()

    def update_badges(self):
        self.nav["orders"].set_badge(self.db.pending_orders() if self.lion_on() else 0)
        self.nav["shopping"].set_badge(self.db.q1("SELECT COUNT(*) FROM shopping")[0])

    def show_part(self, part_id):
        page = self.pages["parts"]
        page.search.clear()
        page.seg.set("all")
        page.stock_filter = "all"
        page.cat_filter = "all"
        self.show_page("parts")
        page.refresh()
        page.table.select_ids({part_id}, part_id)
        page.table.scrollTo(page.table.currentIndex())
        page.table.setFocus()

    def show_drawer(self, drawer_id):
        self.show_page("storage")
        self.pages["storage"].select_drawer(drawer_id)

    def focus_search(self):
        page = self.pages[self.current]
        if hasattr(page, "search"):
            page.search.setFocus()
            page.search.selectAll()

    def show_shortcuts(self):
        ShortcutsDialog(self).exec()

    # ------------------------------------------------------------------ theme
    def set_theme(self, mode):
        self.db.set_setting("theme", mode)
        resolved = mode if mode != "system" else ("dark" if th.system_prefers_dark() else "light")
        th.apply_theme(QApplication.instance(), resolved)

    def toggle_theme(self):
        mode = "light" if th.Theme.is_dark() else "dark"
        self.pages["settings"].theme.set(mode)
        self.set_theme(mode)

    # ------------------------------------------------------------------ lion sync
    def schedule_auto_sync(self):
        try:
            minutes = int(self.db.get_setting("auto_minutes", "30") or 0)
        except ValueError:
            minutes = 0
        self.auto_timer.stop()
        if minutes > 0 and self.lion_on():
            self.auto_timer.start(minutes * 60_000)

    def first_run_tasks(self):
        if self.db.get_setting("setup_done") != "1":
            self.welcome()
        if not self.lion_on():
            return
        if not self.db.categories():
            self.update_categories(quiet=True, then_enrich=True)
        elif self.db.parts_to_enrich():
            self.enrich(None, quiet=True)
        if self.auto_timer.isActive() and self.db.get_setting("lion_user"):
            QTimer.singleShot(4000, lambda: self.start_sync(silent=True))

    def set_status(self, text):
        self.side_status.setText(text)
        self.pages["orders"].status.setText(text)

    def welcome(self):
        """راه‌اندازی اولیه: نام کارگاه، تم، لیون (اختیاری) و ساخت اولین قفسه."""
        d = WelcomeDialog(self, self.db)
        d.exec()
        self.db.set_setting("setup_done", "1")
        self.apply_branding()
        self.pages["settings"].load_values()
        self.apply_lion_visibility()
        self.data_changed()
        if getattr(d, "make_cabinet", False):
            self.show_page("storage")
            self.pages["storage"].add_cabinet()

    def start_sync(self, silent=False):
        if not self.lion_on():
            if not silent:
                toast(self, "اتصال به لیون خاموش است — در تنظیمات روشنش کنید")
            return
        if self.sync_worker and self.sync_worker.isRunning():
            return
        user, pwd = self.db.get_setting("lion_user"), self.db.get_setting("lion_pass")
        if not user or not pwd:
            if not silent:
                toast(self, "ابتدا نام کاربری و رمز لیون را در تنظیمات وارد کنید")
                self.show_page("settings")
            return
        if not silent:
            self.show_page("orders")
        self.pages["orders"].set_syncing(True, "در حال اتصال به lionelectronic.ir…")
        w = SyncWorker(user, pwd, silent)
        w.log.connect(self.set_status)
        w.need_captcha.connect(self.on_captcha)
        w.done.connect(self.on_sync_done)
        self.sync_worker = w
        w.start()

    def on_captcha(self, img):
        d = CaptchaDialog(self, img)
        self.sync_worker.provide_captcha(d.code.text().strip() if d.exec() else "")

    def on_sync_done(self, new_ids, error, silent):
        from datetime import datetime
        self.pages["orders"].set_syncing(False)
        self.data_changed()
        if error:
            self.set_status(error)
            if not silent:
                info(self, "خطا", error)
            return
        self.set_status(f"آخرین بررسی سفارش‌ها: {datetime.now():%H:%M}" +
                        (f" — {len(new_ids)} سفارش جدید" if new_ids else ""))
        if not new_ids:
            if not silent:
                toast(self, "سفارش جدیدی وجود ندارد")
            return
        if silent:
            toast(self, f"{len(new_ids)} سفارش جدید از لیون دریافت شد — در صفحه‌ی سفارش‌ها تصمیم بگیرید")
            QApplication.alert(self)
            return
        orders = [o for o in self.db.list_orders() if o["id"] in new_ids]
        d = NewOrdersDialog(self, orders)
        if d.exec() and d.result_data:
            chosen, ignored = d.result_data
            for i in ignored:
                self.db.set_order_state(i, ORDER_IGNORED)
            touched = []
            for i in chosen:
                touched += self.db.add_order_to_stock(i)
            self.data_changed()
            if chosen:
                toast(self, f"{len(chosen)} سفارش ({len(touched)} قلم) وارد انبار شد")
                self.enrich(list(set(touched)), quiet=True)

    # ------------------------------------------------------------------ enrichment
    def enrich(self, part_ids=None, quiet=False, update_price=False):
        if not self.lion_on():
            if not quiet:
                toast(self, "تکمیل اطلاعات از لیون فقط با روشن بودن اتصال لیون (تنظیمات) کار می‌کند")
            return
        if self.enrich_worker and self.enrich_worker.isRunning():
            if not quiet:
                toast(self, "تکمیل اطلاعات در حال انجام است…")
            return
        w = EnrichWorker(part_ids, update_price=update_price)
        w.progress.connect(lambda d, t: self.side_status.setText(f"تکمیل اطلاعات قطعه‌ها از لیون: {d} از {t}") if t else None)
        w.done.connect(lambda n, err: self.on_enrich_done(n, err, quiet))
        self.enrich_worker = w
        w.start()

    def on_enrich_done(self, n, err, quiet):
        self.side_status.setText("")
        self.data_changed()
        if err:
            if not quiet:
                info(self, "خطا", f"ارتباط با سایت لیون ناموفق بود:\n{err}")
        elif n and (not quiet or n > 1):
            toast(self, f"اطلاعات {n} قطعه از سایت لیون تکمیل شد")
        elif not quiet:
            toast(self, "قطعه‌ای برای تکمیل پیدا نشد")

    def match_passives(self, part_ids=None, refresh_catalog=False):
        """مقاومت/خازن/… عمومی را با محصولات لیون تطبیق می‌دهد."""
        from ui.workers import PassiveMatchWorker
        if not self.lion_on():
            toast(self, "اتصال به لیون خاموش است — در تنظیمات روشنش کنید")
            return
        if getattr(self, "match_worker", None) and self.match_worker.isRunning():
            toast(self, "تطبیق در حال انجام است…")
            return
        w = PassiveMatchWorker(part_ids, refresh_catalog)
        w.progress.connect(lambda i, n, m: self.side_status.setText(m))
        w.done.connect(self.on_match_done)
        self.match_worker = w
        toast(self, "تطبیق قطعه‌های عمومی با لیون شروع شد…")
        w.start()

    def on_match_done(self, applied, review, error):
        from ui.match_review import MatchReviewDialog
        import passive_match as pm
        self.side_status.setText("")
        self.data_changed()
        if error:
            info(self, "خطا", f"تطبیق ناموفق بود:\n{error}")
            return
        if not review:
            toast(self, f"{applied} قطعه به لیون وصل شد" if applied else "قطعه‌ی عمومیِ بدون لینکی نماند")
            return
        d = MatchReviewDialog(self, review, applied)
        if d.exec() and d.chosen:
            for pid, it in d.chosen:
                pm.apply_match(self.db, pid, it)
            self.data_changed()
            toast(self, f"{applied + len(d.chosen)} قطعه به لیون وصل شد")
        elif applied:
            toast(self, f"{applied} قطعه به لیون وصل شد")

    def update_categories(self, quiet=False, then_enrich=False):
        if not self.lion_on():
            return
        w = CategoriesWorker()
        self.side_status.setText("دریافت دسته‌بندی‌ها از لیون…")

        def done(n, err):
            self.side_status.setText("")
            self.db._cat_cache = None
            self.data_changed()
            if err and not quiet:
                info(self, "خطا", err)
            elif not quiet:
                toast(self, f"{n} دسته‌بندی به‌روز شد")
            if then_enrich and not err:
                self.enrich(None, quiet=True)
        w.done.connect(done)
        self.cat_worker = w
        w.start()

    def closeEvent(self, e):
        self.db.set_setting("geometry", bytes(self.saveGeometry().toBase64()).decode())
        super().closeEvent(e)


APP_ID = appinfo.APP_ID   # باید با میانبر نصب‌کننده / create_shortcut.py یکی باشد
ICON_PATH = appinfo.resource("app.ico")


def main():
    if sys.platform == "win32":
        # تا ویندوز برنامه را «انبار الکترونیک» بشناسد (نه Python) و آیکون تسک‌بار درست باشد
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
        except Exception:  # noqa: BLE001
            pass
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName(appinfo.APP_NAME)
    app.setLayoutDirection(Qt.RightToLeft)
    th.setup_font(app)
    db = Database()
    mode = db.get_setting("theme", "system")
    resolved = mode if mode != "system" else ("dark" if th.system_prefers_dark() else "light")
    th.apply_theme(app, resolved)
    app.setWindowIcon(QIcon(ICON_PATH) if os.path.exists(ICON_PATH) else QIcon(th.pixmap("box", "#2563eb", 64)))
    win = MainWindow(db)

    def on_scheme():
        if db.get_setting("theme", "system") == "system":
            win.set_theme("system")
    try:
        app.styleHints().colorSchemeChanged.connect(lambda _: on_scheme())
    except AttributeError:
        pass
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
