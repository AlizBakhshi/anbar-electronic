"""ساخت میانبر «انبار الکترونیک» (برای اجرا از سورس؛ نسخه‌ی نصبی خودش میانبر می‌سازد) در منوی استارت و دسکتاپ (با آیکون و شناسه‌ی برنامه برای تسک‌بار).

اگر پوشه‌ی برنامه یا محل نصب پایتون عوض شد، دوباره اجرا کنید:
    python create_shortcut.py
"""
import os
import sys

import pythoncom
from win32com.propsys import propsys, pscon
from win32com.shell import shell, shellcon

HERE = os.path.dirname(os.path.abspath(__file__))
import appinfo

NAME = appinfo.APP_NAME
APP_ID = appinfo.APP_ID


def make(path):
    """میانبر با IShellLink (پشتیبانی کامل از نام فارسی) + شناسه‌ی برنامه برای تسک‌بار."""
    pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    link = pythoncom.CoCreateInstance(shell.CLSID_ShellLink, None, pythoncom.CLSCTX_INPROC_SERVER, shell.IID_IShellLink)
    link.SetPath(pythonw)
    link.SetArguments(f'"{os.path.join(HERE, "main.py")}"')
    link.SetWorkingDirectory(HERE)
    link.SetIconLocation(os.path.join(HERE, "app.ico"), 0)
    link.SetDescription("انبارداری و مدیریت قطعات الکترونیک")
    store = link.QueryInterface(propsys.IID_IPropertyStore)
    store.SetValue(pscon.PKEY_AppUserModel_ID, propsys.PROPVARIANTType(APP_ID, pythoncom.VT_LPWSTR))
    store.Commit()
    link.QueryInterface(pythoncom.IID_IPersistFile).Save(path, 0)
    return path


def folder(csidl):
    return shell.SHGetFolderPath(0, csidl, None, 0)


if __name__ == "__main__":
    start_menu = os.path.join(folder(shellcon.CSIDL_PROGRAMS), NAME + ".lnk")
    desktop = os.path.join(folder(shellcon.CSIDL_DESKTOPDIRECTORY), NAME + ".lnk")
    for p in (start_menu, desktop):
        print("ساخته شد:", make(p))
