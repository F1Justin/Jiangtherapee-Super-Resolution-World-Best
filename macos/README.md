# Jiangtherapee Bridge — Apple Silicon / Metal

三个后端均从官方 Bridge 2.3.9 Windows 包提取原始 Python 3.10 字节码与模型权重，使用本机 arm64 Python、OpenCV 和 Metal 执行。v9.8 默认采用原生 MPSGraph FP32 Controller / GreenFiLM RArm；融合默认采用原生 Metal FP32 前段，特征和 qmap 保留在 GPU。Fast 和 Stormer 使用原版 WGPU Metal。Nikon Z6 III High Efficiency* NEF 使用仓库提供的 Nikon HE 补丁重新编译 LibRaw 0.22.2，并接入本机 RAW 桥接库。

## 启动

独立 portable 包使用 `JSR Bridge.app`，并提供同目录的 `jsr` CLI 和 `启动 GUI.command`。完整目录解压后可移动；Python、模型、原生库与 ExifTool 随包携带。要求 Apple Silicon 与 macOS 14 及以上。输出、配准缓存和处理日志写入用户选择的输出目录。

```sh
./jsr doctor --gui-test --self-test
./jsr fast --help
./jsr stormer --help
./jsr v98 --help
```

本地预览包采用 ad-hoc 签名，Apple 公证尚未完成。第三方许可和 LibRaw 源码/补丁保存在包内。构建入口为 `macos/.venv/bin/python macos/build_portable.py`，产物写入忽略目录 `macos/dist`。打包后的运行过程使用同包依赖。私有运行产物与源码发布范围保持本地，公开 Release 由作者确认。

新版 GUI 复用官方 Windows 2.3.9 包内的 HTML、CSS 与 JavaScript，由系统 WKWebView 承载。原版三模式选择、RAW 文件列表与预览、Stormer 框选、参数、PTC / 色彩配置搜索、输出选项、日志、进度、停止与打开结果接入本机后端。作者支持入口与 QQ 群信息保留。JSR 页面独立运行。

Fast / Stormer 使用匹配暗场或手动标定。界面的读噪声单位为 DN，Fast 入口换算为归一化单位。手动参数由用户填写；0 DN / 20000 e⁻ 是验收测试参数。v9.8 沿用已验证的自动处理路径，采用 MPSGraph / Metal；其线性 DNG 当前为无压缩编码。三个模式保留照片旋转标记。预览按传感器原始方向显示，Stormer 以同一参考帧的坐标执行局部处理。

每次运行在所选输出目录创建独立任务目录，并保存 `processing.log`。停止操作结束计算进程组，已有输出保留在任务目录。应用退出时结束后台计算。GUI 通过应用内消息与本地 JSON 行协议通信。

原版网页资源位于忽略目录 `vendor/original-ui`，由 `extract_original_ui.py` 校验官方 ZIP 后提取。`build_web_ui.py` 对 v9.8 校准路径、DNG 说明与停止文案执行版本锁定的适配。原始资产与模型仅进入本地 portable 产物。

## 真实 RAW 测试

2026-10-03，Apple M2 Pro、32 GB 内存、macOS 27.2、arm64 Python 3.10.16、Metal。输入为用户提供的 14 张 Nikon Z6 III NEF，6064 × 4040，ISO 2000，1/750 秒，High Efficiency*。

| 模式 | 实测范围 | 输出 | 耗时 |
| --- | --- | --- | --- |
| Fast K14 | 全部 14 帧、全图 | 12128 × 8080 DNG / TIFF | 381.7 秒 |
| Stormer | 前 7 帧、512 × 512 选区 | 1024 × 1024，去鬼影与保留鬼影两组 DNG / TIFF | 52.8 秒 |
| v9.8 K14 · 原版 WGPU | 全部 14 帧、全图、已准备配准缓存 | 12128 × 8080 线性 DNG / 彩色 TIFF | 1926.4 秒 |
| v9.8 K14 · Apple FP32，256 分块 | 全部 14 帧、全图、已准备配准缓存 | 12128 × 8080 线性 DNG / 彩色 TIFF | 487.0 秒 |
| v9.8 K14 · Apple FP32，384 分块 · 第一轮 | 全部 14 帧、全图，从 RAW 解码 / 配准开始 | 12128 × 8080 线性 DNG / 彩色 TIFF | 409.4 秒进程总耗时 |
| v9.8 K14 · Apple FP32，原生 GPU 前段 · 第二轮 | 全部 14 帧、全图，从 RAW 解码 / 配准开始 | 12128 × 8080 线性 DNG / 彩色 TIFF | **249.4 秒进程总耗时** |

