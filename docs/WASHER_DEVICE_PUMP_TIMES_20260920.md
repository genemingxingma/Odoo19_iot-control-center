# Washer Device Pump Times

## 中文操作说明

程序只定义“注入 A 液 / 注入 B 液”。每台洗脱仪分别保存 A/B 泵时间，
不会因为下载、更换或删除平台程序而覆盖设备的注液设置。

1. 在洗脱仪停止状态下打开 `Settings`，点击 `Fill Times`。
2. 按实际测定结果分别设置 `Buffer A`、`Buffer B` 的注液秒数，范围 1~300 秒。
   `NOT SET`（0）表示未设置，不会被当作有效注液时间；不能凭范例的旧值 15 秒进行标定。
3. 点击 `SAVE A + B`。保存不启动泵；`CANCEL` 放弃未保存修改。保存后断网、重启仍可使用。
4. 通电后设备会自动归零并让两台排液泵工作 20 秒；没有单独的 Prepare、Initialize、Lock 或 Unlock 按钮。准备完成后选择范例 `General Microarray Demo V2.0`，核对 A/B 时间，再在现场确认启动。程序中的等待步骤不会自动继续。
5. 首次实际注液时确认液量、管路和排液效果。时间控制不是实际流量反馈；更换泵、管路或明显改变液体条件后需要重新确认时间。

平台路径：`IoT > 仪器 > 洗脱仪 > 程序选择与下发`。
“设备上报的注液设置”显示最近上报的 A/B 秒数、设置版本和采样时间。
0 表示未设置，不是泵开启 0 秒。设备离线时，平台显示值可能滞后。
平台的洗脱程序步骤中不再填写注液时间；排液、洗脱和甩干参数仍属于程序。

范例流程：自动归零、注 A、人工确认、洗脱 5 循环、排液 20 秒、注 B、
洗脱 5 循环、排液 20 秒、甩干 30 秒。洗脱每方向 3 秒、1 转/秒；甩干 10 转/秒。
注液过程中开启溢水泵，排液时两泵共同工作，输出强度沿用已确认的原程序值。
这只是学习和调试用范例，不是经过实验验证的洗脱工艺。

### 现场测试与界面说明（3.6.0-rc3）

- 本版是可驱动真实硬件的现场测试固件，不是禁用输出的演示版。`FIELD TEST` 不代表硬件已经验收。
- 每次通电并完成屏幕握手后，设备约等待 10 秒便自动归零并启动两台排液泵 20 秒。上电前须确认转子周围无人触碰、管路正确及接液容器就位。`STOP` 可取消本次上电周期的自动准备；排除问题后应安全断电重启，不存在手动解锁按钮。
- 准备成功后在 `PROGRAMS` 用 `Previous` / `Next` 选择程序，点 `SELECT`，再点 `Review & Start`。`NOT READY` 时先按提示处理，不要反复按启动。
- 运行页显示 `STEP 当前 / 总数`、动作名称、单独的循环计数和本步剩余时间。进度条按步骤数计算，不代表总剩余时间。注液前后定位与结束减速会显示定位/等待停止，而不是误报已完成。
- 人工等待页仍显示当前步骤，不会自动继续。转子停稳后成对放片；首次需确认槽位 1 的装片参考位置。`SET SLOT 1` 只保存当前位置，不转动；位置不正确时不要确认，也不要手动扳转子。
- `NEXT +180` / `NEXT +60` 会实际转动转子。顺序为 1、4、5、2、3、6；按一次后先等待停稳。槽位方块只是位置指示，不能直接点击选位。`CONTINUE` 由操作者确认平衡后执行，设备没有平衡检测或门盖开关。
- `STOP` 是终止本次运行，不是可继续的暂停。故障复位也不启动程序；修正故障后按提示重新开始，必要时安全断电重启以重新执行上电准备。
- Wi-Fi 字段点开即可编辑。键盘确认只更新当前草稿；回到 Wi-Fi 页点击 `SAVE & CONNECT` 才保存并连接，`Cancel Changes` 放弃未保存修改。空密码表示开放网络。
- `Device LAN IP ... (DHCP)` 是路由器自动分配的洗脱仪地址，不是 IoT 服务器地址。`IoT configured` 仅表示已配置平台连接，不能据此认定当前在线；返回主页后恢复程序同步。
- 现场依次核验：归零及排液、A 注液同时溢水排液、人工等待和六槽定位、正反转洗脱、两泵排液、B 注液、甩干同时排液、结束停机、STOP 终止及重启不续跑。可用适合设备的测试液和模拟装片，先不要使用正式实验芯片。
- 当前 A/B 各 10 秒是操作者已存储的设置，不是经过体积标定的结果。首次测试必须核验实际液量与溢水、排液效果；任何异常立即停止，不能仅凭软件显示判定泵实际工作。

