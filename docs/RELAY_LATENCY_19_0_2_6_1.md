# Relay state feedback, 19.0.2.6.1

## Scope

This patch processes authenticated MQTT receipts in their HTTP transaction,
expedites fresh relay status after durable persistence, and refreshes the native
relay card, list and detail views. The existing command, protection, company and
freshness rules remain unchanged. No device firmware is part of this release.

Live inspection of the user's ON command found a device ON report about one
second after submission, followed by 7.6 seconds before database ingress and
35.3 seconds waiting for the minute-based processor. The browser also lacked
automatic refresh. This was feedback latency, not evidence of failed switching.
Device-reported state does not independently measure load current or contacts.

## 中文

点击 ON 或 OFF 后，请查看“已确认状态”和“命令状态”。命令已发送并不等于
负载已接通；收到设备回报后才确认。继电器卡片、列表和详情页在页面可见、
没有正在编辑内容或打开对话框时，约每两秒刷新一次。网络请求本身也需要时间，
两秒不是完整开关链路的时限。切回页面后会恢复刷新。

如果命令持续等待确认，请检查在线状态、最后联系时间和保护状态，不要连续
重复点击。延时运行、安全保护以及自动开启禁止规则没有被取消。此更新不
自动操作任何继电器，不解除保护，也不更新设备固件。

## English

After choosing ON or OFF, check Confirmed State and Command. A sent command is
not proof that the load is energized; confirmation requires a device report.
Relay cards, lists and detail pages refresh approximately every two seconds
while visible and not being edited, with no open dialog. Network request time
is additional; this is not an end-to-end switching deadline. Refresh resumes
when you return to the page.

If confirmation remains pending, check connection, last contact and protection
status rather than repeatedly clicking. Delay, safety protection and automatic
ON restrictions are unchanged. This update does not switch relays, clear
protection or install device firmware.

## ภาษาไทย

หลังจากกด ON หรือ OFF ให้ตรวจสอบ Confirmed State และ Command การส่งคำสั่งสำเร็จ
ไม่ได้ยืนยันว่าอุปกรณ์ได้รับไฟ ต้องรอข้อมูลยืนยันจากอุปกรณ์ก่อน การ์ด รายการ และหน้า
รายละเอียดของรีเลย์จะรีเฟรชประมาณทุกสองวินาทีเมื่อเปิดดูหน้าอยู่และไม่ได้แก้ไขข้อมูล
หรือเปิดกล่องโต้ตอบ ทั้งนี้ยังมีเวลาในการรับส่งข้อมูลผ่านเครือข่าย จึงไม่ใช่กำหนดเวลา
สูงสุดของการเปิดหรือปิดอุปกรณ์ เมื่อกลับมาที่หน้า ระบบจะรีเฟรชต่อ

หากยังรอการยืนยัน ให้ตรวจสอบการเชื่อมต่อ เวลาติดต่อครั้งล่าสุด และสถานะการป้องกัน
แทนการกดซ้ำหลายครั้ง การทำงานแบบหน่วงเวลา การป้องกัน และข้อจำกัดการเปิดอัตโนมัติ
ยังคงเดิม การอัปเดตนี้ไม่สั่งเปิดหรือปิดรีเลย์ ไม่ปลดการป้องกัน และไม่อัปเดตเฟิร์มแวร์

## Validation Boundary

Use a new synthetic database on imytestth, install the actual old addon, then
upgrade to the exact candidate. Native HTTP tests verify immediate confirmation,
duplicate receipts, retained and older state handling. Bridge tests verify
persistence before fast forwarding, failure retention and duplicate ACKs.
The JavaScript harness verifies refresh cadence, non-overlap and editing guards.
Read-only live telemetry and browser checks do not replace a physical switching
test. Preserve verified database, filestore, addon, bridge and outbox backups.
