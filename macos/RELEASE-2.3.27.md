# 2.3.27-macos.1 验收记录

2026-10-16，本机 Apple M2 Pro / 32 GB / macOS 27.2。官方基线为 [jb-v2.3.27](https://github.com/y-g-jiang/Jiangtherapee-Super-Resolution-World-Best/releases/tag/jb-v2.3.27)，Windows 归档 SHA-256 为 `70c16b20cdaa03530ba220ccbc4d597d8429e781b522b0e8e086f00fb421aec9`。

## 适配内容

- 更新三套官方后端与 JSR 网页资源，保持 v9.8 的 MPSGraph FP32 / 原生 Metal 融合路径。
- 从官方 `LibRaw_HE_Fixes_20261007.zip` 构建 arm64 解码库。
- 接入 Z8 预设与按拍摄时间分组的批量流程；每组重新选择黑场和满阱，保存独立标定审计。
- 三模式压缩 DNG 导出后复制实际参考帧 EXIF / Nikon 私有数据，更新输出尺寸、方向和文件哈希。
- 提供自带 Python、模型、ExifTool 和原生库的 Apple Silicon 便携包，最低 macOS 14。

## 已通过的验证

| 范围 | 结果 |
| --- | --- |
| Nikon Z6 III HE* 解码 | 14 张实拍 NEF；rawpy 与原生桥接解码逐像素一致 |
| Fast K14 | 14 帧全图；12128 × 8080，压缩 DNG 与线性 TIFF 逐像素一致 |
| Stormer | 7 帧，512 × 512 选区；1024 × 1024 普通及去鬼影输出，DNG 与对应线性 TIFF 一致 |
| v9.8 K14 | 14 帧全图、全新配准缓存；12128 × 8080，MPSGraph / Metal，压缩 DNG 可读回 |
| 压缩与元数据 | Compression=7；重打包像素核验通过，Nikon 镜头 / ISO / 拍摄时间保留；EXIF 写入不改变像素 |
| Z8 批量 | 两组合成 DNG（ISO 100 / 2000），先准备两组再顺序执行，标定和选择隔离、取消与重置通过 |
| 便携包协议 | Fast / v9.8 合成、DNG 读回、取消、拒绝不支持的选区模式通过 |
| 便携包 GUI | 三模式选片与预览通过；真实 NEF 的 Stormer 选区任务完成，参考帧 EXIF 写入成功 |
| 原生计算自检 | GUI 结构、网络和融合对照测试通过 |
| 单元检查 | 4 项发布适配测试和 3 项既有优化测试通过 |

v9.8 实拍全流程约 323 秒，DNG 从旧版未压缩约 588 MB 减至约 198 MB。此数据包含本次原生压缩与 EXIF 写入，不能作为同环境的新旧速度对比。

本机详细日志、输出和照片路径位于 Git 忽略的 `validation/release-2.3.27/`；公开记录不包含个人照片。

## 验证边界

Z8 批量测试用于验证控制流程和标定选择，没有 Z8 真实亮场画质验收。Stormer 实拍验证覆盖选区，尚未完成全图性能测试。此次保持三模式 JSR 应用范围，不包含 Windows 照片库或独立 DeepSeek 助手。便携应用采用 ad-hoc 签名，尚未进行 Apple 公证或其他型号 Mac 的测试。
