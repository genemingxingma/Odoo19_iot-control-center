# IoT Control Center V2 / 使用手册 / คู่มือผู้ใช้

## 中文

### 洗脱液加热器与洗脱仪（平台 19.0.2.3.0；固件待带负载实机验收）

**2026-09-19：已收到正确源码 hj_heating.tar.gz。候选现为单路 DS18B20(GPIO14)、加热输出 GPIO16 高有效、SSD1306 OLED 0x3C。SW1(GPIO0) 显示芯片/IP，SW2(GPIO2) 启停，SW3(GPIO12) 查看已保存温度。按键用途按用户要求，不沿用原程序的旧用途。旧双路 BIN 禁止刷入；实机 Flash 容量、探头 ROM、输出驱动及首次配置仍须核验。详见 `docs/HEATER_ESP12S_HARDWARE_20260917.md`。**

平台与通信桥接已于 2026-09-19 发布至 imytestth，设备尚未完成机械和加热负载实机验收。运行总览包含“洗脱液加热器”和“洗脱仪”。管理员先注册仪器及唯一令牌；操作员可下发液体目标温度、发布洗脱程序或停止请求。温度下发不会启动加热，加热只能由本机 SW2 启用；程序同步不会启动洗脱，启动需在设备旁确认。只有“设备已应用”才表示设备确认执行，不能仅凭“已发送”判定成功。

开机归零后排液、本地多程序选择和循环次数编程已加入 `3.4.0-rc5` 候选固件。一台 ESP32 及配套屏幕已通过 USB 刷入，测试期间电机、泵断电且软件调试锁定；这不代表机械实机验收完成。屏幕采用英文、较深蓝色顶栏、浅蓝背景、非白色按钮及较饱满的 Verdana Bold 字体，不再显示敞口转子、温度只读和芯片规格等冗余说明，保留故障及必要操作提示。程序在平台编制和发布，平台会自动在设备程序开头加入安全归零；设备按平台完整列表同步新增、修改和归档移除，离线或失败时保留本地程序。每页三个不是容量上限，固件最多接受 64 个有效程序，超限会整批拒绝而不会静默截断。详见 [程序同步说明](docs/WASHER_PROGRAM_SYNC_20260919.md) 和 [最终 USB 测试记录](docs/WASHER_USB_RC5_RELEASE_20260919.md)。服务器测试只用 imytestth 隔离库，不使用生产业务库或 imytestlan。本次范围见 [发布验收](deploy/PRODUCTION_INSTRUMENTS_2_3_0_2026-09-19.md)。

“温度历史”按小时显示有效采样均值，可查看原始记录。断线探头及未同步时间的记录不会算作零度参与统计。洗脱程序发布后冻结，修改时复制新版本；运行日志记录程序版本、步骤、停止和断电中断。固件更新只接受对应硬件的签名包。首次刷写前必须核对接线、机械防护、输出极性和独立过温保护，详见 `docs/INSTRUMENTS_V3_COMMISSIONING.md`。

候选屏幕目前使用英文。按实际使用要求，洗脱程序只在 Odoo 编辑，下发后保存在设备，离线仍可启动当前程序；注液和排液按时间控制，液温只读取和记录，探头异常不停止定时程序。加热器也只接受平台下发的温度，和保护参数一起在设备保存，不提供本地调温。

洗脱固件候选 `3.4.0-rc5`：电机参数按原程序恢复，注液时进液泵和溢水泵全输出、排水泵关闭；排液时两泵均为 150/255，甩干时两泵均为 50/255（约 19.6%，不是 50%）。主轴原基准为归零/定位/洗脱 1 转/秒、甩干 10 转/秒，通过脉冲调速，不调供电电压。平台新建洗脱步骤默认 1 转/秒，甩干步骤默认 10 转/秒；已发布程序和明确指定的速度不会被静默覆盖。注液后不恢复额外 5 秒排液。

暂停装片时所有泵关闭，等待不计时、不自动继续。初始位为 1 号位，每点一次 `NEXT` 完整切换至下一位，顺序为 `1→4→5→2→3→6→1`，同方向交替转 180°、60°。不再按住分段移动，松手不会停止；移动中忽略连点，不接受“继续”，`STOP` 中止运行。需要先对齐初始位时显示 `ALIGN START`，进入暂停本身不会自动转动。确认实际停稳后放片，人工核对配平后按 `CONTINUE`。界面只指示位置，不能检测芯片数量或实际平衡。敞口设备无门盖开关，定位标定、停止距离和硬件急停仍须实机验收；新配置使用 `loading_index_hz`，不复用旧的一秒点动速度字段。

两款设备均无液位检测。加热器默认累计实际加热 10 分钟、温升小于 1 C 即停止加热（恰好 1 C 不触发）并锁定报警；探头断线或读数无效也停机。正常恒温停歇不计入该窗口，恢复读数或重启不自动恢复加热，须在设备旁检查确认。温升不足不是已确认缺液，仍需排查液量、探头位置和加热器。加热器普通温度采样采用最多 128 条滚动缓存，覆盖计数可查；报警不被覆盖，并另有关键事件预留空间。真实存储故障或关键日志满会安全停机。远程停止不能替代硬件急停，详见 `docs/INSTRUMENTS_V3_COMMISSIONING.md`。

### 继电器位置说明（19.0.2.0.8）

继电器卡片在设备名称下直接显示位置说明，不显示字段标题。位置说明固定预留两行，房间固定预留一行；未填写时保留空白占位，确保下方状态区和按钮位置一致。设备名称保持一行，超长位置说明最多显示两行；电脑上悬停可查看全文，手机上打开设备表单查看。列表仍将“位置说明”固定显示在名称右侧。内容沿用设备表单及其翻译，不修改开关、定时或固件设置。

2026-09-09 随 `19.0.2.0.8` 发布至生产系统，此布局继续保留于 `19.0.2.1.1`，布局验收见 `deploy/PRODUCTION_RELAY_LAYOUT_2026-09-09.md`。[桌面示例](docs/screenshots/relays-aligned-zh-desktop.png)和[手机示例](docs/screenshots/relays-aligned-zh-mobile.png)均使用合成数据。此前 `19.0.2.0.7` 的位置快照迁移修复继续保留，详见 `deploy/PRODUCTION_RELAY_DETAIL_2026-09-09.md`。本次不清理历史数据。空白占位表示尚未填写信息，不代表设备故障。

