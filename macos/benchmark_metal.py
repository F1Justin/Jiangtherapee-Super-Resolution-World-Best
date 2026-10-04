"""Compare original WGPU and native FP32 MPSGraph RefineNet outputs and warm latency."""
from pathlib import Path
import argparse
import json
import os
import sys
import time

import numpy as np

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / 'Core-Only-Source-Code'))
os.environ['WGPU_BACKEND_TYPE'] = 'Metal'
from wgpu_greenfilm_rarm import GreenFiLMTiledRArm
from metal_graph import rarm_class
from weights import load_npz, weight_paths


def difference(actual, expected):
    delta = actual.astype(np.float64) - expected
    report = {'max_abs': float(np.abs(delta).max()), 'rmse': float(np.sqrt(np.mean(delta * delta)))}
    np.testing.assert_allclose(actual, expected, atol=2e-5, rtol=2e-4)
    assert report['rmse'] < 2e-6
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--size', type=int, default=128)
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--frames', type=int, choices=range(1, 15), default=14)
    parser.add_argument('--network', choices=['rarm', 'controller'], default='rarm')
    parser.add_argument('--output', type=Path, default=ROOT / 'validation/metal-benchmark.json')
    args = parser.parse_args()
    from wgpu_unet_tiled import TiledUNet
    from metal_graph import controller_class
    kind = args.network
    checkpoint = weight_paths(args.frames)['refinenet' if kind == 'rarm' else 'controller']
    weights = load_npz(checkpoint)
    original_type = GreenFiLMTiledRArm if kind == 'rarm' else TiledUNet
    original = original_type(weights)
    optimized = (rarm_class if kind == 'rarm' else controller_class)(original_type)(weights)
    forward = (lambda model, value: model.forward_residual_batch(value)) if kind == 'rarm' else (lambda model, value: model.forward(value))
    rng = np.random.default_rng(20261003)
    import hashlib
    report = {'network': kind, 'frames': args.frames, 'precision': 'float32',
              'checkpoint': checkpoint.name, 'checkpoint_sha256': hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
              'reduced_precision_fast_math': False, 'parity': []}
    try:
        shapes = [((1, 6, 19, 23), 0.5), ((2, 6, 24, 32), 1.0), ((1, 6, 31, 35), 2.0)] if kind == 'rarm' else [((151, 19, 23), 0.1), ((151, 24, 32), 0.5), ((151, 31, 35), 1.0)]
        for shape, scale in shapes:
            inputs = rng.uniform(-0.05, scale, shape).astype(np.float32)
            expected = forward(original, inputs)
            actual = forward(optimized, inputs)
            report['parity'].append({'shape': list(shape), **difference(actual, expected)})
        shape = (1, 6, args.size, args.size) if kind == 'rarm' else (151, args.size, args.size)
        inputs = rng.uniform(0, 1, shape).astype(np.float32)
        start = time.perf_counter()
        expected = forward(original, inputs)
        reference_first = time.perf_counter() - start
        start = time.perf_counter()
        actual = forward(optimized, inputs)
        native_first = time.perf_counter() - start
        report['benchmark_parity'] = difference(actual, expected)
        for name, executor in [('wgpu', original), ('mpsgraph', optimized)]:
            samples = []
            for _ in range(args.repeats):
                start = time.perf_counter()
                forward(executor, inputs)
                samples.append(time.perf_counter() - start)
            report[name] = {'seconds': samples, 'median_seconds': float(np.median(samples))}
        report.update({'size': args.size, 'wgpu_first_seconds': reference_first,
                       'mpsgraph_first_seconds': native_first,
                       'native_contract': optimized.contract,
                       'native_metrics': json.loads(optimized._lib.jsr_graph_metrics(optimized._handle)),
                       'speedup': report['wgpu']['median_seconds'] / report['mpsgraph']['median_seconds']})
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2))
        print(json.dumps(report, indent=2), flush=True)
    finally:
        if hasattr(original, 'close'):
            original.close()
        optimized.close()


if __name__ == '__main__':
    main()
