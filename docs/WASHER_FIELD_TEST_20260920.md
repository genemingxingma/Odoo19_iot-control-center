# Washer field-test handoff, 2026-09-20

## Status and scope

Historical rc8 handoff below. Superseded for pump timing by
`WASHER_DEVICE_PUMP_TIMES_20260920.md` and firmware 3.5.0-rc2.

Latest requirement, received during handoff: A/B injection durations should be
per-device settings, while programs specify only the injection action. This is
not yet implemented in rc8: it still executes the published step duration.
Do not treat the sample's 15-second fills as calibrated values or begin fluid
acceptance on that assumption. See the pending design below.

This replaces the rc5 output-locked handoff for the connected washer only.
The application is real actuator-control firmware, not a simulated run. Physical
acceptance is still pending. The device stores `field_test=true` and
`commissioned=false`; successful USB flashing must not certify its mechanics.

Initial live diagnostics confirmed rc5, no platform configuration, no stored
programs and commissioning disabled. That combination prevented any run.
The authorized upgrade preserves the English TJC screen and original motor/PWM
baseline, binds the existing production device identity over verified HTTPS, and
lets the controller synchronize its catalog directly from imytestth. No temporary
PC proxy or simulated program report is used. Existing published/draft programs
are not edited by this handoff.

An intermediate rc6 exposed a CPU0 idle-task watchdog reset during direct TLS
communication. rc7 schedules the network worker at idle priority on CPU0, reserves
12 KiB for its stack, checks task creation, and permits a bounded 12-second TLS
handshake. The original 3-second loop watchdog remains enabled. Motion and screen
handling stay on the application core. See the official description of
[idle-task starvation and the task watchdog](https://docs.espressif.com/projects/esp-idf/en/v4.3/esp32/api-reference/system/wdts.html).

rc8 also removes network-in-flight as a gate for local initialization, paces
exchanges from completion, and gives faults priority over the field-test label.
The host suite now explicitly checks the local initialization readiness guards.

## Firmware and recovery

- Version: `3.4.0-rc8`, signed-package version number `30406`.
- Application: 1,117,040 bytes, SHA-256
  `1e27ae6dc2b93fe954e212085ee9f013505031c15d3d51aaadf488e15bceffa5`.
- Original rc5 4 MB backup, before any writes:
  `D:/Codex/device_backups/washer_20260920_090657`.
- Backup before the rc7 application-only update:
  `D:/Codex/device_backups/washer_20260920_092210`.
- Backup before the final rc8 application-only update:
  `D:/Codex/device_backups/washer_20260920_093248`.
- All full backups were verified against flash. The application and provisioned
  filesystem were verified after writing. Both application-only updates verified
  that bootloader/partition/NVS and the entire second slot/filesystem were unchanged.
- Backups/configuration contain credentials and remain in ACL-restricted storage,
  outside Git. Do not distribute a full-flash or filesystem image as a generic BIN.
- `tools/update_washer_usb_app.py` performs a guarded forward application update
  only when its backup, expected MAC, app hash, partition layout and OTA state match.
- The TFT remains the rc5 English/Verdana screen resource. These layouts are drawn
  by the ESP32, so a second screen flash is not required.

## Test procedure / 中文

新增需求尚未包含在 rc8：A/B 注液目前仍读取程序步骤时长，暂不进行带液
验收。下列流程保留作机械与界面测试参考，不能把范例的 15 秒当作已标定值。

先确认排液管接入废液容器，转子无松动物品，手和衣物远离转子。
首次测试使用清水与空载转子，不直接用于正式样本。先核对驱动输出、
归零方向和停止响应，再验证流量、装片定位与配平甩干。

1. 控制器启动后显示 `FIELD TEST`。它不会自动归零、排液或启动程序；
   断电重启也不会保留本次动作许可。
2. 完成接线和工作区域检查后恢复电机、泵工作电源。先进入
   `DEVICE CARE / WI-FI > INITIALIZE > CONFIRM`，在现场观察归零与两台
   排液泵的 20 秒排液。方向、接管或行为不对时立即 `STOP` 并切断工作电源。
3. 初始化完成后在 `PROGRAMS` 选择程序，再按 `USE PROGRAM`。
   返回首页后按 `REVIEW / START > CONFIRM START` 才开始运行。
4. 范例中 A 液注入 15 秒，等待人工确认；A/B 洗脱分别 5 循环、每方向
   3 秒；每次排液 20 秒，最后甩干 30 秒。它只是学习范例，不是经液量或
   工艺验证的生产程序。甩干沿用原值 10 转/秒，必须先完成空载与配平检查。
5. 初次暂停装片时，若显示 `SET SLOT 1`，先目视确认当前停止位置确实为
   1 号装片位，再点该按钮并 `CONFIRM`。该操作只保存当前位置，不转动。
   不要手动扭转转子来凑零位；如果位置不对，停止并重新标定，不要虚假确认。
6. 保存后按 `NEXT +180`、`NEXT +60` 交替定位，按对侧成对装片。
   每次点击会完成整段转角，松手不会停止。等转子停稳后再放入芯片。
   暂停不会自动继续；确认配平后另按 `CONTINUE`。
7. `STOP` 中止运行，并撤销本次现场测试动作许可。重新运行前要重新初始化。
   软件停止不等于瞬间机械制动，不能替代独立断电/急停。

温度只显示和记录，不控制加热。程序同步不会自动启动设备。
已保存程序可以离线使用；平台同步失败不会清空本地程序。

## ขั้นตอนทดสอบ / ไทย

ข้อกำหนดใหม่เรื่องเวลาเติม A/B แยกตามเครื่องยังไม่รวมใน rc8 รุ่นนี้ยังอ่านเวลา
จากโปรแกรม จึงยังไม่ควรตรวจรับการเติมของเหลวโดยถือว่าเวลา 15 วินาทีผ่านการสอบเทียบแล้ว

ใช้โรเตอร์เปล่าและน้ำสะอาดในการทดสอบครั้งแรก ต่อท่อน้ำทิ้งเข้าภาชนะให้เรียบร้อย
ตรวจทิศทางการหมุน การหยุด และการต่อปั๊มก่อนใช้ตัวอย่างจริง เครื่องเป็นแบบเปิด
ต้องนำมือ เสื้อผ้า และสิ่งของออกจากบริเวณโรเตอร์ก่อนสั่งเคลื่อนที่

1. หลังเปิดเครื่อง หน้าจอแสดง `FIELD TEST` และไม่เริ่มหมุนหรือระบายของเหลวเอง
   การเปิดเครื่องใหม่จะไม่จดจำการอนุญาตให้เคลื่อนที่จากครั้งก่อน
2. หลังตรวจสายและพื้นที่ทำงานแล้ว ให้จ่ายไฟส่วนมอเตอร์และปั๊ม จากนั้นเลือก
   `DEVICE CARE / WI-FI > INITIALIZE > CONFIRM` เพื่อหาตำแหน่งอ้างอิง
   และระบายของเหลวด้วยปั๊มทั้งสองเป็นเวลา 20 วินาที หากทิศทางหรือการทำงานผิด
   ให้กด `STOP` และตัดไฟภาคกำลังทันที
3. เลือกโปรแกรมใน `PROGRAMS` แล้วกด `USE PROGRAM` จากนั้นเลือก
   `REVIEW / START > CONFIRM START` โปรแกรมตัวอย่างยังไม่ผ่านการตรวจรับ
   ปริมาตรของเหลวหรือกระบวนการสำหรับงานจริง
4. เมื่อถึงขั้นตอนรอใส่สไลด์ หากแสดง `SET SLOT 1` ให้ตรวจว่าช่องที่ 1 อยู่ตรง
   ตำแหน่งใส่สไลด์จริง แล้วกดปุ่มและ `CONFIRM` เพื่อบันทึกโดยไม่เคลื่อนที่
   ห้ามหมุนโรเตอร์ด้วยมือเพื่อชดเชยตำแหน่ง หากไม่ตรงให้หยุดและสอบเทียบใหม่
5. ใช้ `NEXT +180` และ `NEXT +60` สลับกัน ใส่สไลด์เป็นคู่ตรงข้าม
   รอให้หยุดสนิทก่อนใส่สไลด์ ตรวจสมดุลแล้วจึงกด `CONTINUE`
6. `STOP` ยกเลิกการทำงานและการอนุญาตทดสอบครั้งนั้น ต้อง Initialize ใหม่ก่อน
   เริ่มอีกครั้ง การหยุดด้วยซอฟต์แวร์ไม่ใช่เบรกฉุกเฉินทางกล

ค่าความเร็วและ PWM อ้างอิงโปรแกรมเดิม การปั่นแห้งใช้ 10 รอบต่อวินาที
จึงต้องตรวจเครื่องเปล่าและสมดุลก่อน โปรแกรมที่บันทึกแล้วใช้งานออฟไลน์ได้
การซิงค์โปรแกรมไม่สั่งให้เครื่องเริ่มทำงานเอง

## Verification boundary

Host checks: 530 control assertions, 174 UI assertions, setup/catalog/heater-panel
suites, and 71 Python core tests passed. Cross-compilation passed; the existing
third-party OneWire warnings were not introduced by this change.

USB diagnostics confirmed direct catalog HTTP 200, the released example program
stored on the actual device, healthy screen/storage/probe, and all motor/pump
output indications off. This is not an electrical measurement of driver polarity
or verification of pump plumbing, home offset, delivered volume, braking distance,
loaded balance, or OTA/SD installation. Those remain onsite acceptance items.

The rc7 direct-network observation collected 85 samples over 178.218 seconds
with one boot ID, zero indicated outputs, matching catalog digest, and HTTP
200/304. A deliberate reboot restored the program before the first catalog
response. rc8 was then flashed and verified; its boot receipt likewise shows
local program restoration before HTTP and a subsequent 304 confirmation.
No local initialization/start or pump/motor motion was triggered by these checks.

## Pending per-device injection timing

- Store independently calibrated A/B durations in the device's nonvolatile
  configuration, not compiled constants. Touchscreen setup is equipment
  calibration, distinct from editing washing programs.
- A published program calls Fill A or Fill B without a duration. Keep washing,
  waiting, spin and existing drain semantics unchanged unless separately requested.
- Validate bounds and configuration integrity. Require the needed channel to be
  configured before starting; never silently use legacy/default injection time.
- Snapshot the selected timing profile at run start and log its revision plus
  applied durations, so later calibration cannot alter an active run.
- Introduce explicit protocol/capability compatibility, migrate program revisions
  deliberately, and test platform/firmware together. Old firmware must not guess
  how to execute a new action-only fill, nor reinterpret an old timed program.
- This proposal assumes a standard fill quantity for each liquid across programs.
  If different programs require different volumes, keep volume in the program
  and pump calibration on the device instead of reintroducing pump-specific time.
