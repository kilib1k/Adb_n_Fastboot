###########################################
# Adb & Fastboot by @kilib1k & @LineXin1  #
# Community Edition v5.1                  #
###########################################
import sys
import subprocess
import threading
import os
import json
import re
import shutil
import platform
import urllib.request
import urllib.error
from datetime import datetime
from PyQt5.QtWidgets import (QApplication, QMainWindow, QPushButton, QVBoxLayout, 
                            QHBoxLayout, QWidget, QTextEdit, QLabel, QFileDialog, 
                            QMessageBox, QProgressBar, QGroupBox, QComboBox, 
                            QMenuBar, QAction, QDialog, QListWidget, QListWidgetItem,
                            QAbstractItemView, QDialogButtonBox, QCheckBox, QInputDialog,
                            QTabWidget, QSplitter, QFrame, QToolBar, QTreeWidget,
                            QTreeWidgetItem, QMenu, QHeaderView, QGridLayout, QLineEdit,
                            QSizePolicy, QPlainTextEdit)
from PyQt5.QtCore import Qt, QTimer, QThread, pyqtSignal, QSize, QSettings
from PyQt5.QtGui import (QFont, QIcon, QPalette, QColor,
                         QTextCharFormat, QSyntaxHighlighter)

CURRENT_VERSION = "5.1.0"

# =====================================================================
# Cross-platform helpers
# =====================================================================
IS_WINDOWS = platform.system() == 'Windows'

# Кодировка вывода adb/fastboot: на Windows консоль использует cp866 (OEM Cyrillic),
# на Linux/macOS — utf-8.
ADB_ENCODING = 'cp866' if IS_WINDOWS else 'utf-8'


def _make_startupinfo():
    """Возвращает STARTUPINFO для скрытия всплывающей консоли на Windows.
    На других ОС возвращает None — параметр startupinfo в subprocess принимает None."""
    if IS_WINDOWS:
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        return si
    return None


def _run_subprocess(cmd, *, capture=True, timeout=None, shell=True):
    """Универсальный запуск subprocess с правильной кодировкой и скрытием консоли."""
    si = _make_startupinfo()
    return subprocess.run(cmd, shell=shell, capture_output=capture,
                          startupinfo=si, text=True,
                          encoding=ADB_ENCODING, errors='ignore',
                          timeout=timeout)
UPDATE_MANIFEST_URL = "https://raw.githubusercontent.com/kilib1k/Adb_n_Fastboot/refs/heads/main/update.json"
UPDATE_CHECK_INTERVAL_HOURS = 24  # авто-проверка не чаще чем раз в сутки


class UpdateChecker(QThread):
    """Асинхронная проверка обновлений — тянет JSON-манифест с GitHub."""
    update_available = pyqtSignal(dict)   # manifest dict
    no_update = pyqtSignal()
    error = pyqtSignal(str)

    def run(self):
        try:
            req = urllib.request.Request(
                UPDATE_MANIFEST_URL,
                headers={'User-Agent': f'AdbFastboot/{CURRENT_VERSION}'}
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = resp.read().decode('utf-8')
            manifest = json.loads(data)
            remote_version = str(manifest.get('version', '0'))
            if _compare_versions(remote_version, CURRENT_VERSION) > 0:
                self.update_available.emit(manifest)
            else:
                self.no_update.emit()
        except urllib.error.URLError as e:
            self.error.emit(f"Network error: {e.reason}")
        except Exception as e:
            self.error.emit(str(e))


def _compare_versions(v1, v2):
    """Сравнение semver-строк: '5.1.0' vs '5.0.0' → 1.
    Возвращает: 1 если v1>v2, -1 если v1<v2, 0 если равны."""
    def parse(v):
        parts = re.findall(r'\d+', str(v))
        return [int(x) for x in parts] or [0]
    a, b = parse(v1), parse(v2)
    while len(a) < len(b):
        a.append(0)
    while len(b) < len(a):
        b.append(0)
    return (a > b) - (a < b)


# =====================================================================
# Logcat highlighter — раскрашивает строки по уровню (V/D/I/W/E/F)
# =====================================================================
class LogcatHighlighter(QSyntaxHighlighter):
    """QSyntaxHighlighter для раскраски строк logcat по уровню лога.

    Формат строки: "01-15 14:23:45.678 W/Tag( 1234): сообщение"
    Применяет цвет ко всей строке в зависимости от уровня (V/D/I/W/E/F).
    Использование QSyntaxHighlighter вместо HTML-форматирования намного быстрее
    — форматирование применяется лениво при отрисовке, а не при вставке текста."""

    # Цвета подобраны под тёмный фон консоли logcat (#0a0a0a)
    LEVEL_CONFIG = [
        ('V', QColor(150, 150, 150), False),   # Verbose — серый
        ('D', QColor( 86, 156, 214), False),   # Debug   — голубой
        ('I', QColor(102, 217, 138), False),   # Info    — зелёный
        ('W', QColor(230, 192,  80), False),   # Warning — жёлтый
        ('E', QColor(244,  90, 105), False),   # Error   — красный
        ('F', QColor(255,  80,  80), True),    # Fatal   — ярко-красный + bold
    ]

    def __init__(self, document):
        super().__init__(document)
        self._rules = []
        for level, color, bold in self.LEVEL_CONFIG:
            fmt = QTextCharFormat()
            fmt.setForeground(color)
            if bold:
                fmt.setFontWeight(QFont.Bold)
            # Целиком красим строку: дата+время + LEVEL/... + сообщение
            pattern = re.compile(
                r'^\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\.\d+\s+' + level + r'/.*$'
            )
            self._rules.append((pattern, fmt))

    def highlightBlock(self, text):
        for pattern, fmt in self._rules:
            if pattern.match(text):
                self.setFormat(0, len(text), fmt)
                return


class UpdateDialog(QDialog):
    """Диалог 'Доступно обновление' — показывает changelog и предлагает скачать."""
    def __init__(self, manifest, parent=None):
        super().__init__(parent)
        self.parent = parent
        self.manifest = manifest
        self.init_ui()
        if parent:
            self.apply_theme()

    def tr(self, key):
        if self.parent and hasattr(self.parent, 'tr'):
            return self.parent.tr(key)
        return key

    def init_ui(self):
        self.setWindowTitle(self.tr("update_title"))
        self.resize(550, 400)

        layout = QVBoxLayout(self)

        # Header: версия → версия
        remote_version = self.manifest.get('version', '?')
        header = QLabel(self.tr("update_header").format(
            current=CURRENT_VERSION, remote=remote_version
        ))
        header.setStyleSheet("font-size: 16px; font-weight: bold; padding: 5px;")
        layout.addWidget(header)

        # Changelog
        changelog_label = QLabel(self.tr("update_changelog_label"))
        changelog_label.setStyleSheet("font-weight: bold; padding-top: 5px;")
        layout.addWidget(changelog_label)

        self.changelog_edit = QTextEdit()
        self.changelog_edit.setReadOnly(True)
        self.changelog_edit.setPlainText(self.manifest.get('changelog', ''))
        layout.addWidget(self.changelog_edit)

        # Размер / дата если есть
        info_parts = []
        if 'size_kb' in self.manifest:
            info_parts.append(f"{self.manifest['size_kb']} KB")
        if 'date' in self.manifest:
            info_parts.append(self.manifest['date'])
        if info_parts:
            info_label = QLabel(" • ".join(info_parts))
            info_label.setStyleSheet("color: #888; padding: 3px;")
            layout.addWidget(info_label)

        # Кнопки
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self.btn_skip = QPushButton(self.tr("update_btn_skip"))
        self.btn_skip.clicked.connect(self.reject)
        btn_layout.addWidget(self.btn_skip)

        self.btn_download = QPushButton(self.tr("update_btn_download"))
        self.btn_download.setStyleSheet("font-weight: bold;")
        self.btn_download.clicked.connect(self.download_update)
        btn_layout.addWidget(self.btn_download)

        layout.addLayout(btn_layout)

    def apply_theme(self):
        if not self.parent:
            return
        theme = self.parent.themes[self.parent.current_theme]
        self.setStyleSheet(f"""
            QDialog {{ background-color: {theme['main_bg']}; }}
            QLabel {{ color: {theme['label_text']}; }}
            QTextEdit {{
                background-color: {theme['console_bg']};
                color: {theme['console_text']};
                border: 1px solid {theme['group_border']};
                border-radius: 6px;
                font-family: 'Consolas';
                padding: 5px;
            }}
            QPushButton {{
                background-color: {theme['button_bg']};
                color: {theme['button_text']};
                border: 1px solid {theme['button_text']};
                border-radius: 8px;
                padding: 8px 16px;
            }}
            QPushButton:hover {{
                background-color: {theme['button_hover_bg']};
                color: {theme['button_hover_text']};
            }}
        """)

    def download_update(self):
        """Скачивает новый .py поверх старого, старый переименовывает в .bak."""
        url = self.manifest.get('download_url')
        if not url:
            QMessageBox.critical(self, self.tr("error_title"),
                                 self.tr("update_no_download_url"))
            return
        try:
            # Блокируем кнопку чтобы не нажали дважды
            self.btn_download.setEnabled(False)
            self.btn_download.setText(self.tr("update_downloading"))

            req = urllib.request.Request(url, headers={
                'User-Agent': f'AdbFastboot/{CURRENT_VERSION}'
            })
            with urllib.request.urlopen(req, timeout=60) as resp:
                content = resp.read()

            # Путь к запущенному .py (важно: не sys.argv[0] если запущено через pythonw)
            current_path = os.path.abspath(sys.argv[0])
            if not os.path.isfile(current_path):
                # fallback на __file__
                current_path = os.path.abspath(__file__)

            backup_path = current_path + '.bak'
            temp_path = current_path + '.new'

            # Пишем в temp
            with open(temp_path, 'wb') as f:
                f.write(content)

            # Backup старого + замена
            if os.path.exists(backup_path):
                try:
                    os.remove(backup_path)
                except Exception:
                    pass
            try:
                os.rename(current_path, backup_path)
            except Exception:
                pass  # на Windows иногда нельзя двигать запущенный файл
            os.rename(temp_path, current_path)

            QMessageBox.information(self, self.tr("update_done_title"),
                                    self.tr("update_done_text"))
            self.accept()
        except Exception as e:
            self.btn_download.setEnabled(True)
            self.btn_download.setText(self.tr("update_btn_download"))
            QMessageBox.critical(self, self.tr("error_title"),
                                 self.tr("update_download_failed").format(err=str(e)))


class InstallThread(QThread):
    output_signal = pyqtSignal(str)
    progress_signal = pyqtSignal(int)
    finished_signal = pyqtSignal(bool, str)
    
    def __init__(self, cmd, description=""):
        super().__init__()
        self.cmd = cmd
        self.description = description
        
    def run(self):
        try:
            self.output_signal.emit(f"Starting: {self.description}")
            self.output_signal.emit(f"Command: {self.cmd}")
            
            si = _make_startupinfo()
            
            process = subprocess.Popen(self.cmd, shell=True, stdout=subprocess.PIPE, 
                                      stderr=subprocess.STDOUT, startupinfo=si, 
                                      universal_newlines=True, encoding=ADB_ENCODING, errors='ignore')
            
            for line in process.stdout:
                self.output_signal.emit(line.strip())
                if "Flashing" in line or "Sending" in line or "writing" in line:
                    self.progress_signal.emit(50)
                    
            process.wait()
            
            if process.returncode == 0:
                self.finished_signal.emit(True, f"{self.description} completed successfully!")
            else:
                self.finished_signal.emit(False, f"{self.description} failed with code {process.returncode}")
                
        except Exception as e:
            self.finished_signal.emit(False, f"Error: {str(e)}")

class PackageManagerDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent = parent
        self.packages = []
        self.package_states = {}
        self.init_ui()

    def tr(self, key):
        """Локализация через parent (ADBLiteApp), иначе возвращает ключ."""
        if self.parent and hasattr(self.parent, 'tr'):
            return self.parent.tr(key)
        return key

    def init_ui(self):
        self.setWindowTitle(self.tr("package_manager_title"))
        self.resize(900, 700)
        
        layout = QVBoxLayout()
        
        info_label = QLabel(self.tr("package_manager_title"))
        info_label.setStyleSheet("font-weight: bold; font-size: 12px; padding: 5px;")
        layout.addWidget(info_label)
        
        filter_group = QGroupBox(self.tr("package_manager_filters"))
        filter_layout = QHBoxLayout()
        
        filter_layout.addWidget(QLabel(self.tr("package_manager_show_label")))
        self.filter_combo = QComboBox()
        # Используем setData для индексно-безопасной локализации
        self.filter_combo.addItem(self.tr("package_manager_all_packages"), "all")
        self.filter_combo.addItem(self.tr("package_manager_system_apps"), "system")
        self.filter_combo.addItem(self.tr("package_manager_user_apps"), "user")
        self.filter_combo.addItem(self.tr("package_manager_disabled_apps"), "disabled")
        self.filter_combo.addItem(self.tr("package_manager_enabled_apps"), "enabled")
        self.filter_combo.currentTextChanged.connect(self.filter_packages)
        filter_layout.addWidget(self.filter_combo)
        
        filter_layout.addStretch()
        
        filter_layout.addWidget(QLabel(self.tr("package_manager_search")))
        self.search_input = QComboBox()
        self.search_input.setEditable(True)
        self.search_input.setMinimumWidth(200)
        self.search_input.addItems([])
        self.search_input.lineEdit().textChanged.connect(self.filter_packages)
        filter_layout.addWidget(self.search_input)
        
        self.btn_refresh_packages = QPushButton(self.tr("package_manager_refresh"))
        self.btn_refresh_packages.clicked.connect(self.load_packages)
        filter_layout.addWidget(self.btn_refresh_packages)
        
        filter_group.setLayout(filter_layout)
        layout.addWidget(filter_group)
        
        self.package_list = QListWidget()
        self.package_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.package_list.itemDoubleClicked.connect(self.toggle_package)
        layout.addWidget(self.package_list)
        
        self.stats_label = QLabel(self.tr("package_manager_loading"))
        self.stats_label.setStyleSheet("color: #888; padding: 5px;")
        layout.addWidget(self.stats_label)
        
        btn_layout = QHBoxLayout()
        
        self.btn_disable_selected = QPushButton(self.tr("package_manager_disable_selected"))
        self.btn_disable_selected.clicked.connect(self.disable_selected)
        btn_layout.addWidget(self.btn_disable_selected)
        
        self.btn_enable_selected = QPushButton(self.tr("package_manager_enable_selected"))
        self.btn_enable_selected.clicked.connect(self.enable_selected)
        btn_layout.addWidget(self.btn_enable_selected)
        
        self.btn_toggle = QPushButton(self.tr("package_manager_toggle_selected"))
        self.btn_toggle.clicked.connect(self.toggle_selected)
        btn_layout.addWidget(self.btn_toggle)
        
        layout.addLayout(btn_layout)
        
        btn_layout2 = QHBoxLayout()
        
        self.btn_disable_all_user = QPushButton(self.tr("package_manager_disable_all_user"))
        self.btn_disable_all_user.clicked.connect(self.disable_all_user_apps)
        btn_layout2.addWidget(self.btn_disable_all_user)
        
        self.btn_enable_all_disabled = QPushButton(self.tr("package_manager_enable_all_disabled"))
        self.btn_enable_all_disabled.clicked.connect(self.enable_all_disabled)
        btn_layout2.addWidget(self.btn_enable_all_disabled)
        
        layout.addLayout(btn_layout2)
        
        self.status_label = QLabel(self.tr("package_manager_ready"))
        self.status_label.setStyleSheet("color: #888; padding: 5px;")
        layout.addWidget(self.status_label)
        
        button_box = QDialogButtonBox(QDialogButtonBox.Close)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)
        
        self.setLayout(layout)
        self.apply_theme()
        
        QTimer.singleShot(100, self.load_packages)
    
    def apply_theme(self):
        if self.parent:
            theme = self.parent.themes[self.parent.current_theme]
            self.setStyleSheet(f"""
                QDialog {{
                    background-color: {theme['main_bg']};
                }}
                QLabel {{
                    color: {theme['label_text']};
                }}
                QPushButton {{
                    background-color: {theme['button_bg']};
                    color: {theme['button_text']};
                    border: 1px solid {theme['button_text']};
                    border-radius: 8px;
                    padding: 8px;
                }}
                QPushButton:hover {{
                    background-color: {theme['button_hover_bg']};
                    color: {theme['button_hover_text']};
                }}
                QListWidget {{
                    background-color: {theme['console_bg']};
                    color: {theme['console_text']};
                    border: 1px solid {theme['group_border']};
                    border-radius: 8px;
                    font-family: 'Consolas';
                    font-size: 11px;
                }}
                QListWidget::item:selected {{
                    background-color: {theme['button_hover_bg']};
                    color: {theme['button_hover_text']};
                }}
                QGroupBox {{
                    color: {theme['group_text']};
                    border: 1px solid {theme['group_border']};
                    border-radius: 8px;
                    margin-top: 10px;
                    font-weight: bold;
                }}
                QComboBox {{
                    background-color: {theme['button_bg']};
                    color: {theme['button_text']};
                    border: 1px solid {theme['button_text']};
                    border-radius: 8px;
                    padding: 5px;
                }}
                QComboBox::drop-down {{
                    border: none;
                }}
                QComboBox QAbstractItemView {{
                    background-color: {theme['button_bg']};
                    color: {theme['button_text']};
                    selection-background-color: {theme['button_hover_bg']};
                }}
            """)
    
    def load_packages(self):
        self.status_label.setText(self.tr("package_manager_loading"))
        self.package_list.clear()
        self.packages = []
        self.package_states = {}
        
        if not self.check_adb_connection():
            self.status_label.setText(self.tr("package_manager_no_adb"))
            return
        
        try:
            si = _make_startupinfo()
            
            result = subprocess.run('adb shell pm list packages', shell=True, capture_output=True, 
                                   startupinfo=si, text=True, encoding=ADB_ENCODING, errors='ignore', timeout=10)
            
            result_disabled = subprocess.run('adb shell pm list packages -d', shell=True, capture_output=True, 
                                            startupinfo=si, text=True, encoding=ADB_ENCODING, errors='ignore', timeout=10)
            
            result_system = subprocess.run('adb shell pm list packages -s', shell=True, capture_output=True, 
                                          startupinfo=si, text=True, encoding=ADB_ENCODING, errors='ignore', timeout=10)
            
            result_enabled = subprocess.run('adb shell pm list packages -e', shell=True, capture_output=True, 
                                           startupinfo=si, text=True, encoding=ADB_ENCODING, errors='ignore', timeout=10)
            
            disabled_packages = set()
            for line in result_disabled.stdout.split('\n'):
                if 'package:' in line:
                    pkg = line.replace('package:', '').strip()
                    disabled_packages.add(pkg)
            
            system_packages = set()
            for line in result_system.stdout.split('\n'):
                if 'package:' in line:
                    pkg = line.replace('package:', '').strip()
                    system_packages.add(pkg)
            
            enabled_packages = set()
            for line in result_enabled.stdout.split('\n'):
                if 'package:' in line:
                    pkg = line.replace('package:', '').strip()
                    enabled_packages.add(pkg)
            
            all_packages = []
            for line in result.stdout.split('\n'):
                if 'package:' in line:
                    pkg = line.replace('package:', '').strip()
                    if pkg:
                        all_packages.append(pkg)
                        is_disabled = pkg in disabled_packages
                        is_system = pkg in system_packages
                        is_enabled = pkg in enabled_packages
                        self.package_states[pkg] = {
                            'disabled': is_disabled,
                            'system': is_system,
                            'enabled': is_enabled,
                            'third_party': not is_system
                        }
            
            self.packages = sorted(all_packages)
            self.update_search_history()
            self.filter_packages()
            
            total_disabled = sum(1 for p in self.packages if self.package_states[p]['disabled'])
            total_system = len(system_packages)
            total_user = len(self.packages) - total_system
            
            stats = self.tr("package_manager_stats").format(
                total=len(self.packages),
                system=total_system,
                user=total_user,
                disabled=total_disabled
            )
            self.stats_label.setText(stats)
            self.status_label.setText(self.tr("package_manager_loaded").format(count=len(self.packages)))
            
            if self.parent:
                self.parent.log(self.tr("package_manager_loaded_log").format(count=len(self.packages), disabled=total_disabled))
            
        except subprocess.TimeoutExpired:
            self.status_label.setText(self.tr("package_manager_timeout"))
        except Exception as e:
            self.status_label.setText(self.tr("package_manager_error") + " " + str(e))
            if self.parent:
                self.parent.log(f"Package loading error: {str(e)}")
    
    def filter_packages(self):
        if not self.packages:
            return
            
        filter_type = self.filter_combo.currentData() or "all"
        search_text = self.search_input.currentText().lower()
        
        self.package_list.clear()
        filtered_count = 0
        
        for package in self.packages:
            state = self.package_states[package]
            
            if filter_type == "system" and not state['system']:
                continue
            elif filter_type == "user" and state['system']:
                continue
            elif filter_type == "disabled" and not state['disabled']:
                continue
            elif filter_type == "enabled" and state['disabled']:
                continue
            
            if search_text and search_text not in package.lower():
                continue
            
            status_icon = "🔴" if state['disabled'] else "🟢"
            type_icon = "📦" if state['system'] else "📱"
            
            # Получаем название приложения для отображения
            app_name = self.get_app_name(package)
            if app_name and app_name != package:
                display_text = f"{status_icon} {type_icon} {app_name} [{package}]"
            else:
                display_text = f"{status_icon} {type_icon} {package}"
            
            item = QListWidgetItem(display_text)
            item.setData(Qt.UserRole, package)
            
            if state['disabled']:
                item.setForeground(QColor(255, 100, 100))
            elif state['system']:
                item.setForeground(QColor(100, 150, 255))
            else:
                item.setForeground(QColor(100, 255, 100))
            
            self.package_list.addItem(item)
            filtered_count += 1
        
        self.status_label.setText(self.tr("package_manager_showing").format(count=filtered_count))
    
    def get_app_name(self, package):
        try:
            si = _make_startupinfo()
            result = subprocess.run(f'adb shell dumpsys package {package} | grep -A 1 "ApplicationInfo" | grep "name="', 
                                   shell=True, capture_output=True, startupinfo=si, 
                                   text=True, encoding=ADB_ENCODING, errors='ignore', timeout=3)
            if result.stdout:
                match = re.search(r'name=(.+?)[,\n]', result.stdout)
                if match:
                    name = match.group(1).strip()
                    if name and len(name) < 50:
                        return name
        except:
            pass
        return package
    
    def check_adb_connection(self):
        try:
            si = _make_startupinfo()
            result = subprocess.run('adb devices', shell=True, capture_output=True, 
                                   startupinfo=si, text=True, encoding=ADB_ENCODING, errors='ignore')
            
            lines = result.stdout.strip().split('\n')
            for line in lines[1:]:
                if line.strip() and 'device' in line and 'offline' not in line:
                    return True
            return False
        except:
            return False
    
    def get_selected_packages(self):
        selected = []
        for item in self.package_list.selectedItems():
            package = item.data(Qt.UserRole)
            if package:
                selected.append(package)
        return selected
    
    def disable_package(self, package):
        if self.parent:
            cmd = f'adb shell pm disable-user --user 0 {package}'
            self.parent.run_with_thread(cmd, f'Disabling {package}')
            self.parent.log(self.tr("package_manager_disabling_log").format(package=package))
    
    def enable_package(self, package):
        if self.parent:
            cmd = f'adb shell pm enable {package}'
            self.parent.run_with_thread(cmd, f'Enabling {package}')
            self.parent.log(self.tr("package_manager_enabling_log").format(package=package))
    
    def disable_selected(self):
        selected = self.get_selected_packages()
        if not selected:
            QMessageBox.warning(self, self.tr("package_manager_no_selection"),
                                self.tr("package_manager_select_at_least"))
            return
        
        system_selected = [p for p in selected if self.package_states[p]['system']]
        warning = ""
        if system_selected:
            warning = "\n\n" + self.tr("package_manager_warning_system").format(len(system_selected))
        
        reply = QMessageBox.question(self, self.tr("package_manager_confirm_disable"), 
                                     self.tr("package_manager_confirm_disable_msg").format(
                                         count=len(selected), warning=warning
                                     ) + "\n\n" +
                                     f"{', '.join(selected[:5])}{'...' if len(selected) > 5 else ''}",
                                     QMessageBox.Yes | QMessageBox.No)
        
        if reply == QMessageBox.Yes:
            for package in selected:
                self.disable_package(package)
            QTimer.singleShot(2000, self.load_packages)
            self.status_label.setText(self.tr("package_manager_disabling").format(count=len(selected)))
    
    def enable_selected(self):
        selected = self.get_selected_packages()
        if not selected:
            QMessageBox.warning(self, self.tr("package_manager_no_selection"),
                                self.tr("package_manager_select_at_least"))
            return
        
        reply = QMessageBox.question(self, self.tr("package_manager_confirm_enable"), 
                                     self.tr("package_manager_confirm_enable_msg").format(count=len(selected)) + "\n\n" +
                                     f"{', '.join(selected[:5])}{'...' if len(selected) > 5 else ''}",
                                     QMessageBox.Yes | QMessageBox.No)
        
        if reply == QMessageBox.Yes:
            for package in selected:
                self.enable_package(package)
            QTimer.singleShot(2000, self.load_packages)
            self.status_label.setText(self.tr("package_manager_enabling").format(count=len(selected)))
    
    def toggle_selected(self):
        selected = self.get_selected_packages()
        if not selected:
            QMessageBox.warning(self, self.tr("package_manager_no_selection"),
                                self.tr("package_manager_select_at_least"))
            return
        
        to_disable = [p for p in selected if not self.package_states[p]['disabled']]
        to_enable = [p for p in selected if self.package_states[p]['disabled']]
        
        reply = QMessageBox.question(self, self.tr("package_manager_confirm_toggle"), 
                                     self.tr("package_manager_confirm_toggle_msg").format(
                                         count=len(selected),
                                         disable=len(to_disable),
                                         enable=len(to_enable)
                                     ),
                                     QMessageBox.Yes | QMessageBox.No)
        
        if reply == QMessageBox.Yes:
            for package in to_disable:
                self.disable_package(package)
            for package in to_enable:
                self.enable_package(package)
            QTimer.singleShot(2000, self.load_packages)
    
    def toggle_package(self, item):
        package = item.data(Qt.UserRole)
        if package:
            if self.package_states[package]['disabled']:
                self.enable_package(package)
            else:
                type_text = self.tr("package_manager_system_app_warn") if self.package_states[package]['system'] else self.tr("package_manager_user_app")
                reply = QMessageBox.question(self, self.tr("package_manager_confirm_disable_single"), 
                                           self.tr("package_manager_confirm_disable_single_msg").format(
                                               package=package, type=type_text
                                           ),
                                           QMessageBox.Yes | QMessageBox.No)
                if reply == QMessageBox.Yes:
                    self.disable_package(package)
            QTimer.singleShot(1500, self.load_packages)
    
    def disable_all_user_apps(self):
        user_apps = [p for p in self.packages if not self.package_states[p]['system'] and not self.package_states[p]['disabled']]
        
        if not user_apps:
            QMessageBox.information(self, self.tr("package_manager_no_apps"),
                                    self.tr("package_manager_no_enabled_user"))
            return
        
        reply = QMessageBox.question(self, self.tr("package_manager_confirm_disable_all"), 
                                     self.tr("package_manager_confirm_disable_all_msg").format(count=len(user_apps)),
                                     QMessageBox.Yes | QMessageBox.No)
        
        if reply == QMessageBox.Yes:
            for package in user_apps:
                self.disable_package(package)
            self.status_label.setText(self.tr("package_manager_disabling").format(count=len(user_apps)))
            QMessageBox.information(self, self.tr("package_manager_info"),
                                    self.tr("package_manager_disabling_started").format(count=len(user_apps)))
            QTimer.singleShot(3000, self.load_packages)
    
    def enable_all_disabled(self):
        disabled_apps = [p for p in self.packages if self.package_states[p]['disabled']]
        
        if not disabled_apps:
            QMessageBox.information(self, self.tr("package_manager_no_apps"),
                                    self.tr("package_manager_no_disabled"))
            return
        
        reply = QMessageBox.question(self, self.tr("package_manager_confirm_enable_all"), 
                                     self.tr("package_manager_confirm_enable_all_msg").format(count=len(disabled_apps)),
                                     QMessageBox.Yes | QMessageBox.No)
        
        if reply == QMessageBox.Yes:
            for package in disabled_apps:
                self.enable_package(package)
            self.status_label.setText(self.tr("package_manager_enabling").format(count=len(disabled_apps)))
            QMessageBox.information(self, self.tr("package_manager_info"),
                                    self.tr("package_manager_enabling_started").format(count=len(disabled_apps)))
            QTimer.singleShot(3000, self.load_packages)
    
    def update_search_history(self):
        current_text = self.search_input.currentText()
        items = [self.search_input.itemText(i) for i in range(self.search_input.count())]
        if current_text and current_text not in items:
            self.search_input.addItem(current_text)
            if self.search_input.count() > 10:
                self.search_input.removeItem(0)

class PartitionManagerDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent = parent
        self.partitions = []
        self.init_ui()

    def tr(self, key):
        """Локализация через parent (ADBLiteApp), иначе возвращает ключ."""
        if self.parent and hasattr(self.parent, 'tr'):
            return self.parent.tr(key)
        return key

    def init_ui(self):
        self.setWindowTitle(self.tr("partition_manager_title"))
        self.resize(700, 600)
        
        layout = QVBoxLayout()
        
        info_label = QLabel(self.tr("partition_manager_info"))
        info_label.setStyleSheet("font-weight: bold; font-size: 12px;")
        layout.addWidget(info_label)
        
        self.partition_list = QListWidget()
        self.partition_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        layout.addWidget(self.partition_list)
        
        btn_layout = QHBoxLayout()
        
        self.btn_refresh = QPushButton(self.tr("partition_manager_refresh"))
        self.btn_refresh.clicked.connect(self.get_partitions)
        btn_layout.addWidget(self.btn_refresh)
        
        self.btn_select_all = QPushButton(self.tr("partition_manager_select_all"))
        self.btn_select_all.clicked.connect(self.select_all)
        btn_layout.addWidget(self.btn_select_all)
        
        self.btn_deselect_all = QPushButton(self.tr("partition_manager_deselect_all"))
        self.btn_deselect_all.clicked.connect(self.deselect_all)
        btn_layout.addWidget(self.btn_deselect_all)
        
        layout.addLayout(btn_layout)
        
        btn_layout2 = QHBoxLayout()
        
        self.btn_flash = QPushButton(self.tr("partition_manager_flash"))
        self.btn_flash.clicked.connect(self.flash_selected)
        btn_layout2.addWidget(self.btn_flash)
        
        self.btn_erase = QPushButton(self.tr("partition_manager_erase"))
        self.btn_erase.clicked.connect(self.erase_selected)
        btn_layout2.addWidget(self.btn_erase)
        
        self.btn_select_file = QPushButton(self.tr("partition_manager_select_image"))
        self.btn_select_file.clicked.connect(self.select_image_file)
        btn_layout2.addWidget(self.btn_select_file)
        
        layout.addLayout(btn_layout2)
        
        self.status_label = QLabel(self.tr("partition_manager_ready"))
        self.status_label.setStyleSheet("color: #888; padding: 5px;")
        layout.addWidget(self.status_label)
        
        button_box = QDialogButtonBox(QDialogButtonBox.Close)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)
        
        self.setLayout(layout)
        self.apply_theme()
        QTimer.singleShot(100, self.get_partitions)
    
    def select_all(self):
        for i in range(self.partition_list.count()):
            item = self.partition_list.item(i)
            item.setCheckState(Qt.Checked)
    
    def deselect_all(self):
        for i in range(self.partition_list.count()):
            item = self.partition_list.item(i)
            item.setCheckState(Qt.Unchecked)
        
    def apply_theme(self):
        if self.parent:
            theme = self.parent.themes[self.parent.current_theme]
            self.setStyleSheet(f"""
                QDialog {{
                    background-color: {theme['main_bg']};
                }}
                QLabel {{
                    color: {theme['label_text']};
                }}
                QPushButton {{
                    background-color: {theme['button_bg']};
                    color: {theme['button_text']};
                    border: 1px solid {theme['button_text']};
                    border-radius: 8px;
                    padding: 8px;
                }}
                QPushButton:hover {{
                    background-color: {theme['button_hover_bg']};
                    color: {theme['button_hover_text']};
                }}
                QListWidget {{
                    background-color: {theme['console_bg']};
                    color: {theme['console_text']};
                    border: 1px solid {theme['group_border']};
                    border-radius: 8px;
                }}
                QListWidget::item:selected {{
                    background-color: {theme['button_hover_bg']};
                    color: {theme['button_hover_text']};
                }}
            """)
        
    def get_partitions(self):
        self.status_label.setText(self.tr("partition_manager_getting"))
        self.partition_list.clear()
        self.partitions = []
        
        try:
            commands = [
                'fastboot getvar all',
                'fastboot oem device-info',
            ]
            
            si = _make_startupinfo()
            
            partitions_set = set()
            
            for cmd in commands:
                try:
                    result = subprocess.run(cmd, shell=True, capture_output=True, 
                                          startupinfo=si, timeout=5, 
                                          text=True, encoding=ADB_ENCODING, errors='ignore')
                    output = result.stdout + result.stderr
                    
                    patterns = [
                        r'(boot|system|vendor|userdata|cache|recovery|dtbo|vbmeta|super|product|odm|metadata|persist|misc|abl|aop|bluetooth|cpucp|devcfg|dsp|engineering|etc|featenabler|hyp|imagefv|keymaster|modem|multiimgoem|oplus|oplussec|qupfw|qweslicstore|qweslicstorebak|shrm|spunvm|storsec|toolsconfig|tz|uefisecapp|xbl|xbl_config|xbl_ramdump)\b',
                        r'partition-size:(\w+):',
                        r'partition-type:(\w+):',
                    ]
                    
                    for pattern in patterns:
                        matches = re.findall(pattern, output.lower())
                        for match in matches:
                            if isinstance(match, tuple):
                                match = match[0]
                            if match and len(match) > 2 and match not in partitions_set:
                                partitions_set.add(match)
                                
                except subprocess.TimeoutExpired:
                    continue
                except Exception:
                    continue
            
            default_partitions = ['boot', 'system', 'vendor', 'userdata', 'cache', 'recovery', 
                                 'dtbo', 'vbmeta', 'super', 'product', 'odm', 'metadata', 'persist']
            
            for part in default_partitions:
                if part not in partitions_set:
                    partitions_set.add(part)
            
            self.partitions = sorted(list(partitions_set))
            
            for partition in self.partitions:
                item = QListWidgetItem(partition)
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(Qt.Unchecked)
                self.partition_list.addItem(item)
            
            self.status_label.setText(self.tr("partition_manager_found").format(count=len(self.partitions)))
            
            if len(self.partitions) == 0:
                self.status_label.setText(self.tr("partition_manager_not_found"))
                if self.parent:
                    self.parent.log(self.tr("partition_manager_warn_log"))
            
        except Exception as e:
            self.status_label.setText(self.tr("partition_manager_error") + " " + str(e))
            if self.parent:
                self.parent.log(self.tr("partition_manager_detect_error").format(error=str(e)))
            
    def get_selected_partitions(self):
        selected = []
        for i in range(self.partition_list.count()):
            item = self.partition_list.item(i)
            if item.checkState() == Qt.Checked:
                selected.append(item.text())
        return selected
        
    def select_image_file(self):
        file_path, _ = QFileDialog.getOpenFileName(self, self.tr("partition_manager_select_image_title"), '',
                                                   self.tr("partition_manager_image_files"))
        if file_path:
            self.image_file_path = file_path
            self.status_label.setText(self.tr("partition_manager_selected_image").format(name=os.path.basename(file_path)))
            
    def flash_selected(self):
        selected = self.get_selected_partitions()
        if not selected:
            QMessageBox.warning(self, self.tr("partition_manager_no_selection"),
                                self.tr("partition_manager_select_at_least"))
            return
            
        if not hasattr(self, 'image_file_path') or not self.image_file_path:
            file_path, _ = QFileDialog.getOpenFileName(self, self.tr("partition_manager_select_image_title"), '',
                                                       self.tr("partition_manager_image_files"))
            if not file_path:
                return
            self.image_file_path = file_path
            
        if not os.path.exists(self.image_file_path):
            QMessageBox.warning(self, self.tr("partition_manager_file_not_found"),
                                self.tr("partition_manager_file_not_found_msg").format(path=self.image_file_path))
            return
            
        reply = QMessageBox.question(self, self.tr("partition_manager_confirm_flash"),
                                    self.tr("partition_manager_confirm_flash_msg").format(
                                        count=len(selected),
                                        partitions=', '.join(selected),
                                        image=os.path.basename(self.image_file_path)
                                    ),
                                    QMessageBox.Yes | QMessageBox.No)
        
        if reply == QMessageBox.Yes:
            commands = []
            for partition in selected:
                commands.append(f'fastboot flash {partition} "{self.image_file_path}"')
            
            cmd_string = ' && '.join(commands)
            if self.parent:
                self.parent.run_with_thread(cmd_string, f'Flashing {len(selected)} partitions')
            self.status_label.setText(self.tr("partition_manager_flashing").format(count=len(selected)))
            if self.parent:
                self.parent.log(self.tr("partition_manager_flashing_log").format(partitions=', '.join(selected)))
            
    def erase_selected(self):
        selected = self.get_selected_partitions()
        if not selected:
            QMessageBox.warning(self, self.tr("partition_manager_no_selection"),
                                self.tr("partition_manager_select_at_least"))
            return
            
        reply = QMessageBox.question(self, self.tr("partition_manager_confirm_erase"),
                                    self.tr("partition_manager_confirm_erase_msg").format(
                                        count=len(selected),
                                        partitions=', '.join(selected)
                                    ),
                                    QMessageBox.Yes | QMessageBox.No)
        
        if reply == QMessageBox.Yes:
            commands = []
            for partition in selected:
                commands.append(f'fastboot erase {partition}')
            
            cmd_string = ' && '.join(commands)
            if self.parent:
                self.parent.run_with_thread(cmd_string, f'Erasing {len(selected)} partitions')
            self.status_label.setText(self.tr("partition_manager_erasing").format(count=len(selected)))
            if self.parent:
                self.parent.log(self.tr("partition_manager_erasing_log").format(partitions=', '.join(selected)))

