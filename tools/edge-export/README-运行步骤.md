# 端侧模型与云端同源对拍 · 运行步骤单

本目录只放**新增文件**，不改 `models/`、不改 `backend-python/`。
目标：把 `models/ml-v2-vis3k.json` 这份随机森林原样搬到端侧，并拿出可复现的实验证据说明
"端侧算出来的 p，和云端参考实现算出来的 p 是同一个数"。

一句话结论（本机已实测，见 `端侧对拍-实验报告.md`）：
同一份 C 代码在 2000 组真实观测特征上，与 `backend-python/ml/forest.py` 的最大偏差
**6.953e-07**（容差 1e-4），判决一致率 **100%**。

---

## 0. 文件清单

| 文件 | 作用 | 谁生成 |
| --- | --- | --- |
| `export_forest.py` | 模型 JSON -> C 源码，含导出前后自检 | 手写 |
| `forest_model.h` / `forest_model.c` | 展平后的森林数据（const，约 497 KiB） | `export_forest.py` |
| `edge_infer.h` / `edge_infer.c` | 端侧推理接口与实现（纯 C99，无递归、无 malloc） | 手写 |
| `edge_esp32.ino` | ESP32 固件：自检 + 串口一问一答 + 耗时汇总 | 手写 |
| `edge_x86_main.c` | Plan B 宿主程序：同一份 C 代码编成 x86 可执行 | 手写 |
| `build_x86.bat` | 用 MSVC（或 gcc）编译上面的宿主程序 | 手写 |
| `gen_cases.py` | 从真实观测序列构造 1000 组 26 维特征 | 手写 |
| `cases.csv` | 1000 行 × 26 列（全国 319 城，含 975 条非三站样本） | `gen_cases.py` |
| `cases-metar3.csv` | 1000 行 × 26 列（只用三站 ZYTX/ZYCC/ZYHB 周边） | `gen_cases.py --stations-only` |
| `cases_meta.json` / `cases-metar3-meta.json` | 抽样口径、来源指纹、p 分位数 | `gen_cases.py` |
| `pair_check.py` | 读用例 -> 跑 Python 参考 -> 读端侧回传 -> 出报告 | 手写 |
| `edge_x86_log.txt` / `edge_x86_metar3_log.txt` | Plan B 的原始输出（证据，别删） | `edge_x86.exe` |
| `out/parity-*.csv` / `out/parity-*.json` | 逐条对比明细与汇总 | `pair_check.py` |

约定：所有命令都在**仓库根目录**下执行；`git bash` 里路径用正斜杠。

---

## A. 装工具链（ESP32 这条路）

### A1. 装 arduino-cli

官方下载页：`https://github.com/arduino/arduino-cli/releases`
取 `arduino-cli_<版本>_Windows_64bit.zip`，解压出 `arduino-cli.exe`，放到一个进了 `PATH` 的目录。

国内网络下 GitHub Releases 经常只有几 KB/s，按下面任一方式取：

```
# 方式一：国内镜像站（地址随站点变动，以站点当期公告为准，不要照抄旧文档）
#   常见做法是把 releases 域名整体替换成镜像前缀，例如：
#   https://<镜像前缀>/https://github.com/arduino/arduino-cli/releases/download/<版本>/arduino-cli_<版本>_Windows_64bit.zip

# 方式二：给 arduino-cli 配代理（Go 写的，认 HTTP_PROXY/HTTPS_PROXY）
export HTTPS_PROXY=http://127.0.0.1:7890
export HTTP_PROXY=http://127.0.0.1:7890
```

验证：

```
arduino-cli version          # 需要 >= 0.34（config add / board details 这两条命令要靠它）
```

### A2. 装 ESP32 核心（含国内镜像）

```
arduino-cli config init
```

随后二选一：

```
# 官方索引（espressif.github.io 通常可直连）
arduino-cli config add board_manager.additional_urls \
  https://espressif.github.io/arduino-esp32/package_esp32_index.json
```

```
# 国内镜像索引（官方索引拉不动时的替代；地址以镜像站当期公告为准）
arduino-cli config add board_manager.additional_urls \
  https://arduino.me/packages/esp32.json
```

然后：

```
arduino-cli core update-index
arduino-cli core install esp32:esp32
arduino-cli core list                     # 应看到 esp32:esp32  <版本> 已安装
```

只想装指定版本（材料要写清版本号时用这条）：

```
arduino-cli core install esp32:esp32@2.0.17
```

> 说明：镜像索引只解决"索引文件 + 核心包"的下载路径，工具链里的 xtensa 编译器等仍是
> 从索引里给的地址下载。若卡在工具链下载，仍要回到代理方案（方式二）。

### A3. 装 CH340 驱动（本机 COM7 状态 Unknown 的根因）

COM7 能列出来但状态是 Unknown，几乎都是 USB 转串口驱动没装好。

