# IoT Control Center V2 / 使用手册 / คู่มือผู้ใช้

## 中文

### 公司与权限

国家与时区、内网主机、MQTT/OTA 端口及原始记录保留天数都从公司配置读取。保留天数为零时不自动删除；正数表示授权清理超过该天数的样本。“保留完整历史”的探头不参与清理。

IoT 用户只能查看；IoT 操作员可以控制本公司设备；IoT 管理员负责配置、绑定、固件和网络维护。查看权限不再隐含控制权限。

### 温湿度

在“环境 / 网关”先注册网关及公司。二进制网关填写中间件实际看到的来源 IP；JSON 网关填写独立验证令牌。探头按“网关、节点、通道”识别，不同公司相同编号不会自动合并。

为探头填写直观名称和位置，图例保留技术编号用于排查。原始记录不可编辑，采样时的公司和位置不会随探头改名、搬动而重写。曲线支持原始样本、小时均值和每日概览。原始样本超过 10000 条会明确提示缩小范围，不会悄悄截断。

同时选择温度和湿度时，左轴为温度、右轴为相对湿度。小时标签采用日期、24 小时制与时区偏移，避免不同时段重名。趋势图不提供温湿度累加、堆叠或饼图；极值和样本数请在透视统计中查看。

旧版原始记录与均值混存结构不再兼容。正式切换前备份；启用明确的 V2 历史清理标记后，标准升级会清除本模块旧温湿度记录与告警，不清除 HR 考勤或其他业务记录。

### 继电器

“指令下发记录”区分已入队、已发送、设备已确认和过期。网页提交成功不等于设备已经动作。

明确“关闭”会取消延时并锁止自动开启；下一次明确“开启”或“开始延时”才解除锁止。重启与最大开启时长保护也采用安全关闭。紫外灯等设备勾选“安全关键设备”并设置有限的最大连续开启时长。软件不能代替门联锁、急停开关和现场验证。

新固件不内置公司的 Wi-Fi 密码、服务器地址或网络端点。首次配置选择正确硬件型号并填写引导网络参数；之后从控制中心接收公司配置，保存成功后回报配置摘要。已经配置的设备，只有按住实体按钮开机才进入配置入口。

OTA 必须配置可信服务器证书指纹；未配置时拒绝升级，不再跳过 HTTPS 证书校验。主、备用 OTA 地址必须使用受信任的证书。不要在聊天、日志或 Git 中提交密码。

### OpenWrt 与考勤

OpenWrt 首次连接前由管理员核实并安装 SSH 主机密钥。心跳最多并行检查 8 台 AP，单次 SSH 有超时，补传的旧状态不会覆盖较新状态。

考勤在允许的最长班次时长内支持跨午夜匹配，不再受执行任务用户的时区或自然日切换影响。错误提示按当前界面语言展示，技术原始消息保留用于排查。

## English

Configure country, timezone, private routes, OTA certificate trust and retention on the company. Zero retention keeps all raw history; positive retention authorizes expiry deletion, except probes marked to keep full history.

Viewers, operators and managers have separate privileges. Register gateways before ingestion. Binary source IPs must map to known company gateways; JSON gateways require their own token. Probe identities are scoped to gateways.

Raw observations are immutable and keep collection-time company/location snapshots. Use meaningful probe names, then select raw, hourly or daily chart views. Oversized raw requests require narrowing the range or using an aggregate.

When both metrics are selected, temperature uses the left axis and humidity the right. Hour labels include the date, 24-hour time and UTC offset. Cumulative, stacked and pie displays are not offered for these measurements; use the pivot for extrema and sample counts.

Command Delivery distinguishes durable intent, publication and device confirmation. OFF cancels delays and inhibits automatic ON. An explicit ON/start resumes operation. Boot/watchdog cutoff fail closed. Configure finite limits for safety-critical equipment and retain physical interlocks.

Firmware has no company-specific network defaults. Provision the correct hardware profile and bootstrap connection, then apply company settings from the control center. OTA requires a trusted TLS certificate fingerprint. Configured devices enter the setup portal only with the physical boot button held.

OpenWrt requires pre-verified SSH host keys. Heartbeats use bounded concurrency/timeouts and ignore stale replay. Attendance can cross midnight within the allowed shift duration and no longer depends on the background user's timezone.

V2 is a breaking release. Back up first and explicitly authorize removal of old module temperature/humidity observations and alerts. HR attendance and unrelated business data are not part of this reset. Do not upgrade production or real devices on the strength of compilation alone.

