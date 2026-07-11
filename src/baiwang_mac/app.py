from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QSettings, QSize, Qt, QThreadPool, QTimer, Signal, Slot
from PySide6.QtGui import QAction, QColor, QCloseEvent, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
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

from .backend import BaiwangController, BaiwangError, DeviceStatus, SMSMessage, is_baiwang_present
from .contacts import Contact, import_csv, import_vcard, load_contacts, save_contacts
from .launch_agent import install as install_launch_agent
from .launch_agent import installed as launch_agent_installed
from .launch_agent import uninstall as uninstall_launch_agent
from .network import NetworkManager, NetworkStatus


APP_NAME = "Baiwang Connect"


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


class MainWindow(QMainWindow):
    def __init__(self, background: bool = False):
        super().__init__()
        self.controller = BaiwangController()
        self.network = NetworkManager()
        self.pool = QThreadPool.globalInstance()
        self.settings = QSettings("goodday00", APP_NAME)
        self.data_dir = Path.home() / "Library" / "Application Support" / APP_NAME
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.contacts_path = self.data_dir / "contacts.json"
        self.contacts: list[Contact] = load_contacts(self.contacts_path)
        self._status_busy = False
        self._messages_busy = False
        self._seen_messages: set[int] | None = None
        self._last_present = False

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
        title = QLabel("Baiwang Connect")
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
        inbox_actions.addWidget(refresh)
        inbox_actions.addWidget(self.listen_checkbox)
        inbox_actions.addStretch()
        inbox_actions.addWidget(delete)
        inbox_layout.addLayout(inbox_actions)
        self.message_table = QTableWidget(0, 5)
        self.message_table.setHorizontalHeaderLabels(["编号", "状态", "发送者", "时间", "内容"])
        self.message_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.message_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.message_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.message_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
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
        about_layout.addWidget(QLabel("Baiwang Connect 0.1.0 · 开源 macOS 工具 · MIT License"))
        layout.addWidget(about)
        layout.addStretch()
        return page

    def _build_tray(self):
        self.tray = QSystemTrayIcon(app_icon(64), self)
        self.tray.setToolTip(APP_NAME)
        menu = QMenu()
        show_action = QAction("打开 Baiwang Connect", self)
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
        self.signal_bar.setValue(status.signal_percent)
        dbm = f"{status.signal_dbm} dBm" if status.signal_dbm is not None else "未知"
        self.signal_label.setText(f"{status.signal_percent}% · CSQ {status.signal_csq} · {dbm}")
        self.statusBar().showMessage(f"AT 接口 {status.at_interface} · {status.carrier} · {status.band}", 5000)

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
                self.message_table.setItem(row, col, QTableWidgetItem(value))
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

        def success(reference):
            suffix = f"（参考编号 {reference}）" if reference is not None else ""
            QMessageBox.information(self, "发送成功", f"短信已提交{suffix}")
            self.message_input.clear()
            self.refresh_messages()

        def finished():
            self.send_button.setEnabled(True)
            self.send_button.setText("发送短信")

        self.run_worker(lambda: self.controller.send_sms(number, body), success, self.show_error, finished)

    def delete_selected_message(self):
        row = self.message_table.currentRow()
        if row < 0:
            self.show_error("请先选中一条短信")
            return
        index = int(self.message_table.item(row, 0).text())
        if QMessageBox.question(self, "删除短信", f"确定删除编号 {index} 的短信吗？") == QMessageBox.StandardButton.Yes:
            self.run_worker(lambda: self.controller.delete_sms(index), lambda _: self.refresh_messages())

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
        QMessageBox.warning(self, "Baiwang Connect", message)

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
