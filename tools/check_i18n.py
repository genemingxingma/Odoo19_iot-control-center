#!/usr/bin/env python3
"""Synchronize and validate the module's user-facing translation catalogs."""

from __future__ import annotations

import argparse
import ast
import re
from pathlib import Path
from xml.etree import ElementTree as ET

import polib


ROOT = Path(__file__).resolve().parents[1]
I18N = ROOT / "i18n"
CATALOGS = ("en_US.po", "zh_CN.po", "th.po", "th_TH.po")
SUSPICIOUS_MARKERS = ("???", "Ã", "Â", "�", "â€", "à¸", "à¹", "ðŸ")
PLACEHOLDER_RE = re.compile(
    r"%(?:\([^)]+\))?[#0 +\-]?(?:\d+|\*)?(?:\.\d+|\.\*)?[diouxXeEfFgGcrs%]|\{[^{}]+\}"
)
SOURCE_TERM_RENAMES = {
    "Ap": "AP",
    "Ip Address": "IP Address",
    "Mac Address": "MAC Address",
    "Remote Ip": "Remote IP",
    "Ssh Port": "SSH Port",
    "Ssh User": "SSH User",
    "Switch Id Display": "Switch ID",
    "Tcp Token": "TCP Token",
}


# Terms absent from older catalogs plus wording overrides found during review.
# Each value is (Simplified Chinese, Thai).
TRANSLATIONS = {
    "192.168.10.15": ("192.168.10.15", "192.168.10.15"),
    "192.168.10.50, 192.168.10.51": ("192.168.10.50, 192.168.10.51", "192.168.10.50, 192.168.10.51"),
    "2.4 GHz SSID Count": ("2.4 GHz SSID 数量", "จำนวน SSID ย่าน 2.4 GHz"),
    "5 GHz SSID Count": ("5 GHz SSID 数量", "จำนวน SSID ย่าน 5 GHz"),
    "Active MQTT Host": ("当前 MQTT 主机", "โฮสต์ MQTT ที่ใช้งานอยู่"),
    "ADMS HTTP URL": ("ADMS HTTP 地址", "URL HTTP ของ ADMS"),
    "ADMS HTTPS URL": ("ADMS HTTPS 地址", "URL HTTPS ของ ADMS"),
    "ADMS Last Payload": ("ADMS 最近数据", "ข้อมูลล่าสุดจาก ADMS"),
    "ADMS Last Seen": ("ADMS 最近在线时间", "เวลาที่พบ ADMS ล่าสุด"),
    "Add this public key manually to each OpenWrt AP's authorized_keys file, then bind the AP in IoT Control Center.": (
        "请将此公钥手动添加到每台 OpenWrt AP 的 authorized_keys 文件中，然后在 IoT 控制中心绑定该 AP。",
        "เพิ่ม public key นี้ลงในไฟล์ authorized_keys ของ OpenWrt AP แต่ละตัวด้วยตนเอง แล้วเชื่อมโยง AP ในศูนย์ควบคุม IoT",
    ),
    "All matched sensors are offline. Please wait for fresh data before binding.": (
        "所有匹配的探头均已离线，请等待收到最新数据后再绑定。",
        "เซ็นเซอร์ที่ตรงกันทั้งหมดออฟไลน์ โปรดรอข้อมูลล่าสุดก่อนเชื่อมโยง",
    ),
    "Connection successful. Sample records fetched: %s": (
        "连接成功，已获取记录数：%s",
        "เชื่อมต่อสำเร็จ ดึงข้อมูลตัวอย่างได้: %s",
    ),
    "Full Probe Every N Heartbeats": (
        "每 N 次心跳进行完整检测",
        "ตรวจสอบเต็มรูปแบบทุก N heartbeat",
    ),
    "If enabled, this node keeps all raw readings and skips historical daily rollup.": (
        "启用后，该节点将保留全部原始监测数据，不再执行历史数据的每日汇总。",
        "หากเปิดใช้ โหนดนี้จะเก็บค่าดิบทั้งหมดและข้ามการสรุปรายวันย้อนหลัง",
    ),
    "IoT TH - Rollup Old Readings": (
        "IoT 温湿度 - 汇总历史监测数据",
        "IoT อุณหภูมิ/ความชื้น - สรุปค่าที่อ่านเก่า",
    ),
    "Matched Sensors": ("匹配的探头", "เซ็นเซอร์ที่ตรงกัน"),
    "No sensor found for this Node ID.": (
        "未找到此节点 ID 对应的探头。",
        "ไม่พบเซ็นเซอร์สำหรับ Node ID นี้",
    ),
    "Statistics Window Hours": ("统计时段（小时）", "ช่วงเวลาสถิติ (ชั่วโมง)"),
    "Bind by ID": ("按 ID 绑定", "เชื่อมโยงด้วย ID"),
    "Bind Node": ("绑定节点", "เชื่อมโยงโหนด"),
    "Bind Node by ID": ("按 ID 绑定节点", "เชื่อมโยงโหนดด้วย ID"),
    "Bind Success": ("绑定成功", "เชื่อมโยงสำเร็จ"),
    "Bind Switch by ID": ("按 ID 绑定开关", "เชื่อมโยงสวิตช์ด้วย ID"),
    "Confirm Bind": ("确认绑定", "ยืนยันการเชื่อมโยง"),
    "Failed to bind node.": ("绑定节点失败。", "เชื่อมโยงโหนดไม่สำเร็จ"),
    "Failed to bind switch.": ("绑定开关失败。", "เชื่อมโยงสวิตช์ไม่สำเร็จ"),
    "Found switch %s. Click Confirm Bind to continue.": (
        "已找到开关 %s，请点击“确认绑定”继续。",
        "พบสวิตช์ %s แล้ว คลิก \"ยืนยันการเชื่อมโยง\" เพื่อดำเนินการต่อ",
    ),
    "No available company for binding.": ("没有可绑定的公司。", "ไม่มีบริษัทที่พร้อมให้เชื่อมโยง"),
    "Node %s is now bound to %s. You can bind next one now.": (
        "节点 %s 已绑定到 %s，现在可以继续绑定下一个。",
        "เชื่อมโยงโหนด %s กับ %s แล้ว คุณสามารถเชื่อมโยงตัวถัดไปได้ทันที",
    ),
    "Node is offline. Please wait for fresh data before binding.": (
        "节点已离线，请等待收到最新数据后再绑定。",
        "โหนดออฟไลน์ โปรดรอข้อมูลล่าสุดก่อนเชื่อมโยง",
    ),
    "IoT - Purge Stale Unbound Devices": (
        "IoT - 清理过期未绑定设备",
        "IoT - ล้างอุปกรณ์ที่หมดอายุและไม่ได้เชื่อมโยง",
    ),
    "Search ID": ("查询 ID", "ค้นหาด้วย ID"),
    "Search Switch ID": ("查询开关 ID", "ค้นหาสวิตช์ด้วย ID"),
    "Switch %s bound successfully. You can bind next one now.": (
        "开关 %s 已绑定，现在可以继续绑定下一个。",
        "เชื่อมโยงสวิตช์ %s สำเร็จแล้ว คุณสามารถเชื่อมโยงตัวถัดไปได้ทันที",
    ),
    "This node is already bound to another company.": (
        "此节点已绑定到其他公司。",
        "โหนดนี้เชื่อมโยงกับบริษัทอื่นแล้ว",
    ),
    "This switch is already bound to company: %s": (
        "此开关已绑定到公司：%s",
        "สวิตช์นี้เชื่อมโยงกับบริษัท %s แล้ว",
    ),
    "Unbind": ("解除绑定", "ยกเลิกการเชื่อมโยง"),
    "Unbound Device Retention (days)": (
        "未绑定设备保留时间（天）",
        "ระยะเวลาเก็บอุปกรณ์ที่ยังไม่ได้เชื่อมโยง (วัน)",
    ),
    "You can only bind to companies you can access.": (
        "只能绑定到您有权访问的公司。",
        "คุณสามารถเชื่อมโยงได้เฉพาะบริษัทที่คุณมีสิทธิ์เข้าถึงเท่านั้น",
    ),
    "A full OpenWrt probe runs every N heartbeat cycles to refresh version and hardware facts.": (
        "每 N 次心跳周期执行一次完整的 OpenWrt 检测，以刷新版本和硬件信息。",
        "ระบบจะตรวจสอบ OpenWrt แบบเต็มทุก N รอบ heartbeat เพื่ออัปเดตเวอร์ชันและข้อมูลฮาร์ดแวร์",
    ),
    "Accumulated ON (Hours):": ("累计开启时间（小时）：", "เวลาเปิดสะสม (ชั่วโมง):"),
    "Adms Http Url": ("ADMS HTTP 地址", "URL HTTP ของ ADMS"),
    "Adms Https Url": ("ADMS HTTPS 地址", "URL HTTPS ของ ADMS"),
    "Adms Last Payload": ("ADMS 最近数据", "ข้อมูล ADMS ล่าสุด"),
    "Adms Last Seen At": ("ADMS 最近在线时间", "เวลาที่พบ ADMS ล่าสุด"),
    "After this many consecutive heartbeat failures, the AP is marked offline.": (
        "连续心跳失败达到此次数后，AP 将标记为离线。",
        "AP จะถูกระบุว่าออฟไลน์เมื่อ heartbeat ล้มเหลวติดต่อกันครบจำนวนนี้",
    ),
    "Attendance Heartbeat Log Interval (seconds)": ("考勤心跳日志间隔（秒）", "ช่วงเวลาบันทึก heartbeat ของเครื่องลงเวลา (วินาที)"),
    "Attendance Source IP Allowlist": ("考勤来源 IP 白名单", "รายการ IP ต้นทางที่อนุญาตสำหรับเครื่องลงเวลา"),
    "Bind TH Node/Sensor Channel by ID": ("按 ID 绑定温湿度节点/探头通道", "เชื่อมโยงโหนด/ช่องเซ็นเซอร์อุณหภูมิและความชื้นด้วย ID"),
    "Board Name": ("控制板名称", "ชื่อบอร์ดควบคุม"),
    "Candidate Count": ("匹配数量", "จำนวนรายการที่ตรงกัน"),
    "Chart Label": ("图例名称", "ชื่อที่แสดงในคำอธิบายกราฟ"),
    "Chart Legend Label": ("图例名称", "ชื่อที่แสดงในคำอธิบายกราฟ"),
    "Checksum Sha256": ("SHA-256 校验值", "ค่า checksum SHA-256"),
    "Client Count Total": ("客户端总数", "จำนวนไคลเอนต์ทั้งหมด"),
    "Comma-separated ADMS source IP allowlist. Leave blank to allow any source that matches a bound device.": (
        "允许访问的 ADMS 来源 IP，以逗号分隔。留空表示允许与已绑定设备匹配的任意来源。",
        "รายการ IP ต้นทางของ ADMS ที่อนุญาต คั่นด้วยจุลภาค เว้นว่างเพื่ออนุญาตต้นทางที่ตรงกับอุปกรณ์ที่เชื่อมโยงไว้",
    ),
    "Command Payload": ("命令数据", "ข้อมูลคำสั่ง"),
    "Company %(company)s is in a country with multiple timezones. Set the timezone on the company contact before using IoT schedules.": (
        "公司 %(company)s 所在国家/地区有多个时区。使用 IoT 定时计划前，请在公司联系人中设置时区。",
        "ประเทศของบริษัท %(company)s มีหลายเขตเวลา โปรดกำหนดเขตเวลาในข้อมูลติดต่อของบริษัทก่อนใช้ตารางเวลา IoT",
    ),
    "Company Country": ("公司所在国家/地区", "ประเทศของบริษัท"),
    "Company Timezone": ("公司时区", "เขตเวลาของบริษัท"),
    "Company internal network settings were sent to the selected controller(s).": (
        "已将公司内网设置发送到选定的控制器。",
        "ส่งการตั้งค่าเครือข่ายภายในของบริษัทไปยังตัวควบคุมที่เลือกแล้ว",
    ),
    "Company-specific server IP or hostname reachable through WireGuard. Do not include scheme, port, or path.": (
        "可通过 WireGuard 访问的公司专用服务器 IP 或主机名。请勿包含协议、端口或路径。",
        "IP หรือชื่อโฮสต์ของเซิร์ฟเวอร์บริษัทที่เข้าถึงผ่าน WireGuard ได้ โดยไม่ต้องใส่รูปแบบโปรโตคอล พอร์ต หรือพาธ",
    ),
    "Completed At": ("完成时间", "เวลาที่เสร็จสิ้น"),
    "Configure the country on company %(company)s before using IoT devices.": (
        "使用 IoT 设备前，请先为公司 %(company)s 设置国家/地区。",
        "โปรดกำหนดประเทศให้บริษัท %(company)s ก่อนใช้อุปกรณ์ IoT",
    ),
    "Confirmed": ("已确认", "ยืนยันแล้ว"),
    "Connected Seconds": ("连接时长（秒）", "ระยะเวลาที่เชื่อมต่อ (วินาที)"),
    "Controllers use the company WireGuard route first and fall back to public endpoints when unavailable.": (
        "控制器优先使用公司的 WireGuard 路由；不可用时自动回退到公网端点。",
        "ตัวควบคุมจะใช้เส้นทาง WireGuard ของบริษัทก่อน และเปลี่ยนไปใช้ปลายทางสาธารณะเมื่อใช้งานไม่ได้",
    ),
    "Create Date": ("创建时间", "วันที่สร้าง"),
    "Current Hostname": ("当前主机名", "ชื่อโฮสต์ปัจจุบัน"),
    "DIO": ("DIO", "DIO"),
    "DOUT": ("DOUT", "DOUT"),
    "Daily Overview": ("每日概览", "ภาพรวมรายวัน"),
    "Delay Active": ("延时中", "โหมดหน่วงเวลาทำงาน"),
    "Delay Active:": ("延时状态：", "สถานะการหน่วงเวลา:"),
    "Delay Duration Minutes": ("延时时长（分钟）", "ระยะเวลาหน่วง (นาที)"),
    "Delay End At": ("延时结束时间", "เวลาสิ้นสุดการหน่วง"),
    "Delay Remaining Minutes": ("剩余延时（分钟）", "เวลาหน่วงที่เหลือ (นาที)"),
    "Delay Remaining:": ("剩余延时：", "เวลาหน่วงที่เหลือ:"),
    "Delay Started At": ("延时开始时间", "เวลาเริ่มการหน่วง"),
    "Delay command sent.": ("延时命令已发送。", "ส่งคำสั่งหน่วงเวลาแล้ว"),
    "Delay mode is active for: %s. Cancel the delay before sending another command.": (
        "以下设备正在执行延时任务：%s。发送其他命令前请先取消延时。",
        "อุปกรณ์ต่อไปนี้อยู่ในโหมดหน่วงเวลา: %s โปรดยกเลิกการหน่วงก่อนส่งคำสั่งอื่น",
    ),
    "Delay mode is active. This action is blocked for: %s": (
        "以下设备正在执行延时任务，当前操作已阻止：%s",
        "อุปกรณ์ต่อไปนี้อยู่ในโหมดหน่วงเวลา จึงไม่สามารถดำเนินการนี้ได้: %s",
    ),
    "Desired Relay State": ("期望继电器状态", "สถานะรีเลย์ที่ต้องการ"),
    "Device UID": ("设备 UID", "UID อุปกรณ์"),
    "Device Uid": ("设备 UID", "UID อุปกรณ์"),
    "Device User": ("设备用户", "ผู้ใช้อุปกรณ์"),
    "Device-side safety cutoff. Set to 0 to disable. UV lamps should always have a finite limit.": (
        "设备端安全断电时限。设为 0 表示禁用；紫外灯必须设置有限时长。",
        "เวลาตัดการทำงานเพื่อความปลอดภัยที่อุปกรณ์ ตั้งเป็น 0 เพื่อปิดใช้งาน โดยหลอด UV ต้องกำหนดเวลาจำกัดเสมอ",
    ),
    "Direction": ("方向", "ทิศทาง"),
    "Download Bytes Total": ("下载总量（字节）", "ปริมาณดาวน์โหลดรวม (ไบต์)"),
    "Download Rate Mbps": ("下载速率（Mbps）", "อัตราดาวน์โหลด (Mbps)"),
    "Employee": ("员工", "พนักงาน"),
    "Enable this to route both MQTT relay traffic and Temperature/Humidity TCP gateway traffic through middleware.": (
        "启用后，MQTT 继电器流量和温湿度 TCP 网关流量都将通过中间件转发。",
        "เปิดใช้เพื่อส่งทั้งข้อมูลรีเลย์ MQTT และข้อมูลเกตเวย์ TCP อุณหภูมิ/ความชื้นผ่านมิดเดิลแวร์",
    ),
    "Enabled": ("已启用", "เปิดใช้งาน"),
    "Encryption": ("加密方式", "การเข้ารหัส"),
    "Endpoint": ("端点", "ปลายทาง"),
    "Enter an internal IP address or hostname without a scheme, port, or path.": (
        "请输入不含协议、端口或路径的内网 IP 地址或主机名。",
        "โปรดป้อน IP ภายในหรือชื่อโฮสต์โดยไม่ใส่รูปแบบโปรโตคอล พอร์ต หรือพาธ",
    ),
    "Error Code": ("错误代码", "รหัสข้อผิดพลาด"),
    "Firmware Hardware Profile": ("固件硬件配置", "โปรไฟล์ฮาร์ดแวร์ของเฟิร์มแวร์"),
    "Firmware Target Version": ("固件目标版本", "เวอร์ชันเฟิร์มแวร์เป้าหมาย"),
    "Firmware Upgrade Completed At": ("固件升级完成时间", "เวลาที่อัปเกรดเฟิร์มแวร์เสร็จสิ้น"),
    "Firmware Upgrade Requested At": ("固件升级请求时间", "เวลาที่ขออัปเกรดเฟิร์มแวร์"),
    "Firmware Upgrade State": ("固件升级状态", "สถานะการอัปเกรดเฟิร์มแวร์"),
    "Firmware:": ("固件：", "เฟิร์มแวร์:"),
    "Flash Real Size Bytes": ("闪存实际大小（字节）", "ขนาดแฟลชจริง (ไบต์)"),
    "Free Heap Bytes": ("可用堆内存（字节）", "หน่วยความจำ heap ที่ว่าง (ไบต์)"),
    "Friendly name used in charts; the technical code is stored separately.": (
        "图表中显示的易读名称；技术编号会单独保留。",
        "ชื่อที่อ่านง่ายสำหรับแสดงในกราฟ โดยเก็บรหัสทางเทคนิคแยกต่างหาก",
    ),
    "Group By": ("分组方式", "จัดกลุ่มตาม"),
    "Heartbeat Fail Count": ("心跳失败次数", "จำนวน heartbeat ที่ล้มเหลว"),
    "Hidden": ("隐藏", "ซ่อน"),
    "High-frequency ADMS request logs older than this many days are purged automatically to keep the database lean.": (
        "超过此天数的高频 ADMS 请求日志将自动清理，以控制数据库容量。",
        "บันทึกคำขอ ADMS ความถี่สูงที่เก่ากว่าจำนวนวันนี้จะถูกล้างอัตโนมัติเพื่อลดขนาดฐานข้อมูล",
    ),
    "High-frequency processed telemetry is kept for a much shorter time than command/status messages.": (
        "高频遥测数据的保留时间远短于命令和状态消息。",
        "ข้อมูล telemetry ความถี่สูงที่ประมวลผลแล้วจะเก็บไว้สั้นกว่าข้อความคำสั่งและสถานะมาก",
    ),
    "Host": ("主机", "โฮสต์"),
    "Idle": ("空闲", "ว่าง"),
    "Image Compatible": ("镜像兼容", "อิมเมจเข้ากันได้"),
    "Image Flash Mode": ("镜像闪存模式", "โหมดแฟลชของอิมเมจ"),
    "Image Flash Size": ("镜像闪存大小", "ขนาดแฟลชของอิมเมจ"),
    "Internal / Primary": ("内网 / 首选", "ภายใน / หลัก"),
    "Internal MQTT Port": ("内网 MQTT 端口", "พอร์ต MQTT ภายใน"),
    "Internal OTA HTTPS Port": ("内网 OTA HTTPS 端口", "พอร์ต OTA HTTPS ภายใน"),
    "Internal Odoo Port": ("内网 Odoo 端口", "พอร์ต Odoo ภายใน"),
    "Internal Server Host": ("内网服务器地址", "โฮสต์เซิร์ฟเวอร์ภายใน"),
    "IoT - Refresh Company Timezone Offsets": ("IoT - 刷新公司时区偏移", "IoT - อัปเดตค่าเขตเวลาของบริษัท"),
    "IoT Attendance Device": ("IoT 考勤设备", "อุปกรณ์ลงเวลา IoT"),
    "IoT Attendance Punch": ("IoT 考勤打卡记录", "บันทึกเวลา IoT"),
    "IoT Attendance Request Log": ("IoT 考勤请求日志", "บันทึกคำขอลงเวลา IoT"),
    "IoT Attendance User Mapping": ("IoT 考勤用户映射", "การเชื่อมโยงผู้ใช้ลงเวลา IoT"),
    "IoT Device Group": ("IoT 设备分组", "กลุ่มอุปกรณ์ IoT"),
    "IoT Firmware Upgrade Log": ("IoT 固件升级日志", "บันทึกการอัปเกรดเฟิร์มแวร์ IoT"),
    "IoT Internal MQTT Port": ("IoT 内网 MQTT 端口", "พอร์ต MQTT ภายในสำหรับ IoT"),
    "IoT Internal OTA HTTPS Port": ("IoT 内网 OTA HTTPS 端口", "พอร์ต OTA HTTPS ภายในสำหรับ IoT"),
    "IoT Internal Odoo Port": ("IoT 内网 Odoo 端口", "พอร์ต Odoo ภายในสำหรับ IoT"),
    "IoT Internal Server Host": ("IoT 内网服务器地址", "โฮสต์เซิร์ฟเวอร์ภายในสำหรับ IoT"),
    "IoT internal ports must be between 1 and 65535.": ("IoT 内网端口必须在 1 到 65535 之间。", "พอร์ตภายในสำหรับ IoT ต้องอยู่ระหว่าง 1 ถึง 65535"),
    "Iot Attendance Adms Port": ("考勤 ADMS 端口", "พอร์ต ADMS สำหรับลงเวลา"),
    "Iot Attendance Allowed Ips": ("考勤允许来源 IP", "IP ที่อนุญาตสำหรับเครื่องลงเวลา"),
    "Iot Attendance Max Open Hours": ("考勤记录最长未签退时长（小时）", "ระยะเวลาสูงสุดของรายการลงเวลาที่ยังไม่ปิด (ชั่วโมง)"),
    "Iot Attendance Punch Raw Retention Days": ("考勤打卡原始数据保留天数", "ระยะเวลาเก็บข้อมูลดิบของการลงเวลา (วัน)"),
    "Iot Attendance Request Retention Days": ("考勤请求保留天数", "ระยะเวลาเก็บคำขอลงเวลา (วัน)"),
    "Iot Device Retention Days": ("IoT 设备保留天数", "ระยะเวลาเก็บอุปกรณ์ IoT (วัน)"),
    "Iot Firmware Base Url": ("IoT 固件基础 URL", "URL พื้นฐานของเฟิร์มแวร์ IoT"),
    "Iot Firmware Log Payload Retention Days": ("IoT 固件日志数据保留天数", "ระยะเวลาเก็บข้อมูลบันทึกเฟิร์มแวร์ IoT (วัน)"),
    "Iot Firmware Log Retention Days": ("IoT 固件日志保留天数", "ระยะเวลาเก็บบันทึกเฟิร์มแวร์ IoT (วัน)"),
    "Iot Middleware Base Url": ("IoT 中间件基础 URL", "URL พื้นฐานของมิดเดิลแวร์ IoT"),
    "Iot Middleware Enabled": ("启用 IoT 中间件", "เปิดใช้มิดเดิลแวร์ IoT"),
    "Iot Middleware Token": ("IoT 中间件令牌", "โทเคนมิดเดิลแวร์ IoT"),
    "Iot Mqtt Message Retention Days": ("IoT MQTT 消息保留天数", "ระยะเวลาเก็บข้อความ MQTT ของ IoT (วัน)"),
    "Iot Mqtt Telemetry Retention Hours": ("IoT MQTT 遥测数据保留小时数", "ระยะเวลาเก็บ telemetry MQTT ของ IoT (ชั่วโมง)"),
    "Iot Mqtt Telemetry Sample Window Seconds": ("IoT MQTT 遥测采样窗口（秒）", "ช่วงเก็บตัวอย่าง telemetry MQTT ของ IoT (วินาที)"),
    "Iot Openwrt Full Probe Every": ("OpenWrt 完整检测周期", "ตรวจสอบ OpenWrt แบบเต็มทุก N heartbeat"),
    "Iot Openwrt Heartbeat Interval Sec": ("OpenWrt 心跳间隔（秒）", "ช่วงเวลา heartbeat ของ OpenWrt (วินาที)"),
    "Iot Openwrt Job Payload Retention Days": ("OpenWrt 任务数据保留天数", "ระยะเวลาเก็บข้อมูลงาน OpenWrt (วัน)"),
    "Iot Openwrt Job Retention Days": ("OpenWrt 任务保留天数", "ระยะเวลาเก็บงาน OpenWrt (วัน)"),
    "Iot Openwrt Offline Failure Threshold": ("OpenWrt 离线失败阈值", "เกณฑ์จำนวนครั้งล้มเหลวก่อนระบุ OpenWrt ว่าออฟไลน์"),
    "Iot Openwrt Online Timeout Sec": ("OpenWrt 在线超时（秒）", "เวลาหมดอายุสถานะออนไลน์ของ OpenWrt (วินาที)"),
    "Iot Openwrt Ssh Private Key Path": ("OpenWrt SSH 私钥路径", "พาธคีย์ส่วนตัว SSH ของ OpenWrt"),
    "Iot Openwrt Ssh Public Key": ("OpenWrt SSH 公钥", "คีย์สาธารณะ SSH ของ OpenWrt"),
    "Iot Th Raw Retention Days": ("温湿度原始数据保留天数", "ระยะเวลาเก็บข้อมูลดิบอุณหภูมิ/ความชื้น (วัน)"),
    "Items": ("条目", "รายการ"),
    "Job": ("任务", "งาน"),
    "Job Count": ("任务数量", "จำนวนงาน"),
    "Job Type": ("任务类型", "ประเภทงาน"),
    "Last Apply At": ("最近应用时间", "เวลาใช้งานล่าสุด"),
    "Last Command": ("最近命令", "คำสั่งล่าสุด"),
    "Last Command Confirmed At": ("最近命令确认时间", "เวลายืนยันคำสั่งล่าสุด"),
    "Last Error": ("最近错误", "ข้อผิดพลาดล่าสุด"),
    "Last Heartbeat At": ("最近心跳时间", "เวลา heartbeat ล่าสุด"),
    "Last 30 Days": ("最近 30 天", "30 วันที่ผ่านมา"),
    "Last Probe At": ("最近检测时间", "เวลาตรวจสอบล่าสุด"),
    "Last Humidity": ("最新湿度", "ความชื้นล่าสุด"),
    "Last Temperature": ("最新温度", "อุณหภูมิล่าสุด"),
    "Last Seen At": ("最近在线时间", "เวลาที่พบล่าสุด"),
    "Last Sync At": ("最近同步时间", "เวลาซิงก์ล่าสุด"),
    "Last Sync Message": ("最近同步消息", "ข้อความซิงก์ล่าสุด"),
    "Last Upgrade At": ("最近升级时间", "เวลาอัปเกรดล่าสุด"),
    "Manual Override": ("手动覆盖", "ควบคุมแทนด้วยตนเอง"),
    "Max Open Attendance Hours": ("考勤记录最长未签退时长（小时）", "ระยะเวลาสูงสุดของรายการลงเวลาที่ยังไม่ปิด (ชั่วโมง)"),
    "Maximum Continuous ON (Minutes)": ("最长连续开启时间（分钟）", "เวลาเปิดต่อเนื่องสูงสุด (นาที)"),
    "Maximum Humidity (%RH)": ("最高湿度（%RH）", "ความชื้นสูงสุด (%RH)"),
    "Maximum Temperature (C)": ("最高温度（°C）", "อุณหภูมิสูงสุด (°C)"),
    "Maximum continuous ON time cannot be negative.": ("最长连续开启时间不能为负数。", "เวลาเปิดต่อเนื่องสูงสุดต้องไม่เป็นค่าติดลบ"),
    "Message": ("消息", "ข้อความ"),
    "Method": ("方法", "วิธีการ"),
    "Middleware checks AP reachability on this interval.": ("中间件按此间隔检查 AP 的可达性。", "มิดเดิลแวร์จะตรวจสอบการเข้าถึง AP ตามช่วงเวลานี้"),
    "Minimum Humidity (%RH)": ("最低湿度（%RH）", "ความชื้นต่ำสุด (%RH)"),
    "Minimum Temperature (C)": ("最低温度（°C）", "อุณหภูมิต่ำสุด (°C)"),
    "Model": ("型号", "รุ่น"),
    "Model Pattern": ("型号匹配规则", "รูปแบบชื่อรุ่น"),
    "Module": ("模块", "โมดูล"),
    "Monitoring & Analysis": ("监测与分析", "การตรวจวัดและการวิเคราะห์"),
    "MQTT Route": ("MQTT 路由", "เส้นทาง MQTT"),
    "Mqtt Active Host": ("MQTT 当前主机", "โฮสต์ MQTT ที่ใช้งานอยู่"),
    "Mqtt Route": ("MQTT 路由", "เส้นทาง MQTT"),
    "Must exactly match the IOT_BRIDGE_TOKEN value in middleware environment config. If left blank when saving, Odoo will generate a secure token automatically.": (
        "必须与中间件环境配置中的 IOT_BRIDGE_TOKEN 完全一致。保存时留空，Odoo 将自动生成安全令牌。",
        "ต้องตรงกับค่า IOT_BRIDGE_TOKEN ในการตั้งค่าสภาพแวดล้อมของมิดเดิลแวร์ทุกตัวอักษร หากเว้นว่างขณะบันทึก Odoo จะสร้างโทเคนที่ปลอดภัยให้อัตโนมัติ",
    ),
    "Network": ("网络", "เครือข่าย"),
    "Network Config Dirty": ("网络配置待同步", "การตั้งค่าเครือข่ายรอซิงก์"),
    "Network configuration": ("网络配置", "การตั้งค่าเครือข่าย"),
    "No MQTT endpoint is configured for %s": ("未为 %s 配置 MQTT 端点", "ยังไม่ได้กำหนดปลายทาง MQTT สำหรับ %s"),
    "No timezone mapping is available for company %(company)s. Set the timezone on the company contact.": (
        "无法获取公司 %(company)s 的时区。请在公司联系人中设置时区。",
        "ไม่พบข้อมูลเขตเวลาสำหรับบริษัท %(company)s โปรดกำหนดเขตเวลาในข้อมูลติดต่อของบริษัท",
    ),
    "No upgrade command could be sent.\n%s": ("未能发送任何升级命令。\n%s", "ไม่สามารถส่งคำสั่งอัปเกรดได้\n%s"),
    "No upgrade command sent successfully. %s": ("未能成功发送任何升级命令。%s", "ไม่สามารถส่งคำสั่งอัปเกรดได้ %s"),
    "No upgrade command sent successfully.\n%s": ("未能成功发送任何升级命令。\n%s", "ไม่สามารถส่งคำสั่งอัปเกรดได้\n%s"),
    "Node Sensor Channel (Temp+Humidity)": ("节点探头通道（温湿度）", "ช่องเซ็นเซอร์ของโหนด (อุณหภูมิและความชื้น)"),
    "Notes": ("备注", "หมายเหตุ"),
    "Online:": ("在线：", "ออนไลน์:"),
    "Open Alerts": ("当前告警", "การแจ้งเตือนที่ยังไม่ปิด"),
    "Open Sensors": ("查看探头", "ดูรายการเซ็นเซอร์"),
    "Open attendances older than this are not auto-closed by a new punch, preventing yesterday's punch from leaking into today.": (
        "超过此时长且未签退的考勤记录不会被新打卡自动关闭，以防前一天的记录延续到当天。",
        "รายการลงเวลาที่ยังไม่ปิดและเก่ากว่าระยะเวลานี้จะไม่ถูกปิดอัตโนมัติด้วยการลงเวลาครั้งใหม่ เพื่อป้องกันรายการของเมื่อวานต่อเนื่องมาถึงวันนี้",
    ),
    "OpenWrt AP Client": ("OpenWrt AP 客户端", "ไคลเอนต์ของ OpenWrt AP"),
    "OpenWrt Template SSID": ("OpenWrt 模板 SSID", "SSID ในแม่แบบ OpenWrt"),
    "OpenWrt Version": ("OpenWrt 版本", "เวอร์ชัน OpenWrt"),
    "Openwrt Version": ("OpenWrt 版本", "เวอร์ชัน OpenWrt"),
    "Optional comma-separated source IPs for ADMS terminals. Blank means any source is accepted only if it matches a bound device SN or host.": (
        "可选的 ADMS 终端来源 IP，以逗号分隔。留空时，仅接受与已绑定设备序列号或主机匹配的来源。",
        "IP ต้นทางของเครื่อง ADMS ที่อนุญาต คั่นด้วยจุลภาค หากเว้นว่างจะรับต้นทางเฉพาะเมื่อหมายเลขเครื่องหรือโฮสต์ตรงกับอุปกรณ์ที่เชื่อมโยงไว้",
    ),
    "Password": ("密码", "รหัสผ่าน"),
    "Payload Text": ("数据内容", "ข้อความข้อมูล"),
    "Port": ("端口", "พอร์ต"),
    "Prefer Company Internal Network": ("优先使用公司内网", "ใช้เครือข่ายภายในของบริษัทก่อน"),
    "Prefer IoT Internal Network": ("IoT 优先使用内网", "ให้ IoT ใช้เครือข่ายภายในก่อน"),
    "Probe": ("检测", "ตรวจสอบ"),
    "Probe Name": ("探头名称", "ชื่อเซ็นเซอร์"),
    "Processed or ignored punch raw payloads are cleared after this many days while keeping the punch result itself.": (
        "已处理或忽略的打卡原始数据将在此天数后清除，但保留打卡结果。",
        "ข้อมูลดิบของการลงเวลาที่ประมวลผลหรือข้ามแล้วจะถูกล้างหลังจำนวนวันนี้ โดยยังคงเก็บผลการลงเวลาไว้",
    ),
    "Public / Fallback": ("公网 / 备用", "สาธารณะ / สำรอง"),
    "Punch Count": ("打卡数量", "จำนวนการลงเวลา"),
    "Punch Direction Mode": ("打卡方向模式", "โหมดทิศทางการลงเวลา"),
    "Punch Time": ("打卡时间", "เวลาลงเวลา"),
    "QIO": ("QIO", "QIO"),
    "QOUT": ("QOUT", "QOUT"),
    "Quarantine Reason": ("隔离原因", "เหตุผลที่กักกัน"),
    "Quarantined": ("已隔离", "ถูกกักกัน"),
    "Quarantined firmware cannot be pushed to devices.": ("已隔离的固件不能下发到设备。", "ไม่สามารถส่งเฟิร์มแวร์ที่ถูกกักกันไปยังอุปกรณ์ได้"),
    "Raw Samples": ("原始采样", "ข้อมูลดิบจากการตรวจวัด"),
    "Raw node-frequency readings older than this are compressed into daily averages unless the sensor keeps full history.": (
        "超过此天数的节点原始采样将压缩为每日平均值；设置保留完整历史的探头除外。",
        "ข้อมูลดิบตามความถี่ของโหนดที่เก่ากว่าระยะเวลานี้จะถูกสรุปเป็นค่าเฉลี่ยรายวัน ยกเว้นเซ็นเซอร์ที่ตั้งค่าให้เก็บประวัติทั้งหมด",
    ),
    "Reading": ("监测数据", "ข้อมูลการตรวจวัด"),
    "Reading Count": ("采样次数", "จำนวนค่าที่ตรวจวัด"),
    "Readings & Analysis": ("监测数据与分析", "ข้อมูลการตรวจวัดและการวิเคราะห์"),
    "Relative Humidity (%RH)": ("相对湿度（%RH）", "ความชื้นสัมพัทธ์ (%RH)"),
    "Relay Command State": ("继电器命令状态", "สถานะคำสั่งรีเลย์"),
    "Relay firmware must be an ESP8266 1MB/DOUT image. Detected flash mode: %(mode)s; flash size: %(size)s.": (
        "继电器固件必须是 ESP8266 1MB/DOUT 镜像。检测到的闪存模式：%(mode)s；闪存大小：%(size)s。",
        "เฟิร์มแวร์รีเลย์ต้องเป็นอิมเมจ ESP8266 1MB/DOUT ตรวจพบโหมดแฟลช: %(mode)s; ขนาดแฟลช: %(size)s",
    ),
    "Relay telemetry from the same device/topic inside this window is collapsed into one queue row to reduce database growth.": (
        "在此窗口内，同一设备和主题的继电器遥测数据将合并为一条队列记录，以减少数据库增长。",
        "ข้อมูล telemetry ของรีเลย์จากอุปกรณ์และหัวข้อเดียวกันภายในช่วงเวลานี้จะถูกรวมเป็นหนึ่งรายการคิวเพื่อลดการเติบโตของฐานข้อมูล",
    ),
    "Reported Version": ("上报版本", "เวอร์ชันที่รายงาน"),
    "Request Count": ("请求数量", "จำนวนคำขอ"),
    "Request Payload": ("请求数据", "ข้อมูลคำขอ"),
    "Requested": ("已请求", "ร้องขอแล้ว"),
    "Requested At": ("请求时间", "เวลาที่ร้องขอ"),
    "Reset Accumulated Time Wizard": ("重置累计时间向导", "ตัวช่วยรีเซ็ตเวลาสะสม"),
    "Response Payload": ("响应数据", "ข้อมูลตอบกลับ"),
    "Retained": ("保留", "เก็บไว้"),
    "Sample Count": ("采样次数", "จำนวนตัวอย่างการวัด"),
    "SHA-256 Checksum": ("SHA-256 校验值", "ค่า checksum SHA-256"),
    "SSID": ("SSID", "SSID"),
    "Samples": ("采样次数", "จำนวนตัวอย่างการวัด"),
    "Schedule Timezone Name": ("定时计划时区", "เขตเวลาของตารางเวลา"),
    "Schedule Timezone Offset Min": ("定时计划时区偏移（分钟）", "ค่าชดเชยเขตเวลาของตาราง (นาที)"),
    "Sensor": ("探头", "เซ็นเซอร์"),
    "Sensor Channel": ("探头通道", "ช่องเซ็นเซอร์"),
    "Sensor Channel (Optional)": ("探头通道（可选）", "ช่องเซ็นเซอร์ (ไม่บังคับ)"),
    "Sensor Count": ("探头数量", "จำนวนเซ็นเซอร์"),
    "Sensor ID": ("探头 ID", "รหัสเซ็นเซอร์"),
    "Sensor Location": ("探头位置", "ตำแหน่งเซ็นเซอร์"),
    "Sensors": ("探头", "เซ็นเซอร์"),
    "Signal Dbm": ("信号强度（dBm）", "ความแรงสัญญาณ (dBm)"),
    "Source": ("来源", "แหล่งที่มา"),
    "Ssid": ("SSID", "SSID"),
    "Statistics Period": ("统计时段", "ช่วงเวลาสถิติ"),
    "Statistics Window": ("统计时段", "ช่วงเวลาสถิติ"),
    "Statistics window must be greater than 0 hours.": ("统计时段必须大于 0 小时。", "ช่วงเวลาสถิติต้องมากกว่า 0 ชั่วโมง"),
    "Status Message": ("状态消息", "ข้อความสถานะ"),
    "Status:": ("状态：", "สถานะ:"),
    "Successful ADMS heartbeats are sampled at this interval. Punch, error, and unknown-device requests are still logged individually. Set to 0 to keep every heartbeat.": (
        "成功的 ADMS 心跳按此间隔抽样记录；打卡、错误和未知设备请求仍会逐条记录。设为 0 可保留每次心跳。",
        "heartbeat ของ ADMS ที่สำเร็จจะถูกบันทึกตามช่วงเวลานี้ ส่วนการลงเวลา ข้อผิดพลาด และคำขอจากอุปกรณ์ที่ไม่รู้จักยังคงบันทึกทุกรายการ ตั้งเป็น 0 เพื่อเก็บ heartbeat ทุกครั้ง",
    ),
    "Switch ID:": ("开关 ID：", "ID สวิตช์:"),
    "Sync Enabled": ("启用同步", "เปิดใช้การซิงก์"),
    "Sync Internal Network": ("同步内网配置", "ซิงก์การตั้งค่าเครือข่ายภายใน"),
    "System Hostname": ("系统主机名", "ชื่อโฮสต์ระบบ"),
    "Target": ("目标", "เป้าหมาย"),
    "Target Version": ("目标版本", "เวอร์ชันเป้าหมาย"),
    "Technical Code": ("技术编号", "รหัสทางเทคนิค"),
    "Temperature (C)": ("温度（°C）", "อุณหภูมิ (°C)"),
    "Temperature low limit must not exceed high limit.": ("温度下限不能高于温度上限。", "ขีดจำกัดอุณหภูมิต่ำสุดต้องไม่สูงกว่าขีดจำกัดสูงสุด"),
    "Humidity low limit must not exceed high limit.": ("湿度下限不能高于湿度上限。", "ขีดจำกัดความชื้นต่ำสุดต้องไม่สูงกว่าขีดจำกัดสูงสุด"),
    "Temperature/Humidity Reading": ("温湿度监测数据", "ข้อมูลการตรวจวัดอุณหภูมิ/ความชื้น"),
    "Temperature/Humidity Sensor": ("温湿度探头", "เซ็นเซอร์อุณหภูมิ/ความชื้น"),
    "Temperature/Humidity Sensor Group": ("温湿度探头分组", "กลุ่มเซ็นเซอร์อุณหภูมิ/ความชื้น"),
    "Template": ("模板", "แม่แบบ"),
    "This firmware is quarantined or incompatible with ESP8266 1MB/DOUT relay hardware.": (
        "该固件已被隔离，或与 ESP8266 1MB/DOUT 继电器硬件不兼容。",
        "เฟิร์มแวร์นี้ถูกกักกันหรือไม่เข้ากับฮาร์ดแวร์รีเลย์ ESP8266 1MB/DOUT",
    ),
    "This firmware is quarantined or incompatible with relay hardware.": ("该固件已被隔离，或与继电器硬件不兼容。", "เฟิร์มแวร์นี้ถูกกักกันหรือไม่เข้ากับฮาร์ดแวร์รีเลย์"),
    "Timed Out": ("已超时", "หมดเวลา"),
    "Total On Hours": ("累计开启小时数", "จำนวนชั่วโมงที่เปิดสะสม"),
    "Trend": ("趋势图", "กราฟแนวโน้ม"),
    "Trend - %s": ("趋势图 - %s", "กราฟแนวโน้ม - %s"),
    "Turn off command sent; waiting for device confirmation.": ("关闭命令已发送，正在等待设备确认。", "ส่งคำสั่งปิดแล้ว กำลังรออุปกรณ์ยืนยัน"),
    "Turn on command sent; waiting for device confirmation.": ("开启命令已发送，正在等待设备确认。", "ส่งคำสั่งเปิดแล้ว กำลังรออุปกรณ์ยืนยัน"),
    "Turn off command sent.": ("关闭命令已发送。", "ส่งคำสั่งปิดแล้ว"),
    "Turn on command sent.": ("开启命令已发送。", "ส่งคำสั่งเปิดแล้ว"),
    "Unbind this node from current company?": ("确定要解除此节点与当前公司的绑定吗？", "ยืนยันยกเลิกการเชื่อมโยงโหนดนี้กับบริษัทปัจจุบันหรือไม่"),
    "Unbind this switch from current company?": ("确定要解除此开关与当前公司的绑定吗？", "ยืนยันยกเลิกการเชื่อมโยงสวิตช์นี้กับบริษัทปัจจุบันหรือไม่"),
    "Unique Hash": ("唯一哈希值", "ค่าแฮชเฉพาะ"),
    "Unnamed Sensor": ("未命名探头", "เซ็นเซอร์ที่ยังไม่ได้ตั้งชื่อ"),
    "Upload Bytes Total": ("上传总量（字节）", "ปริมาณอัปโหลดรวม (ไบต์)"),
    "Upload Rate Mbps": ("上传速率（Mbps）", "อัตราอัปโหลด (Mbps)"),
    "Used to generate the ADMS HTTP/HTTPS address shown in attendance devices. Default is 8069.": (
        "用于生成考勤设备中显示的 ADMS HTTP/HTTPS 地址。默认端口为 8069。",
        "ใช้สร้างที่อยู่ ADMS HTTP/HTTPS ที่แสดงในเครื่องลงเวลา โดยค่าเริ่มต้นคือพอร์ต 8069",
    ),
    "User Count": ("用户数量", "จำนวนผู้ใช้"),
    "Validated": ("已验证", "ตรวจสอบแล้ว"),
    "Validated Key": ("已验证密钥", "คีย์ที่ตรวจสอบแล้ว"),
    "Validated Node": ("已验证节点", "โหนดที่ตรวจสอบแล้ว"),
    "Validated Probe Code": ("已验证探头通道", "รหัสเซ็นเซอร์ที่ตรวจสอบแล้ว"),
    "View Sensors": ("查看探头", "ดูรายการเซ็นเซอร์"),
    "Webhook Token": ("Webhook 令牌", "โทเคน Webhook"),
    "Webhook URL": ("Webhook 地址", "URL Webhook"),
    "Webhook Url": ("Webhook URL", "URL Webhook"),
    "Wifi24 Ssid Count": ("2.4 GHz SSID 数量", "จำนวน SSID ย่าน 2.4 GHz"),
    "Wifi5 Ssid Count": ("5 GHz SSID 数量", "จำนวน SSID ย่าน 5 GHz"),
    "<span>Accumulated ON (Hours): </span>": (
        "<span>累计开启时间（小时）：</span>",
        "<span>เวลาเปิดสะสม (ชั่วโมง): </span>",
    ),
    "<span>Delay Active: </span>": ("<span>延时状态：</span>", "<span>สถานะการหน่วงเวลา: </span>"),
    "<span>Delay Remaining: </span>": ("<span>剩余延时：</span>", "<span>เวลาหน่วงที่เหลือ: </span>"),
    "<span>Firmware: </span>": ("<span>固件：</span>", "<span>เฟิร์มแวร์: </span>"),
    "<span>Online: </span>": ("<span>在线：</span>", "<span>ออนไลน์: </span>"),
    "<span>Status: </span>": ("<span>状态：</span>", "<span>สถานะ: </span>"),
    "<span>Switch ID: </span>": ("<span>开关 ID：</span>", "<span>ID สวิตช์: </span>"),
    "AP": ("AP", "AP"),
    "AP client MAC must be unique per AP.": (
        "每个 AP 的客户端 MAC 必须唯一。",
        "MAC ของไคลเอนต์ต้องไม่ซ้ำกันภายใน AP เดียวกัน",
    ),
    "AP host + SSH port must be unique per company.": (
        "同一公司内 AP 主机与 SSH 端口的组合必须唯一。",
        "โฮสต์ AP และพอร์ต SSH ต้องไม่ซ้ำกันภายในบริษัทเดียวกัน",
    ),
    "IP Address": ("IP 地址", "ที่อยู่ IP"),
    "MAC Address": ("MAC 地址", "ที่อยู่ MAC"),
    "Activities": ("活动", "กิจกรรม"),
    "Activity Exception Decoration": ("活动异常标记", "รูปแบบแสดงข้อยกเว้นของกิจกรรม"),
    "Activity State": ("活动状态", "สถานะกิจกรรม"),
    "Activity Type Icon": ("活动类型图标", "ไอคอนประเภทกิจกรรม"),
    "Companies": ("公司", "บริษัท"),
    "Company Private Network (WireGuard)": ("公司内网（WireGuard）", "เครือข่ายภายในบริษัท (WireGuard)"),
    "Department name must be unique per company.": (
        "同一公司内的部门名称必须唯一。",
        "ชื่อแผนกต้องไม่ซ้ำกันภายในบริษัทเดียวกัน",
    ),
    "Font awesome icon e.g. fa-tasks": (
        "Font Awesome 图标，例如 fa-tasks",
        "ไอคอน Font Awesome เช่น fa-tasks",
    ),
    "Icon": ("图标", "ไอคอน"),
    "Icon to indicate an exception activity.": (
        "用于标识异常活动的图标。",
        "ไอคอนที่ใช้ระบุกิจกรรมที่มีข้อยกเว้น",
    ),
    "Location name must be unique per company.": (
        "同一公司内的位置名称必须唯一。",
        "ชื่อสถานที่ต้องไม่ซ้ำกันภายในบริษัทเดียวกัน",
    ),
    "My Activity Deadline": ("我的活动截止日期", "กำหนดส่งกิจกรรมของฉัน"),
    "Next Activity Calendar Event": ("下一个活动日历事件", "กิจกรรมปฏิทินถัดไป"),
    "Next Activity Deadline": ("下一活动截止日期", "กำหนดส่งกิจกรรมถัดไป"),
    "Next Activity Summary": ("下一活动摘要", "สรุปกิจกรรมถัดไป"),
    "Next Activity Type": ("下一活动类型", "ประเภทกิจกรรมถัดไป"),
    "Ratings": ("评分", "การให้คะแนน"),
    "Remote IP": ("来源 IP", "IP ต้นทาง"),
    "Responsible User": ("负责人", "ผู้รับผิดชอบ"),
    "Sensor Channel must be unique by Node ID + Channel.": (
        "节点 ID 与探头通道的组合必须唯一。",
        "ช่องเซ็นเซอร์ต้องไม่ซ้ำกันในแต่ละ Node ID",
    ),
    "Serial must be unique.": ("序列号必须唯一。", "หมายเลขซีเรียลต้องไม่ซ้ำกัน"),
    "Serial number must be unique.": ("设备序列号必须唯一。", "หมายเลขซีเรียลของอุปกรณ์ต้องไม่ซ้ำกัน"),
    "SMS Delivery error": ("SMS 发送错误", "ข้อผิดพลาดในการส่ง SMS"),
    "SSH Port": ("SSH 端口", "พอร์ต SSH"),
    "SSH User": ("SSH 用户", "ผู้ใช้ SSH"),
    "Status based on activities\nOverdue: Due date is already passed\nToday: Activity date is today\nPlanned: Future activities.": (
        "基于活动的状态\n逾期：截止日期已过\n今天：活动日期为今天\n计划：未来活动。",
        "สถานะตามกิจกรรม\nเกินกำหนด: วันที่ครบกำหนดผ่านไปแล้ว\nวันนี้: วันที่ของกิจกรรมคือวันนี้\nวางแผน: กิจกรรมในอนาคต",
    ),
    "The device user ID must be unique per device.": (
        "每台设备内的用户 ID 必须唯一。",
        "ID ผู้ใช้อุปกรณ์ต้องไม่ซ้ำกันภายในอุปกรณ์เดียวกัน",
    ),
    "The same punch cannot be imported twice.": (
        "同一条打卡记录不能重复导入。",
        "ไม่สามารถนำเข้ารายการลงเวลาเดียวกันซ้ำได้",
    ),
    "Switch ID": ("开关 ID", "ID สวิตช์"),
    "TCP Token": ("TCP 令牌", "โทเค็น TCP"),
    "Type of the exception activity on record.": (
        "记录中异常活动的类型。",
        "ประเภทกิจกรรมที่มีข้อยกเว้นในระเบียน",
    ),
    "Website Messages": ("网站消息", "ข้อความจากเว็บไซต์"),
    "Website communication history": ("网站沟通记录", "ประวัติการสื่อสารผ่านเว็บไซต์"),
    "ap_id": ("AP ID", "AP ID"),
    "iot.imytest.com": ("iot.imytest.com", "iot.imytest.com"),
}


