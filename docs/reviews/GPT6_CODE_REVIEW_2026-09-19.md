# IoT 控制中心与仪器固件审查及修正任务

审查基线：`1ecfe48837b09b272345d18fe2a903811012d514`，平台 `19.0.2.2.0`，洗脱仪 `3.4.0-rc3`，加热器 `3.2.0-rc1`。

本报告用于交给 GPT-5.6 实施修正。本轮只阅读代码、运行本地测试和生成本报告，没有修改业务代码、连接设备操作或发布服务器。重点逐函数检查了仪器固件、程序编制和同步、状态上报、离线日志、OTA；另抽查了继电器消息处理、桥接队列、温湿度记录和界面入口。不是所有模块的逐行穷尽审计，也没有重新进行生产状态或带负载验收。

## 1. 需要修正的问题

P1：应在仪器带负载验收前修正。P2：影响可靠性、记录可信度或运行可预期性。P3：文档与维护问题。

### R01 / P1：洗脱中止后没有使残液清理状态失效

依据：[Startup::stop](D:/Codex/iot_control_center/firmware/instruments/lib/InstrumentCore/src/washer_setup.hpp:55)、[stopRun/startRun](D:/Codex/iot_control_center/firmware/instruments/src/washer.cpp:175)、[Washer::start](D:/Codex/iot_control_center/firmware/instruments/lib/InstrumentCore/src/control.hpp:180)。

初始化完成以后，`Startup::stop()` 特意保留 `Ready`。在注液或洗脱中途按 STOP，输出会关闭，但桶内可能有液体；下一次启动仍通过初始化检查。程序前置步骤只有归零，没有恢复排液，因此可以直接再次注液。程序编译器里的 `liquid=false` 只是一次新程序的逻辑假设，无法代表桶内实际情况。

本次用真实 C++ 核心复现：`startup_phase_after_ready_stop=3 (Ready=3)`；中止注液再启动、归零后得到 `restart_after_fill_abort=1 inlet_a_after_rehome=1 drain=0`。这是状态机复现，没有运行实物。

修改方法：

- 增加独立的 `requires_cleanup` 或 `FluidState::Unknown`，不要用“曾经开机初始化成功”代替“当前允许直接注液”。
- 注液可能开始时就持久化“需要清理”；中止、故障、掉电恢复、运行标记损坏都保留此状态。仅在规定的清理流程成功结束后解除。
- 重新开始程序前要求操作员完成恢复初始化；保留 STOP 立即关输出，不在按 STOP 后自动开启排液泵。
- 本地 RESET 只能清故障提示，不能同时清除残液恢复要求。

验收：在 A 注液、人工等待、洗脱、B 注液和排液未结束时分别 STOP/模拟掉电；再次开始必须先完成清理。正常完整结束不应错误锁死。

### R02 / P1：启动确认没有绑定所确认的程序版本

依据：[确认按钮](D:/Codex/iot_control_center/firmware/instruments/src/washer.cpp:287)、[applyCatalog](D:/Codex/iot_control_center/firmware/instruments/src/washer.cpp:390)、[同步调度](D:/Codex/iot_control_center/firmware/instruments/src/washer.cpp:446)、[同页重绘](D:/Codex/iot_control_center/firmware/instruments/include/tjc_ui.hpp:53)。

确认页为 `page=1`，仍满足同步条件 `page<6`。完整列表同步会直接替换 `washer.program`；若当前程序被删除，还会选择另一个程序。确认按钮调用 `startRun()` 时没有核验操作员先前看到的程序身份和版本。

此外，同一确认页更新内容时没有清除已经按下的触摸状态。本次直接测试真实 Display 类：按住 A/r1 的确认按钮，重绘成 B/r2，稍后松开，返回 `confirm_button_after_program_changed=0 accepts_action=1`。已有 750ms 显示等待并不能消除此问题。

修改方法：

- 进入确认页时保存 `uid + revision + checksum`，显示、确认与实际运行都使用该不可变快照。
- 确认期间可以后台下载，但延迟提交新目录；或者目录变化立即撤销确认并要求重新查看，不能默默切换运行内容。
- 同页的重要内容变化也必须取消旧按压；用页面内容代次绑定 press/release。
- 检查启动时已在途的同步响应，不能只禁止发起新下载。

