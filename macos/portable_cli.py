"""Portable command entry point shared by Finder and the terminal."""
from pathlib import Path
import argparse
import json
import os
import platform
import runpy
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
from release import VERSION, UPSTREAM_VERSION, TAG, ARCHIVE_SHA256


def entry(name):
    path = ROOT / (name + '.py')
    return path if path.is_file() else path.with_suffix('.pyc')


def main():
    parser = argparse.ArgumentParser(description='Jiangtherapee Bridge · Apple Silicon portable CLI')
    parser.add_argument('--version', action='version', version=VERSION)
    parser.add_argument('command', nargs='?', choices=('gui', 'fast', 'stormer', 'v98', 'doctor', 'web-worker', 'gui-tk'))
    args = parser.parse_args(sys.argv[1:2])
    remaining = sys.argv[2:]
    if args.command is None:
        parser.print_help()
        return
    if args.command == 'web-worker':
        runpy.run_path(str(entry('web_bridge')), run_name='__main__')
        return
    if args.command == 'gui':
        host = ROOT.parent.parent / 'MacOS/JSRWeb'
        if host.exists():
            os.execv(str(host), [str(host), *remaining])
        development = ROOT / 'dist/web-dev/JSRWeb'
        if development.exists():
            os.execv(str(development), [str(development), '--resources', str(ROOT / 'dist/web-dev'), '--engine-root', str(ROOT), *remaining])
        raise SystemExit('Build the WKWebView host with build_portable.py')
    if args.command == 'doctor':
        doctor = argparse.ArgumentParser(description='Check the bundled runtime and GPU')
        doctor.add_argument('--raw', type=Path)
        doctor.add_argument('--self-test', action='store_true')
        doctor.add_argument('--gui-test', action='store_true')
        doctor.add_argument('--fusion-test', action='store_true')
        options = doctor.parse_args(remaining)
        import numpy
        import rawpy
        import tkinter
        from metal_graph import library
        native = library()
        result = {'version': VERSION, 'architecture': platform.machine(),
                  'macos': platform.mac_ver()[0], 'python': platform.python_version(),
                  'numpy': numpy.__version__, 'device': json.loads(native.jsr_graph_device_info()),
                  'tcl': tkinter.Tcl().eval('info patchlevel'),
                  'exiftool': subprocess.check_output(['exiftool', '-ver'], text=True).strip()}
        if options.raw:
            with rawpy.imread(str(options.raw)) as raw:
                result['raw'] = {'shape': list(raw.raw_image_visible.shape), 'white_level': raw.white_level,
                                 'black_levels': raw.black_level_per_channel}
        if options.gui_test:
            host = ROOT.parent.parent / 'MacOS/JSRWeb'
            result['gui'] = json.loads(subprocess.check_output([str(host), '--structure-test'], text=True))
            if result['gui']['modes'] != 3 or not result['gui']['ui'] or result['gui']['errors']:
                raise RuntimeError('WKWebView GUI validation failed')
        print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
        if options.self_test:
            check = ROOT.parent / 'Core-Only-Source-Code/check_macos.pyc'
            if not check.exists():
                check = check.with_suffix('.py')
            subprocess.run([sys.executable, str(check), '--frames', '14', '--network-backend', 'mpsgraph'], check=True)
        if options.fusion_test:
            import tempfile
            with tempfile.TemporaryDirectory(prefix='jsr-fusion-') as temporary:
                report = Path(temporary) / 'fusion.json'
                subprocess.run([sys.executable, str(entry('check_native_fusion')), '--output', str(report)], check=True)
                print(report.read_text(), flush=True)
        return
    name = 'gui' if args.command == 'gui-tk' else 'run_' + args.command
    if args.command == 'v98':
        name = 'run_v98'
    path = entry(name)
    sys.argv = [str(path), *remaining]
    runpy.run_path(str(path), run_name='__main__')


if __name__ == '__main__':
    main()