def _python_terms() -> set[str]:
    terms: set[str] = set()
    paths = [
        *ROOT.glob("models/*.py"),
        *ROOT.glob("wizard/*.py"),
        *ROOT.glob("controllers/*.py"),
        *ROOT.glob("services/*.py"),
        ROOT / "hooks.py",
    ]
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if (
                    isinstance(node.func, ast.Name)
                    and node.func.id == "_"
                    and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and isinstance(node.args[0].value, str)
                ):
                    terms.add(node.args[0].value)
                for keyword in node.keywords:
                    if (
                        keyword.arg in ("string", "help")
                        and isinstance(keyword.value, ast.Constant)
                        and isinstance(keyword.value.value, str)
                    ):
                        terms.add(keyword.value.value)
                if (
                    isinstance(node.func, ast.Attribute)
                    and node.func.attr == "Selection"
                    and node.args
                    and isinstance(node.args[0], (ast.List, ast.Tuple))
                ):
                    for item in node.args[0].elts:
                        if (
                            isinstance(item, (ast.List, ast.Tuple))
                            and len(item.elts) > 1
                            and isinstance(item.elts[1], ast.Constant)
                            and isinstance(item.elts[1].value, str)
                        ):
                            terms.add(item.elts[1].value)
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                value = node.value
                if (
                    any(isinstance(target, ast.Name) and target.id == "_description" for target in targets)
                    and isinstance(value, ast.Constant)
                    and isinstance(value.value, str)
                ):
                    terms.add(value.value)
                if (
                    isinstance(value, ast.Call)
                    and isinstance(value.func, ast.Attribute)
                    and isinstance(value.func.value, ast.Name)
                    and value.func.value.id == "fields"
                ):
                    keywords = {keyword.arg for keyword in value.keywords}
                    if "string" not in keywords and "related" not in keywords:
                        for target in targets:
                            if isinstance(target, ast.Name):
                                name = target.id
                                name = name[:-4] if name.endswith("_ids") else name[:-3] if name.endswith("_id") else name
                                terms.add(name.replace("_", " ").title())
    return terms


