from __future__ import annotations

import re

from opencc import OpenCC
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QGroupBox,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QTableWidget,
    QWidget,
)

from .documents import (
    DISCLAIMER_TEXT,
    DISCLAIMER_TEXT_EN,
    HELP_TEXT,
    HELP_TEXT_EN,
    PRIVACY_TEXT,
    PRIVACY_TEXT_EN,
    TERMS_TEXT,
    TERMS_TEXT_EN,
    TIPS_TEXT,
    TIPS_TEXT_EN,
)


_S2T = OpenCC("s2t")

# These are application-owned interface strings. Unknown technical responses
# stay unchanged instead of being sent to an online translation service.
ENGLISH: dict[str, str] = {
    "4G 模块 · 上网、短信与连接管理": "4G module · internet, messaging, and connection management",
    "兼容 DJI 第一代 4G 模块 · 独立第三方工具": "Compatible with DJI first-generation 4G module · Independent third-party tool",
    "兼容 DJI 第一代 4G 模块": "Compatible with DJI first-generation 4G module",
    "中国电信": "China Telecom",
    "中国移动": "China Mobile",
    "中国联通": "China Unicom",
    "概览": "Overview",
    "短信中心": "Messages",
    "通讯录": "Contacts",
    "设置": "Settings",
    "连接与蜂窝网络": "Connectivity & Cellular",
    "Mac 上网策略": "Mac Internet Route",
    "通常保持自动。仅 LTE 不会增强射频信号，切换时可能短暂断网。": "Keep this on Auto in most cases. LTE-only does not boost radio signal and switching may briefly disconnect the network.",
    "收件与发送": "Inbox & Send",
    "发送记录": "Sent History",
    "收件箱": "Inbox",
    "刷新短信": "Refresh Messages",
    "监听新短信": "Watch for New Messages",
    "删除选中": "Delete Selected",
    "查看全文": "View Full Message",
    "复制内容": "Copy Content",
    "收件号码": "Recipient",
    "短信内容": "Message",
    "发送短信": "Send Message",
    "姓名": "Name",
    "电话": "Phone",
    "导入 CSV / vCard": "Import CSV / vCard",
    "用于发送短信": "Use for Message",
    "后台与通知": "Background & Notifications",
    "登录 Mac 后自动启动并驻留菜单栏": "Launch at login and stay in the menu bar",
    "收到新短信时播放提示音": "Play a sound for new messages",
    "套餐、余额与显示": "Plan, Balance & Display",
    "套餐总流量": "Plan Data Allowance",
    "周期重置日": "Billing Reset Day",
    "当前余额（用户填写）": "Current Balance (entered by user)",
    "剩余流量提醒阈值": "Remaining Data Alert Threshold",
    "余额提醒阈值": "Balance Alert Threshold",
    "网速单位": "Speed Units",
    "公网地区": "Public IP Region",
    "保存套餐与显示设置": "Save Plan & Display Settings",
    "提醒事项": "Alerts",
    "剩余流量临近阈值或已经超量": "Remaining data is low or over the limit",
    "套餐余额临近阈值": "Plan balance is low",
    "模块断开、SIM 缺失或入网失败": "Module disconnected, SIM missing, or network registration failed",
    "模块温度过高": "Module temperature is high",
    "语言与地区": "Language & Region",
    "界面语言": "Interface Language",
    "国家/地区格式": "Regional Format",
    "界面语言只列出已完成翻译的语言；国家/地区格式负责日期、数字、货币和单位显示。": "Only completed interface translations are listed; the regional format controls dates, numbers, currency, and units.",
    "语言与地区设置已保存": "Language and region settings saved",
    "使用小贴士、帮助与说明": "Tips, Help & Guides",
    "使用小贴士": "Tips",
    "软件帮助": "Help",
    "重新运行首次引导": "Run Setup Guide Again",
    "隐私、条款与免责声明": "Privacy, Terms & Disclaimer",
    "用户协议": "Terms of Use",
    "隐私说明": "Privacy Notice",
    "免责声明": "Disclaimer",
    "关于": "About",
    "SIM 运营商": "SIM Carrier",
    "网络信息": "Network Information",
    "运营商": "Carrier",
    "网络类型": "Network Type",
    "模块分配 IP": "Module-assigned IP",
    "运营商内网": "Carrier Private Network",
    "公网出口 IP（地区为推断）": "Public Exit IP (region inferred)",
    "由系统自动分配": "Assigned automatically",
    "基站信息": "Cell Site Information",
    "SIM 状态": "SIM Status",
    "正常": "Normal",
    "本机时间": "Local Time",
    "模块温度": "Module Temperature",
    "当前移动网络": "Mobile Network",
    "4G 使用频段": "4G Band",
    "模块网络地址": "Module Network Address",
    "短信服务": "Messaging Service",
    "内部最高温度": "Highest Internal Temperature",
    "Mac 当前上网出口": "Current Mac Internet Route",
    "公网出口 IP（地区为推断）": "Public Exit IP (region inferred)",
    "USB 供电额度（非实时功耗）": "USB Power Allocation (not live usage)",
    "信号": "Signal",
    "信号强度": "Signal Strength",
    "刷新": "Refresh",
    "流量、网速与延迟": "Data, Speed & Latency",
    "手动测速（会消耗流量）": "Run Speed Test (uses data)",
    "首次使用与模块初始化": "First Use & Module Setup",
    "重新检测": "Check Again",
    "开始初始化": "Initialize",
    "Mac 网络切换": "Mac Network Switching",
    "连接策略": "Connection Policy",
    "切换网络": "Switch Network",
    "4G 网络制式": "4G Network Mode",
    "保存模式": "Save Mode",
    "模块已连接": "Module Connected",
    "模块未连接": "Module Disconnected",
    "未检测到 SIM 卡": "SIM Card Not Detected",
    "正在连接移动网络": "Connecting to Mobile Network",
    "可以正常使用": "Ready to Use",
    "Mac 尚未使用 4G 网络": "Mac Is Not Using 4G",
    "请插入兼容 4G 模块": "Insert a compatible 4G module",
    "请检查 SIM 卡": "Check the SIM card",
    "套餐流量未设置": "Data plan not configured",
    "请设置套餐": "Configure your plan",
    "未超量": "Within Limit",
    "临近流量上限": "Data Almost Used Up",
    "已经超量": "Over Data Limit",
    "套餐余额": "Plan Balance",
    "余额偏低": "Low Balance",
    "充足": "Sufficient",
    "短信": "Messages",
    "测速": "Speed Test",
    "展开详情": "Show Details",
    "展开完整界面": "Open Full App",
    "固定为小窗": "Pin Mini Window",
    "回到菜单栏": "Return to Menu Bar",
    "打开完整界面": "Open Full App",
    "固定状态小窗": "Pin Status Window",
    "刷新状态": "Refresh Status",
    "退出": "Quit",
    "正在检测": "Checking",
    "等待模块…": "Waiting for module…",
    "等待模块接入；插入后自动检测初始化状态。": "Waiting for the module; setup status will be checked automatically after connection.",
    "正在检测模块配置…": "Checking module configuration…",
    "需要初始化": "Setup Required",
    "可以收发短信": "Messaging Available",
    "固件未返回": "Not Reported by Firmware",
    "未启用地区查询": "Region Lookup Disabled",
    "正在检测": "Checking",
    "等待连接移动网络": "Waiting for Mobile Network",
    "AT 端口等待中": "Waiting for AT Port",
    "很强": "Excellent",
    "良好": "Good",
    "一般": "Fair",
    "较弱": "Weak",
    "本次连接": "Current Session",
    "本次流量": "Session Data",
    "本周期流量": "Billing Cycle Data",
    "本周期已用": "Billing Cycle Used",
    "已用": "Used",
    "剩余": "Remaining",
    "本机统计": "Counted on This Mac",
    "实时": "Live",
    "实时网速": "Live Speed",
    "当前平均": "Current Average",
    "延迟": "Latency",
    "检测失败": "Check Failed",
    "请在设置中填写套餐": "Configure the data plan in Settings",
    "套餐未设置": "Plan not configured",
    "流量提醒": "Data Alert",
    "余额提醒": "Balance Alert",
    "已开启": "Enabled",
    "USB 供电分配": "USB Power Allocation",
    "非实时功耗": "Not live power usage",
    "字节/秒（MB/s、KB/s、B/s）": "Bytes/sec (MB/s, KB/s, B/s)",
    "比特/秒（Mbps、Kbps、bps）": "Bits/sec (Mbps, Kbps, bps)",
    "查询公网出口国家/地区（访问第三方 IP 数据库）": "Look up public exit country/region (uses a third-party IP database)",
    "跟随 macOS 系统设置": "Follow macOS Settings",
    "简体中文": "简体中文",
    "繁體中文": "繁體中文",
    "English": "English",
    "欢迎使用 4G Dongle Manager": "Welcome to 4G Dongle Manager",
    "先看懂，再开始": "Understand It Before You Start",
    "连接模块": "Connect the Module",
    "套餐与余额": "Plan & Balance",
    "阅读并确认": "Read and Confirm",
    "上一步": "Back",
    "下一步": "Next",
    "同意并开始使用": "Agree & Start",
    "稍后再说": "Not Now",
    "关闭": "Close",
}
ENGLISH.update(
    {
        TERMS_TEXT: TERMS_TEXT_EN,
        PRIVACY_TEXT: PRIVACY_TEXT_EN,
        DISCLAIMER_TEXT: DISCLAIMER_TEXT_EN,
        TIPS_TEXT: TIPS_TEXT_EN,
        HELP_TEXT: HELP_TEXT_EN,
    }
)


