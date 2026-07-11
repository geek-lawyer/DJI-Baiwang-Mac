from __future__ import annotations

from dataclasses import dataclass
import re

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QCloseEvent, QColor, QFont, QIcon, QPainter, QPen
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QStyle,
    QVBoxLayout,
    QWidget,
)
import qtawesome as qta


class CircularProgress(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._value = 0
        self._used = "0 GB"
        self._total = "--"
        self.setFixedSize(142, 142)

    def setValue(self, value: int):
        self._value = max(0, min(100, int(value)))
        self.update()

    def setUsageText(self, text: str):
        match = re.search(r"([0-9.]+\s*[KMGT]?B)\s*/\s*([0-9.]+\s*[KMGT]?B)", text, re.I)
        if match:
            self._used, self._total = match.groups()
        self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(11, 11, -11, -11)
        painter.setPen(QPen(QColor("#E4E7EC"), 9, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawArc(rect, 0, 360 * 16)
        painter.setPen(QPen(QColor("#12B76A"), 9, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawArc(rect, 90 * 16, -self._value * 360 * 16 // 100)
        painter.setPen(QColor("#067647"))
        painter.setFont(QFont(".AppleSystemUIFont", 18, QFont.Weight.DemiBold))
        painter.drawText(self.rect().adjusted(0, 38, 0, 0), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, self._used)
        painter.setPen(QColor("#667085"))
        painter.setFont(QFont(".AppleSystemUIFont", 11))
        painter.drawText(self.rect().adjusted(0, 72, 0, 0), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, f"/ {self._total}")


@dataclass(slots=True)
class CompactData:
    usable: bool = False
    state_text: str = "正在检测"
    carrier: str = "--"
    network: str = "--"
    signal_percent: int = 0
    quota_configured: bool = False
    used_text: str = "--"
    remaining_text: str = "--"
    quota_percent: int = 0
    quota_state: str = "请设置套餐"
    balance_text: str = "未设置"
    balance_state: str = ""
    down_speed: str = "0 B/s"
    up_speed: str = "0 B/s"


class CompactPanel(QDialog):
    open_full = Signal()
    open_sms = Signal()
    open_settings = Signal()
    pin_requested = Signal()
    unpin_requested = Signal()
    speed_test_requested = Signal()

    def __init__(self, mode: str, icon: QIcon, parent=None):
        super().__init__(parent)
        self.mode = mode
        self.setWindowTitle("4G Dongle Manager")
        self.setWindowIcon(icon)
        if mode == "popover":
            self.setWindowFlags(Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
            self.setFixedWidth(430)
        else:
            self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint)
            self.setFixedSize(820, 300)
        self._build(icon)
        self._style()

    @staticmethod
    def _button(text: str, icon=None) -> QPushButton:
        button = QPushButton(text)
        if icon is not None:
            button.setIcon(icon)
            button.setIconSize(QSize(16, 16))
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        return button

    @staticmethod
    def _divider(vertical: bool = False) -> QFrame:
        divider = QFrame()
        divider.setObjectName("divider")
        divider.setFrameShape(QFrame.Shape.VLine if vertical else QFrame.Shape.HLine)
        divider.setFixedWidth(1) if vertical else divider.setFixedHeight(1)
        return divider

    def _status_pixmap(self, kind: QStyle.StandardPixmap, color: str):
        pixmap = self.style().standardIcon(kind).pixmap(24, 24)
        painter = QPainter(pixmap)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
        painter.fillRect(pixmap.rect(), QColor(color))
        painter.end()
        return pixmap

    def _build(self, icon: QIcon):
        if self.mode == "mini":
            self._build_mini(icon)
        else:
            self._build_popover(icon)

    def _state_block(self, icon: QIcon, large_icon: bool = False) -> QWidget:
        box = QWidget()
        layout = QHBoxLayout(box) if large_icon else QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(15 if large_icon else 6)
        if large_icon:
            icon_frame = QFrame()
            icon_frame.setObjectName("iconWell")
            icon_frame.setFixedSize(96, 96)
            icon_layout = QVBoxLayout(icon_frame)
            icon_label = QLabel()
            icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            icon_label.setPixmap(icon.pixmap(72, 72))
            icon_layout.addWidget(icon_label)
            layout.addWidget(icon_frame)
        labels = QWidget()
        labels_layout = QVBoxLayout(labels)
        labels_layout.setContentsMargins(0, 0, 0, 0)
        labels_layout.setSpacing(7)
        self.state_label = QLabel("正在检测")
        self.state_label.setObjectName("state")
        self.state_label.setWordWrap(False)
        self.connection_detail = QLabel("等待模块…")
        self.connection_detail.setObjectName("secondary")
        labels_layout.addStretch()
        state_row = QHBoxLayout()
        state_row.setSpacing(8)
        state_row.addWidget(self.state_label)
        self.state_icon = QLabel()
        self.state_icon.setPixmap(self._status_pixmap(QStyle.StandardPixmap.SP_DialogApplyButton, "#12B76A"))
        state_row.addWidget(self.state_icon)
        state_row.addStretch()
        labels_layout.addLayout(state_row)
        labels_layout.addWidget(self.connection_detail)
        labels_layout.addStretch()
        layout.addWidget(labels, 1)
        return box

    def _quota_block(self) -> QWidget:
        quota_box = QWidget()
        quota_layout = QVBoxLayout(quota_box)
        quota_layout.setContentsMargins(0, 0, 0, 0)
        quota_layout.setSpacing(8)
        quota_row = QHBoxLayout()
        self.quota_used = QLabel("套餐流量未设置")
        self.quota_used.setObjectName("quotaUsed")
        self.quota_remaining = QLabel("")
        self.quota_remaining.setObjectName("secondary")
        quota_row.addWidget(self.quota_used)
        quota_row.addStretch()
        quota_row.addWidget(self.quota_remaining)
        quota_layout.addLayout(quota_row)
        self.quota_bar = QProgressBar()
        self.quota_bar.setRange(0, 100)
        self.quota_bar.setTextVisible(False)
        quota_layout.addWidget(self.quota_bar)
        self.quota_state = QLabel("请在设置中填写套餐")
        self.quota_state.setObjectName("quotaState")
        quota_layout.addWidget(self.quota_state)
        return quota_box

    def _speed_widgets(self) -> QHBoxLayout:
        speed_row = QHBoxLayout()
        speed_row.setSpacing(24)
        self.down_label = QLabel("↓ 0 B/s")
        self.down_label.setObjectName("speed")
        self.up_label = QLabel("↑ 0 B/s")
        self.up_label.setObjectName("speed")
        speed_row.addWidget(self.down_label)
        speed_row.addWidget(self.up_label)
        return speed_row

    def _build_mini(self, icon: QIcon):
        root = QVBoxLayout(self)
        root.setContentsMargins(26, 13, 26, 18)
        root.setSpacing(12)

        header = QHBoxLayout()
        header.addStretch()
        app_name = QLabel("4G Dongle Manager")
        app_name.setObjectName("appName")
        header.addWidget(app_name)
        header.addStretch()
        unpin = self._button("回到菜单栏", qta.icon("fa6s.thumbtack", color="#344054"))
        unpin.clicked.connect(self.unpin_requested)
        header.addWidget(unpin)
        root.addLayout(header)
        root.addWidget(self._divider())

        content = QHBoxLayout()
        content.setSpacing(24)
        content.addWidget(self._state_block(icon, large_icon=True), 11)
        content.addWidget(self._divider(vertical=True))
        content.addWidget(self._quota_block(), 9)
        root.addLayout(content, 1)
        root.addWidget(self._divider())

        actions = self._speed_widgets()
        actions.addWidget(self._divider(vertical=True))
        actions.addStretch(1)
        sms = self._button("短信", qta.icon("fa6s.comment-dots", color="#344054"))
        sms.clicked.connect(self.open_sms)
        actions.addWidget(sms)
        full = self._button("展开详情", qta.icon("fa6s.up-right-and-down-left-from-center", color="#344054"))
        full.setObjectName("primary")
        full.clicked.connect(self.open_full)
        actions.addWidget(full)
        root.addLayout(actions)

    def _build_popover(self, icon: QIcon):
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 18, 24, 18)
        root.setSpacing(14)
        header = QHBoxLayout()
        app_icon = QLabel()
        app_icon.setPixmap(icon.pixmap(36, 36))
        header.addWidget(app_icon)
        app_name = QLabel("4G Dongle Manager")
        app_name.setObjectName("appName")
        header.addWidget(app_name)
        header.addStretch()
        settings = self._button("设置", qta.icon("fa6s.gear", color="#344054"))
        settings.setObjectName("headerAction")
        settings.clicked.connect(self.open_settings)
        header.addWidget(settings)
        root.addLayout(header)
        root.addWidget(self._divider())
        root.addWidget(self._state_block(icon, large_icon=False))
        root.addWidget(self._divider())
        quota_row = QHBoxLayout()
        quota_row.setSpacing(18)
        self.quota_bar = CircularProgress()
        quota_row.addWidget(self.quota_bar)
        quota_details = QWidget()
        quota_details_layout = QVBoxLayout(quota_details)
        quota_details_layout.setContentsMargins(0, 12, 0, 12)
        quota_details_layout.setSpacing(8)
        self.quota_used = QLabel("套餐流量未设置")
        self.quota_used.setObjectName("quotaUsed")
        self.quota_remaining = QLabel("")
        self.quota_remaining.setObjectName("secondary")
        self.quota_state = QLabel("请在设置中填写套餐")
        self.quota_state.setObjectName("quotaState")
        quota_details_layout.addWidget(self.quota_used)
        quota_details_layout.addWidget(self.quota_remaining)
        quota_details_layout.addWidget(self.quota_state)
        quota_details_layout.addStretch()
        quota_row.addWidget(quota_details, 1)
        root.addLayout(quota_row)

        balance_row = QHBoxLayout()
        balance_texts = QVBoxLayout()
        balance_texts.setSpacing(3)
        balance_title = QLabel("套餐余额")
        balance_title.setObjectName("secondary")
        self.balance_label = QLabel("未设置")
        self.balance_label.setObjectName("balance")
        balance_texts.addWidget(balance_title)
        balance_texts.addWidget(self.balance_label)
        balance_row.addLayout(balance_texts)
        balance_row.addStretch()
        self.balance_state_label = QLabel("")
        self.balance_state_label.setObjectName("positiveBadge")
        balance_row.addWidget(self.balance_state_label)
        root.addLayout(balance_row)
        root.addWidget(self._divider())

        speed_row = self._speed_widgets()
        live_label = QLabel("实时")
        live_label.setObjectName("secondary")
        speed_row.insertWidget(0, live_label)
        speed_row.addStretch()
        root.addLayout(speed_row)

        actions = QHBoxLayout()
        sms = self._button("短信", qta.icon("fa6s.comment-dots", color="#344054"))
        sms.setObjectName("flatAction")
        sms.clicked.connect(self.open_sms)
        actions.addWidget(sms)
        speed_test_bottom = self._button("测速", qta.icon("fa6s.gauge-high", color="#344054"))
        speed_test_bottom.setObjectName("flatAction")
        speed_test_bottom.clicked.connect(self.speed_test_requested)
        actions.addWidget(speed_test_bottom)
        full = self._button("展开完整界面", qta.icon("fa6s.up-right-from-square", color="#344054"))
        full.setObjectName("flatAction")
        full.clicked.connect(self.open_full)
        actions.addWidget(full)
        root.addLayout(actions)
        pin = self._button("固定为小窗", qta.icon("fa6s.thumbtack", color="#344054"))
        pin.clicked.connect(self.pin_requested)
        root.addWidget(pin)
        compatibility = QLabel("兼容 DJI 第一代 4G 模块")
        compatibility.setObjectName("compatibility")
        compatibility.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(compatibility)

    def update_data(self, data: CompactData):
        self.state_label.setProperty("i18n_text", data.state_text)
        self.state_label.setText(data.state_text)
        state_color = "#079455" if data.usable else "#D92D20"
        if "等待" in data.state_text or "SIM" in data.state_text:
            state_color = "#B54708"
        self.state_label.setStyleSheet(f"color: {state_color};")
        icon_kind = QStyle.StandardPixmap.SP_DialogApplyButton if data.usable else QStyle.StandardPixmap.SP_MessageBoxCritical
        if "等待" in data.state_text or "SIM" in data.state_text:
            icon_kind = QStyle.StandardPixmap.SP_MessageBoxWarning
        icon_color = "#12B76A" if data.usable else "#F04438"
        if "等待" in data.state_text or "SIM" in data.state_text:
            icon_color = "#F79009"
        self.state_icon.setPixmap(self._status_pixmap(icon_kind, icon_color))
        connection_text = f"{data.carrier} · {data.network} · 信号 {data.signal_percent}%" if data.usable else data.carrier
        self.connection_detail.setProperty("i18n_text", connection_text)
        self.connection_detail.setText(connection_text)
        self.quota_bar.setValue(max(0, min(100, data.quota_percent)))
        quota_used = data.used_text if data.quota_configured else "套餐流量未设置"
        quota_remaining = data.remaining_text if data.quota_configured else ""
        self.quota_used.setProperty("i18n_text", quota_used)
        self.quota_remaining.setProperty("i18n_text", quota_remaining)
        self.quota_used.setText(quota_used)
        if isinstance(self.quota_bar, CircularProgress):
            self.quota_bar.setUsageText(quota_used)
        self.quota_remaining.setText(quota_remaining)
        self.quota_state.setProperty("i18n_text", data.quota_state)
        self.quota_state.setText(data.quota_state)
        quota_color = "#079455"
        if "提醒" in data.quota_state or "临近" in data.quota_state:
            quota_color = "#B54708"
        if "超量" in data.quota_state and "未超量" not in data.quota_state:
            quota_color = "#D92D20"
        self.quota_state.setStyleSheet(f"color: {quota_color};")
        if hasattr(self, "balance_label"):
            self.balance_label.setProperty("i18n_text", data.balance_text)
            self.balance_label.setText(data.balance_text)
            self.balance_state_label.setProperty("i18n_text", data.balance_state)
            self.balance_state_label.setText(data.balance_state)
        down_text = f"↓ {data.down_speed}"
        up_text = f"↑ {data.up_speed}"
        self.down_label.setProperty("i18n_text", down_text)
        self.up_label.setProperty("i18n_text", up_text)
        self.down_label.setText(down_text)
        self.up_label.setText(up_text)

    def closeEvent(self, event: QCloseEvent):
        if self.mode == "mini":
            event.ignore()
            self.hide()
            self.unpin_requested.emit()
        else:
            super().closeEvent(event)

    def _style(self):
        self.setStyleSheet(
            """
            QDialog { background: #FBFCFE; color: #101828; }
            QLabel { font-size: 14px; }
            QLabel#appName { color: #101828; font-size: 16px; font-weight: 650; }
            QLabel#state { font-size: 31px; font-weight: 720; }
            QLabel#secondary { color: #667085; font-size: 14px; }
            QLabel#quotaUsed { color: #101828; font-size: 15px; font-weight: 620; }
            QLabel#quotaState, QLabel#speed { font-size: 16px; font-weight: 620; color: #079455; }
            QLabel#balance { font-size: 17px; font-weight: 650; }
            QLabel#balance { color: #101828; }
            QLabel#compatibility { color: #98A2B3; font-size: 12px; }
            QFrame#divider { background: #E4E7EC; border: none; }
            QLabel#positiveBadge { color: #067647; background: #ECFDF3; border: 1px solid #ABEFC6; border-radius: 10px; padding: 4px 9px; font-size: 12px; font-weight: 650; }
            QFrame#iconWell { background: #F0F9F4; border: 1px solid #D1FADF; border-radius: 48px; }
            QProgressBar { height: 8px; background: #EAECF0; border: none; border-radius: 4px; }
            QProgressBar::chunk { background: #12B76A; border-radius: 4px; }
            QPushButton { color: #344054; min-height: 28px; padding: 6px 11px; border: 1px solid #D0D5DD; border-radius: 8px; background: white; }
            QPushButton:hover { background: #F2F4F7; }
            QPushButton#primary { background: white; color: #344054; border: 1px solid #D0D5DD; }
            QPushButton#flatAction { background: transparent; border: none; padding: 10px 8px; }
            QPushButton#flatAction:hover { background: #F2F4F7; }
            QPushButton#headerAction { min-height: 24px; padding: 4px 7px; border: none; background: transparent; }
            QPushButton#headerAction:hover { background: #F2F4F7; }
            """
        )