首次 V2 生产切换安装的是 `19.0.2.0.4`，历史验收记录见 `deploy/PRODUCTION_V2_2026-09-06.md`。2.0.1 固件保持隔离；2.0.2 已修复定时配置处理问题，并通过两种板型的开关、保护和倒计时测试。11 台在线继电器已逐台升级、恢复原状态并通过短时联合验收；另有两台长期离线设备保持归档，待现场升级。固件测试记录见 `deploy/RELAY_2_0_2_VALIDATION_2026-09-06.md`。

### 网关公网与内网切换

温湿度网关可暂时保留现有公网接入，待现场修改目的地址后再切换 WireGuard。切换时核实中间件实际看到的来源 IP，在原公司的原网关记录中更新来源地址，不新建重复网关、不改变探头编号与绑定。确认新的实时记录正常后再关闭原公网入口。公司地址不写死在固件中，身份验证不能因切换网络而取消。

`19.0.2.0.4` 修复旧版位置字段仍为 JSON 导致新读数无法入库的问题。已持久化的待处理报文沿用原事件编号和接收时间重试；不要删除队列或伪造补传时间。旧温湿度历史已按授权重置，但员工、打卡原始记录、HR 考勤和临床业务记录保留。历史待复核打卡和温度告警仍需按实际情况处理，不能把软件升级当作业务核验完成。

### 归档设备保护（19.0.2.0.2）

归档的继电器不会因历史保留消息或延迟上报被重新发现为新设备。归档前尚未发送的命令会取消，不再下发。离线旧固件设备应保持归档，完成升级与验证后再由管理员恢复使用。

### 运行总览与考勤核查（19.0.2.0.1）

“功能分区 / 总览”先显示待处理事项，再列出继电器、环境监测、考勤和网络入口。统计只覆盖所选公司及可访问记录；点击数字查看对应筛选结果。总览不会发送开关指令，需手动刷新；刷新失败时会明确提示数据可能过期。

探头卡片以名称为主，保留编号用于排查，并显示最新温湿度、采样时间和趋势入口。继电器的“设备确认状态”与请求状态分开，不能把已发送当作已执行。手机上各功能区改为单列。

考勤设备先检查“连接状态”和“最近设备通信”，再点击“待核查”检查打卡。设备在线不等于考勤成功。优先核对公司国家/时区、设备用户编号对应的员工、签到/签退模式及未签退或重叠记录。不同公司不能共用员工对应关系；有明确序列号时不会按相同 VPN 来源 IP 匹配到其他设备。

ADMS 使用设备的考勤状态，而不是指纹/刷卡等验证方式决定签到、签退。上传按时间顺序处理；重复上传不新增重复打卡；单个人员的匹配异常保留为待核查，不丢弃同批其他人员的数据。格式错误或写入失败不会回复成功。同步不会清空考勤机日志；旧的自动清空选项不再执行。历史 HR 考勤不会自动重算、补签退或删除。

本版支持 ATTLOG 标准文本上传和 JSON Webhook；表单编码导致请求正文不可用时明确拒绝。终端的特殊初始化握手、自动补传及重试间隔仍需对具体型号验证，不应把隔离接口测试当作设备端验收。

界面示例均为合成数据：[中文总览](docs/screenshots/overview-zh-desktop.png)、[探头卡片](docs/screenshots/probes-zh-desktop.png)、[手机总览](docs/screenshots/overview-zh-mobile.png)。生产发布状态以发布验收记录为准。

### 公司与权限

国家与时区、内网主机、MQTT/OTA 端口及原始记录保留天数都从公司配置读取。保留天数为零时不自动删除；正数表示授权清理超过该天数的样本。“保留完整历史”的探头不参与清理。

IoT 用户只能查看；IoT 操作员可以控制本公司设备；IoT 管理员负责配置、绑定、固件和网络维护。查看权限不再隐含控制权限。

### 温湿度

在“环境 / 网关”先注册网关及公司。二进制网关填写中间件实际看到的来源 IP；JSON 网关填写独立验证令牌。探头按“网关、节点、通道”识别，不同公司相同编号不会自动合并。

为探头填写直观名称和位置，图例保留技术编号用于排查。原始记录不可编辑，采样时的公司和位置不会随探头改名、搬动而重写。曲线支持原始样本、小时均值和每日概览。原始样本超过 10000 条会明确提示缩小范围，不会悄悄截断。

同时选择温度和湿度时，左轴为温度、右轴为相对湿度。小时标签采用日期、24 小时制与时区偏移，避免不同时段重名。趋势图不提供温湿度累加、堆叠或饼图；极值和样本数请在透视统计中查看。

旧版原始记录与均值混存结构不再兼容。正式切换前备份；启用明确的 V2 历史清理标记后，标准升级会清除本模块旧温湿度记录与告警，不清除 HR 考勤或其他业务记录。

升级前必须处理重复的网关编号及缺失、矛盾的公司归属。遇到这些问题，升级会提前停止，不会为了继续升级而自动归档具名探头。

### 继电器

“指令下发记录”区分已入队、已发送、设备已确认和过期。网页提交成功不等于设备已经动作。

V2 控制器与 1.8.x 固件的倒计时协议不兼容，不能只升级服务器。需先使用隔离控制器和非关键测试设备完成验证，再安排控制器、中间件及固件的配套切换。

2.0.2 支持从旧状态文件进入单向 V1 迁移模式，供旧中心暂时控制已配置设备。收到有效的有序 V2 指令后永久停止接受 V1 指令；新设备不启用迁移模式。旧协议缺少序列、到期时间或指令 ID 时，不能提供完整防重放保证。逐台升级必须分别记录状态、确认新版本和恢复结果；出现持续重连或确认超时立即停止，不能只看“在线”。

