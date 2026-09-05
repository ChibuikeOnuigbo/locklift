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
It adds `Unlock with File Unlocker` and `Force Delete`.

## Command line

Review lock owners and pick which apps to close:

```powershell
LockLift.exe --unlock "C:\Work\old.zip"
```

Ask how to delete a file or folder:

```powershell
LockLift.exe --force-delete "C:\Work\old.zip"
```

The app asks for Recycle Bin or Permanent Delete.
It then shows the apps that use the path.

Close all safe lock owners without a window:

```powershell
LockLift.exe --silent "C:\Work\old.zip"
```

Add or remove the File Explorer item:

```powershell
LockLift.exe --register-explorer
LockLift.exe --unregister-explorer
```

## Delete after restart

For a path that cannot be changed now, use the Force Actions tab.
Pick Delete, then check Schedule operation for next reboot.
LockLift uses Windows to run the delete after the next restart.

To run LockLift at each boot, use Task Scheduler:

1. Open Task Scheduler.
2. Click Create Task.
3. Set the trigger to At startup.
4. Set the action to start `LockLift.exe`.
5. Check Run with highest privileges.

## Download

Get the latest Windows build from the
[LockLift releases page](https://github.com/ChibuikeOnuigbo/locklift/releases).

Use `LockLift.exe` for a quick start.
Use the ZIP when you also want the license note.

## Build

Run this from the project folder:

```powershell
.\build_release.ps1
```

The build makes `dist\LockLift.exe` and
`release\LockLift-windows.zip`.

The app uses Handle from Microsoft Sysinternals.
See `THIRD_PARTY_NOTICES.txt` for its license.
