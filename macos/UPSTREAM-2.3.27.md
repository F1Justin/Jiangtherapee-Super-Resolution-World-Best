# Bridge 2.3.27 拆包对比

检查日期：2026-10-16。基线为本机 macOS 移植使用的官方 Windows Bridge 2.3.9，目标为最新正式发布 jb-v2.3.27。

结论：网络和模型权重保持不变，更新集中于 Nikon HE 解码、标定、高光与白电平、输出可靠性，以及 Z8 工作流。未做新版真实 RAW 重建或性能测试，不能据此断言整体画质或速度提升多少。

## 下载与证据

- [正式发布](https://github.com/y-g-jiang/Jiangtherapee-Super-Resolution-World-Best/releases/tag/jb-v2.3.27)，发布时间 2026-10-15 04:31:55（台北）。
- 本地包：`macos/vendor/Jiangtherapee-Bridge-2.3.27-Windows-x64.zip`，625,762,408 bytes。
- SHA-256：`70c16b20cdaa03530ba220ccbc4d597d8429e781b522b0e8e086f00fb421aec9`，与 GitHub API digest 和[官方更新服务](https://y-g-jiang.github.io/update.json)一致。
- 拆包证据：`macos/vendor/inspect-2.3.27/`，含两版 README、后端 manifest、应用模块反汇编、文件及模块哈希 `comparison.json`、`semantic-summary.txt` 和新版嵌入 UI。
- 静态解析 PyInstaller 归档和 Python 3.10 code object，没有执行下载包中的程序或字节码。模块比较排除路径和行号，比较指令、常量、参数及符号，避免把构建差异误判成逻辑变化。
- 上游 main 已 fetch 到 `a3af142`；从本地 main `6ab0f5b` 到新版只改 README，共 2 行增加、1 行删除。实质应用更新在发布包内。

## 已核实的变化

### 1. 模型没有换

两版共同文件中，外置 Fast K14 `weights.npz`、SPyNet，以及后端嵌入的 Stormer 各尺寸网络、v9.8 Controller / RArm 等全部 `.npz` 资源 SHA-256 一致。manifest 中 v9.8 仍是 BEST24500，Fast 仍是 step 36864。不能把版本号增长理解成重新训练了超分模型。

### 2. Nikon HE / HE* 解码和白电平修复

新增 `ThirdPartySources/LibRaw_HE_Fixes_20261007.zip`，内含可读 C++ 对应源码。说明记录 precinct 的 12-byte 边界修复、失败向上传播，以及 JPEG XS 解码相关修正；本地旧 LibRaw 与新源码的 HE 解码文件确有内容差异。

新解码器保留识别阶段的白电平，不再统一强设 16383。Z f ISO100 14-bit HE 在通用 ADC 上限场景使用已验证的 15892 DN profile 白电平；明确给出的白电平、其他机型和 ISO 不按这一值覆盖。不能直接把此回退套用到 Z6 III。

这是 macOS 现有 Nikon HE 解码器应优先评估的更新；说明中的 Adobe 对照验证属于上游自述，本次没有复跑。

### 3. 黑场标定和 Stormer 高光保护

Stormer 的 `v15_2.dark / raw_input / physical / pipeline` 和 `sensor / ptc / whitepoint` 等模块逻辑发生变化。新增 `Physical.guard_fully_clipped`，其内嵌 WGSL 根据最短曝光的饱和状态建立下界，并检查其他可靠未饱和样本是否冲突；符合条件时对预测做下界保护。这属于融合后处理变化，可以影响极亮区域结果，即使权重不变。

新版 manifest 还记录：黑场在 unpack 后测量，保留各 CFA 相位像素；黑场 DN 统计量按各亮场归一化跨度换算；只有坐标一致才传递空间黑场，否则使用各 CFA 标量偏置。白平衡缺失、坏可选 EXIF、未知机型显式 profile 等输入容错也有更新。

Fast K14 应用逻辑变化集中在 `fast_calibration / fastk14_app / v15_2.dark / v15_2.pipeline`，新增 `raw_metadata`。主要网络、配准与重建模块语义指纹未变。

### 4. 输出链路修复

Stormer 的 `backend / dng_repack / output_chain / bridge_preview / color_profile` 等模块更新。v9.8 K14 仅 `exp_rawmerge / fast_gated_cm_png` 两个模块语义指纹发生变化；网络推理模块保持不变。

manifest 声明的修复包括：v9.8 后处理直接消费已完成产品，避免再次走旧融合/精修；DNG 采用补齐边缘的无损 JPEG 分块布局；预览缩小前保留白端点。Stormer 可以一次保存普通和去鬼影两套 DNG，共用 RAW 解码与配准。

上面输出修复的模块变化已经核实，具体成像效果仍需真实 RAW 对照。旧版 macOS v9.8 当前使用无压缩 DNG，新版 Windows 的压缩链路不会自动带入本机实现。

### 5. Z8 专用标定与批量

实际新增 102 个 Z8 黑场 DNG：三种压缩（无损、HE*、HE）× 34 档 ISO 32–102400。包内说明称来自 408 张黑场、每档四张，条件为 FX、14-bit、1/1000 秒。按本组 ISO 与压缩模式匹配，FWC 在相邻已知 ISO 的满阱数值之间做线性插值，表外使用端点。

新增 `jsr-batch.js` 和后端 `batch_bridge`。Z8 界面支持目录递归扫描，以相邻拍摄间隔不超过 5 秒分组，默认选择各组前 7/14 张，逐组重建并显示批次。其他机型的界面批量仍关闭。

Z8 DNG 输出按本组实际参考帧保留 EXIF、镜头、机身及 Nikon 私有数据；包内提供 Adobe MakN 结构的 metadata 壳，不覆盖重建像素与校准信息。上述范围来自随包 README、manifest 与 UI，未在 Windows 实跑。

### 6. DeepSeek 助手

新增独立助手、联网、脚本工具和 sleep 能力，需用户提供 API Key。包内有使用说明及多份 assistant UI 资源。这是工作流功能，与重建模型更新无关。

## 对现有 macOS 移植的影响

建议移植顺序：先评估 HE 解码与白电平修复，再同步黑场归一化、Stormer 高光保护及输出修复，最后考虑批量、Z8 预设和助手。

现有 `prepare.py / prepare_modes.py / extract_original_ui.py` 锁定 2.3.9 校验值、目录和 UI 地址；不应仅更换版本号或覆盖 vendor 字节码。尤其原生 Metal/MPSGraph 路径需要核查新前后处理逻辑是否被绕过，再使用同一批真实 RAW 比较高光、暗部、DNG 元数据与耗时。

此次仅完成下载、拆包和分析，现有运行时与 macOS app 未升级。