软件检查覆盖离线完整范例、人工等待不超时继续、双排液泵联动、停止不续跑及设置保存/取消。机械方向、归零信号、六槽准确性、实际液量和带载甩干仍须现场验收，不能用模拟测试代替。

## คู่มือภาษาไทย

โปรแกรมกำหนดเพียงขั้นตอนเติม A หรือ B โดยเครื่องล้างแต่ละเครื่องเก็บเวลาเติมแยกกัน
การซิงค์ เพิ่ม แก้ไข หรือลบโปรแกรมไม่เปลี่ยนเวลาปั๊มที่บันทึกไว้ในเครื่อง

1. เมื่อเครื่องหยุด ให้เปิด `Settings > Fill Times`
2. ตั้ง `BUFFER A` และ `BUFFER B` ตามเวลาที่วัดจริง ช่วง 1 ถึง 300 วินาที
   `NOT SET` หรือ 0 หมายถึงยังไม่ตั้งค่า ห้ามใช้ค่าเดิม 15 วินาทีจากตัวอย่างแทนการสอบเทียบ
3. กด `SAVE A + B` เพื่อเก็บไว้ในเครื่องโดยไม่เปิดปั๊ม ค่าใช้ได้แม้ออฟไลน์หรือเริ่มเครื่องใหม่
   กด `CANCEL` เพื่อทิ้งค่าที่ยังไม่บันทึก
4. หลังเปิดเครื่อง ระบบจะหาตำแหน่งอ้างอิงและเปิดปั๊มระบายทั้งสองตัว 20 วินาทีโดยอัตโนมัติ ไม่มีปุ่ม Prepare, Initialize, Lock หรือ Unlock จากนั้นเลือก `General Microarray Demo V2.0` ตรวจเวลา A/B แล้วจึงยืนยันเริ่มที่เครื่อง
5. ตรวจปริมาณน้ำยาจริงและการระบายในการทดสอบครั้งแรก ต้องตรวจเวลาใหม่เมื่อเปลี่ยนปั๊มหรือท่อ

ที่แพลตฟอร์ม เปิด IoT > เครื่องมือ > เครื่องล้าง > เลือกและซิงค์โปรแกรม
ค่าปั๊มเป็นข้อมูลล่าสุดที่เครื่องรายงาน พร้อมรุ่นการตั้งค่าและเวลาเก็บค่า ไม่ใช่ค่าที่ส่งจากโปรแกรม
ข้อมูลขณะออฟไลน์อาจไม่เป็นปัจจุบัน ขั้นตอนเติมไม่ต้องระบุเวลาในโปรแกรมอีกต่อไป
ขั้นตอนรอผู้ปฏิบัติงานต้องกด CONTINUE ที่เครื่อง ตัวอย่างนี้ใช้เพื่อเรียนรู้และทดสอบเท่านั้น

### การทดสอบที่เครื่องและหน้าจอรุ่น 3.6.0-rc3

