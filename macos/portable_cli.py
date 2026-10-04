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
VERSION = '2.3.9-macos-preview.1'


def entry(name):
    path = ROOT / (name + '.py')
    return path if path.is_file() else path.with_suffix('.pyc')


def main():
    parser = argparse.ArgumentParser(description='Jiangtherapee Bridge · Apple Silicon portable CLI')
    parser.add_argument('--version', action='version', version=VERSION)
    parser.add_argument('command', nargs='?', choices=('gui', 'fast', 'stormer', 'v98', 'doctor'))
    args = parser.parse_args(sys.argv[1:2])
    remaining = sys.argv[2:]
    if args.command is None:
        parser.print_help()
        return
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
            from gui import Application
            window = tkinter.Tk()
            try:
                application = Application(window)
                window.update()
                result['gui'] = {'window_created': bool(window.winfo_viewable()),
                                 'title': window.title(), 'default_mode': application.mode.get(),
                                 'size': [window.winfo_width(), window.winfo_height()]}
                if not result['gui']['window_created']:
                    raise RuntimeError('GUI window did not become visible')
            finally:
                window.destroy()
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
    name = 'gui' if args.command == 'gui' else 'run_' + args.command
    if args.command == 'v98':
        name = 'run_v98'
    path = entry(name)
    sys.argv = [str(path), *remaining]
    runpy.run_path(str(path), run_name='__main__')


if __name__ == '__main__':
    main()
