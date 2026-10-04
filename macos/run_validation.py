"""Run a fixed native configuration and validate its complete linear DNG output."""
from pathlib import Path
import argparse
import json
import os
import subprocess
import sys
import time
import shutil


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inputs-dir', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--mmap-dir', type=Path, required=True)
    parser.add_argument('--compare-to', type=Path, required=True)
    parser.add_argument('--prepare-cache', action='store_true')
    parser.add_argument('--tile', type=int, default=384)
    parser.add_argument('--rarm-halo', type=int, default=48)
    parser.add_argument('--controller-cache', type=int, default=1)
    parser.add_argument('--rarm-cache', type=int, default=1)
    parser.add_argument('--fold-film', action='store_true')
    parser.add_argument('--native-fusion', action='store_true')
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    output = args.output_dir.resolve()
    if output.exists():
        raise SystemExit('Validation output must be a fresh directory')
    frames = sorted(p for p in args.inputs_dir.iterdir() if p.suffix.lower() == '.nef')
    if len(frames) != 14:
        raise SystemExit('This validation configuration requires 14 NEF frames')
    output.mkdir(parents=True)
    snapshot = output / 'build-source'
    snapshot.mkdir()
    for path in [*root.joinpath('native').glob('*'), root / 'vendor/metal/jsr_graph.build.json']:
        if path.is_file():
            shutil.copy2(path, snapshot / path.name)
    environment = dict(os.environ, JSR_METAL_TILE=str(args.tile), JSR_RARM_HALO=str(args.rarm_halo),
        JSR_CONTROLLER_CACHE=str(args.controller_cache), JSR_RARM_CACHE=str(args.rarm_cache),
        JSR_METAL_FOLD_FILM=str(int(args.fold_film)), JSR_NATIVE_FUSION=str(int(args.native_fusion)))
    command = [sys.executable, str(root / 'run_v98.py'), '--output-dir', str(output),
               '--cache-mode', 'memmap', '--mmap-dir', str(args.mmap_dir.resolve()),
               '--out-dng', 'on', '--out-tiff', 'on', '--out-png', 'off',
               '--camera-profile-source', 'libraw', '--resource-mode', 'balanced']
    if args.prepare_cache:
        command.append('--prepare-mmap-cache')
    for frame in frames:
        command.extend(['--raw-frame', str(frame.resolve())])
    with (output / 'process.log').open('w') as log:
        start = time.perf_counter()
        result = subprocess.run(command, env=environment, stdout=log, stderr=subprocess.STDOUT)
    (output / 'WALL.json').write_text(json.dumps({'process_wall_seconds': time.perf_counter() - start,
        'cache': 'RAW decode and alignment included' if args.prepare_cache else 'prepared alignment cache', 'exit_code': result.returncode,
        'strategy': {key: value for key, value in environment.items() if key.startswith('JSR_')}}, indent=2))
    if result.returncode:
        raise SystemExit(result.returncode)
    dng = next(output.glob('*.dng'))
    subprocess.run([sys.executable, str(root / 'compare_metal_outputs.py'), str(args.compare_to.resolve()),
        str(dng), '--block-native', str(args.tile), '--output', str(output / 'parity.json')], check=True)
    subprocess.run([sys.executable, str(root / 'validate_outputs.py'), str(output)], check=True)


if __name__ == '__main__':
    main()
