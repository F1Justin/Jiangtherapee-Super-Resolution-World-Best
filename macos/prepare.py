"""Extract the original Fast K14 bytecode and resources from a verified Bridge release."""

from __future__ import annotations

import argparse
import importlib.util
import json
import marshal
from pathlib import Path
import shutil
import sys
import zipfile

from PyInstaller.archive.readers import CArchiveReader, ZlibArchiveReader


from release import ARCHIVE_SHA256, PREFIX, TAG, UPSTREAM_VERSION, extract_shared, sha256
BACKEND_SHA256 = "db977a8d285364939d143f2878ad6e3a79d784b8f6a0508fabffa93949d3b7f2"
MODULES = {
    "measured_dark_lut", "raw_metadata", "diagnostic_entry", "fast_align", "fast_calibration", "fast_frontend_run", "fast_ptc",
    "fast_signal", "fastk14_app", "frontend", "frontend_reliable", "frontend_steered",
    "native_dng", "network_reliable", "registration_candidate", "registration_linear_support",
    "resident_k14", "resource_plan", "source_atlas", "stable_gather", "support_bounds",
    "wgpu_buf", "wgpu_compact", "wgpu_conv_wgsl", "wgpu_k14", "wgpu_lifetime", "wgpu_rarm_tiled",
}
RESOURCES = {
    "wgpu/conv_shader.pyc": "conv_shader.pyc",
    "wgpu/assets_v15_2/spynet.npz": "wgpu/assets_v15_2/spynet.npz",
    "wgpu_reconstruction/weights.npz": "wgpu_reconstruction/weights.npz",
    "ptc_index.csv": "ptc_index.csv",
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    args = parser.parse_args()
    if sys.version_info[:2] != (3, 10):
        parser.error("Python 3.10 is required by the original bytecode")
    if sha256(args.archive) != ARCHIVE_SHA256:
        parser.error("Archive SHA-256 differs from the official JSR " + UPSTREAM_VERSION + " release")
    extract_shared(args.archive)
    root = Path(__file__).resolve().parent
    vendor = root / "vendor"
    output = vendor / "fast"
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(args.archive) as archive:
        prefix = PREFIX + "resources/"
        backend = vendor / "jsr_fast_k14_backend.exe"
        backend.write_bytes(archive.read(prefix + "jsr_fast_k14_backend.exe"))
        if sha256(backend) != BACKEND_SHA256:
            parser.error("Fast K14 backend checksum mismatch")
        packed = CArchiveReader(str(backend))
        pyz_path = vendor / "fast.pyz"
        pyz_path.write_bytes(packed.extract("PYZ.pyz"))
        pyz = ZlibArchiveReader(str(pyz_path), check_pymagic=True)
        for name, (kind, *_) in pyz.toc.items():
            if name not in MODULES and name.split(".")[0] not in {"v15_1", "v15_2"}:
                continue
            path = output.joinpath(*name.split("."))
            path = path / "__init__.pyc" if kind == 1 else path.with_suffix(".pyc")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(importlib.util.MAGIC_NUMBER + bytes(12) + marshal.dumps(pyz.extract(name)))
        for original, destination in RESOURCES.items():
            path = output / destination
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(archive.read(prefix + "_internal/" + original))
    shutil.copyfile(root / "conv_shader.py", output / "conv_shader.py")
    manifest = {
        "release": TAG,
        "archive_sha256": ARCHIVE_SHA256,
        "backend_sha256": BACKEND_SHA256,
        "python_bytecode": "3.10",
        "files": {str(path.relative_to(output)): sha256(path) for path in sorted(output.rglob("*"))
                  if path.is_file() and path.name != "manifest.json" and "__pycache__" not in path.parts},
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    backend.unlink()
    pyz_path.unlink()
    print(json.dumps({"status": "prepared", "files": len(manifest["files"]), "root": str(output)}))


if __name__ == "__main__":
    main()
