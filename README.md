# 4G Dongle Manager for macOS

**大疆一代 4G 增强图传模块的 macOS 桌面管理工具：自动初始化、4G 上网、短信收发、信号与温度监控、Wi-Fi/4G 切换。**

一款面向 DJI 第一代 4G 增强图传模块（Baiwang，VID `0x2ca3` / PID `0x4006`）的 macOS 桌面应用。

> 当前为早期版本。修改网络服务顺序或蜂窝制式前请理解其影响；应用不会也不能放大模块的射频发射功率。

## 功能

- 菜单栏常驻，自动检测 USB 插拔
- 首次使用向导：检测原始模式、确认后切换 CDC-ECM 并匹配运营商配置
- 显示运营商、LTE 制式、频段、信号百分比、CSQ/dBm、IMS 和蜂窝 IP
- 显示模块内部温度，并在高温时提醒
- 菜单栏弹窗与可固定状态小窗，优先显示“是否可用、流量是否超限、余额是否充足”
- 显示本次运行时间、本次与周期流量、剩余流量、余额及阈值提醒
- 实时/平均上下行网速、自动单位切换、延迟和手动测速
- 显示模块内网 IP、公网出口 IP 与推断地区（公网地区查询默认关闭）
- 显示 USB 供电额度；该数值不是模块实时功耗
- 中文/英文短信发送、收件箱、删除和新短信通知音
- 本机持久化发送历史，显示发送时间、提交成功/失败、参考编号和完整内容
- Wi-Fi、DJI 4G 和自动回退三种 Mac 网络策略
- 自动模式下让 Baiwang 服务优先，Wi-Fi 作为备用
- 导入 CSV 或 vCard 通讯录
- 登录 Mac 后自动启动，关闭窗口后继续在后台监听
- 简体中文、繁體中文、English 界面语言，以及独立的国家/地区格式选择
- 首次引导、使用小贴士、软件帮助、隐私说明、用户协议与免责声明
- 所有短信和通讯录均在本机处理，不上传云端

## 重要限制

- **不能调大信号。** 信号由天线、位置、遮挡和运营商基站决定。应用只显示信号，并可选择自动网络或仅 LTE。
- 初始化不会静默执行。应用发现未配置模块后会展示将要修改的内容，只有用户确认才写入并重启模块。
- USB 插入时“自动启动”的实现方式是登录代理：应用登录后常驻菜单栏，检测模块插入。模块本身无法唤醒一台完全没有后台代理的 Mac 应用。
- 网络切换依赖 macOS `networksetup`。某些系统配置可能要求管理员授权。
- SIM 必须开通短信业务。中国电信 LTE 短信通常需要正确的运营商 MBN、IMS 和分组域短信设置。

## 安装开发环境

```bash
brew install python@3.12 libusb
python3.12 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
```

开发运行：

```bash
./scripts/run_dev.sh
```

## 构建 `.app`

```bash
./scripts/build_macos.sh
open "dist/4G Dongle Manager.app"
```

PyInstaller 会把 Python、Qt、PyUSB 和 `libusb` 打包进应用。[PyInstaller 官方文档](https://pyinstaller.org/en/stable/)说明其 macOS 应用打包能力。

## 通讯录格式

CSV 示例（使用虚构号码）：

```csv
name,phone
测试联系人,+8613800000000
```

也支持 `.vcf` / `.vcard` 文件。

## 工作原理

```text
DJI Baiwang USB
├── CDC-ECM 网卡接口 → macOS Baiwang/en6 → 4G 上网
└── Vendor Bulk AT 接口 → PyUSB/libusb → 信号、网络状态、短信
```

短信采用 UCS2 编码，并设置 DCS `8`，确保中文正文在手机上正确显示。应用通过 AT 指令读取状态和短信；网络切换通过 macOS 系统网络服务完成。

## 隐私与安全

- 不记录或提交真实测试电话号码。
- 发送前必须由用户在界面中二次确认。
- 自动监听只读取模块内短信，不会自动回复。
- 通讯录保存在 `~/Library/Application Support/Baiwang Connect/contacts.json`。

## 致谢

CDC-ECM 切换思路参考了 [tinydream96/DJI-4G-Dongle-macOS-Config](https://github.com/tinydream96/DJI-4G-Dongle-macOS-Config)。本项目为独立实现，不隶属于 DJI 或 Quectel。

## License

[MIT](LICENSE). Copyright © 2026 geek-lawyer.