1. WCH 官方下载页：`https://www.wch.cn/downloads/CH341SER_EXE.html`（打不开就搜 `CH341SER.ZIP`）。
2. 解压后以管理员身份运行 `SETUP.EXE`，点"安装"，看到"驱动预安装成功"即可。
3. 拔插一次板子，`设备管理器 -> 端口(COM 和 LPT)` 应出现 `USB-SERIAL CH340 (COMx)`，前面没有黄色感叹号。
4. 再验证：

```
arduino-cli board list
# 期望看到类似：COM7  USB VID:PID=1A86:7523  serial  USB Serial  esp32:esp32:esp32
```

状态从 `Unknown` 变成 `esp32:esp32:esp32`（或至少不再是 Unknown），才说明驱动和识别都通了。
仍是 Unknown 时按顺序排查：换 USB 数据线（有些线只有电源）、换 USB 口（避开前置面板与 Hub）、
关掉占用该串口的程序（串口助手、另一个 `arduino-cli monitor`、`pair_check.py`）。

### A4. 编译与烧录

Arduino 要求 **草图目录名与 .ino 同名**，而我们的目录叫 `edge-export`、.ino 叫 `edge_esp32.ino`，
所以先拼一个合规的草图目录（这一步不能省，否则报 `Sketch ... must be in a folder named the same`）：

```
cd <仓库根目录>
mkdir -p tools/edge-export/build/edge_esp32
cp tools/edge-export/edge_esp32.ino \
   tools/edge-export/edge_infer.c tools/edge-export/edge_infer.h \
   tools/edge-export/forest_model.c tools/edge-export/forest_model.h \
   tools/edge-export/build/edge_esp32/
```

编译（模型数组约 497 KiB，必须放大 app 分区，否则报 `Sketch too big`）：

```
arduino-cli compile --fqbn "esp32:esp32:esp32:PartitionScheme=huge_app" \
  tools/edge-export/build/edge_esp32
```

> 若报 `unknown option: PartitionScheme`，先查这块板子真实的选项名：
> `arduino-cli board details -b esp32:esp32:esp32`，把 `PartitionScheme` 换成列表里实际那个，
> 值取 `huge_app`（3 MB APP / 无 OTA）。

烧录（把 COM7 换成你的口）：

```
arduino-cli upload -p COM7 --fqbn "esp32:esp32:esp32:PartitionScheme=huge_app" \
  tools/edge-export/build/edge_esp32
```

看串口（先确认板子活着）：

```
arduino-cli monitor -p COM7 -c baudrate=921600
```

正常开机应看到（数值必须与 Plan B 完全一致）：

```
# MODEL alc-forest-v1 ml-v2-vis3k fp=7a7fc34a92babc78
# model=ml-v2-vis3k fp=7a7fc34a92babc78 trees=100 features=26 nodes=24111 leaves=24211 calib=92 bytes=509106 checks=OK
# DEFAULTS_P 0.048425
# READY
```

`# DEFAULTS_P 0.048425` 这一行是三处交叉校验里最快的一处：它把"全 defaults 向量"这一条
固定输入在板子上跑一遍。**本机 x86 版实测也是 0.048425**，数不一样就说明烧进去的不是这份模型。

### A5. 失败排查表

| 现象 | 原因 | 处置 |
| --- | --- | --- |
| `arduino-cli board list` 里 COM7 状态 `Unknown` | CH340 驱动未就绪 | 按 A3 装 `CH341SER`，换线换口 |
| `core install` 卡住 / `403` / `timeout` | 索引或工具链下载被墙 | 换镜像索引（A2），或设 `HTTPS_PROXY` |
| `Sketch ... must be in a folder named the same` | 目录名与 .ino 名不一致 | 按 A4 复制到 `build/edge_esp32/` |
| `Sketch too big` / app 分区不足 | 默认分区只给 app 1310 KiB | `PartitionScheme=huge_app` |
| `undefined reference to edge_predict` | `.c` 没和 `.ino` 在同一目录；或 C/C++ 混编 | 确认 `edge_infer.c` 在同一目录；`edge_infer.h` 已有 `extern "C"` |
| `forest_model.h: No such file` | 头文件没复制进草图目录 | 按 A4 的 cp 再执行一次 |
| 串口输出乱码 | 波特率不一致 | 监视器与固件都用 921600 |
| 开机只打 `# SELF_CHECK_FAILED` | 模型数组被改坏 / 编译目标不一致 | 重跑 `export_forest.py`，不要手改 `forest_model.c` |
| `pair_check.py` 第一条就超时 | 固件卡在自检失败，或串口被占用 | 先用 `arduino-cli monitor` 手工确认 `# READY` |

---

## B. 跑对拍（真板子）

三步，缺一不可。**用例必须先于板子准备好**，因为固件是按行被动应答的。

```
cd <仓库根目录>

# B1 生成 1000 组用例（固定随机种子，任何人重跑结果相同）
python tools/edge-export/gen_cases.py
#   期望结尾：[OK] 分布检查通过：极差 0.942921，p>=0.3 有 728 组，可以进入对拍。

# B2 装 pyserial（只在这一步需要；--input 日志模式不需要）
python -m pip install pyserial -i https://pypi.tuna.tsinghua.edu.cn/simple

# B3 跑对拍：一问一答，逐条比对
python tools/edge-export/pair_check.py --cases tools/edge-export/cases.csv \
  --port COM7 --baud 921600
```

