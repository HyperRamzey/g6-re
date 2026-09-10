@echo off
rem Register the patched G6 ASIO driver (sample-based latency) for ALL ASIO hosts.
rem
rem Nuendo/Cubase enumerate ASIO drivers ONLY from HKLM\SOFTWARE\ASIO (proven by
rem disassembly of baios.dll: RegOpenKeyW(HKEY_LOCAL_MACHINE, "SOFTWARE\ASIO")).
rem The COM class itself stays per-user in HKCU\Software\Classes\CLSID\{8F5E2A31-...}
rem - Steinberg hosts resolve CLSIDs through HKCR, which merges per-user classes,
rem   and the CLSID validator only checks that the InprocServer32 DLL file exists.
rem
rem The patched DLL is NOT a system file - the stock Creative ASIO driver stays
rem registered and untouched. Uninstall = run unregister_hklm.cmd (or delete the
rem HKLM key) + delete the two HKCU keys from patch_asio.py's install steps.
rem
rem Run as: right-click -> Run as administrator

setlocal
set "KEY=HKLM\SOFTWARE\ASIO\G6 ASIO (sample-based patch)"
set "CLSID={8F5E2A31-6C74-4B9E-9D3A-2E7F5A6B8C90}"

net session >nul 2>&1
if errorlevel 1 (
    echo ERROR: please run this script as Administrator.
    exit /b 1
)

echo Checking patched DLL registration (per-user COM class)...
reg query "HKCU\Software\Classes\CLSID\%CLSID%\InprocServer32" /ve >nul 2>&1
if errorlevel 1 (
    echo ERROR: per-user COM class not found. Run the patch_asio.py install steps first:
    echo   reg add "HKCU\Software\Classes\CLSID\%CLSID%" /ve /d "CAsio Class (G6 sample-latency patch)" /f
    echo   reg add "HKCU\Software\Classes\CLSID\%CLSID%\InprocServer32" /ve /d "<full path to CtUsAs64_patched.dll>" /f
    echo   reg add "HKCU\Software\Classes\CLSID\%CLSID%\InprocServer32" /v ThreadingModel /d "Apartment" /f
    exit /b 1
)
rem reg query /ve output line looks like:
rem     (Default)    REG_SZ    C:\path\CtUsAs64_patched.dll
rem The value line is matched via REG_SZ (the key header line contains no
rem REG_SZ token, so tokens=2,* yields the DLL path only on the value line).
for /f "tokens=2,*" %%A in ('reg query "HKCU\Software\Classes\CLSID\%CLSID%\InprocServer32" /ve 2^>nul ^| findstr /c:"REG_SZ"') do set "DLL=%%B"
if not defined DLL (
    echo ERROR: could not read InprocServer32 value - per-user COM class incomplete.
    exit /b 1
)
if not exist "%DLL%" (
    echo ERROR: patched DLL not found at "%DLL%" - fix the per-user registration first.
    exit /b 1
)
echo OK: %DLL%

echo Adding HKLM enumeration entry (what Nuendo/Cubase read)...
reg add "%KEY%" /ve /d "G6 sample-based ASIO" /f
reg add "%KEY%" /v CLSID /d "%CLSID%" /f
reg add "%KEY%" /v Description /d "Creative Sound Blaster ASIO (sample latency patch)" /f
if errorlevel 1 (
    echo ERROR: failed to write HKLM key.
    exit /b 1
)

echo.
echo Done. Full registration:
reg query "%KEY%" /s
echo.
echo The driver should now appear in Nuendo: Studio -^> Audio Connections -^> Audio System -^>
echo "G6 ASIO (sample-based patch)". Restart Nuendo if it was running.
endlocal
