"""Compare native FP32 fusion stages against release WGPU/NumPy stages."""
import argparse
import json
from pathlib import Path
import time

import numpy as np


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    import os
    os.environ['JSR_NATIVE_FUSION'] = '0'
    from run_v98 import configure
    configure()
    import wgpu_multik_stream_v1 as stream
    import local_v7_frontend as frontend
    import wgpu_unet_tiled
    import wgpu_buf as gb
    import sys
    sys.path.append(str(Path(__file__).resolve().parent.parent / "Core-Only-Source-Code"))
    from weights import weight_paths, load_npz
    from native_fusion import NativeTapSession
    root = Path(__file__).resolve().parent / 'vendor/v98/wgpu_v81_assets'
    local = frontend.CachedLocalV7Frontend(root / 'local_v7_static_affine_v1.npz')
    weights = load_npz(weight_paths(14)['controller'])
    model = wgpu_unet_tiled.TiledUNet(weights)
    rng = np.random.default_rng(641)
    reports = []
    for h, w, k in [(17, 19, 1), (24, 27, 14)]:
        n, m = h + 8, w + 8
        frames = rng.uniform(0, 180, (k, n, m)).astype(np.float32)
        ci = np.array([[0, 1], [1, 2]], np.int32)[np.arange(n)[:, None] % 2, np.arange(m)[None, :] % 2]
        flow = rng.normal(0, .15, (k, n, m, 2)).astype(np.float32)
        shift = np.tile(np.array([0, 0, n, m], np.float32), (k, 1))
        cov = np.tile(np.array([1, .1, 1.1], np.float32), (h * w * 4, 1))
        differences = {}

        def compare(name, ref, actual, atol):
            d = actual.astype(np.float64) - ref.astype(np.float64)
            result = {'max_abs': float(np.max(np.abs(d))), 'rmse': float(np.sqrt(np.mean(d * d))),
                      'atol': atol, 'passed': bool(np.array_equal(ref, actual) if atol == 0 else np.allclose(ref, actual, atol=atol, rtol=2e-4))}
            differences[name] = result
            if not result['passed']:
                raise AssertionError(f'{name}: {result}')

        with stream.StreamingTapSession(cov, 4, 4, h, w, n, m) as original, \
                NativeTapSession(cov, 4, 4, h, w, n, m) as native:
            for start in range(0, k, 4):
                chunk = (frames[start:start+4], ci, flow[start:start+4], shift[start:start+4])
                original.accumulate_phase(*chunk)
                native.accumulate_phase(*chunk)
            phase, legacy = original.phase_and_legacy(k)
            native.phase_and_legacy(k)
            compare('phase144', phase[:144], native.debug(0)[:144], 0)
            compare('legacy', legacy, native.debug(1), 0)
            feature, _ = local.make_controller_input(phase, legacy)
            native.frontend(local)
            compare('feature', feature, native.debug(0), 2e-5)
            reference_qmap = model.forward(feature)
            native.controller(model)
            compare('controller', reference_qmap, native.debug(2), .0002)
            native.debug_qmap(reference_qmap)
            original.begin_learned(gb.upload(reference_qmap), 5.0)
            native.begin_learned(__import__('native_fusion').NativeFeatures(native, 36), 5.0)
            for start in range(0, k, 4):
                chunk = (frames[start:start+4], ci, flow[start:start+4], shift[start:start+4])
                original.accumulate_learned(*chunk)
                native.accumulate_learned(*chunk)
            expected = original.learned_merge(k)
            actual = native.learned_merge(k)
            compare('learned_same_qmap', expected, actual, 3e-5)
            reports.append({'native_shape': [h, w], 'k': k, 'stages': differences,
                            'metrics': json.loads(native._lib.jsr_fusion_metrics(native._handle))})
    model.close()
    args.output.write_text(json.dumps({'passed': True, 'cases': reports}, indent=2))
    print(args.output)


if __name__ == '__main__':
    main()
