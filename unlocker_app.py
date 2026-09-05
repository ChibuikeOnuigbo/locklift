import sys
import os
import ctypes
import win32file
import winreg
import psutil
import time
import json
import shutil
import csv
import logging
import re
import subprocess
from datetime import datetime
import winsound
from ctypes import wintypes

from PyQt6.QtCore import (
    Qt, QThread, pyqtSignal, QTimer, QSize, QPropertyAnimation, QEasingCurve,
    QPoint, QParallelAnimationGroup, QSequentialAnimationGroup, QRect
)
from PyQt6.QtGui import (
    QFont, QIcon, QColor, QPalette, QPainter, QLinearGradient, QBrush,
    QPixmap, QMovie, QGuiApplication, QPen, QPainterPath
)
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QTabWidget, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QLineEdit, QTableWidget, QTableWidgetItem,
    QHeaderView, QProgressBar, QFileDialog, QDialog, QCheckBox, QTextEdit,
    QComboBox, QStatusBar, QGraphicsOpacityEffect, QFrame, QSizePolicy,
    QGraphicsDropShadowEffect, QGroupBox, QButtonGroup, QRadioButton,
    QGridLayout, QGraphicsBlurEffect, QScrollArea, QMessageBox
)
APP_DATA_DIR = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "LockLift")
os.makedirs(APP_DATA_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(APP_DATA_DIR, "unlocker_debug.log"), encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("UnlockerApp")


def get_asset_path(filename):
    """Get absolute path to assets, works for dev and for PyInstaller"""
    base_path = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    assets_dir = os.path.join(base_path, "assets")
    path = os.path.join(assets_dir, filename)
    logger.debug(f"Asset path requested: {filename} -> {path}")
    return path


def is_admin():
    try:
        result = ctypes.windll.shell32.IsUserAnAdmin()
        logger.debug(f"Admin check: {result}")
        return result
    except Exception as e:
        logger.error(f"Admin check failed: {e}")
        return False


def elevate_if_needed():
    logger.debug("Checking elevation status")
    if not is_admin():
        if "--elevated" not in sys.argv:
            logger.info("Elevation needed, restarting as admin")
            script = os.path.abspath(sys.argv[0])
            params = " ".join([f'"{arg}"' for arg in sys.argv[1:] + ["--elevated"]])
            try:
                ctypes.windll.shell32.ShellExecuteW(
                    None, "runas", sys.executable, f'"{script}" {params}', None, 1
                )
            except Exception as e:
                logger.error(f"Elevation failed: {e}")
            finally:
                logger.debug("Exiting non-admin process")
                sys.exit(0)  # Important: exit the non-admin process
        else:
            logger.debug("Already elevated")
            return True  # Already elevated
    else:
        logger.debug("Already admin")
        return True  # Already admin


def get_process_name(pid):
    try:
        process = psutil.Process(pid)
        name = process.name()
        logger.debug(f"Got process name for PID {pid}: {name}")
        return name
    except Exception as e:
        logger.error(f"Failed to get process name for PID {pid}: {e}")
        return "Unknown Process"


def get_process_path(pid):
    try:
        process = psutil.Process(pid)
        path = process.exe()
        logger.debug(f"Got process path for PID {pid}: {path}")
        return path
    except Exception as e:
        logger.error(f"Failed to get process path for PID {pid}: {e}")
        return ""


def is_file_locked(file_path):
    try:
        with open(file_path, "a") as f:
            pass
        logger.debug(f"File not locked: {file_path}")
        return False
    except IOError as e:
        logger.debug(f"File locked: {file_path} - {e}")
        return True


def find_and_kill_process_by_path(path):
    """Kill process by its executable path"""
    logger.info(f"Attempting to kill process by path: {path}")
    normalized = os.path.normcase(path)
    killed = False

    for proc in psutil.process_iter(["pid", "exe"]):
        try:
            if proc.info["exe"] and os.path.normcase(proc.info["exe"]) == normalized:
                logger.info(
                    f"Killing process: {proc.info['exe']} (PID: {proc.info['pid']})"
                )
                proc.kill()
                killed = True
        except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
            logger.error(f"Error killing process: {e}")
            continue

    logger.info(f"Kill by path result: {killed}")
    return killed


def kill_processes_by_name(process_name):
    """Kill all processes with the given name"""
    logger.info(f"Killing processes by name: {process_name}")
    killed_count = 0
    for proc in psutil.process_iter(["name"]):
        try:
            if proc.info["name"].lower() == process_name.lower():
                logger.info(f"Killing process: {proc.info['name']} (PID: {proc.pid})")
                proc.kill()
                killed_count += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
            logger.error(f"Error killing process: {e}")
            continue
    logger.info(f"Killed {killed_count} processes by name")
    return killed_count


def create_fallback_pixmap(width=24, height=24, color=QColor(52, 152, 219)):
    """Create a fallback pixmap if assets are missing"""
    logger.warning(f"Creating fallback pixmap: {width}x{height}")
    pixmap = QPixmap(width, height)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setBrush(color)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(0, 0, width, height)
    painter.end()
    return pixmap


def set_action_cursors(root):
    """Use a hand cursor on all key UI controls."""
    control_types = (
        QPushButton,
        QLineEdit,
        QComboBox,
        QCheckBox,
        QRadioButton,
        QTableWidget,
        QTabWidget,
    )
    for widget in root.findChildren(QWidget):
        if isinstance(widget, control_types):
            widget.setCursor(Qt.CursorShape.PointingHandCursor)
    if isinstance(root, QTabWidget):
        root.tabBar().setCursor(Qt.CursorShape.PointingHandCursor)


def run_handle(query):
    exe_path = get_asset_path("handle.exe")
    if not os.path.exists(exe_path):
        exe_path = os.path.join(os.path.dirname(__file__), "handle.exe")
    if not os.path.exists(exe_path):
        print("handle.exe not found")
        return ""

    try:
        proc = subprocess.run([exe_path, "-a", "-u", query], capture_output=True, text=True)
        return proc.stdout + proc.stderr


    except Exception as e:
        logger.error("Handle failed: %s", e)
        return ""


def get_application_command():
    """Return the command Explorer should use to launch this application."""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    return f'"{sys.executable}" "{os.path.abspath(__file__)}"'


def _delete_registry_tree(root, path):
    try:
        with winreg.OpenKey(root, path, 0, winreg.KEY_WRITE | winreg.KEY_READ) as key:
            while True:
                try:
                    child = winreg.EnumKey(key, 0)
                except OSError:
                    break
                _delete_registry_tree(root, f"{path}\\{child}")
        winreg.DeleteKey(root, path)
    except FileNotFoundError:
        pass


def set_explorer_integration(enabled):
    """Install or remove per-user Explorer actions."""
    paths = [
        r"Software\Classes\*\shell\FileUnlocker",
        r"Software\Classes\Directory\shell\FileUnlocker",
        r"Software\Classes\Drive\shell\FileUnlocker",
        r"Software\Classes\*\shell\LockLiftForceDelete",
        r"Software\Classes\Directory\shell\LockLiftForceDelete",
        r"Software\Classes\Drive\shell\LockLiftForceDelete",
    ]
    if not enabled:
        for path in paths:
            _delete_registry_tree(winreg.HKEY_CURRENT_USER, path)
        return

    unlock_command = f'{get_application_command()} --unlock "%1"'
    delete_command = f'{get_application_command()} --force-delete "%1"'
    executable_dir = os.path.dirname(sys.executable if getattr(sys, "frozen", False) else __file__)
    icon_path = os.path.join(executable_dir, "unlocker.ico")
    if not os.path.exists(icon_path):
        icon_path = get_asset_path("unlock.png")

    for path in paths[:3]:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, path) as key:
            winreg.SetValueEx(key, "MUIVerb", 0, winreg.REG_SZ, "Unlock with File Unlocker")
            winreg.SetValueEx(key, "Icon", 0, winreg.REG_SZ, icon_path)
            with winreg.CreateKey(key, "command") as command_key:
                winreg.SetValueEx(command_key, "", 0, winreg.REG_SZ, unlock_command)
    for path in paths[3:]:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, path) as key:
            winreg.SetValueEx(key, "MUIVerb", 0, winreg.REG_SZ, "Force Delete")
            winreg.SetValueEx(key, "Icon", 0, winreg.REG_SZ, icon_path)
            with winreg.CreateKey(key, "command") as command_key:
                winreg.SetValueEx(command_key, "", 0, winreg.REG_SZ, delete_command)


def silent_unlock(path):
    """Unlock processes holding a file or folder and return an exit code."""
    if not path or not os.path.exists(path):
        print(f"Path not found: {path}")
        return 2
    try:
        terminated, failed = terminate_processes(get_lock_processes(path))
        print(f"Closed {terminated} process(es); failed: {failed}; path: {path}")
        return 0 if terminated and not failed else 1
    except Exception as exc:
        logger.exception("Silent unlock failed")
        print(f"Unlock failed: {exc}")
        return 1


class SHFILEOPSTRUCTW(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("wFunc", wintypes.UINT),
        ("pFrom", wintypes.LPCWSTR),
        ("pTo", wintypes.LPCWSTR),
        ("fFlags", wintypes.WORD),
        ("fAnyOperationsAborted", wintypes.BOOL),
        ("hNameMappings", wintypes.LPVOID),
        ("lpszProgressTitle", wintypes.LPCWSTR),
    ]


def send_to_recycle_bin(path):
    """Move a file or folder to the Windows Recycle Bin."""
    operation = SHFILEOPSTRUCTW(
        wFunc=3,
        pFrom=f"{path}\0\0",
        fFlags=0x0040 | 0x0010 | 0x0004 | 0x0400,
    )
    return ctypes.windll.shell32.SHFileOperationW(ctypes.byref(operation)) == 0


def delete_path(path, permanent):
    if permanent:
        if os.path.isdir(path):
            shutil.rmtree(path)
        else:
            os.remove(path)
        return True
    return send_to_recycle_bin(path)


def run_unlock_dialog(path):
    app = QApplication.instance() or QApplication(sys.argv)
    dialog = ProcessChoiceDialog(path)
    result = dialog.exec()
    if not QApplication.instance():
        app.quit()
    return 0 if result == QDialog.DialogCode.Accepted else 1


def run_force_delete_dialog(path):
    app = QApplication.instance() or QApplication(sys.argv)
    choice = QMessageBox()
    choice.setWindowTitle("Force Delete")
    choice.setText(f"Delete this path?\n\n{path}")
    choice.setInformativeText("Choose Recycle Bin to keep a way back, or Permanent Delete to remove it now.")
    recycle = choice.addButton("Recycle Bin", QMessageBox.ButtonRole.AcceptRole)
    permanent = choice.addButton("Permanent Delete", QMessageBox.ButtonRole.DestructiveRole)
    choice.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
    choice.exec()
    clicked = choice.clickedButton()
    if clicked not in (recycle, permanent):
        return 1

    if get_lock_processes(path):
        process_dialog = ProcessChoiceDialog(path)
        if process_dialog.exec() != QDialog.DialogCode.Accepted:
            return 1
    try:
        delete_path(path, clicked is permanent)
        QMessageBox.information(None, "Delete complete", "The path was deleted.")
        return 0
    except Exception as exc:
        QMessageBox.critical(None, "Delete failed", str(exc))
        return 1


def is_safe_to_kill(process_name, pid):
    system_critical = {
        "system",
        "idle",
        "svchost.exe",
        "csrss.exe",
        "wininit.exe",
        "winlogon.exe",
        "services.exe",
        "lsass.exe",
        "explorer.exe",
        "smss.exe",
    }

    pname = process_name.strip().lower()

    if pname in system_critical:
        return False

    try:
        proc = psutil.Process(pid)
        user = proc.username().lower()
        if "nt authority" in user or "system" in user or "network service" in user:
            return False
    except Exception as e:
        print(f"[⚠️] Could not inspect PID {pid}: {e}")
        return False

    return True

def parse_handle_output(output, query):
    """Parse Handle output into safe process records."""
    if not isinstance(output, str):
        raise ValueError("Expected raw string output from handle.exe, but got something else")

    matches = []

    for line in output.splitlines():
        if query.lower() in line.lower():
            match = re.search(r"^(.+?)\s+pid:\s*(\d+)\s+type:\s*\S+\s+(.*)$", line, re.IGNORECASE)
            if match:
                process_name = match.group(1).strip()
                pid = int(match.group(2))
                path = match.group(3).strip()

                matches.append({
                    "name": process_name,
                    "pid": pid,
                    "path": path,
                    "protected": not is_safe_to_kill(process_name, pid),
                })

    return matches