排查反复重连时，先核对运行时长、复位原因和保留指令。诊断中如需移除保留指令，应先备份，不能清空所有设备的配置。旧版后台会复用消息记录，最新回报应按接收时间判断，不能只按记录编号判断。升级验收还须匹配实时回报中的指令编号和配置版本，并交叉检查后台状态；发送成功不等于设备已执行。

明确“关闭”会取消延时并锁止自动开启；下一次明确“开启”或“开始延时”才解除锁止。重启与最大开启时长保护也采用安全关闭。紫外灯等设备勾选“安全关键设备”并设置有限的最大连续开启时长。软件不能代替门联锁、急停开关和现场验证。

新固件不内置公司的 Wi-Fi 密码、服务器地址或网络端点。首次配置选择正确硬件型号并填写引导网络参数；之后从控制中心接收公司配置，保存成功后回报配置摘要。已经配置的设备，只有按住实体按钮开机才进入配置入口。

OTA 必须配置可信服务器证书指纹；未配置时拒绝升级，不再跳过 HTTPS 证书校验。主、备用 OTA 地址必须使用受信任的证书。不要在聊天、日志或 Git 中提交密码。

### OpenWrt 与考勤

OpenWrt 首次连接前由管理员核实并安装 SSH 主机密钥。心跳最多并行检查 8 台 AP，单次 SSH 有超时，补传的旧状态不会覆盖较新状态。

考勤在允许的最长班次时长内支持跨午夜匹配，不再受执行任务用户的时区或自然日切换影响。错误提示按当前界面语言展示，技术原始消息保留用于排查。

## English

### Buffer Heaters and Array Washers (Platform 19.0.2.3.0; Loaded Hardware Acceptance Pending)

**Source correction, 2026-09-19: hj_heating.tar.gz confirms one DS18B20 on GPIO14, active-high heat on GPIO16 and SSD1306 OLED at 0x3C. SW1(GPIO0) shows chip/IP, SW2(GPIO2) enables/stops and SW3(GPIO12) shows the stored target. Previous dual-channel BINs remain prohibited. Physical Flash size, probe ROM, driver and commissioning remain unverified. See `docs/HEATER_ESP12S_HARDWARE_20260917.md`.**

The platform and bridge were released on imytestth on 2026-09-19; mechanical and loaded-heater acceptance remains pending. Register each instrument and its unique token before use. Operators can send the temperature target, release washer programs, or request a stop. Downloading does not start heating or motion: SW2 is the only heating enable and washer start remains local. Check device-applied acknowledgements rather than assuming a sent command succeeded.

Washer startup home/drain, local multi-program selection and explicit cycle counts are implemented in the `3.4.0-rc5` candidate. One ESP32 and its paired screen have been USB-flashed with actuator power isolated and software commissioning locked; mechanical acceptance remains pending. The English-only darker blue/white UI uses an embedded bold Verdana font and light-blue controls on pale surfaces, and removes redundant rotor, read-only and chip-specification labels. Programs are authored and released in Odoo; publishing automatically prepends a safe homing step. The complete catalog synchronizes additions, revisions and removals while retaining local programs offline or after errors. Three programs per page is not a capacity limit; the firmware accepts up to 64 valid programs and rejects an oversized catalog atomically. See [program synchronization](docs/WASHER_PROGRAM_SYNC_20260919.md) and [final USB test evidence](docs/WASHER_USB_RC5_RELEASE_20260919.md). Server tests use isolated databases on imytestth, never its production business database or imytestlan. See [the production release](deploy/PRODUCTION_INSTRUMENTS_2_3_0_2026-09-19.md).

Temperature history groups valid observations by hour; sensor faults and unsynchronised timestamps are excluded from averages. Released programs are immutable; duplicate to revise. Run logs retain program revision, steps and interruptions. OTA and ESP32 SD updates require a matching signed package and an idle device. Verify wiring, output polarity, mechanical protection and independent thermal protection before commissioning.

The candidate screen is English-only. Programs are edited only in Odoo and stored on the washer for offline use. Filling and draining are timed; liquid temperature is recorded, not controlled, and a sensor warning does not stop the timed program. Heater targets and protection settings are also downloaded and stored locally; there is no local temperature editing.

Washer candidate `3.4.0-rc5` restores original motor values: the inlet and overflow run at full output during filling, with the bottom drain off. Both pumps use 150/255 during drainage and 50/255 during spin drying (about 19.6%, not 50%). Original spindle settings are 1 rev/s for homing/positioning/washing and 10 rev/s for spin drying, controlled by pulses rather than supply voltage. New wash steps default to 1 rev/s and spin-dry steps to 10 rev/s; published programs and explicit speeds are not overwritten. The extra five-second post-fill drain is not restored.

During a manual wait, all pumps stay off and the program never continues on a timer. Starting at slot 1, each NEXT tap completes one move in order `1 -> 4 -> 5 -> 2 -> 3 -> 6 -> 1`, alternating +180 and +60 degrees in the same direction. This replaces hold-to-jog; release does not stop a move. Further taps and Continue are rejected during motion; STOP aborts the run. ALIGN START explicitly aligns slot 1 if necessary; entering a wait does not move automatically. Confirm standstill before loading and verify physical balance before CONTINUE. Slot indicators do not sense slides or balance. Loading calibration, stopping distance and emergency stopping remain hardware acceptance items on this open-top machine. Use the new `loading_index_hz` configuration; the old one-second jog-speed field is not reused.

Neither device has a level sensor. The heater stops heating and latches an alarm if the temperature rises by less than 1 C in 600 seconds of actual heating (default), or if a probe fails. Normal thermostat-off time is excluded. Sensor recovery or reboot never restarts heating automatically; inspect and confirm locally. Insufficient rise is not proof of an empty container. Ordinary heater samples use a rolling buffer of up to 128 records, with a visible overwrite count; alarms are not evicted and separate capacity is reserved for critical events. Real storage failure or critical-log exhaustion causes a safe stop. A remote stop does not replace physical emergency stopping. See `docs/INSTRUMENTS_V3_COMMISSIONING.md`.

### Relay Location Details (19.0.2.0.8)