def _xml_terms() -> set[str]:
    terms: set[str] = set()
    paths = [
        *ROOT.glob("views/*.xml"),
        *ROOT.glob("wizard/*_views.xml"),
        *ROOT.glob("data/*.xml"),
        *ROOT.glob("static/src/xml/*.xml"),
    ]
    for path in paths:
        root = ET.parse(path).getroot()
        for element in root.iter():
            for attribute in ("string", "help", "confirm", "placeholder"):
                value = element.attrib.get(attribute)
                if value and not value.startswith(("{", "[", "%", "/")):
                    terms.add(value)
            if element.tag == "menuitem" and element.attrib.get("name"):
                terms.add(element.attrib["name"])
            if element.text:
                value = " ".join(element.text.split())
                if (
                    value
                    and element.tag != "field"
                    and re.search(r"[A-Za-z]{2}", value)
                    and value != "this._iotGetActiveMeasures()"
                ):
                    terms.add(value)
        for record in root.findall(".//record"):
            if record.attrib.get("model") in ("ir.actions.act_window", "ir.cron"):
                for field in record.findall("./field"):
                    if field.attrib.get("name") == "name" and field.text:
                        terms.add(field.text.strip())
    return terms


def _javascript_terms() -> set[str]:
    terms: set[str] = set()
    for path in ROOT.glob("static/src/js/*.js"):
        source = path.read_text(encoding="utf-8")
        terms.update(match.group(2) for match in re.finditer(r'_t\(\s*(["\'])(.*?)\1\s*\)', source))
    return terms