def process_risk(process_name, pid):
    """Return a simple warning level for a process the user may stop."""
    name = process_name.lower()
    try:
        process = psutil.Process(pid)
        username = (process.username() or "").lower()
        path = (process.exe() or "").lower()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        username = ""
        path = ""

    if name in {"system", "idle", "svchost.exe", "csrss.exe", "wininit.exe", "winlogon.exe", "services.exe", "lsass.exe", "explorer.exe", "smss.exe"}:
        return "PROTECTED - Windows process", 4
    if name in {"code.exe", "devenv.exe", "winword.exe", "excel.exe", "notepad.exe"}:
        return "HIGH - may lose unsaved work", 3
    if "system32" in path or "windows" in path or "system" in username:
        return "HIGH - Windows process", 3
    if name in {"chrome.exe", "msedge.exe", "firefox.exe", "python.exe", "node.exe"}:
        return "MEDIUM - active app", 2
    return "LOW - review first", 1


def get_lock_processes(path):
    """Find lock owners and add warning data for the small action dialog."""
    records = []
    for match in parse_handle_output(run_handle(path), path):
        warning, rank = process_risk(match["name"], match["pid"])
        match["warning"] = warning
        match["rank"] = rank
        records.append(match)
    return sorted(records, key=lambda item: (-item["rank"], item["name"].lower(), item["pid"]))


def terminate_processes(processes):
    """Stop selected processes and return success and failure counts."""
    stopped = 0
    failed = 0
    for item in processes:
        if item.get("protected"):
            failed += 1
            continue
        try:
            process = psutil.Process(item["pid"])
            process.terminate()
            try:
                process.wait(timeout=1)
            except psutil.TimeoutExpired:
                process.kill()
                process.wait(timeout=1)
            stopped += 1
        except (psutil.NoSuchProcess, psutil.ZombieProcess):
            stopped += 1
        except (psutil.AccessDenied, PermissionError, psutil.TimeoutExpired):
            failed += 1
        except Exception:
            logger.exception("Could not stop PID %s", item.get("pid"))
            failed += 1
    return stopped, failed


