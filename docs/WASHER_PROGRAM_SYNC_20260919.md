# Washer program synchronization / 洗脱仪程序同步 / การซิงค์โปรแกรมเครื่องล้าง

## 中文

- IoT 平台是程序列表的唯一维护入口。设备不编辑或单独删除程序。
- 发布新程序后加入设备列表；修改时使用“创建新版本”，发布后替换同一程序的旧版本。草稿不影响设备。
- 归档最新已发布版本，将该程序从设备列表移除，不恢复更早的版本。平台保留版本记录用于追溯。
- 设备空闲时约每 30 秒检查完整列表。运行中及本地配置界面不替换列表；下一次空闲同步时更新。
- 只有身份验证、完整性校验、程序验证和本地保存均成功，才一次性替换整个列表。
- 断网、超时、鉴权失败、数据不完整或保存失败时，保留原列表。已保存程序断网仍可选择运行。
- 平台明确返回经过验证的空列表时，设备清空列表；网络失败不能视为空列表。
- 不限制为三个程序。屏幕每页显示三个并可翻页；设备仍有有限的 RAM 和 Flash，超过资源预算时整次同步失败，不截断列表。
- 操作员只编制实际工艺步骤；发布时平台自动在开头加入一次安全归零。A 液排尽后可直接注入 B 液，未排液时禁止换液或甩干。
- 更新保留当前选中的程序身份；若该程序已移除，只更新选择，不自动开始其他程序。启动、人工等待后继续仍需在设备上确认。

## English

The company platform owns the full list. Publish to add, create and publish a
new revision to replace, and archive the latest released revision to remove.
Drafts do not change devices and removing a revision never revives an older one.
The idle controller checks roughly every 30 seconds, outside local setup screens.
Authenticated, complete, validated snapshots are persisted before replacing the
local list. Offline, invalid or failed transfers retain existing programs.
An explicitly verified empty snapshot clears the list. Three entries per page
is only pagination, not a three-program limit. Memory and file-size limits cause
whole-update rejection, never silent truncation. Updates never start a run.
Publishing prepends one safe homing step automatically; it is not shown as an
extra editable process step. A drained A fill may be followed by B fill, while
buffer changes and spin drying are rejected if liquid has not been drained.

## ไทย

จัดการรายการโปรแกรมทั้งหมดในแพลตฟอร์มของบริษัท เผยแพร่เพื่อเพิ่มโปรแกรม
สร้างและเผยแพร่รุ่นใหม่เพื่อแทนที่รุ่นเดิม และเก็บรุ่นล่าสุดที่เผยแพร่แล้วเข้าคลัง
เพื่อนำโปรแกรมออกจากเครื่อง ฉบับร่างไม่เปลี่ยนโปรแกรมในเครื่อง
และการนำโปรแกรมออกจะไม่ทำให้รุ่นเก่ากลับมา
เครื่องตรวจรายการประมาณทุก 30 วินาทีเมื่อว่างและไม่ได้อยู่ในหน้าตั้งค่าที่เครื่อง
ต้องตรวจสอบสิทธิ์ ความครบถ้วน ความถูกต้อง และบันทึกสำเร็จก่อนแทนที่รายการทั้งหมด
หากออฟไลน์หรือซิงค์ไม่สำเร็จจะคงโปรแกรมเดิมไว้และยังเลือกใช้งานแบบออฟไลน์ได้
รายการว่างที่ตรวจสอบแล้วเท่านั้นจึงจะล้างรายการในเครื่องได้
สามโปรแกรมต่อหน้าเป็นเพียงการแบ่งหน้า ไม่ใช่จำนวนสูงสุดที่จัดเก็บได้
หากเกินทรัพยากรของเครื่องจะปฏิเสธการอัปเดตทั้งหมด ไม่ตัดรายการบางส่วน
การซิงค์ไม่เริ่มการทำงานเอง ต้องยืนยันที่เครื่องก่อนเริ่มหรือทำงานต่อ

## Validation scope

The final paired USB flash, rc3 darker-blue/light-blue UI and device integration
evidence are recorded in [USB test results](WASHER_USB_TEST_20260919.md).
Physical commissioning remains pending. The catalog API and program editor are
deployed with platform `19.0.2.3.0`.

Candidate firmware: `3.4.0-rc5`. The shared C++ snapshot parser is tested with
eight programs, replacement/addition/deletion, selection identity, empty lists,
duplicate IDs, wrong device identity, invalid revisions and incomplete snapshots.
The host suite also covers startup sequencing and keyboard/pagination touch maps.
The ESP32 build fits the 4 MB/no-PSRAM target. Software validation is not physical
commissioning, production deployment, or evidence of a completed USB flash.

Verified on 2026-09-19:

- imytestth synthetic database `iot_instruments_2031dd5c5ef9`: 100 post-install
  tests, zero failures/errors. This is fresh-install regression, not a rehearsal
  upgrading the production-version database. Artifacts are in
  `/tmp/iot_instruments_2031dd5c5ef9`; production services/data were not changed.
- Local Python core suite: 71 tests passed using the system Python environment.
- Native safety checks: 526; UI checks: 168; heater-panel, washer-setup and
  shared catalog-parser suites passed.
- Four translation catalogs validate (`1028` source terms).
- Final ESP32 build: 54,060 bytes static RAM; application 1,104,965 bytes within
  its 1,769,472-byte OTA slot. Dynamic memory still limits catalog size.
- Built BIN: 1,111,536 bytes, SHA-256
  `b63104d10c71bcf9da2c458d36d1e427775e3dc44a58f3ff3cc5639f311e6559`.
  This application is not a complete first-install USB or SD migration package.
