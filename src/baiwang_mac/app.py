from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QLocale, QObject, QProcess, QRunnable, QSettings, QSize, Qt, QThreadPool, QTimer, Signal, Slot
from PySide6.QtGui import QAction, QCloseEvent, QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
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
    QScrollArea,
    QSpinBox,
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
from .compact import CompactData, CompactPanel
from .contacts import Contact, import_csv, import_vcard, load_contacts, save_contacts
from .documents import DISCLAIMER_TEXT, HELP_TEXT, PRIVACY_TEXT, TERMS_TEXT, TIPS_TEXT
from .i18n import apply_widget_language, translate
from .launch_agent import install as install_launch_agent
from .launch_agent import installed as launch_agent_installed
from .launch_agent import uninstall as uninstall_launch_agent
from .network import NetworkManager, NetworkStatus
from .onboarding import OnboardingWizard
from .telemetry import TrafficMonitor, TrafficSnapshot, format_bytes, format_speed_pair


APP_NAME = "4G Dongle Manager"
DATA_NAME = "Baiwang Connect"  # Preserve existing contacts and message history.


def app_icon(size: int = 128) -> QIcon:
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    source = root / "assets" / "4g-dongle-icon.png"
    pixmap = QPixmap(str(source))
    if pixmap.isNull():
        return QIcon()
    return QIcon(pixmap.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))


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
        self.setMinimumHeight(88)
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
    def __init__(self, background: bool = False, demo: bool = False, language_override: str | None = None):
        super().__init__()
        self.demo = demo
        self.controller = BaiwangController()
        self.network = NetworkManager()
        self.pool = QThreadPool.globalInstance()
        self._active_workers: set[Worker] = set()
        self.settings = QSettings("goodday00", DATA_NAME)
        self.ui_language = language_override or self.settings.value("ui_language", "zh_CN")
        saved_locale = self.settings.value("locale", "system")
        if saved_locale != "system":
            QLocale.setDefault(QLocale(saved_locale))
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
        self._traffic_warned = False
        self._balance_warned = False
        self._network_detail_busy = False
        self.last_device_status = DeviceStatus()
        self.last_network_status: NetworkStatus | None = None
        self.traffic_snapshot: TrafficSnapshot | None = None
        self.public_exit_ip = ""
        self.public_exit_location = ""
        self.latency_ms: float | None = None
        self.usb_power_ma: int | None = None
        self._last_ip_lookup = 0.0
        self.baiwang_interface = self.network.baiwang_interface()
        self.traffic_monitor = TrafficMonitor(
            self.baiwang_interface,
            self.data_dir / "traffic-usage.json",
            int(self.settings.value("cycle_reset_day", 1)),
        )

        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(app_icon())
        self.resize(1040, 720)
        self.setMinimumSize(900, 620)
        self._build_ui()
        self._build_tray()
        self._apply_style()
        self.apply_ui_language()
        if self.settings.value("mini_pinned", False, bool):
            QTimer.singleShot(500, self.pin_mini_window)

        if demo:
            self.apply_demo_data()
        else:
            self.poll_timer = QTimer(self)
            self.poll_timer.timeout.connect(self.refresh_all)
            self.poll_timer.start(10_000)
            self.sms_timer = QTimer(self)
            self.sms_timer.timeout.connect(self.poll_sms)
            self.sms_timer.start(15_000)
            self.telemetry_timer = QTimer(self)
            self.telemetry_timer.timeout.connect(self.sample_telemetry)
            self.telemetry_timer.start(1_000)
            self.network_detail_timer = QTimer(self)
            self.network_detail_timer.timeout.connect(self.refresh_network_details)
            self.network_detail_timer.start(60_000)
            QTimer.singleShot(200, self.refresh_all)
            QTimer.singleShot(2_000, self.sample_telemetry)
            QTimer.singleShot(5_000, self.refresh_network_details)
        if not demo and not background and not self.settings.value("onboarding_complete", False, bool):
            QTimer.singleShot(800, self.run_onboarding)

        if background:
            QTimer.singleShot(0, self.hide)

    def show_default_surface(self):
        self.mini_window.show()
        self.mini_window.raise_()
        self.mini_window.activateWindow()

    def show_popover_preview(self):
        screen = QApplication.primaryScreen().availableGeometry()
        self.popover.adjustSize()
        self.popover.move(screen.right() - self.popover.width() - 30, screen.top() + 30)
        self.popover.show()
        self.popover.raise_()

    def capture_surfaces(self, directory: str):
        target = Path(directory)
        target.mkdir(parents=True, exist_ok=True)
        self.mini_window.show()
        QApplication.processEvents()
        self.mini_window.grab().save(str(target / "implementation-mini.png"), "PNG")
        self.mini_window.hide()
        self.popover.show()
        QApplication.processEvents()
        self.popover.grab().save(str(target / "implementation-popover.png"), "PNG")
        self.popover.hide()
        QApplication.instance().quit()

    def apply_demo_data(self):
        data = CompactData(
            usable=True,
            state_text="可以正常使用",
            carrier="中国电信",
            network="4G LTE",
            signal_percent=90,
            quota_configured=True,
            used_text="已用 38.40 GB / 100 GB",
            remaining_text="剩余 61.60 GB",
            quota_percent=38,
            quota_state="未超量",
            balance_text="¥42.60",
            balance_state="充足",
            down_speed="1.08 MB/s",
            up_speed="0.15 MB/s",
        )
        self.popover.update_data(data)
        self.mini_window.update_data(data)
        apply_widget_language(self.popover, self.ui_language)
        apply_widget_language(self.mini_window, self.ui_language)

    def _build_ui(self):
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(14)

        header = QHBoxLayout()
        title_box = QVBoxLayout()
        title = QLabel("4G Dongle Manager")
        title.setObjectName("pageTitle")
        subtitle = QLabel("兼容 DJI 第一代 4G 模块 · 独立第三方工具")
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
        self.tabs.addTab(self._sms_center_tab(), "短信中心")
        self.tabs.addTab(self._contacts_tab(), "通讯录")
        self.tabs.addTab(self._settings_tab(), "设置")
        root.addWidget(self.tabs)
        self.setCentralWidget(central)
        self.setStatusBar(QStatusBar())

    def _overview_tab(self) -> QWidget:
        page = QWidget()
        page.setMinimumWidth(860)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 18, 4, 4)
        layout.setSpacing(16)

        cards = QGridLayout()
        cards.setSpacing(12)
        self.cards = {
            "carrier": StatusCard("SIM 运营商"),
            "network": StatusCard("当前移动网络"),
            "band": StatusCard("4G 使用频段"),
            "ip": StatusCard("模块网络地址"),
            "ims": StatusCard("短信服务"),
            "temperature": StatusCard("内部最高温度"),
            "route": StatusCard("Mac 当前上网出口"),
            "public_ip": StatusCard("公网出口 IP（地区为推断）"),
            "power": StatusCard("USB 供电额度（非实时功耗）"),
        }
        for idx, card in enumerate(self.cards.values()):
            cards.addWidget(card, idx // 4, idx % 4)
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

        usage_group = QGroupBox("流量、网速与延迟")
        usage_layout = QGridLayout(usage_group)
        self.session_time_label = QLabel("本次连接：00:00:00")
        self.session_usage_label = QLabel("本次流量：0 B")
        self.cycle_usage_label = QLabel("本周期：尚未统计")
        self.remaining_usage_label = QLabel("剩余：请在设置中填写套餐")
        self.live_speed_label = QLabel("实时：↓ 0 B/s  ↑ 0 B/s")
        self.average_speed_label = QLabel("当前平均：↓ 0 B/s  ↑ 0 B/s")
        self.latency_label = QLabel("延迟：正在检测")
        self.usage_bar = QProgressBar()
        self.usage_bar.setRange(0, 100)
        self.usage_bar.setTextVisible(False)
        usage_layout.addWidget(self.session_time_label, 0, 0)
        usage_layout.addWidget(self.session_usage_label, 0, 1)
        usage_layout.addWidget(self.cycle_usage_label, 1, 0)
        usage_layout.addWidget(self.remaining_usage_label, 1, 1)
        usage_layout.addWidget(self.usage_bar, 2, 0, 1, 2)
        usage_layout.addWidget(self.live_speed_label, 3, 0)
        usage_layout.addWidget(self.average_speed_label, 3, 1)
        usage_layout.addWidget(self.latency_label, 4, 0)
        speed_test = QPushButton("手动测速（会消耗流量）")
        speed_test.clicked.connect(self.run_speed_test)
        usage_layout.addWidget(speed_test, 4, 1)
        layout.addWidget(usage_group)

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
        apply_network = QPushButton("切换网络")
        apply_network.setObjectName("primary")
        apply_network.clicked.connect(self.apply_network_mode)
        network_layout.addWidget(apply_network)
        layout.addWidget(network_group)

        radio_group = QGroupBox("4G 网络制式")
        radio_layout = QHBoxLayout(radio_group)
        info = QLabel("通常保持“自动”。只有网络不稳定时才尝试“仅 LTE”；软件不能放大物理信号。")
        info.setWordWrap(True)
        radio_layout.addWidget(info, 1)
        self.radio_mode = QComboBox()
        self.radio_mode.addItem("自动（推荐）", "auto")
        self.radio_mode.addItem("仅 LTE", "lte")
        radio_layout.addWidget(self.radio_mode)
        apply_radio = QPushButton("保存模式")
        apply_radio.clicked.connect(self.apply_radio_mode)
        radio_layout.addWidget(apply_radio)
        layout.addWidget(radio_group)
        layout.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(page)
        return scroll

    def _sms_center_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 4, 0, 0)
        self.sms_tabs = QTabWidget()
        self.sms_tabs.addTab(self._messages_tab(), "收件与发送")
        self.sms_tabs.addTab(self._sent_tab(), "发送记录")
        layout.addWidget(self.sms_tabs)
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

        plan = QGroupBox("套餐、余额与显示")
        plan_layout = QFormLayout(plan)
        self.quota_input = QDoubleSpinBox()
        self.quota_input.setRange(0, 100000)
        self.quota_input.setDecimals(2)
        self.quota_input.setSuffix(" GB / 周期")
        self.quota_input.setValue(float(self.settings.value("quota_gb", 0)))
        self.reset_day_input = QSpinBox()
        self.reset_day_input.setRange(1, 28)
        self.reset_day_input.setValue(int(self.settings.value("cycle_reset_day", 1)))
        self.reset_day_input.setPrefix("每月 ")
        self.reset_day_input.setSuffix(" 日")
        self.balance_input = QDoubleSpinBox()
        self.balance_input.setRange(-100000, 100000)
        self.balance_input.setDecimals(2)
        self.balance_input.setPrefix("¥ ")
        self.balance_input.setValue(float(self.settings.value("plan_balance", 0)))
        self.traffic_threshold_input = QDoubleSpinBox()
        self.traffic_threshold_input.setRange(0, 100000)
        self.traffic_threshold_input.setDecimals(2)
        self.traffic_threshold_input.setSuffix(" GB")
        self.traffic_threshold_input.setValue(float(self.settings.value("traffic_warning_gb", 10)))
        self.balance_threshold_input = QDoubleSpinBox()
        self.balance_threshold_input.setRange(0, 100000)
        self.balance_threshold_input.setDecimals(2)
        self.balance_threshold_input.setPrefix("¥ ")
        self.balance_threshold_input.setValue(float(self.settings.value("balance_warning", 10)))
        self.speed_unit_combo = QComboBox()
        self.speed_unit_combo.addItem("字节/秒（MB/s、KB/s、B/s）", "bytes")
        self.speed_unit_combo.addItem("比特/秒（Mbps、Kbps、bps）", "bits")
        self.speed_unit_combo.setCurrentIndex(max(0, self.speed_unit_combo.findData(self.settings.value("speed_family", "bytes"))))
        self.ip_lookup_checkbox = QCheckBox("查询公网出口国家/地区（访问第三方 IP 数据库）")
        self.ip_lookup_checkbox.setChecked(self.settings.value("allow_ip_lookup", False, bool))
        plan_layout.addRow("套餐总流量", self.quota_input)
        plan_layout.addRow("周期重置日", self.reset_day_input)
        plan_layout.addRow("当前余额（用户填写）", self.balance_input)
        plan_layout.addRow("剩余流量提醒阈值", self.traffic_threshold_input)
        plan_layout.addRow("余额提醒阈值", self.balance_threshold_input)
        plan_layout.addRow("网速单位", self.speed_unit_combo)
        plan_layout.addRow("公网地区", self.ip_lookup_checkbox)
        save_plan = QPushButton("保存套餐与显示设置")
        save_plan.setObjectName("primary")
        save_plan.clicked.connect(self.save_plan_settings)
        plan_layout.addRow("", save_plan)
        layout.addWidget(plan)

        reminders = QGroupBox("提醒事项")
        reminders_layout = QVBoxLayout(reminders)
        self.traffic_alert_checkbox = QCheckBox("剩余流量临近阈值或已经超量")
        self.balance_alert_checkbox = QCheckBox("套餐余额临近阈值")
        self.disconnect_alert_checkbox = QCheckBox("模块断开、SIM 缺失或入网失败")
        self.temperature_alert_checkbox = QCheckBox("模块温度过高")
        for key, widget in (
            ("traffic_alert", self.traffic_alert_checkbox),
            ("balance_alert", self.balance_alert_checkbox),
            ("disconnect_alert", self.disconnect_alert_checkbox),
            ("temperature_alert", self.temperature_alert_checkbox),
        ):
            widget.setChecked(self.settings.value(key, True, bool))
            widget.toggled.connect(lambda checked, setting_key=key: self.settings.setValue(setting_key, checked))
            reminders_layout.addWidget(widget)
        layout.addWidget(reminders)

        language = QGroupBox("语言与地区")
        language_layout = QFormLayout(language)
        self.ui_language_combo = QComboBox()
        self.ui_language_combo.addItem("简体中文", "zh_CN")
        self.ui_language_combo.addItem("繁體中文", "zh_TW")
        self.ui_language_combo.addItem("English", "en_US")
        self.ui_language_combo.setCurrentIndex(max(0, self.ui_language_combo.findData(self.ui_language)))
        self.ui_language_combo.currentIndexChanged.connect(self.save_locale)
        language_layout.addRow("界面语言", self.ui_language_combo)
        self.locale_combo = QComboBox()
        self.locale_combo.setProperty("i18n_skip", True)
        self.locale_combo.setEditable(True)
        self.locale_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.locale_combo.setMaxVisibleItems(18)
        self.locale_combo.addItem("跟随 macOS 系统设置", "system")
        seen: set[str] = set()
        locale_entries: list[tuple[str, str]] = []
        for locale in QLocale.matchingLocales(
            QLocale.Language.AnyLanguage,
            QLocale.Script.AnyScript,
            QLocale.Country.AnyCountry,
        ):
            code = locale.name()
            if code in seen or code == "C":
                continue
            seen.add(code)
            language_name = locale.nativeLanguageName() or QLocale.languageToString(locale.language())
            territory_name = locale.nativeTerritoryName() or QLocale.territoryToString(locale.territory())
            label = f"{language_name} — {territory_name}（{code}）" if territory_name else f"{language_name}（{code}）"
            locale_entries.append((label, code))
        for label, code in sorted(locale_entries, key=lambda item: item[0].casefold()):
            self.locale_combo.addItem(label, code)
        saved_locale = self.settings.value("locale", "system")
        locale_index = self.locale_combo.findData(saved_locale)
        self.locale_combo.setCurrentIndex(max(0, locale_index))
        self.locale_combo.currentIndexChanged.connect(self.save_locale)
        language_layout.addRow("国家/地区格式", self.locale_combo)
        language_note = QLabel("界面语言只列出已完成翻译的语言；国家/地区格式负责日期、数字、货币和单位显示。")
        language_note.setObjectName("muted")
        language_note.setWordWrap(True)
        language_layout.addRow("", language_note)
        layout.addWidget(language)

        help_group = QGroupBox("使用小贴士、帮助与说明")
        help_layout = QHBoxLayout(help_group)
        for title, text in (("使用小贴士", TIPS_TEXT), ("软件帮助", HELP_TEXT)):
            button = QPushButton(title)
            button.clicked.connect(lambda _checked=False, t=title, body=text: self.show_document(t, body))
            help_layout.addWidget(button)
        tutorial = QPushButton("重新运行首次引导")
        tutorial.clicked.connect(self.run_onboarding)
        help_layout.addWidget(tutorial)
        help_layout.addStretch()
        layout.addWidget(help_group)

        legal = QGroupBox("隐私、条款与免责声明")
        legal_layout = QHBoxLayout(legal)
        for title, text in (("用户协议", TERMS_TEXT), ("隐私说明", PRIVACY_TEXT), ("免责声明", DISCLAIMER_TEXT)):
            button = QPushButton(title)
            button.clicked.connect(lambda _checked=False, t=title, body=text: self.show_document(t, body))
            legal_layout.addWidget(button)
        legal_layout.addStretch()
        layout.addWidget(legal)

        about = QGroupBox("关于")
        about_layout = QVBoxLayout(about)
        about_layout.addWidget(QLabel("4G Dongle Manager 0.3.0 · 独立第三方兼容工具 · 专有软件"))
        layout.addWidget(about)
        layout.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(page)
        return scroll

    def save_locale(self, _index: int):
        ui_language = self.ui_language_combo.currentData()
        locale_name = self.locale_combo.currentData()
        if not locale_name or not ui_language:
            return
        language_changed = ui_language != self.ui_language
        self.ui_language = ui_language
        self.settings.setValue("ui_language", ui_language)
        self.settings.setValue("locale", locale_name)
        if locale_name == "system":
            QLocale.setDefault(QLocale.system())
        else:
            QLocale.setDefault(QLocale(locale_name))
        self.settings.sync()
        if language_changed:
            QTimer.singleShot(150, self.restart_for_language)
        else:
            self.statusBar().showMessage(self.t("语言与地区设置已保存"), 5000)

    def restart_for_language(self):
        executable = str(Path(sys.executable).resolve())
        QProcess.startDetached(executable, [])
        QApplication.instance().quit()

    def t(self, text: str) -> str:
        return translate(text, self.ui_language)

    def apply_ui_language(self):
        apply_widget_language(self, self.ui_language)
        if hasattr(self, "popover"):
            apply_widget_language(self.popover, self.ui_language)
            apply_widget_language(self.mini_window, self.ui_language)

    def save_plan_settings(self):
        self.settings.setValue("quota_gb", self.quota_input.value())
        self.settings.setValue("cycle_reset_day", self.reset_day_input.value())
        self.settings.setValue("plan_balance", self.balance_input.value())
        self.settings.setValue("balance_configured", True)
        self.settings.setValue("traffic_warning_gb", self.traffic_threshold_input.value())
        self.settings.setValue("balance_warning", self.balance_threshold_input.value())
        self.settings.setValue("speed_family", self.speed_unit_combo.currentData())
        self.settings.setValue("allow_ip_lookup", self.ip_lookup_checkbox.isChecked())
        self.settings.sync()
        self.traffic_monitor.set_reset_day(self.reset_day_input.value())
        self._traffic_warned = False
        self._balance_warned = False
        self._last_ip_lookup = 0.0
        self.sample_telemetry()
        self.refresh_network_details()
        self.statusBar().showMessage("套餐、提醒阈值和显示单位已保存", 5000)

    def show_document(self, title: str, body: str):
        dialog = QDialog(self)
        dialog.setWindowTitle(self.t(title))
        dialog.resize(680, 520)
        layout = QVBoxLayout(dialog)
        content = QPlainTextEdit(self.t(body))
        content.setReadOnly(True)
        layout.addWidget(content)
        close = QPushButton(self.t("关闭"))
        close.clicked.connect(dialog.accept)
        layout.addWidget(close, alignment=Qt.AlignmentFlag.AlignRight)
        dialog.exec()

    def run_onboarding(self):
        wizard = OnboardingWizard(self.settings, self.show_document, self)
        apply_widget_language(wizard, self.ui_language)
        if wizard.exec() == QDialog.DialogCode.Accepted:
            if hasattr(self, "quota_input"):
                self.quota_input.setValue(float(self.settings.value("quota_gb", 0)))
                self.reset_day_input.setValue(int(self.settings.value("cycle_reset_day", 1)))
                self.balance_input.setValue(float(self.settings.value("plan_balance", 0)))
                self.ip_lookup_checkbox.setChecked(self.settings.value("allow_ip_lookup", False, bool))
            self.traffic_monitor.set_reset_day(int(self.settings.value("cycle_reset_day", 1)))
            self.sample_telemetry()
            self.refresh_network_details()

    @staticmethod
    def _format_duration(seconds: int) -> str:
        hours, remainder = divmod(max(0, int(seconds)), 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

    def _compact_data(self) -> CompactData:
        device = self.last_device_status
        network = self.last_network_status
        traffic = self.traffic_snapshot
        usable = bool(device.sim_ready and device.registered and network and network.baiwang_active)
        if not self._last_present:
            state_text = "模块未连接"
            carrier_text = "请插入兼容 4G 模块"
        elif not device.sim_ready:
            state_text = "未检测到 SIM 卡"
            carrier_text = "请检查 SIM 卡"
        elif not device.registered:
            state_text = "正在连接移动网络"
            carrier_text = device.carrier
        elif usable:
            state_text = "可以正常使用"
            carrier_text = device.carrier
        else:
            state_text = "Mac 尚未使用 4G 网络"
            carrier_text = device.carrier

        used_bytes = traffic.cycle_total if traffic else 0
        quota_gb = float(self.settings.value("quota_gb", 0))
        quota_bytes = quota_gb * 1024**3
        quota_configured = quota_bytes > 0
        remaining = max(0.0, quota_bytes - used_bytes)
        quota_percent = round(min(100, used_bytes / quota_bytes * 100)) if quota_configured else 0
        warning_bytes = float(self.settings.value("traffic_warning_gb", 10)) * 1024**3
        if not quota_configured:
            quota_state = "请设置套餐"
        elif used_bytes >= quota_bytes:
            quota_state = "已经超量"
        elif remaining <= warning_bytes:
            quota_state = "临近流量上限"
        else:
            quota_state = "未超量"

        balance_configured = self.settings.value("balance_configured", False, bool)
        balance = float(self.settings.value("plan_balance", 0))
        balance_threshold = float(self.settings.value("balance_warning", 10))
        balance_state = "余额偏低" if balance_configured and balance <= balance_threshold else "充足"
        speed_family = self.settings.value("speed_family", "bytes")
        down, up = format_speed_pair(
            traffic.down_bytes_per_second if traffic else 0,
            traffic.up_bytes_per_second if traffic else 0,
            speed_family,
        )
        network_name = "4G LTE" if "LTE" in device.network.upper() else device.network
        return CompactData(
            usable=usable,
            state_text=state_text,
            carrier=carrier_text,
            network=network_name,
            signal_percent=device.signal_percent,
            quota_configured=quota_configured,
            used_text=f"已用 {format_bytes(used_bytes)} / {quota_gb:g} GB" if quota_configured else "--",
            remaining_text=f"剩余 {format_bytes(remaining)}" if quota_configured else "",
            quota_percent=quota_percent,
            quota_state=quota_state,
            balance_text=f"¥{balance:.2f}" if balance_configured else "未设置",
            balance_state=balance_state if balance_configured else "",
            down_speed=down,
            up_speed=up,
        )

    def update_compact_views(self):
        data = self._compact_data()
        self.popover.update_data(data)
        self.mini_window.update_data(data)
        apply_widget_language(self.popover, self.ui_language)
        apply_widget_language(self.mini_window, self.ui_language)
        self.tray.setToolTip(f"{APP_NAME} · {self.t(data.state_text)}")

    def sample_telemetry(self):
        active = bool(self.last_network_status and self.last_network_status.baiwang_active)
        try:
            self.traffic_snapshot = self.traffic_monitor.sample(active)
        except Exception as exc:
            self.statusBar().showMessage(f"读取流量统计失败：{exc}", 3000)
            return
        traffic = self.traffic_snapshot
        self.session_time_label.setText(self.t(f"本次连接：{self._format_duration(traffic.session_seconds)}"))
        self.session_usage_label.setText(self.t(f"本次流量：{format_bytes(traffic.session_total)}"))
        self.cycle_usage_label.setText(self.t(f"本周期已用：{format_bytes(traffic.cycle_total)}（本机统计）"))
        quota_gb = float(self.settings.value("quota_gb", 0))
        quota_bytes = quota_gb * 1024**3
        if quota_bytes > 0:
            remaining = max(0.0, quota_bytes - traffic.cycle_total)
            percent = round(min(100, traffic.cycle_total / quota_bytes * 100))
            self.remaining_usage_label.setText(self.t(f"剩余：{format_bytes(remaining)} / {quota_gb:g} GB"))
            self.usage_bar.setValue(percent)
        else:
            self.remaining_usage_label.setText(self.t("剩余：请在设置中填写套餐"))
            self.usage_bar.setValue(0)
        family = self.settings.value("speed_family", "bytes")
        down, up = format_speed_pair(traffic.down_bytes_per_second, traffic.up_bytes_per_second, family)
        average_down, average_up = format_speed_pair(
            traffic.average_down_bytes_per_second,
            traffic.average_up_bytes_per_second,
            family,
        )
        self.live_speed_label.setText(self.t(f"实时：↓ {down}  ↑ {up}"))
        self.average_speed_label.setText(self.t(f"当前平均：↓ {average_down}  ↑ {average_up}"))
        self.update_compact_views()
        self.check_usage_warnings()

    def check_usage_warnings(self):
        if not self.traffic_snapshot:
            return
        quota_gb = float(self.settings.value("quota_gb", 0))
        quota_bytes = quota_gb * 1024**3
        warning_bytes = float(self.settings.value("traffic_warning_gb", 10)) * 1024**3
        remaining = quota_bytes - self.traffic_snapshot.cycle_total
        should_warn = quota_bytes > 0 and remaining <= warning_bytes
        if should_warn and not self._traffic_warned and self.settings.value("traffic_alert", True, bool):
            text = "套餐流量已经超出设置值" if remaining <= 0 else f"套餐流量预计只剩 {format_bytes(remaining)}"
            self.tray.showMessage("流量提醒", text)
            self._traffic_warned = True
        elif not should_warn:
            self._traffic_warned = False
        balance_configured = self.settings.value("balance_configured", False, bool)
        balance = float(self.settings.value("plan_balance", 0))
        balance_threshold = float(self.settings.value("balance_warning", 10))
        should_balance_warn = balance_configured and balance <= balance_threshold
        if should_balance_warn and not self._balance_warned and self.settings.value("balance_alert", True, bool):
            self.tray.showMessage("余额提醒", f"用户填写的套餐余额为 ¥{balance:.2f}，请向运营商核实。")
            self._balance_warned = True
        elif not should_balance_warn:
            self._balance_warned = False

    def refresh_network_details(self):
        if self._network_detail_busy or not self._last_present:
            return
        self._network_detail_busy = True
        allow_lookup = self.settings.value("allow_ip_lookup", False, bool)
        lookup_due = allow_lookup and time.monotonic() - self._last_ip_lookup >= 900

        def collect():
            latency = self.network.latency(self.baiwang_interface)
            power = self.network.usb_power_allocation()
            public = self.network.public_exit(self.baiwang_interface) if lookup_due else None
            return latency, power, public

        def success(result):
            latency, power, public = result
            self.latency_ms = latency
            self.usb_power_ma = power
            self.latency_label.setText(self.t(f"延迟：{latency:.0f} ms" if latency is not None else "延迟：检测失败"))
            if power is None:
                self.cards["power"].value.setText("macOS 未返回")
            else:
                watts = power * 5 / 1000
                self.cards["power"].value.setText(f"最高约 {watts:.1f} W（{power} mA）")
            if public:
                ip, country, city = public
                self.public_exit_ip = ip
                self.public_exit_location = " · ".join(item for item in (country, city) if item)
                location = self.public_exit_location or "地区未知"
                self.cards["public_ip"].value.setText(f"{ip}\n{location}（IP 数据库推断）")
                self._last_ip_lookup = time.monotonic()
            elif not allow_lookup:
                self.cards["public_ip"].value.setText("未启用地区查询")

        self.run_worker(collect, success, lambda _error: None, lambda: setattr(self, "_network_detail_busy", False))

    def run_speed_test(self):
        answer = QMessageBox.question(
            self,
            "手动测速",
            "测速会产生下载和上传流量，实际消耗量由测试过程决定，可能超过 100 MB。是否继续？",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.statusBar().showMessage("正在测速，请保持模块连接…")

        def success(result):
            QMessageBox.information(
                self,
                "测速完成",
                f"下载：{result['download']:.2f} {result['download_unit']}\n"
                f"上传：{result['upload']:.2f} {result['upload_unit']}\n\n"
                "本次测速流量会自动计入本机周期统计。",
            )

        self.run_worker(lambda: self.network.speed_test(self.baiwang_interface), success)

    def _build_tray(self):
        self.tray = QSystemTrayIcon(app_icon(64), self)
        self.tray.setToolTip(APP_NAME)
        self.popover = CompactPanel("popover", app_icon(64))
        self.mini_window = CompactPanel("mini", app_icon(64))
        self.popover.open_full.connect(self.show_window)
        self.popover.open_sms.connect(self.open_sms_center)
        self.popover.open_settings.connect(self.open_settings)
        self.popover.pin_requested.connect(self.pin_mini_window)
        self.popover.speed_test_requested.connect(self.run_speed_test)
        self.mini_window.open_full.connect(self.show_window)
        self.mini_window.open_sms.connect(self.open_sms_center)
        self.mini_window.unpin_requested.connect(self.unpin_mini_window)
        menu = QMenu(self)
        self.tray_menu = menu
        show_action = QAction("打开完整界面", self)
        show_action.triggered.connect(self.show_window)
        pin_action = QAction("固定状态小窗", self)
        pin_action.triggered.connect(self.pin_mini_window)
        refresh_action = QAction("刷新状态", self)
        refresh_action.triggered.connect(self.refresh_all)
        quit_action = QAction("退出", self)
        quit_action.triggered.connect(QApplication.instance().quit)
        menu.addAction(show_action)
        menu.addAction(pin_action)
        menu.addAction(refresh_action)
        menu.addSeparator()
        menu.addAction(quit_action)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self.handle_tray_activation)
        self.tray.show()

    def handle_tray_activation(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.toggle_popover()

    def toggle_popover(self):
        if self.popover.isVisible():
            self.popover.hide()
            return
        tray_rect = self.tray.geometry()
        screen = QApplication.screenAt(tray_rect.center()) or QApplication.primaryScreen()
        available = screen.availableGeometry()
        self.popover.adjustSize()
        x = min(
            max(available.left() + 8, tray_rect.center().x() - self.popover.width() // 2),
            available.right() - self.popover.width() - 8,
        )
        y = max(available.top() + 8, tray_rect.bottom() + 8)
        self.popover.move(x, y)
        self.popover.show()
        self.popover.raise_()
        self.popover.activateWindow()

    def pin_mini_window(self):
        self.settings.setValue("mini_pinned", True)
        self.popover.hide()
        self.mini_window.show()
        self.mini_window.raise_()
        self.mini_window.activateWindow()

    def unpin_mini_window(self):
        self.settings.setValue("mini_pinned", False)
        self.mini_window.hide()

    def open_sms_center(self):
        self.tabs.setCurrentIndex(1)
        self.show_window()

    def open_settings(self):
        self.tabs.setCurrentIndex(3)
        self.show_window()

    def _apply_style(self):
        self.setStyleSheet(
            """
            QMainWindow, QWidget { background: #FBFCFE; color: #172033; font-size: 14px; }
            QLabel#pageTitle { font-size: 26px; font-weight: 700; color: #101828; }
            QLabel#muted { color: #667085; }
            QLabel#badge { background: #F2F4F7; color: #475467; padding: 9px 14px; border-radius: 12px; font-weight: 600; }
            QFrame#statusCard, QGroupBox { background: white; border: 1px solid #E4E7EC; border-radius: 12px; }
            QLabel#cardValue { font-size: 18px; font-weight: 650; color: #101828; }
            QGroupBox { margin-top: 12px; padding: 14px; font-weight: 650; }
            QGroupBox::title { subcontrol-origin: margin; left: 14px; padding: 0 5px; }
            QPushButton { background: #FFFFFF; border: 1px solid #D0D5DD; border-radius: 8px; padding: 8px 14px; min-height: 26px; }
            QPushButton:hover { background: #F2F4F7; }
            QPushButton:disabled { background: #EAECF0; color: #98A2B3; border-color: #EAECF0; }
            QPushButton#primary { background: #101828; color: white; border: none; font-weight: 650; }
            QPushButton#primary:hover { background: #344054; }
            QPushButton#primary:disabled { background: #EAECF0; color: #98A2B3; }
            QLineEdit, QPlainTextEdit, QComboBox { background: white; border: 1px solid #D0D5DD; border-radius: 8px; padding: 8px; }
            QComboBox { min-height: 26px; }
            QTableWidget { background: white; border: 1px solid #E4E7EC; border-radius: 8px; gridline-color: #EAECF0; }
            QHeaderView::section { background: #F9FAFB; padding: 8px; border: none; border-bottom: 1px solid #EAECF0; font-weight: 650; }
            QTabWidget::pane { border: none; }
            QTabBar::tab { padding: 10px 20px; color: #667085; }
            QTabBar::tab:selected { color: #067647; border-bottom: 2px solid #12B76A; font-weight: 650; }
            QProgressBar { background: #EAECF0; border: none; border-radius: 6px; height: 12px; }
            QProgressBar::chunk { background: #12B76A; border-radius: 6px; }
            """
        )

    def run_worker(self, fn, on_result=None, on_error=None, on_finished=None):
        worker = Worker(fn)
        # PySide may otherwise destroy the Python QRunnable wrapper while Qt
        # still has queued events for its signal object, causing a Shiboken
        # use-after-free crash on the main thread.
        worker.setAutoDelete(False)
        self._active_workers.add(worker)
        if on_result:
            worker.signals.result.connect(on_result)
        worker.signals.error.connect(on_error or self.show_error)

        def finish_worker():
            if on_finished:
                on_finished()
            QTimer.singleShot(250, lambda: self._active_workers.discard(worker))

        worker.signals.finished.connect(finish_worker)
        self.pool.start(worker)

    def refresh_all(self):
        present = is_baiwang_present()
        if present != self._last_present:
            self._last_present = present
            if present:
                self.tray.showMessage(APP_NAME, "已检测到兼容 4G 模块")
            else:
                self.connection_badge.setText("● 模块未连接")
                self.connection_badge.setStyleSheet("background: #FEF3F2; color: #B42318;")
                self.last_device_status = DeviceStatus()
                self.update_compact_views()
        if present and not self._status_busy:
            self._status_busy = True
            self.run_worker(self.controller.get_status, self.render_status, self.status_error, lambda: setattr(self, "_status_busy", False))
        self.run_worker(self.network.status, self.render_network, lambda _error: None)

    @Slot(object)
    def render_status(self, status: DeviceStatus):
        self.last_device_status = status
        if not status.sim_ready:
            self.connection_badge.setText("● 未检测到 SIM 卡")
            self.connection_badge.setStyleSheet("background: #FFF4E5; color: #B54708;")
        elif status.registered:
            self.connection_badge.setText("● 模块已连接")
            self.connection_badge.setStyleSheet("background: #ECFDF3; color: #027A48;")
        else:
            self.connection_badge.setText("● 等待连接移动网络")
            self.connection_badge.setStyleSheet("background: #FFFAEB; color: #B54708;")
        self.cards["carrier"].value.setText(status.carrier if status.sim_ready else "未检测到 SIM 卡")
        self.cards["network"].value.setText(status.network)
        self.cards["band"].value.setText(status.band)
        self.cards["ip"].value.setText(status.ip_address)
        self.cards["ims"].value.setText("可以收发短信" if status.ims_enabled else "需要初始化")
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
        if status.signal_percent >= 80:
            quality = "很强"
        elif status.signal_percent >= 60:
            quality = "良好"
        elif status.signal_percent >= 35:
            quality = "一般"
        else:
            quality = "较弱"
        self.signal_label.setText(f"信号 {status.signal_percent}%（{quality}） · {dbm}")
        self.signal_label.setToolTip(f"技术读数：CSQ {status.signal_csq}/31")
        self.statusBar().showMessage(f"AT 接口 {status.at_interface} · {status.carrier} · {status.band}", 5000)
        self.update_compact_views()
        apply_widget_language(self, self.ui_language)
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
                self.provision_label.setText("模块已经初始化，可以直接使用 4G 上网和短信功能。")
                self.provision_label.setToolTip(f"技术配置：{profile}")
                self.provision_button.setEnabled(False)
                if self.settings.value("pending_init_success", False, bool):
                    self.settings.setValue("pending_init_success", False)
                    QMessageBox.information(
                        self,
                        "初始化成功",
                        "模块配置已保存，整个 USB 模块以后支持热插拔。接入兼容 ECM 网络的 Mac、Linux 或部分 Windows 设备时，无需安装本软件也可基础上网。\n\n"
                        "注意：未安装本软件的设备无法获得套餐流量、余额、温度和断线提醒，也不能使用本软件界面收发短信；在其他设备产生的流量不会自动计入这台 Mac。\n\n"
                        "USB 模块热插拔不等于运行中可以随意拔插 SIM 卡。",
                    )

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
            "初始化兼容 4G 模块",
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
            self.settings.setValue("pending_init_success", True)
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
        self.last_network_status = status
        if status.interface and status.interface != self.baiwang_interface:
            self.baiwang_interface = status.interface
            self.traffic_monitor.interface = status.interface
        interface = status.default_interface
        if interface.startswith("utun"):
            display = f"VPN / 代理（{interface}）"
        elif interface == status.interface:
            display = f"4G 模块（{status.interface}）"
        elif interface == "en0":
            display = "Wi-Fi（en0）"
        else:
            display = interface
        self.cards["route"].value.setText(display)
        self.sample_telemetry()
        apply_widget_language(self, self.ui_language)

    def status_error(self, message: str):
        self.connection_badge.setText("● AT 端口等待中")
        self.connection_badge.setStyleSheet("background: #F2F4F7; color: #475467;")
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
        self.popover.hide()
        self.mini_window.hide()
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
    parser.add_argument("--demo", action="store_true")
    parser.add_argument("--ui-language", choices=("zh_CN", "zh_TW", "en_US"))
    parser.add_argument("--popover-preview", action="store_true")
    parser.add_argument("--capture-surfaces")
    args, _ = parser.parse_known_args()
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("goodday00")
    app.setQuitOnLastWindowClosed(False)
    app.setWindowIcon(app_icon())
    window = MainWindow(background=args.background, demo=args.demo, language_override=args.ui_language)
    activation_ready = {"value": not args.background}

    def handle_activation(state):
        if state == Qt.ApplicationState.ApplicationActive and activation_ready["value"]:
            window.show_default_surface()

    app.applicationStateChanged.connect(handle_activation)
    if args.capture_surfaces:
        QTimer.singleShot(500, lambda: window.capture_surfaces(args.capture_surfaces))
    elif args.popover_preview:
        QTimer.singleShot(0, window.show_popover_preview)
    elif not args.background:
        QTimer.singleShot(0, window.show_default_surface)
    else:
        # Avoid opening the window during login startup. A later Finder/Dock
        # activation (for example double-clicking the app) reopens it.
        QTimer.singleShot(3000, lambda: activation_ready.update(value=True))
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
