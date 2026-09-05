# LockLift

LockLift is a Windows file and folder unlocker that finds processes holding a path and releases them safely. It also supports monitoring, force actions, scheduled operations, and a File Explorer context-menu action.

## Features

- Unlock files, folders, and drives from File Explorer.
- Scan lock owners with Sysinternals Handle.
- Skip protected Windows processes and system identities.
- Monitor a path for new and released locks.
- Force unlock, rename, move, delete, or schedule an operation for reboot.
- Silent command-line mode for Explorer and automation.
- Per-user Explorer integration, so setup does not require machine-wide registry changes.

## File Explorer integration

On first launch, LockLift asks whether to add `Unlock with File Unlocker` to the context menu for files, folders, and drives. The choice is saved in `settings.json`. The integration can also be managed from a terminal:

```powershell
LockLift.exe --register-explorer
LockLift.exe --unregister-explorer
LockLift.exe --silent "C:\path\to\locked-file.ext"
```

The integration uses the current user's registry hive and does not overwrite system-wide Explorer settings.

## Build

Run `build_release.ps1` from this directory. The build bundles the application, `handle.exe`, the application icon, and the complete `assets` directory into `dist\LockLift.exe`, then creates `release\LockLift-windows.zip`.

The included Handle utility is from Microsoft Sysinternals and remains subject to its own license terms. Keep its accompanying license information with distributed releases as required.
