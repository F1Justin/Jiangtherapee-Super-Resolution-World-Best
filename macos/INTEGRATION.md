# 上游集成接口

此目录提供可选的 Apple Silicon 后端。现有 Windows 入口和公开 WGPU 网络保持现有默认行为。作者可以在完整应用源码中选择后端，并直接接入原生执行器与融合会话。

## 通用优化接入

FiLM 折叠、精修 halo 选择和 CPU 分块复用位于[通用优化 PR #3](https://github.com/y-g-jiang/Jiangtherapee-Super-Resolution-World-Best/pull/3)。通用模块合并后，v9.8 的 MPSGraph 入口默认启用 FiLM 折叠、halo 24 和 CPU 分块缓存。仅安装本后端时，默认使用原始 FiLM、halo 48 和原始 CPU 分块调度；原生 GPU 前段和 MPSGraph 网络继续可用。显式请求通用优化参数时须先安装通用模块。GPU 上传及缓冲区复用由本后端实现。

## 公开核心独立验证

原生网络验证直接加载 `Core-Only-Source-Code/weights` 中的模型和校验清单。此路径只使用公开源码、公开权重和新建原生库。

```sh
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r Core-Only-Source-Code/requirements.txt psutil
.venv/bin/python macos/build_metal.py
.venv/bin/python Core-Only-Source-Code/check_macos.py --frames 14 --network-backend mpsgraph
.venv/bin/python macos/benchmark_metal.py --network controller --frames 14 --size 96
.venv/bin/python macos/benchmark_metal.py --network rarm --frames 14 --size 96
```

构建需要 Apple Silicon macOS 和 Xcode Command Line Tools 或 Xcode。`.venv` 是独立核心验证环境；`macos/.venv` 是完整发布包运行环境。后者使用 Python 3.10，准备步骤见 `README.md`。

## 网络接口

将后端选择放在创建网络实例的位置。两种工厂保留现有网络的宿主侧变换和调用接口：

```python
from wgpu_unet_tiled import TiledUNet
from wgpu_greenfilm_rarm import GreenFiLMTiledRArm
from metal_graph import controller_class, rarm_class

controller = controller_class(TiledUNet)(controller_weights)
rarm = rarm_class(GreenFiLMTiledRArm)(rarm_weights)
```

`controller.forward(feature_chw)` 返回 FP32 的 36 通道 CHW 数组。`rarm.forward_residual_batch(input_nchw)` 返回 FP32 的 N×3×H×W 数组。现有 `factorized` 接口保留原版颜色与幅度变换。应用结束时调用 `close()`；融合结束后可以调用 Controller 的 `release_workspaces()`。

精确形状图缓存和内存预算由 `metal_graph.py` 管理。FiLM 合并由独立通用优化贡献的 `Core-Only-Source-Code/reconstruction_optimizations.py` 实现；`JSR_METAL_FOLD_FILM=1` 在创建 RArm 时启用，原始权重文件保持原样。

## GPU 驻留融合接口

`NativeTapSession` 接收以下数据：

| 数据 | FP32 / 整数布局 |
| --- | --- |
| 协方差 | `(height*2*width*2, 3)` FP32，按输出像素排列 |
| RAW 分块 | `(K_chunk, NF, MF)` FP32，使用原版 255 信号单位 |
| CFA | `(NF, MF)` int32，R/G/B 编码 0/1/2 |
| 参考 flow | `(K_chunk, N, M, 2)` FP32，dx/dy 顺序 |
| shift | `(K_chunk, 4)` FP32，yshift/xshift/NK/MK |
| 局部归一化 | `CachedLocalV7Frontend`，原版 Gaussian 和 151 通道 mean/std |

同一块内按原版顺序传入所有帧，随后复用这些分块执行 learned merge：

```python
from native_fusion import NativeTapSession

with NativeTapSession(covariance, y0r, x0r, height, width, N, M) as session:
    for frames, cfa, flow, shift in chunks:
        session.accumulate_phase(frames, cfa, flow, shift)
    phase, legacy = session.phase_and_legacy(k_used)
    feature, _ = session.frontend(frontend)
    qmap = session.controller(controller)
    session.begin_learned(qmap, 5.0)
    for frames, cfa, flow, shift in chunks:
        session.accumulate_learned(frames, cfa, flow, shift)
    learned = session.learned_merge(k_used)
```

`chunks` 是可重复遍历的同一组分块。`phase`、`feature`、`qmap` 是 GPU 资源令牌；`legacy` 在 `learned_merge()` 完成后填充。最终返回两张 HWC FP32 RGB，后续 LCA、精修、高光和导出沿用应用原有流程。

融合上下文保持 48 原生像素。八块网络、TTA1 的精修上下文可独立采用 24 原生像素；数学半径和全图边界验证见 `OPTIMIZATION.md`。作者在调度源码中直接设置这两个独立参数即可。

当前实现每次驻留一块，在同一 Metal 队列异步提交统计、局部特征、Controller 与 learned merge；块结束时等待并检查有限值和颜色支持。上传缓存、统计缓冲区与图输出由会话保持有效。

## 发布包兼容入口与验证范围

`prepare.py`、`prepare_modes.py`、`run_fast.py`、`run_stormer.py` 和 `run_v98.py` 提供 JSR 17.3.1 完整流程的兼容运行方式。准备脚本从用户提供、校验过散列的官方 Windows ZIP 中提取 Python 3.10 字节码及资源。运行钩子与字节码调度常量对应这个固定发布版本。作者源码集成采用上面的显式调用接口。

照片、提取字节码、额外模型、生成库、虚拟环境和完整运行产物由 Git 忽略。`BENCHMARK.json` 保存脱敏数据。完整 RAW 验证使用私人拍摄的 14 张 Nikon Z6 III HE* 照片；其他相机和其他 Apple 芯片的结果通过相同工具测量。Fast 验证了全图，Stormer 验证了两种去鬼影配置的选区，v9.8 验证了全图及原版像素比较。

`build_app.py` 生成当前源码环境的本地启动器。独立发行包需要作者选定的环境打包、签名和发布流程。第三方 LibRaw 对应源码采用官方发布包的 LibRaw_HE_Fixes_20261007.zip，散列锁定位于 release.py，项目新增代码的许可由维护者明确后纳入发布规则。