Relay cards show the location detail below the name without a heading. The detail always reserves two lines and the room reserves one, even when empty, keeping the state panel and buttons aligned. Device names stay on one line and long details are limited to two lines. Hover for full text on desktop, or open the device form on mobile. The list keeps Location Detail beside the name. Values and translations use the existing device form; relay state, schedules and firmware settings are unchanged.

Released to production on 2026-09-09 as `19.0.2.0.8`; see `deploy/PRODUCTION_RELAY_LAYOUT_2026-09-09.md` and the [synthetic desktop example](docs/screenshots/relays-aligned-en-desktop.png). The preceding `19.0.2.0.7` snapshot migration fix remains in place; see `deploy/PRODUCTION_RELAY_DETAIL_2026-09-09.md`. This layout release does not discard history. An empty slot means the detail has not been filled in, not that the device has failed.

### Archived Device Protection (19.0.2.0.2)

Retained or late reports do not rediscover archived relays. Commands still queued when a device is archived are cancelled. Keep offline legacy devices archived until an administrator upgrades and verifies them before returning them to service.

### Overview and Attendance Review (19.0.2.0.1)

Start at Workspaces / Overview. Click priority counts to open the matching records in the selected companies. Refresh is manual; a failed refresh clearly marks potentially stale data. The overview never sends device commands. Probe cards show names, recent temperature/humidity and trend links. Relay confirmation is distinct from requested output state. Workspaces stack vertically on phones.

For attendance, check connection and last contact first, then review pending punches. Contact alone does not prove HR attendance was matched. Check company timezone/country, terminal user IDs, employee mappings, direction mode and overlapping/open attendance. Mappings cannot cross companies; a conflicting serial number never falls back to a shared VPN source address.

ADMS direction comes from attendance status, not the verification method. Batches are sorted; replays are deduplicated; one employee's matching error remains reviewable without discarding other employees. Failed imports are not acknowledged as successful. Synchronization never clears terminal logs, including the former automatic-clear option. Historical HR attendance is not silently recalculated, closed or deleted. Model-specific initialization and device retry behavior still require hardware validation.

All screenshots use synthetic data: [English overview](docs/screenshots/overview-en-desktop.png). See the production acceptance record for the deployed scope.

The initial V2 production cutover installed `19.0.2.0.4`; see `deploy/PRODUCTION_V2_2026-09-06.md`. Firmware 2.0.1 remains quarantined. The 2.0.2 fix passed switching, watchdog and timer tests on both board profiles. All 11 online relays passed serial upgrade, state restoration and bounded fleet observation; two long-offline devices remain archived pending onsite upgrade. See `deploy/RELAY_2_0_2_VALIDATION_2026-09-06.md`.

Keep the gateway's current public route until its destination is changed onsite. For WireGuard cutover, verify the source address seen by the bridge and update the same company's existing gateway through Odoo. Preserve probe identities and bindings. Confirm fresh samples before closing public access. Never disable authentication or hard-code company endpoints in firmware.

Version `19.0.2.0.4` converts legacy JSON location columns to text snapshots. Retry durable events with their original identities and reception times; never purge the queue or invent backfill timestamps. The authorized reset affects old environmental history, not employee, punch, HR attendance or clinical records. Historical punches needing review and threshold alerts still require operational review.

Configure country, timezone, private routes, OTA certificate trust and retention on the company. Zero retention keeps all raw history; positive retention authorizes expiry deletion, except probes marked to keep full history.

Viewers, operators and managers have separate privileges. Register gateways before ingestion. Binary source IPs must map to known company gateways; JSON gateways require their own token. Probe identities are scoped to gateways.

Resolve duplicate gateway identities and missing or inconsistent company ownership before upgrading. Migration stops rather than silently archiving named probes. V2 control requires compatible firmware; 1.8.x cannot be left operating under a backend-only V2 upgrade. Validate an isolated controller/device pair before a coordinated cutover.

Raw observations are immutable and keep collection-time company/location snapshots. Use meaningful probe names, then select raw, hourly or daily chart views. Oversized raw requests require narrowing the range or using an aggregate.

When both metrics are selected, temperature uses the left axis and humidity the right. Hour labels include the date, 24-hour time and UTC offset. Cumulative, stacked and pie displays are not offered for these measurements; use the pivot for extrema and sample counts.

Command Delivery distinguishes durable intent, publication and device confirmation. OFF cancels delays and inhibits automatic ON. An explicit ON/start resumes operation. Boot/watchdog cutoff fail closed. Configure finite limits for safety-critical equipment and retain physical interlocks.

Firmware 2.0.2 can load a one-way V1 migration mode from an existing V1 state file. A valid sequenced V2 command permanently disables V1 commands; fresh devices do not enter migration mode. Legacy traffic missing sequence, expiry or command identity cannot provide full replay protection. Capture and verify each device separately during rolling updates. Repeated reconnects or missing confirmations stop the rollout, even if the page says online.

For repeated reconnects, inspect uptime, reset reason and retained commands first. Back up any retained command before a targeted diagnostic removal; never clear the fleet's configuration. V1 can reuse message rows, so determine the latest report by reception time rather than row ID. Upgrade acceptance also requires matching live command identities and configuration revisions, cross-checked against backend state. Publication is not proof of device execution.

Firmware has no company-specific network defaults. Provision the correct hardware profile and bootstrap connection, then apply company settings from the control center. OTA requires a trusted TLS certificate fingerprint. Configured devices enter the setup portal only with the physical boot button held.

OpenWrt requires pre-verified SSH host keys. Heartbeats use bounded concurrency/timeouts and ignore stale replay. Attendance can cross midnight within the allowed shift duration and no longer depends on the background user's timezone.

V2 is a breaking release. Back up first and explicitly authorize removal of old module temperature/humidity observations and alerts. HR attendance and unrelated business data are not part of this reset. Do not upgrade production or real devices on the strength of compilation alone.

## ภาษาไทย

### เครื่องอุ่นน้ำยาล้างและเครื่องล้างสไลด์ (แพลตฟอร์ม 19.0.2.3.0; รอตรวจรับเครื่องจริงพร้อมโหลด)

