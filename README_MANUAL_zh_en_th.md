# iMyTest IoT Control Center User Manual (中文 | English | ไทย)

## 中文（简体）

### 1. 系统简介
`iMyTest IoT Control Center` 用于在 Odoo 19 中管理两类设备：
1. `Switch`（ESP8266 继电器模块，MQTT）
2. `Environment`（温湿度节点，TCP 网关上报）

支持：多公司、按 ID 绑定、定时控制、分组管理、告警、OTA 升级、趋势分析。

### 2. 安装前置
1. Odoo Python 依赖：`paho-mqtt`、`pytz`
2. MQTT Broker 可达（建议端口 `1883`）
3. 温湿度 TCP 上报端口可达（默认 `9910`）
4. 安装模块：`IoT Control Center`

### 3. 角色权限
1. `IoT User`：查看与日常操作
2. `IoT Manager`：绑定、计划、分组、固件
3. `System Admin`：全部权限

### 4. 菜单
1. `Control Cards`
2. `Switch`
3. `Environment`

### 5. 继电器操作
#### 5.1 按 ID 绑定
1. `Switch -> Bind by ID`
2. 输入 `Switch ID`，点 `Search ID`
3. 校验通过后点 `Confirm Bind`

#### 5.2 开关与延时
1. 在列表/卡片点 `ON/OFF`
2. `Delay` 启动倒计时开，倒计时中再点 `Delay` 取消并关
3. Delay 期间优先级最高，屏蔽普通软件开关和计划动作

#### 5.3 定时计划
1. `Switch -> Schedules`
2. 选择对象（设备/组）、动作、日期、时间
3. 保存后系统自动下发并刷新设备计划

#### 5.4 累积时长
1. `Total ON Hours` 显示累计开启小时
2. 重置时必须填写原因，写入操作记录

### 6. 固件 OTA
1. `Switch -> Firmware Management` 上传 `.bin`
2. 填写版本号保存
3. `Batch Push Upgrade` 选择设备批量下发
4. `Upgrade Logs` 查看结果

### 7. 温湿度操作
#### 7.1 绑定节点
1. `Environment -> Bind Node by ID`
2. 输入 `Node ID`（区分大小写）
3. `Search ID` 后 `Confirm Bind`

#### 7.2 探头分组与阈值覆盖
1. `Environment -> Sensor Groups` 创建分组
2. 设置组温湿度上下限
3. 探头加入组后：组阈值覆盖探头自身阈值
4. 探头界面查看 `Threshold Source` 与 `Effective ...`

#### 7.3 分析与告警
1. `Readings & Analysis` 查看趋势
2. 超限自动生成 `Open` 告警
3. 恢复正常后自动 `Closed`

### 8. 多公司规则
1. 未绑定设备默认不在公司业务中使用
2. 绑定到公司后仅该公司可见可管
3. 解绑后可被其他公司重新绑定

---

## English

### 1. Overview
`iMyTest IoT Control Center` manages:
1. `Switch` devices (ESP8266 relay via MQTT)
2. `Environment` sensors (temperature/humidity via TCP gateway)

Features: multi-company, ID binding, scheduling, grouping, alerts, OTA, trend analytics.

### 2. Prerequisites
1. Python deps in Odoo runtime: `paho-mqtt`, `pytz`
2. Reachable MQTT broker (recommended port `1883`)
3. Reachable TH TCP ingest port (default `9910`)
4. Install module `IoT Control Center`

### 3. Roles
1. `IoT User`: view and daily operations
2. `IoT Manager`: binding, schedules, groups, firmware
3. `System Admin`: full access

### 4. Menus
1. `Control Cards`
2. `Switch`
3. `Environment`

### 5. Switch
#### 5.1 Bind by ID
1. Go to `Switch -> Bind by ID`
2. Enter `Switch ID`, click `Search ID`
3. Click `Confirm Bind` after validation

#### 5.2 ON/OFF and Delay
1. Use `ON/OFF` in list/card view
2. `Delay` turns ON with countdown; click again to cancel and turn OFF
3. Delay mode has top priority over normal switch/schedule actions

#### 5.3 Schedules
1. Open `Switch -> Schedules`
2. Select target (device/group), action, days, time
3. Save to auto-sync full schedule set to devices

#### 5.4 Total ON Hours
1. `Total ON Hours` records cumulative ON duration
2. Reset requires a mandatory reason and logs the operation

### 6. Firmware OTA
1. Upload `.bin` in `Switch -> Firmware Management`
2. Set version and save
3. Use `Batch Push Upgrade` for target devices
4. Check `Upgrade Logs`

### 7. Environment
#### 7.1 Bind node
1. Go to `Environment -> Bind Node by ID`
2. Enter case-sensitive `Node ID`
3. Click `Search ID` then `Confirm Bind`