class ProcessChoiceDialog(QDialog):
    def __init__(self, path, parent=None):
        super().__init__(parent)
        self.path = path
        self.processes = get_lock_processes(path)
        self.setWindowTitle("LockLift - Choose processes")
        self.resize(900, 430)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"Processes using: {path}"))
        self.table = QTableWidget(len(self.processes), 5)
        self.table.setHorizontalHeaderLabels(["Close", "Process", "PID", "Risk", "Handle"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        for row, process in enumerate(self.processes):
            check = QTableWidgetItem()
            check.setCheckState(Qt.CheckState.Unchecked)
            self.table.setItem(row, 0, check)
            self.table.setItem(row, 1, QTableWidgetItem(process["name"]))
            self.table.setItem(row, 2, QTableWidgetItem(str(process["pid"])))
            self.table.setItem(row, 3, QTableWidgetItem(process["warning"]))
            self.table.setItem(row, 4, QTableWidgetItem(process["path"]))
            if process.get("protected"):
                self.table.item(row, 0).setFlags(Qt.ItemFlag.ItemIsEnabled)
        layout.addWidget(self.table)

        note = QLabel("High risk apps may have unsaved work. Check each process before closing it.")
        layout.addWidget(note)
        buttons = QHBoxLayout()
        select_all = QPushButton("Select all")
        close_selected = QPushButton("Close selected")
        cancel = QPushButton("Cancel")
        select_all.clicked.connect(self.select_all)
        close_selected.clicked.connect(self.close_selected)
        cancel.clicked.connect(self.reject)
        buttons.addWidget(select_all)
        buttons.addWidget(close_selected)
        buttons.addWidget(cancel)
        layout.addLayout(buttons)
        set_action_cursors(self)

    def select_all(self):
        for row in range(self.table.rowCount()):
            if not self.processes[row].get("protected"):
                self.table.item(row, 0).setCheckState(Qt.CheckState.Checked)

    def close_selected(self):
        selected = [
            process for row, process in enumerate(self.processes)
            if self.table.item(row, 0).checkState() == Qt.CheckState.Checked and not process.get("protected")
        ]
        if not selected:
            QMessageBox.information(self, "No process selected", "Select at least one process.")
            return
        stopped, failed = terminate_processes(selected)
        QMessageBox.information(self, "Unlock complete", f"Closed {stopped} process(es). Failed: {failed}.")
        self.accept()

class IconButton(QPushButton):
    def __init__(self, icon_path, text, color, parent=None):
        super().__init__(parent)
        logger.debug(f"Creating IconButton: {text}")
        self.setMinimumHeight(40)
        self.color = QColor(color)
        self.setStyleSheet(
            f"""
            QPushButton {{
                background-color: {self.color.name()};
                color: white;
                font-weight: bold;
                border-radius: 8px;
                padding: 8px 15px;
                font-size: 12px;
                border: none;
                min-height: 40px;
                text-align: left;
                padding-left: 45px;
            }}
            QPushButton:hover {{
                background-color: {self.color.darker(120).name()};
            }}
            QPushButton:pressed {{
                background-color: {self.color.darker(150).name()};
            }}
        """
        )
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        # Add shadow effect
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(10)
        shadow.setColor(QColor(0, 0, 0, 80))
        shadow.setOffset(0, 3)
        self.setGraphicsEffect(shadow)

        # Add icon
        self.icon_label = QLabel(self)
        try:
            logger.debug(f"Loading icon: {icon_path}")
            pixmap = QPixmap(icon_path)
            if pixmap.isNull():
                logger.warning(f"Icon is null: {icon_path}")
                pixmap = create_fallback_pixmap()
        except Exception as e:
            logger.error(f"Error loading icon {icon_path}: {e}")
            pixmap = create_fallback_pixmap()

        self.icon_label.setPixmap(
            pixmap.scaled(
                24,
                24,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        self.icon_label.setGeometry(10, 8, 24, 24)
        self.icon_label.setStyleSheet("background: transparent;")

        self.setText(text)

    def resizeEvent(self, event):
        logger.debug(f"Resizing IconButton: {self.text()}")
        super().resizeEvent(event)
        self.icon_label.setGeometry(10, (self.height() - 24) // 2, 24, 24)

    def setIcon(self, icon_path):
        try:
            logger.debug(f"Setting icon: {icon_path}")
            pixmap = QPixmap(icon_path)
            if pixmap.isNull():
                logger.warning(f"Icon is null: {icon_path}")
                pixmap = create_fallback_pixmap(24, 24)
        except Exception as e:
            logger.error(f"Error loading icon {icon_path}: {e}")
            pixmap = create_fallback_pixmap(24, 24)
        self.icon_label.setPixmap(
            pixmap.scaled(
                24,
                24,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )


class FileLockDetector(QThread):
    locks_detected = pyqtSignal(list)
    error_occurred = pyqtSignal(str)
    progress_updated = pyqtSignal(int, int, str)

    def __init__(self, query=None):
        super().__init__()
        self.query = query
        self.cancelled = False
        logger.info(f"[🔍] FileLockDetector created for query: {query}")

    def run(self):
        logger.info("[🧵] FileLockDetector thread started")

        if not self.query or not isinstance(self.query, str):
            error = f"Invalid or missing query: {self.query}"
            logger.error(error)
            self.error_occurred.emit(error)
            return

        try:
            # Ensure handle.exe returns a string
            raw_output = run_handle(self.query)
            if not isinstance(raw_output, str):
                raise ValueError("Expected string output from run_handle(), got something else.")

            logger.info(f"[📦] Handle output received for query: {self.query}")
            matches = parse_handle_output(raw_output, self.query)
            logger.info(f"[📄] Matches extracted: {len(matches)} entries")

            locks = []
            for match in matches:
                # Support both string and dict-based match items
                if isinstance(match, str):
                    regex = re.search(r"(.+?)\s+pid:\s+(\d+)\s+type:\s+\w+\s+(.*)", match)
                    if regex:
                        process_name = regex.group(1).strip()
                        pid = int(regex.group(2))
                        path = regex.group(3).strip()
                    else:
                        logger.warning(f"[⚠️] Couldn't parse line: {match}")
                        continue
                elif isinstance(match, dict):
                    process_name = match.get("name", "Unknown")
                    pid = match.get("pid", -1)
                    path = match.get("path", "")
                else:
                    logger.warning(f"[⚠️] Unexpected match format: {match}")
                    continue

                lock_info = {
                    "pid": pid,
                    "name": process_name,
                    "path": path,
                    "handle": None,
                }

                logger.debug(f"[🔒] Found lock: {lock_info}")
                locks.append(lock_info)

            logger.info(f"[✅] Scan complete. Found {len(locks)} valid locks.")
            self.locks_detected.emit(locks)

        except Exception as e:
            logger.exception("Error in lock detection:")
            self.error_occurred.emit(str(e))

    def cancel(self):
        logger.info("[🛑] Cancelling lock detection")
        self.cancelled = True


class ProcessTerminator(QThread):
    process_terminated = pyqtSignal(int, bool, str)  # pid, success, message

    def __init__(self, pid):
        super().__init__()
        self.pid = pid
        logger.info(f"ProcessTerminator created for PID: {pid}")

    def run(self):
        logger.info(f"Terminating process {self.pid}")
        try:
            process = psutil.Process(self.pid)
            process.terminate()
            try:
                # Wait a bit to see if the process exits
                time.sleep(0.5)
                if process.is_running():
                    logger.info(f"Process still running, killing PID: {self.pid}")
                    process.kill()
                self.process_terminated.emit(self.pid, True, "Process terminated")
                logger.info(f"Successfully terminated PID: {self.pid}")
            except Exception as e:
                logger.error(f"Error terminating process: {e}")
                self.process_terminated.emit(self.pid, True, "Process terminated")
        except psutil.AccessDenied:
            error = "Access denied: Run as administrator"
            logger.error(error)
            self.process_terminated.emit(self.pid, False, error)
        except Exception as e:
            error = f"Error: {str(e)}"
            logger.error(error)
            self.process_terminated.emit(self.pid, False, error)


class FileMonitor(QThread):
    lock_detected = pyqtSignal(str)
    status_update = pyqtSignal(str)

    def __init__(self, query):
        super().__init__()
        self.query = query
        self.running = True
        logger.info(f"FileMonitor created for query: {query}")

    def run(self):
        logger.info("FileMonitor thread started")
        self.status_update.emit(f"Starting monitoring: {self.query}")
        last_locks = []

        while self.running:
            try:
                # Use handle.exe for monitoring
                raw_output = run_handle(self.query)
                current_locks = parse_handle_output(raw_output, self.query)

                # Check for new locks
                new_locks = [lock for lock in current_locks if lock not in last_locks]
                for lock in new_locks:
                    msg = f"[{datetime.now().strftime('%H:%M:%S')}] NEW LOCK: {lock}"
                    logger.info(msg)
                    self.lock_detected.emit(msg)

                # Check for released locks
                released_locks = [
                    lock for lock in last_locks if lock not in current_locks
                ]
                for lock in released_locks:
                    msg = (
                        f"[{datetime.now().strftime('%H:%M:%S')}] LOCK RELEASED: {lock}"
                    )
                    logger.info(msg)
                    self.lock_detected.emit(msg)

                last_locks = current_locks
                time.sleep(2)  # Check every 2 seconds

            except Exception as e:
                error = f"Monitoring error: {str(e)}"
                logger.error(error)
                self.status_update.emit(error)
                time.sleep(5)

    def stop(self):
        logger.info("Stopping file monitoring")
        self.running = False


class SplashScreen(QDialog):
    def __init__(self):
        super().__init__()
        logger.info("Creating splash screen")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setFixedSize(500, 300)

        # Create main layout
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Create frame
        self.frame = QFrame()
        self.frame.setObjectName("splashFrame")
        self.frame.setStyleSheet(
            """
            #splashFrame {
                background-color: rgba(44, 62, 80, 220);
                border-radius: 20px;
                border: 2px solid #3498db;
            }
        """
        )

        frame_layout = QVBoxLayout(self.frame)
        frame_layout.setContentsMargins(20, 20, 20, 20)
        frame_layout.setSpacing(20)

        # Animated logo
        self.animation_label = QLabel()
        try:
            gif_path = get_asset_path("loading.gif")
            logger.debug(f"Loading splash animation: {gif_path}")
            self.movie = QMovie(gif_path)
            if self.movie.isValid():
                logger.debug("Splash animation valid")
                self.animation_label.setMovie(self.movie)
                self.movie.start()
            else:
                logger.warning("Splash animation invalid")
                self.animation_label.setText("Loading...")
                self.animation_label.setStyleSheet("font-size: 16px; color: white;")
        except Exception as e:
            logger.error(f"Error loading splash animation: {e}")
            self.animation_label.setText("Loading...")
            self.animation_label.setStyleSheet("font-size: 16px; color: white;")

        frame_layout.addWidget(self.animation_label, 0, Qt.AlignmentFlag.AlignCenter)

        # App title
        title = QLabel("Secure File Unlocker")
        title.setStyleSheet(
            """
            font-size: 28px;
            font-weight: bold;
            color: #ecf0f1;
        """
        )
        frame_layout.addWidget(title, 0, Qt.AlignmentFlag.AlignCenter)

        # Loading text
        self.loading_text = QLabel("Initializing...")
        self.loading_text.setStyleSheet(
            """
            font-size: 16px;
            color: #bdc3c7;
        """
        )
        frame_layout.addWidget(self.loading_text, 0, Qt.AlignmentFlag.AlignCenter)

        # Progress bar
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(8)
        self.progress.setStyleSheet(
            """
            QProgressBar {
                background-color: rgba(44, 62, 80, 150);
                border-radius: 4px;
                border: 1px solid #3498db;
            }
            QProgressBar::chunk {
                background-color: #3498db;
                border-radius: 4px;
            }
        """
        )
        frame_layout.addWidget(self.progress)

        layout.addWidget(self.frame)

        # Start loading simulation
        self.loading_value = 0
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_loading)
        self.timer.start(50)

    def update_loading(self):
        self.loading_value += 1
        self.progress.setValue(self.loading_value)

        if self.loading_value <= 30:
            self.loading_text.setText("Loading core modules...")
        elif self.loading_value <= 60:
            self.loading_text.setText("Initializing security features...")
        elif self.loading_value <= 90:
            self.loading_text.setText("Preparing user interface...")
        else:
            self.loading_text.setText("Ready to unlock files!")

        if self.loading_value >= 100:
            logger.info("Splash screen loading complete")
            self.timer.stop()
            self.accept()


class UnlockerApp(QMainWindow):
    def __init__(self):
        super().__init__()
        logger.info("Initializing main application")
        self.setWindowTitle("Secure File Unlocker")
        self.setMinimumSize(1000, 700)

        # Application state
        self.current_file = ""
        self.active_locks = []
        self.current_theme = "dark"
        self.scan_in_progress = False
        self.detector = None
        self.monitor_thread = None
        self.monitoring = False
        self.ui_animations_enabled = True

        # Create central widget
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)

        # Create main layout
        main_layout = QVBoxLayout(self.central_widget)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)

        # Header with logo and title
        header = QWidget()
        header.setStyleSheet("background: transparent;")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(10, 10, 10, 10)

        # Logo
        self.logo = QLabel()
        try:
            icon_path = get_asset_path("unlock.png")
            logger.debug(f"Loading app icon: {icon_path}")
            pixmap = QPixmap(icon_path)
            if pixmap.isNull():
                logger.warning("App icon is null, using fallback")
                pixmap = create_fallback_pixmap(48, 48)
        except Exception as e:
            logger.error(f"Error loading app icon: {e}")
            pixmap = create_fallback_pixmap(48, 48)
        self.logo.setPixmap(
            pixmap.scaled(
                48,
                48,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        header_layout.addWidget(self.logo)

        # Title
        title = QLabel("Secure File Unlocker")
        title.setStyleSheet("font-size: 24px; font-weight: bold; color: #ecf0f1;")
        header_layout.addWidget(title, 1)

        # Theme button
        self.theme_btn = QPushButton()
        try:
            theme_icon = get_asset_path("theme.png")
            logger.debug(f"Loading theme icon: {theme_icon}")
            self.theme_btn.setIcon(QIcon(theme_icon))
        except Exception as e:
            logger.error(f"Error loading theme icon: {e}")
            self.theme_btn.setIcon(QIcon(create_fallback_pixmap(24, 24, QColor(52, 152, 219))))
        self.theme_btn.setIconSize(QSize(24, 24))
        self.theme_btn.setFixedSize(40, 40)
        self.theme_btn.setStyleSheet(
            """
            QPushButton {
                background-color: #3498db;
                border-radius: 20px;
                border: none;
            }
            QPushButton:hover {
                background-color: #2980b9;
            }
        """
        )
        self.theme_btn.clicked.connect(self.toggle_theme)
        header_layout.addWidget(self.theme_btn)

        main_layout.addWidget(header)

        # Create tab widget with Chrome-like styling
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setStyleSheet(
            """
            QTabWidget::pane {
                border: none;
                background: rgba(52, 73, 94, 180);
                border-radius: 8px;
            }
            QTabBar::tab {
                background: #2c3e50;
                color: #bdc3c7;
                padding: 12px 24px;
                border-top-left-radius: 8px;
                border-top-right-radius: 8px;
                margin-right: 2px;
                font-weight: bold;
                font-size: 13px;
                min-width: 120px;
                border-bottom: 2px solid transparent;
            }
            QTabBar::tab:selected {
                background: rgba(52, 73, 94, 200);
                color: #ecf0f1;
                border-bottom: 2px solid #3498db;
            }
            QTabBar::tab:hover {
                background: #3d566e;
            }
            QTabBar::tab:!selected {
                margin-top: 4px;
            }
        """
        )

        # Create tabs
        logger.debug("Creating application tabs")
        self.active_locks_tab = self.create_active_locks_tab()
        self.force_actions_tab = self.create_force_actions_tab()
        self.monitor_tab = self.create_monitor_tab()
        self.settings_tab = self.create_settings_tab()

        self.tabs.addTab(self.active_locks_tab, "Active Locks")
        self.tabs.addTab(self.force_actions_tab, "Force Actions")
        self.tabs.addTab(self.monitor_tab, "Monitor")
        self.tabs.addTab(self.settings_tab, "Settings")

        set_action_cursors(self)

        main_layout.addWidget(self.tabs, 1)

        # Status bar
        self.status_bar = QStatusBar()
        self.status_bar.setStyleSheet(
            """
            background: rgba(44, 62, 80, 200); 
            color: #bdc3c7; 
            border-top: 1px solid #34495e;
            font-size: 11px;
            padding: 5px;
        """
        )
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready")

        # Enable drag and drop
        self.setAcceptDrops(True)

        # Apply theme
        self.apply_theme(self.current_theme)

        # Apply glass effect
        self.apply_glass_effect()

        # Add entrance animation
        self.animate_entrance()

        # Set initial geometry
        self.center_window()

        # Create sidebar for additional options
        self.create_sidebar()

        # Load settings
        self.load_settings()
        QTimer.singleShot(0, self.prompt_explorer_integration)

    def prompt_explorer_integration(self):
        if self.settings.get("explorer_integration") is True:
            set_explorer_integration(True)
            return
        if self.settings.get("explorer_integration") is False:
            return
        answer = QMessageBox.question(
            self,
            "File Explorer integration",
            "Add Unlock with File Unlocker to the File Explorer context menu for files and folders?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        enabled = answer == QMessageBox.StandardButton.Yes
        try:
            set_explorer_integration(enabled)
            self.settings["explorer_integration"] = enabled
            self.save_settings()
        except OSError as exc:
            self.settings["explorer_integration"] = False
            QMessageBox.warning(self, "Integration unavailable", f"Could not update File Explorer: {exc}")

    def create_sidebar(self):
        """Create sidebar for additional options in Force Actions tab"""
        self.sidebar = QFrame(self)
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setStyleSheet(
            """
            #sidebar {
                background-color: rgba(44, 62, 80, 230);
                border-left: 1px solid #3498db;
                border-radius: 8px;
            }
        """
        )
        self.sidebar.setFixedWidth(300)
        self.sidebar.hide()

        sidebar_layout = QVBoxLayout(self.sidebar)
        sidebar_layout.setContentsMargins(15, 15, 15, 15)
        sidebar_layout.setSpacing(15)

        title = QLabel("Additional Options")
        title.setStyleSheet("font-size: 16px; font-weight: bold; color: #3498db;")
        sidebar_layout.addWidget(title)

        self.additional_input = QLineEdit()
        self.additional_input.setPlaceholderText("Enter new name or destination path")
        self.additional_input.setStyleSheet(
            """
            QLineEdit {
                background: rgba(52, 73, 94, 180);
                color: #ecf0f1;
                border: 1px solid #3d566e;
                border-radius: 6px;
                padding: 10px;
                font-size: 13px;
            }
        """
        )
        sidebar_layout.addWidget(self.additional_input)

        close_btn = QPushButton("Close")
        close_btn.setStyleSheet(
            """
            QPushButton {
                background-color: #e74c3c;
                color: white;
                border-radius: 6px;
                padding: 8px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #c0392b;
            }
        """
        )
        close_btn.clicked.connect(self.sidebar.hide)
        sidebar_layout.addWidget(close_btn)
        sidebar_layout.addStretch(1)

    def toggle_sidebar(self, checked):
        """Show/hide sidebar based on radio button selection"""
        if checked and (self.rename_radio.isChecked() or self.move_radio.isChecked()):
            self.sidebar.show()
            # Position sidebar
            sidebar_x = self.width() - 320
            sidebar_y = 50
            self.sidebar.setGeometry(sidebar_x, sidebar_y, 300, self.height() - 100)
        else:
            self.sidebar.hide()

    def center_window(self):
        """Center the window on the screen"""
        logger.info("Centering main window")
        screen = QApplication.primaryScreen().availableGeometry()
        size = self.geometry()
        x = (screen.width() - size.width()) // 2
        y = (screen.height() - size.height()) // 2
        self.move(x, y)
        logger.debug(f"Window positioned at: {x}, {y}")

    def apply_glass_effect(self):
        self.setStyleSheet(
            """
            QMainWindow {
                background-color: rgba(0, 0, 0, 50);
                border-radius: 15px;
            }
        """
        )

        self.background_label = QLabel(self)
        self.background_label.setGeometry(0, 0, self.width(), self.height())

        # Make it click-through
        self.background_label.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True
        )

        # Load image based on theme
        self.update_background()

        # Send it behind
        self.background_label.stackUnder(self.centralWidget())

    def update_background(self):
        """Update background based on current theme"""
        # Fix: Only proceed if background_label exists
        if not hasattr(self, "background_label"):
            return
    
        if self.current_theme == "dark":
            background_path = get_asset_path("dark.jpg")
        elif self.current_theme == "light":
            background_path = get_asset_path("light.jpg")
        elif self.current_theme == "blue":
            background_path = get_asset_path("blue.jpg")
        elif self.current_theme == "purple":
            background_path = get_asset_path("purple.jpg")
        else:
            background_path = get_asset_path("dark.jpg")
    
        pixmap = QPixmap(background_path)
        if pixmap.isNull():
            self.background_label.setStyleSheet("background-color: #2c3e50;")
        else:
            # Apply blur effect
            blur_effect = QGraphicsBlurEffect()
            blur_effect.setBlurRadius(15)
            self.background_label.setGraphicsEffect(blur_effect)
    
            # Add color overlay
            overlay = QPixmap(pixmap.size())
            if self.current_theme == "dark":
                overlay.fill(QColor(30, 30, 30, 140))  # Stronger, more opaque overlay
            elif self.current_theme == "light":
                overlay.fill(QColor(0, 0, 0, 160))
            elif self.current_theme == "blue":
                overlay.fill(QColor(25, 118, 210, 140))
            elif self.current_theme == "purple":
                overlay.fill(QColor(81, 45, 168, 140))
    
            painter = QPainter(pixmap)
            painter.drawPixmap(0, 0, overlay)
            painter.end()
    
            self.background_label.setPixmap(
                pixmap.scaled(
                    self.size(),
                    Qt.AspectRatioMode.IgnoreAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )

    def animate_entrance(self):
        if not self.ui_animations_enabled:
            self.showMaximized()
            return

        logger.info("Starting entrance animation")
        # Set opacity and prepare window
        self.setWindowOpacity(0)
        self.showNormal()  # Needed to animate position before maximizing
        self.raise_()
        self.activateWindow()

        # Calculate positions
        screen = QGuiApplication.primaryScreen().availableGeometry()
        start_pos = QPoint(0, -100)  # Start slightly above the screen
        end_pos = QPoint(0, 0)  # Move to top-left corner

        self.move(start_pos)

        # Create animation group
        self.entrance_animation = QParallelAnimationGroup(self)

        # Fade-in
        fade = QPropertyAnimation(self, b"windowOpacity")
        fade.setDuration(700)
        fade.setStartValue(0)
        fade.setEndValue(1)
        fade.setEasingCurve(QEasingCurve.Type.OutCubic)

        # Slide down
        slide = QPropertyAnimation(self, b"pos")
        slide.setDuration(700)
        slide.setStartValue(start_pos)
        slide.setEndValue(end_pos)
        slide.setEasingCurve(QEasingCurve.Type.OutCubic)

        self.entrance_animation.addAnimation(fade)
        self.entrance_animation.addAnimation(slide)

        # After animation ends, maximize the window
        def finalize_animation():
            self.setWindowOpacity(1)
            self.showMaximized()

        self.entrance_animation.finished.connect(finalize_animation)
        self.entrance_animation.start()

    def resizeEvent(self, event):
        logger.debug(f"Resizing window: {event.size().width()}x{event.size().height()}")
        super().resizeEvent(event)
        # Resize background to match window size
        if hasattr(self, "background_label"):
            self.background_label.setGeometry(0, 0, self.width(), self.height())
            self.update_background()

        # Position sidebar if visible
        if hasattr(self, "sidebar") and self.sidebar.isVisible():
            sidebar_x = self.width() - 320
            sidebar_y = 50
            self.sidebar.setGeometry(sidebar_x, sidebar_y, 300, self.height() - 100)

    def closeEvent(self, event):
        logger.info("Application closing")
        # Stop any running threads when closing the app
        if self.detector and self.detector.isRunning():
            logger.debug("Stopping detector thread")
            self.detector.cancel()
            self.detector.wait(1000)
        if self.monitor_thread and self.monitor_thread.isRunning():
            logger.debug("Stopping monitor thread")
            self.monitor_thread.stop()
            self.monitor_thread.wait(1000)
        event.accept()

    def create_active_locks_tab(self):
        logger.debug("Creating Active Locks tab")
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(15)

        # Path selection
        path_group = QGroupBox("Select File or Folder Name")
        path_group.setStyleSheet(
            """
            QGroupBox {
                background: rgba(52, 73, 94, 180);
                color: #3498db;
                border: 1px solid #3d566e;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 15px;
                font-weight: bold;
                font-size: 14px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
                color: #3498db;
            }
        """
        )
        path_layout = QVBoxLayout(path_group)
        path_layout.setContentsMargins(15, 25, 15, 15)
        path_layout.setSpacing(10)

        # Name input
        self.path_input = QLineEdit()
        self.path_input.setPlaceholderText(
            "Enter filename or folder name (not full path)"
        )
        self.path_input.setStyleSheet(
            """
            QLineEdit {
                background: rgba(44, 62, 80, 180);
                color: #ecf0f1;
                border: 1px solid #3d566e;
                border-radius: 6px;
                padding: 10px;
                font-size: 13px;
            }
        """
        )
        path_layout.addWidget(self.path_input)

        # Browse buttons
        browse_container = QWidget()
        browse_layout = QGridLayout(browse_container)
        browse_layout.setContentsMargins(0, 5, 0, 0)
        browse_layout.setHorizontalSpacing(10)

        self.file_browse_btn = IconButton(
            get_asset_path("file.png"), "Browse File", "#1abc9c", self
        )
        self.file_browse_btn.setMinimumHeight(40)
        self.file_browse_btn.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.file_browse_btn.clicked.connect(self.browse_file)
        browse_layout.addWidget(self.file_browse_btn, 0, 0)

        self.folder_browse_btn = IconButton(
            get_asset_path("folder.png"), "Browse Folder", "#3498db", self
        )
        self.folder_browse_btn.setMinimumHeight(40)
        self.folder_browse_btn.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.folder_browse_btn.clicked.connect(self.browse_folder)
        browse_layout.addWidget(self.folder_browse_btn, 0, 1)

        path_layout.addWidget(browse_container)
        layout.addWidget(path_group)

        # Action buttons
        action_container = QWidget()
        action_layout = QHBoxLayout(action_container)
        action_layout.setContentsMargins(0, 5, 0, 0)
        action_layout.setSpacing(10)

        self.scan_btn = IconButton(
            get_asset_path("scan.png"), "Scan for Locks", "#3498db", self
        )
        self.scan_btn.setMinimumHeight(45)
        self.scan_btn.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.scan_btn.clicked.connect(self.scan_locks)
        action_layout.addWidget(self.scan_btn)

        self.cancel_btn = IconButton(
            get_asset_path("cancel.png"), "Cancel Scan", "#e74c3c", self
        )
        self.cancel_btn.setMinimumHeight(45)
        self.cancel_btn.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.cancel_btn.setVisible(False)
        self.cancel_btn.clicked.connect(self.cancel_scan)
        action_layout.addWidget(self.cancel_btn)

        layout.addWidget(action_container)

        # Progress container
        progress_container = QWidget()
        progress_layout = QVBoxLayout(progress_container)
        progress_layout.setContentsMargins(0, 5, 0, 5)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(8)
        self.progress_bar.setStyleSheet(
            """
            QProgressBar {
                background: rgba(44, 62, 80, 180);
                border: 1px solid #3d566e;
                border-radius: 6px;
                height: 16px;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #3498db, stop:1 #1abc9c);
                border-radius: 6px;
            }
        """
        )
        progress_layout.addWidget(self.progress_bar)

        # Progress label
        self.progress_label = QLabel()
        self.progress_label.setStyleSheet("color: #3498db; font-size: 12px;")
        self.progress_label.setVisible(False)
        progress_layout.addWidget(self.progress_label)

        layout.addWidget(progress_container)

        # Results table
        results_group = QGroupBox("Active Locks")
        results_group.setStyleSheet(
            """
            QGroupBox {
                background: rgba(52, 73, 94, 180);
                color: #3498db;
                border: 1px solid #3d566e;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 15px;
                font-weight: bold;
                font-size: 14px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
                color: #3498db;
            }
        """
        )
        results_layout = QVBoxLayout(results_group)
        results_layout.setContentsMargins(15, 25, 15, 15)

        self.locks_table = QTableWidget()
        self.locks_table.setColumnCount(4)
        self.locks_table.setHorizontalHeaderLabels(
            ["Process", "PID", "File Path", "Actions"]
        )
        self.locks_table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.ResizeToContents
        )
        self.locks_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self.locks_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        self.locks_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Stretch
        )
        self.locks_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.locks_table.setStyleSheet(
            """
            QTableWidget {
                background: rgba(44, 62, 80, 180);
                color: #ecf0f1;
                border: 1px solid #3d566e;
                border-radius: 6px;
                gridline-color: #3d566e;
                font-size: 12px;
                alternate-background-color: rgba(52, 73, 94, 0.5);
            }
            QHeaderView::section {
                background: #1abc9c;
                color: #2c3e50;
                padding: 8px;
                font-weight: bold;
                border: none;
                font-size: 12px;
            }
        """
        )
        self.locks_table.setAlternatingRowColors(True)
        results_layout.addWidget(self.locks_table, 1)

        # Action buttons
        action_container = QWidget()
        action_layout = QHBoxLayout(action_container)
        action_layout.setContentsMargins(0, 10, 0, 0)
        action_layout.setSpacing(10)

        self.unlock_all_btn = IconButton(
            get_asset_path("unlock.png"), "Unlock All Processes", "#3498db", self
        )
        self.unlock_all_btn.setMinimumHeight(40)
        self.unlock_all_btn.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.unlock_all_btn.clicked.connect(self.unlock_all)
        action_layout.addWidget(self.unlock_all_btn)

        self.refresh_btn = IconButton(
            get_asset_path("refresh.png"), "Refresh", "#1abc9c", self
        )
        self.refresh_btn.setMinimumHeight(40)
        self.refresh_btn.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.refresh_btn.clicked.connect(self.scan_locks)
        action_layout.addWidget(self.refresh_btn)

        results_layout.addWidget(action_container)

        layout.addWidget(results_group, 1)

        return tab

    def create_force_actions_tab(self):
        logger.debug("Creating Force Actions tab")
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(15)

        # Path selection
        path_group = QGroupBox("Select File or Folder to Force Action")
        path_group.setStyleSheet(
            """
            QGroupBox {
                background: rgba(52, 73, 94, 180);
                color: #3498db;
                border: 1px solid #3d566e;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 15px;
                font-weight: bold;
                font-size: 14px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
                color: #3498db;
            }
        """
        )
        path_layout = QVBoxLayout(path_group)
        path_layout.setContentsMargins(15, 25, 15, 15)

        self.force_path_input = QLineEdit()
        self.force_path_input.setPlaceholderText(
            "Drag & drop file/folder or click Browse..."
        )
        self.force_path_input.setStyleSheet(
            """
            QLineEdit {
                background: rgba(44, 62, 80, 180);
                color: #ecf0f1;
                border: 1px solid #3d566e;
                border-radius: 6px;
                padding: 10px;
                font-size: 13px;
            }
        """
        )
        path_layout.addWidget(self.force_path_input)

        # Browse buttons
        browse_container = QWidget()
        browse_layout = QGridLayout(browse_container)
        browse_layout.setContentsMargins(0, 10, 0, 10)
        browse_layout.setHorizontalSpacing(10)
        browse_layout.setVerticalSpacing(10)

        self.force_file_browse_btn = IconButton(
            get_asset_path("file.png"), "Browse File", "#1abc9c", self
        )
        self.force_file_browse_btn.setMinimumHeight(50)
        self.force_file_browse_btn.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.force_file_browse_btn.clicked.connect(self.browse_force_file)
        browse_layout.addWidget(self.force_file_browse_btn, 0, 0)

        self.force_folder_browse_btn = IconButton(
            get_asset_path("folder.png"), "Browse Folder", "#3498db", self
        )
        self.force_folder_browse_btn.setMinimumHeight(50)
        self.force_folder_browse_btn.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.force_folder_browse_btn.clicked.connect(self.browse_force_folder)
        browse_layout.addWidget(self.force_folder_browse_btn, 0, 1)

        path_layout.addWidget(browse_container)
        layout.addWidget(path_group)

        # Operation selection
        operation_group = QGroupBox("Select Operation")
        operation_group.setStyleSheet(
            """
            QGroupBox {
                background: rgba(52, 73, 94, 180);
                color: #3498db;
                border: 1px solid #3d566e;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 15px;
                font-weight: bold;
                font-size: 14px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
                color: #3498db;
            }
        """
        )
        operation_layout = QGridLayout(operation_group)
        operation_layout.setContentsMargins(15, 25, 15, 15)
        operation_layout.setHorizontalSpacing(15)
        operation_layout.setVerticalSpacing(10)

        # Operation buttons
        self.operation_group = QButtonGroup()

        self.delete_radio = QRadioButton("Delete")
        self.delete_radio.setChecked(True)
        self.delete_radio.setStyleSheet("color: #ecf0f1; font-size: 13px;")
        operation_layout.addWidget(self.delete_radio, 0, 0)

        self.rename_radio = QRadioButton("Rename")
        self.rename_radio.setStyleSheet("color: #ecf0f1; font-size: 13px;")
        operation_layout.addWidget(self.rename_radio, 0, 1)

        self.move_radio = QRadioButton("Move")
        self.move_radio.setStyleSheet("color: #ecf0f1; font-size: 13px;")
        operation_layout.addWidget(self.move_radio, 0, 2)

        self.operation_group.addButton(self.delete_radio)
        self.operation_group.addButton(self.rename_radio)
        self.operation_group.addButton(self.move_radio)

        # Schedule for reboot
        self.schedule_reboot = QCheckBox("Schedule operation for next reboot")
        self.schedule_reboot.setStyleSheet("color: #ecf0f1; font-size: 13px;")
        self.schedule_reboot.setStyleSheet("color: #ecf0f1; font-size: 13px;")
        operation_layout.addWidget(self.schedule_reboot, 1, 0, 1, 3)

        # Kill by name checkbox
        self.kill_by_name = QCheckBox("Kill processes with same name")
        self.kill_by_name.setStyleSheet("color: #ecf0f1; font-size: 13px;")
        self.kill_by_name.setToolTip(
            "Also kill processes that have the same name as the file"
        )
        operation_layout.addWidget(self.kill_by_name, 2, 0, 1, 3)

        layout.addWidget(operation_group)

        # Connect radio buttons to sidebar
        self.delete_radio.toggled.connect(self.toggle_sidebar)
        self.rename_radio.toggled.connect(self.toggle_sidebar)
        self.move_radio.toggled.connect(self.toggle_sidebar)

        # Force action button
        self.force_btn = IconButton(
            get_asset_path("force.png"), "Execute Force Action", "#e74c3c", self
        )
        self.force_btn.setFixedHeight(45)
        self.force_btn.clicked.connect(self.perform_force_action)
        layout.addWidget(self.force_btn)

        # Status display
        self.force_status = QTextEdit()
        self.force_status.setReadOnly(True)
        self.force_status.setStyleSheet(
            """
            QTextEdit {
                background: rgba(44, 62, 80, 180);
                color: #bdc3c7;
                border: 1px solid #3d566e;
                border-radius: 6px;
                padding: 10px;
                font-size: 12px;
            }
        """
        )
        layout.addWidget(self.force_status, 1)

        return tab

    def create_monitor_tab(self):
        logger.debug("Creating Monitor tab")
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(15)

        # Path selection
        path_group = QGroupBox("Select File or Folder Name to Monitor")
        path_group.setStyleSheet(
            """
            QGroupBox {
                background: rgba(52, 73, 94, 180);
                color: #3498db;
                border: 1px solid #3d566e;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 15px;
                font-weight: bold;
                font-size: 14px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
                color: #3498db;
            }
        """
        )
        path_layout = QVBoxLayout(path_group)
        path_layout.setContentsMargins(15, 25, 15, 15)

        self.monitor_path_input = QLineEdit()
        self.monitor_path_input.setPlaceholderText(
            "Enter filename or folder name (not full path)"
        )
        self.monitor_path_input.setStyleSheet(
            """
            QLineEdit {
                background: rgba(44, 62, 80, 180);
                color: #ecf0f1;
                border: 1px solid #3d566e;
                border-radius: 6px;
                padding: 10px;
                font-size: 13px;
            }
        """
        )
        path_layout.addWidget(self.monitor_path_input)

        # Browse buttons
        browse_container = QWidget()
        browse_layout = QGridLayout(browse_container)
        browse_layout.setContentsMargins(0, 5, 0, 0)
        browse_layout.setHorizontalSpacing(10)

        self.monitor_file_browse_btn = IconButton(
            get_asset_path("file.png"), "Browse File", "#1abc9c", self
        )
        self.monitor_file_browse_btn.setMinimumHeight(40)
        self.monitor_file_browse_btn.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.monitor_file_browse_btn.clicked.connect(self.browse_monitor_file)
        browse_layout.addWidget(self.monitor_file_browse_btn, 0, 0)

        self.monitor_folder_browse_btn = IconButton(
            get_asset_path("folder.png"), "Browse Folder", "#3498db", self
        )
        self.monitor_folder_browse_btn.setMinimumHeight(40)
        self.monitor_folder_browse_btn.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.monitor_folder_browse_btn.clicked.connect(self.browse_monitor_folder)
        browse_layout.addWidget(self.monitor_folder_browse_btn, 0, 1)

        path_layout.addWidget(browse_container)
        layout.addWidget(path_group)

        # Monitor button
        self.monitor_btn = IconButton(
            get_asset_path("monitor.png"), "Start Monitoring", "#3498db", self
        )
        self.monitor_btn.setFixedHeight(45)
        self.monitor_btn.clicked.connect(self.toggle_monitoring)
        layout.addWidget(self.monitor_btn)

        # Monitoring log
        log_group = QGroupBox("Lock Status Monitor")
        log_group.setStyleSheet(
            """
            QGroupBox {
                background: rgba(52, 73, 94, 180);
                color: #3498db;
                border: 1px solid #3d566e;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 15px;
                font-weight: bold;
                font-size: 14px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
                color: #3498db;
            }
        """
        )
        log_layout = QVBoxLayout(log_group)
        log_layout.setContentsMargins(15, 25, 15, 15)

        self.monitor_log = QTextEdit()
        self.monitor_log.setReadOnly(True)
        self.monitor_log.setStyleSheet(
            """
            QTextEdit {
                background: rgba(44, 62, 80, 180);
                color: #bdc3c7;
                border: 1px solid #3d566e;
                border-radius: 6px;
                font-family: Consolas, monospace;
                font-size: 12px;
                padding: 10px;
            }
        """
        )
        log_layout.addWidget(self.monitor_log, 1)

        # Action buttons container
        action_container = QWidget()
        action_layout = QHBoxLayout(action_container)
        action_layout.setContentsMargins(10, 10, 10, 10)
        action_layout.setSpacing(10)

        # Style container
        action_container.setStyleSheet(
            """
            QWidget {
                background-color: rgba(255, 255, 255, 0.03);
                border-radius: 12px;
            }
        """
        )

        # Clear Log button
        self.clear_log_btn = IconButton(
            get_asset_path("clear.png"), "Clear Log", "#e74c3c", self
        )
        self.clear_log_btn.setMinimumHeight(40)
        self.clear_log_btn.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.clear_log_btn.clicked.connect(lambda: self.monitor_log.clear())
        action_layout.addWidget(self.clear_log_btn)

        # Save Log button
        self.save_log_btn = IconButton(
            get_asset_path("save.png"), "Save Log", "#1abc9c", self
        )
        self.save_log_btn.setMinimumHeight(40)
        self.save_log_btn.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.save_log_btn.clicked.connect(self.save_log)
        action_layout.addWidget(self.save_log_btn)

        log_layout.addWidget(action_container)

        layout.addWidget(log_group, 1)

        return tab

    def create_settings_tab(self):
        logger.debug("Creating Settings tab")
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(15)

        # Theme selection
        theme_group = QGroupBox("Appearance Settings")
        theme_group.setStyleSheet(
            """
            QGroupBox {
                background: rgba(52, 73, 94, 180);
                color: #3498db;
                border: 1px solid #3d566e;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 15px;
                font-weight: bold;
                font-size: 14px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
                color: #3498db;
            }
        """
        )
        theme_layout = QGridLayout(theme_group)
        theme_layout.setContentsMargins(15, 25, 15, 15)
        theme_layout.setHorizontalSpacing(15)
        theme_layout.setVerticalSpacing(10)

        theme_label = QLabel("Theme:")
        theme_label.setStyleSheet("color: #ecf0f1; font-size: 13px;")
        theme_layout.addWidget(theme_label, 0, 0)

        self.theme_combo = QComboBox()
        self.theme_combo.addItems(["Dark", "Light", "Blue", "Purple"])
        self.theme_combo.setCurrentText(self.current_theme.capitalize())
        self.theme_combo.setStyleSheet(
            """
            QComboBox {
                background: rgba(44, 62, 80, 180);
                color: #ecf0f1;
                border: 1px solid #3d566e;
                border-radius: 6px;
                padding: 8px;
                font-size: 13px;
            }
            QComboBox::drop-down {
                subcontrol-origin: padding;
                subcontrol-position: top right;
                width: 30px;
                border-left-width: 1px;
                border-left-color: #3d566e;
                border-left-style: solid;
                border-top-right-radius: 6px;
                border-bottom-right-radius: 6px;
            }
        """
        )
        self.theme_combo.currentTextChanged.connect(self.change_theme)
        theme_layout.addWidget(self.theme_combo, 0, 1)

        # Animation toggle
        self.animation_toggle = QCheckBox("Enable UI animations")
        self.animation_toggle.setChecked(True)
        self.animation_toggle.setStyleSheet("color: #ecf0f1; font-size: 13px;")
        theme_layout.addWidget(self.animation_toggle, 1, 0, 1, 2)

        layout.addWidget(theme_group)

        # Security settings
        security_group = QGroupBox("Security Settings")
        security_group.setStyleSheet(
            """
            QGroupBox {
                background: rgba(52, 73, 94, 180);
                color: #3498db;
                border: 1px solid #3d566e;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 15px;
                font-weight: bold;
                font-size: 14px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
                color: #3498db;
            }
        """
        )
        security_layout = QGridLayout(security_group)
        security_layout.setContentsMargins(15, 25, 15, 15)
        security_layout.setHorizontalSpacing(15)
        security_layout.setVerticalSpacing(10)

        # Auto-elevate setting
        self.auto_elevate = QCheckBox("Automatically request admin privileges")
        self.auto_elevate.setChecked(True)
        self.auto_elevate.setStyleSheet("color: #ecf0f1; font-size: 13px;")
        security_layout.addWidget(self.auto_elevate, 0, 0, 1, 2)

        # Logging settings
        logging_label = QLabel("Logging Level:")
        logging_label.setStyleSheet("color: #ecf0f1; font-size: 13px;")
        security_layout.addWidget(logging_label, 1, 0)

        self.log_level = QComboBox()
        self.log_level.addItems(["Minimal", "Normal", "Verbose"])
        self.log_level.setCurrentText("Normal")
        self.log_level.setStyleSheet(
            """
            QComboBox {
                background: rgba(44, 62, 80, 180);
                color: #ecf0f1;
                border: 1px solid #3d566e;
                border-radius: 6px;
                padding: 8px;
                font-size: 13px;
            }
            QComboBox::drop-down {
                subcontrol-origin: padding;
                subcontrol-position: top right;
                width: 30px;
                border-left-width: 1px;
                border-left-color: #3d566e;
                border-left-style: solid;
                border-top-right-radius: 6px;
                border-bottom-right-radius: 6px;
            }
        """
        )
        security_layout.addWidget(self.log_level, 1, 1)

        layout.addWidget(security_group)

        # Action buttons
        action_container = QWidget()
        action_layout = QHBoxLayout(action_container)
        action_layout.setContentsMargins(0, 10, 0, 0)
        action_layout.setSpacing(10)

        self.save_btn = IconButton(
            get_asset_path("save.png"), "Save Settings", "#1abc9c", self
        )
        self.save_btn.setFixedHeight(40)
        self.save_btn.clicked.connect(self.save_settings)
        action_layout.addWidget(self.save_btn)

        self.about_btn = IconButton(
            get_asset_path("info.png"), "About", "#3498db", self
        )
        self.about_btn.setFixedHeight(40)
        self.about_btn.clicked.connect(self.show_about)
        action_layout.addWidget(self.about_btn)

        self.defender_btn = IconButton(
            get_asset_path("shield.png"), "Check Defender", "#3498db", self
        )
        self.defender_btn.setFixedHeight(40)
        self.defender_btn.clicked.connect(self.check_defender_status)
        action_layout.addWidget(self.defender_btn)

        layout.addWidget(action_container)

        return tab

    def schedule_rename_or_move_on_reboot(self, source, destination):
        try:
            # Ensure source file exists
            if not os.path.exists(source):
                logger.warning(f"[⚠] Source file does not exist: {source}")
                return False
    
            # Prevent no-op if source and destination are identical
            if os.path.abspath(source) == os.path.abspath(destination):
                logger.warning("[⚠] Source and destination paths are the same. No action taken.")
                return False
    
            # Ensure destination directory exists
            dest_dir = os.path.dirname(destination)
            if not os.path.exists(dest_dir):
                os.makedirs(dest_dir, exist_ok=True)
                logger.info(f"[+] Created destination directory: {dest_dir}")
    
            # Schedule rename/move on reboot
            win32file.MoveFileEx(
                source,
                destination,
                win32file.MOVEFILE_DELAY_UNTIL_REBOOT | win32file.MOVEFILE_REPLACE_EXISTING
            )
            logger.info(f"[✅] Scheduled move/rename on reboot:\n    From: {source}\n    To:   {destination}")

            # Confirm operation was added to the registry
            def _get_pending_file_renames():
                try:
                    key = winreg.OpenKey(
                        winreg.HKEY_LOCAL_MACHINE,
                        r"SYSTEM\CurrentControlSet\Control\Session Manager",
                        0,
                        winreg.KEY_READ
                    )
                    value, _ = winreg.QueryValueEx(key, "PendingFileRenameOperations")
                    return value if value else []
                except FileNotFoundError:
                    logger.warning("No PendingFileRenameOperations found in registry.")
                    return []
                except Exception as e:
                    logger.error(f"[❌] Error reading PendingFileRenameOperations: {e}")
                    return []
    
            pending_ops = _get_pending_file_renames()
            if any(source.lower() in s.lower() and destination.lower() in s.lower() for s in pending_ops):
                logger.info("[🔐] Operation confirmed in PendingFileRenameOperations registry key.")
            else:
                logger.warning("[❗] Unable to confirm operation in registry. It may not be saved.")
    
            return True

        except Exception as e:
            logger.error(f"[❌] Failed to schedule move/rename: {e}")
            return False

    def browse_file(self):
        logger.debug("Browsing for file")
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select File", "", "All Files (*.*)"
        )
        if file_path:
            logger.info(f"Selected file: {file_path}")
            # Extract filename only
            filename = os.path.basename(file_path)
            self.path_input.setText(filename)

    def browse_folder(self):
        logger.debug("Browsing for folder")
        folder_path = QFileDialog.getExistingDirectory(self, "Select Folder")
        if folder_path:
            logger.info(f"Selected folder: {folder_path}")
            # Extract folder name only
            foldername = os.path.basename(folder_path)
            self.path_input.setText(foldername)

    def browse_force_file(self):
        logger.debug("Browsing for force file")
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select File", "", "All Files (*.*)"
        )
        if file_path:
            logger.info(f"Selected force file: {file_path}")
            self.force_path_input.setText(file_path)

    def browse_force_folder(self):
        logger.debug("Browsing for force folder")
        folder_path = QFileDialog.getExistingDirectory(self, "Select Folder")
        if folder_path:
            logger.info(f"Selected force folder: {folder_path}")
            self.force_path_input.setText(folder_path)

    def browse_monitor_file(self):
        logger.debug("Browsing for monitor file")
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select File", "", "All Files (*.*)"
        )
        if file_path:
            logger.info(f"Selected monitor file: {file_path}")
            # Extract filename only
            filename = os.path.basename(file_path)
            self.monitor_path_input.setText(filename)

    def browse_monitor_folder(self):
        logger.debug("Browsing for monitor folder")
        folder_path = QFileDialog.getExistingDirectory(self, "Select Folder")
        if folder_path:
            logger.info(f"Selected monitor folder: {folder_path}")
            # Extract folder name only
            foldername = os.path.basename(folder_path)
            self.monitor_path_input.setText(foldername)

    def scan_locks(self):
        name = self.path_input.text().strip()
        logger.info(f"Scanning locks for: {name}")
        if not name:
            error = "❌ Please enter a file or folder name"
            logger.warning(error)
            self.show_status_message(error, "#e74c3c")
            return

        # Reset UI state
        self.locks_table.setRowCount(0)

        # Show progress UI
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_label.setVisible(True)
        self.progress_label.setText("Preparing scan...")

        # Update buttons
        self.scan_btn.setVisible(False)
        self.cancel_btn.setVisible(True)

        # Start detection in a separate thread
        self.scan_in_progress = True
        self.detector = FileLockDetector(name)
        self.detector.locks_detected.connect(self.display_locks)
        self.detector.error_occurred.connect(self.handle_detection_error)
        self.detector.start()

    def cancel_scan(self):
        logger.info("Cancelling scan")
        if self.detector:
            self.detector.cancel()
        self.scan_in_progress = False
        self.reset_scan_ui()
        self.status_bar.showMessage("Scan cancelled")
        self.show_status_message("Scan cancelled", "#f39c12")

    def reset_scan_ui(self):
        logger.debug("Resetting scan UI")
        self.progress_bar.setVisible(False)
        self.progress_label.setVisible(False)
        self.scan_btn.setVisible(True)
        self.cancel_btn.setVisible(False)

    def display_locks(self, locks):
        logger.info(f"Displaying {len(locks)} locks")
        self.reset_scan_ui()
        self.active_locks = locks
        self.locks_table.setRowCount(len(locks))

        for row, lock in enumerate(locks):
            # Process name
            self.locks_table.setItem(row, 0, QTableWidgetItem(lock["name"]))

            # PID
            self.locks_table.setItem(row, 1, QTableWidgetItem(str(lock["pid"])))

            # File path
            self.locks_table.setItem(row, 2, QTableWidgetItem(lock["path"]))

            # Action buttons
            action_widget = QWidget()
            action_layout = QHBoxLayout(action_widget)
            action_layout.setContentsMargins(5, 5, 5, 5)
            action_layout.setSpacing(5)

            kill_btn = QPushButton("Kill")
            kill_btn.setStyleSheet(
                """
                QPushButton {
                    background-color: #e74c3c;
                    color: white;
                    border-radius: 4px;
                    padding: 5px 10px;
                    font-size: 11px;
                    min-width: 60px;
                }
                QPushButton:hover {
                    background-color: #c0392b;
                }
            """
            )
            kill_btn.clicked.connect(lambda _, p=lock["pid"]: self.kill_process(p))
            action_layout.addWidget(kill_btn)

            unlock_btn = QPushButton("Unlock")
            unlock_btn.setStyleSheet(
                """
                QPushButton {
                    background-color: #1abc9c;
                    color: white;
                    border-radius: 4px;
                    padding: 5px 10px;
                    font-size: 11px;
                    min-width: 60px;
                }
                QPushButton:hover {
                    background-color: #16a085;
                }
            """
            )
            unlock_btn.clicked.connect(lambda _, p=lock["pid"]: self.unlock_file(p))
            action_layout.addWidget(unlock_btn)

            self.locks_table.setCellWidget(row, 3, action_widget)

        # Save lock info to file
        self.save_lock_info(locks)

        if locks:
            msg = f"Found {len(locks)} active locks"
            logger.info(msg)
            self.status_bar.showMessage(msg)
            self.show_status_message(f"✅ {msg}", "#2ecc71")
        else:
            msg = "No active locks found"
            logger.info(msg)
            self.status_bar.showMessage(msg)
            self.show_status_message(f"✅ {msg}", "#2ecc71")
        self.scan_in_progress = False

    def save_lock_info(self, locks):
        """Save lock scan results to a persistent CSV file with detailed logging"""
        try:
            # File paths
            report_path = os.path.join(APP_DATA_DIR, "locks_report.csv")
            log_path = os.path.join(APP_DATA_DIR, "locks_report.log")

            # Setup logger for file writing
            file_logger = logging.getLogger("lock_report")
            file_logger.setLevel(logging.INFO)

            if not file_logger.handlers:
                handler = logging.FileHandler(log_path, encoding="utf-8")
                handler.setFormatter(
                    logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
                )
                file_logger.addHandler(handler)

            # Prepare data
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            scanned_name = self.path_input.text().strip() or "(No name provided)"

            # Create file if not exists
            file_exists = os.path.isfile(report_path)

            with open(report_path, "a", newline="", encoding="utf-8") as csvfile:
                writer = csv.writer(csvfile)

                # Write headers if new
                if not file_exists:
                    writer.writerow(
                        [
                            "Timestamp",
                            "Search Name",
                            "Process Name",
                            "PID",
                            "Locked File or Folder",
                        ]
                    )
                    file_logger.info("🆕 Created new lock report file.")

                if not locks:
                    writer.writerow(
                        [timestamp, scanned_name, "✅ No locks found", "-", "-"]
                    )
                    file_logger.info(f"✅ No locks found for name: {scanned_name}")
                else:
                    for lock in locks:
                        writer.writerow(
                            [
                                timestamp,
                                scanned_name,
                                lock.get("name", "Unknown"),
                                lock.get("pid", "Unknown"),
                                lock.get("path", "Unknown"),
                            ]
                        )
                    file_logger.info(
                        f"🔐 Logged {len(locks)} locks for name: {scanned_name}"
                    )

            logger.info(f"✅ Lock scan saved to CSV: {report_path}")

        except Exception as e:
            logger.error(f"❌ Error saving lock info: {e}")

    def kill_process(self, pid):
        logger.info(f"Killing process: {pid}")
        # Start termination in a separate thread
        self.terminator = ProcessTerminator(pid)
        self.terminator.process_terminated.connect(self.handle_process_termination)
        self.terminator.start()

        # Show status immediately
        self.show_status_message(f"Terminating process {pid}...", "#f39c12")

    def handle_process_termination(self, pid, success, message):
        if success:
            logger.info(f"Successfully terminated PID: {pid}")
            self.show_status_message(f"✅ Process {pid} terminated", "#2ecc71")
            # Refresh locks after delay
            QTimer.singleShot(1000, self.scan_locks)
        else:
            logger.error(f"Failed to terminate PID {pid}: {message}")
            if "Access denied" in message:
                self.show_status_message(
                    "❌ Access denied: Run as administrator", "#e74c3c"
                )
            else:
                self.show_status_message(f"❌ {message}", "#e74c3c")

    def unlock_file(self, pid):
        logger.info(f"Unlocking file for PID: {pid}")
        # In a real implementation, we'd close file handles here
        # For now, we'll just terminate the process
        self.kill_process(pid)

    def unlock_all(self):
        logger.info("Unlocking all processes")
        if not self.active_locks:
            error = "❌ No active locks to unlock"
            logger.warning(error)
            self.show_status_message(error, "#e74c3c")
            return

        success = 0
        errors = 0
        access_denied = False

        for lock in self.active_locks:
            try:
                process = psutil.Process(lock["pid"])
                process.terminate()
                try:
                    # Wait a bit to see if the process exits
                    time.sleep(0.5)
                    if process.is_running():
                        process.kill()
                    success += 1
                    logger.info(f"Unlocked PID: {lock['pid']}")
                except Exception as e:
                    logger.error(f"Error unlocking PID {lock['pid']}: {e}")
                    success += 1
            except psutil.AccessDenied:
                access_denied = True
                errors += 1
                logger.error(f"Access denied to PID: {lock['pid']}")
            except Exception as e:
                errors += 1
                logger.error(f"Error unlocking PID {lock['pid']}: {e}")

        # Show result animation
        if success > 0:
            msg = f"✅ Unlocked {success} processes"
            logger.info(msg)
            self.show_status_message(msg, "#2ecc71")
        if errors > 0:
            if access_denied:
                error = f"❌ Failed to unlock {errors} processes (access denied)"
            else:
                error = f"❌ Failed to unlock {errors} processes"
            logger.error(error)
            self.show_status_message(error, "#e74c3c")

        # Refresh locks after delay
        QTimer.singleShot(1500, self.scan_locks)

    def force_unlock_path(self, path):
        """Force unlock a path by terminating any processes locking it."""
        logger.info(f"Force unlocking: {path}")
        # Kill by path if it's an executable
        if find_and_kill_process_by_path(path):
            self.force_status.append(f"Killed process using: {path}")

        # Now scan for any locks and kill those processes
        locks = []
        try:
            # Use handle.exe for force unlocking
            raw_output = run_handle(path)
            matches = parse_handle_output(raw_output, path)

            for match in matches:
                process_name = match.get("name", "Unknown")
                pid = match.get("pid", -1)
                try:
                    process = psutil.Process(pid)
                    process.terminate()
                    try:
                        time.sleep(0.5)
                        if process.is_running():
                            process.kill()
                        self.force_status.append(
                            f"Killed process: {process_name} (PID: {pid})"
                        )
                    except Exception as e:
                        logger.error(f"Error killing process: {e}")
                except Exception as e:
                    logger.error(f"Error force unlocking: {e}")
        except Exception as e:
            logger.error(f"Error in force unlock: {e}")

        # Wait a bit for the locks to be released
        time.sleep(0.5)
    
    def perform_force_action(self):
        path = self.force_path_input.text().strip()
        logger.info(f"Performing force action on: {path}")
    
        if not path or not os.path.exists(path):
            error = "❌ Please select a valid file or folder"
            logger.warning(error)
            self.show_status_message(error, "#e74c3c")
            return
    
        operation = ""
        if self.delete_radio.isChecked():
            operation = "Delete"
        elif self.rename_radio.isChecked():
            operation = "Rename"
        elif self.move_radio.isChecked():
            operation = "Move"
    
        schedule = self.schedule_reboot.isChecked()
        logger.debug(f"Operation: {operation}, Schedule: {schedule}")
    
        if self.kill_by_name.isChecked():
            file_name = os.path.basename(path)
            base_name = os.path.splitext(file_name)[0]
            killed_count = kill_processes_by_name(base_name)
            self.force_status.append(f"Killed {killed_count} processes with name: {base_name}")
            logger.info(f"Killed {killed_count} processes with name: {base_name}")
    
        self.force_unlock_path(path)
    
        try:
            if operation == "Delete":
                if os.path.isdir(path):
                    if schedule:
                        self.schedule_delete_on_reboot(path)
                        self.force_status.append(f"Scheduled directory for deletion on next reboot: {path}")
                    else:
                        shutil.rmtree(path)
                        self.force_status.append(f"Successfully deleted directory: {path}")
                else:
                    if schedule:
                        self.schedule_delete_on_reboot(path)
                        self.force_status.append(f"Scheduled file for deletion on next reboot: {path}")
                    else:
                        os.remove(path)
                        self.force_status.append(f"Successfully deleted file: {path}")
                self.show_status_message(f"✅ {operation} completed successfully", "#2ecc71")
    
            elif operation == "Rename":
                new_name = self.additional_input.text().strip()
                if not new_name:
                    self.show_status_message("❌ Please enter a new name", "#e74c3c")
                    return
    
                base, ext = os.path.splitext(path)
                if not os.path.splitext(new_name)[1]:
                    new_name += ext  # Keep original extension if missing
    
                new_path = os.path.join(os.path.dirname(path), new_name)
    
                if os.path.exists(new_path):
                    self.show_status_message("❌ A file with the new name already exists", "#e74c3c")
                    QMessageBox.warning(self, "Rename Conflict", f"The file '{new_name}' already exists. Please choose a different name.")
                    self.additional_input.clear()
                    return
    
                if schedule:
                    if self.schedule_rename_or_move_on_reboot(path, new_path):
                        self.force_status.append(f"Scheduled rename on reboot: {path} → {new_path}")
                        self.show_status_message("✅ Rename scheduled for next reboot", "#2ecc71")
                    else:
                        self.show_status_message("❌ Failed to schedule rename", "#e74c3c")
                else:
                    os.rename(path, new_path)
                    self.force_status.append(f"Renamed to: {new_path}")
                    self.show_status_message(f"✅ Renamed to {new_name}", "#2ecc71")
    
            elif operation == "Move":
                dest = self.additional_input.text().strip()
                if not dest:
                    self.show_status_message("❌ Please enter a destination path", "#e74c3c")
                    return
    
                if os.path.isdir(dest):
                    dest = os.path.join(dest, os.path.basename(path))
    
                if os.path.exists(dest):
                    self.show_status_message("❌ Destination already exists", "#e74c3c")
                    QMessageBox.warning(self, "Move Conflict", f"The destination '{dest}' already exists. Please choose a different location.")
                    self.additional_input.clear()
                    return
    
                if schedule:
                    if self.schedule_rename_or_move_on_reboot(path, dest):
                        self.force_status.append(f"Scheduled move on reboot: {path} → {dest}")
                        self.show_status_message("✅ Move scheduled for next reboot", "#2ecc71")
                    else:
                        self.show_status_message("❌ Failed to schedule move", "#e74c3c")
                else:
                    shutil.move(path, dest)
                    self.force_status.append(f"Moved to: {dest}")
                    self.show_status_message(f"✅ Moved to {dest}", "#2ecc71")
    
        except PermissionError:
            error = "❌ Access denied. File may be in use by another process."
            self.force_status.append(error)
            self.show_status_message(error, "#e74c3c")
            logger.error(error)
    
        except Exception as e:
            error = f"❌ Error: {str(e)}"
            self.force_status.append(error)
            self.show_status_message(error, "#e74c3c")
            logger.error(error)

    def schedule_rename_or_move_on_reboot(self, source, destination, rename_field=None):
        try:
            if not os.path.exists(source):
                QMessageBox.warning(self, "Source Missing", f"The source file/folder does not exist:\n{source}")
                return False
    
            # Preserve extension if only renaming (i.e., same folder, different name)
            if os.path.isdir(source):
                is_file = False
            else:
                is_file = True
    
            # Check if user forgot extension (only if it's a file)
            if is_file and not os.path.splitext(destination)[1]:
                _, ext = os.path.splitext(source)
                destination += ext
                logger.info(f"No extension specified. Auto-appending original extension: {ext}")
    
            # Prevent overwrite of existing destination file
            if os.path.exists(destination):
                QMessageBox.warning(
                    self,
                    "Destination Exists",
                    f"A file/folder already exists at the destination:\n{destination}\n\nPlease choose a new name or location.",
                )
                if rename_field:
                    rename_field.clear()
                return False
    
            dest_dir = os.path.dirname(destination)
            if not os.path.exists(dest_dir):
                os.makedirs(dest_dir, exist_ok=True)
                logger.info(f"Created destination directory: {dest_dir}")
    
            win32file.MoveFileEx(
                source,
                destination,
                win32file.MOVEFILE_DELAY_UNTIL_REBOOT | win32file.MOVEFILE_REPLACE_EXISTING
            )
            logger.info(f"Scheduled move/rename: {source} → {destination}")
            return True
    
        except Exception as e:
            logger.error(f"Failed to schedule move/rename: {e}")
            QMessageBox.critical(self, "Error", f"Failed to schedule operation:\n{e}")
            return False
    
    def schedule_delete_on_reboot(self, path):
        try:
            win32file.MoveFileEx(
                path,
                None,
                win32file.MOVEFILE_DELAY_UNTIL_REBOOT
                | win32file.MOVEFILE_REPLACE_EXISTING,
            )
            self.force_status.append("✅ Operation scheduled for next reboot")
            logger.info(f"Scheduled for reboot: {path}")
        except Exception as e:
            error = f"❌ Failed to schedule: {str(e)}"
            self.force_status.append(error)
            logger.error(error)

    def toggle_monitoring(self):
        name = self.monitor_path_input.text().strip()
        logger.info(f"Toggling monitoring for: {name}")
        if not name:
            error = "❌ Please enter a file or folder name"
            logger.warning(error)
            self.show_status_message(error, "#e74c3c")
            return

        if not self.monitoring:
            # Start monitoring
            logger.info("Starting monitoring")
            try:
                self.monitor_btn.setIcon(get_asset_path("stop.png"))
            except Exception as e:
                logger.error(f"Error loading stop icon: {e}")
                self.monitor_btn.setIcon(
                    create_fallback_pixmap(24, 24, QColor(231, 76, 60))
                )
            self.monitor_btn.setText("Stop Monitoring")
            self.monitor_btn.setStyleSheet(
                self.monitor_btn.styleSheet().replace("#3498db", "#e74c3c")
            )
            self.monitor_log.append(
                f"[{datetime.now().strftime('%H:%M:%S')}] Starting monitoring: {name}"
            )

            self.monitor_thread = FileMonitor(name)
            self.monitor_thread.lock_detected.connect(self.monitor_log.append)
            self.monitor_thread.status_update.connect(self.monitor_log.append)
            self.monitor_thread.start()
            self.monitoring = True
        else:
            # Stop monitoring
            logger.info("Stopping monitoring")
            try:
                self.monitor_btn.setIcon(get_asset_path("monitor.png"))
            except Exception as e:
                logger.error(f"Error loading monitor icon: {e}")
                self.monitor_btn.setIcon(
                    create_fallback_pixmap(24, 24, QColor(52, 152, 219))
                )
            self.monitor_btn.setText("Start Monitoring")
            self.monitor_btn.setStyleSheet(
                self.monitor_btn.styleSheet().replace("#e74c3c", "#3498db")
            )
            self.monitor_log.append(
                f"[{datetime.now().strftime('%H:%M:%S')}] Monitoring stopped"
            )

            if self.monitor_thread:
                self.monitor_thread.stop()
                self.monitor_thread.quit()
                self.monitor_thread.wait(1000)
            self.monitoring = False

    def save_log(self):
        logger.info("Saving log")
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save Log File", "", "Text Files (*.txt)"
        )
        if file_path:
            try:
                with open(file_path, "w") as f:
                    f.write(self.monitor_log.toPlainText())
                self.show_status_message("✅ Log saved successfully", "#2ecc71")
                logger.info(f"Log saved to: {file_path}")
            except Exception as e:
                error = f"❌ Error saving log: {str(e)}"
                self.show_status_message(error, "#e74c3c")
                logger.error(error)

    def load_settings(self):
        logger.info("Loading settings")
        self.settings = {}
        try:
            settings_path = os.path.join(
                os.path.dirname(os.path.abspath(__file__)), "settings.json"
            )
            if os.path.exists(settings_path):
                with open(settings_path, "r") as f:
                    settings = json.load(f)
                    self.settings = settings
                    theme = settings.get("theme", "dark")
                    self.current_theme = theme
                    self.theme_combo.setCurrentText(theme.capitalize())
                    self.ui_animations_enabled = settings.get("animations", True)
                    self.animation_toggle.setChecked(self.ui_animations_enabled)
                    self.auto_elevate.setChecked(settings.get("auto_elevate", True))
                    self.log_level.setCurrentText(settings.get("log_level", "Normal"))
                    self.apply_theme(theme)
                logger.info(f"Settings loaded from: {settings_path}")
            else:
                logger.info("No settings file found, using defaults")
        except Exception as e:
            logger.error(f"Error loading settings: {e}")

    def save_settings(self):
        logger.info("Saving settings")
        try:
            settings = {
                "theme": self.current_theme,
                "animations": self.animation_toggle.isChecked(),
                "auto_elevate": self.auto_elevate.isChecked(),
                "log_level": self.log_level.currentText(),
                "explorer_integration": self.settings.get("explorer_integration"),
            }
            self.settings = settings

            settings_path = os.path.join(
                os.path.dirname(os.path.abspath(__file__)), "settings.json"
            )
            with open(settings_path, "w") as f:
                json.dump(settings, f)

            self.ui_animations_enabled = settings["animations"]
            self.show_status_message("✅ Settings saved successfully", "#2ecc71")
            logger.info(f"Settings saved to: {settings_path}")
        except Exception as e:
            error = f"❌ Error saving settings: {str(e)}"
            self.show_status_message(error, "#e74c3c")
            logger.error(error)

    def show_status_message(self, message, color):
        if not self.ui_animations_enabled:
            self.status_bar.showMessage(message)
            return

        logger.debug(f"Showing status message: {message}")
        # Create a floating status message
        status_label = QLabel(message, self)
        status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        status_label.setStyleSheet(
            f"""
            background-color: {color};
            color: white;
            font-weight: bold;
            border-radius: 15px;
            padding: 15px;
            font-size: 14px;
        """
        )

        # Position at bottom of window
        status_label.setGeometry(self.width() // 2 - 200, self.height() - 150, 400, 60)

        # Add shadow
        shadow = QGraphicsDropShadowEffect(status_label)
        shadow.setBlurRadius(20)
        shadow.setColor(QColor(0, 0, 0, 150))
        shadow.setOffset(0, 5)
        status_label.setGraphicsEffect(shadow)

        # Create animation group
        group = QSequentialAnimationGroup()

        # Fade in
        effect = QGraphicsOpacityEffect(status_label)
        effect.setOpacity(0)
        status_label.setGraphicsEffect(effect)

        fade_in = QPropertyAnimation(effect, b"opacity")
        fade_in.setDuration(500)
        fade_in.setStartValue(0)
        fade_in.setEndValue(1)
        fade_in.setEasingCurve(QEasingCurve.Type.OutCubic)
        group.addAnimation(fade_in)

        # Stay visible
        pause = QPropertyAnimation(status_label, b"geometry")
        pause.setDuration(2000)
        pause.setStartValue(status_label.geometry())
        pause.setEndValue(status_label.geometry())
        group.addAnimation(pause)

        # Fade out
        fade_out = QPropertyAnimation(effect, b"opacity")
        fade_out.setDuration(500)
        fade_out.setStartValue(1)
        fade_out.setEndValue(0)
        fade_out.setEasingCurve(QEasingCurve.Type.OutCubic)
        group.addAnimation(fade_out)

        # Clean up after animation
        group.finished.connect(lambda: status_label.deleteLater())

        # Show and animate
        status_label.show()
        group.start()

    def handle_detection_error(self, error):
        logger.error(f"Detection error: {error}")
        self.reset_scan_ui()
        self.scan_in_progress = False
        self.show_status_message(f"❌ Scan error: {error}", "#e74c3c")

    def change_theme(self, theme_name):
        theme = theme_name.lower()
        logger.info(f"Changing theme to: {theme}")
        self.current_theme = theme
        self.apply_theme(theme)
        self.update_background()

    def apply_theme(self, theme_name):
        theme_settings = {
            "dark": {
                "background": "#2c3e50",
                "text": "#ecf0f1",
                "button": "#3498db",
                "header": "#1a2a3a"
            },
            "light": {
                "background": "#ecf0f1",
                "text": "#2c3e50",
                "button": "#3498db",
                "header": "#bdc3c7"
            },
            "blue": {
                "background": "#2c3e50",
                "text": "#ecf0f1",
                "button": "#2980b9",
                "header": "#1a5276"
            },
            "purple": {
                "background": "#2c3e50",
                "text": "#ecf0f1",
                "button": "#8e44ad",
                "header": "#4a235a"
            }
        }
        
        theme = theme_settings.get(theme_name, theme_settings["dark"])
        
        self.setStyleSheet(f"""
            QMainWindow {{
                background-color: {theme['background']};
            }}
            QLabel {{
                color: {theme['text']};
            }}
            QPushButton {{
                background-color: {theme['button']};
                color: white;
            }}
            QHeaderView::section {{
                background-color: {theme['header']};
                color: white;
            }}
            QTabWidget::pane {{
                background: {theme['background']};
            }}
            QGroupBox {{
                color: {theme['button']};
            }}
        """)
        
        # Update status bar
        self.status_bar.setStyleSheet(f"""
            background: {theme['header']}; 
            color: {theme['text']}; 
            border-top: 1px solid {theme['button']};
        """)
        
        # Update background
        self.update_background()
        
        # Update theme button
        self.theme_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {theme['button']};
                border-radius: 20px;
                border: none;
            }}
            QPushButton:hover {{
                background-color: {QColor(theme['button']).darker(120).name()};
            }}
        """)

    def toggle_theme(self):
        logger.info("Toggling theme")
        if self.current_theme == "dark":
            self.apply_theme("light")
            self.current_theme = "light"
            self.theme_combo.setCurrentText("Light")
        else:
            self.apply_theme("dark")
            self.current_theme = "dark"
            self.theme_combo.setCurrentText("Dark")
        self.update()

    def check_defender_status(self):
        logger.info("Checking Defender status")
        try:
            # This is a simulated check - in a real app you would check Defender status
            dialog = QDialog(self)
            dialog.setWindowTitle("Defender Status")
            dialog.setFixedSize(400, 200)

            layout = QVBoxLayout(dialog)

            status = QLabel(
                "Windows Defender is active\nReal-time protection is enabled"
            )
            status.setStyleSheet("font-size: 14px; color: #2c3e50;")
            layout.addWidget(status, 0, Qt.AlignmentFlag.AlignCenter)

            close_btn = QPushButton("OK")
            close_btn.setStyleSheet(
                """
                QPushButton {
                    background-color: #3498db;
                    color: white;
                    border-radius: 6px;
                    padding: 8px 20px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #2980b9;
                }
            """
            )
            close_btn.clicked.connect(dialog.accept)
            layout.addWidget(close_btn, 0, Qt.AlignmentFlag.AlignCenter)

            dialog.exec()
        except Exception as e:
            error = f"❌ Error checking Defender status: {str(e)}"
            logger.error(error)
            self.show_status_message(error, "#e74c3c")

    def show_about(self):
        if not self.ui_animations_enabled:
            self.show_simple_about()
            return
            
        logger.info("Showing about dialog")
        dialog = QDialog(self)
        dialog.setWindowTitle("About Secure File Unlocker")
        dialog.setFixedSize(600, 700)
        dialog.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        dialog.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    
        # Main layout with centering
        main_layout = QVBoxLayout(dialog)
        main_layout.setContentsMargins(40, 40, 40, 40)
        main_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
    
        # Shadow container with animation-safe effects
        shadow_container = QFrame()
        shadow_container.setObjectName("aboutShadowContainer")
        shadow_container.setStyleSheet("""
            #aboutShadowContainer {
                background: transparent;
                border-radius: 18px;
            }
        """)
        
        # Enhanced shadow effect
        shadow_effect = QGraphicsDropShadowEffect()
        shadow_effect.setBlurRadius(50)
        shadow_effect.setColor(QColor(0, 0, 0, 180))
        shadow_effect.setOffset(0, 5)
        shadow_container.setGraphicsEffect(shadow_effect)
        
        shadow_layout = QVBoxLayout(shadow_container)
        shadow_layout.setContentsMargins(0, 0, 0, 0)
        shadow_layout.setSpacing(0)
    
        # Main content frame
        content = QFrame()
        content.setObjectName("aboutContent")
        content.setStyleSheet("""
            #aboutContent {
                border-radius: 18px;
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:1,
                    stop:0 #232526, stop:0.5 #4f2c2c, stop:1 #ff512f
                );
                border: 2px solid rgba(255,255,255,0.15);
            }
        """)
        
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
    
        # Title bar with improved styling
        title_bar = QWidget()
        title_bar.setFixedHeight(48)
        title_bar.setStyleSheet("""
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #1a2a6c, stop:1 #ff512f);
            border-top-left-radius: 18px;
            border-top-right-radius: 18px;
        """)
        
        title_layout = QHBoxLayout(title_bar)
        title_layout.setContentsMargins(18, 0, 12, 0)
    
        icon_label = QLabel()
        pixmap = QPixmap(get_asset_path("unlock.png"))
        if pixmap.isNull():
            pixmap = QPixmap(32, 32)
            pixmap.fill(Qt.GlobalColor.gray)
        icon_label.setPixmap(pixmap.scaled(32, 32, 
            Qt.AspectRatioMode.KeepAspectRatio, 
            Qt.TransformationMode.SmoothTransformation))
        icon_label.setFixedSize(32, 32)
        title_layout.addWidget(icon_label)
    
        title_text = QLabel("About Secure File Unlocker")
        title_text.setStyleSheet("""
            color: white; 
            font-size: 18px; 
            font-weight: bold; 
            padding-left: 10px;
        """)
        title_layout.addWidget(title_text, alignment=Qt.AlignmentFlag.AlignLeft)
        title_layout.addStretch()
    
        close_btn = QPushButton("✕")
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setFixedSize(28, 28)
        close_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: white;
                font-size: 18px;
                border: none;
                border-radius: 14px;
            }
            QPushButton:hover {
                background: #e74c3c;
            }
        """)
        close_btn.clicked.connect(dialog.reject)
        title_layout.addWidget(close_btn)
    
        content_layout.addWidget(title_bar)
    
        # Scroll area with custom scrollbars
        content_scroll = QScrollArea()
        content_scroll.setWidgetResizable(True)
        content_scroll.setStyleSheet("""
            QScrollArea {
                background: transparent;
                border: none;
            }
            QScrollBar:vertical {
                background: rgba(255, 255, 255, 0.1);
                width: 10px;
                margin: 0;
                border-radius: 5px;
            }
            QScrollBar::handle:vertical {
                background: rgba(255, 255, 255, 0.4);
                border-radius: 5px;
                min-height: 30px;
            }
            QScrollBar::handle:vertical:hover {
                background: rgba(255, 255, 255, 0.6);
            }
            QScrollBar::add-line:vertical, 
            QScrollBar::sub-line:vertical {
                height: 0;
                background: none;
            }
        """)
    
        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setContentsMargins(40, 30, 40, 30)
        scroll_layout.setSpacing(20)
    
        # Logo with animation
        logo_label = QLabel()
        logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pixmap = QPixmap(get_asset_path("unlock.png"))
        if pixmap.isNull():
            pixmap = QPixmap(100, 100)
            pixmap.fill(Qt.GlobalColor.gray)
        logo_label.setPixmap(pixmap.scaled(100, 100, 
            Qt.AspectRatioMode.KeepAspectRatio, 
            Qt.TransformationMode.SmoothTransformation))
        scroll_layout.addWidget(logo_label, alignment=Qt.AlignmentFlag.AlignCenter)
    
        # App title
        app_title = QLabel("Secure File Unlocker")
        app_title.setFont(QFont("Segoe UI", 24, QFont.Weight.Bold))
        app_title.setStyleSheet("""
            color: white; 
            letter-spacing: 1px;
            padding-top: 10px;
        """)
        app_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        scroll_layout.addWidget(app_title)
    
        # Version
        version = QLabel("Version 2.0")
        version.setStyleSheet("""
            font-size: 16px; 
            color: #a0d2ff;
            padding-bottom: 15px;
        """)
        version.setAlignment(Qt.AlignmentFlag.AlignCenter)
        scroll_layout.addWidget(version)
    
        # Usage instructions
        usage = QLabel(
            "<b>HOW TO USE:</b><br><br>"
            "1. Select the file or folder that is locked.<br>"
            "2. Click <i>'Scan'</i> to detect the processes using the file.<br>"
            "3. Review the list of detected locks.<br>"
            "4. Click <i>'Unlock All'</i> to release the file from all safe processes."
        )
        usage.setStyleSheet("""
            background-color: rgba(255,255,255,0.10);
            border-radius: 14px;
            padding: 18px;
            font-size: 14px;
            border-left: 4px solid #4facfe;
            color: #fff;
            text-align: left;
        """)
        usage.setWordWrap(True)
        usage.setAlignment(Qt.AlignmentFlag.AlignCenter)
        scroll_layout.addWidget(usage)
    
        # Developer Info
        dev = QLabel("Developed by The_studio725")
        dev.setStyleSheet("""
            font-size: 18px; 
            font-weight: bold; 
            color: white;
            padding-top: 20px;
        """)
        dev.setAlignment(Qt.AlignmentFlag.AlignCenter)
        scroll_layout.addWidget(dev)
    
        # YouTube link
        yt = QLabel('<a href="https://www.youtube.com/@The_studio725" style="color: #00acee; text-decoration: none;">📺 Visit YouTube</a>')
        yt.setOpenExternalLinks(True)
        yt.setStyleSheet("font-size: 15px;")
        yt.setAlignment(Qt.AlignmentFlag.AlignCenter)
        scroll_layout.addWidget(yt)
    
        # Email
        email = QLabel("✉️ studiocoding09@gmail.com")
        email.setStyleSheet("""
            font-size: 15px; 
            color: white;
            padding: 8px 0 20px 0;
        """)
        email.setAlignment(Qt.AlignmentFlag.AlignCenter)
        scroll_layout.addWidget(email)
    
        # Close button
        close_btn2 = QPushButton("Close")
        close_btn2.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn2.setFixedHeight(42)
        close_btn2.setMinimumWidth(180)
        close_btn2.setStyleSheet("""
            QPushButton {
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:0, 
                    stop:0 #FF512F, stop:1 #F09819
                );
                color: white;
                border-radius: 10px;
                font-weight: bold;
                font-size: 16px;
                border: none;
                padding: 8px 16px;
            }
            QPushButton:hover {
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:0, 
                    stop:0 #e74c3c, stop:1 #e67e22
                );
            }
        """)
        close_btn2.clicked.connect(dialog.accept)
        scroll_layout.addWidget(close_btn2, alignment=Qt.AlignmentFlag.AlignHCenter)
    
        scroll_layout.addStretch(1)
        content_scroll.setWidget(scroll_content)
        content_layout.addWidget(content_scroll)
        shadow_layout.addWidget(content)
        main_layout.addWidget(shadow_container)
    
        dialog.exec()
        
    def show_simple_about(self):
        logger.info("Showing simple about dialog (animations disabled)")
        QMessageBox.about(self, "About Secure File Unlocker", 
            "Secure File Unlocker\nVersion 2.0\n\n"
            "Developed by The_studio725\n\n"
            "YouTube: https://www.youtube.com/@The_studio725\n"
            "Email: studiocoding09@gmail.com")

