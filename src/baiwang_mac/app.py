from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QSettings, QSize, Qt, QThreadPool, QTimer, Signal, Slot
from PySide6.QtGui import QAction, QColor, QCloseEvent, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QStatusBar,
    QSystemTrayIcon,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QMenu,
)

from .backend import BaiwangController, BaiwangError, DeviceStatus, ProvisioningInfo, SMSMessage, is_baiwang_present
from .contacts import Contact, import_csv, import_vcard, load_contacts, save_contacts
from .launch_agent import install as install_launch_agent
from .launch_agent import installed as launch_agent_installed
from .launch_agent import uninstall as uninstall_launch_agent
from .network import NetworkManager, NetworkStatus


APP_NAME = "DJI 4G Dongle Manager"
DATA_NAME = "Baiwang Connect"  # Preserve existing contacts and message history.


def app_icon(size: int = 128) -> QIcon:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor("#176BFF"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(6, 6, size - 12, size - 12, size * 0.24, size * 0.24)
    painter.setPen(QColor("white"))
    font = QFont("Helvetica Neue", int(size * 0.44), QFont.Weight.Bold)
    painter.setFont(font)
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "B")
    painter.end()
    return QIcon(pixmap)


class WorkerSignals(QObject):
    result = Signal(object)
    error = Signal(str)
    finished = Signal()


class Worker(QRunnable):
    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.signals = WorkerSignals()

    @Slot()
    def run(self):
        try:
            result = self.fn(*self.args, **self.kwargs)
            self.signals.result.emit(result)
        except Exception as exc:
            self.signals.error.emit(str(exc))
        finally:
            self.signals.finished.emit()