**แก้ไขตามซอร์สที่ถูกต้อง 2026-09-19: hj_heating.tar.gz ใช้ DS18B20 หนึ่งช่องที่ GPIO14, เอาต์พุตทำความร้อน GPIO16 แบบ HIGH และ SSD1306 OLED 0x3C ปุ่ม SW1(GPIO0) แสดงชิป/IP, SW2(GPIO2) เปิดใช้หรือหยุด และ SW3(GPIO12) แสดงค่าที่บันทึกแล้ว ห้ามใช้ BIN สองช่องเดิม ยังต้องตรวจ Flash, ROM หัววัด และวงจรขับกับเครื่องจริง ดู `docs/HEATER_ESP12S_HARDWARE_20260917.md`**

เผยแพร่แพลตฟอร์มและระบบรับส่งข้อมูลบน imytestth เมื่อ 2026-09-19 แต่ยังไม่ผ่านการตรวจรับกลไกและโหลดทำความร้อนจริง ต้องลงทะเบียนเครื่องมือและโทเคนเฉพาะก่อนใช้งาน ผู้ปฏิบัติงานส่งอุณหภูมิเป้าหมาย โปรแกรมล้างที่เผยแพร่แล้ว หรือคำสั่งหยุดได้ การส่งข้อมูลไม่เริ่มทำความร้อนหรือการเคลื่อนไหว การทำความร้อนเปิดใช้ได้จาก SW2 ที่เครื่องเท่านั้น และการเริ่มล้างต้องยืนยันที่เครื่อง ตรวจสอบสถานะที่อุปกรณ์ยืนยัน ไม่ใช่เพียงสถานะส่งแล้ว

รุ่นทดสอบ `3.4.0-rc5` เพิ่มการกลับตำแหน่งและระบายหลังเปิดเครื่อง การเลือกหลายโปรแกรม และการกำหนดจำนวนรอบล้างแล้ว แฟลช ESP32 และจอหนึ่งชุดผ่าน USB แล้ว โดยตัดไฟมอเตอร์และปั๊ม พร้อมล็อกการใช้งานในซอฟต์แวร์ ยังไม่ถือว่าผ่านการตรวจรับกลไก หน้าจอภาษาอังกฤษใช้ตัวอักษร Verdana Bold แถบสีน้ำเงินเข้ม พื้นหลังฟ้าอ่อน และปุ่มสีฟ้าแทนปุ่มสีขาว โปรแกรมสร้างและเผยแพร่ใน Odoo โดยระบบเพิ่มขั้นตอนกลับตำแหน่งที่ต้นโปรแกรมให้อัตโนมัติ รายการทั้งหมดซิงค์ตามแพลตฟอร์ม ทั้งเพิ่ม แก้ไข และนำออก หากออฟไลน์หรือซิงค์ไม่สำเร็จจะคงรายการเดิมไว้ สามโปรแกรมต่อหน้าไม่ใช่ความจุสูงสุด อุปกรณ์รับได้สูงสุด 64 โปรแกรมที่ถูกต้องและจะปฏิเสธทั้งชุดเมื่อเกินขีดจำกัด ดู [การซิงค์โปรแกรม](docs/WASHER_PROGRAM_SYNC_20260919.md) และ [ผลทดสอบ USB ขั้นสุดท้าย](docs/WASHER_USB_RC5_RELEASE_20260919.md) การทดสอบบนเซิร์ฟเวอร์ใช้ฐานข้อมูลแยกบน imytestth เท่านั้น ไม่ใช้ฐานข้อมูลจริงหรือ imytestlan ดู [บันทึกการเผยแพร่](deploy/PRODUCTION_INSTRUMENTS_2_3_0_2026-09-19.md)

ประวัติอุณหภูมิแสดงค่าเฉลี่ยรายชั่วโมง โดยไม่นำค่าจากเซ็นเซอร์ผิดพลาดหรือเวลาที่ยังไม่ซิงค์มาคำนวณ โปรแกรมที่เผยแพร่แล้วแก้ไขไม่ได้ ต้องทำสำเนาเป็นรุ่นใหม่ บันทึกการทำงานเก็บรุ่นโปรแกรม ขั้นตอนและการหยุดชะงัก การอัปเดต OTA และ SD ของ ESP32 ต้องใช้แพ็กเกจลงนามที่ตรงรุ่นและเครื่องต้องว่าง ต้องตรวจสาย ขั้วเอาต์พุต อุปกรณ์ป้องกันส่วนหมุน และอุปกรณ์ตัดความร้อนอิสระก่อนใช้งาน

หน้าจอรุ่นทดสอบใช้ภาษาอังกฤษเท่านั้น แก้ไขโปรแกรมเฉพาะใน Odoo แล้วบันทึกลงเครื่องล้างเพื่อใช้งานออฟไลน์ การเติมและระบายน้ำยาควบคุมด้วยเวลา อุณหภูมิใช้บันทึก ไม่ได้ควบคุม และคำเตือนเซ็นเซอร์ไม่หยุดโปรแกรมตามเวลา เครื่องอุ่นรับอุณหภูมิเป้าหมายและค่าป้องกันจากแพลตฟอร์ม บันทึกไว้ในเครื่อง และไม่ให้ปรับอุณหภูมิที่ตัวเครื่อง

เครื่องล้างรุ่นทดสอบ `3.4.0-rc5` ใช้ค่ามอเตอร์ตามโปรแกรมเดิม ระหว่างเติมน้ำยา ปั๊มเติมและปั๊มน้ำล้นทำงานเต็มกำลัง ปั๊มระบายด้านล่างปิด ระหว่างระบายทั้งสองปั๊มใช้ 150/255 และขณะปั่นแห้งใช้ 50/255 (ประมาณ 19.6% ไม่ใช่ 50%) ค่าเดิมของแกนหมุนคือ 1 รอบ/วินาทีสำหรับกลับตำแหน่ง จัดตำแหน่ง และล้าง กับ 10 รอบ/วินาทีสำหรับปั่นแห้ง ควบคุมด้วยพัลส์ ไม่ใช่ปรับแรงดันไฟฟ้า ขั้นตอนล้างใหม่ใช้ค่าเริ่มต้น 1 รอบ/วินาที และปั่นแห้ง 10 รอบ/วินาที โดยไม่แก้โปรแกรมที่เผยแพร่แล้วหรือค่าที่ระบุไว้ชัดเจน ไม่คืนการระบายเพิ่ม 5 วินาทีหลังเติม

