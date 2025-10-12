import sys
import subprocess
import os
import platform
import json
import signal
import webbrowser
import requests

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QPushButton,
    QVBoxLayout, QGridLayout, QLabel, QMessageBox, QFrame, QHBoxLayout,
    QDialog, QDialogButtonBox, QCheckBox, QLineEdit, QFileDialog
)
from PySide6.QtGui import QFont, QCursor, QColor, QPainter, QBrush, QIcon, QResizeEvent
from PySide6.QtCore import (
    Qt, QTimer, QObject, Signal, QThread, QPropertyAnimation, QPoint, QEasingCurve,
    Property
)

# --- NEW: Application Version Constant ---
# Change this value for each new release.
APP_VERSION = "1.2"

# --- PYINSTALLER HELPER FUNCTION ---
def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        # _MEIPASS is not defined, so we are running in a normal Python environment
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)


# --- Update Checker Worker ---
class UpdateChecker(QObject):
    update_available = Signal(str, str)

    def __init__(self, current_version):
        super().__init__()
        self.current_version = current_version
        self.api_url = "https://api.github.com/repos/cfopuser/mtk-root-control/releases/latest"

    def run(self):
        try:
            response = requests.get(self.api_url, timeout=5)
            response.raise_for_status()
            
            latest_release = response.json()
            latest_version = latest_release.get("tag_name", "0.0.0")
            download_url = latest_release.get("html_url", "")

            latest_v = latest_version.lstrip('v')
            current_v = self.current_version.lstrip('v')

            if tuple(map(int, latest_v.split('.'))) > tuple(map(int, current_v.split('.'))):
                print(f"Update found: {latest_version}")
                self.update_available.emit(latest_version, download_url)

        except requests.exceptions.RequestException as e:
            print(f"Could not check for updates: {e}")
        except Exception as e:
            print(f"An error occurred during update check: {e}")

# --- Configuration File Handling ---
CONFIG_FILE = 'app_config.json'

def load_config():
    if not os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'w') as f:
            json.dump({'drivers_installed': False}, f)
        return {'drivers_installed': False}
    try:
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        return {'drivers_installed': False}

def save_config(config):
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=4)


# --- Worker for Running Commands ---
class CommandRunner(QObject):
    finished = Signal(int, str)
    error = Signal(str, str)

    def __init__(self):
        super().__init__()
        self.process = None
        self._is_stopping = False

    def run_command(self, command, title):
        self._is_stopping = False
        try:
            popen_kwargs = {
                'shell': True,
                'stdout': subprocess.PIPE,
                'stderr': subprocess.PIPE,
                'text': True,
                'encoding': 'utf-8',
                'errors': 'ignore'
            }
            if os.name == 'nt':
                popen_kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW
            else:
                popen_kwargs['preexec_fn'] = os.setsid

            self.process = subprocess.Popen(command, **popen_kwargs)
            
            stdout, stderr = self.process.communicate()
            return_code = self.process.returncode

            if self._is_stopping:
                self.finished.emit(-9, "user_stopped")
                return
            
            if return_code != 0:
                error_output = (stderr or "") + (stdout or "")
                self.error.emit(f"Error running '{title}':\n{error_output.strip()}", command)
            
            self.finished.emit(return_code, command)

        except Exception as e:
            if not self._is_stopping:
                self.error.emit(f"An unexpected error occurred: {e}", command)
            self.finished.emit(-1, command)
        finally:
            self.process = None

    def stop_command(self):
        if self.process and self.process.poll() is None:
            print("Stop command requested by user.")
            self._is_stopping = True
            pid = self.process.pid
            try:
                if os.name == 'nt':
                    subprocess.run(
                        f"taskkill /F /T /PID {pid}",
                        shell=True, check=True, capture_output=True
                    )
                else:
                    os.killpg(os.getpgid(pid), signal.SIGKILL)
            except (subprocess.CalledProcessError, OSError) as e:
                print(f"Could not stop process {pid}. It might have already finished. Error: {e}")