第二轮于 2026-10-04 完成验收，冷启动总耗时缩短 39.1%，纯重建 193.1 秒。全图最大差异 1 DN，RMSE 0.007374 DN，暗部、通道、拼接边界与关键元数据全部通过。实现、参数和逐项测量见 [第二轮优化说明](OPTIMIZATION.md)。

Fast 与 Stormer 的 DNG 解码像素和相应 TIFF 完全一致。测试参数为黑电平 1008 DN、读噪声 0、满阱 20000 e⁻；用户已授权使用测试参数。Stormer 全图耗时尚待实测，界面提供完整原版全图路径。

v9.8 原版 WGPU 的纯重建耗时 1864.8 秒，其中 GreenFiLM RArm 精修为 1594.4 秒。原版 900 秒重建速度门槛记录为 `FAIL`，功能运行状态为 `COMPLETE`。DNG 经 TIFF 解码器和 LibRaw RGB 后处理读回，尺寸、16-bit 数据及旋转标记验证通过。彩色 TIFF 与相机线性 DNG 分属不同色彩空间。当前 v9.8 DNG 为无压缩无损文件，约 588 MB。

Apple FP32 的相同缓存全图测试耗时 487.0 秒，整次重建与导出提速 3.96 倍。纯重建 470.8 秒，原版 900 秒门槛为 `PASS`。全部 2.94 亿个颜色样本中，99.9943% 与原版相同，其余最大差值 1 DN，RMSE 为 0.00757 DN；暗部 RMSE 为 0.00628 DN。Orientation、BlackLevel、WhiteLevel、ColorMatrix1、AsShotNeutral 和 PhotometricInterpretation 均相同。峰值进程 RSS 为 6.40 GiB，单个原生网络执行器记录的最大 Metal 分配为 1.63 GiB。

384 分块性能档在空缓存下完整运行 409.4 秒，纯重建 346.0 秒，相对原版纯重建提速 5.39 倍。峰值进程 RSS 为 9.46 GiB，原生网络最大 Metal 分配为 3.27 GiB。全图最大差值仍为 1 DN，RMSE 为 0.00735 DN，全部关键元数据相同。进程总耗时涵盖 RAW 解码、配准、重建、导出与旋转标记写入。

v9.8 的原版 Metal `tanh` 在大正数输入下溢出为 NaN。移植入口采用等价稳定公式；独立 GPU 测试与 NumPy 的最大绝对误差为 1.19 × 10⁻⁷。原版模型、卷积和融合权重保留。Windows CPU 扩展路径有明确运行检查，融合执行器与网络执行器由后端选择确定。

合成 14 帧验证覆盖新解码、全局/稠密配准、原版 K14 模型、精修与导出。最新状态见 `ACCEPTANCE.json`，完整运行数据在 `validation`。

## Apple Silicon 优化

`native/graph_bridge.mm` 将 Controller U-Net 和 GreenFiLM RArm 编译为完整 MPSGraph。卷积采用 NHWC，模型权重按原版 OIHW 转换，整网在单次调用中执行。网络采用共享 Metal 缓冲区；Controller 输入与 qmap 在原生 GPU 前段驻留，RArm 在末端读回 RGB。原版权重文件、GELU 近似、稳定 FiLM tanh、颜色变换与精修逻辑保留。FiLM 默认执行等价仿射合并，K14 的零投影权重编译为带原始偏置的常量。

计算采用 FP32；macOS 26 及以上显式关闭 reduced-precision fast math。本机测试为 macOS 27.2，动态库最低构建目标为 macOS 13。RArm 开始执行时释放已完成融合阶段的 Controller 工作空间。自适应分块按运行开始时的可用内存选择 256 / 384 / 512 原生像素，融合保留 48 像素 halo，精修独立采用 24 像素 halo。`JSR_METAL_TILE=256` 等环境变量可固定分块，用于重复基准。可用内存达到 32 GiB 时选择 512；物理内存达到 24 GiB 且可用内存达到 10 GiB 时选择 384；其余选择 256。本机 384 性能档通过全尺寸冷启动验证。

macOS 导出使用 APFS 写时复制，减少大尺寸浮点中间文件的实际磁盘写入；其他文件系统回退到普通复制。运行入口检查导出空间并记录峰值 RSS、Metal 分配及最低空闲磁盘。

384 分块性能档与原版回归路径：

```sh
JSR_METAL_TILE=384 macos/.venv/bin/python macos/run_v98.py ...
JSR_METAL_NETWORKS=wgpu macos/.venv/bin/python macos/run_v98.py ...
```

独立网络基准保留同一模型权重并比较原版 WGPU 输出，覆盖非方形尺寸、双批次与不同输入范围：

```sh
macos/.venv/bin/python macos/benchmark_metal.py --network rarm --frames 14 --size 864 --output macos/validation/rarm.json
macos/.venv/bin/python macos/benchmark_metal.py --network controller --frames 14 --size 96 --output macos/validation/controller.json
```