ขณะรอผู้ปฏิบัติงาน ปั๊มทั้งหมดปิดและไม่ทำงานต่อเอง เริ่มที่ช่อง 1 แตะ `NEXT` แต่ละครั้งเพื่อหมุนครบหนึ่งตำแหน่งตามลำดับ `1 -> 4 -> 5 -> 2 -> 3 -> 6 -> 1` โดยหมุนทิศทางเดียวกันสลับ 180 และ 60 องศา ไม่ต้องกดค้าง และปล่อยนิ้วแล้วเครื่องจะยังหมุนจนถึงตำแหน่ง ระหว่างเคลื่อนที่จะไม่รับการแตะซ้ำหรือคำสั่งดำเนินการต่อ กด `STOP` เพื่อยุติการทำงาน ถ้าต้องจัดตำแหน่งเริ่มต้นให้กด `ALIGN START` การเข้าสู่ขั้นตอนรอไม่ทำให้หมุนเอง ตรวจว่าโรเตอร์หยุดสนิทก่อนใส่สไลด์ และตรวจสมดุลจริงก่อนกด `CONTINUE` หน้าจอแสดงตำแหน่งเท่านั้น ไม่ตรวจจำนวนสไลด์หรือสมดุล เครื่องเป็นแบบเปิด ต้องตรวจรับการสอบเทียบ ระยะหยุด และปุ่มหยุดฉุกเฉิน ใช้ค่า `loading_index_hz` ใหม่ ไม่ใช้ค่าความเร็วขยับทีละหนึ่งวินาทีเดิม

ทั้งสองเครื่องไม่มีเซ็นเซอร์ระดับน้ำยา ค่าเริ่มต้นของเครื่องอุ่นคือหยุดทำความร้อนและค้างสัญญาณเตือนเมื่อเปิดทำความร้อนสะสม 600 วินาทีแล้วอุณหภูมิเพิ่มน้อยกว่า 1 C หรือเซ็นเซอร์ขัดข้อง ไม่นับช่วงที่เทอร์โมสตัทหยุดตามปกติ การอ่านค่ากลับมาหรือรีบูตจะไม่เริ่มทำความร้อนเอง ต้องตรวจและยืนยันที่เครื่อง อุณหภูมิเพิ่มไม่พอไม่ได้พิสูจน์ว่าน้ำยาหมด ตัวอย่างอุณหภูมิเครื่องอุ่นใช้บัฟเฟอร์หมุนเวียนสูงสุด 128 รายการและนับรายการที่ถูกเขียนทับ ไม่ลบสัญญาณเตือนและสงวนพื้นที่แยกสำหรับเหตุการณ์สำคัญ หากหน่วยความจำขัดข้องหรือบันทึกสำคัญเต็ม เครื่องจะหยุด คำสั่งหยุดระยะไกลไม่ใช้แทนปุ่มหยุดฉุกเฉิน ดู `docs/INSTRUMENTS_V3_COMMISSIONING.md`

### รายละเอียดตำแหน่งรีเลย์ (19.0.2.0.8)

เผยแพร่รุ่น `19.0.2.0.8` สู่ระบบใช้งานจริงเมื่อ 2026-09-09 ดูบันทึกตรวจรับที่ `deploy/PRODUCTION_RELAY_LAYOUT_2026-09-09.md` พร้อม[ตัวอย่างหน้าจอคอมพิวเตอร์](docs/screenshots/relays-aligned-th-desktop.png)และ[โทรศัพท์](docs/screenshots/relays-aligned-th-mobile.png) ซึ่งใช้ข้อมูลจำลองทั้งหมด รุ่นนี้ไม่ลบประวัติและยังคงการแก้ไขข้อมูลตำแหน่งจากรุ่น `19.0.2.0.7` ช่องว่างหมายถึงยังไม่ได้กรอกข้อมูล ไม่ใช่อุปกรณ์ขัดข้อง

การ์ดรีเลย์แสดงรายละเอียดตำแหน่งใต้ชื่ออุปกรณ์โดยไม่แสดงหัวข้อ โดยจองพื้นที่รายละเอียดไว้สองบรรทัดและห้องหนึ่งบรรทัดเสมอ แม้ไม่ได้กรอกข้อมูล เพื่อให้ส่วนสถานะและปุ่มอยู่ตรงกัน ชื่ออุปกรณ์แสดงหนึ่งบรรทัด ส่วนรายละเอียดแสดงไม่เกินสองบรรทัด บนคอมพิวเตอร์เลื่อนเมาส์ค้างเพื่อดูข้อความทั้งหมด หรือเปิดแบบฟอร์มอุปกรณ์บนโทรศัพท์ มุมมองรายการยังแสดงรายละเอียดตำแหน่งถัดจากชื่อ ข้อมูลและคำแปลมาจากแบบฟอร์มเดิม โดยไม่เปลี่ยนการเปิดปิด ตารางเวลา หรือเฟิร์มแวร์

### การป้องกันอุปกรณ์ที่เก็บถาวร (19.0.2.0.2)

ข้อความที่ค้างอยู่หรือส่งมาล่าช้าจะไม่ทำให้รีเลย์ที่เก็บถาวรถูกค้นพบเป็นอุปกรณ์ใหม่ คำสั่งที่ยังรอส่งจะถูกยกเลิก อุปกรณ์ออฟไลน์ที่ใช้เฟิร์มแวร์เก่าควรคงสถานะเก็บถาวรไว้จนกว่าผู้ดูแลจะอัปเกรดและตรวจสอบก่อนนำกลับมาใช้งาน

### ภาพรวมและการตรวจสอบลงเวลา (19.0.2.0.1)

