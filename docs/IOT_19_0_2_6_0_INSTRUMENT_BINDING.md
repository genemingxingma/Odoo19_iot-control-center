# IoT Control Center 19.0.2.6.0 - Instrument Binding

## English

### Add a heater or washer

1. On the device, open the identity page and record the complete ID. Heater IDs
   start with `HTR-`; washer IDs start with `WSH-`.
2. In IoT Control Center, open **Instruments > Add Instrument by Device ID**.
3. Enter the complete ID, choose the company, name and location, then confirm.
4. Configure Wi-Fi and the platform address on the physical device. The device
   claims only the ID that an operator has already reserved for that company.
5. Confirm that the instrument card shows the expected company, location and
   online state before sending settings or programs.

The firmware does not contain a company, country or fixed private address.
Company ownership is assigned by the platform during binding.

### Heater display

- Main page: operating state, large current temperature and target temperature.
- SW1: full device ID and current IP address.
- SW2: enable or disable local heating permission.
- SW3: saved target temperature.
- Fault page: `ALARM`, the reason and `HEAT OFF`; this page overrides all normal
  pages while a real safety fault is active.

## 中文

### 添加加热器或洗脱仪

1. 在设备上打开设备信息页，记下完整唯一 ID。加热器以 `HTR-` 开头，洗脱仪以
   `WSH-` 开头。
2. 在 IoT 控制中心打开 **仪器 > 按设备 ID 添加仪器**。
3. 输入完整 ID，选择所属公司、名称和位置，然后确认。
4. 在实体设备上配置 Wi-Fi 和平台地址。设备只能认领管理员已经为该公司预留的
   ID。
5. 下发设置或程序前，确认仪器卡片显示的公司、位置和在线状态正确。

固件不写入公司、国家或固定内网地址；设备归属只在平台绑定时确定。

### 加热器屏幕

- 主页面：运行状态、大号当前温度、目标温度。
- SW1：完整设备 ID 和当前 IP 地址。
- SW2：启用或禁用本地加热许可。
- SW3：已保存在设备中的目标温度。
- 故障页面：显示 `ALARM`、原因和 `HEAT OFF`；真实安全故障发生时会覆盖普通页面。

## ภาษาไทย

### เพิ่มเครื่องอุ่นน้ำยาหรือเครื่องล้าง

1. เปิดหน้าข้อมูลอุปกรณ์และจดรหัสทั้งหมด รหัสเครื่องอุ่นน้ำยาขึ้นต้นด้วย `HTR-`
   และรหัสเครื่องล้างขึ้นต้นด้วย `WSH-`
2. ใน IoT Control Center เปิด **Instruments > Add Instrument by Device ID**
3. กรอกรหัสทั้งหมด เลือกบริษัท ชื่อ และตำแหน่ง แล้วกดยืนยัน
4. ตั้งค่า Wi-Fi และที่อยู่แพลตฟอร์มบนอุปกรณ์ อุปกรณ์จะผูกได้เฉพาะรหัสที่ผู้ดูแล
   จองให้บริษัทนั้นไว้ล่วงหน้า
5. ตรวจสอบบริษัท ตำแหน่ง และสถานะออนไลน์บนการ์ดอุปกรณ์ก่อนส่งค่าหรือโปรแกรม

เฟิร์มแวร์ไม่บันทึกบริษัท ประเทศ หรือที่อยู่เครือข่ายภายในแบบตายตัว การเป็นเจ้าของ
อุปกรณ์กำหนดโดยแพลตฟอร์มระหว่างการผูกอุปกรณ์เท่านั้น

### หน้าจอเครื่องอุ่นน้ำยา

- หน้าหลัก: สถานะการทำงาน อุณหภูมิปัจจุบันตัวใหญ่ และอุณหภูมิเป้าหมาย
- SW1: รหัสอุปกรณ์ทั้งหมดและ IP ปัจจุบัน
- SW2: เปิดหรือปิดสิทธิ์ทำความร้อนในเครื่อง
- SW3: อุณหภูมิเป้าหมายที่บันทึกไว้ในอุปกรณ์
- หน้าข้อผิดพลาด: แสดง `ALARM` สาเหตุ และ `HEAT OFF` และจะแทนที่หน้าปกติ
  เมื่อเกิดข้อผิดพลาดด้านความปลอดภัยจริง