M2 Pro 上，864 × 864 RArm 单次推理从 7.309 秒降到 0.860 秒，提速 8.50 倍；输出最大浮点误差 2.28 × 10⁻⁶。完整 RAW 验收比较相机线性 DNG 的全部像素、暗部和元数据，记录在 `BENCHMARK.json`。Fast 和 Stormer 的原版网络路径已适配 Metal，原生网络加速范围为 v9.8。

## 上游集成

公开核心的独立验证和作者应用的接入接口见 [上游集成说明](INTEGRATION.md)。

平台桥接、原生图执行器、分块调度、导出资源管理与验证工具作为独立模块提交。作者在应用源码中接入这些接口后，可直接构建 macOS 后端。当前 ZIP 提取入口验证已发布版本，字节码调度常量有严格契约检查。原版产品报告中的 WGPU 路由字段保留为发布包契约；`macos_port` 记录实际 Controller、RArm 和融合执行器。

本机照片、完整报告及包含本机路径的 `ACCEPTANCE.json` 由 Git 忽略；公开 `BENCHMARK.json` 保存脱敏性能和精度结果。独立 portable 应用包含运行环境，并采用 ad-hoc 签名。公开应用发布还需 Apple 公证与 macOS arm64 CI。

## 重新准备

先安装 Xcode Command Line Tools 或 Xcode，以及 Homebrew 的 `brotli`、`cmake`、`ninja`、`jpeg-turbo`、`little-cms2` 和 `exiftool`，然后在仓库根目录执行：

```sh
uv python install 3.10
uv venv --python 3.10 macos/.venv
uv pip install --python macos/.venv/bin/python -r macos/requirements.txt
macos/.venv/bin/python macos/prepare.py /absolute/path/Jiangtherapee-Bridge-2.3.9-Windows-x64.zip
macos/.venv/bin/python macos/prepare_modes.py /absolute/path/Jiangtherapee-Bridge-2.3.9-Windows-x64.zip
macos/.venv/bin/python macos/build_native.py
macos/.venv/bin/python macos/build_metal.py
macos/.venv/bin/python macos/extract_original_ui.py
macos/.venv/bin/python macos/build_portable.py
```

PyPI 安装可指定 `--index-url https://pypi.tuna.tsinghua.edu.cn/simple`。字节码使用 Python 3.10，WGPU 使用 0.31.0。`Core-Only-Source-Code` 的 Python 3.12 验证环境独立保留。

官方 ZIP SHA-256：`66367390fd0efdc46002411b9117685716258d3bed0571ac74ecbe83d2c31c06`。提取文件的散列记录在各后端 `manifest.json`。构建脚本校验 LibRaw、CMake 源码包和本仓库 Nikon HE 补丁，并对本机动态库签名。原始包、提取模块、模型和生成库保存在 Git 忽略的 `vendor`，许可证沿用仓库 `Third-Party-Licenses` 与提取资源中的文件。

## 命令行

三个入口保留各自原版参数：

```sh
macos/.venv/bin/python macos/run_fast.py --help
macos/.venv/bin/python macos/run_stormer.py --help
macos/.venv/bin/python macos/run_v98.py --help
```

Fast 可传 `--inputs` JSON 路径数组或重复 `--raw-frame`，GPU / 主存默认预算分别为 4 / 12 GB；手动参数 `--black` 是 DN，`--read-noise` 是归一化值。

Stormer 可传重复 `--raw-frame`，`--backend Metal --grid 256 --memory-gb 4`，以及暗场或 `--developer-mode --read-noise-dn ... --black-level-dn ... --full-well-electrons ...`。`--roi X Y WIDTH HEIGHT` 提供原版局部处理。

v9.8 使用重复 `--raw-frame`，并指定 `--cache-mode memmap --prepare-mmap-cache --resource-mode balanced --camera-profile-source libraw --out-dng on --out-tiff on --out-png off`，生成原版流式对齐缓存。缓存保存在输出目录，可重复使用。

macOS 的 OpenCV 使用 GCD，由系统调度线程；`--cpu-cores` 约束 Fast 解码计划。验收报告记录实际线程信息与 Metal 设备。

## 独立通用优化

FiLM 折叠、精修 halo 选择和 CPU 分块缓存通过[通用优化 PR #3](https://github.com/y-g-jiang/Jiangtherapee-Super-Resolution-World-Best/pull/3) 提供。该模块合并后默认启用；本后端单独安装时使用原始 FiLM、halo 48 和原始 CPU 分块调度。此目录的最优性能记录包含通用优化和 Apple 后端。接入方式见 `INTEGRATION.md`。