เปิดส่วนการทำงาน / ภาพรวม แล้วคลิกจำนวนรายการที่ต้องดูแลเพื่อดูข้อมูลของบริษัทที่เลือก กดรีเฟรชเพื่อโหลดสถานะล่าสุด หากรีเฟรชไม่สำเร็จจะมีคำเตือนว่าข้อมูลอาจเก่า หน้าภาพรวมไม่ส่งคำสั่งควบคุมอุปกรณ์ การ์ดเซ็นเซอร์แสดงชื่อ อุณหภูมิ ความชื้น และปุ่มดูแนวโน้ม สถานะที่รีเลย์ยืนยันแยกจากสถานะที่ร้องขอ บนโทรศัพท์จะแสดงทีละส่วนในแนวตั้ง

สำหรับเครื่องลงเวลา ให้ตรวจสอบการเชื่อมต่อและเวลาติดต่อล่าสุด จากนั้นเปิดรายการรอตรวจสอบ การเชื่อมต่อสำเร็จไม่ได้แปลว่าบันทึก HR ถูกต้องแล้ว ตรวจสอบประเทศและเขตเวลาบริษัท รหัสผู้ใช้ในเครื่อง การจับคู่พนักงาน โหมดเข้า/ออก และช่วงเวลาซ้อนทับหรือรายการที่ยังไม่ออก ห้ามจับคู่ข้ามบริษัท และไม่ใช้ IP ของ VPN แทนหมายเลขเครื่องที่ไม่ตรงกัน

ADMS ใช้สถานะลงเวลา ไม่ใช้วิธียืนยันตัวตนเพื่อตัดสินเข้า/ออก ระบบเรียงข้อมูลตามเวลาและไม่สร้างรายการซ้ำ ข้อผิดพลาดของพนักงานคนหนึ่งจะไม่ทำให้ข้อมูลของคนอื่นหาย การนำเข้าที่ล้มเหลวจะไม่ตอบว่าสำเร็จ การซิงค์ไม่ล้างข้อมูลในเครื่อง แม้เคยเปิดตัวเลือกล้างอัตโนมัติ ประวัติ HR จะไม่ถูกคำนวณใหม่ ปิดรายการ หรือลบโดยอัตโนมัติ ยังต้องทดสอบขั้นตอนเริ่มเชื่อมต่อและการส่งซ้ำกับเครื่องรุ่นจริง

ภาพตัวอย่างเป็นข้อมูลจำลองทั้งหมด: [ภาพรวมภาษาไทย](docs/screenshots/overview-th-desktop.png) และ [หน้าจอโทรศัพท์](docs/screenshots/overview-th-mobile.png) ขอบเขตการใช้งานจริงให้ดูจากบันทึกตรวจรับ

การเปลี่ยนระบบเป็น V2 ครั้งแรกติดตั้งรุ่น `19.0.2.0.4` ดูบันทึกเดิมที่ `deploy/PRODUCTION_V2_2026-09-06.md` เฟิร์มแวร์ 2.0.1 ยังถูกระงับการใช้งาน ส่วน 2.0.2 แก้ปัญหาการประมวลผลตารางเวลาแล้ว และผ่านการทดสอบเปิดปิด การตัดเมื่อเปิดนานเกินกำหนด และตัวจับเวลากับฮาร์ดแวร์ทั้งสองรุ่น รีเลย์ออนไลน์ทั้ง 11 เครื่องอัปเกรดทีละเครื่อง คืนสถานะเดิม และผ่านการตรวจสอบร่วมกันในช่วงเวลาทดสอบแล้ว อีกสองเครื่องที่ออฟไลน์มานานยังคงเก็บถาวรเพื่อรออัปเกรดหน้างาน ดูบันทึกที่ `deploy/RELAY_2_0_2_VALIDATION_2026-09-06.md`

เกตเวย์อุณหภูมิและความชื้นใช้เส้นทางสาธารณะเดิมต่อไปได้จนกว่าจะเปลี่ยนปลายทางที่หน้างาน เมื่อเปลี่ยนเป็น WireGuard ให้ตรวจสอบ IP ต้นทางที่บริดจ์เห็นจริง แล้วแก้ที่เกตเวย์เดิมของบริษัทใน Odoo โดยไม่สร้างเกตเวย์ซ้ำหรือเปลี่ยนการผูกเซ็นเซอร์ ตรวจสอบว่ามีข้อมูลใหม่ก่อนปิดช่องทางสาธารณะ ห้ามปิดการยืนยันตัวตนหรือฝังที่อยู่ของบริษัทลงในเฟิร์มแวร์

รุ่น `19.0.2.0.4` แปลงคอลัมน์ตำแหน่งแบบ JSON เดิมให้เป็นข้อความ เพื่อรับค่าที่อ่านใหม่ได้ ข้อความที่เก็บในคิวต้องส่งซ้ำโดยใช้หมายเลขเหตุการณ์และเวลารับเดิม ห้ามล้างคิวหรือสร้างเวลาย้อนหลังขึ้นเอง การรีเซ็ตที่ได้รับอนุญาตครอบคลุมเฉพาะประวัติสิ่งแวดล้อมเดิม ไม่รวมพนักงาน ข้อมูลลงเวลา ประวัติ HR หรือข้อมูลทางคลินิก รายการลงเวลาที่รอตรวจสอบและการแจ้งเตือนเกินเกณฑ์ยังต้องตรวจสอบตามข้อเท็จจริง

ตั้งค่าประเทศ เขตเวลา เครือข่ายภายใน ใบรับรอง OTA และระยะเวลาเก็บข้อมูลที่บริษัท ค่า 0 หมายถึงเก็บข้อมูลดิบโดยไม่ลบอัตโนมัติ ค่ามากกว่า 0 อนุญาตให้ลบข้อมูลที่เกินระยะเวลาที่กำหนด ยกเว้นเซ็นเซอร์ที่ตั้งให้เก็บประวัติทั้งหมด

แยกสิทธิ์ผู้ดูข้อมูล ผู้ควบคุมอุปกรณ์ และผู้ดูแลระบบ ต้องลงทะเบียนเกตเวย์กับบริษัทก่อนรับข้อมูล ระบุ IP ต้นทางสำหรับเกตเวย์ไบนารี และโทเคนเฉพาะสำหรับเกตเวย์ JSON หมายเลขเซ็นเซอร์ซ้ำกันได้เมื่ออยู่คนละเกตเวย์

