# JSR 17.3.1 与 Bridge 2.3.27 的差异

2026-10-22 检查官方 [jsr-v17.3.1](https://github.com/y-g-jiang/Jiangtherapee-Super-Resolution-World-Best/releases/tag/jsr-v17.3.1)，发布时间为台北时间 2026-10-18 21:53。归档 `JSR_V17.3.1.zip` 共 517,284,175 字节，SHA-256 为 `3509347135e2513b95104fa545da2479fdf23262aa26135249b245075cd7fef5`，与 GitHub asset digest 一致。

重建权重未更新；主要算法变化是 Stormer 配准，主要工作流变化是撤回机型内置黑场与专用批量。以下结论来自归档 README、实际 UI、Python 3.10 模块语义指纹与真实 RAW 运行日志。

| 项目 | Bridge 2.3.27 | 独立 JSR 17.3.1 |
| --- | --- | --- |
| 产品与界面 | Bridge 照片管理中的 JSR 面板 | 独立 JSR，三模式页签；默认推荐 Stormer 7 帧，支持逐张添加 RAW |
| 网络权重 | Stormer、Fast K14、K14 | 共同 `.npz` 资源及外置 Fast 权重散列相同；训练步数仍为 Fast 36864、K14 24500 |
| Stormer 配准 | SPyNet 光流路径 | 全局单应＋曝光/高光掩膜的自适应多项式残差场，上限四次；同一连续坐标映射用于恢复和去鬼影 |
| 内置标定 | Z8 内置黑场与专用批量 | README 明确因黑场漂移撤回 Z8/S5II 预设、机型选择条和专用多组界面；实际资源与界面均已撤回 |
| K14 输入 | 旧 Mac 版允许未提供黑场 | 新官方界面与 README 要求黑场；Mac GUI、IPC 与 CLI 同步要求 |
| Stormer / Fast 标定 | 黑场或手动参数 | 保留，PTC/FWC 自动匹配、两级选择和 ISO 满阱插值继续提供 |
| RAW 解码 | Nikon HE 2026-10-07 修复 | `libraw-build.json` 的库、解码器及桥接散列完全相同；沿用对应源码和 arm64 构建 |
| 输出 | 无损压缩 DNG 与参考帧元数据 | 保留；Mac 每次使用独立任务目录和 processing.log |

## 配准机制与证据

新入口安装 `v15_2.masked_alignment`，新增 `masked_fit`、`masked_local`、`masked_geometry_cpu`。原有 `v15_2.pipeline` 模块本身语义指纹未变，入口在运行时替换配准函数和几何类型；只更新权重或旧 pipeline 文件会漏掉此次算法变化。

新几何表示直接在 RAW 查询位置计算连续参考帧→源帧坐标；去鬼影网格由同一解析场生成。局部导引使用曝光和逐帧、逐 CFA 饱和信息屏蔽不可靠观测，残差拟合允许在证据不足时降阶。本机 512 × 512 实拍选区的六个配准对均记录 `poly2`，日志为 `Masked quartic pair`，不能把本次运行理解为始终使用四次多项式。

旧版的网络训练权重、K14 网络/融合模块及 Fast 主体保持一致。更新可改变运动估计和融合采样，具体画质变化受场景运动、饱和与有效拟合样本分布影响；本次读回验证证明输出完整性，没有以像素差异替代画质评价。

## 分发材料的冲突

归档的 `jsr_backend_manifest.json` 仍残留 `bridge_version=2.3.27`、`z8_dark_preset=true`、`jsr_batch_enabled=true` 和旧 `build_flavor` 等字段；它同时追加了 `jsr_standalone_version=17.3.1`、新配准字段。对是否启用预设和批量，以新版 README、实际缺失的预设资源、隐藏且没有可选值的 UI 为准。

17.3.1 包未附上它所声明的 `ThirdPartySources/LibRaw_HE_Fixes_20261007.zip`。同一 decoder 的材料仍可从官方 Bridge 2.3.27 获取，其 SHA-256 为 `7e7bb2dc8f54098c0b488572cfd6adea4adf29d162353b3f0c155a2b1f1fdc94`；Mac 包继续携带该完整源码与许可证。

## Mac 适配

独立分支 `codex/macos-17.3.1` 更新三后端和原始界面，保留 K14 的原生 MPSGraph / Metal 执行器。Stormer 原入口将 `wgpu` 放到 Python 搜索路径前面；提取时将本版 PYZ 的 `v15_2` 模块同步到该目录，避免旧嵌入包遮蔽新版配准。

删除原 Z8 预设和专用批量运行代码；相机 PTC 匹配独立保留。GUI 在完整 7/14 帧输入后解析，未满组时仅保存路径；支持增量选片、去重和本机文件拖放。K14 缺少黑场在启动计算前拒绝。DeepSeek 助手仍未移植。

完整本机静态材料位于 Git 忽略的 `vendor/inspect-17.3.1/`：模块/资源 SHA-256、语义比较、原始说明、GUI 资源与配准符号记录。验收结果见 [17.3.1 验收记录](RELEASE-17.3.1.md)。
