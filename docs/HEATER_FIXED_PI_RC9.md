# Heater fixed PI candidate 3.2.0-rc9

## Control / 控温 / การควบคุม

The heater uses fixed PI time-proportioning, not voltage adjustment: Kp=20 percent/C,
Ki=20/600 percent/(C*s), a 1 second control interval and a 2 second SSR window.
These constants are not operator settings. The SSR still switches fully ON/OFF;
the ratio changes average thermal power. No derivative term or volume setting is required.

加热器采用固定 PI 时间比例控温，不调节输出电压。每秒计算一次，在两秒窗口内
控制固态继电器通断比例；不增加 PID 参数或液体体积设置。默认 42 摄氏度，
网络下发的目标温度继续持久保存。达到目标加 1 摄氏度时停止输出。

เครื่องทำความร้อนใช้ PI แบบค่าคงที่ คำนวณทุก 1 วินาที และควบคุมสัดส่วนเวลาเปิด SSR
ในช่วง 2 วินาที ไม่ใช่การปรับแรงดัน ไม่มีพารามิเตอร์ PI ให้ผู้ใช้ปรับ
ค่าเริ่มต้น 42 องศาเซลเซียส และบันทึกค่าอุณหภูมิที่ได้รับจากระบบไว้ในเครื่อง

## Protection / 保护 / การป้องกัน

Anti-windup limits the integrator; OFF, target changes and faults reset control.
Blocking network/storage work switches the output OFF before proceeding and does
not integrate its elapsed time. Sensor validity, over-temperature, watchdog,
latched fault and local-enable checks are retained.

Below the target's 1 C holding band, the no-rise check counts actual SSR ON time:
10 accumulated powered minutes with less than 1 C rise stops heating and alarms.
It does not incorrectly alarm at a stable holding temperature. This is a response
check, not proof that the bucket contains liquid or an independent thermal cutoff.

低于目标的恒温区间时，累计实际加热十分钟、升温小于一摄氏度将停止加热并报警。
恒温阶段不要求持续升温。探头断线、超温和看门狗保护保留，不替代独立过温断电保护。
温度记录仍每小时生成，离线仅保留有界缓存，上线确认接收后删除。

เมื่อต่ำกว่าช่วงรักษาอุณหภูมิ หากเปิด SSR สะสมครบ 10 นาที แต่อุณหภูมิเพิ่มน้อยกว่า
1 องศาเซลเซียส เครื่องจะหยุดทำความร้อนและแจ้งเตือน การตรวจนี้ไม่แทนอุปกรณ์ตัดไฟเมื่อร้อนเกิน
และไม่ใช่หลักฐานว่ามีของเหลวในถัง

## Candidate Evidence

Local Python contract/OTA tests, native C++ safety/UI tests, and both heater/washer
builds passed. Synthetic 2 L, 5 L and variable-volume models stayed within 41-43 C
after settling; those model results are not measured physical performance.

Application size: 483248 bytes. SHA256:
`988187c046a3bd424fa15e2f04f7501ef07be29511076f10d645605f0b60d627`.

This is NOT a legacy migration package. No device was flashed by these build tests.
An original-firmware heater still requires its exact identity, storage-layout
evidence, reviewed configuration migration and a separately authorized release.
The production platform already accepts these diagnostic fields without an addon
upgrade. Do not place this application in the legacy HTTP download service.
