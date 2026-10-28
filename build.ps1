$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$python = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $python -or $python -like "*WindowsApps*") {
    $alt = Join-Path $env:LOCALAPPDATA "Python\bin\python.exe"
    if (Test-Path $alt) { $python = $alt }
}
if (-not $python -or -not (Test-Path $python)) {
    throw "没有找到可用的 Python。请先安装 Python 3.10+，并勾选 Add to PATH。"
}
& $python -c "import sys; print(sys.version)" | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Python 无法运行：$python" }

& $python -m pip install --disable-pip-version-check -r requirements-build.txt
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }

& $python -m PyInstaller `
    --noconfirm `
    --clean `
    --onedir `
    --windowed `
    --noupx `
    --name MouseBattery `
    --icon "assets/icon.ico" `
    --add-data "assets/icon.ico;assets" `
    --version-file "version_info.txt" `
    main.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed" }

$releaseDir = "release/鼠标电量"
if (Test-Path $releaseDir) { Remove-Item $releaseDir -Recurse -Force }
New-Item -ItemType Directory -Force $releaseDir | Out-Null
Copy-Item "dist/MouseBattery/*" $releaseDir -Recurse -Force
Move-Item "$releaseDir/MouseBattery.exe" "$releaseDir/鼠标电量.exe" -Force
Copy-Item "README.md", "LICENSE" $releaseDir -Force
Copy-Item "docs" "$releaseDir/docs" -Recurse -Force

$zip = "release/鼠标电量-v1.0.0-win64.zip"
Remove-Item $zip -ErrorAction SilentlyContinue
Compress-Archive -Path $releaseDir -DestinationPath $zip -Force

Get-Item "$releaseDir/鼠标电量.exe", $zip | Select-Object Name, Length, FullName
