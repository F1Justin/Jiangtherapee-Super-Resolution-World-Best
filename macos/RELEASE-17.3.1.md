# 17.3.1-macos.1 验收记录

2026-10-22，官方基线 [jsr-v17.3.1](https://github.com/y-g-jiang/Jiangtherapee-Super-Resolution-World-Best/releases/tag/jsr-v17.3.1)。原始归档 SHA-256：`3509347135e2513b95104fa545da2479fdf23262aa26135249b245075cd7fef5`。拆包机制和分发材料差异见 [上游分析](UPSTREAM-17.3.1.md)。

## 本版变化

- 同步独立版三模式界面、后端和 Stormer 高光掩膜残差配准；K14 保留 MPSGraph FP32 / 原生 Metal。
- 同步官方撤回 Z8/S5II 内置黑场和专用批量的决定，保留通用 PTC/FWC 自动匹配及 ISO 插值。
- K14 在 GUI、IPC、CLI 中要求实际适用的黑场。Fast / Stormer 保留黑场或手动参数。
- 支持逐张添加、未满组暂存、本机文件拖放；保留压缩 DNG、参考帧 EXIF 和 Nikon 私有数据。
- 三套网络权重及 LibRaw 解码器身份与 2.3.27 一致；对应源码和许可随包携带。

## 本轮验证

| 检查 | 结果 |
| --- | --- |
| 官方归档身份 | 下载字节数、SHA-256 与 GitHub asset digest 一致 |
| 后端提取 | 三后端均可加载；Stormer 实际导入新版 masked_alignment，解决 wgpu 搜索路径遮蔽 |
| Stormer 实拍 | Z6 III HE*，前 7 帧，原生 512 × 512 选区；普通、去鬼影两套 1024 × 1024 DNG/TIFF，进程约 29.38 秒 |
| 输出读回 | 两套 DNG Compression=7，与对应线性 TIFF 逐像素一致；LibRaw 读回、方向及参考帧 EXIF 写入通过 |
| 实际配准 | 六个配准对记录 Masked quartic，适应性拟合为 poly2；未运行 SPyNet |
| 成品 GUI | 3 模式选片和启动就绪检查通过；K14 无黑场时禁用启动，选择后恢复；页面无脚本错误 |
| 单元检查 | 8 项通过，覆盖 PTC 满阱插值、未知机型、黑场必填、撤回预设拒绝、未满组不解码与已有优化检查 |
| 便携打包 | arm64 自包含依赖、无未解析绝对库路径，ad-hoc 签名验证通过 |

Stormer 4 GB 显式预算试跑触发内存保护，按官方默认 6 GB 重跑完成。用户要求停止重建后，本轮 Fast 14 帧全图回归被 SIGTERM 中止（进程 323.24 秒，exit -15），不计为通过。未继续运行 K14 重建、最终 GUI 任务或 GPU 自检。

本版不声称完成三模式全图画质回归；上一版的完整测试见 [2.3.27 验收记录](RELEASE-2.3.27.md)。本机详细日志与照片位于 Git 忽略的 `validation/release-17.3.1/`，不进入发布资产。

便携应用面向 Apple Silicon / macOS 14+，采用 ad-hoc 签名，未 Apple 公证。未移植 DeepSeek 助手。