#### 7.2 Sensor groups and threshold override
1. Create groups in `Environment -> Sensor Groups`
2. Configure group temp/humidity limits
3. Once a sensor is in a group, group thresholds override local sensor thresholds
4. Check `Threshold Source` and `Effective ...` fields on sensor form

#### 7.3 Readings and alerts
1. `Readings & Analysis` for trend lines
2. Out-of-range values create `Open` alerts
3. Alerts auto-close when values return to normal

### 8. Multi-company
1. Unbound devices are not used in company operations
2. Bound devices are visible/controllable only within bound company
3. After unbind, another company can bind them

---

## ภาษาไทย

### 1. ภาพรวม
`iMyTest IoT Control Center` ใช้จัดการ:
1. `Switch` (รีเลย์ ESP8266 ผ่าน MQTT)
2. `Environment` (โหนดอุณหภูมิ/ความชื้นผ่าน TCP Gateway)

รองรับหลายบริษัท, ผูกด้วย ID, ตั้งเวลา, จัดกลุ่ม, แจ้งเตือน, OTA, วิเคราะห์แนวโน้ม

### 2. ข้อกำหนดก่อนใช้งาน
1. Python dependencies: `paho-mqtt`, `pytz`
2. MQTT broker เข้าถึงได้ (แนะนำพอร์ต `1883`)
3. พอร์ต TCP ของ TH Gateway เข้าถึงได้ (ค่าเริ่มต้น `9910`)
4. ติดตั้งโมดูล `IoT Control Center`

### 3. สิทธิ์
1. `IoT User`: ดูข้อมูลและใช้งานทั่วไป
2. `IoT Manager`: ผูกอุปกรณ์, ตั้งเวลา, จัดกลุ่ม, เฟิร์มแวร์
3. `System Admin`: สิทธิ์ทั้งหมด

### 4. เมนูหลัก
1. `Control Cards`
2. `Switch`
3. `Environment`

### 5. การใช้งาน Switch
#### 5.1 ผูกด้วย ID
1. ไปที่ `Switch -> Bind by ID`
2. กรอก `Switch ID` แล้วกด `Search ID`
3. ตรวจสอบผ่านแล้วกด `Confirm Bind`

#### 5.2 ON/OFF และ Delay
1. กด `ON/OFF` จากรายการหรือการ์ด
2. `Delay` จะเปิดรีเลย์พร้อมนับถอยหลัง; กดซ้ำเพื่อยกเลิกและปิด
3. ระหว่าง Delay คำสั่งทั่วไปและตารางเวลาจะถูกบล็อก

#### 5.3 ตารางเวลา
1. ไปที่ `Switch -> Schedules`
2. เลือกเป้าหมาย (อุปกรณ์/กลุ่ม), คำสั่ง, วัน, เวลา
3. บันทึกแล้วระบบซิงก์ตารางทั้งหมดลงอุปกรณ์อัตโนมัติ

#### 5.4 ชั่วโมงทำงานสะสม
1. `Total ON Hours` คือเวลาทำงานสะสม
2. การรีเซ็ตต้องกรอกเหตุผลและระบบจะบันทึก log

### 6. OTA เฟิร์มแวร์
1. อัปโหลด `.bin` ใน `Switch -> Firmware Management`
2. กำหนดเวอร์ชันและบันทึก
3. ใช้ `Batch Push Upgrade` เพื่อส่งแบบกลุ่ม
4. ตรวจสอบผลที่ `Upgrade Logs`

### 7. Environment
#### 7.1 ผูกโหนด
1. ไปที่ `Environment -> Bind Node by ID`
2. กรอก `Node ID` ให้ตรงตัวพิมพ์ใหญ่/เล็ก
3. กด `Search ID` แล้ว `Confirm Bind`

#### 7.2 กลุ่ม Sensor และการ override threshold
1. สร้างกลุ่มที่ `Environment -> Sensor Groups`
2. ตั้งค่าอุณหภูมิ/ความชื้นของกลุ่ม
3. เมื่อ sensor อยู่ในกลุ่ม จะใช้ค่ากลุ่มแทนค่าของ sensor
4. ตรวจสอบได้จาก `Threshold Source` และ `Effective ...`

#### 7.3 กราฟและการแจ้งเตือน
1. `Readings & Analysis` สำหรับกราฟแนวโน้ม
2. เกินช่วงจะสร้างแจ้งเตือน `Open`
3. กลับสู่ปกติแล้วจะปิดแจ้งเตือนอัตโนมัติ

### 8. หลายบริษัท
1. อุปกรณ์ที่ยังไม่ผูก จะไม่ถูกใช้ใน workflow ของบริษัท
2. ผูกแล้วจะเห็นและควบคุมได้เฉพาะบริษัทนั้น
3. เมื่อ unbind แล้ว บริษัทอื่นสามารถ bind ต่อได้
