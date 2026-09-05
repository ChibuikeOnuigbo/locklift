$ErrorActionPreference = "Stop"

python -m pip install -r requirements.txt
python -m PyInstaller --clean --noconfirm LockLift.spec

$release = Join-Path $PWD "release"
New-Item -ItemType Directory -Force -Path $release | Out-Null
$zip = Join-Path $release "LockLift-windows.zip"
if (Test-Path $zip) { Remove-Item $zip -Force }
Compress-Archive -Path "dist\LockLift.exe" -DestinationPath $zip
Write-Host "Created $zip"