def translate(text: str, language: str) -> str:
    if not text or language == "zh_CN":
        return text
    if language == "zh_TW":
        return _S2T.convert(text)
    if language != "en_US":
        return text
    translated = text
    for source, target in sorted(ENGLISH.items(), key=lambda item: len(item[0]), reverse=True):
        translated = translated.replace(source, target)
    return translated


def _canonical(obj, key: str, current: str) -> str:
    source = obj.property(key)
    if source is None or re.search(r"[\u3400-\u9fff]", current):
        source = current
        obj.setProperty(key, source)
    return str(source)


def apply_widget_language(root: QWidget, language: str):
    widgets = [root, *root.findChildren(QWidget)]
    for widget in widgets:
        if widget.property("i18n_skip"):
            continue
        if isinstance(widget, (QLabel, QPushButton, QCheckBox)):
            source = _canonical(widget, "i18n_text", widget.text())
            widget.setText(translate(source, language))
        if isinstance(widget, QGroupBox):
            source = _canonical(widget, "i18n_title", widget.title())
            widget.setTitle(translate(source, language))
        if isinstance(widget, (QLineEdit, QPlainTextEdit)):
            placeholder = widget.placeholderText()
            if placeholder:
                source = _canonical(widget, "i18n_placeholder", placeholder)
                widget.setPlaceholderText(translate(source, language))
        if isinstance(widget, QTabWidget):
            for index in range(widget.count()):
                page = widget.widget(index)
                source = page.property("i18n_tab")
                current = widget.tabText(index)
                if source is None or re.search(r"[\u3400-\u9fff]", current):
                    source = current
                    page.setProperty("i18n_tab", source)
                widget.setTabText(index, translate(str(source), language))
        if isinstance(widget, QComboBox):
            for index in range(widget.count()):
                source = widget.itemData(index, Qt.ItemDataRole.UserRole + 10)
                current = widget.itemText(index)
                if source is None or re.search(r"[\u3400-\u9fff]", current):
                    source = current
                    widget.setItemData(index, source, Qt.ItemDataRole.UserRole + 10)
                widget.setItemText(index, translate(str(source), language))
        if isinstance(widget, QTableWidget):
            for index in range(widget.columnCount()):
                item = widget.horizontalHeaderItem(index)
                if item:
                    source = item.data(Qt.ItemDataRole.UserRole + 10) or item.text()
                    item.setData(Qt.ItemDataRole.UserRole + 10, source)
                    item.setText(translate(str(source), language))
    for action in root.findChildren(QAction):
        source = _canonical(action, "i18n_text", action.text())
        action.setText(translate(source, language))
    if isinstance(root, (QDialog, QMainWindow)):
        source = _canonical(root, "i18n_window_title", root.windowTitle())
        root.setWindowTitle(translate(source, language))
