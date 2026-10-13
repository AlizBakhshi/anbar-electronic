# ساخت نسخه‌ی exe:  pyinstaller --noconfirm AnbarElectronic.spec
# خروجی در dist\AnbarElectronic\ ؛ برای ساخت نصب‌کننده installer.iss را با Inno Setup کامپایل کنید.

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=[("app.ico", ".")],
    hiddenimports=["lxml", "lxml.etree", "bs4", "openpyxl", "qrcode", "jdatetime", "PIL.Image"],
    excludes=["tkinter", "matplotlib", "numpy", "pandas", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
              "PySide6.Qt3DCore", "PySide6.QtQuick", "PySide6.QtQml", "PySide6.QtMultimedia", "PySide6.QtCharts",
              "PySide6.QtDataVisualization", "PySide6.QtPdf", "PySide6.QtBluetooth", "PySide6.QtNetwork",
              "PySide6.QtOpenGL", "PySide6.QtSql", "PySide6.QtLocation", "PySide6.QtPositioning", "win32com"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AnbarElectronic",
    icon="app.ico",
    console=False,
    version=None,
)
coll = COLLECT(exe, a.binaries, a.datas, name="AnbarElectronic")