def source_terms() -> set[str]:
    terms = _python_terms() | _xml_terms() | _javascript_terms()
    return {term for term in terms if term and not term.startswith(("iot.", "ir."))}


def _entry(po: polib.POFile, msgid: str) -> polib.POEntry:
    entry = po.find(msgid)
    if entry:
        return entry
    entry = polib.POEntry(
        msgid=msgid,
        msgstr="",
        comment="module: iot_control_center",
        occurrences=[("code:addons/iot_control_center", "0")],
    )
    po.append(entry)
    return entry


def _normalize_source_terms(po: polib.POFile) -> None:
    generic_occurrence = ("code:addons/iot_control_center", "0")
    for old_msgid, new_msgid in SOURCE_TERM_RENAMES.items():
        old_entry = po.find(old_msgid)
        if not old_entry or old_entry.obsolete:
            continue
        new_entry = _entry(po, new_msgid)
        occurrences = set(old_entry.occurrences) | set(new_entry.occurrences)
        if len(occurrences) > 1:
            occurrences.discard(generic_occurrence)
        new_entry.occurrences = sorted(occurrences)
        new_entry.flags = sorted(set(old_entry.flags) | set(new_entry.flags))
        po.remove(old_entry)


def synchronize() -> None:
    pot = polib.pofile(str(I18N / "iot_control_center.pot"), encoding="utf-8")
    catalogs = {name: polib.pofile(str(I18N / name), encoding="utf-8") for name in CATALOGS}
    _normalize_source_terms(pot)
    for catalog in catalogs.values():
        _normalize_source_terms(catalog)
    official_entries = {entry.msgid: entry for entry in pot if not entry.obsolete and entry.msgid}
    required = source_terms() | set(official_entries)

    missing_manual: list[str] = []
    for msgid in sorted(required):
        pot_entry = _entry(pot, msgid)
        english_entry = _entry(catalogs["en_US.po"], msgid)
        english_entry.msgstr = msgid
        english_entry.occurrences = list(pot_entry.occurrences)
        english_entry.flags = list(pot_entry.flags)
        for name, language_index in (("zh_CN.po", 0), ("th.po", 1), ("th_TH.po", 1)):
            entry = _entry(catalogs[name], msgid)
            entry.occurrences = list(pot_entry.occurrences)
            entry.flags = list(pot_entry.flags)
            if msgid in TRANSLATIONS:
                entry.msgstr = TRANSLATIONS[msgid][language_index]
            elif not entry.msgstr or any(marker in entry.msgstr for marker in SUSPICIOUS_MARKERS):
                missing_manual.append(msgid)

    # Reviewed wording also fixes valid legacy entries retained for upgrade compatibility.
    for msgid, translations in TRANSLATIONS.items():
        for name, language_index in (("zh_CN.po", 0), ("th.po", 1), ("th_TH.po", 1)):
            entry = catalogs[name].find(msgid)
            if entry and not entry.obsolete:
                entry.msgstr = translations[language_index]

    if missing_manual:
        unique = "\n".join(f"  - {msgid!r}" for msgid in sorted(set(missing_manual)))
        raise SystemExit(f"Missing reviewed translations:\n{unique}")

    pot.save(str(I18N / "iot_control_center.pot"))
    for name, po in catalogs.items():
        po.save(str(I18N / name))