- เป็นเฟิร์มแวร์ทดสอบที่สั่งมอเตอร์และปั๊มจริงได้ `FIELD TEST` ไม่ได้หมายถึงผ่านการตรวจรับฮาร์ดแวร์แล้ว
- หลังหน้าจอเชื่อมต่อ ระบบรอประมาณ 10 วินาทีแล้วหาตำแหน่งอ้างอิงและเปิดปั๊มระบายทั้งสองตัว 20 วินาทีโดยอัตโนมัติ ตรวจมือ ท่อ และภาชนะรับก่อนเปิดเครื่อง กด `STOP` เพื่อยกเลิกการเตรียมในรอบเปิดเครื่องนั้น และแก้ปัญหาก่อนปิดแล้วเปิดใหม่อย่างปลอดภัย
- เลือกโปรแกรมใน `PROGRAMS` ด้วย `Previous` / `Next` แล้วกด `SELECT` และ `Review & Start` หากแสดง `NOT READY` ให้แก้ตามข้อความก่อน
- ขณะทำงานจะแสดงเลขขั้นตอน ชื่อขั้นตอน รอบการล้าง และเวลาที่เหลือแยกกัน แถบความคืบหน้าคิดตามจำนวนขั้นตอน ไม่ใช่เวลารวมที่เหลือ
- หน้ารอใส่สไลด์แสดงขั้นตอนปัจจุบันและไม่ทำต่อเอง `SET SLOT 1` บันทึกตำแหน่งที่หยุดอยู่โดยไม่หมุน อย่ายืนยันถ้าตำแหน่งไม่ถูกต้องและอย่าฝืนหมุนด้วยมือ
- `NEXT +180` / `NEXT +60` หมุนจริงตามลำดับช่อง 1, 4, 5, 2, 3, 6 รอให้หยุดก่อนใส่สไลด์เป็นคู่ตรงข้าม ช่องบนจอเป็นตัวบอกตำแหน่ง ไม่ใช่ปุ่มเลือกช่อง ตรวจสมดุลก่อนกด `CONTINUE` เครื่องไม่มีตัวตรวจสมดุลหรือสวิตช์ฝาครอบ
- `STOP` ยุติรอบ ไม่ใช่การพักที่ทำต่อได้ การรีเซ็ตข้อผิดพลาดไม่เริ่มรอบใหม่ หากจำเป็นให้ปิดแล้วเปิดเครื่องใหม่อย่างปลอดภัยเพื่อเตรียมเครื่องอีกครั้ง
- Wi-Fi: การยืนยันบนแป้นพิมพ์แก้เฉพาะค่าร่าง กด `SAVE & CONNECT` เพื่อบันทึกและเชื่อมต่อจริง หรือ `Cancel Changes` เพื่อยกเลิก รหัสผ่านว่างหมายถึงเครือข่ายเปิด
- `Device LAN IP ... (DHCP)` เป็น IP ของเครื่องที่เราเตอร์แจก ไม่ใช่ IP เซิร์ฟเวอร์ `IoT configured` หมายถึงตั้งค่าไว้แล้ว ไม่ยืนยันว่าออนไลน์ขณะนั้น กลับหน้าหลักเพื่อซิงค์โปรแกรม
- ทดสอบกลับตำแหน่งและระบาย เติม A พร้อมปั๊มน้ำล้น รอและจัดตำแหน่งหกช่อง ล้างสองทิศ ระบายสองปั๊ม เติม B ปั่นแห้งพร้อมระบาย จบงาน STOP และเปิดใหม่โดยไม่ทำรอบเดิมต่อ ใช้น้ำยาทดสอบที่เหมาะสมและสไลด์จำลองก่อนใช้งานจริง
- ค่า A/B ปัจจุบันอย่างละ 10 วินาทีเป็นค่าที่ผู้ใช้บันทึก ไม่ใช่ผลสอบเทียบปริมาตร ต้องตรวจปริมาณ ทิศทางมอเตอร์ ตำแหน่งช่อง และการระบายจริง การทดสอบซอฟต์แวร์ไม่แทนการตรวจรับเครื่อง