ก่อนอัปเกรด ต้องแก้หมายเลขเกตเวย์ที่ซ้ำกัน รวมถึงบริษัทที่ยังไม่ได้ระบุหรือไม่ตรงกัน ระบบจะหยุดการอัปเกรดแทนการเก็บเซ็นเซอร์เข้าคลังโดยอัตโนมัติ ตัวควบคุม V2 ใช้โปรโตคอลจับเวลาที่ไม่เข้ากับเฟิร์มแวร์ 1.8.x จึงห้ามอัปเกรดเฉพาะเซิร์ฟเวอร์ ต้องทดสอบตัวควบคุมกับอุปกรณ์ในระบบแยกก่อน แล้วจึงวางแผนเปลี่ยนตัวควบคุม บริดจ์ และเฟิร์มแวร์พร้อมกัน

ข้อมูลดิบที่บันทึกแล้วแก้ไขไม่ได้ และเก็บบริษัทกับตำแหน่ง ณ เวลาที่อ่านค่า ตั้งชื่อเซ็นเซอร์ให้สื่อถึงอุปกรณ์หรือสถานที่ กราฟเลือกดูข้อมูลดิบ ค่าเฉลี่ยรายชั่วโมง หรือรายวันได้ หากข้อมูลดิบเกิน 10000 รายการ ระบบจะแจ้งให้ลดช่วงเวลาหรือเลือกค่าเฉลี่ย

เมื่อเลือกทั้งสองค่า แกนซ้ายแสดงอุณหภูมิและแกนขวาแสดงความชื้น ป้ายเวลามีวันที่ เวลาแบบ 24 ชั่วโมง และส่วนต่างจาก UTC ไม่ใช้กราฟสะสม กราฟซ้อน หรือกราฟวงกลมกับค่าเหล่านี้ ดูค่าสูงสุด ต่ำสุด และจำนวนตัวอย่างได้ในตาราง Pivot

หน้าประวัติคำสั่งแยกสถานะเข้าคิว ส่งแล้ว และอุปกรณ์ยืนยันแล้ว คำสั่งปิดจะยกเลิกตัวจับเวลาและระงับการเปิดอัตโนมัติ ต้องสั่งเปิดหรือเริ่มจับเวลาใหม่เพื่อกลับมาทำงาน การเริ่มระบบใหม่และการตัดเมื่อเปิดนานเกินกำหนดจะเข้าสู่สถานะปิดอย่างปลอดภัย อุปกรณ์สำคัญด้านความปลอดภัยต้องมีเวลาสูงสุดและระบบตัดทางกายภาพ

เฟิร์มแวร์ 2.0.2 รองรับโหมดเปลี่ยนผ่าน V1 เฉพาะอุปกรณ์ที่มีไฟล์สถานะ V1 เดิม เมื่อรับคำสั่ง V2 ที่มีลำดับถูกต้องแล้ว จะไม่รับคำสั่ง V1 อีก อุปกรณ์ใหม่ไม่ใช้โหมดนี้ คำสั่งเก่าที่ไม่มีลำดับ เวลาหมดอายุ หรือหมายเลขคำสั่งยังป้องกันการเล่นซ้ำได้ไม่ครบ ต้องบันทึกและตรวจสอบสถานะก่อนและหลังอัปเกรดทีละเครื่อง หากเชื่อมต่อซ้ำหรือไม่ได้รับการยืนยัน ให้หยุดอัปเกรด แม้หน้าจอจะแสดงว่าออนไลน์

หากอุปกรณ์เชื่อมต่อซ้ำ ให้ตรวจสอบระยะเวลาทำงาน สาเหตุการรีเซ็ต และคำสั่งที่โบรกเกอร์เก็บไว้ก่อน หากต้องนำคำสั่งที่เก็บไว้ออกเพื่อวิเคราะห์ ให้สำรองและดำเนินการเฉพาะเครื่องนั้น ห้ามล้างการตั้งค่าทุกเครื่อง ระบบ V1 อาจใช้แถวข้อความเดิมซ้ำ จึงต้องดูเวลารับข้อความแทนหมายเลขแถวเมื่อตรวจสอบข้อมูลล่าสุด การตรวจรับหลังอัปเกรดต้องตรวจสอบหมายเลขคำสั่งและรุ่นการตั้งค่าจากข้อความสดให้ตรงกัน พร้อมตรวจสอบสถานะในระบบ การส่งสำเร็จไม่ได้ยืนยันว่าอุปกรณ์ทำงานตามคำสั่งแล้ว

เฟิร์มแวร์ไม่ฝังรหัสผ่านหรือที่อยู่เครือข่ายของบริษัท ตั้งค่ารุ่นฮาร์ดแวร์และการเชื่อมต่อเริ่มต้นก่อน จากนั้นรับการตั้งค่าบริษัทจากศูนย์ควบคุม OTA ต้องมีลายนิ้วมือใบรับรอง TLS ที่เชื่อถือได้ อุปกรณ์ที่ตั้งค่าแล้วจะเปิดหน้าตั้งค่าเมื่อกดปุ่มบนตัวอุปกรณ์ขณะเปิดเครื่องเท่านั้น

OpenWrt ต้องตรวจสอบและติดตั้ง SSH host key ก่อนใช้งาน ตรวจสอบพร้อมกันได้ไม่เกิน 8 เครื่องและมีเวลารอสูงสุด ข้อมูลย้อนหลังจะไม่ทับสถานะที่ใหม่กว่า การลงเวลางานรองรับกะข้ามเที่ยงคืนภายในระยะเวลาที่อนุญาต

V2 เปลี่ยนโครงสร้างข้อมูล ต้องสำรองข้อมูลและอนุญาตการลบประวัติอุณหภูมิ/ความชื้นกับการแจ้งเตือนเดิมก่อนอัปเกรด ข้อมูลลงเวลาของ HR และข้อมูลธุรกิจอื่นไม่อยู่ในขอบเขตการลบ ต้องทดสอบในฐานข้อมูลแยกก่อนใช้งานจริง
