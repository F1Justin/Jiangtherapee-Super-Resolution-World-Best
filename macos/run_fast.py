"""Run Bridge 2.3.9 Fast K14 with native macOS libraries and Metal."""

from __future__ import annotations

import json
import os
from pathlib import Path
import platform
import sys


def main() -> None:
    if platform.system() != "Darwin" or platform.machine() != "arm64" or sys.version_info[:2] != (3, 10):
        raise SystemExit("Use macos/.venv/bin/python (arm64 Python 3.10)")
    root = Path(__file__).resolve().parent / "vendor" / "fast"
    if not (root / "fastk14_app.pyc").is_file():
        raise SystemExit("Run macos/prepare.py with the Bridge 2.3.9 Windows ZIP first")
    os.environ["WGPU_BACKEND_TYPE"] = "Metal"
    os.environ["JSR_WGPU_BACKEND"] = "Metal"
    os.environ["OMP_NUM_THREADS"] = "4"
    os.environ["OPENBLAS_NUM_THREADS"] = "1"
    sys.path.insert(0, str(root))
    sys._MEIPASS = str(root)
    from finish import snapshot_images
    initial_images = snapshot_images(Path(sys.argv[sys.argv.index('--output-dir') + 1])) if '--output-dir' in sys.argv else {}

    import cv2
    import psutil

    # Darwin 使用系统调度；这里记录可调度核心集合。
    def schedulable_cpus(self, cpus=None):
        return list(range(psutil.cpu_count(logical=True) or 1))

    psutil.Process.cpu_affinity = schedulable_cpus
    import resource_plan

    resource_plan.physical_cpus = lambda: list(range(psutil.cpu_count(logical=False) or 1))
    import diagnostic_entry
    import fastk14_app
    import stable_gather
    import v15_2.memory

    stable_gather.install()
    import ctypes
    import ctypes.util

    metal = ctypes.CDLL("/System/Library/Frameworks/Metal.framework/Metal")
    objc = ctypes.CDLL(ctypes.util.find_library("objc"))
    metal.MTLCreateSystemDefaultDevice.restype = ctypes.c_void_p
    metal_device = metal.MTLCreateSystemDefaultDevice()
    objc.sel_registerName.argtypes = [ctypes.c_char_p]
    objc.sel_registerName.restype = ctypes.c_void_p
    selector = objc.sel_registerName(b"currentAllocatedSize")
    message = ctypes.CFUNCTYPE(ctypes.c_uint64, ctypes.c_void_p, ctypes.c_void_p)(
        ("objc_msgSend", objc)
    )
    observed_adapter = {}

    def metal_budget(info):
        observed_adapter.update(info)
        result = v15_2.memory._mac_budget(info)
        result["current_process_usage"] = int(message(metal_device, selector))
        return result

    v15_2.memory._windows_budget = metal_budget
    original_threads = cv2.setNumThreads
    requested_cores = 4
    if "--cpu-cores" in sys.argv:
        requested_cores = int(sys.argv[sys.argv.index("--cpu-cores") + 1])
    original_threads(requested_cores)
    fastk14_app.main()
    original_threads(requested_cores)

    if "--output-dir" in sys.argv:
        output = Path(sys.argv[sys.argv.index("--output-dir") + 1])
        report_path = output / "RESULT.json"
        if report_path.is_file():
            report = json.loads(report_path.read_text(encoding="utf-8"))
            report["macos_port"] = {
                "release": "jb-v2.3.9",
                "runtime": platform.python_version(),
                "architecture": platform.machine(),
                "backend": "Metal",
                "adapter": observed_adapter,
                "cpu_affinity_enforced": False,
                "requested_decode_threads": requested_cores,
                "opencv_parallel_framework": "GCD / system scheduling",
                "opencv_threads": cv2.getNumThreads(),
            }
            report["cpu_affinity"] = None
            from finish import preserve_orientation
            preserve_orientation(output, Path(report['reference']), initial_images)
            policy = report.get("resource_plan", {})
            policy["cpu_threads"] = len(policy.pop("cpu_affinity", []))
            report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
