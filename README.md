# IoT Control Center (Odoo 19)

用于管理 ESP8266 继电器模块（Wi-Fi + MQTT + OTA）。

## 功能
- 继电器远程开关控制与状态回传。
- 定时开关采用“下发到设备本地存储执行”模式（断网可继续执行）。
- 累积接通时长统计（分钟精度，界面显示 HH:MM）。
- 累积时长重置。
- 固件上传与批量 OTA 下发。
- 多公司 / 多部门 / 多位置管理。
- 通过 TCP 网关接入温湿度探头，记录与分析数据，支持趋势图和阈值告警。

## Odoo 依赖
- Python: `paho-mqtt`, `pytz`

## MQTT topic 约定
- Odoo -> 设备命令: `{topic_root}/{serial}/command`
- 设备 -> Odoo状态: `{topic_root}/{serial}/status`
- 设备 -> Odoo遥测: `{topic_root}/{serial}/telemetry`

## 命令 payload
### 继电器控制
```json
{"command":"relay","state":"on"}
```
`state` 支持 `on/off/toggle`。

### 升级命令
```json
{"command":"upgrade","url":"https://.../download?...","version":"1.0.2","checksum":"sha256"}
```

### 定时策略下发
```json
{
  "command":"schedule_set",
  "version":3,
  "entries":[
    {"weekday":0,"hour":8,"minute":0,"action":"on","offset_min":480},
    {"weekday":0,"hour":20,"minute":0,"action":"off","offset_min":480}
  ]
}
```

### 清空定时策略
```json
{"command":"schedule_clear","version":4}
```

## 温湿度 TCP 上报协议
网关向 Odoo 的 TCP 监听地址（`th_tcp_host:th_tcp_port`）发送按行分隔 JSON：

```json
{
  "gateway_serial": "th-gw-001",
  "token": "optional-secret",
  "reported_at": "2026-02-12T14:00:00Z",
  "probes": [
    {"probe_code": "A1", "temperature": 24.5, "humidity": 56.2},
    {"probe_code": "A2", "temperature": 25.1, "humidity": 58.8}
  ]
}
```

服务端自动执行：
- 首次上报自动创建网关和探头。
- 写入温湿度读数并用于统计。
- 按探头阈值生成/关闭超温超湿告警。

## 安装
1. 将 `iot_control_center` 目录加入 Odoo addons path。
2. 安装 Python 依赖：`pip install paho-mqtt pytz`
3. 更新应用列表并安装模块。
4. 在系统设置中配置 MQTT 参数。
5. 创建部门/位置，录入设备（`serial` 需与固件一致）。

## 测试预置参数
- WiFi SSID: `iMyTest_IoT`
- WiFi 密码: `iMyTest_IoT`
- Odoo 19 CE 地址: `http://192.168.10.155:8069`
- 默认 MQTT Host: `192.168.10.155`

建议同时确认 Odoo 系统参数 `web.base.url` 为 `http://192.168.10.155:8069`，用于 OTA 下载链接生成。