class StatusCard(QFrame):
    def __init__(self, title: str, value: str = "--"):
        super().__init__()
        self.setObjectName("statusCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 14)
        title_label = QLabel(title)
        title_label.setObjectName("muted")
        self.value = QLabel(value)
        self.value.setObjectName("cardValue")
        self.value.setWordWrap(True)
        layout.addWidget(title_label)
        layout.addWidget(self.value)


class MessageDetailDialog(QDialog):
    def __init__(
        self,
        sender: str,
        timestamp: str,
        body: str,
        parent=None,
        party_label: str = "发送者",
        time_label: str = "接收时间",
    ):
        super().__init__(parent)
        self.body = body
        self.setWindowTitle("短信详情")
        self.resize(620, 430)
        layout = QVBoxLayout(self)
        meta = QFormLayout()
        sender_value = QLineEdit(sender)
        sender_value.setReadOnly(True)
        time_value = QLineEdit(timestamp or "未知时间")
        time_value.setReadOnly(True)
        meta.addRow(party_label, sender_value)
        meta.addRow(time_label, time_value)
        layout.addLayout(meta)
        layout.addWidget(QLabel("短信全文"))
        content = QPlainTextEdit(body)
        content.setReadOnly(True)
        content.setMinimumHeight(250)
        layout.addWidget(content, 1)
        actions = QHBoxLayout()
        copy_button = QPushButton("复制全文")
        copy_button.setObjectName("primary")
        copy_button.clicked.connect(self.copy_body)
        close_button = QPushButton("关闭")
        close_button.clicked.connect(self.accept)
        actions.addStretch()
        actions.addWidget(copy_button)
        actions.addWidget(close_button)
        layout.addLayout(actions)

    def copy_body(self):
        QApplication.clipboard().setText(self.body)
        self.parent().statusBar().showMessage("短信内容已复制", 4000)


class MainWindow(QMainWindow):
    def __init__(self, background: bool = False):
        super().__init__()
        self.controller = BaiwangController()
        self.network = NetworkManager()
        self.pool = QThreadPool.globalInstance()
        self.settings = QSettings("goodday00", DATA_NAME)
        self.data_dir = Path.home() / "Library" / "Application Support" / DATA_NAME
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.contacts_path = self.data_dir / "contacts.json"
        self.contacts: list[Contact] = load_contacts(self.contacts_path)
        self.sent_history_path = self.data_dir / "sent-history.json"
        try:
            self.sent_history: list[dict] = json.loads(self.sent_history_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            self.sent_history = []
        self._status_busy = False
        self._messages_busy = False
        self._seen_messages: set[int] | None = None
        self._last_present = False
        self._provision_checked = False
        self._provision_busy = False
        self._provision_prompted = False
        self._provision_info: ProvisioningInfo | None = None
        self._thermal_warned = False

        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(app_icon())
        self.resize(1040, 720)
        self.setMinimumSize(900, 620)
        self._build_ui()
        self._build_tray()
        self._apply_style()

        self.poll_timer = QTimer(self)
        self.poll_timer.timeout.connect(self.refresh_all)
        self.poll_timer.start(10_000)
        self.sms_timer = QTimer(self)
        self.sms_timer.timeout.connect(self.poll_sms)
        self.sms_timer.start(15_000)
        QTimer.singleShot(200, self.refresh_all)

        if background:
            QTimer.singleShot(0, self.hide)

    def _build_ui(self):
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(14)

        header = QHBoxLayout()
        title_box = QVBoxLayout()
        title = QLabel("DJI 4G Dongle Manager")
        title.setObjectName("pageTitle")
        subtitle = QLabel("DJI 4G 模块 · 上网、短信与连接管理")
        subtitle.setObjectName("muted")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        header.addLayout(title_box)
        header.addStretch()
        self.connection_badge = QLabel("● 正在检测")
        self.connection_badge.setObjectName("badge")
        header.addWidget(self.connection_badge)
        root.addLayout(header)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._overview_tab(), "概览")
        self.tabs.addTab(self._messages_tab(), "短信")
        self.tabs.addTab(self._sent_tab(), "已发送")
        self.tabs.addTab(self._contacts_tab(), "通讯录")
        self.tabs.addTab(self._settings_tab(), "设置")
        root.addWidget(self.tabs)
        self.setCentralWidget(central)
        self.setStatusBar(QStatusBar())

    def _overview_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 18, 4, 4)
        layout.setSpacing(16)

        cards = QGridLayout()
        cards.setSpacing(12)
        self.cards = {
            "carrier": StatusCard("运营商"),
            "network": StatusCard("蜂窝网络"),
            "band": StatusCard("频段"),
            "ip": StatusCard("蜂窝 IP"),
            "ims": StatusCard("IMS 短信"),
            "temperature": StatusCard("模块温度"),
            "route": StatusCard("默认接口"),
        }
        for idx, card in enumerate(self.cards.values()):
            cards.addWidget(card, idx // 3, idx % 3)
        layout.addLayout(cards)

        signal_group = QGroupBox("信号")
        signal_layout = QHBoxLayout(signal_group)
        self.signal_label = QLabel("等待模块…")
        self.signal_bar = QProgressBar()
        self.signal_bar.setRange(0, 100)
        self.signal_bar.setTextVisible(False)
        signal_layout.addWidget(self.signal_label)
        signal_layout.addWidget(self.signal_bar, 1)
        refresh = QPushButton("刷新")
        refresh.clicked.connect(self.refresh_all)
        signal_layout.addWidget(refresh)
        layout.addWidget(signal_group)

        provision_group = QGroupBox("首次使用与模块初始化")
        provision_layout = QHBoxLayout(provision_group)
        self.provision_label = QLabel("正在检测模块配置…")
        self.provision_label.setWordWrap(True)
        provision_layout.addWidget(self.provision_label, 1)
        detect_provision = QPushButton("重新检测")
        detect_provision.clicked.connect(lambda: self.check_provisioning(auto_prompt=False))
        provision_layout.addWidget(detect_provision)
        self.provision_button = QPushButton("开始初始化")
        self.provision_button.setObjectName("primary")
        self.provision_button.setEnabled(False)
        self.provision_button.clicked.connect(self.start_initialization)
        provision_layout.addWidget(self.provision_button)
        layout.addWidget(provision_group)

        network_group = QGroupBox("Mac 网络切换")
        network_layout = QHBoxLayout(network_group)
        network_layout.addWidget(QLabel("连接策略"))
        self.network_mode = QComboBox()
        self.network_mode.addItem("自动切换（4G 优先，Wi‑Fi 备用）", "auto")
        self.network_mode.addItem("只使用 DJI 4G", "4g")
        self.network_mode.addItem("优先使用 Wi‑Fi", "wifi")
        saved_mode = self.settings.value("network_mode", "auto")
        self.network_mode.setCurrentIndex(max(0, self.network_mode.findData(saved_mode)))
        network_layout.addWidget(self.network_mode, 1)
        apply_network = QPushButton("应用")
        apply_network.setObjectName("primary")
        apply_network.clicked.connect(self.apply_network_mode)
        network_layout.addWidget(apply_network)
        layout.addWidget(network_group)

        radio_group = QGroupBox("蜂窝模式（不能放大射频信号）")
        radio_layout = QHBoxLayout(radio_group)
        info = QLabel("可选择自动网络或锁定 LTE；信号强度由位置、天线和基站决定。")
        info.setWordWrap(True)
        radio_layout.addWidget(info, 1)
        self.radio_mode = QComboBox()
        self.radio_mode.addItem("自动（推荐）", "auto")
        self.radio_mode.addItem("仅 LTE", "lte")
        radio_layout.addWidget(self.radio_mode)
        apply_radio = QPushButton("设置")
        apply_radio.clicked.connect(self.apply_radio_mode)
        radio_layout.addWidget(apply_radio)
        layout.addWidget(radio_group)
        layout.addStretch()
        return page

    def _messages_tab(self) -> QWidget:
        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(4, 18, 4, 4)
        layout.setSpacing(18)

        inbox_group = QGroupBox("收件箱")
        inbox_layout = QVBoxLayout(inbox_group)
        inbox_actions = QHBoxLayout()
        refresh = QPushButton("刷新短信")
        refresh.clicked.connect(self.refresh_messages)
        self.listen_checkbox = QCheckBox("监听新短信")
        self.listen_checkbox.setChecked(self.settings.value("listen_sms", True, bool))
        self.listen_checkbox.toggled.connect(lambda checked: self.settings.setValue("listen_sms", checked))
        delete = QPushButton("删除选中")
        delete.clicked.connect(self.delete_selected_message)
        view = QPushButton("查看全文")
        view.clicked.connect(self.show_selected_message)
        copy = QPushButton("复制内容")
        copy.clicked.connect(self.copy_selected_message)
        inbox_actions.addWidget(refresh)
        inbox_actions.addWidget(self.listen_checkbox)
        inbox_actions.addStretch()
        inbox_actions.addWidget(view)
        inbox_actions.addWidget(copy)
        inbox_actions.addWidget(delete)
        inbox_layout.addLayout(inbox_actions)
        self.message_table = QTableWidget(0, 5)
        self.message_table.setHorizontalHeaderLabels(["编号", "状态", "发送者", "时间", "内容"])
        self.message_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.message_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.message_table.setWordWrap(False)
        self.message_table.cellDoubleClicked.connect(lambda row, _column: self.show_message_detail(row))
        self.message_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.message_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.message_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.message_table.setColumnHidden(0, True)
        inbox_layout.addWidget(self.message_table)
        layout.addWidget(inbox_group, 3)

        compose_group = QGroupBox("发送短信")
        compose_layout = QVBoxLayout(compose_group)
        form = QFormLayout()
        self.phone_input = QLineEdit()
        self.phone_input.setPlaceholderText("例如 +8613800000000")
        self.message_input = QPlainTextEdit()
        self.message_input.setPlaceholderText("输入短信内容，支持中文…")
        self.message_input.setMaximumBlockCount(20)
        form.addRow("收件号码", self.phone_input)
        form.addRow("短信内容", self.message_input)
        compose_layout.addLayout(form)
        note = QLabel("发送会产生运营商短信费用。应用不会在后台自动发送。")
        note.setObjectName("muted")
        note.setWordWrap(True)
        compose_layout.addWidget(note)
        self.send_button = QPushButton("发送短信")
        self.send_button.setObjectName("primary")
        self.send_button.clicked.connect(self.send_message)
        compose_layout.addWidget(self.send_button)
        compose_layout.addStretch()
        layout.addWidget(compose_group, 2)
        return page

    def _sent_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 18, 4, 4)
        actions = QHBoxLayout()
        description = QLabel("这里保存本机发送记录。“已提交运营商”不等于对方手机已送达。")
        description.setObjectName("muted")
        actions.addWidget(description, 1)
        view = QPushButton("查看全文")
        view.clicked.connect(self.show_selected_sent_message)
        copy = QPushButton("复制内容")
        copy.clicked.connect(self.copy_selected_sent_message)
        delete = QPushButton("删除选中")
        delete.clicked.connect(self.delete_selected_sent_records)
        actions.addWidget(view)
        actions.addWidget(copy)
        actions.addWidget(delete)
        layout.addLayout(actions)
        self.sent_table = QTableWidget(0, 5)
        self.sent_table.setHorizontalHeaderLabels(["发送时间", "收件人", "状态", "参考编号", "内容"])
        self.sent_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.sent_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.sent_table.setWordWrap(False)
        self.sent_table.cellDoubleClicked.connect(lambda row, _column: self.show_sent_message_detail(row))
        self.sent_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.sent_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.sent_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.sent_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.sent_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.sent_table)
        self.render_sent_history()
        return page

    def _contacts_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 18, 4, 4)
        actions = QHBoxLayout()
        import_button = QPushButton("导入 CSV / vCard")
        import_button.clicked.connect(self.import_contacts)
        use_button = QPushButton("用于发送短信")
        use_button.setObjectName("primary")
        use_button.clicked.connect(self.use_selected_contact)
        actions.addWidget(import_button)
        actions.addWidget(use_button)
        actions.addStretch()
        layout.addLayout(actions)
        self.contact_table = QTableWidget(0, 2)
        self.contact_table.setHorizontalHeaderLabels(["姓名", "电话"])
        self.contact_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.contact_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.contact_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.contact_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.contact_table.doubleClicked.connect(self.use_selected_contact)
        layout.addWidget(self.contact_table)
        self.render_contacts()
        return page

    def _settings_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 18, 4, 4)
        behavior = QGroupBox("后台与通知")
        behavior_layout = QVBoxLayout(behavior)
        self.launch_checkbox = QCheckBox("登录 Mac 后自动启动并驻留菜单栏")
        self.launch_checkbox.setChecked(launch_agent_installed())
        self.launch_checkbox.toggled.connect(self.toggle_launch_agent)
        self.sound_checkbox = QCheckBox("收到新短信时播放提示音")
        self.sound_checkbox.setChecked(self.settings.value("sound", True, bool))
        self.sound_checkbox.toggled.connect(lambda checked: self.settings.setValue("sound", checked))
        behavior_layout.addWidget(self.launch_checkbox)
        behavior_layout.addWidget(self.sound_checkbox)
        layout.addWidget(behavior)

        privacy = QGroupBox("隐私")
        privacy_layout = QVBoxLayout(privacy)
        privacy_layout.addWidget(QLabel("短信通过 USB 在本机处理，不上传到云端。通讯录只保存在本机应用数据目录。"))
        layout.addWidget(privacy)

        about = QGroupBox("关于")
        about_layout = QVBoxLayout(about)
        about_layout.addWidget(QLabel("DJI 4G Dongle Manager 0.2.0 · 专有软件 · All rights reserved"))
        layout.addWidget(about)
        layout.addStretch()
        return page

    def _build_tray(self):
        self.tray = QSystemTrayIcon(app_icon(64), self)
        self.tray.setToolTip(APP_NAME)
        menu = QMenu()
        show_action = QAction("打开 DJI 4G Dongle Manager", self)
        show_action.triggered.connect(self.show_window)
        refresh_action = QAction("刷新状态", self)
        refresh_action.triggered.connect(self.refresh_all)
        quit_action = QAction("退出", self)
        quit_action.triggered.connect(QApplication.instance().quit)
        menu.addAction(show_action)
        menu.addAction(refresh_action)
        menu.addSeparator()
        menu.addAction(quit_action)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(lambda reason: self.show_window() if reason == QSystemTrayIcon.ActivationReason.Trigger else None)
        self.tray.show()

    def _apply_style(self):
        self.setStyleSheet(
            """
            QMainWindow, QWidget { background: #F4F6FA; color: #172033; font-size: 14px; }
            QLabel#pageTitle { font-size: 26px; font-weight: 700; color: #101828; }
            QLabel#muted { color: #667085; }
            QLabel#badge { background: #E8F1FF; color: #175CD3; padding: 7px 12px; border-radius: 12px; font-weight: 600; }
            QFrame#statusCard, QGroupBox { background: white; border: 1px solid #E4E7EC; border-radius: 12px; }
            QLabel#cardValue { font-size: 18px; font-weight: 650; color: #101828; }
            QGroupBox { margin-top: 12px; padding: 14px; font-weight: 650; }
            QGroupBox::title { subcontrol-origin: margin; left: 14px; padding: 0 5px; }
            QPushButton { background: #FFFFFF; border: 1px solid #D0D5DD; border-radius: 8px; padding: 8px 14px; }
            QPushButton:hover { background: #F2F4F7; }
            QPushButton#primary { background: #176BFF; color: white; border: none; font-weight: 650; }
            QPushButton#primary:hover { background: #155EEF; }
            QLineEdit, QPlainTextEdit, QComboBox { background: white; border: 1px solid #D0D5DD; border-radius: 8px; padding: 8px; }
            QTableWidget { background: white; border: 1px solid #E4E7EC; border-radius: 8px; gridline-color: #EAECF0; }
            QHeaderView::section { background: #F9FAFB; padding: 8px; border: none; border-bottom: 1px solid #EAECF0; font-weight: 650; }
            QTabWidget::pane { border: none; }
            QTabBar::tab { padding: 10px 20px; color: #667085; }
            QTabBar::tab:selected { color: #175CD3; border-bottom: 2px solid #176BFF; font-weight: 650; }
            QProgressBar { background: #EAECF0; border: none; border-radius: 6px; height: 12px; }
            QProgressBar::chunk { background: #12B76A; border-radius: 6px; }
            """
        )

    def run_worker(self, fn, on_result=None, on_error=None, on_finished=None):
        worker = Worker(fn)
        if on_result:
            worker.signals.result.connect(on_result)
        worker.signals.error.connect(on_error or self.show_error)
        if on_finished:
            worker.signals.finished.connect(on_finished)
        self.pool.start(worker)

    def refresh_all(self):
        present = is_baiwang_present()
        if present != self._last_present:
            self._last_present = present
            if present:
                self.tray.showMessage(APP_NAME, "已检测到 DJI Baiwang 4G 模块")
            else:
                self.connection_badge.setText("● 模块未连接")
        if present and not self._status_busy:
            self._status_busy = True
            self.run_worker(self.controller.get_status, self.render_status, self.status_error, lambda: setattr(self, "_status_busy", False))
        self.run_worker(self.network.status, self.render_network, lambda _error: None)

    @Slot(object)
    def render_status(self, status: DeviceStatus):
        self.connection_badge.setText("● 模块已连接" if status.registered else "● 等待蜂窝注册")
        self.cards["carrier"].value.setText(status.carrier)
        self.cards["network"].value.setText(status.network)
        self.cards["band"].value.setText(status.band)
        self.cards["ip"].value.setText(status.ip_address)
        self.cards["ims"].value.setText("已启用" if status.ims_enabled else "未启用")
        if status.max_temperature is None:
            self.cards["temperature"].value.setText("固件未返回")
        else:
            self.cards["temperature"].value.setText(f"{status.max_temperature} °C")
            if status.max_temperature >= 90 and not self._thermal_warned:
                self._thermal_warned = True
                self.tray.showMessage("模块温度较高", f"当前内部最高温度 {status.max_temperature} °C，请改善散热。")
            elif status.max_temperature < 80:
                self._thermal_warned = False
        self.signal_bar.setValue(status.signal_percent)
        dbm = f"{status.signal_dbm} dBm" if status.signal_dbm is not None else "未知"
        self.signal_label.setText(f"{status.signal_percent}% · CSQ {status.signal_csq} · {dbm}")
        self.statusBar().showMessage(f"AT 接口 {status.at_interface} · {status.carrier} · {status.band}", 5000)
        if not self._provision_checked and not self._provision_busy:
            QTimer.singleShot(3000, lambda: self.check_provisioning(auto_prompt=True))

    def check_provisioning(self, auto_prompt: bool = False):
        if self._provision_busy or not self._last_present:
            return
        self._provision_busy = True
        self.provision_label.setText("正在检测 USB、运营商、IMS 和短信配置…")

        def success(info: ProvisioningInfo):
            self._provision_checked = True
            self._provision_info = info
            if info.needs_initialization:
                self.provision_label.setText("需要初始化：" + "；".join(info.reasons))
                self.provision_button.setEnabled(True)
                if auto_prompt and not self._provision_prompted:
                    self._provision_prompted = True
                    QTimer.singleShot(300, self.start_initialization)
            else:
                profile = info.selected_mbn or "自动运营商配置"
                self.provision_label.setText(f"模块已经初始化，无需重复操作。当前配置：{profile}")
                self.provision_button.setEnabled(False)

        def failed(message: str):
            self.provision_label.setText(f"初始化状态检测暂时失败：{message}")

        self.run_worker(
            self.controller.inspect_provisioning,
            success,
            failed,
            lambda: setattr(self, "_provision_busy", False),
        )

    def start_initialization(self):
        info = self._provision_info
        if not info or not info.needs_initialization:
            self.check_provisioning(auto_prompt=False)
            return
        profile_text = info.target_mbn or "未知运营商：仅切换 CDC-ECM，不修改 MBN"
        details = "\n".join(f"• {reason}" for reason in info.reasons)
        answer = QMessageBox.warning(
            self,
            "初始化 DJI 4G 模块",
            "应用将写入模块的非易失配置并重启 USB。该操作通常只需执行一次。\n\n"
            f"识别运营商：{info.carrier}\n目标配置：{profile_text}\n\n{details}\n\n"
            "初始化期间请勿拔出模块。是否继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        backup = self.data_dir / "provisioning-backup.json"
        backup.write_text(
            json.dumps(
                {"saved_at": datetime.now().isoformat(timespec="seconds"), "configuration": asdict(info)},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        self._provision_busy = True
        self.provision_button.setEnabled(False)
        self.provision_label.setText("正在初始化；模块将自动重启，请勿拔出…")

        def success(_result):
            self.provision_label.setText("初始化指令已写入，等待模块重新连接并验证…")
            self._provision_checked = False
            self._provision_info = None
            QTimer.singleShot(25_000, lambda: self.check_provisioning(auto_prompt=False))
            QMessageBox.information(self, "初始化已开始", "模块正在重启。约 15–30 秒后应用会自动重新检测。")

        def failed(message: str):
            self.provision_label.setText(f"初始化失败：{message}")
            self.provision_button.setEnabled(True)
            QMessageBox.warning(self, "初始化失败", message)

        self.run_worker(
            lambda: self.controller.initialize_module(info),
            success,
            failed,
            lambda: setattr(self, "_provision_busy", False),
        )

    @Slot(object)
    def render_network(self, status: NetworkStatus):
        self.cards["route"].value.setText(status.default_interface)

    def status_error(self, message: str):
        self.connection_badge.setText("● AT 端口等待中")
        self.statusBar().showMessage(message, 5000)

    def apply_network_mode(self):
        mode = self.network_mode.currentData()
        text = self.network_mode.currentText()
        answer = QMessageBox.question(self, "切换网络", f"确定应用“{text}”吗？网络可能短暂中断。")
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.settings.setValue("network_mode", mode)
        self.run_worker(lambda: self.network.switch(mode), lambda _: self.statusBar().showMessage("网络策略已应用", 5000))

    def apply_radio_mode(self):
        mode = self.radio_mode.currentData()
        answer = QMessageBox.warning(
            self,
            "修改蜂窝模式",
            "此设置不会增强发射功率，可能造成短暂断网。确定继续吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.run_worker(lambda: self.controller.set_radio_mode(mode), lambda _: self.statusBar().showMessage("蜂窝模式已更新", 5000))

    def refresh_messages(self):
        if self._messages_busy:
            return
        self._messages_busy = True
        self.run_worker(self.controller.list_messages, self.render_messages, self.show_error, lambda: setattr(self, "_messages_busy", False))

    @Slot(object)
    def render_messages(self, messages: list[SMSMessage]):
        self.message_table.setRowCount(len(messages))
        for row, message in enumerate(messages):
            values = [str(message.index), message.status, message.sender, message.timestamp, message.body]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                if col == 4:
                    item.setToolTip("\n".join(value[i:i + 48] for i in range(0, len(value), 48)))
                self.message_table.setItem(row, col, item)
            self.message_table.setRowHeight(row, 44)
        self.statusBar().showMessage(f"已读取 {len(messages)} 条短信", 4000)

    def poll_sms(self):
        if not self.listen_checkbox.isChecked() or self._messages_busy or not self._last_present:
            return
        self._messages_busy = True
        self.run_worker(self.controller.list_messages, self.handle_polled_messages, lambda _error: None, lambda: setattr(self, "_messages_busy", False))

    @Slot(object)
    def handle_polled_messages(self, messages: list[SMSMessage]):
        current = {message.index for message in messages}
        if self._seen_messages is not None:
            new_items = [message for message in messages if message.index not in self._seen_messages]
            for message in new_items:
                preview = message.body[:60] or "（无正文）"
                self.tray.showMessage(f"来自 {message.sender}", preview, QSystemTrayIcon.MessageIcon.Information, 8000)
                if self.sound_checkbox.isChecked():
                    QApplication.beep()
        self._seen_messages = current
        self.render_messages(messages)

    def send_message(self):
        number = self.phone_input.text().strip()
        body = self.message_input.toPlainText().strip()
        if not number or not body:
            self.show_error("请输入收件号码和短信内容")
            return
        answer = QMessageBox.question(self, "确认发送", f"发送给：{number}\n\n{body}\n\n运营商可能收取短信费用。")
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.send_button.setEnabled(False)
        self.send_button.setText("正在发送…")
        record = {
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "recipient": number,
            "body": body,
            "status": "正在发送",
            "reference": "",
            "error": "",
        }
        self.sent_history.insert(0, record)
        self.save_sent_history()
        self.render_sent_history()

        def success(reference):
            suffix = f"（参考编号 {reference}）" if reference is not None else ""
            record["status"] = "已提交运营商"
            record["reference"] = str(reference) if reference is not None else ""
            self.save_sent_history()
            self.render_sent_history()
            QMessageBox.information(self, "发送成功", f"短信已提交{suffix}")
            self.message_input.clear()
            self.refresh_messages()

        def failed(message: str):
            record["status"] = "发送失败"
            record["error"] = message
            self.save_sent_history()
            self.render_sent_history()
            self.show_error(message)

        def finished():
            self.send_button.setEnabled(True)
            self.send_button.setText("发送短信")

        self.run_worker(lambda: self.controller.send_sms(number, body), success, failed, finished)

    def save_sent_history(self):
        self.sent_history_path.write_text(
            json.dumps(self.sent_history[:500], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def render_sent_history(self):
        if not hasattr(self, "sent_table"):
            return
        self.sent_table.setRowCount(len(self.sent_history))
        for row, record in enumerate(self.sent_history):
            status = record.get("status", "未知")
            if record.get("error"):
                status += f"：{record['error']}"
            values = [
                record.get("time", ""),
                record.get("recipient", ""),
                status,
                record.get("reference", ""),
                record.get("body", ""),
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                if col in (2, 4):
                    item.setToolTip("\n".join(value[i:i + 48] for i in range(0, len(value), 48)))
                self.sent_table.setItem(row, col, item)
            self.sent_table.setRowHeight(row, 44)

    def selected_sent_row(self) -> int | None:
        row = self.sent_table.currentRow()
        if row < 0:
            self.show_error("请先选中一条发送记录")
            return None
        return row

    def show_selected_sent_message(self):
        row = self.selected_sent_row()
        if row is not None:
            self.show_sent_message_detail(row)

    def show_sent_message_detail(self, row: int):
        record = self.sent_history[row]
        MessageDetailDialog(
            record.get("recipient", ""),
            record.get("time", ""),
            record.get("body", ""),
            self,
            party_label="收件人",
            time_label="发送时间",
        ).exec()

    def copy_selected_sent_message(self):
        row = self.selected_sent_row()
        if row is None:
            return
        QApplication.clipboard().setText(self.sent_history[row].get("body", ""))
        self.statusBar().showMessage("发送内容已复制", 4000)

    def delete_selected_sent_records(self):
        rows = sorted({index.row() for index in self.sent_table.selectionModel().selectedRows()}, reverse=True)
        if not rows:
            self.show_error("请先选中一条发送记录")
            return
        answer = QMessageBox.question(
            self,
            "永久删除发送记录",
            f"确定从 Mac 本地历史中永久删除选中的 {len(rows)} 条记录吗？此操作无法撤销。",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        for row in rows:
            if 0 <= row < len(self.sent_history):
                self.sent_history.pop(row)
        self.save_sent_history()
        self.render_sent_history()
        self.statusBar().showMessage("发送记录已永久删除", 4000)

    def delete_selected_message(self):
        rows = sorted({index.row() for index in self.message_table.selectionModel().selectedRows()})
        if not rows:
            self.show_error("请先选中一条短信")
            return
        indexes = [int(self.message_table.item(row, 0).text()) for row in rows]
        answer = QMessageBox.question(
            self,
            "永久删除短信",
            f"确定从 4G 模块中永久删除选中的 {len(indexes)} 条短信吗？此操作无法撤销。",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        def remove_from_module():
            for message_index in indexes:
                self.controller.delete_sms(message_index)

        self.run_worker(remove_from_module, lambda _: self.refresh_messages())

    def selected_message_row(self) -> int | None:
        row = self.message_table.currentRow()
        if row < 0:
            self.show_error("请先选中一条短信")
            return None
        return row

    def show_selected_message(self):
        row = self.selected_message_row()
        if row is not None:
            self.show_message_detail(row)

    def show_message_detail(self, row: int):
        sender = self.message_table.item(row, 2).text() if self.message_table.item(row, 2) else ""
        timestamp = self.message_table.item(row, 3).text() if self.message_table.item(row, 3) else ""
        body = self.message_table.item(row, 4).text() if self.message_table.item(row, 4) else ""
        MessageDetailDialog(sender, timestamp, body, self).exec()

    def copy_selected_message(self):
        row = self.selected_message_row()
        if row is None:
            return
        body_item = self.message_table.item(row, 4)
        QApplication.clipboard().setText(body_item.text() if body_item else "")
        self.statusBar().showMessage("短信内容已复制", 4000)

    def render_contacts(self):
        self.contact_table.setRowCount(len(self.contacts))
        for row, contact in enumerate(self.contacts):
            self.contact_table.setItem(row, 0, QTableWidgetItem(contact.name))
            self.contact_table.setItem(row, 1, QTableWidgetItem(contact.phone))

    def import_contacts(self):
        path, _ = QFileDialog.getOpenFileName(self, "导入通讯录", "", "通讯录 (*.csv *.vcf *.vcard)")
        if not path:
            return
        try:
            imported = import_csv(path) if path.lower().endswith(".csv") else import_vcard(path)
            existing = {(item.name, item.phone) for item in self.contacts}
            self.contacts.extend(item for item in imported if (item.name, item.phone) not in existing)
            save_contacts(self.contacts_path, self.contacts)
            self.render_contacts()
            self.statusBar().showMessage(f"已导入 {len(imported)} 个联系人", 5000)
        except Exception as exc:
            self.show_error(str(exc))

    def use_selected_contact(self):
        row = self.contact_table.currentRow()
        if row < 0:
            self.show_error("请先选择联系人")
            return
        self.phone_input.setText(self.contact_table.item(row, 1).text())
        self.tabs.setCurrentIndex(1)
        self.message_input.setFocus()

    def toggle_launch_agent(self, enabled: bool):
        try:
            install_launch_agent() if enabled else uninstall_launch_agent()
            self.statusBar().showMessage("开机启动设置已更新", 5000)
        except Exception as exc:
            self.launch_checkbox.blockSignals(True)
            self.launch_checkbox.setChecked(not enabled)
            self.launch_checkbox.blockSignals(False)
            self.show_error(f"更新开机启动失败：{exc}")

    def show_window(self):
        self.show()
        self.raise_()
        self.activateWindow()

    @Slot(str)
    def show_error(self, message: str):
        QMessageBox.warning(self, APP_NAME, message)

    def closeEvent(self, event: QCloseEvent):
        event.ignore()
        self.hide()
        self.tray.showMessage(APP_NAME, "应用仍在后台运行，可从菜单栏重新打开。", QSystemTrayIcon.MessageIcon.Information, 4000)


def main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--background", action="store_true")
    args, _ = parser.parse_known_args()
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("goodday00")
    app.setQuitOnLastWindowClosed(False)
    app.setWindowIcon(app_icon())
    window = MainWindow(background=args.background)
    activation_ready = {"value": not args.background}

    def handle_activation(state):
        if state == Qt.ApplicationState.ApplicationActive and activation_ready["value"]:
            window.show_window()

    app.applicationStateChanged.connect(handle_activation)
    if not args.background:
        window.show()
    else:
        # Avoid opening the window during login startup. A later Finder/Dock
        # activation (for example double-clicking the app) reopens it.
        QTimer.singleShot(3000, lambda: activation_ready.update(value=True))
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
