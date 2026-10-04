"""FP32 Metal tap statistics, local features and learned merge on one native queue."""
import ctypes
import functools
import json
from pathlib import Path
import time

import numpy as np
import psutil
from metal_graph import FLOAT, METRICS, library

INT = ctypes.POINTER(ctypes.c_int32)
SHADER_SOURCE = Path(__file__).with_name('native').joinpath('fusion.metal').read_bytes()
METRICS_FUSION = {'precision': 'float32', 'tap_math': 'release-compatible MSL 3.1 on macOS 14+ / MSL 3.0 on macOS 13; preserved invariance',
                  'frontend_fast_math': False, 'scheduling': 'one resident tile, asynchronous stages on one queue',
                  'tiles': 0, 'uploaded_bytes': 0, 'downloaded_bytes': 0, 'peak_allocated_bytes': 0}


def fusion_library():
    lib = library()
    lib.jsr_fusion_create.argtypes = [ctypes.c_char_p, FLOAT] + [ctypes.c_int] * 6
    lib.jsr_fusion_create.restype = ctypes.c_void_p
    signatures = {
        'phase': [FLOAT, INT, FLOAT, FLOAT, ctypes.c_int, ctypes.c_int, ctypes.c_int],
        'finalize_phase': [ctypes.c_int], 'frontend': [FLOAT],
        'controller': [ctypes.c_void_p], 'learned': [ctypes.c_int, ctypes.c_float],
        'finish': [FLOAT, FLOAT], 'debug': [ctypes.c_int, FLOAT], 'debug_qmap': [FLOAT],
    }
    for name, arguments in signatures.items():
        fn = getattr(lib, 'jsr_fusion_' + name)
        fn.argtypes = [ctypes.c_void_p] + arguments
        fn.restype = ctypes.c_int
    lib.jsr_fusion_destroy.argtypes = [ctypes.c_void_p]
    lib.jsr_fusion_destroy.restype = None
    lib.jsr_fusion_metrics.argtypes = [ctypes.c_void_p]
    lib.jsr_fusion_metrics.restype = ctypes.c_char_p
    return lib


class NativeFeatures:
    def __init__(self, session, channels=151):
        self.session = session
        self.shape = (channels, session.ho, session.wo)
        self.dtype = np.dtype('float32')