## Contract And Verification

- Recipe schema 2 omits `duration_s` for Fill A/B. Exchange/catalog envelopes remain version 1; the heater protocol is unchanged.
- Recipe schema 1 is readable for migration but cannot start on the new washer firmware. Publish/sync a new revision; do not silently reinterpret legacy timings.
- Local settings are atomically saved in `/pump-timing.json` with a monotonically increasing revision. Missing/invalid settings do not acquire guessed defaults.
- A run resolves an independent execution copy before starting. The canonical catalog is not modified. Used pump settings are retained in run events and the power-loss marker.
- Runtime checks reject unconfigured required pumps, invalid durations and attempts to start unresolved templates. Settings cannot be edited during a run, startup preparation or rotor motion.
- Installed pair: firmware `3.6.0-rc3`, build marker `30603`, plus the native V4 RC3 TFT. They were installed and hash-verified together on 2026-09-22.
- Pre-rc1 backup: `D:/Codex/device_backups/washer_20260920_095144`. Application, preserved prefix, second application slot and filesystem verified after flashing rc1. rc2 adds persistent visibility of start-rejection messages on the review page.
- Pre-rc2 backup: `D:/Codex/device_backups/washer_20260920_100227`; full backup and all app/preserved-region checks passed. The boot diagnostics confirm rc2, settings unset, screen/network healthy, and no active outputs.
- The TJC interface is English-only and uses native pages. RC3 changes both the HMI and controller application, so both artifacts must be updated as a matched pair.
- Physical liquid-volume calibration and motor/pump acceptance remain operator tasks. Software tests and successful flashing do not certify them.

## Release Evidence

- Platform `19.0.2.5.0` deployed on imytestth from archive SHA-256 `eb65a88cd17fbc5ea40681d4ca56df32b8643eaa604299f293eadd6076e82b0d`.
- Final upgrade rehearsal: `iot_instruments_upgrade_20260920025858`, 107 Odoo tests passed. Local suites: 73 Python tests, 530 control checks, 185 UI checks, plus setup/catalog/pump/heater tests; both MCU targets compiled.
- English, Chinese and Thai UI checks passed at 1920, 1440, 1366 and 390 px. Fill-time table cells contain no value or editor; drainage time remains visible. Real synthetic-interface captures are retained in `docs/images/iot-2.5.0-*-washer-pumps.png`.
- Production backup: `/opt/odoo/module_backups/iot_instruments_production_20260920_030914`. Database, filestore, addon and bridge backups verified. Twenty protected tables unchanged during upgrade; zero new relay commands and zero ingest errors in the release check.
- Demo revision 3 uses schema 2, label `General Microarray Demo V2.0`; revision 1 archived, existing revision 2 draft unchanged. No device command was created by this publication.
- Actual USB diagnostics and platform feedback both confirm catalog SHA-256 `609f2ba83aaef6de50d6a0712226459556b404809bf3f3e93f5689489901047f` and selected revision 3.
- After local screen interaction, the device reported A=10 s, B=10 s, settings revision 2. These are observed device settings, not values supplied by the demo or a claim of measured volume calibration.
- A subsequent reboot restored demo revision 3 and both 10-second settings before any catalog HTTP response (`catalog_http_status=0`), then received HTTP 304 for the same catalog. Outputs remained off. Receipt: `deploy/artifacts/washer-field-test-boot-20260920-101625.json`.
- Final rc2 observation: 84 samples across 178.092 seconds, one boot, all outputs off. No automatic initialization or arming occurred.
- Chinese and Thai instructions published internally in Odoo Knowledge articles 1186 and 1187 with verified private screenshot attachments. They are not public website articles.