# --- Custom Dialogs ---
class CustomDialog(QDialog):
    def __init__(self, parent, title, text):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(400)
        self.setStyleSheet("""
            QDialog {
                background-color: #262626; border: 1px solid #00ff7f;
                border-radius: 15px; font-family: 'Consolas', 'Courier New', monospace;
            }
            QLabel { color: #f0f0f0; font-size: 16px; }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(25, 25, 25, 25)
        layout.setSpacing(20)

        self.message_label = QLabel(text)
        self.message_label.setWordWrap(True)
        self.message_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.message_label)

        button_box = QDialogButtonBox()
        ok_button = QPushButton("אישור")
        ok_button.setCursor(QCursor(Qt.PointingHandCursor))
        ok_button.setStyleSheet("""
            QPushButton {
                background-color: #00ff7f; color: #1a1a1a; font-size: 14px;
                font-weight: bold; padding: 10px 25px; border-radius: 8px; min-width: 90px;
            }
            QPushButton:hover { background-color: #00cc66; }
        """)
        button_box.addButton(ok_button, QDialogButtonBox.AcceptRole)
        button_box.accepted.connect(self.accept)
        button_box.setCenterButtons(True)
        layout.addWidget(button_box)

class UpdateDialog(QDialog):
    def __init__(self, parent, new_version, download_url):
        super().__init__(parent)
        self.setWindowTitle("קיים עדכון")
        self.download_url = download_url
        self.setModal(True)
        self.setMinimumWidth(450)
        self.setStyleSheet("""
            QDialog {
                background-color: #262626; border: 1px solid #00ff7f;
                border-radius: 15px; font-family: 'Consolas', 'Courier New', monospace;
            }
            QLabel { color: #f0f0f0; font-size: 16px; }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(25, 25, 25, 25)
        layout.setSpacing(20)

        message = f"גרסה חדשה ({new_version}) זמינה!\nמומלץ לעדכן לקבלת התיקונים והתכונות האחרונות."
        self.message_label = QLabel(message)
        self.message_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.message_label)

        button_box = QDialogButtonBox()
        download_button = QPushButton("הורדה")
        later_button = QPushButton("אחר כך")

        download_button.setCursor(QCursor(Qt.PointingHandCursor))
        later_button.setCursor(QCursor(Qt.PointingHandCursor))

        download_button.setStyleSheet("""
            QPushButton {
                background-color: #00ff7f; color: #1a1a1a; font-size: 14px;
                font-weight: bold; padding: 10px 25px; border-radius: 8px; min-width: 90px;
            }
            QPushButton:hover { background-color: #00cc66; }
        """)
        later_button.setStyleSheet("""
            QPushButton {
                background-color: #555; color: #f0f0f0; font-size: 14px;
                font-weight: bold; padding: 10px 25px; border-radius: 8px; min-width: 90px;
            }
            QPushButton:hover { background-color: #666; }
        """)

        button_box.addButton(download_button, QDialogButtonBox.AcceptRole)
        button_box.addButton(later_button, QDialogButtonBox.RejectRole)
        button_box.accepted.connect(self.download)
        button_box.rejected.connect(self.reject)
        button_box.setCenterButtons(True)
        layout.addWidget(button_box)

    def download(self):
        webbrowser.open(self.download_url)
        self.accept()

# --- WelcomeWindow Class ---
class WelcomeWindow(QMainWindow):
    def __init__(self, main_tool_window):
        super().__init__()
        self.main_tool_window = main_tool_window
        self.setWindowIcon(QIcon(resource_path('mtk_icon.ico')))
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle("ברוכים הבאים - התקנת דרייברים")
        self.setMinimumSize(800, 500)
        self.setStyleSheet("background-color: #1a1a1a;")

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setAlignment(Qt.AlignCenter)
        main_layout.setSpacing(25)
        main_layout.setContentsMargins(50, 20, 50, 20)

        title_label = QLabel("ברוכים הבאים לכלי ה-MTK")
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setStyleSheet("""
            color: #00ff7f; font-size: 32px; font-weight: bold;
            font-family: 'Consolas', 'Courier New', monospace;
        """)

        info_label = QLabel("לפני שמתחילים, יש להתקין את הדרייברים הנדרשים.\nשלב זה הוא חד פעמי וחיוני לפעולת התוכנה.")
        info_label.setAlignment(Qt.AlignCenter)
        info_label.setStyleSheet("color: #f0f0f0; font-size: 18px;")

        self.status_label = QLabel()
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setStyleSheet("color: #ffaa00; font-size: 16px; font-weight: bold;")

        self.install_button = QPushButton("התקן דרייברים")
        self.install_button.setMinimumHeight(60)
        self.install_button.setStyleSheet("""
            QPushButton {
                background-color: #00ff7f; color: #1a1a1a;
                font-size: 18px; font-weight: bold;
                padding: 15px; border-radius: 8px;
            }
            QPushButton:hover { background-color: #00cc66; }
        """)
        self.install_button.clicked.connect(self.run_driver_installation)
        
        self.skip_button = QPushButton("דלג")
        self.skip_button.setCursor(QCursor(Qt.PointingHandCursor))
        self.skip_button.setStyleSheet("""
            QPushButton {
                background-color: transparent; color: #888;
                font-size: 14px; border: none; padding: 5px;
            }
            QPushButton:hover { color: #bbb; text-decoration: underline; }
        """)
        self.skip_button.clicked.connect(self.skip_to_main_window)

        main_layout.addWidget(title_label)
        main_layout.addWidget(info_label)
        main_layout.addStretch(1)
        main_layout.addWidget(self.install_button)
        main_layout.addWidget(self.status_label)
        main_layout.addStretch(1)
        
        skip_layout = QHBoxLayout()
        skip_layout.addStretch()
        skip_layout.addWidget(self.skip_button)
        skip_layout.addStretch()
        main_layout.addLayout(skip_layout)


    def run_driver_installation(self):
        try:
            CustomDialog(self, "התקנת דרייבר MTK", "חלון התקנת דרייבר MTK יפתח כעת. אנא עקוב אחר ההוראות.").exec()
            mtk_exe_path = resource_path("mtk.exe")
            self.run_command(f'"{mtk_exe_path}"', "התקנת דרייבר MTK")

            driver_path = ''
            if platform.machine().endswith('64'):
                CustomDialog(self, 'התקנת דרייבר Fastboot', 'חלון התקנת דרייבר Fastboot יפתח כעת. אנא עקוב אחר ההוראות.').exec()
                driver_exe = resource_path(os.path.join("driver", "DPInst_x64"))
                driver_path = f'"{driver_exe}" /f'
            else:
                CustomDialog(self, 'התקנת דרייבר Fastboot', 'חלון התקנת דרייבר Fastboot יפתח כעת. אנא עקוב אחר ההוראות.').exec()
                driver_exe = resource_path(os.path.join("driver", "DPInst_x86"))
                driver_path = f'"{driver_exe}" /f'

            self.run_command(driver_path, "התקנת דרייבר Fastboot")

            config = load_config()
            config['drivers_installed'] = True
            save_config(config)
            
            CustomDialog(self, "הצלחה", "התקנת הדרייברים הושלמה!\nהכלי הראשי יפתח כעת.").exec()
            
            self.proceed_to_main_window()

        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            self.status_label.setText(f"התקנת הדרייברים נכשלה. אנא נסה שוב או דלג.")
            self.status_label.setStyleSheet("color: #ff4747; font-size: 16px; font-weight: bold;")
            CustomDialog(self, "שגיאה", f"אירעה שגיאה קריטית במהלך התקנת הדרייברים:\n{e}").exec()

    def run_command(self, command, title):
        try:
            # Using creationflags to hide console window on Windows
            subprocess.run(command, shell=True, check=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        except FileNotFoundError:
            CustomDialog(self, "קובץ לא נמצא", f"הפקודה עבור '{title}' נכשלה.\nודא שהקובץ הנדרש קיים בתיקייה הנכונה.").exec()
            raise
        except subprocess.CalledProcessError as e:
            CustomDialog(self, "שגיאה", f"אירעה שגיאה במהלך '{title}':\n{e}").exec()
            raise

    def proceed_to_main_window(self):
        self.main_tool_window.show()
        self.close()

    def skip_to_main_window(self):
        self.main_tool_window.show()
        self.close()

# --- Animated Toggle Switch Widget ---
class AnimatedToggleSwitch(QCheckBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCursor(QCursor(Qt.PointingHandCursor))

        self._on_color = QColor("#00ff7f")
        self._off_color = QColor("#555")
        self._thumb_color = QColor("#f0f0f0")

        self.setFixedSize(60, 28)
        self._thumb_radius = 10
        self._padding = 4
        
        self._thumb_pos = self._calculate_thumb_pos()

        self.animation = QPropertyAnimation(self, b"thumb_pos", self)
        self.animation.setDuration(200)
        self.animation.setEasingCurve(QEasingCurve.InOutCubic)

        self.stateChanged.connect(self._start_animation)

    def _calculate_thumb_pos(self) -> QPoint:
        if self.isChecked():
            x = self._padding + self._thumb_radius
        else:
            x = self.width() - self._padding - self._thumb_radius
        return QPoint(x, self.height() // 2)

    @Property(QPoint)
    def thumb_pos(self) -> QPoint:
        return self._thumb_pos

    @thumb_pos.setter
    def thumb_pos(self, pos: QPoint):
        self._thumb_pos = pos
        self.update()

    def _start_animation(self, state):
        self.animation.stop()
        self.animation.setStartValue(self.thumb_pos)
        self.animation.setEndValue(self._calculate_thumb_pos())
        self.animation.start()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)

        track_color = self._on_color if self.isChecked() else self._off_color

        painter.setBrush(track_color)
        painter.drawRoundedRect(self.rect(), self.height() / 2, self.height() / 2)

        painter.setBrush(self._thumb_color)
        painter.drawEllipse(self.thumb_pos, self._thumb_radius, self._thumb_radius)

    def hitButton(self, pos: QPoint) -> bool:
        return self.contentsRect().contains(pos)
    
    def resizeEvent(self, event: QResizeEvent):
        super().resizeEvent(event)
        self._thumb_pos = self._calculate_thumb_pos()


class ModernMTKTool(QMainWindow):
    request_command = Signal(str, str)

    def __init__(self):
        super().__init__()
        self.action_buttons = {}
        self.path_edits = {}
        self.active_button = None
        self.command_chain = []
        self.expert_mode_enabled = False

        # Paths to executables, defined once
        self.adb_exe = resource_path("adb.exe")
        self.fastboot_exe = resource_path("fastboot.exe")

        # Set default paths for bundled images
        self.boot_img_path = resource_path(os.path.join("boot & recovery", "boot.img"))
        self.recovery_img_path = resource_path(os.path.join("boot & recovery", "recovery.img"))
        
        self.setWindowIcon(QIcon(resource_path('mtk_icon.ico')))

        self.init_ui()
        self.init_worker()
        self.start_device_monitor()
        self.start_update_check()

    def init_worker(self):
        self.thread = QThread()
        self.worker = CommandRunner()
        self.worker.moveToThread(self.thread)
        self.request_command.connect(self.worker.run_command)
        self.worker.finished.connect(self.on_command_finished)
        self.worker.error.connect(self.on_command_error)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.start()

    def init_ui(self):
        self.setWindowTitle(f"כלי רוט למכשירי MTK (v{APP_VERSION})")
        self.setMinimumSize(900, 700)
        self.resize(1100, 750)
        self.setStyleSheet("background-color: #1a1a1a;")

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setAlignment(Qt.AlignCenter)
        main_layout.setContentsMargins(50, 20, 50, 20)

        title_label = QLabel("לוח בקרה למכשירי MTK")
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setStyleSheet("""
            color: #00ff7f; font-size: 36px;
            font-weight: bold; padding-bottom: 20px;
            font-family: 'Consolas', 'Courier New', monospace;
        """)
        main_layout.addWidget(title_label)

        grid_layout = QGridLayout()
        grid_layout.setSpacing(25)
        main_layout.addLayout(grid_layout)

        card1, btn1 = self.create_action_card("1: פתיחת Bootloader", self.unlock_bootloader, "unlock")
        card2, btn2 = self.create_action_card("2: צריבת boot", self.flash_boot, "flash_boot")
        card3, btn3 = self.create_action_card("3: צריבת recovery", self.flash_recovery, "flash_recovery")
        card4, btn4 = self.create_action_card("4: איתחול מכשיר", self.reboot_device, "reboot")
        self.action_buttons = {
            "unlock": btn1, "flash_boot": btn2,
            "flash_recovery": btn3, "reboot": btn4
        }
        
        grid_layout.addWidget(card1, 0, 0)
        grid_layout.addWidget(card2, 0, 1)
        grid_layout.addWidget(card3, 1, 0)
        grid_layout.addWidget(card4, 1, 1)

        self.device_model_label = QLabel("מחפש מכשיר...")
        self.device_cpu_label = QLabel("...")
        self.device_android_label = QLabel("...")
        device_info_card = self.create_data_card("פרטי המכשיר", [
            ("דגם:", self.device_model_label),
            ("מעבד:", self.device_cpu_label),
            ("גרסת אנדרואיד:", self.device_android_label),
        ])
        
        self.device_status_label = QLabel("לא ידוע")
        connection_status_card = self.create_data_card("מצב חיבור", [("סטטוס:", self.device_status_label)])

        grid_layout.addWidget(device_info_card, 2, 0)
        grid_layout.addWidget(connection_status_card, 2, 1)
        
        main_layout.addSpacing(20)

        expert_layout = QHBoxLayout()
        expert_label = QLabel("מצב מומחה")
        expert_label.setStyleSheet("color: #f0f0f0; font-size: 14px; font-weight: bold;")
        self.expert_switch = AnimatedToggleSwitch()
        self.expert_switch.toggled.connect(self.on_expert_mode_toggled)
        
        expert_layout.addWidget(expert_label)
        expert_layout.addWidget(self.expert_switch)
        expert_layout.addStretch()
        main_layout.addLayout(expert_layout)

        footer_layout = QHBoxLayout()
        self.update_label = QPushButton("קיים עדכון חדש!")
        self.update_label.setCursor(QCursor(Qt.PointingHandCursor))
        self.update_label.setStyleSheet("""
            QPushButton {
                background-color: transparent; color: #00aaff;
                font-size: 14px; border: none; padding: 5px;
                font-weight: bold;
            }
            QPushButton:hover { text-decoration: underline; }
        """)
        self.update_label.hide()

        footer_label = QLabel("פותח על ידי @cfopuser | לחץ 'Esc' ליציאה")
        footer_label.setAlignment(Qt.AlignCenter)
        footer_label.setStyleSheet("color: #555; font-size: 14px; padding-top: 10px;")
        
        footer_layout.addWidget(self.update_label)
        footer_layout.addStretch()
        footer_layout.addWidget(footer_label)
        footer_layout.addStretch()
        main_layout.addLayout(footer_layout)

        self.update_button_states()

    def create_card_base(self):
        card = QFrame()
        card.setFrameShape(QFrame.StyledPanel)
        card.setStyleSheet("""
            QFrame {
                background-color: #262626; border-radius: 15px;
                border: 1px solid #00ff7f;
            }
        """)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(20, 20, 20, 20)
        card.setMinimumHeight(180)
        return card, card_layout

    def create_action_card(self, title, function_to_call, card_id):
        card, card_layout = self.create_card_base()

        card_label = QLabel(title)
        card_label.setAlignment(Qt.AlignCenter)
        card_label.setStyleSheet("color: #f0f0f0; font-size: 18px; font-weight: bold; border: none;")
        card_layout.addWidget(card_label)
        card_layout.addStretch()

        if card_id in ["flash_boot", "flash_recovery"]:
            file_chooser_layout = QHBoxLayout()
            file_chooser_layout.setSpacing(10)

            path_edit = QLineEdit()
            path_edit.setReadOnly(True)
            path_edit.setStyleSheet("""
                QLineEdit {
                    background-color: #1a1a1a; color: #f0f0f0;
                    border: 1px solid #555; border-radius: 5px; padding: 5px;
                    font-size: 12px;
                }
            """)
            
            initial_path = self.boot_img_path if card_id == "flash_boot" else self.recovery_img_path
            path_edit.setText(initial_path)
            self.path_edits[card_id] = path_edit

            browse_button = QPushButton("...")
            browse_button.setFixedSize(30, 30)
            browse_button.setCursor(QCursor(Qt.PointingHandCursor))
            browse_button.setStyleSheet("""
                QPushButton {
                    background-color: #555; color: #f0f0f0; font-weight: bold;
                    border-radius: 5px;
                }
                QPushButton:hover { background-color: #666; }
            """)
            browse_button.clicked.connect(lambda: self.select_file(card_id))
            
            file_chooser_layout.addWidget(path_edit)
            file_chooser_layout.addWidget(browse_button)
            card_layout.addLayout(file_chooser_layout)

        button = QPushButton("הפעל")
        button.setStyleSheet("""
            QPushButton {
                background-color: #00ff7f; color: #1a1a1a;
                font-size: 16px; font-weight: bold;
                padding: 12px; border-radius: 8px; margin-top: 10px;
            }
            QPushButton:hover { background-color: #00cc66; }
            QPushButton:disabled { background-color: #555; color: #888; border: 1px solid #666; }
            QPushButton[stop_button="true"] { background-color: #ff4747; color: #030302; }
            QPushButton[stop_button="true"]:hover { background-color: #d63b3b; }
        """)
        button.clicked.connect(lambda: function_to_call(button))

        card_layout.addWidget(button)
        return card, button

    def create_data_card(self, title, data_labels):
        card, card_layout = self.create_card_base()

        title_label = QLabel(title)
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setStyleSheet("color: #00ff7f; font-size: 20px; font-weight: bold; border: none; padding-bottom: 10px;")
        card_layout.addWidget(title_label)

        for name, label_widget in data_labels:
            row_layout = QHBoxLayout()
            name_label = QLabel(name)
            name_label.setStyleSheet("color: #aaa; font-size: 14px; border: none;")
            label_widget.setStyleSheet("color: #f0f0f0; font-size: 16px; font-weight: bold; border: none;")
            row_layout.addWidget(name_label)
            row_layout.addWidget(label_widget, 1, Qt.AlignRight) 
            card_layout.addLayout(row_layout)
        
        card_layout.addStretch()
        return card
    
    def select_file(self, file_type):
        expected_filename = ""
        if file_type == "flash_boot":
            expected_filename = "boot.img"
        elif file_type == "flash_recovery":
            expected_filename = "recovery.img"
        else:
            return

        dialog = QFileDialog(self)
        dialog.setNameFilter("Image files (*.img)")
        dialog.setFileMode(QFileDialog.ExistingFile)
        
        if dialog.exec():
            selected_file = dialog.selectedFiles()[0]
            filename = os.path.basename(selected_file)

            if filename.lower() == expected_filename:
                if file_type == "flash_boot":
                    self.boot_img_path = selected_file
                else: # flash_recovery
                    self.recovery_img_path = selected_file
                
                self.path_edits[file_type].setText(selected_file)
            else:
                error_msg = f"שגיאה: יש לבחור קובץ בשם '{expected_filename}'."
                CustomDialog(self, "קובץ לא תקין", error_msg).exec()

    def set_ui_for_running_command(self, is_running, active_button=None):
        for btn in self.action_buttons.values():
            btn.setEnabled(not is_running)
        
        self.expert_switch.setEnabled(not is_running)
        
        if is_running and active_button:
            active_button.setEnabled(True)

    def execute_command(self, command, title, button, success_message=""):
        if self.active_button is not None:
            QMessageBox.warning(self, "פעולה מתבצעת", "ניתן להריץ רק פקודה אחת בכל פעם.")
            return

        self.active_button = button
        self.set_ui_for_running_command(True, button)
        
        button.setText("עצור")
        button.setProperty("stop_button", True)
        button.style().unpolish(button)
        button.style().polish(button)

        try: button.clicked.disconnect()
        except RuntimeError: pass
        button.clicked.connect(self.stop_current_command)
        
        button.setProperty("original_title", title)
        button.setProperty("success_message", success_message)
        
        self.request_command.emit(command, title)

    def stop_current_command(self):
        self.worker.stop_command()

    def on_command_error(self, message, command):
        QMessageBox.critical(self, "שגיאה", message)
    
    def on_command_finished(self, return_code, command):
        print(f"Command '{command}' finished with code {return_code}.")
        
        button_that_finished = self.active_button

        if return_code == 0 and command != "user_stopped":
            if self.command_chain:
                next_step = self.command_chain.pop(0)
                next_step = (*next_step[:2], button_that_finished, *next_step[3:])
                QTimer.singleShot(500, lambda: self.execute_command(*next_step))
                return

            success_message = button_that_finished.property("success_message") if button_that_finished else ""
            if success_message:
                QMessageBox.information(self, "הצלחה", f"{success_message}")
        
        self.set_ui_for_running_command(False)
        self.update_button_states()

        if button_that_finished:
            button_that_finished.setText("הפעל")
            button_that_finished.setProperty("stop_button", False)
            button_that_finished.style().unpolish(button_that_finished)
            button_that_finished.style().polish(button_that_finished)
            self.reset_button_functionality(button_that_finished)

        self.active_button = None
        self.command_chain.clear()

    def reset_button_functionality(self, button):
        if not button: return
        
        if button == self.action_buttons["unlock"]: original_function = self.unlock_bootloader
        elif button == self.action_buttons["flash_boot"]: original_function = self.flash_boot
        elif button == self.action_buttons["flash_recovery"]: original_function = self.flash_recovery
        elif button == self.action_buttons["reboot"]: original_function = self.reboot_device
        else: return

        try: button.clicked.disconnect() 
        except RuntimeError: pass
        button.clicked.connect(lambda: original_function(button))

    def unlock_bootloader(self, button):
        self.command_chain = [
            (f'"{self.fastboot_exe}" flashing unlock', "פתיחת Bootloader", "ה-Bootloader נפתח בהצלחה.")
        ]
        self.execute_command(f'"{self.adb_exe}" reboot bootloader', "כניסה ל-Bootloader", button)

    def flash_boot(self, button):
        self.command_chain = [
            (f'"{self.fastboot_exe}" flash boot "{self.boot_img_path}"', "צריבת Boot", "צריבת קובץ boot הושלמה."),
            (f'"{self.fastboot_exe}" reboot', "איתחול המכשיר", "המכשיר אותחל בהצלחה.")
        ]
        vbmeta_path = resource_path("vbmeta.img")
        command = f'"{self.fastboot_exe}" --disable-verity --disable-verification flash vbmeta "{vbmeta_path}"'
        self.execute_command(command, "צריבת VBMeta", button)

    def flash_recovery(self, button):
        self.command_chain = [
            (f'"{self.fastboot_exe}" flash recovery "{self.recovery_img_path}"', "צריבת Recovery", "צריבת קובץ recovery הושלמה."),
            (f'"{self.fastboot_exe}" reboot', "איתחול המכשיר", "המכשיר אותחל בהצלחה.")
        ]
        vbmeta_path = resource_path("vbmeta.img")
        command = f'"{self.fastboot_exe}" --disable-verity --disable-verification flash vbmeta "{vbmeta_path}"'
        self.execute_command(command, "צריבת VBMeta", button)

    def reboot_device(self, button):
        self.execute_command(f'"{self.fastboot_exe}" reboot', "איתחול המכשיר", button, "המכשיר מאתחל כעת.")

    def on_expert_mode_toggled(self, checked):
        self.expert_mode_enabled = checked
        self.update_button_states()

    def update_button_states(self):
        if self.active_button is not None:
            return

        if self.expert_mode_enabled:
            for button in self.action_buttons.values():
                button.setEnabled(True)
            return

        status = self.device_status_label.text()
        is_adb = "ADB" in status
        is_fastboot = "Fastboot" in status

        self.action_buttons["unlock"].setEnabled(is_adb)
        self.action_buttons["flash_boot"].setEnabled(is_fastboot)
        self.action_buttons["flash_recovery"].setEnabled(is_fastboot)
        self.action_buttons["reboot"].setEnabled(is_fastboot)

    def start_device_monitor(self):
        self.update_device_info() 
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_device_info)
        self.timer.start(3000)

    def run_adb_command(self, command, capture=True):
        try:
            popen_kwargs = {
                'shell': True,
                'capture_output': capture,
                'text': True,
                'check': True,
                'encoding': 'utf-8',
                'errors': 'ignore'
            }
            if os.name == 'nt':
                popen_kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW
            
            result = subprocess.run(command, **popen_kwargs)
            return result.stdout.strip() if capture else ""
        except (subprocess.CalledProcessError, FileNotFoundError):
            return None 

    def update_device_info(self):
        fastboot_devices = self.run_adb_command(f'"{self.fastboot_exe}" devices')
        if fastboot_devices is not None and fastboot_devices:
            self.device_status_label.setText("Fastboot Mode")
            self.device_status_label.setStyleSheet("color: #00aaff; font-size: 18px; font-weight: bold; border: none;")
            self.device_model_label.setText("N/A in Fastboot")
            self.device_cpu_label.setText("N/A in Fastboot")
            self.device_android_label.setText("N/A in Fastboot")
            self.update_button_states()
            return

        adb_devices = self.run_adb_command(f'"{self.adb_exe}" devices')
        if adb_devices is None or "List of devices attached" not in adb_devices or len(adb_devices.splitlines()) < 2:
            self.device_status_label.setText("לא מחובר")
            self.device_status_label.setStyleSheet("color: #ff4747; font-size: 18px; font-weight: bold; border: none;")
            self.device_model_label.setText("-")
            self.device_cpu_label.setText("-")
            self.device_android_label.setText("-")
            self.update_button_states()
            return

        device_line = adb_devices.splitlines()[1]
        if "device" in device_line:
            status_text = "מחובר (ADB)"
            status_color = "#00ff7f"
        elif "recovery" in device_line:
            status_text = "Recovery Mode"
            status_color = "#ffaa00"
        elif "unauthorized" in device_line:
             status_text = "לא מאושר"
             status_color = "#ffaa00"
        else:
            status_text = "לא ידוע"
            status_color = "#aaaaaa"

        self.device_status_label.setText(status_text)
        self.device_status_label.setStyleSheet(f"color: {status_color}; font-size: 18px; font-weight: bold; border: none;")

        if "device" in device_line:
            model = self.run_adb_command(f'"{self.adb_exe}" shell getprop ro.product.model') or "לא זמין"
            cpu = self.run_adb_command(f'"{self.adb_exe}" shell getprop ro.board.platform') or "לא זמין"
            android_ver = self.run_adb_command(f'"{self.adb_exe}" shell getprop ro.build.version.release') or "לא זמין"
            self.device_model_label.setText(model)
            self.device_cpu_label.setText(cpu)
            self.device_android_label.setText(android_ver)
        
        self.update_button_states()

    def start_update_check(self):
        self.update_thread = QThread()
        self.update_worker = UpdateChecker(APP_VERSION)
        self.update_worker.moveToThread(self.update_thread)
        
        self.update_worker.update_available.connect(self.handle_update_check)
        self.update_thread.started.connect(self.update_worker.run)
        self.update_thread.finished.connect(self.update_thread.deleteLater)
        
        self.update_thread.start()

    def handle_update_check(self, new_version, download_url):
        self.latest_version_tag = new_version
        self.download_url = download_url
        self.update_label.show()
        self.update_label.clicked.connect(self.show_update_dialog)

    def show_update_dialog(self):
        dialog = UpdateDialog(self, self.latest_version_tag, self.download_url)
        dialog.exec()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.close()

    def closeEvent(self, event):
        print("Closing application...")
        if hasattr(self, 'update_thread') and self.update_thread.isRunning():
            self.update_thread.quit()
            self.update_thread.wait()
        
        if self.thread.isRunning():
            self.worker.stop_command()
            self.thread.quit()
            self.thread.wait()
        event.accept()

if __name__ == '__main__':
    app = QApplication(sys.argv)
    app.setLayoutDirection(Qt.RightToLeft) 

    app.setStyleSheet("""
        QMessageBox { background-color: #262626; }
        QMessageBox QLabel { color: #f0f0f0; font-size: 16px; }
        QMessageBox QPushButton {
            background-color: #00ff7f; color: #1a1a1a; font-size: 14px;
            font-weight: bold; padding: 10px 25px; border-radius: 8px; min-width: 90px;
        }
        QMessageBox QPushButton:hover { background-color: #00cc66; }
    """)

    config = load_config()
    main_window = ModernMTKTool()

    if config.get('drivers_installed', False):
        main_window.show()
    else:
        welcome_screen = WelcomeWindow(main_tool_window=main_window)
        welcome_screen.show()

    sys.exit(app.exec())
