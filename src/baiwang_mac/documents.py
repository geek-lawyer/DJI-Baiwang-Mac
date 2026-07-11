TERMS_VERSION = "2026-07-11-v1"

TERMS_TEXT = """用户协议（简要版）

1. 本软件是独立开发的第三方工具，与 DJI、大疆创新、运营商或 SIM 卡发行方不存在隶属、授权或代言关系。
2. 软件用于管理用户自行拥有并有权操作的兼容 4G 模块。用户应遵守所在地法律、运营商协议和资费规则。
3. 短信和移动数据可能由运营商收费。执行发送、测速、网络切换和模块初始化前，请确认资费与设备状态。
4. 套餐、余额和流量阈值由用户填写或由本机统计，不能替代运营商账单。
5. 用户可以停止使用并删除本机保存的数据。完整条款以后续正式发布版本为准。
"""

PRIVACY_TEXT = """隐私说明

短信、通讯录、发送记录、套餐设置和本机流量统计默认只保存在这台 Mac。

如果用户启用“查询公网出口地区”，软件会将当前公网 IP 发送给第三方 IP 地理数据库，用来推断国家或地区。该结果不是 GPS 定位，可能不准确。关闭该功能后不会执行此查询。

手动测速会连接 Apple 的网络质量测试服务并消耗移动流量。软件不会把短信正文或通讯录上传到开发者服务器。
"""

DISCLAIMER_TEXT = """免责声明

1. 本软件显示的信号、温度、IP、流量、余额、延迟、网速和功耗信息可能来自模块、macOS、本机累计、用户填写或第三方数据库；界面会尽量标注来源。
2. “USB 供电分配 500 mA / 最高约 2.5 W”是供电额度换算，不是实时功耗测量。精确功耗需要外接支持数据输出的 USB 功率计。
3. 本机流量统计无法包含模块在其他设备上产生的流量，也可能因系统重装、数据清理或网卡计数重置而不完整。
4. 公网出口国家或地区由 IP 数据库推断，不代表设备的实际地理位置。
5. 初始化、切换网络或热插拔可能造成暂时断网。重要任务前请保留备用网络。
"""

TIPS_TEXT = """使用小贴士

• 小窗只显示“是否可用、是否临近流量上限、是否异常”；点击“展开详情”查看技术信息。
• 菜单栏图标可随时打开快捷面板；“固定为小窗”会把状态常驻桌面。
• 上下行速度始终使用同一单位。字节模式会在 MB/s、KB/s、B/s 之间自动切换。
• 流量与余额提醒需要先在设置中填写套餐总量、重置日、余额和阈值。
• 发送短信、手动测速和公网 IP 地区查询都可能产生运营商流量或费用。
• 模块初始化成功后，USB 网络配置会保存在模块里；接入兼容系统可直接上网。
"""

HELP_TEXT = """帮助与故障排查

模块未连接：重新插拔 USB，确认 macOS 已允许 USB 配件接入。

未检测到 SIM：关闭占用网络的任务后重新插卡；USB 模块热插拔与 SIM 热插拔是两回事。

不能上网：检查 SIM 是否欠费、是否有流量、信号是否正常；在概览重新检测模块配置。

收不到短信：确认短信监听已开启、SIM 支持短信、模块已经完成 IMS/短信初始化。

流量不一致：本软件统计这台 Mac 上兼容网卡经过的流量，不包含模块在其他设备上的使用量。

位置不准确：公网地区是 IP 数据库推断，运营商漫游、专网、代理或 VPN 都可能改变结果。
"""

TERMS_TEXT_EN = """Terms of Use (Summary)

1. This is an independently developed third-party utility. It is not affiliated with, authorized by, or endorsed by DJI, a mobile carrier, or a SIM issuer.
2. Use it only with compatible 4G modules you own or are authorized to manage, and follow local laws, carrier terms, and pricing.
3. SMS and mobile data may incur carrier charges. Check your plan and device state before sending messages, running speed tests, switching networks, or initializing a module.
4. Plan allowance, balance, and alert thresholds are entered by the user or counted locally and do not replace the carrier's bill.
5. You may stop using the app and remove locally stored data at any time.
"""

PRIVACY_TEXT_EN = """Privacy Notice

Messages, contacts, sent history, plan settings, and local traffic counters are stored on this Mac by default.

If public exit-region lookup is enabled, the current public IP is sent to a third-party IP geolocation database to infer a country or region. This is not GPS location and may be inaccurate. No lookup is performed when the feature is disabled.

A manual speed test connects to Apple's network-quality service and consumes mobile data. Message content and contacts are not uploaded to the developer.
"""

DISCLAIMER_TEXT_EN = """Disclaimer

1. Signal, temperature, IP, traffic, balance, latency, speed, and power information may come from the module, macOS, local counters, user input, or a third-party database. The app labels the source where possible.
2. “USB allocation 500 mA / up to about 2.5 W” is a power-allocation calculation, not live power measurement. Accurate wattage requires an external USB power meter with data output.
3. Local traffic statistics cannot include usage produced when the module is connected to another device and may be incomplete after system reinstallation, data deletion, or interface-counter resets.
4. Public exit country or region is inferred from an IP database and is not the device's physical location.
5. Initialization, network switching, and hot-plugging may briefly interrupt connectivity. Keep a backup connection for important work.
"""

TIPS_TEXT_EN = """Tips

• The mini window answers three questions: is the connection usable, is the data limit near, and is anything wrong. Open Details for technical information.
• Click the menu-bar icon for the quick panel. Pin Mini Window keeps status visible on the desktop.
• Download and upload always use the same unit. Byte mode automatically changes between MB/s, KB/s, and B/s.
• Configure the plan allowance, reset day, balance, and thresholds before using data or balance alerts.
• Sending SMS, running a speed test, and looking up the public IP region may consume carrier data or incur charges.
• After successful initialization, USB network settings remain in the module and compatible systems can use basic internet access directly.
"""

HELP_TEXT_EN = """Help & Troubleshooting

Module not connected: reconnect USB and allow USB accessories when macOS asks.

SIM not detected: stop network-sensitive work and reseat the SIM. USB-module hot-plugging and SIM hot-swapping are different operations.

No internet: check the SIM balance, data allowance, and signal, then recheck module configuration from Overview.

No incoming SMS: enable message watching and confirm that the SIM supports SMS and the module completed IMS/message initialization.

Traffic mismatch: this app counts traffic passing through the compatible interface on this Mac; it cannot include usage from other devices.

Location mismatch: the region is inferred from an IP database and can change because of roaming, private carrier networks, proxies, or VPNs.
"""
