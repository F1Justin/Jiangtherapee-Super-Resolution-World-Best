"""Compare fusion stages on an existing real RAW alignment cache."""
import argparse
import json
from pathlib import Path
import sys

import numpy as np


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    import os
    os.environ['JSR_NATIVE_FUSION'] = '0'
    from run_v98 import configure
    configure()
    sys.path.append(str(Path(__file__).resolve().parent.parent / 'Core-Only-Source-Code'))
    from weights import weight_paths
    import wgpu_v81_reconstructor as recon
    import local_v7_frontend as local
    from native_fusion import NativeTapSession, NativeFeatures
    paths = weight_paths(14)
    model = recon.WgpuV81Reconstructor(paths['controller'], paths['static_affine'], paths['refinenet'])
    bayers, flows, grey, cfa = [np.load(args.cache / (name + '.npy'), mmap_mode='r')
        for name in ('bayers', 'flows', 'ref_grey', 'cfa')]
    original_frontend = local.CachedLocalV7Frontend.make_controller_input
    stored = {}

    def host_frontend(self, phase, legacy):
        result = original_frontend(self, phase, legacy)
        stored['feature_reference'] = result[0].copy()
        return result

    local.CachedLocalV7Frontend.make_controller_input = host_frontend
    reports = []
    original_session = recon.multik_stream.StreamingTapSession
    try:
        for top, left in [(0, 0), (1500, 2500), (3500, 5500)]:
            recon.multik_stream.StreamingTapSession = original_session
            local.CachedLocalV7Frontend.make_controller_input = host_frontend
            original = model.merge_tile(bayers, flows, grey, cfa, np.arange(14), top, left, 64, 64, 48)

            def gpu_frontend(self, phase, legacy):
                result = phase.session.frontend(self)
                stored['feature_native'] = phase.session.debug(0)
                return result

            local.CachedLocalV7Frontend.make_controller_input = gpu_frontend
            recon.multik_stream.StreamingTapSession = NativeTapSession
            controller = model.controller
            forward = controller.forward_buffer
            controller.forward_buffer = lambda feature: feature.session.controller(controller)
            try:
                actual = model.merge_tile(bayers, flows, grey, cfa, np.arange(14), top, left, 64, 64, 48)
            finally:
                controller.forward_buffer = forward
            entry = {'top_left': [top, left], 'stages': {}}
            for name, ref, value in [('feature', stored['feature_reference'], stored['feature_native']),
                    ('learned', original[0], actual[0]), ('legacy', original[1], actual[1])]:
                delta = value.astype(np.float64) - ref.astype(np.float64)
                entry['stages'][name] = {'max_abs': float(abs(delta).max()),
                    'rmse': float(np.sqrt(np.mean(delta * delta))), 'exact_fraction': float(np.mean(ref == value))}
                if name != 'feature':
                    dn = np.rint(ref * (65535 / 255)).astype(np.int32)
                    dn_actual = np.rint(value * (65535 / 255)).astype(np.int32)
                    d = dn_actual - dn
                    entry['stages'][name]['quantized_max_dn'] = int(abs(d).max())
                    entry['stages'][name]['quantized_rmse_dn'] = float(np.sqrt(np.mean(d.astype(np.float64)**2)))
            reports.append(entry)
        args.output.write_text(json.dumps(reports, indent=2))
        print(json.dumps(reports, indent=2))
    finally:
        recon.multik_stream.StreamingTapSession = original_session
        local.CachedLocalV7Frontend.make_controller_input = original_frontend
        model.controller.close()
        model.rarm.close()


if __name__ == '__main__':
    main()
