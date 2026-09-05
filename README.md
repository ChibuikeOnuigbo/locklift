# LockLift

LockLift helps you free files and folders that are in use.
It can find the app that holds a file, then stop that app.

## What it can do

- Free files, folders, and drives from File Explorer.
- Find apps that hold a file.
- Skip key Windows apps.
- Watch a file for new locks.
- Stop locks before a move, copy, or delete.
- Move, rename, or delete a locked path.
- Run from a command line.

## Use it

1. Start LockLift.
2. Pick a file or folder.
3. Click Scan.
4. Pick a lock in the list.
5. Click Unlock.

On first start, LockLift asks to add this item to File Explorer:
`Unlock with File Unlocker`.

This works for files, folders, and drives. The choice is saved for your user.

## Command line

Free one path without the main window:

```powershell
LockLift.exe --silent "C:\Work\old.zip"
```

Add or remove the File Explorer item:

```powershell
LockLift.exe --register-explorer
LockLift.exe --unregister-explorer
```

## Build

Run this from the project folder:

```powershell
.\build_release.ps1
```

The build makes `dist\LockLift.exe` and
`release\LockLift-windows.zip`.

The app uses Handle from Microsoft Sysinternals.
See `THIRD_PARTY_NOTICES.txt` for its license.
