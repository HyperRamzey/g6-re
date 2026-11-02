# build.ps1 - build the VST2 insert plugin with mingw64 gcc.
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File plugin\build.ps1
#
# The plugin is a plain C DLL with no C++ runtime and no MSVC dependency, so
# `-static-libgcc` is enough to make it portable to any VST2 host.
#
# The numerical flags are a contract, not tuning: -ffp-contract=off keeps the
# compiler from fusing multiply-adds, which would break bit-exactness against
# the reference render. g6ct.c itself refuses to build under -ffast-math.

param(
    [string]$Out = "g6ct.dll"
)

$ErrorActionPreference = "Stop"

$gcc = "C:\ProgramData\mingw64\mingw64\bin\gcc.exe"
if (-not (Test-Path $gcc)) {
    $cmd = Get-Command gcc -ErrorAction SilentlyContinue
    if (-not $cmd) { throw "gcc not found (expected $gcc)" }
    $gcc = $cmd.Source
}

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$up = Join-Path $here "..\upstream"

$argsList = @(
    "-O2", "-std=c11", "-Wall", "-Wextra", "-Wno-main",
    "-ffp-contract=off", "-fno-fast-math",
    "-DG6CT_DOUBLE",
    "-shared", "-static-libgcc",
    "-I$up",
    "-o", (Join-Path $here $Out),
    (Join-Path $here "g6ct_vst.c"),
    (Join-Path $up "g6ct.c"),
    "-lm", "-lgdi32", "-luser32"
)

& $gcc @argsList
if ($LASTEXITCODE -ne 0) { throw "gcc failed with exit code $LASTEXITCODE" }

$dll = Join-Path $here $Out
$item = Get-Item $dll
"built {0}  {1} bytes" -f $item.FullName, $item.Length

$objdump = "C:\ProgramData\mingw64\mingw64\bin\objdump.exe"
if (Test-Path $objdump) {
    & $objdump -p $dll |
        Select-String -Pattern "^\s*\[\s*\d+\].*(VSTPluginMain|main)$" |
        ForEach-Object { "  export: " + $_.Line.Trim() }
}
