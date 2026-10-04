"""Collect real local validation evidence for the three native backends."""
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import platform
import re

ROOT = Path(__file__).resolve().parent
VALIDATION = ROOT / 'validation'


def read(path):
    return json.loads(path.read_text())


def main():
    decoder = read(VALIDATION / 'raw-decoder-validation.json')
    fast = read(VALIDATION / 'real-fast/RESULT.json')
    stormer = next((VALIDATION / 'real-stormer-roi').rglob('result_off.json'))
    sr = read(stormer)
    transformer = sr['reconstruction']['transformer']
    stormer_log = (VALIDATION / 'real-stormer-roi.log').read_text()
    match = re.search(r'DONE total ([\d.]+)s', stormer_log)
    report = {
        'updated_at_utc': datetime.now(timezone.utc).isoformat(),
        'release': 'jb-v2.3.9', 'platform': platform.platform(),
        'architecture': platform.machine(), 'python': platform.python_version(),
        'dataset': 'local 14-frame Nikon Z6 III validation burst',
        'raw_decoder': decoder,
        'test_calibration': {'applies_to': ['Fast K14', 'Stormer'],
                             'black_dn': 1008, 'read_noise_dn': 0, 'fullwell_e': 20000,
                             'user_authorized_test_values': True},
        'modes': {
            'fast_k14': {'status': fast['status'], 'scope': '14 frames, full image',
                         'seconds': fast['total_seconds'], 'output_hw': [8080, 12128],
                         'pixel_validation': read(VALIDATION / 'real-fast/pixel-validation.json'),
                         'adapter': fast['macos_port']['adapter'],
                         'result': str((VALIDATION / 'real-fast/RESULT.json').resolve())},
            'stormer_k7': {'status': sr['status'], 'scope': 'first 7 frames, 512 x 512 native ROI at (2600, 1600)',
                           'full_image_timing_verified': False,
                           'seconds': float(match.group(1)) if match else None, 'output_hw': [1024, 1024],
                           'outputs': ['deghost off', 'deghost on'],
                           'pixel_validation': read(VALIDATION / 'real-stormer-roi/pixel-validation.json'),
                           'adapter': transformer['restoration']['memory']['capabilities']['adapter'],
                           'result': str(stormer.resolve())},
            'v98_k14': {'status': 'RUNNING', 'scope': '14 frames, full image',
                        'log': str((VALIDATION / 'real-v98.log').resolve())},
        },
        'metal_numerics': read(VALIDATION / 'metal-numerics.json'),
        'synthetic_fast': {'result': read(VALIDATION / 'final-port/RESULT.json'),
                           'pixel_validation': read(VALIDATION / 'final-port/pixel-validation.json')},
        'gui': {'launcher': str((ROOT / 'JSR Metal.app').resolve()),
                'mode_choices': ['Fast K14', 'Stormer K7', 'v9.8 K14'],
                'launched': True, 'visual_automation_verified': False,
                'visual_automation_error': 'Computer Use NSCocoaErrorDomain 3840: unterminated JSON string'},
    }
    products = list((VALIDATION / 'real-v98').glob('*PRODUCT.json'))
    if products:
        product = read(products[0])
        evidence = product['sidecar_result']
        report['modes']['v98_k14'] = {
            'status': product['status'], 'scope': '14 frames, full image',
            'seconds': product['elapsed_seconds'],
            'pure_reconstruction_seconds': evidence['timing']['pure_reconstruction_seconds'],
            'original_speed_gate': evidence['speed_gate'],
            'all_input_frames_used': evidence['single_wgpu_codepath']['all_input_frames_used'],
            'adapter': evidence['wgpu_adapter_observed'],
            'outputs': product['outputs'], 'result': str(products[0].resolve()),
        }
        validation = VALIDATION / 'real-v98/pixel-validation.json'
        if validation.exists():
            report['modes']['v98_k14']['pixel_validation'] = read(validation)
    optimized = list((VALIDATION / 'real-v98-metal-final').glob('*PRODUCT.json'))
    parity = VALIDATION / 'metal-full-parity-final.json'
    if optimized:
        product = read(optimized[0])
        evidence = product['sidecar_result']
        report['modes']['v98_k14_apple'] = {
            'status': product['status'], 'scope': '14 frames, full image',
            'seconds': product['elapsed_seconds'],
            'pure_reconstruction_seconds': evidence['timing']['pure_reconstruction_seconds'],
            'original_speed_gate': evidence['speed_gate'],
            'all_input_frames_used': evidence['single_wgpu_codepath']['all_input_frames_used'],
            'macos_port': product['macos_port'],
            'outputs': product['outputs'], 'result': str(optimized[0].resolve()),
        }
        if parity.exists():
            report['modes']['v98_k14_apple']['original_output_parity'] = read(parity)
        validation = VALIDATION / 'real-v98-metal-final/pixel-validation.json'
        if validation.exists():
            report['modes']['v98_k14_apple']['pixel_validation'] = read(validation)
    cold = VALIDATION / 'real-v98-metal-cold'
    if (cold / 'WALL.json').is_file():
        from write_benchmark import product, summary
        report['modes']['v98_k14_apple_cold'] = {
            **summary(product('real-v98-metal-cold')), **read(cold / 'WALL.json'),
            'original_output_parity': read(VALIDATION / 'metal-full-parity-cold.json'),
            'pixel_validation': read(cold / 'pixel-validation.json'),
        }
    (ROOT / 'ACCEPTANCE.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps({name: info['status'] for name, info in report['modes'].items()}))


if __name__ == '__main__':
    main()
