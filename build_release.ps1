$ErrorActionPreference = "Stop"

$pyinstaller_command = Get-Command pyinstaller.exe -ErrorAction SilentlyContinue
if ($pyinstaller_command) {
	$pyinstaller_path = $pyinstaller_command.Source
} elseif (Test-Path ".venv\Scripts\pyinstaller.exe") {
	$pyinstaller_path = (Resolve-Path ".venv\Scripts\pyinstaller.exe").Path
}
if (-not $pyinstaller_path) {
	throw "PyInstaller was not found. Install requirements.txt, then run this script again."
}

& $pyinstaller_path --clean --noconfirm LockLift.spec

$release = Join-Path $PWD "release"
New-Item -ItemType Directory -Force -Path $release | Out-Null
$zip = Join-Path $release "LockLift-windows.zip"
if (Test-Path $zip) { Remove-Item $zip -Force }
$package = Join-Path $release "LockLift"
if (Test-Path $package) { Remove-Item $package -Recurse -Force }
New-Item -ItemType Directory -Force -Path $package | Out-Null
Copy-Item "dist\LockLift.exe" $package
Copy-Item "THIRD_PARTY_NOTICES.txt" $package
Compress-Archive -Path "$package\*" -DestinationPath $zip
Remove-Item $package -Recurse -Force
Write-Host "Created $zip"
