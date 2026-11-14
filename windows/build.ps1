# Build the standalone Windows program and SurveyCleaner-Setup-<version>.exe.
#
# Needs: Python 3.10+ and Inno Setup 6 (winget install JRSoftware.InnoSetup).
# Run from the repository root:   powershell -ExecutionPolicy Bypass -File windows\build.ps1
# Result: dist\SurveyCleaner-Setup-<version>.exe
#
# Builds in a short temporary folder, because Windows path-length limits can
# break the build inside deeply nested folders.

param(
    [string]$Python = "python",
    [string]$Iscc = ""
)
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$work = Join-Path $env:TEMP "scw"

if (-not $Iscc) {
    $candidates = @("$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
                    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
                    "$env:ProgramFiles\Inno Setup 6\ISCC.exe")
    $Iscc = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
    if (-not $Iscc) { throw "Inno Setup 6 not found. Install it with: winget install JRSoftware.InnoSetup" }
}

# Optional code signing: with a code-signing certificate in your Windows
# certificate store (or on its USB token), set SURVEYCLEAN_SIGN_THUMBPRINT to its
# thumbprint. Signing removes "Unknown publisher" and lets SmartScreen build
# trust in the app over time.
function Invoke-Sign([string]$File) {
    $thumb = $env:SURVEYCLEAN_SIGN_THUMBPRINT
    if (-not $thumb) { return }
    $signtool = Get-ChildItem "${env:ProgramFiles(x86)}\Windows Kits\10\bin\*\x64\signtool.exe" -ErrorAction SilentlyContinue |
        Sort-Object FullName -Descending | Select-Object -First 1
    if (-not $signtool) { throw "signtool.exe not found: install the Windows SDK (signing tools)." }
    $timestamp = if ($env:SURVEYCLEAN_TIMESTAMP_URL) { $env:SURVEYCLEAN_TIMESTAMP_URL } else { "http://timestamp.digicert.com" }
    & $signtool.FullName sign /sha1 $thumb /fd sha256 /tr $timestamp /td sha256 /d "Survey Cleaner" $File
    if ($LASTEXITCODE) { throw "Signing failed for $File" }
    & $signtool.FullName verify /pa $File | Out-Null
    if ($LASTEXITCODE) { throw "Signature check failed for $File" }
    Write-Host "Signed: $File"
}

$version = (Select-String -Path "$repo\surveyclean\__init__.py" -Pattern '__version__ = "([^"]+)"').Matches[0].Groups[1].Value
Write-Host "Building Survey Cleaner $version"

if (Test-Path $work) { Remove-Item -Recurse -Force $work }
New-Item -ItemType Directory -Force "$work\src" | Out-Null
Copy-Item "$repo\pyproject.toml", "$repo\README.md", "$repo\LICENSE" "$work\src"
Copy-Item "$repo\surveyclean" "$work\src" -Recurse
Copy-Item "$repo\windows" "$work\src" -Recurse
Get-ChildItem "$work\src" -Recurse -Directory -Filter __pycache__ | Remove-Item -Recurse -Force

# A clean virtual environment keeps the bundle to what the app needs.
& $Python -m venv "$work\venv"
$py = "$work\venv\Scripts\python.exe"
& $py -m pip install -q --upgrade pip
& $py -m pip install -q "$work\src" pyinstaller
if ($LASTEXITCODE) { throw "pip install failed" }

Push-Location "$work\src"
try {
    & $py -m PyInstaller --noconfirm --clean --windowed --onedir `
        --name "Survey Cleaner" `
        --icon "$work\src\surveyclean\assets\icon.ico" `
        --collect-data surveyclean `
        --collect-all pyreadstat --collect-all pyreadr `
        --hidden-import surveyclean.export `
        --distpath "$work\dist" --workpath "$work\build" --specpath "$work\build" `
        "windows\launcher.py"
    if ($LASTEXITCODE) { throw "PyInstaller failed" }

    # Check the bundled program really cleans data before packaging it.
    $report = "$work\selftest.txt"
    Start-Process -Wait -FilePath "$work\dist\Survey Cleaner\Survey Cleaner.exe" -ArgumentList "--selftest", "`"$report`""
    Get-Content $report | Write-Host
    if (-not (Select-String -Path $report -Pattern "SELFTEST EXIT 0" -Quiet)) { throw "Self-test of the bundled program failed" }

    Invoke-Sign "$work\dist\Survey Cleaner\Survey Cleaner.exe"
    & $Iscc /Q "/DAppVersion=$version" "/DSourceDir=$work\dist\Survey Cleaner" "/DOutputDir=$work\out" "windows\installer.iss"
    if ($LASTEXITCODE) { throw "Inno Setup failed" }
    Invoke-Sign "$work\out\SurveyCleaner-Setup-$version.exe"
} finally {
    Pop-Location
}

New-Item -ItemType Directory -Force "$repo\dist" | Out-Null
Copy-Item "$work\out\SurveyCleaner-Setup-$version.exe" "$repo\dist" -Force
# Same file under a fixed name: attach both to the release, and the README's
# "Download for Windows" button (releases/latest/download/SurveyCleaner-Setup.exe)
# always serves the newest version.
Copy-Item "$work\out\SurveyCleaner-Setup-$version.exe" "$repo\dist\SurveyCleaner-Setup.exe" -Force
Get-ChildItem "$repo\dist\SurveyCleaner-Setup-$version.exe", "$repo\dist\SurveyCleaner-Setup.exe" | ForEach-Object {
    Write-Host ("Installer: {0} ({1:N1} MB)" -f $_.FullName, ($_.Length / 1MB))
}
if (-not $env:SURVEYCLEAN_SIGN_THUMBPRINT) {
    Write-Host "Not code-signed (set SURVEYCLEAN_SIGN_THUMBPRINT to sign); Windows will show a SmartScreen warning."
}