def _placeholders(value: str) -> list[str]:
    return sorted(match for match in PLACEHOLDER_RE.findall(value) if match != "%%")


def validate() -> None:
    pot = polib.pofile(str(I18N / "iot_control_center.pot"), encoding="utf-8")
    catalogs = {name: polib.pofile(str(I18N / name), encoding="utf-8") for name in CATALOGS}
    errors: list[str] = []

    pot_entries = {entry.msgid: entry for entry in pot if not entry.obsolete and entry.msgid}
    pot_ids = set(pot_entries)
    required = source_terms() | pot_ids
    deprecated = sorted(set(SOURCE_TERM_RENAMES) & pot_ids)
    if deprecated:
        errors.append(f"POT contains deprecated source terms: {deprecated}")
    missing_pot = sorted(required - pot_ids)
    if missing_pot:
        errors.append(f"POT missing {len(missing_pot)} source terms")

    for name, po in catalogs.items():
        active_entries = [entry for entry in po if not entry.obsolete and entry.msgid]
        entries = {entry.msgid: entry for entry in active_entries}
        if len(entries) != len(active_entries):
            errors.append(f"{name} contains duplicate active msgids")
        missing = sorted(required - set(entries))
        if missing:
            errors.append(f"{name} missing {len(missing)} source terms")
        for msgid in sorted(pot_ids & set(entries)):
            if set(entries[msgid].occurrences) != set(pot_entries[msgid].occurrences):
                errors.append(f"{name}: source references differ for {msgid!r}")
        for msgid in sorted(entries):
            msgstr = entries[msgid].msgstr
            if not msgstr:
                errors.append(f"{name}: empty translation for {msgid!r}")
            if any(marker in msgstr for marker in SUSPICIOUS_MARKERS):
                errors.append(f"{name}: suspicious encoding for {msgid!r}")
            if _placeholders(msgid) != _placeholders(msgstr):
                errors.append(f"{name}: placeholder mismatch for {msgid!r}")
            if name == "en_US.po" and msgstr != msgid:
                errors.append(f"{name}: English translation differs for {msgid!r}")

    thai = {entry.msgid: entry.msgstr for entry in catalogs["th.po"] if not entry.obsolete and entry.msgid}
    thai_th = {entry.msgid: entry.msgstr for entry in catalogs["th_TH.po"] if not entry.obsolete and entry.msgid}
    for msgid in sorted(set(thai) | set(thai_th)):
        if thai.get(msgid) != thai_th.get(msgid):
            errors.append(f"Thai catalogs differ for {msgid!r}")

    if errors:
        raise SystemExit("\n".join(errors[:100]))
    print(f"I18N_OK source_terms={len(required)} catalogs={len(CATALOGS)}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true", help="Synchronize catalogs before validation")
    args = parser.parse_args()
    if args.write:
        synchronize()
    validate()


if __name__ == "__main__":
    main()
