"""Run the original seven-frame Stormer backend on Metal."""
from pathlib import Path
import os
import platform
import runpy
import sys


def main():
    if platform.system() != 'Darwin' or platform.machine() != 'arm64' or sys.version_info[:2] != (3, 10):
        raise SystemExit('Use macos/.venv/bin/python (arm64 Python 3.10)')
    root = Path(__file__).resolve().parent / 'vendor' / 'stormer'
    sys._MEIPASS = str(root)
    sys.path.insert(0, str(root))
    os.environ['WGPU_BACKEND_TYPE'] = 'Metal'
    os.environ['JSR_WGPU_BACKEND'] = 'Metal'
    os.environ['OPENBLAS_NUM_THREADS'] = '1'
    import cv2
    cv2.setNumThreads(4)
    from finish import snapshot_images
    initial_images = snapshot_images(Path(sys.argv[sys.argv.index('--output-dir') + 1])) if '--output-dir' in sys.argv else {}
    runpy.run_path(str(root / 'backend_entry.pyc'), run_name='__main__')
    if '--output-dir' in sys.argv and '--raw-frame' in sys.argv:
        from finish import preserve_orientation
        preserve_orientation(Path(sys.argv[sys.argv.index('--output-dir') + 1]), Path(sys.argv[sys.argv.index('--raw-frame') + 1]), initial_images)


if __name__ == '__main__':
    main()