class NativeTapSession:
    def __init__(self, covariance, y0r, x0r, height, width, reference_n, reference_m):
        self._lib = fusion_library()
        self.ho, self.wo = height * 2, width * 2
        self.n, self.m = reference_n, reference_m
        if min(height, width, reference_n, reference_m) <= 0:
            raise ValueError('Native fusion dimensions must be positive')
        device = json.loads(self._lib.jsr_graph_device_info())
        estimate = self.ho * self.wo * (361 + 443) * 4
        budget = min(device['recommended_working_set_bytes'] * .65, psutil.virtual_memory().available * .75)
        if estimate > budget:
            raise MemoryError('Native fusion tile exceeds the available memory budget; select a smaller tile')
        covariance = np.ascontiguousarray(covariance, np.float32)
        if covariance.shape != (self.ho * self.wo, 3) or not np.isfinite(covariance).all():
            raise ValueError('Invalid native covariance')
        self._handle = self._lib.jsr_fusion_create(SHADER_SOURCE, covariance.ctypes.data_as(FLOAT),
            y0r, x0r, height, width, reference_n, reference_m)
        if not self._handle:
            raise RuntimeError(self._lib.jsr_graph_error().decode())
        self.phase_frames = self.learned_frames = self._learned_index = 0
        self._chunks = []
        self.max_transient_bytes = 0
        self.legacy = np.empty((self.ho, self.wo, 3), np.float32)
        self._finalized = self._normalized = self._controlled = self._finished = False

    def _call(self, name, *args):
        if not self._handle:
            raise RuntimeError('Native fusion session is closed')
        if getattr(self._lib, 'jsr_fusion_' + name)(self._handle, *args):
            raise RuntimeError(self._lib.jsr_graph_error().decode())

    def accumulate_phase(self, frames, ci, flow, fshift):
        if self._finalized:
            raise RuntimeError('Phase is already finalized')
        frames, flow, fshift = [np.ascontiguousarray(a, np.float32) for a in (frames, flow, fshift)]
        ci = np.ascontiguousarray(ci, np.int32)
        k, nf, mf = frames.shape
        if ci.shape != (nf, mf) or flow.shape != (k, self.n, self.m, 2) or fshift.shape != (k, 4):
            raise ValueError('Native chunk shape mismatch')
        if (min(k, nf, mf) <= 0 or not all(np.isfinite(a).all() for a in (frames, flow, fshift))
                or ci.min() < 0 or ci.max() > 2 or np.any(fshift[:, 2:] < 1)
                or np.any(fshift[:, 2] > nf) or np.any(fshift[:, 3] > mf)):
            raise ValueError('Invalid native chunk values')
        self._call('phase', frames.ctypes.data_as(FLOAT), ci.ctypes.data_as(INT),
            flow.ctypes.data_as(FLOAT), fshift.ctypes.data_as(FLOAT), k, nf, mf)
        self.phase_frames += k
        self._chunks.append(k)
        self.max_transient_bytes += sum(a.nbytes for a in (frames, ci, flow, fshift))

    def phase_and_legacy(self, k_used):
        if self._finalized or k_used != self.phase_frames or k_used <= 0:
            raise RuntimeError('Native phase frame ledger mismatch')
        self._call('finalize_phase', k_used)
        self._finalized = True
        return NativeFeatures(self), self.legacy

    def frontend(self, frontend):
        if not self._finalized or self._normalized:
            raise RuntimeError('Native frontend stage mismatch')
        from local_v7_frontend import _gaussian_kernel
        coefficients = np.concatenate([_gaussian_kernel(16, 4.0), _gaussian_kernel(8, 2.0),
            np.asarray(frontend.mean).reshape(-1), np.asarray(frontend.std).reshape(-1)]).astype(np.float32)
        if coefficients.shape != (352,) or not np.isfinite(coefficients).all() or np.any(coefficients[201:] <= 0):
            raise ValueError('Invalid native frontend coefficients')
        self._call('frontend', coefficients.ctypes.data_as(FLOAT))
        self._normalized = True
        return NativeFeatures(self), None

    def controller(self, model):
        if not self._normalized or self._controlled:
            raise RuntimeError('Native Controller stage mismatch')
        start = time.perf_counter()
        with model._lock:
            self._call('controller', model._handle)
            metric = METRICS.setdefault('controller', {'calls': 0, 'seconds': 0.0, 'peak_metal_allocated_bytes': 0})
            metric['calls'] += 1
            metric['seconds'] += time.perf_counter() - start
            metric['native'] = json.loads(model._lib.jsr_graph_metrics(model._handle))
            metric['gpu_resident_io'] = True
            metric['seconds_semantics'] = 'host enqueue including graph compilation; GPU completion belongs to merge_total'
            device = json.loads(model._lib.jsr_graph_device_info())
            metric['peak_metal_allocated_bytes'] = max(metric['peak_metal_allocated_bytes'], device['allocated_bytes'])
            metric['peak_rss_bytes'] = max(metric.get('peak_rss_bytes', 0), psutil.Process().memory_info().rss)
        self._controlled = True
        return NativeFeatures(self, 36)

    def begin_learned(self, qmap, cap):
        if not self._controlled or not isinstance(qmap, NativeFeatures) or qmap.session is not self:
            raise RuntimeError('Native learned merge stage mismatch')
        self.cap = float(cap)
        if self.cap <= 0 or not np.isfinite(self.cap):
            raise ValueError('Invalid learned merge cap')

    def accumulate_learned(self, frames, ci, flow, fshift):
        if self._learned_index >= len(self._chunks) or frames.shape[0] != self._chunks[self._learned_index]:
            raise RuntimeError('Native learned chunk ledger mismatch')
        self._call('learned', self._learned_index, self.cap)
        self.learned_frames += frames.shape[0]
        self._learned_index += 1

    def learned_merge(self, k_used):
        if k_used != self.learned_frames or k_used != self.phase_frames or self._finished:
            raise RuntimeError('Native learned frame ledger mismatch')
        result = np.empty_like(self.legacy)
        self._call('finish', self.legacy.ctypes.data_as(FLOAT), result.ctypes.data_as(FLOAT))
        self._finished = True
        metric = json.loads(self._lib.jsr_fusion_metrics(self._handle))
        METRICS_FUSION['tiles'] += 1
        for name in ('uploaded_bytes', 'downloaded_bytes'):
            METRICS_FUSION[name] += metric[name]
        METRICS_FUSION['peak_allocated_bytes'] = max(METRICS_FUSION['peak_allocated_bytes'], metric['allocated_bytes'])
        return result

    def debug(self, tensor):
        result = np.empty((151, self.ho, self.wo) if tensor == 0 else
            ((self.ho, self.wo, 3) if tensor == 1 else (36, self.ho, self.wo)), np.float32)
        self._call('debug', tensor, result.ctypes.data_as(FLOAT))
        return result

    def debug_qmap(self, values):
        array = np.ascontiguousarray(values, np.float32)
        if array.shape != (36, self.ho, self.wo) or not np.isfinite(array).all():
            raise ValueError('Invalid debug qmap')
        self._call('debug_qmap', array.ctypes.data_as(FLOAT))

    @property
    def persistent_bytes(self):
        return json.loads(self._lib.jsr_fusion_metrics(self._handle))['allocated_bytes']

    def close(self):
        if getattr(self, '_handle', None):
            self._lib.jsr_fusion_destroy(self._handle)
            self._handle = None

    def __del__(self):
        self.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def install():
    import wgpu_multik_stream_v1
    import local_v7_frontend
    import wgpu_v81_reconstructor
    wgpu_multik_stream_v1.StreamingTapSession = NativeTapSession
    original = local_v7_frontend.CachedLocalV7Frontend.make_controller_input

    @functools.wraps(original)
    def frontend(self, phase, legacy):
        if isinstance(phase, NativeFeatures):
            return phase.session.frontend(self)
        return original(self, phase, legacy)

    local_v7_frontend.CachedLocalV7Frontend.make_controller_input = frontend
    cls = wgpu_v81_reconstructor.WgpuV81Reconstructor
    from optimization_support import generic_optimizations
    optimizations = generic_optimizations()
    if optimizations is not None:
        optimizations.install_chunk_reuse(cls)