class LogcatThread(QThread):
    """Поток для потокового чтения adb logcat. Использует пакетную передачу строк."""
    lines_signal = pyqtSignal(list)
    status_signal = pyqtSignal(str)

    def __init__(self, extra_args="", parent=None):
        super().__init__()
        self.extra_args = extra_args
        self._parent = parent
        self._running = True

    def _tr(self, key, **kwargs):
        """Локализация строк статуса. Если есть parent с tr — используем, иначе возвращаем ключ."""
        if self._parent and hasattr(self._parent, 'tr'):
            text = self._parent.tr(key)
        else:
            text = key
        if kwargs:
            try:
                return text.format(**kwargs)
            except Exception:
                return text
        return text

    def run(self):
        try:
            si = _make_startupinfo()
            cmd = 'adb logcat -v time'
            if self.extra_args:
                cmd += ' ' + self.extra_args
            self.status_signal.emit(self._tr("logcat_starting", cmd=cmd))
            process = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE,
                                       stderr=subprocess.STDOUT, startupinfo=si,
                                       universal_newlines=True, encoding='utf-8',
                                       errors='ignore', bufsize=1)
            batch = []
            batch_size = 200  # накопить больше строк, потом отправить (меньше сигналов = меньше нагрузка на GUI)
            for line in process.stdout:
                if not self._running:
                    try:
                        process.terminate()
                    except Exception:
                        pass
                    break
                batch.append(line.rstrip('\r\n'))
                if len(batch) >= batch_size:
                    self.lines_signal.emit(batch)
                    batch = []
            # отправляем остаток
            if batch:
                self.lines_signal.emit(batch)
            process.wait()
            self.status_signal.emit(self._tr("logcat_stopped"))
        except Exception as e:
            self.status_signal.emit(self._tr("logcat_error_prefix", error=str(e)))

    def stop(self):
        self._running = False


class LogcatDialog(QDialog):
    """Живой лог Android с фильтрами. Оптимизирован для большого потока строк."""

    MAX_VIEW_LINES = 1000  # максимум строк в виджете (меньше = быстрее GUI)
    FLUSH_INTERVAL_MS = 250  # как часто сбрасывать накопленный буфер в виджет (4 раза/сек)
    MAX_PENDING = 3000  # если накоплено больше — дропаем старые (защита от перегрузки)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent = parent
        self.logcat_thread = None
        self.paused = False
        self._search_filter = ""
        self._pending_lines = []  # буфер строк, ждущих flush
        self._total_seen = 0
        self.init_ui()

    def tr(self, key):
        """Локализация через parent (ADBLiteApp), иначе возвращает ключ."""
        if self.parent and hasattr(self.parent, 'tr'):
            return self.parent.tr(key)
        return key

    def init_ui(self):
        title = self.tr("logcat_title")
        self.setWindowTitle(title)
        self.resize(900, 650)

        layout = QVBoxLayout()

        # Фильтры
        filter_group = QGroupBox(self.tr("logcat_filters"))
        fl = QGridLayout()

        fl.addWidget(QLabel(self.tr("logcat_level")), 0, 0)
        self.level_combo = QComboBox()
        # Используем itemData для индексно-безопасной локализации:
        # 0=All, 1=V, 2=D, 3=I, 4=W, 5=E, 6=F
        self.level_combo.addItem(self.tr("logcat_all"), "")
        self.level_combo.addItem(self.tr("logcat_verbose"), "V")
        self.level_combo.addItem(self.tr("logcat_debug"), "D")
        self.level_combo.addItem(self.tr("logcat_info"), "I")
        self.level_combo.addItem(self.tr("logcat_warning"), "W")
        self.level_combo.addItem(self.tr("logcat_error_level"), "E")
        self.level_combo.addItem(self.tr("logcat_fatal"), "F")
        self.level_combo.currentTextChanged.connect(self.restart_logcat)
        fl.addWidget(self.level_combo, 0, 1)

        fl.addWidget(QLabel(self.tr("logcat_tag")), 0, 2)
        self.tag_input = QLineEdit()
        self.tag_input.setPlaceholderText(self.tr("logcat_tag_placeholder"))
        fl.addWidget(self.tag_input, 0, 3)

        fl.addWidget(QLabel(self.tr("logcat_pid")), 1, 0)
        self.pid_input = QLineEdit()
        self.pid_input.setPlaceholderText(self.tr("logcat_pid_placeholder"))
        fl.addWidget(self.pid_input, 1, 1)

        fl.addWidget(QLabel(self.tr("logcat_search")), 1, 2)
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(self.tr("logcat_search_placeholder"))
        self.search_input.textChanged.connect(self.on_search_changed)
        fl.addWidget(self.search_input, 1, 3)

        filter_group.setLayout(fl)
        layout.addWidget(filter_group)

        # Кнопки управления
        btn_layout = QHBoxLayout()

        self.btn_start = QPushButton(self.tr("logcat_start"))
        self.btn_start.clicked.connect(self.start_logcat)
        btn_layout.addWidget(self.btn_start)

        self.btn_stop = QPushButton(self.tr("logcat_stop"))
        self.btn_stop.clicked.connect(self.stop_logcat)
        self.btn_stop.setEnabled(False)
        btn_layout.addWidget(self.btn_stop)

        self.btn_pause = QPushButton(self.tr("logcat_pause"))
        self.btn_pause.clicked.connect(self.toggle_pause)
        self.btn_pause.setCheckable(True)
        self.btn_pause.setEnabled(False)
        btn_layout.addWidget(self.btn_pause)

        self.btn_clear = QPushButton(self.tr("logcat_clear"))
        self.btn_clear.clicked.connect(self.clear_log)
        btn_layout.addWidget(self.btn_clear)

        self.btn_save = QPushButton(self.tr("logcat_save"))
        self.btn_save.clicked.connect(self.save_log)
        btn_layout.addWidget(self.btn_save)

        layout.addLayout(btn_layout)

        # Лог — используем QPlainTextEdit (гораздо быстрее QTextEdit для больших объёмов)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(self.MAX_VIEW_LINES)  # автообрезка старых строк
        self.log_view.setUndoRedoEnabled(False)  # отключаем undo — экономит память
        self.log_view.setCenterOnScroll(False)
        self.log_view.setFont(QFont("Consolas", 9))
        self.log_view.setStyleSheet("""
            QPlainTextEdit {
                background-color: #0a0a0a;
                color: #cccccc;
                border: 1px solid #444;
                border-radius: 6px;
            }
        """)
        layout.addWidget(self.log_view)

        # Подключаем подсветку синтаксиса — раскраска по уровням V/D/I/W/E/F
        self.highlighter = LogcatHighlighter(self.log_view.document())

        # Статус
        self.status_label = QLabel(self.tr("logcat_ready"))
        self.status_label.setStyleSheet("color: #888; padding: 4px;")
        layout.addWidget(self.status_label)

        button_box = QDialogButtonBox(QDialogButtonBox.Close)
        button_box.rejected.connect(self.on_close)
        layout.addWidget(button_box)

        self.setLayout(layout)
        self.apply_theme()

        # Таймер для периодического flush буфера в виджет
        self.flush_timer = QTimer(self)
        self.flush_timer.setInterval(self.FLUSH_INTERVAL_MS)
        self.flush_timer.timeout.connect(self._flush_buffer)

    def apply_theme(self):
        if not self.parent:
            return
        theme = self.parent.themes[self.parent.current_theme]
        self.setStyleSheet(f"""
            QDialog {{ background-color: {theme['main_bg']}; }}
            QLabel {{ color: {theme['label_text']}; }}
            QGroupBox {{
                color: {theme['group_text']};
                border: 1px solid {theme['group_border']};
                border-radius: 8px;
                margin-top: 10px;
                font-weight: bold;
            }}
            QPushButton {{
                background-color: {theme['button_bg']};
                color: {theme['button_text']};
                border: 1px solid {theme['button_text']};
                border-radius: 8px;
                padding: 6px 12px;
            }}
            QPushButton:hover {{
                background-color: {theme['button_hover_bg']};
                color: {theme['button_hover_text']};
            }}
            QLineEdit, QComboBox {{
                background-color: {theme['console_bg']};
                color: {theme['console_text']};
                border: 1px solid {theme['group_border']};
                border-radius: 6px;
                padding: 4px;
            }}
        """)

    def build_args(self):
        args = []
        # Используем itemData (буква уровня или пустая строка для "All") —
        # это позволяет корректно работать с любым переводом.
        level = self.level_combo.currentData()
        if level:
            args.append(f"*:{level}")

        tag = self.tag_input.text().strip()
        if tag:
            if level:
                args[-1] = f"{tag}:{level}"
            else:
                args.append(f"{tag}:V")

        pid = self.pid_input.text().strip()
        if pid and pid.isdigit():
            args.insert(0, f"--pid={pid}")

        return " ".join(args)

    def start_logcat(self):
        if self.logcat_thread and self.logcat_thread.isRunning():
            return
        args = self.build_args()
        self.clear_log()
        self.logcat_thread = LogcatThread(args, parent=self)
        self.logcat_thread.lines_signal.connect(self.on_lines_received)
        self.logcat_thread.status_signal.connect(self.on_status)
        self.logcat_thread.start()
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.btn_pause.setEnabled(True)
        self.btn_pause.setChecked(False)
        self.paused = False
        self.flush_timer.start()

    def restart_logcat(self):
        if self.logcat_thread and self.logcat_thread.isRunning():
            self.stop_logcat()
            QTimer.singleShot(400, self.start_logcat)

    def stop_logcat(self):
        if self.logcat_thread:
            self.logcat_thread.stop()
            self.logcat_thread.wait(2000)
        self.flush_timer.stop()
        # финальный сброс
        self._flush_buffer()

    def on_lines_received(self, lines):
        """Получаем пакет строк от потока. Накапливаем, не трогаем GUI напрямую."""
        if self.paused:
            return
        search = self._search_filter
        if search:
            sl = search.lower()
            lines = [ln for ln in lines if sl in ln.lower()]
        # Защита от перегрузки: если буфер уже большой — дропаем старые
        if len(self._pending_lines) > self.MAX_PENDING:
            # оставляем последние 200, остальное выбрасываем
            self._pending_lines = self._pending_lines[-200:]
            self._pending_lines.append(self.tr("logcat_dropped"))
        self._pending_lines.extend(lines)
        self._total_seen += len(lines)

    def _is_at_bottom(self):
        """Проверяем, что пользователь в самом низу лога (чтобы не рвать скролл)."""
        sb = self.log_view.verticalScrollBar()
        return sb.value() >= sb.maximum() - 5

    def _flush_buffer(self):
        """Периодически сбрасываем накопленный буфер в виджет одним вызовом."""
        if not self._pending_lines:
            return
        # Автоскролл только если пользователь сам внизу — иначе не рываем его положение
        auto_scroll = self._is_at_bottom()
        text = "\n".join(self._pending_lines)
        self._pending_lines = []
        # appendPlainText быстрее чем append с HTML и не пересчитывает layout всего документа
        self.log_view.appendPlainText(text)
        if auto_scroll:
            self.log_view.ensureCursorVisible()
        # обновляем счётчик не каждый flush (дёргать статус дорого), а раз в секунду
        self._flush_count = getattr(self, '_flush_count', 0) + 1
        if self._flush_count % 4 == 0:
            self.status_label.setText(
                self.tr("logcat_showing").format(
                    shown=min(self._total_seen, self.MAX_VIEW_LINES),
                    total=self._total_seen
                )
            )

    def on_search_changed(self, text):
        self._search_filter = text

    def toggle_pause(self):
        self.paused = self.btn_pause.isChecked()
        self.btn_pause.setText(self.tr("logcat_resume") if self.paused else self.tr("logcat_pause"))
        if self.paused:
            self.flush_timer.stop()
            self._pending_lines = []
        else:
            self.flush_timer.start()

    def clear_log(self):
        self._pending_lines = []
        self._total_seen = 0
        self.log_view.clear()

    def save_log(self):
        text = self.log_view.toPlainText()
        if not text.strip():
            QMessageBox.information(self, self.tr("logcat_empty"), self.tr("logcat_empty_msg"))
            return
        path, _ = QFileDialog.getSaveFileName(self, self.tr("logcat_save_title"),
                                               self.tr("logcat_save_default"),
                                               self.tr("logcat_save_text_files"))
        if path:
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(text)
                QMessageBox.information(self, self.tr("logcat_saved"),
                                        self.tr("logcat_saved_msg").format(path=path))
            except Exception as e:
                QMessageBox.critical(self, self.tr("logcat_error"), str(e))

    def on_status(self, msg):
        self.status_label.setText(msg)
        if "stopped" in msg.lower() or "error" in msg.lower():
            self.btn_start.setEnabled(True)
            self.btn_stop.setEnabled(False)
            self.btn_pause.setEnabled(False)
            self.flush_timer.stop()
            self._flush_buffer()

    def on_close(self):
        self.stop_logcat()
        self.reject()


