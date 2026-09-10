@echo off
rem Remove the HKLM enumeration entry for the patched G6 ASIO driver.
rem (leaves the per-user COM class + HKCU\Software\ASIO entry alone - those are
rem  removed with the patch_asio.py install steps if you want a full uninstall;
rem  see docs/ASIO.md "Uninstall" for the complete list)
rem
rem Run as: right-click -> Run as administrator

net session >nul 2>&1
if errorlevel 1 (
    echo ERROR: please run this script as Administrator.
    exit /b 1
)

reg delete "HKLM\SOFTWARE\ASIO\G6 ASIO (sample-based patch)" /f
if errorlevel 1 (
    echo ERROR: failed to delete HKLM key ^(does not exist?^)
    exit /b 1
)
echo Removed HKLM\SOFTWARE\ASIO\G6 ASIO (sample-based patch)