验收：确认页打开、按住、松开三个时间点插入修改、删除、空目录响应；均不得启动未确认的新程序。正常选择和自动同步仍应可用。

### R03 / P1：再次注液使用累计绝对位置，可能反转很多圈后超时

依据：[注液前后 moveTo](D:/Codex/iot_control_center/firmware/instruments/src/washer.cpp:521)、[连续洗脱运动](D:/Codex/iot_control_center/firmware/instruments/src/washer.cpp:549)、[原电机参数](D:/Codex/iot_control_center/firmware/instruments/lib/InstrumentCore/src/motor_profile.hpp:7)。

连续正反转后，步进控制器位置是累计脉冲数。下一次注液直接 `moveTo(133)`，不是移动到本圈内相同的注液角度，且只有 5 秒定位超时。暂停装片代码已经会取模，注液路径却没有这样处理。

本次确认平台接受以下合法参数：洗脱 30 秒、1 rev/s、换向间隔 60 秒，然后排液、注入 B。按代码的 1 rev/s² 加减速作理想轨迹估算，洗脱及减速后累计约 30 圈。从约 96,000 脉冲回到 133，在最高 3,200 脉冲/秒下至少约 30 秒，必然超出 5 秒限制。此为代码和轨迹计算结论，未在电机上执行。

修改方法：

- 在洗脱结束到定位之间增加等待减速停止的状态。
- 仅在控制器已经停稳、位置参考有效时，将累计位置归一化为一圈内角度，再按允许方向计算到注液位的相对距离；需要重新归零时使用明确的有界归零流程。
- 不要在电机运行中改写位置；不能靠把超时改成几十秒掩盖多圈回转。
- 到位条件除 `isRunning()==false` 外还应检查目标脉冲位置，定位预算应包含加减速。

验收：不同正反转周期、非整周期定时洗脱、六槽定位后的不同角度、正负累计多圈位置，均能在规定角度和时间内进入下一次注液；定位期间所有泵关闭。

### R04 / P2：正常甩干结束直接走强制停机路径

依据：[完成状态](D:/Codex/iot_control_center/firmware/instruments/lib/InstrumentCore/src/control.hpp:186)、[结束处理](D:/Codex/iot_control_center/firmware/instruments/src/washer.cpp:675)、[outputsOff](D:/Codex/iot_control_center/firmware/instruments/src/washer.cpp:130)。

最后一步甩干到时，核心立即置 `completed=true`，主循环随即拉低电机使能、关闭排液并 `forceStop()`。同一套路径同时用于紧急停止和正常结束，没有正常减速阶段。所用 FastAccelStepper 0.31.8 头文件明确区分了 `stopMove()` 的减速和 `forceStop()` 的无减速停止；停止发脉冲也不等于真实转子立即停止。

修改方法：增加正常 `Decelerating/Finishing` 阶段，先发正常减速，按已标定策略维持甩干排液，到控制器停止并完成规定收尾后才记录完成。故障及 STOP 保留明确的紧急停机处理，不应为了平滑停机而延迟必要断电。把“程序时间结束”和“允许人工操作”区分开。无转速反馈时不能声称已测得物理零速。

验收：最后一步直接甩干、甩干后等待、甩干后另一运动步骤，以及减速途中 STOP；检查使能、泵、完成事件的时序，并在空载硬件上测量实际停稳时间。

### R05 / P2：平台与固件程序校验不一致，可使整个目录停止更新

依据：[Python recipe](D:/Codex/iot_control_center/core/instruments.py:59)、[C++ validRecipe](D:/Codex/iot_control_center/firmware/instruments/lib/InstrumentCore/src/control.hpp:90)、[目录大小校验](D:/Codex/iot_control_center/core/instruments.py:107)、[设备目录容量](D:/Codex/iot_control_center/firmware/instruments/include/program_catalog.hpp:46)。

已确认两个例子：

- 仅一个显式 Home 步骤的平台程序可以校验、发布，但设备要求至少两个步骤。由于同步是全量原子替换，该程序会使同公司整份目录被拒绝，其他有效程序也无法更新。
- 平台仅检查 JSON 不超过 24,576 字节，不检查设备程序条数和解码内存。本机真实结构 `sizeof(Recipe)=636`，当前设备代码容量为 77；80 个简单 Home+Wait 程序仅 13,751 字节，平台允许而设备拒绝。应以目标编译器结果和协议能力为准，不能把本机结构大小当永久协议常量。