class WirelessAdbDialog(QDialog):
    """Управление беспроводным ADB"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent = parent
        self.init_ui()

    def tr(self, key):
        """Локализация через parent (ADBLiteApp), иначе возвращает ключ."""
        if self.parent and hasattr(self.parent, 'tr'):
            return self.parent.tr(key)
        return key

    def init_ui(self):
        title = self.tr("wireless_adb_title")
        self.setWindowTitle(title)
        self.resize(500, 400)

        layout = QVBoxLayout()

        info_label = QLabel(self.tr("wireless_adb_info"))
        info_label.setWordWrap(True)
        info_label.setStyleSheet("padding: 8px; background-color: rgba(255,255,255,0.05); border-radius: 6px;")
        layout.addWidget(info_label)

        # Текущее состояние
        status_group = QGroupBox(self.tr("wireless_adb_status"))
        sl = QVBoxLayout()
        self.status_display = QTextEdit()
        self.status_display.setReadOnly(True)
        self.status_display.setMaximumHeight(100)
        self.status_display.setFont(QFont("Consolas", 9))
        sl.addWidget(self.status_display)
        status_group.setLayout(sl)
        layout.addWidget(status_group)

        # Включение TCP/IP
        enable_group = QGroupBox(self.tr("wireless_adb_enable"))
        el = QGridLayout()
        el.addWidget(QLabel(self.tr("wireless_adb_port")), 0, 0)
        self.port_input = QLineEdit("5555")
        self.port_input.setMaximumWidth(100)
        el.addWidget(self.port_input, 0, 1)
        self.btn_enable_tcpip = QPushButton(self.tr("wireless_adb_enable_btn"))
        self.btn_enable_tcpip.clicked.connect(self.enable_tcpip)
        el.addWidget(self.btn_enable_tcpip, 0, 2)
        enable_group.setLayout(el)
        layout.addWidget(enable_group)

        # Подключение
        connect_group = QGroupBox(self.tr("wireless_adb_connect"))
        cl = QGridLayout()
        cl.addWidget(QLabel(self.tr("wireless_adb_ip_port")), 0, 0)
        self.ip_input = QLineEdit()
        self.ip_input.setPlaceholderText(self.tr("wireless_adb_ip_placeholder"))
        cl.addWidget(self.ip_input, 0, 1)
        self.btn_connect = QPushButton(self.tr("wireless_adb_connect_btn"))
        self.btn_connect.clicked.connect(self.connect_device)
        cl.addWidget(self.btn_connect, 0, 2)
        connect_group.setLayout(cl)
        layout.addWidget(connect_group)

        # Управление
        btn_layout = QHBoxLayout()
        self.btn_refresh = QPushButton(self.tr("wireless_adb_refresh_btn"))
        self.btn_refresh.clicked.connect(self.refresh_status)
        btn_layout.addWidget(self.btn_refresh)

        self.btn_disconnect = QPushButton(self.tr("wireless_adb_disconnect_btn"))
        self.btn_disconnect.clicked.connect(self.disconnect_device)
        btn_layout.addWidget(self.btn_disconnect)

        self.btn_disconnect_all = QPushButton(self.tr("wireless_adb_disconnect_all_btn"))
        self.btn_disconnect_all.clicked.connect(self.disconnect_all)
        btn_layout.addWidget(self.btn_disconnect_all)

        layout.addLayout(btn_layout)

        button_box = QDialogButtonBox(QDialogButtonBox.Close)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

        self.setLayout(layout)
        self.apply_theme()
        QTimer.singleShot(200, self.refresh_status)

    def apply_theme(self):
        if not self.parent:
            return
        theme = self.parent.themes[self.parent.current_theme]
        self.setStyleSheet(f"""
            QDialog {{ background-color: {theme['main_bg']}; }}
            QLabel {{ color: {theme['label_text']}; }}
            QGroupBox {{
                color: {theme['group_text']};
                border: 1px solid {theme['group_border']};
                border-radius: 8px;
                margin-top: 10px;
                font-weight: bold;
            }}
            QPushButton {{
                background-color: {theme['button_bg']};
                color: {theme['button_text']};
                border: 1px solid {theme['button_text']};
                border-radius: 8px;
                padding: 6px 12px;
            }}
            QPushButton:hover {{
                background-color: {theme['button_hover_bg']};
                color: {theme['button_hover_text']};
            }}
            QLineEdit, QTextEdit {{
                background-color: {theme['console_bg']};
                color: {theme['console_text']};
                border: 1px solid {theme['group_border']};
                border-radius: 6px;
                padding: 4px;
            }}
        """)

    def _run_adb(self, cmd, timeout=8):
        try:
            si = _make_startupinfo()
            result = subprocess.run(cmd, shell=True, capture_output=True,
                                    startupinfo=si, text=True,
                                    encoding=ADB_ENCODING, errors='ignore', timeout=timeout)
            return (result.stdout or "") + (result.stderr or "")
        except subprocess.TimeoutExpired:
            return "Timeout"
        except Exception as e:
            return f"Error: {str(e)}"

    def enable_tcpip(self):
        port = self.port_input.text().strip() or "5555"
        if self.parent:
            self.parent.log(self.tr("wireless_adb_enabling").format(port=port))
        out = self._run_adb(f'adb tcpip {port}')
        if self.parent:
            self.parent.log(f"adb tcpip {port}: {out.strip()}")
        QMessageBox.information(self, self.tr("wireless_adb_tcpip_title"),
                                self.tr("wireless_adb_tcpip_msg").format(port=port))

    def connect_device(self):
        target = self.ip_input.text().strip()
        if not target:
            QMessageBox.warning(self, self.tr("wireless_adb_input_required"),
                                self.tr("wireless_adb_enter_ip"))
            return
        if self.parent:
            self.parent.log(self.tr("wireless_adb_connecting").format(target=target))
        out = self._run_adb(f'adb connect {target}')
        if self.parent:
            self.parent.log(f"adb connect: {out.strip()}")
        QTimer.singleShot(500, self.refresh_status)

    def disconnect_device(self):
        target = self.ip_input.text().strip()
        if not target:
            QMessageBox.warning(self, self.tr("wireless_adb_input_required"),
                                self.tr("wireless_adb_enter_ip_disconnect"))
            return
        out = self._run_adb(f'adb disconnect {target}')
        if self.parent:
            self.parent.log(self.tr("wireless_adb_disconnecting").format(target=target))
        QTimer.singleShot(500, self.refresh_status)

    def disconnect_all(self):
        reply = QMessageBox.question(self, self.tr("wireless_adb_confirm_disconnect_all"),
                                     self.tr("wireless_adb_disconnect_all_msg"),
                                     QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            out = self._run_adb('adb disconnect')
            if self.parent:
                self.parent.log(f"adb disconnect all: {out.strip()}")
            QTimer.singleShot(500, self.refresh_status)

    def refresh_status(self):
        out = self._run_adb('adb devices')
        self.status_display.setText(out.strip() or self.tr("wireless_adb_no_output"))


class AdbExplorerDialog(QDialog):
    """Файловый проводник устройства"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent = parent
        self.current_path = "/sdcard"
        self.init_ui()

    def tr(self, key):
        """Локализация через parent (ADBLiteApp), иначе возвращает ключ."""
        if self.parent and hasattr(self.parent, 'tr'):
            return self.parent.tr(key)
        return key

    def init_ui(self):
        title = self.tr("explorer_title")
        self.setWindowTitle(title)
        self.resize(850, 600)

        layout = QVBoxLayout()

        # Текущий путь + навигация
        nav_layout = QHBoxLayout()
        self.btn_up = QPushButton(self.tr("explorer_up"))
        self.btn_up.clicked.connect(self.go_up)
        nav_layout.addWidget(self.btn_up)

        self.btn_home = QPushButton(self.tr("explorer_home"))
        self.btn_home.clicked.connect(lambda: self.navigate("/sdcard"))
        nav_layout.addWidget(self.btn_home)

        self.path_label = QLabel(self.current_path)
        self.path_label.setStyleSheet("font-family: Consolas; padding: 4px 8px; "
                                       "background-color: rgba(255,255,255,0.05); border-radius: 4px;")
        nav_layout.addWidget(self.path_label, 1)

        self.btn_refresh = QPushButton(self.tr("explorer_refresh_btn"))
        self.btn_refresh.clicked.connect(self.refresh)
        nav_layout.addWidget(self.btn_refresh)

        layout.addLayout(nav_layout)

        # Быстрые пути
        quick_layout = QHBoxLayout()
        for name, path in [(self.tr("explorer_root"), "/"), ("/data", "/data"), ("/system", "/system"),
                           ("/cache", "/cache"), ("/persist", "/persist")]:
            btn = QPushButton(name)
            btn.clicked.connect(lambda checked, p=path: self.navigate(p))
            quick_layout.addWidget(btn)
        quick_layout.addStretch()
        layout.addLayout(quick_layout)

        # Дерево файлов
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels([
            self.tr("explorer_column_name"),
            self.tr("explorer_column_size"),
            self.tr("explorer_column_perms"),
            self.tr("explorer_column_date"),
            self.tr("explorer_column_owner"),
        ])
        self.tree.setRootIsDecorated(False)
        self.tree.setSortingEnabled(True)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.itemDoubleClicked.connect(self.on_item_double_clicked)
        self.tree.customContextMenuRequested.connect(self.show_context_menu)
        header = self.tree.header()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        layout.addWidget(self.tree)

        # Кнопки операций
        btn_layout = QHBoxLayout()

        self.btn_push = QPushButton(self.tr("explorer_push"))
        self.btn_push.clicked.connect(self.push_file)
        btn_layout.addWidget(self.btn_push)

        self.btn_pull = QPushButton(self.tr("explorer_pull"))
        self.btn_pull.clicked.connect(self.pull_file)
        btn_layout.addWidget(self.btn_pull)

        self.btn_delete = QPushButton(self.tr("explorer_delete"))
        self.btn_delete.clicked.connect(self.delete_selected)
        btn_layout.addWidget(self.btn_delete)

        self.btn_mkdir = QPushButton(self.tr("explorer_new_folder"))
        self.btn_mkdir.clicked.connect(self.make_dir)
        btn_layout.addWidget(self.btn_mkdir)

        layout.addLayout(btn_layout)

        self.status_label = QLabel(self.tr("explorer_ready"))
        self.status_label.setStyleSheet("color: #888; padding: 4px;")
        layout.addWidget(self.status_label)

        button_box = QDialogButtonBox(QDialogButtonBox.Close)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

        self.setLayout(layout)
        self.apply_theme()
        QTimer.singleShot(200, self.refresh)

    def apply_theme(self):
        if not self.parent:
            return
        theme = self.parent.themes[self.parent.current_theme]
        self.setStyleSheet(f"""
            QDialog {{ background-color: {theme['main_bg']}; }}
            QLabel {{ color: {theme['label_text']}; }}
            QGroupBox {{
                color: {theme['group_text']};
                border: 1px solid {theme['group_border']};
                border-radius: 8px;
                margin-top: 10px;
                font-weight: bold;
            }}
            QPushButton {{
                background-color: {theme['button_bg']};
                color: {theme['button_text']};
                border: 1px solid {theme['button_text']};
                border-radius: 8px;
                padding: 6px 12px;
            }}
            QPushButton:hover {{
                background-color: {theme['button_hover_bg']};
                color: {theme['button_hover_text']};
            }}
            QTreeWidget {{
                background-color: {theme['console_bg']};
                color: {theme['console_text']};
                border: 1px solid {theme['group_border']};
                border-radius: 6px;
                font-family: Consolas;
                font-size: 11px;
            }}
            QTreeWidget::item:selected {{
                background-color: {theme['button_hover_bg']};
                color: {theme['button_hover_text']};
            }}
            QHeaderView::section {{
                background-color: {theme['button_bg']};
                color: {theme['button_text']};
                padding: 4px;
                border: none;
                border-right: 1px solid {theme['group_border']};
            }}
        """)

    def _run_adb_shell(self, cmd, timeout=10):
        try:
            si = _make_startupinfo()
            full = f'adb shell "{cmd}"'
            result = subprocess.run(full, shell=True, capture_output=True,
                                    startupinfo=si, text=True,
                                    encoding=ADB_ENCODING, errors='ignore', timeout=timeout)
            return (result.stdout or "") + (result.stderr or "")
        except subprocess.TimeoutExpired:
            return "TIMEOUT"
        except Exception as e:
            return f"ERROR: {str(e)}"

    def _human_size(self, size_str):
        try:
            size = int(size_str)
        except (ValueError, TypeError):
            return size_str
        if size < 1024:
            return f"{size} B"
        elif size < 1024 * 1024:
            return f"{size / 1024:.1f} KB"
        elif size < 1024 * 1024 * 1024:
            return f"{size / (1024 * 1024):.1f} MB"
        else:
            return f"{size / (1024 * 1024 * 1024):.2f} GB"

    def refresh(self):
        self.tree.clear()
        self.status_label.setText(self.tr("explorer_loading").format(path=self.current_path))

        escaped_path = self.current_path.replace('"', '\\"')
        output = self._run_adb_shell(f'ls -la "{escaped_path}" 2>&1')

        if output.startswith("ERROR") or "TIMEOUT" in output:
            self.status_label.setText(self.tr("explorer_error_load").format(output[:200]))
            return

        entries = []
        for line in output.split('\n'):
            line = line.strip()
            if not line or line.startswith('total '):
                continue
            parts = line.split()
            if len(parts) < 7:
                continue
            perms = parts[0]
            owner = parts[2]
            size = parts[3] if not parts[3].startswith('Jan') else '0'
            date = " ".join(parts[4:7]) if len(parts) >= 7 else ""
            name = " ".join(parts[7:]) if len(parts) > 7 else ""
            if not name or name == '.' or name == '..':
                continue
            entries.append((perms, owner, size, date, name))

        for perms, owner, size, date, name in entries:
            item = QTreeWidgetItem()
            item.setText(0, name)
            item.setText(1, self._human_size(size))
            item.setText(2, perms)
            item.setText(3, date)
            item.setText(4, owner)
            is_dir = perms.startswith('d')
            if is_dir:
                item.setIcon(0, QIcon.fromTheme("folder"))
                item.setForeground(0, QColor(100, 180, 255))
                item.setData(0, Qt.UserRole, ('dir', name))
            else:
                item.setIcon(0, QIcon.fromTheme("document"))
                item.setForeground(0, QColor(200, 200, 200))
                item.setData(0, Qt.UserRole, ('file', name, size))
            self.tree.addTopLevelItem(item)

        self.path_label.setText(self.current_path)
        self.status_label.setText(self.tr("explorer_items").format(count=len(entries)))

    def navigate(self, path):
        self.current_path = path
        self.refresh()

    def go_up(self):
        if self.current_path == "/" or self.current_path == "":
            return
        parts = self.current_path.rstrip('/').split('/')
        parts.pop()
        new_path = "/".join(parts) or "/"
        self.navigate(new_path)

    def on_item_double_clicked(self, item, column):
        data = item.data(0, Qt.UserRole)
        if not data:
            return
        if data[0] == 'dir':
            name = data[1]
            if self.current_path.endswith('/'):
                new_path = self.current_path + name
            else:
                new_path = self.current_path + '/' + name
            self.navigate(new_path)

    def get_selected_items(self):
        return self.tree.selectedItems()

    def show_context_menu(self, pos):
        items = self.get_selected_items()
        if not items:
            return
        menu = QMenu(self)

        # Используем setData для индексно-безопасной локализации
        if len(items) == 1 and items[0].data(0, Qt.UserRole)[0] == 'file':
            act_pull = menu.addAction(self.tr("explorer_pull_menu"))
            act_pull.setData("pull")
        act_push = menu.addAction(self.tr("explorer_push_menu"))
        act_push.setData("push")
        act_delete = menu.addAction(self.tr("explorer_delete_menu"))
        act_delete.setData("delete")
        menu.addSeparator()
        act_refresh = menu.addAction(self.tr("explorer_refresh_menu"))
        act_refresh.setData("refresh")

        action = menu.exec_(self.tree.viewport().mapToGlobal(pos))
        if not action:
            return
        action_key = action.data()
        if action_key == "pull":
            self.pull_file()
        elif action_key == "push":
            self.push_file()
        elif action_key == "delete":
            self.delete_selected()
        elif action_key == "refresh":
            self.refresh()

    def push_file(self):
        file_path, _ = QFileDialog.getOpenFileName(self, self.tr("explorer_push_title"),
                                                   "", self.tr("explorer_push_all_files"))
        if not file_path:
            return
        fname = os.path.basename(file_path)
        cmd = f'adb push "{file_path}" "{self.current_path}/{fname}"'
        if self.parent:
            self.parent.log(self.tr("explorer_pushing").format(name=fname, path=self.current_path))
            self.parent.run_with_thread(cmd, f"Push {fname}")
        self.status_label.setText(self.tr("explorer_pushing_status").format(name=fname))
        QTimer.singleShot(1500, self.refresh)

    def pull_file(self):
        items = self.get_selected_items()
        if not items:
            QMessageBox.warning(self, self.tr("explorer_pull_no_selection"),
                                self.tr("explorer_pull_select_file"))
            return
        save_dir = QFileDialog.getExistingDirectory(self, self.tr("explorer_pull_dest"))
        if not save_dir:
            return
        for item in items:
            data = item.data(0, Qt.UserRole)
            if not data or data[0] != 'file':
                continue
            name = data[1]
            remote_path = f"{self.current_path}/{name}"
            local_path = os.path.join(save_dir, name)
            cmd = f'adb pull "{remote_path}" "{local_path}"'
            if self.parent:
                self.parent.log(self.tr("explorer_pulling").format(name=name, dir=save_dir))
                self.parent.run_with_thread(cmd, f"Pull {name}")
        self.status_label.setText(self.tr("explorer_pulling_status"))

    def delete_selected(self):
        items = self.get_selected_items()
        if not items:
            return
        names = [it.data(0, Qt.UserRole)[1] for it in items if it.data(0, Qt.UserRole)]
        reply = QMessageBox.question(self, self.tr("explorer_confirm_delete"),
                                     self.tr("explorer_confirm_delete_msg").format(
                                         count=len(names),
                                         names="\n".join(names[:10]) + ("\n..." if len(names) > 10 else "")
                                     ),
                                     QMessageBox.Yes | QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        for name in names:
            cmd = f'rm -rf "{self.current_path}/{name}"'
            out = self._run_adb_shell(cmd)
            if self.parent:
                self.parent.log(self.tr("explorer_deleted").format(name=name))
        QTimer.singleShot(500, self.refresh)

    def make_dir(self):
        name, ok = QInputDialog.getText(self, self.tr("explorer_new_folder_title"),
                                        self.tr("explorer_new_folder_prompt"))
        if not ok or not name:
            return
        cmd = f'mkdir -p "{self.current_path}/{name}"'
        out = self._run_adb_shell(cmd)
        if "ERROR" in out or "denied" in out.lower():
            QMessageBox.critical(self, self.tr("explorer_new_folder_error"),
                                self.tr("explorer_new_folder_error_msg").format(output=out))
        else:
            if self.parent:
                self.parent.log(self.tr("explorer_created_folder").format(name=name))
            QTimer.singleShot(300, self.refresh)


# =====================================================================================
# DebloatDialog — пресеты для удаления bloatware (Google/Carrier/AOSP/OEM)
# Все операции обратимы:
#   • pm disable-user --user 0 <pkg>      — отключить (включается обратно pm enable)
#   • pm uninstall -k --user 0 <pkg>      — удалить для user 0 (apk остаётся в /system)
#   • cmd package install-existing <pkg>  — восстановить удалённый для user 0
# Источники пресетов: Universal Android Debloater (UAD) + community-опыт.
# =====================================================================================
class DebloatDialog(QDialog):
    # Каждый пресет: ключ → {title, description, packages: [(pkg, name, risk), ...]}
    # risk: 'safe' (можно смело отключать) | 'caution' (может ломать фичи —
    # например Gboard, Contacts, Phone — отключать только если есть замена).
    PRESETS = {
        'google_apps': {
            'title_key': 'debloat_preset_google_apps',
            'desc_key': 'debloat_preset_google_apps_desc',
            'packages': [
                ('com.android.chrome', 'Google Chrome', 'safe'),
                ('com.google.android.googlequicksearchbox', 'Google App / Assistant', 'caution'),
                ('com.google.android.apps.photos', 'Google Photos', 'safe'),
                ('com.google.android.apps.maps', 'Google Maps', 'safe'),
                ('com.google.android.youtube', 'YouTube', 'safe'),
                ('com.google.android.apps.youtube.music', 'YouTube Music', 'safe'),
                ('com.google.android.apps.docs', 'Google Drive', 'safe'),
                ('com.google.android.apps.docs.editors.docs', 'Google Docs', 'safe'),
                ('com.google.android.apps.docs.editors.sheets', 'Google Sheets', 'safe'),
                ('com.google.android.apps.docs.editors.slides', 'Google Slides', 'safe'),
                ('com.google.android.gm', 'Gmail', 'safe'),
                ('com.google.android.keep', 'Google Keep', 'safe'),
                ('com.google.android.apps.translate', 'Google Translate', 'safe'),
                ('com.google.android.inputmethod.latin', 'Gboard', 'caution'),
                ('com.google.android.deskclock', 'Google Clock', 'safe'),
                ('com.google.android.calculator', 'Google Calculator', 'safe'),
                ('com.google.android.calendar', 'Google Calendar', 'safe'),
                ('com.google.android.contacts', 'Google Contacts', 'caution'),
                ('com.google.android.apps.messaging', 'Google Messages', 'caution'),
                ('com.google.android.dialer', 'Google Phone', 'caution'),
                ('com.google.android.tts', 'Google TTS', 'caution'),
                ('com.google.android.videos', 'Google TV / Movies', 'safe'),
                ('com.google.android.apps.magazines', 'Google News', 'safe'),
                ('com.google.android.apps.books', 'Google Play Books', 'safe'),
                ('com.google.android.apps.wallet', 'Google Wallet', 'safe'),
                ('com.google.android.feedback', 'Feedback', 'safe'),
                ('com.google.android.setupwizard', 'Setup Wizard', 'safe'),
                ('com.google.android.partnersetup', 'Partner Setup', 'safe'),
                ('com.google.android.onetimeinitializer', 'One-time Init', 'safe'),
                ('com.google.android.configupdater', 'Config Updater', 'safe'),
                ('com.google.android.markup', 'Markup', 'safe'),
                ('com.google.android.printservice.recommendation', 'Print Service', 'safe'),
                ('com.google.android.gms.location.history', 'Location History', 'safe'),
            ],
        },
        'google_telemetry': {
            'title_key': 'debloat_preset_telemetry',
            'desc_key': 'debloat_preset_telemetry_desc',
            'packages': [
                ('com.google.android.apps.wellbeing', 'Digital Wellbeing', 'safe'),
                ('com.google.android.apps.turbo', 'Battery Turbo', 'safe'),
                ('com.google.android.feedback', 'Feedback', 'safe'),
                ('com.google.android.partnersetup', 'Partner Setup', 'safe'),
                ('com.google.android.onetimeinitializer', 'One-time Init', 'safe'),
                ('com.google.android.gms.location.history', 'Location History', 'safe'),
                ('com.google.android.gms.car', 'GMS Car Service', 'safe'),
                ('com.google.android.syncadapters.calendar', 'Calendar Sync Adapter', 'safe'),
                ('com.google.android.syncadapters.contacts', 'Contacts Sync Adapter', 'safe'),
            ],
        },
        'carrier_partner': {
            'title_key': 'debloat_preset_carrier',
            'desc_key': 'debloat_preset_carrier_desc',
            'packages': [
                ('com.android.providers.partnerbookmarks', 'Partner Bookmarks', 'safe'),
                ('com.android.partnerbrowsercustomizations', 'Browser Customizations', 'safe'),
                ('com.android.bookmarkprovider', 'Bookmark Provider', 'safe'),
                ('com.android.wallpaper.livepicker', 'Live Wallpaper Picker', 'safe'),
                ('com.android.wallpaperbackup', 'Wallpaper Backup', 'safe'),
                ('com.android.egg', 'Easter Egg', 'safe'),
                ('com.android.traceur', 'System Tracing', 'safe'),
            ],
        },
        'aosp_optional': {
            'title_key': 'debloat_preset_aosp',
            'desc_key': 'debloat_preset_aosp_desc',
            'packages': [
                ('com.android.calendar', 'AOSP Calendar', 'safe'),
                ('com.android.deskclock', 'AOSP Clock', 'safe'),
                ('com.android.calculator2', 'AOSP Calculator', 'safe'),
                ('com.android.soundrecorder', 'Sound Recorder', 'safe'),
                ('com.android.voicedialer', 'Voice Dialer', 'safe'),
                ('com.android.providers.calendar', 'Calendar Provider', 'caution'),
                ('com.android.printspooler', 'Print Spooler', 'safe'),
                ('com.android.emergency', 'Emergency Info', 'caution'),
            ],
        },
        'samsung_bloat': {
            'title_key': 'debloat_preset_samsung',
            'desc_key': 'debloat_preset_samsung_desc',
            'packages': [
                ('com.samsung.android.bixby.service', 'Bixby Service', 'safe'),
                ('com.samsung.android.bixby.voiceinput', 'Bixby Voice', 'safe'),
                ('com.samsung.android.bixby.wakeup', 'Bixby Wakeup', 'safe'),
                ('com.samsung.android.app.spage', 'Bixby Home / Free', 'safe'),
                ('com.samsung.android.app.notes', 'Samsung Notes', 'safe'),
                ('com.samsung.android.app.reminder', 'Reminder', 'safe'),
                ('com.sec.android.app.shealth', 'Samsung Health', 'safe'),
                ('com.samsung.android.app.dressroom', 'Wallpaper Picker', 'safe'),
                ('com.sec.android.app.voicenote', 'Voice Recorder', 'safe'),
                ('com.samsung.android.oneconnect', 'SmartThings', 'safe'),
                ('com.samsung.android.voc', 'Samsung Members', 'safe'),
                ('com.samsung.svoice.sync', 'S Voice Sync', 'safe'),
                ('com.sec.android.widgetapp.samsungapps', 'Galaxy Store Widget', 'safe'),
                ('com.sec.android.app.samsungapps', 'Galaxy Store', 'caution'),
                ('com.samsung.android.scloud', 'Samsung Cloud', 'safe'),
                ('com.samsung.android.privatemode', 'Private Mode', 'safe'),
                ('com.samsung.android.livestickers', 'AR Stickers', 'safe'),
                ('com.samsung.android.knox.containeragent', 'Knox Container', 'caution'),
                ('com.samsung.android.drivelink.stub', 'Car Mode Stub', 'safe'),
                ('com.samsung.android.service.aircommand', 'Air Command', 'safe'),
                ('com.monotype.android.font.chococooky', 'Chococooky Font', 'safe'),
                ('com.monotype.android.font.cooljazz', 'Cool Jazz Font', 'safe'),
                ('com.monotype.android.font.rosemary', 'Rosemary Font', 'safe'),
            ],
        },
        'xiaomi_bloat': {
            'title_key': 'debloat_preset_xiaomi',
            'desc_key': 'debloat_preset_xiaomi_desc',
            'packages': [
                ('com.miui.player', 'Mi Music', 'safe'),
                ('com.miui.video', 'Mi Video', 'safe'),
                ('com.miui.miservice', 'Mi Services', 'safe'),
                ('com.miui.mishare.connectivity', 'Mi Share', 'safe'),
                ('com.miui.weather2', 'Weather', 'safe'),
                ('com.miui.notes', 'Notes', 'safe'),
                ('com.miui.calculator', 'Calculator', 'safe'),
                ('com.miui.cleanmaster', 'Clean Master', 'safe'),
                ('com.miui.compass', 'Compass', 'safe'),
                ('com.miui.hybrid', 'Quick Apps', 'safe'),
                ('com.miui.msa.global', 'MSA', 'safe'),
                ('com.miui.personalassistant', 'App Vault', 'safe'),
                ('com.xiaomi.joyose', 'Joyose', 'safe'),
                ('com.xiaomi.midrop', 'Mi Drop', 'safe'),
                ('com.xiaomi.mipicks', 'GetApps', 'safe'),
                ('com.xiaomi.payment', 'Mi Pay', 'safe'),
                ('com.mi.globalbrowser', 'Mi Browser', 'safe'),
                ('com.android.miui', 'MIUI Shell', 'caution'),
            ],
        },
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent = parent
        self.installed_packages = set()      # все установленные пакеты
        self.disabled_packages = set()       # отключённые (pm list -d)
        self.uninstalled_for_user = set()    # удалённые для user 0
        self._run_in_progress = False
        self.init_ui()
        self.apply_theme()
        QTimer.singleShot(150, self.refresh_packages)

    def tr(self, key):
        if self.parent and hasattr(self.parent, 'tr'):
            return self.parent.tr(key)
        return key

    # ---------------------------------------------------------------- UI
    def init_ui(self):
        self.setWindowTitle(self.tr("debloat_title"))
        self.resize(1000, 700)

        layout = QVBoxLayout(self)

        # ---- Header / info ----
        info_label = QLabel(self.tr("debloat_info"))
        info_label.setWordWrap(True)
        info_label.setStyleSheet("font-weight: bold; padding: 5px;")
        layout.addWidget(info_label)

        safety_label = QLabel(self.tr("debloat_safety_note"))
        safety_label.setWordWrap(True)
        safety_label.setStyleSheet("color: #888; padding: 2px 5px 8px 5px;")
        layout.addWidget(safety_label)

        # ---- Preset selector ----
        preset_group = QGroupBox(self.tr("debloat_presets_group"))
        preset_layout = QHBoxLayout(preset_group)

        preset_layout.addWidget(QLabel(self.tr("debloat_preset_label")))
        self.preset_combo = QComboBox()
        for key, preset in self.PRESETS.items():
            self.preset_combo.addItem(self.tr(preset['title_key']), key)
        preset_layout.addWidget(self.preset_combo, 1)

        self.btn_apply_preset = QPushButton(self.tr("debloat_apply_preset"))
        self.btn_apply_preset.clicked.connect(self.apply_preset)
        preset_layout.addWidget(self.btn_apply_preset)

        self.btn_clear_selection = QPushButton(self.tr("debloat_clear_selection"))
        self.btn_clear_selection.clicked.connect(self.clear_selection)
        preset_layout.addWidget(self.btn_clear_selection)

        preset_description_label = QLabel(self.tr("debloat_preset_description"))
        preset_description_label.setObjectName("debloat_preset_description_label")
        preset_description_label.setWordWrap(True)
        preset_description_label.setStyleSheet("color: #aaa; padding: 5px;")
        preset_layout.addWidget(preset_description_label, 2)

        self.preset_combo.currentIndexChanged.connect(self.update_preset_description)
        layout.addWidget(preset_group)

        # ---- Search row ----
        search_layout = QHBoxLayout()
        search_layout.addWidget(QLabel(self.tr("debloat_search_label")))
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(self.tr("debloat_search_placeholder"))
        self.search_input.textChanged.connect(self.filter_packages)
        search_layout.addWidget(self.search_input, 1)

        self.btn_refresh = QPushButton(self.tr("debloat_refresh"))
        self.btn_refresh.clicked.connect(self.refresh_packages)
        search_layout.addWidget(self.btn_refresh)

        layout.addLayout(search_layout)

        # ---- Tree widget ----
        self.tree = QTreeWidget()
        self.tree.setColumnCount(5)
        self.tree.setHeaderLabels([
            self.tr("debloat_col_check"),
            self.tr("debloat_col_package"),
            self.tr("debloat_col_description"),
            self.tr("debloat_col_state"),
            self.tr("debloat_col_risk"),
        ])
        self.tree.setRootIsDecorated(False)
        self.tree.setUniformRowHeights(True)
        self.tree.setSortingEnabled(True)
        header = self.tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Interactive)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.tree.setColumnWidth(1, 280)
        layout.addWidget(self.tree, 1)

        # ---- Stats ----
        self.stats_label = QLabel(self.tr("debloat_loading"))
        self.stats_label.setStyleSheet("color: #888; padding: 5px;")
        layout.addWidget(self.stats_label)

        # ---- Action buttons ----
        action_group = QGroupBox(self.tr("debloat_actions_group"))
        action_layout = QHBoxLayout(action_group)

        self.btn_disable = QPushButton(self.tr("debloat_btn_disable"))
        self.btn_disable.clicked.connect(self.disable_selected)
        action_layout.addWidget(self.btn_disable)

        self.btn_enable = QPushButton(self.tr("debloat_btn_enable"))
        self.btn_enable.clicked.connect(self.enable_selected)
        action_layout.addWidget(self.btn_enable)

        self.btn_uninstall_user = QPushButton(self.tr("debloat_btn_uninstall_user"))
        self.btn_uninstall_user.clicked.connect(self.uninstall_for_user)
        action_layout.addWidget(self.btn_uninstall_user)

        self.btn_reinstall_user = QPushButton(self.tr("debloat_btn_reinstall_user"))
        self.btn_reinstall_user.clicked.connect(self.reinstall_for_user)
        action_layout.addWidget(self.btn_reinstall_user)

        layout.addWidget(action_group)

        # ---- Status ----
        self.status_label = QLabel(self.tr("debloat_ready"))
        self.status_label.setStyleSheet("color: #888; padding: 5px;")
        layout.addWidget(self.status_label)

        # ---- Close button ----
        button_box = QDialogButtonBox(QDialogButtonBox.Close)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def update_preset_description(self):
        idx = self.preset_combo.currentIndex()
        if idx < 0:
            return
        preset_key = self.preset_combo.itemData(idx)
        preset = self.PRESETS.get(preset_key)
        if not preset:
            return
        label = self.findChild(QLabel, "debloat_preset_description_label")
        if label:
            label.setText(self.tr(preset['desc_key']))

    # ---------------------------------------------------------------- Theme
    def apply_theme(self):
        if not self.parent:
            return
        theme = self.parent.themes[self.parent.current_theme]
        self.setStyleSheet(f"""
            QDialog {{ background-color: {theme['main_bg']}; }}
            QLabel {{ color: {theme['label_text']}; }}
            QPushButton {{
                background-color: {theme['button_bg']};
                color: {theme['button_text']};
                border: 1px solid {theme['button_text']};
                border-radius: 8px;
                padding: 7px 10px;
            }}
            QPushButton:hover {{
                background-color: {theme['button_hover_bg']};
                color: {theme['button_hover_text']};
            }}
            QTreeWidget {{
                background-color: {theme['console_bg']};
                color: {theme['console_text']};
                border: 1px solid {theme['group_border']};
                border-radius: 8px;
                font-family: 'Consolas';
                font-size: 11px;
            }}
            QTreeWidget::item:selected {{
                background-color: {theme['button_hover_bg']};
                color: {theme['button_hover_text']};
            }}
            QHeaderView::section {{
                background-color: {theme['button_bg']};
                color: {theme['button_text']};
                padding: 5px;
                border: 1px solid {theme['group_border']};
            }}
            QGroupBox {{
                color: {theme['group_text']};
                border: 1px solid {theme['group_border']};
                border-radius: 8px;
                margin-top: 10px;
                font-weight: bold;
            }}
            QComboBox, QLineEdit {{
                background-color: {theme['button_bg']};
                color: {theme['button_text']};
                border: 1px solid {theme['button_text']};
                border-radius: 6px;
                padding: 5px;
            }}
        """)

    # ---------------------------------------------------------------- ADB helpers
    def _run_adb(self, cmd, timeout=10):
        """Запуск adb-команды и возврат (stdout+stderr) текста."""
        try:
            si = _make_startupinfo()
            full = cmd if cmd.startswith('adb ') else f'adb {cmd}'
            result = subprocess.run(full, shell=True, capture_output=True,
                                    startupinfo=si, text=True,
                                    encoding=ADB_ENCODING, errors='ignore', timeout=timeout)
            return (result.stdout or '') + (result.stderr or '')
        except subprocess.TimeoutExpired:
            return 'TIMEOUT'
        except Exception as e:
            return f'ERROR: {e}'

    def check_adb(self):
        out = self._run_adb('devices')
        for line in out.strip().split('\n')[1:]:
            if line.strip() and 'device' in line and 'offline' not in line:
                return True
        return False

    # ---------------------------------------------------------------- Loading
    def refresh_packages(self):
        if not self.check_adb():
            self.stats_label.setText(self.tr("debloat_no_connection"))
            self.status_label.setText(self.tr("debloat_no_connection"))
            return
        self.status_label.setText(self.tr("debloat_loading"))

        # Грузим все установленные
        out_all = self._run_adb('shell pm list packages')
        self.installed_packages = {
            ln.replace('package:', '').strip()
            for ln in out_all.split('\n') if 'package:' in ln
        }

        # Отключённые
        out_dis = self._run_adb('shell pm list packages -d')
        self.disabled_packages = {
            ln.replace('package:', '').strip()
            for ln in out_dis.split('\n') if 'package:' in ln
        }

        # Удалённые для user 0: pm list packages --user 0 -u показывает uninstalled
        # Простой способ: список всех пакетов, которые "uninstalled for user 0"
        # даёт `pm list packages -u` (uninstalled) минус текущие установленные.
        out_uninst = self._run_adb('shell pm list packages -u')
        all_known = {
            ln.replace('package:', '').strip()
            for ln in out_uninst.split('\n') if 'package:' in ln
        }
        self.uninstalled_for_user = all_known - self.installed_packages

        self.populate_tree()
        self.update_preset_description()

    def populate_tree(self):
        self.tree.clear()
        search = self.search_input.text().lower().strip()

        total = 0
        for preset_key, preset in self.PRESETS.items():
            for pkg, name, risk in preset['packages']:
                if search and search not in pkg.lower() and search not in name.lower():
                    continue
                item = QTreeWidgetItem()
                # Column 0: checkbox
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(0, Qt.Unchecked)
                item.setText(1, pkg)
                item.setText(2, name)

                if pkg in self.uninstalled_for_user:
                    state_text = self.tr("debloat_state_uninstalled")
                    state_color = QColor(180, 100, 100)
                elif pkg in self.disabled_packages:
                    state_text = self.tr("debloat_state_disabled")
                    state_color = QColor(220, 180, 80)
                elif pkg in self.installed_packages:
                    state_text = self.tr("debloat_state_enabled")
                    state_color = QColor(100, 200, 100)
                else:
                    state_text = self.tr("debloat_state_not_installed")
                    state_color = QColor(140, 140, 140)
                item.setText(3, state_text)
                item.setForeground(3, state_color)

                risk_text = self.tr("debloat_risk_safe") if risk == 'safe' else self.tr("debloat_risk_caution")
                risk_color = QColor(100, 200, 100) if risk == 'safe' else QColor(220, 160, 60)
                item.setText(4, risk_text)
                item.setForeground(4, risk_color)

                item.setData(0, Qt.UserRole, {'pkg': pkg, 'risk': risk})
                self.tree.addTopLevelItem(item)
                total += 1

        installed_in_presets = sum(
            1 for i in range(self.tree.topLevelItemCount())
            if self.tree.topLevelItem(i).text(3) == self.tr("debloat_state_enabled")
        )
        self.stats_label.setText(
            self.tr("debloat_stats").format(
                total, installed_in_presets, len(self.installed_packages)
            )
        )
        self.status_label.setText(self.tr("debloat_ready"))

    def filter_packages(self):
        self.populate_tree()

    # ---------------------------------------------------------------- Selection
    def get_selected_packages(self):
        selected = []
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            if item.checkState(0) == Qt.Checked:
                data = item.data(0, Qt.UserRole)
                if data:
                    selected.append((data['pkg'], data['risk']))
        return selected

    def apply_preset(self):
        idx = self.preset_combo.currentIndex()
        if idx < 0:
            return
        preset_key = self.preset_combo.itemData(idx)
        preset = self.PRESETS.get(preset_key)
        if not preset:
            return
        # Снимаем все чекбоксы
        for i in range(self.tree.topLevelItemCount()):
            self.tree.topLevelItem(i).setCheckState(0, Qt.Unchecked)
        # Отмечаем все пакеты пресета, которые есть на устройстве
        marked = 0
        not_present = 0
        for pkg, _, risk in preset['packages']:
            if pkg not in self.installed_packages:
                not_present += 1
                continue
            for i in range(self.tree.topLevelItemCount()):
                item = self.tree.topLevelItem(i)
                if item.text(1) == pkg:
                    item.setCheckState(0, Qt.Checked)
                    marked += 1
                    break
        if self.parent:
            self.parent.log(f"Debloat preset '{preset_key}': {marked} selected, {not_present} not installed")
        self.status_label.setText(
            self.tr("debloat_preset_applied").format(marked=marked, not_present=not_present)
        )

    def clear_selection(self):
        for i in range(self.tree.topLevelItemCount()):
            self.tree.topLevelItem(i).setCheckState(0, Qt.Unchecked)
        self.status_label.setText(self.tr("debloat_ready"))

    # ---------------------------------------------------------------- Actions
    def _run_batch(self, packages, action_label, cmd_template):
        """Запуск batch-операций. cmd_template содержит {pkg}."""
        if not packages:
            QMessageBox.information(self, self.tr("debloat_no_selection"),
                                    self.tr("debloat_select_first"))
            return
        # Подтверждение с предупреждением о caution-пакетах
        caution_pkgs = [p for p, r in packages if r == 'caution']
        warning = ""
        if caution_pkgs:
            warning = "\n\n" + self.tr("debloat_caution_warning").format(len(caution_pkgs))

        preview = "\n".join(p for p, _ in packages[:8])
        if len(packages) > 8:
            preview += f"\n... (+{len(packages) - 8})"

        reply = QMessageBox.question(
            self,
            action_label,
            self.tr("debloat_confirm_action").format(
                action=action_label,
                count=len(packages),
                preview=preview,
                warning=warning
            ),
            QMessageBox.Yes | QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        self.status_label.setText(self.tr("debloat_running").format(action=action_label))
        if self.parent:
            self.parent.log(f"--- {action_label}: {len(packages)} packages ---")

        # Запускаем последовательно (синхронно) — это быстрее чем
        # поднимать QThread на каждый пакет, и работает без блокировки UI
        # т.к. каждая команда обычно < 200мс.
        for pkg, _ in packages:
            cmd = cmd_template.format(pkg=pkg)
            if self.parent:
                self.parent.log(f"  → {cmd}")
            out = self._run_adb(cmd, timeout=15)
            if 'Failure' in out or 'Error' in out:
                if self.parent:
                    self.parent.log(f"  ! {pkg}: {out.strip()[:200]}")

        self.status_label.setText(self.tr("debloat_action_done").format(action=action_label))
        # Обновляем состояние
        QTimer.singleShot(400, self.refresh_packages)

    def disable_selected(self):
        packages = self.get_selected_packages()
        # Только установленные и не-отключённые
        packages = [(p, r) for p, r in packages
                    if p in self.installed_packages and p not in self.disabled_packages]
        self._run_batch(
            packages,
            self.tr("debloat_btn_disable"),
            'shell pm disable-user --user 0 {pkg}'
        )

    def enable_selected(self):
        packages = self.get_selected_packages()
        # Только отключённые
        packages = [(p, r) for p, r in packages if p in self.disabled_packages]
        self._run_batch(
            packages,
            self.tr("debloat_btn_enable"),
            'shell pm enable {pkg}'
        )

    def uninstall_for_user(self):
        packages = self.get_selected_packages()
        # Только установленные
        packages = [(p, r) for p, r in packages if p in self.installed_packages]
        self._run_batch(
            packages,
            self.tr("debloat_btn_uninstall_user"),
            'shell pm uninstall -k --user 0 {pkg}'
        )

    def reinstall_for_user(self):
        packages = self.get_selected_packages()
        # Только удалённые для user 0
        packages = [(p, r) for p, r in packages if p in self.uninstalled_for_user]
        self._run_batch(
            packages,
            self.tr("debloat_btn_reinstall_user"),
            'shell cmd package install-existing {pkg}'
        )


class ADBLiteApp(QMainWindow):
    def __init__(self):
        super().__init__()
        icon_path = self.get_icon_path()
        if icon_path and os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        self.setWindowTitle('ADB & FASTBOOT - Community Edition v5.1')
        self.resize(1000, 750)
        self.setMinimumSize(800, 600)
        
        self.device_state = 'Offline'
        
        self.themes = {
            "Gray (Default)": {
                "main_bg": "#1a1a1a",
                "button_bg": "#3a3a3a",
                "button_text": "#cccccc",
                "button_hover_bg": "#cccccc",
                "button_hover_text": "#111111",
                "console_bg": "#141414",
                "console_text": "#cccccc",
                "label_text": "#cccccc",
                "group_border": "#cccccc",
                "group_text": "#cccccc",
                "status_online": "#51cf66",
                "status_offline": "#aaaaaa",
                "progress_bg": "#cccccc"
            },
            "Dark": {
                "main_bg": "#121212",
                "button_bg": "#1e1e1e",
                "button_text": "#00d8d6",
                "button_hover_bg": "#00d8d6",
                "button_hover_text": "#000000",
                "console_bg": "#000000",
                "console_text": "#05c46b",
                "label_text": "#ffffff",
                "group_border": "#555555",
                "group_text": "#00d8d6",
                "status_online": "#05c46b",
                "status_offline": "#ff3f34",
                "progress_bg": "#00d8d6"
            },
            "Light": {
                "main_bg": "#f5f5f5",
                "button_bg": "#ffffff",
                "button_text": "#2196F3",
                "button_hover_bg": "#2196F3",
                "button_hover_text": "#ffffff",
                "console_bg": "#ffffff",
                "console_text": "#000000",
                "label_text": "#000000",
                "group_border": "#cccccc",
                "group_text": "#2196F3",
                "status_online": "#4CAF50",
                "status_offline": "#f44336",
                "progress_bg": "#2196F3"
            },
            "Green": {
                "main_bg": "#0a2e0a",
                "button_bg": "#0d470d",
                "button_text": "#00ff00",
                "button_hover_bg": "#00ff00",
                "button_hover_text": "#000000",
                "console_bg": "#051a05",
                "console_text": "#00ff00",
                "label_text": "#00ff00",
                "group_border": "#00ff00",
                "group_text": "#00ff00",
                "status_online": "#00ff00",
                "status_offline": "#ff4444",
                "progress_bg": "#00ff00"
            },
            "Blue": {
                "main_bg": "#0a1a3a",
                "button_bg": "#0d2860",
                "button_text": "#4da8ff",
                "button_hover_bg": "#4da8ff",
                "button_hover_text": "#000000",
                "console_bg": "#051530",
                "console_text": "#4da8ff",
                "label_text": "#4da8ff",
                "group_border": "#4da8ff",
                "group_text": "#4da8ff",
                "status_online": "#4da8ff",
                "status_offline": "#ff6b6b",
                "progress_bg": "#4da8ff"
            },
            "Purple": {
                "main_bg": "#1a0a2e",
                "button_bg": "#2d0d47",
                "button_text": "#b85cff",
                "button_hover_bg": "#b85cff",
                "button_hover_text": "#000000",
                "console_bg": "#150530",
                "console_text": "#b85cff",
                "label_text": "#b85cff",
                "group_border": "#b85cff",
                "group_text": "#b85cff",
                "status_online": "#b85cff",
                "status_offline": "#ff6b6b",
                "progress_bg": "#b85cff"
            },
            "Orange": {
                "main_bg": "#2a1508",
                "button_bg": "#7a3a10",
                "button_text": "#ffa94d",
                "button_hover_bg": "#ffa94d",
                "button_hover_text": "#1a0c00",
                "console_bg": "#1f0f05",
                "console_text": "#ffa94d",
                "label_text": "#ffa94d",
                "group_border": "#ffa94d",
                "group_text": "#ffa94d",
                "status_online": "#51cf66",
                "status_offline": "#ffa94d",
                "progress_bg": "#ffa94d"
            },
            "Cyan": {
                "main_bg": "#0a1e24",
                "button_bg": "#10424f",
                "button_text": "#5de4f0",
                "button_hover_bg": "#5de4f0",
                "button_hover_text": "#031016",
                "console_bg": "#06161c",
                "console_text": "#5de4f0",
                "label_text": "#5de4f0",
                "group_border": "#5de4f0",
                "group_text": "#5de4f0",
                "status_online": "#51cf66",
                "status_offline": "#5de4f0",
                "progress_bg": "#5de4f0"
            }
        }
        
        self.current_theme = "Gray (Default)"
        self.gsi_image_path = None
        self.current_lang = "en"
        self.lang = {}
        
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(10, 10, 10, 10)
        
        top_panel = self.create_top_panel()
        main_layout.addWidget(top_panel)
        
        self.tab_widget = QTabWidget()
        main_layout.addWidget(self.tab_widget)
        
        self.create_device_tab()
        self.create_gsi_tab()
        self.create_partition_tab()
        self.create_info_tab()
        
        console_panel = self.create_console_panel()
        main_layout.addWidget(console_panel, 1)
        
        self.status_timer = QTimer()
        self.status_timer.timeout.connect(self.check_device_status)
        self.status_timer.start(2000)
        
        self.scrcpy_path = self.get_scrcpy_path()
        self.gsi_image_path = None
        
        # Загружаем язык и применяем перевод ПОСЛЕ создания всех виджетов
        self.load_language()
        self.update_ui_texts(update_theme_selector=True)
        
        self.apply_theme()
        
        # Авто-проверка обновлений (тихо, не чаще раза в сутки).
        # Задержка 3с чтобы GUI успел показаться и не блокировать старт.
        QTimer.singleShot(3000, self.check_for_updates_auto)
        
    def get_icon_path(self):
        """Получение пути к иконке"""
        if getattr(sys, 'frozen', False):
            # Если программа запущена как exe
            base_path = os.path.dirname(sys.executable)
        else:
            # Если запущена как скрипт
            base_path = os.path.dirname(os.path.abspath(__file__))
        
        # Возможные пути к иконке
        possible_paths = [
            os.path.join(base_path, 'icon.ico'),
            os.path.join(base_path, 'icon.png'),
            os.path.join(base_path, 'icon.jpg'),
            os.path.join(base_path, 'app.ico'),
            os.path.join(base_path, 'logo.ico'),
            os.path.join(base_path, 'assets', 'icon.ico'),
            os.path.join(base_path, 'assets', 'icon.png'),
        ]
        
        for path in possible_paths:
            if os.path.exists(path):
                return path
        return None
        
    def load_language(self):
        # Получаем путь к директории где находится скрипт
        if getattr(sys, 'frozen', False):
            base_path = os.path.dirname(sys.executable)
        else:
            base_path = os.path.dirname(os.path.abspath(__file__))
        
        lang_file = os.path.join(base_path, "localization.json")
        
        try:
            with open(lang_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                self.lang = data.get(self.current_lang, data.get("ru", {}))
        except FileNotFoundError:
            print(f"File not found: {lang_file}")
            self.lang = {"theme": "Theme", "status": "Status", "language": "Language"}
        except Exception as e:
            print(f"Error loading language: {e}")
            self.lang = {"theme": "Theme", "status": "Status", "language": "Language"}
    def tr(self, key):
        return self.lang.get(key, key)

    def change_theme(self):
        # Получаем выбранный переведенный текст
        selected_translated = self.theme_selector.currentText()
        # Ищем оригинальное название темы
        for original_name in self.themes.keys():
            if self.tr(f"theme_{original_name}") == selected_translated:
                if self.current_theme != original_name:
                    self.current_theme = original_name
                    self.apply_theme()
                    self.log(f"{self.tr('theme_changed')}: {original_name}")
                break

    def update_ui_texts(self, update_theme_selector=True):
        # Заголовок окна
        self.setWindowTitle(self.tr("window_title"))
        
        # Заголовок приложения (верхняя панель)
        title_label = self.findChild(QLabel, "title_label")
        if title_label:
            title_label.setText(self.tr("title_text"))
        
        # Вкладки
        self.tab_widget.setTabText(0, self.tr("device_tab"))
        self.tab_widget.setTabText(1, self.tr("gsi_tab"))
        self.tab_widget.setTabText(2, self.tr("partitions_tab"))
        self.tab_widget.setTabText(3, self.tr("info_tab"))
        
        # Верхняя панель - обновляем все QLabel по objectName
        for obj_name, key in [("lang_label", "language"),
                              ("theme_label", "theme"),
                              ("status_label", "status_title")]:
            child = self.findChild(QLabel, obj_name)
            if child:
                child.setText(self.tr(key))
        
        # Группы на вкладке Device - ищем по objectName
        reboot_group = self.findChild(QGroupBox, "reboot_group")
        if reboot_group:
            reboot_group.setTitle(self.tr("reboot_options"))
        
        adb_group = self.findChild(QGroupBox, "adb_group")
        if adb_group:
            adb_group.setTitle(self.tr("adb_functions"))
        
        fastboot_group = self.findChild(QGroupBox, "fastboot_group")
        if fastboot_group:
            fastboot_group.setTitle(self.tr("fastboot_utils"))
        
        # Кнопки Device
        self.btn_system.setText(self.tr("system"))
        self.btn_recovery.setText(self.tr("recovery"))
        self.btn_bootloader.setText(self.tr("bootloader"))
        self.btn_fastbootd.setText(self.tr("fastbootd"))
        self.btn_install.setText(self.tr("install_apk"))
        self.btn_sideload.setText(self.tr("adb_sideload"))
        self.btn_bypass.setText(self.tr("bypass_setup"))
        self.btn_scrcpy.setText(self.tr("scrcpy_mirror"))
        self.btn_package_manager.setText(self.tr("package_manager"))
        self.btn_logcat.setText(self.tr("logcat_viewer"))
        self.btn_wireless_adb.setText(self.tr("wireless_adb"))
        self.btn_explorer.setText(self.tr("file_explorer"))
        self.btn_debloat.setText(self.tr("debloat_presets"))
        self.btn_screenshot.setText(self.tr("screenshot"))
        self.btn_partition_manager.setText(self.tr("partition_manager"))
        self.btn_unlock_fastboot.setText(self.tr("unlock_bootloader"))
        self.btn_relock_fastboot.setText(self.tr("relock_bootloader"))
        self.btn_switch_slot.setText(self.tr("switch_ab_slot"))
        self.btn_unlock_ability.setText(self.tr("check_unlock_ability"))
        # Консоль — кнопка Save Log
        if hasattr(self, 'save_log_btn'):
            self.save_log_btn.setText(self.tr("save_console_log"))
        if hasattr(self, 'clear_console_btn'):
            self.clear_console_btn.setText(self.tr("clear"))
        
        # Кнопка проверки обновлений в About
        if hasattr(self, 'btn_check_updates'):
            # Если проверка идёт — не перезаписываем текст "Checking..."
            if self.btn_check_updates.isEnabled():
                self.btn_check_updates.setText(self.tr("update_btn_check"))
        
        # GSI вкладка
        select_group = self.findChild(QGroupBox, "select_group")
        if select_group:
            select_group.setTitle(self.tr("select_gsi_image"))
        
        slot_group = self.findChild(QGroupBox, "slot_group")
        if slot_group:
            slot_group.setTitle(self.tr("slot_information"))
        
        install_group = self.findChild(QGroupBox, "install_group")
        if install_group:
            install_group.setTitle(self.tr("install_gsi"))
        
        wipe_group = self.findChild(QGroupBox, "wipe_group")
        if wipe_group:
            wipe_group.setTitle(self.tr("data_management"))
        
        # GSI информационный текст
        gsi_info_label = self.findChild(QLabel, "gsi_info_label")
        if gsi_info_label:
            gsi_info_label.setText(self.tr("gsi_tool_text"))
        
        self.btn_select_gsi.setText(self.tr("select_gsi"))
        self.btn_check_slot.setText(self.tr("check_slot"))
        self.btn_install_gsi_ab.setText(self.tr("ab_device"))
        self.btn_install_gsi_aonly.setText(self.tr("aonly_device"))
        self.btn_wipe_data.setText(self.tr("wipe_data"))
        
        # Метки GSI
        if hasattr(self, 'gsi_label'):
            self.gsi_label.setText(self.tr("no_gsi_image"))
        if hasattr(self, 'slot_info_label'):
            self.slot_info_label.setText(self.tr("check_slot_text"))
        
        # Partition вкладка
        self.btn_partition_manager_quick.setText(self.tr("open_partition_manager"))
        if hasattr(self, 'partition_info_label'):
            self.partition_info_label.setText(self.tr("partition_guide_title"))

        if hasattr(self, 'partition_instruction_text'):
            self.partition_instruction_text.setText(self.tr("partition_guide_text"))
        
        # Info вкладка
        self.btn_device_info.setText(self.tr("device_info"))
        self.info_display.setPlaceholderText(self.tr("click_to_see_details"))
        
        # About — используем objectName вместо text-matching
        about_title_label = self.findChild(QLabel, "about_title_label")
        if about_title_label:
            about_title_label.setText(self.tr("about_title"))
        about_text_label = self.findChild(QLabel, "about_text_label")
        if about_text_label:
            about_text_label.setText(self.tr("about_text"))
        
        # Консоль — используем objectName
        console_label = self.findChild(QLabel, "console_label")
        if console_label:
            console_label.setText(self.tr("console_log"))
        
        # Обновляем названия тем в комбобоксе
        if update_theme_selector:
            # Блокируем сигналы чтобы не вызывать change_theme
            self.theme_selector.blockSignals(True)
            current_index = self.theme_selector.currentIndex()
            self.theme_selector.clear()
            for theme_name in self.themes.keys():
                # Переводим название темы
                translated_name = self.tr(f"theme_{theme_name}")
                self.theme_selector.addItem(translated_name)
            # Восстанавливаем индекс если он был
            if current_index >= 0 and current_index < self.theme_selector.count():
                self.theme_selector.setCurrentIndex(current_index)
            self.theme_selector.blockSignals(False)
    def log(self, text):
        self.console.append(f'> {text}')
        scrollbar = self.console.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
    def create_top_panel(self):
        panel = QFrame()
        panel.setFrameStyle(QFrame.StyledPanel)
        layout = QHBoxLayout(panel)
        
        title_label = QLabel("ADB & FASTBOOT - Community Edition v5.1")
        title_label.setObjectName("title_label")
        title_label.setStyleSheet("font-size: 16px; font-weight: bold;")
        layout.addWidget(title_label)
        
        layout.addStretch()
        
        lang_label = QLabel("Language")
        lang_label.setObjectName("lang_label")  # Добавляем objectName
        layout.addWidget(lang_label)
        
        self.lang_selector = QComboBox()
        self.lang_selector.addItems(["en", "ru"])
        self.lang_selector.currentTextChanged.connect(self.change_language)
        layout.addWidget(self.lang_selector)
        
        layout.addSpacing(10)
        
        # Создаем лейблы с objectName для легкого поиска
        theme_label = QLabel("Theme")
        theme_label.setObjectName("theme_label")  # Добавляем objectName
        layout.addWidget(theme_label)
        
        self.theme_selector = QComboBox()
        self.theme_selector.addItems(self.themes.keys())
        self.theme_selector.currentTextChanged.connect(self.change_theme)
        layout.addWidget(self.theme_selector)
        
        layout.addSpacing(20)
        
        status_label = QLabel("Status:")
        status_label.setObjectName("status_label")  # Добавляем objectName
        layout.addWidget(status_label)
        
        self.status_lbl = QLabel('SCANNING...')
        self.status_lbl.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(self.status_lbl)
    
        return panel
    
    def create_device_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(15)
        
        reboot_group = QGroupBox("Reboot Options")
        reboot_group.setObjectName("reboot_group")
        reboot_layout = QVBoxLayout()
        
        row1 = QHBoxLayout()
        self.btn_system = QPushButton("SYSTEM")
        self.btn_recovery = QPushButton("RECOVERY")
        self.btn_bootloader = QPushButton("BOOTLOADER")
        
        for btn in [self.btn_system, self.btn_recovery, self.btn_bootloader]:
            btn.clicked.connect(self.handle_reboot)
            row1.addWidget(btn)
        reboot_layout.addLayout(row1)
        
        row2 = QHBoxLayout()
        self.btn_fastbootd = QPushButton("FASTBOOTD")
        self.btn_fastbootd.clicked.connect(self.reboot_to_fastbootd)
        row2.addWidget(self.btn_fastbootd)
        reboot_layout.addLayout(row2)
        
        reboot_group.setLayout(reboot_layout)
        layout.addWidget(reboot_group)
        
        adb_group = QGroupBox("ADB Functions")
        adb_group.setObjectName("adb_group")
        adb_layout = QVBoxLayout()
        
        row3 = QHBoxLayout()
        self.btn_install = QPushButton("INSTALL APK")
        self.btn_install.clicked.connect(self.install_apk)
        self.btn_sideload = QPushButton("ADB SIDELOAD")
        self.btn_sideload.clicked.connect(self.run_sideload)
        row3.addWidget(self.btn_install)
        row3.addWidget(self.btn_sideload)
        adb_layout.addLayout(row3)
        
        row4 = QHBoxLayout()
        self.btn_bypass = QPushButton("BYPASS SETUP")
        self.btn_bypass.clicked.connect(self.bypass_setup)
        self.btn_scrcpy = QPushButton("SCRCPY MIRROR")
        self.btn_scrcpy.clicked.connect(self.run_scrcpy)
        self.btn_package_manager = QPushButton("PACKAGE MANAGER")
        self.btn_package_manager.clicked.connect(self.open_package_manager)
        row4.addWidget(self.btn_bypass)
        row4.addWidget(self.btn_scrcpy)
        row4.addWidget(self.btn_package_manager)
        adb_layout.addLayout(row4)
        
        row4b = QHBoxLayout()
        self.btn_logcat = QPushButton("LOGCAT VIEWER")
        self.btn_logcat.clicked.connect(self.open_logcat)
        self.btn_wireless_adb = QPushButton("WIRELESS ADB")
        self.btn_wireless_adb.clicked.connect(self.open_wireless_adb)
        self.btn_explorer = QPushButton("FILE EXPLORER")
        self.btn_explorer.clicked.connect(self.open_explorer)
        self.btn_debloat = QPushButton("DEBLOAT PRESETS")
        self.btn_debloat.clicked.connect(self.open_debloat)
        row4b.addWidget(self.btn_logcat)
        row4b.addWidget(self.btn_wireless_adb)
        row4b.addWidget(self.btn_explorer)
        row4b.addWidget(self.btn_debloat)
        adb_layout.addLayout(row4b)

        row4c = QHBoxLayout()
        self.btn_screenshot = QPushButton("📸 SCREENSHOT")
        self.btn_screenshot.clicked.connect(self.take_screenshot)
        row4c.addWidget(self.btn_screenshot)
        row4c.addStretch()
        adb_layout.addLayout(row4c)

        adb_group.setLayout(adb_layout)
        layout.addWidget(adb_group)
        
        fastboot_group = QGroupBox("Fastboot Utilities")
        fastboot_group.setObjectName("fastboot_group")
        fastboot_layout = QVBoxLayout()
        
        row5 = QHBoxLayout()
        self.btn_partition_manager = QPushButton("PARTITION MANAGER")
        self.btn_partition_manager.clicked.connect(self.open_partition_manager)
        self.btn_unlock_fastboot = QPushButton("UNLOCK BOOTLOADER")
        self.btn_unlock_fastboot.clicked.connect(self.unlock_bootloader_fastboot)
        self.btn_relock_fastboot = QPushButton("RELOCK BOOTLOADER")
        self.btn_relock_fastboot.clicked.connect(self.relock_bootloader_fastboot)
        row5.addWidget(self.btn_partition_manager)
        row5.addWidget(self.btn_unlock_fastboot)
        row5.addWidget(self.btn_relock_fastboot)
        fastboot_layout.addLayout(row5)

        row6 = QHBoxLayout()
        self.btn_switch_slot = QPushButton("🔄 SWITCH A/B SLOT")
        self.btn_switch_slot.clicked.connect(self.switch_ab_slot)
        row6.addWidget(self.btn_switch_slot)
        self.btn_unlock_ability = QPushButton("CHECK UNLOCK ABILITY")
        self.btn_unlock_ability.clicked.connect(self.check_unlock_ability)
        row6.addWidget(self.btn_unlock_ability)
        fastboot_layout.addLayout(row6)

        fastboot_group.setLayout(fastboot_layout)
        layout.addWidget(fastboot_group)

        layout.addStretch()
        self.tab_widget.addTab(tab, "Device")
    
    def create_gsi_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(15)
        
        info_frame = QFrame()
        info_frame.setFrameStyle(QFrame.StyledPanel)
        info_layout = QHBoxLayout(info_frame)
        info_label = QLabel("GSI (Generic System Image) installation tool")
        info_label.setObjectName("gsi_info_label")
        info_label.setStyleSheet("font-weight: bold;")
        info_layout.addWidget(info_label)
        layout.addWidget(info_frame)
        
        select_group = QGroupBox("Select GSI Image")
        select_group.setObjectName("select_group")
        select_layout = QHBoxLayout()
        self.gsi_label = QLabel("No image selected")
        self.gsi_label.setStyleSheet("font-family: monospace;")
        self.btn_select_gsi = QPushButton("SELECT GSI IMAGE")
        self.btn_select_gsi.clicked.connect(self.select_gsi_image)
        select_layout.addWidget(self.gsi_label)
        select_layout.addWidget(self.btn_select_gsi)
        select_group.setLayout(select_layout)
        layout.addWidget(select_group)
        
        slot_group = QGroupBox("Slot Information")
        slot_group.setObjectName("slot_group")
        slot_layout = QHBoxLayout()
        self.btn_check_slot = QPushButton("CHECK CURRENT SLOT")
        self.btn_check_slot.clicked.connect(self.check_current_slot)
        self.slot_info_label = QLabel("Click to check")
        self.slot_info_label.setStyleSheet("font-family: monospace;")
        slot_layout.addWidget(self.btn_check_slot)
        slot_layout.addWidget(self.slot_info_label)
        slot_group.setLayout(slot_layout)
        layout.addWidget(slot_group)
        
        install_group = QGroupBox("Install GSI")
        install_group.setObjectName("install_group")
        install_layout = QHBoxLayout()
        self.btn_install_gsi_ab = QPushButton("A/B DEVICE")
        self.btn_install_gsi_ab.clicked.connect(lambda: self.install_gsi(ab_device=True))
        self.btn_install_gsi_aonly = QPushButton("A-ONLY DEVICE")
        self.btn_install_gsi_aonly.clicked.connect(lambda: self.install_gsi(ab_device=False))
        install_layout.addWidget(self.btn_install_gsi_ab)
        install_layout.addWidget(self.btn_install_gsi_aonly)
        install_group.setLayout(install_layout)
        layout.addWidget(install_group)
        
        wipe_group = QGroupBox("Data Management")
        wipe_group.setObjectName("wipe_group")
        wipe_layout = QHBoxLayout()
        self.btn_wipe_data = QPushButton("WIPE DATA (FULL)")
        self.btn_wipe_data.clicked.connect(self.complete_wipe_data)
        wipe_layout.addWidget(self.btn_wipe_data)
        wipe_group.setLayout(wipe_layout)
        layout.addWidget(wipe_group)
        
        layout.addStretch()
        self.tab_widget.addTab(tab, "GSI Installer")
    
    def create_partition_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        self.partition_info_label = QLabel("📖 PARTITION MANAGER GUIDE:")  # Сохраняем ссылку
        self.partition_info_label.setStyleSheet("font-weight: bold; padding: 10px;")
        layout.addWidget(self.partition_info_label)
        
        btn_layout = QHBoxLayout()
        self.btn_partition_manager_quick = QPushButton("OPEN PARTITION MANAGER")
        self.btn_partition_manager_quick.clicked.connect(self.open_partition_manager)
        btn_layout.addWidget(self.btn_partition_manager_quick)
        
        layout.addLayout(btn_layout)
        
        self.partition_instruction_text = QTextEdit()  # Сохраняем ссылку
        self.partition_instruction_text.setReadOnly(True)
        self.partition_instruction_text.setMaximumHeight(200)
        self.partition_instruction_text.setText("""📖 PARTITION MANAGER GUIDE:
        
    1. Make sure your device is in FASTBOOT mode
    2. Click 'OPEN PARTITION MANAGER' to see all partitions
    3. Select partitions you want to flash or erase
    4. Choose an image file for flashing
    5. Confirm the operation

    ⚠️ WARNING: Modifying partitions can brick your device!
    Only proceed if you know what you're doing.""")
        layout.addWidget(self.partition_instruction_text)
        
        layout.addStretch()
        self.tab_widget.addTab(tab, "Partitions")
    
    def create_info_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        self.btn_device_info = QPushButton("GET DEVICE INFORMATION")
        self.btn_device_info.clicked.connect(self.get_device_info)
        self.btn_device_info.setMinimumHeight(50)
        self.btn_device_info.setStyleSheet("font-size: 14px; font-weight: bold;")
        layout.addWidget(self.btn_device_info)
        
        self.info_display = QTextEdit()
        self.info_display.setReadOnly(True)
        self.info_display.setPlaceholderText("Click 'Get Device Information' to see details...")
        layout.addWidget(self.info_display)
        
        about_frame = QFrame()
        about_frame.setObjectName("about_frame")
        about_frame.setFrameStyle(QFrame.StyledPanel)
        about_layout = QVBoxLayout(about_frame)
        
        about_title = QLabel("About")
        about_title.setObjectName("about_title_label")
        about_title.setStyleSheet("font-weight: bold; font-size: 12px;")
        about_layout.addWidget(about_title)
        
        about_text = QLabel("ADB & FASTBOOT - Community Edition\nCreated by: @LineXin_Blossom & @kilib1k\nVersion: v5.1 (Logcat, Wireless ADB, File Explorer)\n© 2026 Community Edition")
        about_text.setObjectName("about_text_label")
        about_text.setWordWrap(True)
        about_layout.addWidget(about_text)
        
        # Кнопка проверки обновлений
        update_row = QHBoxLayout()
        self.btn_check_updates = QPushButton("🔄 Check for Updates")
        self.btn_check_updates.clicked.connect(self.check_for_updates_manual)
        update_row.addWidget(self.btn_check_updates)
        update_row.addStretch()
        about_layout.addLayout(update_row)
        
        layout.addWidget(about_frame)
        
        self.tab_widget.addTab(tab, "Info")
    
    def create_console_panel(self):
        panel = QFrame()
        panel.setFrameStyle(QFrame.StyledPanel)
        layout = QVBoxLayout(panel)
        
        console_header = QHBoxLayout()
        console_label = QLabel("Console Log")
        console_label.setObjectName("console_label")
        console_label.setStyleSheet("font-weight: bold; font-size: 12px;")
        console_header.addWidget(console_label)
        
        console_header.addStretch()
        
        self.clear_console_btn = QPushButton("Clear")
        self.clear_console_btn.clicked.connect(self.clear_console)
        self.clear_console_btn.setMinimumWidth(80)
        self.clear_console_btn.setMaximumWidth(60)
        console_header.addWidget(self.clear_console_btn)

        self.save_log_btn = QPushButton("💾 Save Log")
        self.save_log_btn.clicked.connect(self.save_console_log)
        self.save_log_btn.setMinimumWidth(90)
        self.save_log_btn.setMaximumWidth(110)
        console_header.addWidget(self.save_log_btn)
        
        layout.addLayout(console_header)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)
        
        self.console = QTextEdit()
        self.console.setReadOnly(True)
        self.console.setFont(QFont("Consolas", 9))
        layout.addWidget(self.console)
        
        return panel
    
    def clear_console(self):
        self.console.clear()
        self.log(self.tr("console_cleared"))

    def save_console_log(self):
        """Сохраняет содержимое консоли в текстовый файл"""
        text = self.console.toPlainText()
        if not text.strip():
            QMessageBox.information(self, self.tr("console_empty"), self.tr("console_empty_msg"))
            return
        # имя по умолчанию с датой/временем
        default_name = f"console_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        path, _ = QFileDialog.getSaveFileName(self, self.tr("console_save_title"), default_name,
                                               self.tr("console_save_text_files"))
        if path:
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(text)
                self.log(self.tr("console_log_saved").format(path=path))
                QMessageBox.information(self, self.tr("console_saved"),
                                        self.tr("console_saved_msg").format(path=path))
            except Exception as e:
                QMessageBox.critical(self, self.tr("error_title"), str(e))
    
    def get_scrcpy_path(self):
        # 1. Сначала ищем в PATH (Linux/macOS: обычно ставится пакетным менеджером,
        #    Windows: может быть в PATH если установщик добавил).
        which = shutil.which('scrcpy')
        if which:
            return which

        # 2. Ищем в директории программы (Windows: портативная версия рядом с .exe/.py).
        if getattr(sys, 'frozen', False):
            base_path = getattr(sys, '_MEIPASS', None) or os.path.dirname(sys.executable)
        else:
            base_path = os.path.dirname(os.path.abspath(__file__))

        possible_paths = [
            # Windows
            os.path.join(base_path, 'scrcpy', 'scrcpy.exe'),
            os.path.join(base_path, 'scrcpy.exe'),
            os.path.join(base_path, 'tools', 'scrcpy', 'scrcpy.exe'),
            os.path.join(base_path, 'bin', 'scrcpy.exe'),
            # Linux/macOS
            os.path.join(base_path, 'scrcpy', 'scrcpy'),
            os.path.join(base_path, 'scrcpy'),
            os.path.join(base_path, 'bin', 'scrcpy'),
            os.path.join(base_path, 'tools', 'scrcpy', 'scrcpy'),
        ]

        for path in possible_paths:
            if os.path.exists(path) and os.access(path, os.X_OK):
                return path
        return None
    
    def show_message_box(self, title, message, icon=QMessageBox.Information, buttons=QMessageBox.Ok):
        msg_box = QMessageBox()
        msg_box.setWindowTitle(title)
        msg_box.setText(message)
        msg_box.setIcon(icon)
        msg_box.setStandardButtons(buttons)
        
        theme = self.themes[self.current_theme]
        msg_box.setStyleSheet(f"""
            QMessageBox {{
                background-color: {theme['main_bg']};
                color: {theme['label_text']};
            }}
            QMessageBox QLabel {{
                color: {theme['label_text']};
                background-color: {theme['main_bg']};
                font-size: 11px;
            }}
            QMessageBox QPushButton {{
                background-color: {theme['button_bg']};
                color: {theme['button_text']};
                border: 1px solid {theme['button_text']};
                border-radius: 8px;
                padding: 5px 15px;
                min-width: 80px;
                font-size: 11px;
            }}
            QMessageBox QPushButton:hover {{
                background-color: {theme['button_hover_bg']};
                color: {theme['button_hover_text']};
            }}
        """)
        
        return msg_box.exec_()
    
    def apply_theme(self):
        theme = self.themes[self.current_theme]
        
        self.setStyleSheet(f"""
            QMainWindow {{ background-color: {theme['main_bg']}; }}
            
            QPushButton {{ 
                background-color: {theme['button_bg']}; 
                color: {theme['button_text']}; 
                border: 1px solid {theme['button_text']}; 
                padding: 8px; 
                font-weight: bold;
                border-radius: 8px;
                font-size: 11px;
                min-height: 30px;
            }}
            
            QPushButton:hover {{ 
                background-color: {theme['button_hover_bg']}; 
                color: {theme['button_hover_text']}; 
            }}
            
            QPushButton:disabled {{ 
                border-color: #666; 
                color: #666; 
            }}
            
            QTextEdit {{ 
                background-color: {theme['console_bg']}; 
                color: {theme['console_text']}; 
                font-family: 'Consolas'; 
                border: 1px solid {theme['group_border']}; 
                border-radius: 8px;
                font-size: 10px; 
            }}
            
            QLabel {{ 
                color: {theme['label_text']}; 
                font-size: 11px; 
            }}
            
            QGroupBox {{ 
                color: {theme['group_text']}; 
                border: 1px solid {theme['group_border']}; 
                border-radius: 8px;
                margin-top: 10px; 
                font-size: 12px; 
                font-weight: bold;
            }}
            
            QGroupBox::title {{ 
                subcontrol-origin: margin; 
                left: 10px; 
                padding: 0 5px 0 5px; 
            }}
            
            QProgressBar {{ 
                border: 1px solid {theme['group_border']}; 
                border-radius: 8px; 
                text-align: center; 
                height: 20px; 
            }}
            
            QProgressBar::chunk {{ 
                background-color: {theme['progress_bg']}; 
                border-radius: 7px; 
            }}
            
            QComboBox {{
                background-color: {theme['button_bg']};
                color: {theme['button_text']};
                border: 1px solid {theme['button_text']};
                border-radius: 8px;
                padding: 5px;
                font-size: 11px;
                min-width: 100px;
            }}
            
            QComboBox:hover {{
                background-color: {theme['button_hover_bg']};
                color: {theme['button_hover_text']};
            }}
            
            QComboBox::drop-down {{
                border: none;
            }}
            
            QComboBox QAbstractItemView {{
                background-color: {theme['button_bg']};
                color: {theme['button_text']};
                selection-background-color: {theme['button_hover_bg']};
                selection-color: {theme['button_hover_text']};
            }}
            
            QTabWidget::pane {{
                border: 1px solid {theme['group_border']};
                border-radius: 8px;
                background-color: {theme['main_bg']};
            }}
            
            QTabBar::tab {{
                background-color: {theme['button_bg']};
                color: {theme['button_text']};
                padding: 8px 12px;
                margin-right: 2px;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
            }}
            
            QTabBar::tab:selected {{
                background-color: {theme['button_hover_bg']};
                color: {theme['button_hover_text']};
            }}
            
            QTabBar::tab:hover {{
                background-color: {theme['button_hover_bg']};
                color: {theme['button_hover_text']};
            }}
            
            QFrame {{
                border-radius: 8px;
            }}
        """)
        
        self.update_status_display()
    
    def update_status_display(self):
        theme = self.themes[self.current_theme]
        if self.device_state in ['ADB MISSING', 'OFFLINE']:
            self.status_lbl.setStyleSheet(f'color: {theme["status_offline"]}; font-weight: bold; font-size: 14px;')
        else:
            self.status_lbl.setStyleSheet(f'color: {theme["status_online"]}; font-weight: bold; font-size: 14px;')
    
    def change_language(self, lang_code):
        self.current_lang = lang_code
        self.load_language()
        # Сохраняем текущую тему до обновления UI
        current_theme = self.current_theme
        self.update_ui_texts(update_theme_selector=True)
        # Восстанавливаем выбранную тему по оригинальному названию
        self.set_theme_by_original_name(current_theme)
        self.console.append(f"> Language: {lang_code}")    
            
    def set_theme_by_original_name(self, original_name):
        """Установить тему по оригинальному имени"""
        for i in range(self.theme_selector.count()):
            # Получаем оригинальное имя для каждого пункта
            for theme_name in self.themes.keys():
                if self.tr(f"theme_{theme_name}") == self.theme_selector.itemText(i):
                    if theme_name == original_name:
                        self.theme_selector.setCurrentIndex(i)
                        self.current_theme = original_name
                        self.apply_theme()
                        return
                        break
    
    def update_progress(self, value):
        self.progress_bar.setValue(value)
    
    def show_progress(self, show=True):
        self.progress_bar.setVisible(show)
        if show:
            self.progress_bar.setValue(0)
    
    def run_with_thread(self, cmd, description):
        self.show_progress(True)
        self.install_thread = InstallThread(cmd, description)
        self.install_thread.output_signal.connect(self.log)
        self.install_thread.progress_signal.connect(self.update_progress)
        self.install_thread.finished_signal.connect(self.on_install_finished)
        self.install_thread.start()
    
    def on_install_finished(self, success, message):
        self.show_progress(False)
        if success:
            self.show_message_box(self.tr("success_title"), message, QMessageBox.Information)
        else:
            self.show_message_box(self.tr("error_title"), message, QMessageBox.Critical)
        self.log(message)
    
    def run_cmd_thread(self, cmd):
        def target():
            self.log(f'Executing: {cmd}')
            try:
                si = _make_startupinfo()
                process = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, startupinfo=si)
                for line in process.stdout:
                    decoded_line = line.decode(ADB_ENCODING, errors='ignore').strip()
                    if decoded_line:
                        self.console.append(decoded_line)
                process.wait()
                self.log('Done.')
            except Exception as e:
                self.log(f'Error: {str(e)}')
        threading.Thread(target=target, daemon=True).start()
    
    def check_device_status(self):
        try:
            si = _make_startupinfo()
            res_adb = subprocess.run('adb devices', shell=True, capture_output=True, startupinfo=si)
            adb_out = (res_adb.stdout + res_adb.stderr).decode(ADB_ENCODING, errors='ignore')
            res_fb = subprocess.run('fastboot devices', shell=True, capture_output=True, startupinfo=si)
            fb_out = (res_fb.stdout + res_fb.stderr).decode(ADB_ENCODING, errors='ignore')
            
            if 'не является внутренней' in adb_out or 'not recognized' in adb_out or 'command not found' in adb_out:
                self.device_state = 'ADB MISSING'
            else:
                if 'sideload' in adb_out:
                    self.device_state = 'SIDELOAD'
                elif 'recovery' in adb_out:
                    self.device_state = 'RECOVERY'
                elif 'List of devices attached' in adb_out and len(adb_out.strip().split('\n')) > 1:
                    self.device_state = 'ADB'
                elif fb_out.strip() and (not ('не является' in fb_out or 'not recognized' in fb_out or 'command not found' in fb_out)):
                    try:
                        res_var = subprocess.run('fastboot getvar version 2>&1', shell=True, capture_output=True, startupinfo=si, timeout=3)
                        var_out = (res_var.stdout + res_var.stderr).decode(ADB_ENCODING, errors='ignore').lower()
                        if 'fastbootd' in var_out:
                            self.device_state = 'FASTBOOTD'
                        else:
                            self.device_state = 'FASTBOOT'
                    except:
                        self.device_state = 'FASTBOOT'
                else:
                    self.device_state = 'OFFLINE'
                    
            # Переводим статус на выбранный язык
            if self.device_state == 'ADB MISSING':
                self.status_lbl.setText(self.tr("status_adb_missing"))
            elif self.device_state == 'OFFLINE':
                self.status_lbl.setText(self.tr("status_offline"))
            elif self.device_state == 'SIDELOAD':
                self.status_lbl.setText(self.tr("status_sideload"))
            elif self.device_state == 'RECOVERY':
                self.status_lbl.setText(self.tr("status_recovery"))
            elif self.device_state == 'ADB':
                self.status_lbl.setText(self.tr("status_adb"))
            elif self.device_state == 'FASTBOOT':
                self.status_lbl.setText(self.tr("status_fastboot"))
            elif self.device_state == 'FASTBOOTD':
                self.status_lbl.setText(self.tr("status_fastbootd"))
            else:
                self.status_lbl.setText(self.device_state)
                
            self.update_status_display()
                
            is_connected = self.device_state not in ['OFFLINE', 'ADB MISSING']
            self.btn_system.setEnabled(is_connected)
            self.btn_recovery.setEnabled(is_connected)
            self.btn_bootloader.setEnabled(is_connected)
            self.btn_install.setEnabled(self.device_state == 'ADB')
            self.btn_bypass.setEnabled(self.device_state == 'ADB')
            self.btn_sideload.setEnabled(self.device_state in ['SIDELOAD', 'ADB'])
            self.btn_scrcpy.setEnabled(self.device_state == 'ADB' and self.scrcpy_path is not None)
            self.btn_device_info.setEnabled(self.device_state == 'ADB')
            self.btn_package_manager.setEnabled(self.device_state == 'ADB')
            self.btn_logcat.setEnabled(self.device_state == 'ADB')
            self.btn_explorer.setEnabled(self.device_state == 'ADB')
            self.btn_debloat.setEnabled(self.device_state == 'ADB')
            self.btn_screenshot.setEnabled(self.device_state == 'ADB')
            # Wireless ADB доступен всегда — даже когда нет устройства, для подключения по Wi-Fi
            self.btn_wireless_adb.setEnabled(True)

            is_fastboot_mode = self.device_state in ['FASTBOOT', 'FASTBOOTD']
            self.btn_fastbootd.setEnabled(is_fastboot_mode or self.device_state == 'ADB')
            self.btn_partition_manager.setEnabled(is_fastboot_mode)
            self.btn_partition_manager_quick.setEnabled(is_fastboot_mode)
            self.btn_unlock_fastboot.setEnabled(is_fastboot_mode)
            self.btn_relock_fastboot.setEnabled(is_fastboot_mode)
            self.btn_switch_slot.setEnabled(is_fastboot_mode)
            self.btn_unlock_ability.setEnabled(is_fastboot_mode)
            
            gsi_enabled = self.device_state == 'FASTBOOT'
            self.btn_install_gsi_ab.setEnabled(gsi_enabled and self.gsi_image_path is not None)
            self.btn_install_gsi_aonly.setEnabled(gsi_enabled and self.gsi_image_path is not None)
            self.btn_wipe_data.setEnabled(gsi_enabled)
            self.btn_select_gsi.setEnabled(gsi_enabled)
            self.btn_check_slot.setEnabled(gsi_enabled)
                
        except Exception as e:
            self.status_lbl.setText(self.tr("status_error"))
    
    def handle_reboot(self):
        # Используем identity кнопки, а не её текст — это безопасно при любой локализации.
        # Defensive: action всегда приводится к lower-case на случай, если кто-то
        # в будущем будет брать его из текста кнопки (баг v4: "BootLoader" с большой
        # буквы приводил к `adb reboot BootLoader` и телефон уходил в систему, а не
        # в bootloader — Android registry-sensitive к регистру reboot-target).
        sender = self.sender()
        if sender == self.btn_system:
            action = 'system'
        elif sender == self.btn_recovery:
            action = 'recovery'
        elif sender == self.btn_bootloader:
            action = 'bootloader'
        else:
            return
        action = action.lower()

        if self.device_state == 'FASTBOOT' or self.device_state == 'FASTBOOTD':
            if action == 'bootloader':
                cmd = 'fastboot reboot-bootloader'
            elif action == 'system':
                cmd = 'fastboot reboot'
            else:
                cmd = f'fastboot reboot {action}'
        else:
            if action == 'system':
                cmd = 'adb reboot'
            else:
                cmd = f'adb reboot {action}'
        self.run_cmd_thread(cmd)
    
    def reboot_to_fastbootd(self):
        if self.device_state == 'ADB':
            self.run_cmd_thread('adb reboot fastboot')
            self.log(self.tr("reboot_fastbootd_log"))
        elif self.device_state == 'FASTBOOT':
            self.run_cmd_thread('fastboot reboot fastboot')
            self.log(self.tr("reboot_fastbootd_log"))
        else:
            self.show_message_box(self.tr("wrong_mode"), self.tr("wrong_mode_adb_fastboot"), QMessageBox.Warning)
    
    def install_apk(self):
        file_path, _ = QFileDialog.getOpenFileName(self, self.tr("select_apk"), '', self.tr("select_apk_filter"))
        if file_path:
            self.run_cmd_thread(f'adb install "{file_path}"')
    
    def run_sideload(self):
        file_path, _ = QFileDialog.getOpenFileName(self, self.tr("select_firmware"), '', self.tr("select_firmware_filter"))
        if file_path:
            self.show_message_box(self.tr("sideload_title"), self.tr("sideload_msg"), QMessageBox.Information)
            self.run_cmd_thread(f'adb sideload "{file_path}"')
    
    def bypass_setup(self):
        cmd = 'adb shell settings put global setup_wizard_has_run 1 && adb shell settings put secure user_setup_complete 1 && adb shell settings put global device_provisioned 1'
        self.log(self.tr("bypass_log"))
        self.run_cmd_thread(cmd)
    
    def run_scrcpy(self):
        if self.scrcpy_path is None:
            self.show_message_box(self.tr("scrcpy_not_found"),
                              self.tr("scrcpy_not_found_msg"), QMessageBox.Warning)
            return
            
        self.log(self.tr("scrcpy_starting"))
        try:
            si = _make_startupinfo()
            cmd = f'"{self.scrcpy_path}"'
            subprocess.Popen(cmd, shell=True, startupinfo=si)
            self.log(self.tr("scrcpy_started"))
        except Exception as e:
            self.log(f"Error: {str(e)}")
    
    def unlock_bootloader_fastboot(self):
        reply = self.show_message_box(self.tr("unlock_title"),
                                    self.tr("unlock_msg"),
                                    QMessageBox.Warning, QMessageBox.Yes | QMessageBox.No)
        
        if reply == QMessageBox.Yes:
            self.log(self.tr("unlock_start"))
            self.log(self.tr("unlock_warn"))
            
            commands = [
                'fastboot oem unlock',
                'fastboot flashing unlock',
                'fastboot oem unlock-go'
            ]
            
            self.show_message_box(self.tr("unlock_instructions_title"),
                                self.tr("unlock_instructions_msg"),
                                QMessageBox.Information)
            
            for cmd in commands:
                self.log(self.tr("unlock_trying").format(cmd=cmd))
                self.run_cmd_thread(cmd)
                
            self.log(self.tr("unlock_success_msg"))
            self.log(self.tr("unlock_fail_msg"))

    def relock_bootloader_fastboot(self):
        """Relock bootloader (обратная операция к unlock)"""
        reply = self.show_message_box(
            self.tr("relock_title"),
            self.tr("relock_msg"),
            QMessageBox.Warning, QMessageBox.Yes | QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            self.log(self.tr("relock_start"))
            commands = [
                'fastboot flashing lock',
                'fastboot oem lock',
                'fastboot oem lock-go'
            ]
            for cmd in commands:
                self.log(self.tr("unlock_trying").format(cmd=cmd))
                self.run_cmd_thread(cmd)
            self.log(self.tr("relock_success_msg"))

    def switch_ab_slot(self):
        """Переключение активного A/B слота на противоположный"""
        if self.device_state not in ['FASTBOOT', 'FASTBOOTD']:
            self.show_message_box(self.tr("wrong_mode"), self.tr("wrong_mode_fastboot"), QMessageBox.Warning)
            return

        # Сначала узнаём текущий слот
        try:
            si = _make_startupinfo()
            result = subprocess.run('fastboot getvar current-slot', shell=True,
                                    capture_output=True, startupinfo=si, text=True,
                                    encoding=ADB_ENCODING, errors='ignore', timeout=5)
            out = (result.stdout or "") + (result.stderr or "")
        except Exception as e:
            self.show_message_box(self.tr("error_title"),
                                  self.tr("slot_check_error_msg").format(error=str(e)),
                                  QMessageBox.Critical)
            return

        current = None
        for line in out.split('\n'):
            if 'current-slot:' in line.lower():
                current = line.lower().split('current-slot:')[-1].strip()
                break

        if current not in ('a', 'b'):
            self.show_message_box(self.tr("slot_not_supported_title"),
                                  self.tr("slot_not_supported_msg"),
                                  QMessageBox.Warning)
            return

        target = 'b' if current == 'a' else 'a'
        reply = QMessageBox.question(
            self, self.tr("slot_switch_title"),
            self.tr("slot_switch_msg").format(current=current.upper(), target=target.upper()),
            QMessageBox.Yes | QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            cmd = f'fastboot --set-active={target}'
            self.log(self.tr("slot_switching").format(current=current.upper(), target=target.upper()))
            self.run_cmd_thread(cmd)

    def check_unlock_ability(self):
        """Проверка возможности разблокировки (важно для Xiaomi и др.)"""
        if self.device_state not in ['FASTBOOT', 'FASTBOOTD']:
            self.show_message_box(self.tr("wrong_mode"), self.tr("wrong_mode_fastboot"), QMessageBox.Warning)
            return

        self.log(self.tr("unlock_ability_check"))
        try:
            si = _make_startupinfo()
            commands = [
                'fastboot oem device-info',
                'fastboot flashing get_unlock_ability',
                'fastboot oem get-token',
            ]
            for cmd in commands:
                self.log(f"> {cmd}")
                result = subprocess.run(cmd, shell=True, capture_output=True,
                                        startupinfo=si, text=True,
                                        encoding='utf-8', errors='ignore', timeout=5)
                out = (result.stdout or "") + (result.stderr or "")
                for line in out.split('\n'):
                    if line.strip():
                        self.log(line.strip())
            self.show_message_box(self.tr("unlock_ability_title"),
                                  self.tr("unlock_ability_msg"),
                                  QMessageBox.Information)
        except Exception as e:
            self.log(f"Error: {str(e)}")

    def take_screenshot(self):
        """Делает скриншот экрана устройства и сохраняет на ПК"""
        if self.device_state != 'ADB':
            self.show_message_box(self.tr("wrong_mode"),
                                  self.tr("wrong_mode_adb_screenshot"),
                                  QMessageBox.Warning)
            return

        default_name = f"screenshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        save_path, _ = QFileDialog.getSaveFileName(self, self.tr("screenshot_save_title"), default_name,
                                                    "PNG Image (*.png);;All Files (*.*)")
        if not save_path:
            return

        self.log(self.tr("screenshot_saving").format(name=os.path.basename(save_path)))
        try:
            si = _make_startupinfo()
            # На Windows `adb exec-out screencap -p` даёт CRLF-искажения.
            # Надёжнее: screencap в /sdcard, затем adb pull
            tmp_remote = '/sdcard/_screenshot_tmp.png'
            subprocess.run(f'adb shell screencap -p {tmp_remote}', shell=True,
                           startupinfo=si, timeout=10)
            subprocess.run(f'adb pull "{tmp_remote}" "{save_path}"', shell=True,
                           startupinfo=si, timeout=15)
            # чистим временный файл
            subprocess.run(f'adb shell rm {tmp_remote}', shell=True,
                           startupinfo=si, timeout=5)

            if os.path.exists(save_path) and os.path.getsize(save_path) > 0:
                self.log(self.tr("screenshot_saved").format(path=save_path))
                self.show_message_box(self.tr("screenshot_saved_title"),
                                      self.tr("screenshot_saved_msg").format(path=save_path),
                                      QMessageBox.Information)
            else:
                self.show_message_box(self.tr("screenshot_failed_title"),
                                      self.tr("screenshot_failed_msg"),
                                      QMessageBox.Critical)
        except subprocess.TimeoutExpired:
            self.show_message_box(self.tr("screenshot_timeout_title"),
                                  self.tr("screenshot_timeout_msg"), QMessageBox.Warning)
        except Exception as e:
            self.show_message_box(self.tr("screenshot_error_title"), str(e), QMessageBox.Critical)

    # =============================================================
    # Update system (бесплатный GitHub-based авто-апдейт)
    # =============================================================
    def check_for_updates_manual(self):
        """Ручная проверка — запускается по кнопке в About."""
        self.log(f"Checking for updates (current: v{CURRENT_VERSION})...")
        self.btn_check_updates.setEnabled(False)
        self.btn_check_updates.setText(self.tr("update_checking"))
        self._update_checker = UpdateChecker()
        self._update_checker.update_available.connect(self._on_update_available)
        self._update_checker.no_update.connect(self._on_no_update)
        self._update_checker.error.connect(self._on_update_error)
        self._update_checker.start()

    def check_for_updates_auto(self):
        """Тихая авто-проверка при старте — не чаще раза в UPDATE_CHECK_INTERVAL_HOURS.
        Молча логирует, не показывает диалог если обновлений нет."""
        if "USERNAME" in UPDATE_MANIFEST_URL or "REPO" in UPDATE_MANIFEST_URL:
            # URL ещё не настроен — пропускаем тихо
            return
        settings = QSettings("AdbFastboot", "Community")
        last_check = settings.value("last_update_check", 0, type=int)
        now = int(datetime.now().timestamp())
        if (now - last_check) < UPDATE_CHECK_INTERVAL_HOURS * 3600:
            return  # уже проверяли недавно
        settings.setValue("last_update_check", now)

        self.log("Auto-checking for updates...")
        self._auto_updater = UpdateChecker()
        self._auto_updater.update_available.connect(self._on_update_available)
        # silent: не показываем "no update" или "error" — только логируем
        self._auto_updater.no_update.connect(
            lambda: self.log("You're on the latest version.")
        )
        self._auto_updater.error.connect(
            lambda e: self.log(f"Update check failed: {e}")
        )
        self._auto_updater.start()

    def _on_update_available(self, manifest):
        self.btn_check_updates.setEnabled(True)
        self.btn_check_updates.setText(self.tr("update_btn_check_again"))
        remote_ver = manifest.get('version', '?')
        self.log(f"Update available: v{remote_ver}")
        dlg = UpdateDialog(manifest, self)
        dlg.exec_()

    def _on_no_update(self):
        self.btn_check_updates.setEnabled(True)
        self.btn_check_updates.setText(self.tr("update_btn_check_again"))
        self.log("You're on the latest version.")
        QMessageBox.information(self, self.tr("update_up_to_date_title"),
                                self.tr("update_up_to_date_text").format(
                                    version=CURRENT_VERSION
                                ))

    def _on_update_error(self, err):
        self.btn_check_updates.setEnabled(True)
        self.btn_check_updates.setText(self.tr("update_btn_check_again"))
        self.log(f"Update check failed: {err}")
        QMessageBox.warning(self, self.tr("update_error_title"),
                            self.tr("update_error_text").format(err=err))

    def open_package_manager(self):
        if self.device_state != 'ADB':
            self.show_message_box(self.tr("error_title"), self.tr("wrong_mode_adb"), QMessageBox.Warning)
            return
        
        self.package_manager = PackageManagerDialog(self)
        self.package_manager.exec_()
    
    def open_logcat(self):
        if self.device_state != 'ADB':
            self.show_message_box(self.tr("error_title"), self.tr("wrong_mode_adb"), QMessageBox.Warning)
            return
        self.logcat_dialog = LogcatDialog(self)
        self.logcat_dialog.exec_()
    
    def open_wireless_adb(self):
        # Wireless ADB можно открыть всегда — даже для подключения
        self.wireless_adb_dialog = WirelessAdbDialog(self)
        self.wireless_adb_dialog.exec_()
    
    def open_explorer(self):
        if self.device_state != 'ADB':
            self.show_message_box(self.tr("error_title"), self.tr("wrong_mode_adb"), QMessageBox.Warning)
            return
        self.explorer_dialog = AdbExplorerDialog(self)
        self.explorer_dialog.exec_()
    
    def open_debloat(self):
        if self.device_state != 'ADB':
            self.show_message_box(self.tr("error_title"), self.tr("wrong_mode_adb"), QMessageBox.Warning)
            return
        self.debloat_dialog = DebloatDialog(self)
        self.debloat_dialog.exec_()
    
    def open_partition_manager(self):
        if self.device_state not in ['FASTBOOT', 'FASTBOOTD']:
            self.show_message_box(self.tr("error_title"), self.tr("wrong_mode_fastboot_or_fastbootd"), QMessageBox.Warning)
            return
        
        self.partition_manager = PartitionManagerDialog(self)
        self.partition_manager.exec_()
    
    def select_gsi_image(self):
        file_path, _ = QFileDialog.getOpenFileName(self, self.tr("select_gsi_image"), '', 'GSI Image (*.img);;All Files (*.*)')
        if file_path:
            self.gsi_image_path = file_path
            self.gsi_label.setText(f"📁 {os.path.basename(file_path)}")
            self.log(self.tr("gsi_selected_log").format(name=os.path.basename(file_path)))
            self.show_message_box(self.tr("gsi_selected_title"),
                                  self.tr("gsi_selected_msg").format(name=os.path.basename(file_path)),
                                  QMessageBox.Information)
            self.check_device_status()
    
    def check_current_slot(self):
        self.log(self.tr("slot_checking"))
    
        try:
            si = _make_startupinfo()
            result = subprocess.run('fastboot getvar current-slot', 
                              shell=True, 
                              capture_output=True,
                              startupinfo=si,
                              text=True,
                              encoding=ADB_ENCODING,
                              errors='ignore',
                              timeout=5)
        
            output = result.stdout.strip()
            self.log(self.tr("slot_output").format(output=output))
        
            if 'current-slot:' in output:
                slot = output.split('current-slot:')[-1].strip()
                self.slot_info_label.setText(self.tr("slot_result").format(slot=slot))
                self.log(self.tr("slot_current").format(slot=slot))
            else:
                self.slot_info_label.setText(self.tr("slot_ab_device"))
            
        except Exception as e:
                self.log(f"Error: {str(e)}")
                self.slot_info_label.setText(self.tr("slot_error"))
    
    def complete_wipe_data(self):
        reply = self.show_message_box(self.tr("wipe_title"), self.tr("wipe_msg"), QMessageBox.Question, QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            self.log(self.tr("wipe_start"))
            commands = ['fastboot erase userdata', 'fastboot erase cache', 'fastboot reboot recovery']
            cmd_string = ' && '.join(commands)
            self.run_with_thread(cmd_string, 'Data Wipe')
    
    def install_gsi(self, ab_device=True):
        if not self.gsi_image_path:
            self.show_message_box(self.tr("gsi_no_gsi_title"), self.tr("gsi_no_gsi_msg"), QMessageBox.Warning)
            return
        if not os.path.exists(self.gsi_image_path):
            self.show_message_box(self.tr("gsi_not_found_title"), self.tr("gsi_not_found_msg"), QMessageBox.Warning)
            return
            
        device_type = "A/B" if ab_device else "A-Only"
        reply = self.show_message_box(self.tr("gsi_install_title"),
                                      self.tr("gsi_install_msg").format(
                                          device_type=device_type,
                                          image=os.path.basename(self.gsi_image_path)
                                      ),
                                      QMessageBox.Question, QMessageBox.Yes | QMessageBox.No)
        
        if reply == QMessageBox.Yes:
            self.log(self.tr("gsi_installing").format(device_type=device_type))
            if ab_device:
                commands = ['fastboot erase system', f'fastboot flash system "{self.gsi_image_path}"', 'fastboot --set-active=a', 'fastboot reboot recovery']
            else:
                commands = ['fastboot erase system', f'fastboot flash system "{self.gsi_image_path}"', 'fastboot reboot recovery']
            cmd_string = ' && '.join(commands)
            self.run_with_thread(cmd_string, f'GSI Install {device_type}')
            QTimer.singleShot(2000, lambda: self.show_message_box(self.tr("gsi_important_title"),
                                                                  self.tr("gsi_important_msg"),
                                                                  QMessageBox.Information))
    
    def get_device_info(self):
        if self.device_state != 'ADB':
            self.show_message_box(self.tr("error_title"), self.tr("wrong_mode_adb"), QMessageBox.Warning)
            return
        
        self.log("=" * 50)
        self.log(self.tr("device_info_start"))
        self.log("=" * 50)
        
        info_text = ""
        
        def run_adb_command(cmd):
            try:
                si = _make_startupinfo()
                result = subprocess.run(cmd, shell=True, capture_output=True, startupinfo=si, 
                                      text=True, encoding=ADB_ENCODING, errors='ignore', timeout=5)
                return result.stdout.strip()
            except:
                return "N/A"
        
        manufacturer = run_adb_command('adb shell getprop ro.product.manufacturer')
        model = run_adb_command('adb shell getprop ro.product.model')
        android_version = run_adb_command('adb shell getprop ro.build.version.release')
        android_sdk = run_adb_command('adb shell getprop ro.build.version.sdk')
        
        battery_info = run_adb_command('adb shell dumpsys battery')
        battery_level = "N/A"
        if battery_info != "N/A":
            level_match = re.search(r'level:\s*(\d+)', battery_info)
            if level_match:
                battery_level = f"{level_match.group(1)}%"
        
        info_text = self.tr("device_info_header") + "\n\n" + \
            self.tr("device_info_device").format(manufacturer=manufacturer or 'N/A', model=model or 'N/A') + "\n" + \
            self.tr("device_info_android").format(version=android_version or 'N/A', sdk=android_sdk or 'N/A') + "\n" + \
            self.tr("device_info_battery").format(level=battery_level) + "\n\n" + \
            self.tr("device_info_full_below")
        
        self.info_display.setText(info_text)
        
        product_name = run_adb_command('adb shell getprop ro.product.name')
        device_code = run_adb_command('adb shell getprop ro.product.device')
        
        self.log(self.tr("device_info_manufacturer").format(value=manufacturer or 'N/A'))
        self.log(self.tr("device_info_model").format(value=model or 'N/A'))
        self.log(self.tr("device_info_product").format(value=product_name or 'N/A'))
        self.log(self.tr("device_info_device_code").format(value=device_code or 'N/A'))
        
        mem_total = run_adb_command('adb shell cat /proc/meminfo 2>/dev/null | grep MemTotal')
        if mem_total != "N/A" and mem_total:
            total_match = re.search(r'MemTotal:\s*(\d+)', mem_total)
            if total_match:
                total_kb = int(total_match.group(1))
                total_ram = f"{total_kb // 1024} MB ({total_kb / (1024*1024):.2f} GB)"
                self.log(self.tr("device_info_ram").format(value=total_ram))
        
        kernel_version = run_adb_command('adb shell uname -a 2>/dev/null')
        if kernel_version and kernel_version != "N/A":
            kernel_short = kernel_version[:80] + "..." if len(kernel_version) > 80 else kernel_version
            self.log(self.tr("device_info_kernel").format(value=kernel_short))
        
        self.log("=" * 50)
        self.log(self.tr("device_info_success"))
        self.log("=" * 50)
        
        self.show_message_box(self.tr("device_info_title"), info_text, QMessageBox.Information)

if __name__ == '__main__':
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    
    window = ADBLiteApp()
    window.show()
    sys.exit(app.exec_())
