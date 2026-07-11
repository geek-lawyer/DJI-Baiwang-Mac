from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWizard,
    QWizardPage,
)

from .documents import DISCLAIMER_TEXT, PRIVACY_TEXT, TERMS_TEXT, TERMS_VERSION


class OnboardingWizard(QWizard):
    def __init__(self, settings: QSettings, show_document, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.show_document = show_document
        self.setWindowTitle("欢迎使用 4G Dongle Manager")
        self.resize(720, 520)
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)
        self.setButtonText(QWizard.WizardButton.BackButton, "上一步")
        self.setButtonText(QWizard.WizardButton.NextButton, "下一步")
        self.setButtonText(QWizard.WizardButton.FinishButton, "同意并开始使用")
        self.setButtonText(QWizard.WizardButton.CancelButton, "稍后再说")
        self.setStyleSheet(
            """
            QWizard { background: #FBFCFE; color: #172033; }
            QWizardPage QLabel { font-size: 14px; line-height: 1.4; }
            QPushButton { color: #344054; min-height: 28px; padding: 6px 14px; border: 1px solid #D0D5DD; border-radius: 8px; background: white; }
            QPushButton:hover { background: #F2F4F7; }
            """
        )
        self._welcome_page()
        self._connection_page()
        self._plan_page()
        self._alerts_page()
        self._agreement_page()

    @staticmethod
    def _page(title: str, subtitle: str) -> tuple[QWizardPage, QVBoxLayout]:
        page = QWizardPage()
        page.setTitle(title)
        page.setSubTitle(subtitle)
        layout = QVBoxLayout(page)
        layout.setSpacing(14)
        return page, layout

    def _welcome_page(self):
        page, layout = self._page("先看懂，再开始", "这是独立开发的第三方兼容工具，不是 DJI 或运营商官方软件。")
        text = QLabel(
            "应用会帮助你确认模块能否上网、收发短信、查看信号，并在套餐流量或余额临近阈值时提醒。\n\n"
            "普通用户可以只看菜单栏小窗；需要时再展开完整网络详情。"
        )
        text.setWordWrap(True)
        layout.addWidget(text)
        layout.addStretch()
        self.addPage(page)

    def _connection_page(self):
        page, layout = self._page("连接模块", "插入兼容 4G 模块，并在 macOS 提示时允许 USB 配件接入。")
        text = QLabel(
            "首次初始化会写入模块的 USB 网络和运营商配置，并可能重启模块。完成后配置会保存在模块中。\n\n"
            "初始化成功后，整个 USB 模块支持热插拔；接到兼容 ECM 网络的 Mac、Linux 或部分 Windows 设备，可不安装本软件直接上网。\n\n"
            "警告：其他设备不会获得本软件的套餐流量、余额、温度或断线提醒，也不能使用本软件界面收发短信；跨设备流量不会自动计入这台 Mac。"
        )
        text.setWordWrap(True)
        layout.addWidget(text)
        layout.addStretch()
        self.addPage(page)

    def _plan_page(self):
        page, layout = self._page("套餐与余额", "这些数据无法从所有 SIM 通用读取，请按运营商套餐填写；以后可在设置中修改。")
        self.quota = QDoubleSpinBox()
        self.quota.setRange(0, 100000)
        self.quota.setDecimals(2)
        self.quota.setSuffix(" GB / 周期")
        self.quota.setValue(float(self.settings.value("quota_gb", 0)))
        self.reset_day = QSpinBox()
        self.reset_day.setRange(1, 28)
        self.reset_day.setPrefix("每月 ")
        self.reset_day.setSuffix(" 日重置")
        self.reset_day.setValue(int(self.settings.value("cycle_reset_day", 1)))
        self.balance = QDoubleSpinBox()
        self.balance.setRange(-100000, 100000)
        self.balance.setDecimals(2)
        self.balance.setPrefix("¥ ")
        self.balance.setValue(float(self.settings.value("plan_balance", 0)))
        layout.addWidget(QLabel("套餐总流量"))
        layout.addWidget(self.quota)
        layout.addWidget(QLabel("计费周期"))
        layout.addWidget(self.reset_day)
        layout.addWidget(QLabel("当前套餐余额（用户填写）"))
        layout.addWidget(self.balance)
        layout.addStretch()
        self.addPage(page)

    def _alerts_page(self):
        page, layout = self._page("提醒事项", "提醒只在本软件运行时可用。")
        self.traffic_alert = QCheckBox("剩余流量临近阈值时提醒")
        self.traffic_alert.setChecked(self.settings.value("traffic_alert", True, bool))
        self.balance_alert = QCheckBox("套餐余额临近阈值时提醒")
        self.balance_alert.setChecked(self.settings.value("balance_alert", True, bool))
        self.disconnect_alert = QCheckBox("模块断开或 SIM 异常时提醒")
        self.disconnect_alert.setChecked(self.settings.value("disconnect_alert", True, bool))
        self.temperature_alert = QCheckBox("模块温度过高时提醒")
        self.temperature_alert.setChecked(self.settings.value("temperature_alert", True, bool))
        self.ip_lookup = QCheckBox("允许查询公网出口国家/地区（会访问第三方 IP 数据库）")
        self.ip_lookup.setChecked(self.settings.value("allow_ip_lookup", False, bool))
        for widget in (self.traffic_alert, self.balance_alert, self.disconnect_alert, self.temperature_alert, self.ip_lookup):
            layout.addWidget(widget)
        layout.addStretch()
        self.addPage(page)

    def _agreement_page(self):
        page, layout = self._page("阅读并确认", "请分别查看条款。勾选框默认不选。")
        for title, text in (("用户协议", TERMS_TEXT), ("隐私说明", PRIVACY_TEXT), ("免责声明", DISCLAIMER_TEXT)):
            button = QPushButton(f"查看《{title}》")
            button.clicked.connect(lambda _checked=False, t=title, body=text: self.show_document(t, body))
            layout.addWidget(button)
        self.agree = QCheckBox("我已阅读并同意《用户协议》《隐私说明》《免责声明》")
        page.registerField("agreements*", self.agree)
        layout.addWidget(self.agree)
        layout.addStretch()
        self.addPage(page)

    def accept(self):
        self.settings.setValue("quota_gb", self.quota.value())
        self.settings.setValue("cycle_reset_day", self.reset_day.value())
        self.settings.setValue("plan_balance", self.balance.value())
        self.settings.setValue("balance_configured", True)
        self.settings.setValue("traffic_alert", self.traffic_alert.isChecked())
        self.settings.setValue("balance_alert", self.balance_alert.isChecked())
        self.settings.setValue("disconnect_alert", self.disconnect_alert.isChecked())
        self.settings.setValue("temperature_alert", self.temperature_alert.isChecked())
        self.settings.setValue("allow_ip_lookup", self.ip_lookup.isChecked())
        self.settings.setValue("onboarding_complete", True)
        self.settings.setValue("terms_version", TERMS_VERSION)
        self.settings.setValue("terms_accepted_at", datetime.now().isoformat(timespec="seconds"))
        self.settings.sync()
        super().accept()