修改方法：建立共享的有效/无效 JSON 契约样例，同时喂给 Python 编译器、C++ 网络目录解析器和本地恢复解析器。固件上报 schema、最大步骤、目录字节及条数能力；发布前校验目标目录是否可装入。平台显示期望目录摘要、设备已应用摘要、最近同步错误和时间，不能只显示“支持自动同步”。保持全量失败保留旧目录，不静默截断，也不要恢复“三个程序上限”。

验收：单 Home、自动 Home 后边界步骤数、空目录、容量边界和超限目录；所有端接受/拒绝结论一致；一个无效草稿或发布失败不影响已工作的目录。

### R06 / P2：加热器实时上传的输出状态被通信暂停污染

依据：[snapshot 读取引脚](D:/Codex/iot_control_center/firmware/instruments/src/heater.cpp:91)、[先关输出再拍快照](D:/Codex/iot_control_center/firmware/instruments/src/heater.cpp:256)、[平台写入输出状态](D:/Codex/iot_control_center/models/iot_instrument.py:232)。

每次实时交换先 `heater.pause()`、关闭 GPIO，再调用 `snapshot()`。所以即时上报读到的是为 HTTPS 临时关闭后的输出；设备可能在两次通信之间正常加热，但平台经常显示 `Heater Output=false`。分钟历史样本可能记录 true，与实时字段不同，容易让使用者误判。

修改方法：在安全断电通信之前捕获带采样时间的控制快照，随后仍然关闭输出再执行阻塞通信。建议分别上报本地启用许可、温控需求、采样时输出、通信暂停原因和最近周期输出占比；界面明确显示“采样状态”，不伪装独立的电流或实际加热反馈。不能简单删除通信前断电措施。

验收：确有热需求时每次实时上报能表达通信前状态；网络超时期间引脚保持关闭，SW2 停止仍锁存；本地真正关闭、恒温断电与通信暂停能够区分。

### R07 / P2：离线日志没有运行前容量保障，写满会中途停流程

依据：[Journal::save](D:/Codex/iot_control_center/firmware/instruments/include/runtime.hpp:173)、[logEvent](D:/Codex/iot_control_center/firmware/instruments/src/washer.cpp:165)、[开始条件](D:/Codex/iot_control_center/firmware/instruments/src/washer.cpp:187)。

洗脱日志达到 128 条时 `healthy=false` 并停机，但启动只检查当前 healthy 标志，没有为本次运行预留容量。一次典型流程包含开始、步骤、等待、继续、完成，以及每次装片的请求和完成事件；几次离线运行就可能接近上限。之后会在某次步骤日志落盘时中止，可能已经注入液体。保护性停机本身应保留，缺的是可预期的容量管理。

加热器普通样本在总队列到 112 条时滚动淘汰。一分钟一个样本，在没有其他事件时约保留 112 分钟；不能把它理解为长期完整离线温度历史。

修改方法：提供队列剩余条数/字节和平台待补传状态；启动前为必要运行事件与终止事件预留空间。不足时在注液前阻止新运行并给出明确提示。进一步用分段追加日志或 SD 扩展保留量，普通观测与关键事件分开，允许明确统计的普通样本淘汰，不能静默删掉运行审计事件。针对无限次人工定位需单独规定日志预算，不能假设每次只点六次。

验收：队列 110/127/128 条、SD/Flash 空间不足、联网补传后恢复、断网多次运行；必须能解释停机原因并保留终止事件。空间不足不应到注液之后才首次发现。

### R08 / P2：洗脱仪晚接入的温度探头没有完成转换时间保障

依据：[启动分辨率设置](D:/Codex/iot_control_center/firmware/instruments/src/washer.cpp:646)、[固定 400ms 读取](D:/Codex/iot_control_center/firmware/instruments/src/washer.cpp:662)。

