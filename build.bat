@echo off
rem ساخت exe و (اگر Inno Setup نصب باشد) نصب‌کننده
cd /d %~dp0
python -m pip install -r requirements.txt pyinstaller || goto :err
python -m PyInstaller --noconfirm AnbarElectronic.spec || goto :err
if not exist release mkdir release
powershell -NoProfile -Command "Compress-Archive -Force -Path 'dist\AnbarElectronic\*' -DestinationPath 'release\AnbarElectronic-portable.zip'"
set ISCC="%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist %ISCC% set ISCC="%LocalAppData%\Programs\Inno Setup 6\ISCC.exe"
if exist %ISCC% (
    %ISCC% installer.iss || goto :err
) else (
    echo Inno Setup 6 not found - only the portable zip was built. Install it from https://jrsoftware.org/isdl.php
)
echo.
echo Done. Output: release\
goto :eof
:err
echo Build failed.
exit /b 1
