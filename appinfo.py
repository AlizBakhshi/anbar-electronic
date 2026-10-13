"""نام برنامه، محل ذخیره‌ی اطلاعات و تنظیمات عمومی نسخه‌ی همگانی."""
import os
import sys

APP_NAME = "انبار الکترونیک"
APP_ID = "AnbarElectronic.App"      # شناسه‌ی ویندوز برای تسک‌بار (همان مقدار در نصب‌کننده)
DATA_FOLDER = "AnbarElectronic"
VERSION = "1.0.1"


def base_dir():
    """پوشه‌ی برنامه (کنار exe یا main.py)."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def resource(name):
    """فایل‌های همراه برنامه (آیکون و…) — در exe از پوشه‌ی بسته‌بندی خوانده می‌شوند."""
    root = getattr(sys, "_MEIPASS", None) or base_dir()
    return os.path.join(root, name)


def data_dir():
    """محل دیتابیس و عکس‌ها.
    حالت قابل‌حمل: اگر کنار برنامه فایل portable.txt یا warehouse.db باشد، همان‌جا.
    در غیر این صورت: %APPDATA%\\AnbarElectronic (هر کاربر ویندوز اطلاعات خودش را دارد)."""
    here = base_dir()
    if os.path.exists(os.path.join(here, "portable.txt")) or os.path.exists(os.path.join(here, "warehouse.db")):
        return here
    root = os.environ.get("APPDATA") or os.path.expanduser("~")
    d = os.path.join(root, DATA_FOLDER)
    os.makedirs(d, exist_ok=True)
    return d


def lion_enabled(db):
    """اتصال به لیون الکترونیک اختیاری است و پیش‌فرض خاموش."""
    return db.get_setting("lion_enabled", "0") == "1"


def shop_name(db):
    return db.get_setting("shop_name", "").strip() or APP_NAME
