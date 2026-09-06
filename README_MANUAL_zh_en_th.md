# IoT Control Center V2 / 使用手册 / คู่มือผู้ใช้

## 中文

本手册描述 V2 候选架构，不代表生产服务器已切换。2.0.1 固件保持隔离；2.0.2 已修复定时配置处理问题，并通过两种板型的开关、保护和倒计时测试。11 台在线继电器已逐台升级、恢复原状态并通过短时联合验收；另有两台长期离线设备待处理。记录见 `deploy/RELAY_2_0_2_VALIDATION_2026-09-06.md`。

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

This manual describes the V2 candidate, not a completed production backend cutover. Firmware 2.0.1 remains quarantined. The 2.0.2 fix passed switching, watchdog and timer tests on both board profiles. All 11 online relays passed serial upgrade, state restoration and bounded fleet observation; two long-offline devices remain pending. See `deploy/RELAY_2_0_2_VALIDATION_2026-09-06.md`.

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

คู่มือนี้อธิบายสถาปัตยกรรม V2 ที่อยู่ระหว่างทดสอบ ไม่ได้หมายความว่าเซิร์ฟเวอร์ใช้งานจริงเปลี่ยนเป็น V2 แล้ว เฟิร์มแวร์ 2.0.1 ยังถูกระงับการใช้งาน ส่วน 2.0.2 แก้ปัญหาการประมวลผลตารางเวลาแล้ว และผ่านการทดสอบเปิดปิด การตัดเมื่อเปิดนานเกินกำหนด และตัวจับเวลากับฮาร์ดแวร์ทั้งสองรุ่น รีเลย์ออนไลน์ทั้ง 11 เครื่องอัปเกรดทีละเครื่อง คืนสถานะเดิม และผ่านการตรวจสอบร่วมกันในช่วงเวลาทดสอบแล้ว อีกสองเครื่องที่ออฟไลน์มานานยังรอดำเนินการ ดูบันทึกที่ `deploy/RELAY_2_0_2_VALIDATION_2026-09-06.md`

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
