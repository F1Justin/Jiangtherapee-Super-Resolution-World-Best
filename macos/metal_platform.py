"""Apple unified-memory tile selection and APFS scratch-file cloning."""
from contextlib import contextmanager
from pathlib import Path
import ctypes
import os
import shutil

import psutil

CLONE_METRICS = {'files': 0, 'logical_bytes': 0}


def install_tile_profile():
    import v82_wgpu_product_adapter as adapter
    import v82_wgpu_product_engine as engine
    requested = os.environ.get('JSR_METAL_TILE', 'auto')
    available = psutil.virtual_memory().available
    block = (512 if available >= 32 * 2**30 else 384 if psutil.virtual_memory().total >= 24 * 2**30 and available >= 10 * 2**30 else 256) if requested == 'auto' else int(requested)
    if block not in (256, 384, 512):
        raise ValueError('JSR_METAL_TILE must be auto, 256, 384 or 512')
    # The sealed release stores this scheduling parameter as a literal in both contracts.
    for function in (adapter.run, engine._validate_request):
        constants = function.__code__.co_consts
        if sum(type(value) is int and value == 384 for value in constants) != 1:
            raise RuntimeError('Original tile contract changed')
        function.__code__ = function.__code__.replace(co_consts=tuple(
            block if type(value) is int and value == 384 else value for value in constants))
    return {'block_native': block, 'halo_native': 48, 'available_memory_at_selection': available}


@contextmanager
def clone_scratch_files(output):
    root = Path(output).resolve()
    original = shutil.copyfile
    libc = ctypes.CDLL('/usr/lib/libSystem.B.dylib', use_errno=True)
    clone = libc.clonefile
    clone.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint32]
    clone.restype = ctypes.c_int

    def copyfile(src, dst, *, follow_symlinks=True):
        source, destination = Path(src), Path(dst)
        if (follow_symlinks and source.is_file() and not destination.exists()
                and source.resolve().is_relative_to(root) and destination.resolve().is_relative_to(root)):
            if clone(os.fsencode(source), os.fsencode(destination), 0) == 0:
                CLONE_METRICS['files'] += 1
                CLONE_METRICS['logical_bytes'] += source.stat().st_size
                return dst
        return original(src, dst, follow_symlinks=follow_symlinks)

    shutil.copyfile = copyfile
    try:
        yield
    finally:
        shutil.copyfile = original
