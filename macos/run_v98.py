"""Run v9.8 K14 with native FP32 networks, Metal merge and an arm64 RAW bridge."""
from pathlib import Path
import os
import platform
import sys
import types


def configure():
    if os.environ.get('JSR_MACOS_CONFIGURED') == str(os.getpid()):
        return
    if platform.system() != 'Darwin' or platform.machine() != 'arm64' or sys.version_info[:2] != (3, 10):
        raise SystemExit('Use macos/.venv/bin/python (arm64 Python 3.10)')
    root = Path(__file__).resolve().parent / 'vendor' / 'v98'
    sys._MEIPASS = str(root)
    sys.path.insert(0, str(root))
    os.environ['WGPU_BACKEND_TYPE'] = 'Metal'
    os.environ['JSR_WGPU_BACKEND'] = 'Metal'
    os.environ['OPENBLAS_NUM_THREADS'] = '1'
    import cv2
    cv2.setNumThreads(4)
    import numba
    original_njit = numba.njit

    # Sourceless release modules have no source path for Numba's disk cache.
    def njit(*args, **kwargs):
        kwargs['cache'] = False
        return original_njit(*args, **kwargs)

    numba.njit = njit
    networks = os.environ.get('JSR_METAL_NETWORKS', 'mpsgraph')
    if networks not in ('mpsgraph', 'wgpu'):
        raise ValueError('JSR_METAL_NETWORKS must be mpsgraph or wgpu')
    if networks == 'mpsgraph':
        from optimization_support import generic_optimizations
        optimized = generic_optimizations() is not None
        os.environ.setdefault('JSR_METAL_FOLD_FILM', '1' if optimized else '0')
        os.environ.setdefault('JSR_RARM_HALO', '24' if optimized else '48')
        os.environ.setdefault('JSR_NATIVE_FUSION', '1')
        from metal_graph import install
        install()
        from metal_platform import install_tile_profile
        os.environ['JSR_METAL_PROFILE'] = __import__('json').dumps(install_tile_profile())
        from refine_schedule import install as install_refine_schedule
        install_refine_schedule()
    import srhq_joraw2
    srhq_joraw2.BUILD_ID = 'jsr-macos-arm64-libraw-0.22.2-nikon-he'
    library = root.parent / 'libraw' / 'lib' / 'jsr_raw_bridge.dylib'
    srhq_joraw2._candidate_dlls = lambda: [library]
    cpu = types.ModuleType('srhq_core')
    for name in ('raw_merge', 'raw_merge_stripe_kernel', 'raw_merge_o1', 'cov9_main_kernel',
                 'coarse_gate_kernel', 'cov_from_ks_kernel', 'cov3_legacy_kernel'):
        def unavailable(*args, _name=name, **kwargs):
            raise RuntimeError(f'The Windows CPU extension {_name} is unavailable; select the WGPU engine')
        setattr(cpu, name, unavailable)
    sys.modules['srhq_core'] = cpu
    import wgpu_multik_stream_v1
    original_shader = wgpu_multik_stream_v1.WGSL_LEARNED_ACCUMULATE
    helper = '''
fn stable_tanh(x: f32) -> f32 {
    let e = exp(-2.0 * abs(x));
    return sign(x) * (1.0 - e) / (1.0 + e);
}
'''
    # Metal's built-in tanh overflows for positive logits above about 44.
    expression = 'tanh(raw / P.cap)'
    if expression not in original_shader:
        raise RuntimeError('The original learned-merge shader contract changed')
    wgpu_multik_stream_v1.WGSL_LEARNED_ACCUMULATE = helper + original_shader.replace(expression, 'stable_tanh(raw / P.cap)')
    if os.environ.get('JSR_NATIVE_FUSION', '0') == '1':
        if networks != 'mpsgraph':
            raise ValueError('Native fusion requires MPSGraph networks')
        from native_fusion import install as install_fusion
        install_fusion()
    os.environ['JSR_MACOS_CONFIGURED'] = str(os.getpid())
    if networks == 'mpsgraph':
        import json
        build = Path(__file__).resolve().parent / 'vendor/metal/jsr_graph.build.json'
        os.environ['JSR_LOADED_NATIVE_BUILD'] = build.read_text()


