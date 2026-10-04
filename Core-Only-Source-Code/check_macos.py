"""Verify the published JSR networks on native Apple Silicon with synthetic inputs."""

from __future__ import annotations

import argparse
import json
import os
import platform
import time

import numpy as np

from local_v7_frontend import CachedLocalV7Frontend, local_amplitude, make_controller_input
from weights import load_npz, weight_paths
import wgpu_buf as gb
from wgpu_greenfilm_rarm import GreenFiLMTiledRArm
from wgpu_rarm_tiled import CONV_WGSL, TTA1_CODES
from wgpu_unet_tiled import TiledUNet


def check_convolution(rng: np.random.Generator) -> float:
    import wgpu

    source = rng.normal(size=(2, 8, 10)).astype(np.float32)
    weight = rng.normal(size=(3, 2, 3, 3)).astype(np.float32)
    bias = rng.normal(size=3).astype(np.float32)
    padded = np.pad(source, ((0, 0), (1, 1), (1, 1)))
    windows = np.lib.stride_tricks.sliding_window_view(padded, (3, 3), axis=(1, 2))
    expected = np.einsum("ihwkl,oikl->ohw", windows, weight) + bias[:, None, None]
    device = gb.dev()
    pipeline = device.create_compute_pipeline(
        layout="auto",
        compute={"module": device.create_shader_module(code=CONV_WGSL), "entry_point": "main"},
    )
    buffers = [gb.upload(item) for item in (source, weight, bias, np.zeros_like(expected))]
    uniform = device.create_buffer_with_data(
        data=np.asarray([1, 2, 3, 8, 10, 3, 0, 0, 80, 18, 0, 0], np.uint32).tobytes(),
        usage=wgpu.BufferUsage.UNIFORM,
    )
    try:
        bind = gb.bind(pipeline, [*buffers, uniform])
        encoder = device.create_command_encoder()
        compute = encoder.begin_compute_pass()
        compute.set_pipeline(pipeline)
        compute.set_bind_group(0, bind)
        compute.dispatch_workgroups(3, 1, 1)
        compute.end()
        device.queue.submit([encoder.finish()])
        actual = buffers[-1].numpy()
        np.testing.assert_allclose(actual, expected, rtol=2e-5, atol=2e-5)
        return float(np.max(np.abs(actual - expected)))
    finally:
        for buffer in buffers:
            buffer.destroy()
        uniform.destroy()


def validate_output(value: np.ndarray, shape: tuple[int, ...]) -> dict:
    if value.shape != shape or not np.isfinite(value).all():
        raise RuntimeError(f"Invalid network output: {value.shape}; expected {shape}")
    return {"shape": list(value.shape), "min": float(value.min()), "max": float(value.max())}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frames", type=int, choices=range(1, 15), default=4)
    parser.add_argument("--network-backend", choices=['wgpu', 'mpsgraph'], default='wgpu')
    args = parser.parse_args()
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        parser.error("Run with an arm64 Python on macOS")
    os.environ["WGPU_BACKEND_TYPE"] = "Metal"
    if args.network_backend == 'mpsgraph':
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'macos'))
        from metal_graph import rarm_class, controller_class
        global GreenFiLMTiledRArm, TiledUNet
        GreenFiLMTiledRArm = rarm_class(GreenFiLMTiledRArm)
        TiledUNet = controller_class(TiledUNet)
    rng = np.random.default_rng(20261003)
    adapter = gb.info()
    if adapter.get("backend_type") != "Metal":
        raise RuntimeError(f"Expected Metal adapter, got {adapter}")
    paths = weight_paths(args.frames)
    error = check_convolution(rng)
    height, width = 32, 40
    legacy = rng.uniform(0.1, 0.6, (height, width, 3)).astype(np.float32)
    phase = rng.uniform(0.0, 0.1, (144, height, width)).astype(np.float32)
    feature, _ = make_controller_input(phase, legacy, paths["static_affine"])
    cached_feature, _ = CachedLocalV7Frontend(paths["static_affine"]).make_controller_input(phase, legacy)
    np.testing.assert_allclose(feature, cached_feature, rtol=2e-5, atol=2e-5)
    controller = TiledUNet(load_npz(paths["controller"]))
    start = time.perf_counter()
    control = controller.forward(feature)
    controller_seconds = time.perf_counter() - start
    control_stats = validate_output(control, (36, height, width))
    # RAW-to-Tap fusion is absent from the published source; RefineNet gets a separate fixture.
    rgb = np.ascontiguousarray(legacy.transpose(2, 0, 1))
    refine_input = np.concatenate((rgb, rgb), axis=0)
    refine = GreenFiLMTiledRArm(load_npz(paths["refinenet"]))
    try:
        start = time.perf_counter()
        result = refine.factorized(refine_input, local_amplitude(legacy), TTA1_CODES)
        refine_seconds = time.perf_counter() - start
        refine_stats = validate_output(result, (3, height, width))
    finally:
        refine.close()
    print(json.dumps({
        "status": "passed",
        "scope": "synthetic core inference; complete RAW pipeline available through macos launchers",
        "network_backend": args.network_backend,
        "python": platform.python_version(),
        "architecture": platform.machine(),
        "adapter": adapter,
        "frames": args.frames,
        "convolution_max_abs_error": error,
        "frontend_parity": "passed",
        "controller": dict(control_stats, first_forward_seconds=controller_seconds),
        "refinenet": dict(refine_stats, first_forward_seconds=refine_seconds),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