## ภาษาไทย

ตั้งค่าประเทศ เขตเวลา เครือข่ายภายใน ใบรับรอง OTA และระยะเวลาเก็บข้อมูลที่บริษัท ค่า 0 หมายถึงเก็บข้อมูลดิบโดยไม่ลบอัตโนมัติ ค่ามากกว่า 0 อนุญาตให้ลบข้อมูลที่เกินระยะเวลาที่กำหนด ยกเว้นเซ็นเซอร์ที่ตั้งให้เก็บประวัติทั้งหมด

แยกสิทธิ์ผู้ดูข้อมูล ผู้ควบคุมอุปกรณ์ และผู้ดูแลระบบ ต้องลงทะเบียนเกตเวย์กับบริษัทก่อนรับข้อมูล ระบุ IP ต้นทางสำหรับเกตเวย์ไบนารี และโทเคนเฉพาะสำหรับเกตเวย์ JSON หมายเลขเซ็นเซอร์ซ้ำกันได้เมื่ออยู่คนละเกตเวย์

ข้อมูลดิบที่บันทึกแล้วแก้ไขไม่ได้ และเก็บบริษัทกับตำแหน่ง ณ เวลาที่อ่านค่า ตั้งชื่อเซ็นเซอร์ให้สื่อถึงอุปกรณ์หรือสถานที่ กราฟเลือกดูข้อมูลดิบ ค่าเฉลี่ยรายชั่วโมง หรือรายวันได้ หากข้อมูลดิบเกิน 10000 รายการ ระบบจะแจ้งให้ลดช่วงเวลาหรือเลือกค่าเฉลี่ย

เมื่อเลือกทั้งสองค่า แกนซ้ายแสดงอุณหภูมิและแกนขวาแสดงความชื้น ป้ายเวลามีวันที่ เวลาแบบ 24 ชั่วโมง และส่วนต่างจาก UTC ไม่ใช้กราฟสะสม กราฟซ้อน หรือกราฟวงกลมกับค่าเหล่านี้ ดูค่าสูงสุด ต่ำสุด และจำนวนตัวอย่างได้ในตาราง Pivot

หน้าประวัติคำสั่งแยกสถานะเข้าคิว ส่งแล้ว และอุปกรณ์ยืนยันแล้ว คำสั่งปิดจะยกเลิกตัวจับเวลาและระงับการเปิดอัตโนมัติ ต้องสั่งเปิดหรือเริ่มจับเวลาใหม่เพื่อกลับมาทำงาน การเริ่มระบบใหม่และการตัดเมื่อเปิดนานเกินกำหนดจะเข้าสู่สถานะปิดอย่างปลอดภัย อุปกรณ์สำคัญด้านความปลอดภัยต้องมีเวลาสูงสุดและระบบตัดทางกายภาพ

เฟิร์มแวร์ไม่ฝังรหัสผ่านหรือที่อยู่เครือข่ายของบริษัท ตั้งค่ารุ่นฮาร์ดแวร์และการเชื่อมต่อเริ่มต้นก่อน จากนั้นรับการตั้งค่าบริษัทจากศูนย์ควบคุม OTA ต้องมีลายนิ้วมือใบรับรอง TLS ที่เชื่อถือได้ อุปกรณ์ที่ตั้งค่าแล้วจะเปิดหน้าตั้งค่าเมื่อกดปุ่มบนตัวอุปกรณ์ขณะเปิดเครื่องเท่านั้น

OpenWrt ต้องตรวจสอบและติดตั้ง SSH host key ก่อนใช้งาน ตรวจสอบพร้อมกันได้ไม่เกิน 8 เครื่องและมีเวลารอสูงสุด ข้อมูลย้อนหลังจะไม่ทับสถานะที่ใหม่กว่า การลงเวลางานรองรับกะข้ามเที่ยงคืนภายในระยะเวลาที่อนุญาต

V2 เปลี่ยนโครงสร้างข้อมูล ต้องสำรองข้อมูลและอนุญาตการลบประวัติอุณหภูมิ/ความชื้นกับการแจ้งเตือนเดิมก่อนอัปเกรด ข้อมูลลงเวลาของ HR และข้อมูลธุรกิจอื่นไม่อยู่ในขอบเขตการลบ ต้องทดสอบในฐานข้อมูลแยกก่อนใช้งานจริง
