"""Publish local benchmark measurements without input names or host paths."""
from datetime import datetime, timezone
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parent
VALIDATION = ROOT / 'validation'


def read(path):
    return json.loads(path.read_text())


def product(folder):
    return read(next((VALIDATION / folder).glob('*PRODUCT.json')))


def summary(item):
    sidecar = item['sidecar_result']
    result = {
        'status': item['status'], 'product_elapsed_seconds': item['elapsed_seconds'],
        'pure_reconstruction_seconds': sidecar['timing']['pure_reconstruction_seconds'],
        'original_speed_gate': sidecar['speed_gate'],
        'all_input_frames_used': sidecar['single_wgpu_codepath']['all_input_frames_used'],
    }
    if 'macos_port' in item:
        result['macos_port'] = item['macos_port']
    return result


def main():
    baseline = product('real-v98')
    optimized = product('real-v98-metal-final')
    report = {
        'measured_at_utc': datetime.now(timezone.utc).isoformat(),
        'release': 'jb-v2.3.9',
        'hardware': {'chip': 'Apple M2 Pro', 'gpu_cores': 16, 'memory_gib': 32,
                     'architecture': 'arm64', 'os': 'macOS 27.2', 'python': '3.10.16'},
        'input': {'camera': 'Nikon Z6 III', 'compression': 'High Efficiency*',
                  'frames': 14, 'native_hw': [4040, 6064], 'iso': 2000, 'shutter_seconds': 1 / 750},
        'output': {'hwc': [8080, 12128, 3], 'dtype': 'uint16',
                   'formats': ['camera-linear DNG', 'color-rendered TIFF']},
        'v98_wgpu_baseline': summary(baseline),
        'v98_apple_memory_profile': summary(optimized),
        'cache_policy_for_comparison': 'Both reconstruction timings use prepared alignment caches',
        'reconstruction_and_export_speedup': baseline['elapsed_seconds'] / optimized['elapsed_seconds'],
        'pure_reconstruction_speedup': baseline['sidecar_result']['timing']['pure_reconstruction_seconds']
                                     / optimized['sidecar_result']['timing']['pure_reconstruction_seconds'],
        'original_output_parity': read(VALIDATION / 'metal-full-parity-final.json'),
        'dng_readback_verified': (VALIDATION / 'real-v98-metal-final/pixel-validation.json').is_file(),
        'other_modes': {'fast_k14': {'scope': '14 frames, full image', 'seconds': 381.699,
                                    'executor': 'original WGPU Metal'},
                        'stormer_k7': {'scope': '7 frames, 512 x 512 native ROI, deghost off/on pair',
                                       'seconds': 52.8, 'full_image_timing_verified': False,
                                       'executor': 'original WGPU Metal'}},
    }
    cold = VALIDATION / 'real-v98-metal-cold'
    if list(cold.glob('*PRODUCT.json')) and (cold / 'WALL.json').is_file():
        report['v98_apple_cold_start'] = {
            **summary(product('real-v98-metal-cold')), **read(cold / 'WALL.json'),
            'scope': 'RAW decode, alignment, reconstruction, DNG/TIFF export and orientation update',
        }
        parity = VALIDATION / 'metal-full-parity-cold.json'
        if parity.is_file():
            report['v98_apple_cold_start']['original_output_parity'] = read(parity)
    core = VALIDATION / 'core-metal-final.json'
    if core.is_file():
        report['current_build_validation'] = {
            'build': read(ROOT / 'vendor/metal/jsr_graph.build.json'),
            'core': read(core),
            'network_parity': {
                kind: read(VALIDATION / f'metal-{kind}-final-build.json')['parity']
                for kind in ('controller', 'rarm')
            },
        }
    (ROOT / 'BENCHMARK.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print('Wrote macos/BENCHMARK.json')


if __name__ == '__main__':
    main()