def main():
    logger.info("Application starting")
    if "--help" in sys.argv or "-h" in sys.argv:
        print("LockLift commands:")
        print('  --unlock "PATH"        Review and close lock owners')
        print('  --force-delete "PATH" Ask how to delete a path')
        print('  --silent "PATH"       Close all safe lock owners')
        print("  --register-explorer   Add File Explorer actions")
        print("  --unregister-explorer Remove File Explorer actions")
        return
    if "--register-explorer" in sys.argv:
        set_explorer_integration(True)
        return
    if "--unregister-explorer" in sys.argv:
        set_explorer_integration(False)
        return
    action = None
    for name in ("--unlock", "--force-delete", "--silent"):
        if name in sys.argv:
            action = name
            break
    if action in ("--unlock", "--force-delete"):
        index = sys.argv.index(action)
        path = sys.argv[index + 1] if index + 1 < len(sys.argv) else ""
        if not path or not os.path.exists(path):
            print(f"Path not found: {path}")
            return 2
        if not is_admin() and "--elevated" not in sys.argv:
            elevate_if_needed()
            return
        if action == "--unlock":
            raise SystemExit(run_unlock_dialog(path))
        raise SystemExit(run_force_delete_dialog(path))
    if "--silent" in sys.argv:
        index = sys.argv.index("--silent")
        path = sys.argv[index + 1] if index + 1 < len(sys.argv) else ""
        if not path or not os.path.exists(path):
            print(f"Path not found: {path}")
            return 2
        if not is_admin() and "--elevated" not in sys.argv:
            elevate_if_needed()
            return
        raise SystemExit(silent_unlock(path))
    if not elevate_if_needed():
        logger.error("Elevation failed, exiting")
        return  # Prevents continuing if elevation is pending

    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    # Show splash screen
    logger.info("Showing splash screen")
    splash = SplashScreen()
    splash.exec()

    # Create and show main window
    logger.info("Creating main window")
    window = UnlockerApp()
    window.show()
    window.raise_()
    window.activateWindow()
    # Open in fullscreen
    window.setWindowTitle("Ultimate File & Folder Unlocker")  # Optional: set title
    window.resize(1280, 800)  # Initial size

    # Center the window on screen before showing
    screen_geometry = QGuiApplication.primaryScreen().availableGeometry()
    x = (screen_geometry.width() - window.width()) // 2
    y = (screen_geometry.height() - window.height()) // 2
    window.move(x, y)
    window.showMaximized()  # Starts maximized (not fullscreen!)

    # Play sound on open
    try:
        import pygame
        pygame.mixer.init()
        pygame.mixer.music.load(get_asset_path("startup.mp3"))  # now you can use mp3
        pygame.mixer.music.set_volume(1.0)  # Max volume (0.0 to 1.0)
        pygame.mixer.music.play()
    except:
        winsound.Beep(800, 500)

    logger.info("Main window shown")

    sys.exit(app.exec())


if __name__ == "__main__":
    main()