def main():
    if '--raw-frame' in sys.argv and '--dark-frame' not in sys.argv:
        raise SystemExit('JSR 17.3.1 K14 requires --dark-frame with an applicable dark RAW')
    configure()
    from finish import snapshot_images
    initial_images = snapshot_images(Path(sys.argv[sys.argv.index('--output-dir') + 1])) if '--output-dir' in sys.argv else {}
    resources = None
    if '--output-dir' in sys.argv and '--raw-frame' in sys.argv:
        from job_resources import JobResources
        resources = JobResources(Path(sys.argv[sys.argv.index('--output-dir') + 1]),
            raw_frame=Path(sys.argv[sys.argv.index('--raw-frame') + 1]),
            mmap_dir=Path(sys.argv[sys.argv.index('--mmap-dir') + 1]) if '--mmap-dir' in sys.argv else None,
            frames=sys.argv.count('--raw-frame'))
    from metal_platform import clone_scratch_files
    try:
        with clone_scratch_files(Path(sys.argv[sys.argv.index('--output-dir') + 1]) if '--output-dir' in sys.argv else Path.cwd() / 'output'):
            import fast_gated_cm_png
            fast_gated_cm_png.main()
    finally:
        observed_resources = resources.close() if resources else {}
    if '--output-dir' in sys.argv and '--raw-frame' in sys.argv:
        from output_metadata import finalize
        frames = [sys.argv[i + 1] for i, arg in enumerate(sys.argv) if arg == '--raw-frame']
        compress = not ('--dng-compression' in sys.argv and sys.argv[sys.argv.index('--dng-compression') + 1] == 'none')
        finalize(Path(sys.argv[sys.argv.index('--output-dir') + 1]), frames, 'v98', initial_images, compress)
    if '--output-dir' in sys.argv:
        import json
        output = Path(sys.argv[sys.argv.index('--output-dir') + 1])
        for path in output.glob('*PRODUCT.json'):
            product = json.loads(path.read_text())
            product['macos_port'] = {
                'network_backend': os.environ.get('JSR_METAL_NETWORKS', 'mpsgraph'),
                'rarm_executor': 'MPSGraph FP32' if os.environ.get('JSR_METAL_NETWORKS', 'mpsgraph') == 'mpsgraph' else 'WGPU FP32',
                'controller_executor': 'MPSGraph FP32' if os.environ.get('JSR_METAL_NETWORKS', 'mpsgraph') == 'mpsgraph' else 'WGPU FP32',
                'merge_executor': 'native Metal FP32' if os.environ.get('JSR_NATIVE_FUSION', '0') == '1' else 'WGPU Metal', 'original_manifest_contract': 'Windows release WGPU route',
                'reduced_precision_fast_math': False,
                'resources': observed_resources,
            }
            if product['macos_port']['network_backend'] == 'mpsgraph':
                from metal_graph import METRICS
                from metal_platform import CLONE_METRICS
                product['macos_port']['native_network_metrics'] = METRICS
                if os.environ.get('JSR_NATIVE_FUSION', '0') == '1':
                    from native_fusion import METRICS_FUSION
                    product['macos_port']['native_fusion_metrics'] = METRICS_FUSION
                product['macos_port']['tile_profile'] = json.loads(os.environ['JSR_METAL_PROFILE'])
                product['macos_port']['apfs_clones'] = CLONE_METRICS
                product['macos_port']['native_build'] = json.loads(os.environ['JSR_LOADED_NATIVE_BUILD'])
                product['macos_port']['refinement_halo_native'] = int(os.environ.get('JSR_RARM_HALO', '48'))
            path.write_text(json.dumps(product, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
