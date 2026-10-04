"""Build the native FP32 MPSGraph inference bridge on Apple Silicon."""
from pathlib import Path
import platform
import subprocess
import hashlib
import json


def main():
    if platform.system() != 'Darwin' or platform.machine() != 'arm64':
        raise SystemExit('Native Apple Silicon build required')
    root = Path(__file__).resolve().parent
    output = root / 'vendor/metal/jsr_graph.dylib'
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = output.with_suffix('.staging.dylib')
    subprocess.run(['xcrun', 'clang++', '-std=c++17', '-O3', '-fobjc-arc', '-dynamiclib',
                    '-arch', 'arm64', '-mmacosx-version-min=13.0',
                    str(root / 'native/graph_bridge.mm'), '-o', str(staging),
                    '-framework', 'Foundation', '-framework', 'Metal',
                    '-framework', 'MetalPerformanceShaders', '-framework', 'MetalPerformanceShadersGraph'], check=True)
    subprocess.run(['codesign', '--force', '--sign', '-', str(staging)], check=True)
    staging.replace(output)
    record_build(output)
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
