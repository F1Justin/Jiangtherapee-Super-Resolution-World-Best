"""Build the native FP32 MPSGraph inference bridge on Apple Silicon."""
from pathlib import Path
import argparse
import platform
import subprocess
import hashlib
import json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--embed-fusion', action='store_true')
    args = parser.parse_args()
    if platform.system() != 'Darwin' or platform.machine() != 'arm64':
        raise SystemExit('Native Apple Silicon build required')
    root = Path(__file__).resolve().parent
    output = args.output or root / 'vendor/metal/jsr_graph.dylib'
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = output.with_suffix('.staging.dylib')
    extra = []
    header = output.parent / 'fusion_embedded.h'
    if args.embed_fusion:
        shader = (root / 'native/fusion.metal').read_text()
        header.write_text('#define JSR_EMBEDDED_FUSION 1\nstatic const char jsr_embedded_fusion[] = '
                          + json.dumps(shader) + ';\n')
        extra = ['-include', str(header)]
    subprocess.run(['xcrun', 'clang++', '-std=c++17', '-O3', '-fobjc-arc', '-dynamiclib',
                    '-arch', 'arm64', '-mmacosx-version-min=13.0',
                    *extra, str(root / 'native/graph_bridge.mm'), '-o', str(staging),
                    '-framework', 'Foundation', '-framework', 'Metal',
                    '-framework', 'MetalPerformanceShaders', '-framework', 'MetalPerformanceShadersGraph'], check=True)
    subprocess.run(['codesign', '--force', '--sign', '-', str(staging)], check=True)
    staging.replace(output)
    record_build(output)
    if args.embed_fusion:
        header.unlink()
    print(output)


def record_build(output):
    root = Path(__file__).resolve().parent
    source = root / 'native/graph_bridge.mm'
    metadata = {'precision': 'float32', 'reduced_precision_fast_math': False,
                'architecture': 'arm64', 'minimum_macos': '13.0',
                'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
                'native_sources_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in sorted(root.joinpath('native').glob('*')) if p.suffix in ('.mm', '.inc', '.metal')},
                'library_sha256': hashlib.sha256(output.read_bytes()).hexdigest(),
                'compiler': subprocess.check_output(['xcrun', 'clang++', '--version'], text=True).splitlines()[0]}
    output.with_suffix('.build.json').write_text(json.dumps(metadata, indent=2))


if __name__ == '__main__':
    main()
