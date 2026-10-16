"""Extract original Stormer and v9.8 modules and model resources from Bridge 2.3.27."""
from pathlib import Path
import argparse
import hashlib
import importlib.util
import json
import marshal
import shutil
import sys
import zipfile

from PyInstaller.archive.readers import CArchiveReader, ZlibArchiveReader
from release import ARCHIVE_SHA256, PREFIX, TAG, sha256

MODULES = {
    'stormer': ('jsr_backend', set('''batch_bridge backend bridge_preview color_profile developer dng_repack native_dng
        output_chain profile_metadata ptc selftest sensor srhq_joraw2 v124_dng v82_lca
        v82_lossless_dng whitepoint'''.split())),
    'v98': ('jsr_v98_k14_backend', set('''_srhq_kernels alias_v6 batch_raw_probe block_align bsr_steer
        exp_rawmerge fast_gated_cm_png highlight_recovery local_v7_frontend make_jdng make_sharp_jdng
        modelb_align newpipe_homog perceptual_sharpen render_cm_png sharpen_cupy srhq_joraw2 srhq_pou
        v82_lca v82_lossless_dng v82_wgpu_product_adapter v82_wgpu_product_engine v94_wgpu_wrapper
        wgpu_buf wgpu_fused_v8_1 wgpu_gather wgpu_greenfilm_rarm wgpu_multik_stream_v1 wgpu_net
        wgpu_rarm_tiled wgpu_unet_tiled wgpu_v81_reconstructor'''.split())),
}
CACHE_LAUNCHER = '''import sys, marshal
from pathlib import Path
root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root))
from run_v98 import configure
configure()
exec(marshal.loads(Path(__file__).with_suffix('.pyc').read_bytes()[16:]))
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive', type=Path)
    args = parser.parse_args()
    if sys.version_info[:2] != (3, 10):
        parser.error('The original bytecode requires Python 3.10')
    if sha256(args.archive) != ARCHIVE_SHA256:
        parser.error('Bridge archive checksum mismatch')
    base = Path(__file__).resolve().parent / 'vendor'
    base.mkdir(exist_ok=True)
    prefix = PREFIX + 'resources/'
    with zipfile.ZipFile(args.archive) as release:
        for mode, (exe, names) in MODULES.items():
            output = base / mode
            output.mkdir(exist_ok=True)
            binary = base / (exe + '.exe')
            binary.write_bytes(release.read(prefix + binary.name))
            packed = CArchiveReader(str(binary))
            pyz_file = base / (mode + '.pyz')
            pyz_file.write_bytes(packed.extract('PYZ.pyz'))
            pyz = ZlibArchiveReader(str(pyz_file), check_pymagic=True)
            for name, (kind, *_) in pyz.toc.items():
                if name not in names and name.split('.')[0] not in {'v15_1', 'v15_2'}:
                    continue
                path = output.joinpath(*name.split('.'))
                path = path / '__init__.pyc' if kind == 1 else path.with_suffix('.pyc')
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(importlib.util.MAGIC_NUMBER + bytes(12) + marshal.dumps(pyz.extract(name)))
            for name, record in packed.toc.items():
                if record[-1] == 'b' and (name.endswith(('.pyc', '.npz', '.json', '.csv', '.data'))
                                          or 'LICENSE' in name or 'NOTICE' in name):
                    path = output / name.replace('\\', '/')
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(packed.extract(name))
                elif record[-1] == 's' and not name.startswith('pyi'):
                    (output / (name + '_entry.pyc')).write_bytes(importlib.util.MAGIC_NUMBER + bytes(12) + packed.extract(name))
            if mode == 'stormer':
                for name in ['conv_shader.py', 'conv_shader.pyc']:
                    shutil.copyfile(base / 'fast' / name, output / name)
                    shutil.copyfile(base / 'fast' / name, output / 'wgpu' / name)
            else:
                (output / 'newpipe_homog.py').write_text(CACHE_LAUNCHER)
            manifest = {
                'release': TAG, 'archive_sha256': ARCHIVE_SHA256,
                'mode': mode, 'backend_sha256': sha256(binary),
                'files': {str(p.relative_to(output)): sha256(p) for p in sorted(output.rglob('*'))
                          if p.is_file() and p.name != 'manifest.json' and '__pycache__' not in p.parts},
            }
            (output / 'manifest.json').write_text(json.dumps(manifest, indent=2))
            binary.unlink()
            pyz_file.unlink()
            print(json.dumps({'mode': mode, 'files': len(manifest['files']), 'root': str(output)}))


if __name__ == '__main__':
    main()