如果启动时未接探头，`setResolution(11)` 没有可配置的传感器。之后 `getAddress()` 找到新接入、仍为 12 位配置的 DS18B20，代码仍只等 400ms 就读并标记 `sampled=now`，没有重新配置分辨率或检查转换完成。12 位转换最长 750ms，11 位最长 375ms，见 [Analog Devices 官方数据手册](https://www.analog.com/media/en/technical-documentation/data-sheets/ds18b20.pdf)。因此不能保证这次取得的是已完成的新测量；具体错误表现需用实际探头验证。

修改方法：探头发现/重新确认后校验地址、供电模式和分辨率；异步等待转换完成或按实际分辨率设置足够截止时间。只在成功完成一次转换后更新采样时间；允许缺探头时继续定时洗脱，保持用户已确认的功能边界。可复用加热器更保守的 750ms 处理，但不要复制加热器“探头故障停洗脱”的策略。

验收：开机无探头后接入默认 12 位探头、探头中途断开和恢复、85 C 上电值、CRC 失败；不能把旧值重新盖上新时间。不会误中断纯定时洗脱。

### R09 / P2：冷启动离线记录丢失可恢复的相对时间信息

依据：[设备事件时间](D:/Codex/iot_control_center/firmware/instruments/include/runtime.hpp:166)、[读取/运行记录入库](D:/Codex/iot_control_center/models/iot_instrument.py:244)、[统计排除无时钟样本](D:/Codex/iot_control_center/models/iot_instrument.py:317)。

无可信时间时设备正确发送 `sampled_at=0`，同时提供 boot_id、seq、uptime_ms。然而读数和运行日志入库只保留 sampled_at/received_at，丢弃事件的 boot/seq/uptime；通用 receipt 只存摘要，不存原始载荷。这样即使设备同一次启动稍后联网校时，也失去了恢复离线事件时间轴的依据。加热器这些样本会永久排除于小时图，洗脱日志只能看到补传时间。

修改方法：保留每条关键记录的 boot_id、seq、扩展后的单调时间及 `time_quality`。记录同启动周期的可信校时锚点，在可证明的区间推算发生时间并标记为估算；处理 millis 回绕、重启和 NTP 跳变。无可靠锚点的事件保留相对时间，不冒充准确 UTC，更不能用 received_at 替代发生时间直接计入小时统计。

验收：断网冷启动运行、同一 boot 联网校时、跨 boot 补传、时钟跳变；运行顺序与时长可追溯，小时图明确显示缺测/估算质量。

### R10 / P2：配置应用与命令回执不是同一事务，掉电后可能回报相反结果

依据：[heater handleCommand](D:/Codex/iot_control_center/firmware/instruments/src/heater.cpp:123)、[Journal::remember](D:/Codex/iot_control_center/firmware/instruments/include/runtime.hpp:158)、[平台接受回执](D:/Codex/iot_control_center/models/iot_instrument.py:264)。

固件先把 `/command.json` 保存为 `rejected`，然后保存 `/targets.json`，最后才把回执改为 `applied`。如果在目标温度保存成功后、回执更新前掉电，重启会载入新目标，却把该命令报告为拒绝。这是两个文件分别原子写，并不构成跨文件事务。

修改方法：使用 `received/applying/applied/rejected` 等真实阶段；目标配置和对应 command_id/config_revision 一起原子保存。启动恢复时依据已保存配置核对未完成命令，生成正确回执，不盲目重放不可逆动作。将配置摘要带入状态和确认。OTA 同理区分“写入待重启”和“新固件已启动确认”，不要把刷写 API 成功当完整验收。

验收：在 intent 保存、配置替换、回执保存三个边界分别模拟掉电；设备实际生效配置与平台最终确认一致，且不会自动启用加热。

### R11 / P2：每次心跳永久写 receipt，长期数据增长缺少边界

依据：[每次 exchange 的 _claim](D:/Codex/iot_control_center/models/iot_instrument.py:208)、[receipt 模型](D:/Codex/iot_control_center/models/ingest_event.py:3)、[固件轮询](D:/Codex/iot_control_center/firmware/instruments/src/washer.cpp:452)。

每个唯一心跳也会新增 `iot.ingest.event`，未找到这个表的保留/压缩机制。按 5 秒一次估算，单台设备一天约 17,280 条、一年约 630 万条 receipt；实际频率受网络和目录同步影响。它与一分钟温度采样的业务数据量不是一回事。这是容量增长风险，不代表本次测到了数据库已变慢。

修改方法：分开实时状态心跳与需要长期幂等的业务事件。心跳可使用已验证的 boot/sequence 水位更新当前状态；观测、报警、命令和运行日志保留独立幂等键。制定可证明安全的重放窗口或归档机制，补充 instrument/time 组合索引和数据量指标。不能直接给 receipt 加短 TTL：老事件仍可能在设备/桥接队列中，删除去重证据后可能重复处理或触发唯一约束错误。

验收：大量空闲心跳不会无限产生无业务价值的永久行；关键事件重复、乱序和长期离线补传仍只处理一次。用隔离库解释查询计划和测量数据量，不用估算替代性能测试。

### R12 / P2：末尾人工等待完成后遗漏完成日志和运行标记清理

依据：[本地继续](D:/Codex/iot_control_center/firmware/instruments/src/washer.cpp:239)、[resume/advance](D:/Codex/iot_control_center/firmware/instruments/lib/InstrumentCore/src/control.hpp:186)、[主循环边沿检测](D:/Codex/iot_control_center/firmware/instruments/src/washer.cpp:670)。

平台允许在最后添加人工等待。此时 CONTINUE 在 `serialTick()` 内调用 `resume()`，直接把 `running` 改为 false；主循环稍后才取得 `before=washer.running`。因此用于写 completed 事件并删除 `/run.json` 的 `before && !washer.running` 条件不成立。界面可以显示完成，但日志只有 continued，运行标记还在，下次启动误报上次 power_loss。

本次用真实核心复现：`final_wait_resume=1 completed=1 main_loop_completion_branch=0`，结合调用次序确认漏处理路径。

修改方法：统一由运行生命周期组件处理终止事件，保证来自 tick、CONTINUE、STOP 或异常的状态迁移都产生一次且仅一次终止处理；避免只在主循环某一位置比较布尔边沿。完成事件确认落盘后才能清理运行标记，写入失败则保留可恢复证据。

验收：最后为 Wait、多个连续 Wait、正常末尾 Dry、重复 CONTINUE、写完成事件失败和随即断电；完成/中止事件恰好一次，真正完成后的重启不产生虚假 power_loss。

### R13 / P3：当前调试指南仍含已过期的功能状态

依据：[“只保存一个程序”](D:/Codex/iot_control_center/docs/INSTRUMENTS_V3_COMMISSIONING.md:47)、[“开机排液、多程序、循环数待实现”](D:/Codex/iot_control_center/docs/INSTRUMENTS_V3_COMMISSIONING.md:74)，与实际 `programs.json`、Startup 和 cycle 编译逻辑不一致。

修改方法：历史验收记录保留日期和历史含义；当前操作/调试手册维护单一功能矩阵，区分已实现、模拟通过、已刷入、带负载通过。同步适用的中英泰手册及 Knowledge；不以更新文档替代实际验收。

## 2. 科学性与架构判断

总体分层合理，建议保留并修正边界，不宜再做一次全模块推倒重写。设备实时执行、平台编制并版本化发布、完整目录原子同步、断网保留、显式本地启动、UTC 上报、配置和国家信息不写死、固件签名验证，这些方向都正确。低层核心能够脱离 MCU 测试，也是有价值的基础。

温升保护应继续使用用户要求的 600 秒、温升小于 1 C，恰好 1 C 不报警。目前实现计的是累计实际开启加热的时间；这比把网络停热也算成加热更符合功率投入，但它不保证按墙上时钟十分钟报警。需要在记录中同时显示实际加热时间和经过时间。该判据只能识别温升不足，不能证明有液或无液；若探头脱离液体但被附近热源加热，温升条件仍可能满足。液量、热功率、散热与探头安装必须通过标定来验证，不应让后续模型自行放宽阈值。

加热控制当前为 1 C 回差的开关控制：低于目标约 1 C 重新加热，达到目标断开。平台允许 0.25 C 的设定步进，并不代表实际恒温精度为 0.25 C。是否需要更窄回差、最短通断周期或 PID，应依据负载、热惯性和继电器/SSR 类型决定。暂不建议在缺少实测参数时直接上 PID。

洗脱使用定时泵量是合理的既有硬件方案，前提是对泵、管路、液体与扬程标定；PWM 150/255 或 50/255 不能解释成确定流量或精确电压。保留用户确认的原值，先验证再调整。

“正转 3 秒、反转 3 秒”的当前含义是每 3 秒改变目标方向。在 1 rev/s、1 rev/s² 下，从 +1 到 -1 的理想反转需要 2 秒，其中包含减速和反向加速。因此并非两个方向都各有 3 秒稳定转速。程序编辑器应写清楚计时含义，并对高转速/短换向间隔给出运动可达性检查。不要在修 BUG 时静默改变已经发布程序的计时含义。

OTA 已有签名、机型、尺寸和摘要检查，这是传输和镜像完整性的基础；双应用槽不自动等于启动失败回滚。可在后续阶段为 ESP32 完成启动自检、待确认版本和已验证的回滚机制；需核对 bootloader 配置，不能只调用一个确认 API 就宣称支持。ESP8266 需单独制定恢复方案，不能套用 ESP32 的双槽假设。

## 3. 给 GPT-5.6 的实施顺序

1. 基于本报告的 commit 先检查差异；建立会失败的 R01-R03 测试，然后修复残液恢复、确认快照和定位状态机。
2. 修复 R04-R06：正常停止流程、双端契约一致性、加热状态语义；继续保留原硬件输出参数和本地启动限制。
3. 修复 R07-R10 和 R12：容量预留、探头转换、离线时间、配置/回执恢复和统一运行终止处理。使用虚拟时钟、可注入故障的文件系统和模拟电机驱动验证，不操作实物来复现危险路径。
4. 完成 R11、R13 的平台容量治理、界面错误提示及文档同步。
5. 在 imytestth 新隔离库执行真实 Odoo 安装、升级、公司隔离和接口测试；再做授权范围内的设备空载验证。平台发布和固件硬件验收分开记录，部署/刷写按实施时用户指令执行。

建议把 `washer.cpp` 中的运动阶段、运行生命周期、目录同步提交、HMI 确认和日志存储抽成可注入依赖的小组件。先通过上述行为测试，再移动代码；不以拆文件数量或引入通用框架衡量架构质量。

共同验收要求：

- 新测试运行的是实际控制/协议代码，不是另一份重写的模拟逻辑；验证真实输出时序、配置内容和事件，而不只是搜索源码里的字符串。
- 同一组程序样例跨 Python/C++ 运行，覆盖正常、非法和容量边界；至少有一条典型完整程序贯穿编制、同步、确认、执行和日志。
- 不使用删除日志、关闭传感器检查、自动复位报警、允许远程启动、静默改已发布程序等方式让测试通过。
- 每项交付标注已修复、测试证据和剩余实机验证；保留未完成项，不把“编译成功”写成“功能实测完成”。

## 4. 本次验证与边界

- `python -m unittest discover -s core_tests -v`：71 项通过。
- `python tools/test_instrument_core.py`：526 个核心检查、168 个 UI 检查，以及 heater panel、washer setup、catalog 测试均通过。
- 对真实 C++ 核心追加一次性复现，确认 R01 的 Ready 保留/再次注液和 R05 的单 Home 拒绝；输出见各问题正文。
- 对真实 Display 类追加一次性触摸复现，确认 R02 同页程序变化后旧按压仍可确认。
- 对真实 Washer 核心及实际调用次序追加一次性复现，确认 R12 末尾 Wait 经 CONTINUE 结束后错过主循环完成分支。
- 运行真实 Python 契约，确认 R03 参数被接受、R05 单 Home 和 80 个短程序目录被接受。
- 其余结论来自源码调用链；DS18B20 时序同时核对了制造商资料。正常结束的真实转子惯性、传感器热插拔表现、低 PWM 泵启动能力和网络耗时没有做硬件测量。
- 本次没有重新执行服务器 Odoo 测试或固件构建，没有修改、推送或部署应用代码。现有测试通过没有覆盖上述跨组件时序与掉电边界，不能据此否定这些发现。

补充核验：审查中检查了“标准 Odoo 19 Datetime 是否必然截断收到的毫秒”的猜测。官方 [fields_temporal.py](https://raw.githubusercontent.com/odoo/odoo/19.0/odoo/orm/fields_temporal.py) 对传入的 naive datetime 可直接保留，不能据此指控继电器链路存在秒级截断；该猜测未列入缺陷。继电器同时间戳事件的排序仍可作为后续测试项目，但本报告不将它当作已证实的历史故障原因。