期望看到（数字与 Plan B 应当一致，只有 `us` 不同）：

```
端侧自报模型   : alc-forest-v1 ml-v2-vis3k fp=7a7fc34a92babc78
端侧自检       : model=ml-v2-vis3k ... checks=OK
用例数         : 1000

原始概率 p(POS) 一致性（容差 1e-04）：
  max|Δp|      : <1e-06 量级>   PASS
  mean|Δp|     : <1e-07 量级>
  超差组数     : 0 / 1000

判决一致率（p >= 0.3 视为 POS）：1000/1000 = 100.0000%
单次耗时（端侧）：min .. / p50 .. / mean .. / max ..  us
[PASS] 端云同源：1000 组用例全部在 1e-04 容差内。
```

注意事项：

- **必须一问一答**。一次性把 1000 行灌进串口会撑爆 256 字节 UART 接收缓冲，丢行之后得到的是
  "对拍失败"的假象；`pair_check.py` 已经是锁步实现，不要自己另写批量发送。
- ESP32 的 `micros()` 分辨率是 1 us，单条耗时只能看量级；**均值**（1000 条平均）才是可用数字。
- 想留档就重定向：`python ... > out/esp32-run.txt 2>&1`，再把 `out/esp32-run.txt` 交给报告。
- 三站口径那一组同理，把 `--cases` 换成 `tools/edge-export/cases-metar3.csv` 即可。

---

## C. Plan B：工具链装不上时，用同一份 C 代码在等价编译目标上验证

这不是退让，是可辩护的替代方案：编的是**同一份** `edge_infer.c` + **同一份** `forest_model.c`，
只换编译目标。对外表述就写"同一份 C 代码在等价编译目标上验证"，不要写成"已上板实测"。

```
cd <仓库根目录>/tools/edge-export

# C1 编译 x86 宿主（优先 MSVC，找不到就找 gcc）
cmd //c build_x86.bat
#   期望：[OK] edge_x86.exe built with MSVC (manual environment)

# C2 跑一遍用例，落盘
./edge_x86.exe cases.csv > edge_x86_log.txt

# C3 对拍（不走串口，读日志）
cd <仓库根目录>
python tools/edge-export/pair_check.py --input tools/edge-export/edge_x86_log.txt
```

本机已实测通过，用的是 `MSVC 14.44.35207`（`/O2 /std:c11`），x64 目标：

```
max|Δp|  6.953e-07（全国 1000 组）  5.727e-07（三站 1000 组）   超差 0 / 1000
p50 单次耗时 3 us（同一台 PC 上 Python 参考实现是 137 us）
```

说明两点，免得别人踩：

- `build_x86.bat` 不直接调 `vcvars64.bat`，而是自己拼 `PATH/INCLUDE/LIB`。原因是 `vcvars64.bat`
  会 call `reg.exe`；在某些受限环境里 `reg.exe` 被策略拦住，它**静默失败**，`INCLUDE` 空着，
  编译器就报 `cannot open stdio.h` —— 看起来像工具链坏了，其实只是环境没配。
- `.bat` 文件必须是 **CRLF** 行尾、且只用 ASCII。UTF-8 中文注释在 GBK 代码页下会被 cmd 解析坏，
  甚至把 `if` 块吃掉。中文说明因此全部放在本文件里。

---

## D. 复现清单（评委/队友照着敲一遍即可）

```
cd <仓库根目录>

python tools/edge-export/export_forest.py            # 导出 + 自检（应打 PASS）
python tools/edge-export/gen_cases.py                # 1000 组用例 + 分布检查
python tools/edge-export/gen_cases.py --stations-only \
  --out tools/edge-export/cases-metar3.csv \
  --meta tools/edge-export/cases-metar3-meta.json    # 三站口径 1000 组

cd tools/edge-export && cmd //c build_x86.bat && cd ../..   # 编译 x86 宿主
tools/edge-export/edge_x86.exe tools/edge-export/cases.csv > tools/edge-export/edge_x86_log.txt
python tools/edge-export/pair_check.py --input tools/edge-export/edge_x86_log.txt \
  --cases tools/edge-export/cases.csv --tag national

# 有板子时，把上面最后一步换成：
python tools/edge-export/pair_check.py --cases tools/edge-export/cases.csv \
  --port COM7 --baud 921600
```

三处必须一致的指纹：

| 位置 | 指纹 |
| --- | --- |
| `export_forest.py` 打印的"指纹" | `7a7fc34a92babc78` |
| 固件/宿主开机第一行 `fp=` | `7a7fc34a92babc78` |
| `pair_check.py` 的"端侧自报模型" | `7a7fc34a92babc78` |

指纹不一致就是"跑的不是这份模型"，先解决这个再谈一致性。
