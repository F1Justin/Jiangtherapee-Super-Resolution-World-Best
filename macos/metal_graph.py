"""Native FP32 MPSGraph executors with the original network's host-side transforms."""
from pathlib import Path
import ctypes
import json
import threading
import time
import weakref
import os

import numpy as np
import psutil

FLOAT = ctypes.POINTER(ctypes.c_float)
METRICS = {}
MODELS = weakref.WeakSet()


def library():
    path = Path(__file__).resolve().parent / 'vendor/metal/jsr_graph.dylib'
    if not path.is_file():
        raise RuntimeError('Build the Metal bridge with macos/build_metal.py')
    lib = ctypes.CDLL(str(path))
    for name in ('jsr_graph_create', 'jsr_graph_create_controller'):
        function = getattr(lib, name)
        function.argtypes = [ctypes.c_char_p, FLOAT]
        function.restype = ctypes.c_void_p
    lib.jsr_graph_forward.argtypes = [ctypes.c_void_p, FLOAT, FLOAT, ctypes.c_int, ctypes.c_int, ctypes.c_int]
    lib.jsr_graph_forward.restype = ctypes.c_int
    lib.jsr_graph_cache_policy.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_uint64]
    lib.jsr_graph_cache_policy.restype = None
    lib.jsr_graph_metrics.argtypes = [ctypes.c_void_p]
    lib.jsr_graph_metrics.restype = ctypes.c_char_p
    for name in ('jsr_graph_destroy', 'jsr_graph_release_workspaces'):
        function = getattr(lib, name)
        function.argtypes = [ctypes.c_void_p]
        function.restype = None
    for name in ('jsr_graph_error', 'jsr_graph_device_info'):
        function = getattr(lib, name)
        function.argtypes = []
        function.restype = ctypes.c_char_p
    return lib


class NativeGraph:
    def __init__(self, weights, cin, cout, controller=False):
        self._lib = library()
        self._lock = threading.RLock()
        self.cin, self.cout = cin, cout
        self._shape = None
        self._released_controllers = False
        self._kind = 'controller' if controller else 'rarm'
        self._folded = not controller and os.environ.get('JSR_METAL_FOLD_FILM', '0') == '1'
        if self._folded:
            from optimization_support import generic_optimizations
            optimizations = generic_optimizations()
            if optimizations is None:
                raise RuntimeError('FiLM folding requires the portable reconstruction optimizations contribution')
            weights = optimizations.fold_film(weights)
        base_width = weights['enc.0.0.weight' if controller else 'inp.weight'].shape[0]
        # U-Net's deeper channel counts operate at smaller spatial resolutions.
        self._workspace_elements_per_pixel = cin + cout + base_width * 8
        entries, tensors, offset = [], [], 0
        for name, value in sorted(weights.items()):
            value = np.ascontiguousarray(value, np.float32)
            if not np.isfinite(value).all():
                raise ValueError('Model weights must be finite')
            entries.append({'name': name, 'shape': list(value.shape), 'offset': offset,
                            'zero': self._folded and name.endswith('.weight') and not bool(np.any(value))})
            tensors.append(value.reshape(-1))
            offset += value.size
        packed = np.concatenate(tensors)
        create = self._lib.jsr_graph_create_controller if controller else self._lib.jsr_graph_create
        self._handle = create(json.dumps(entries).encode(), packed.ctypes.data_as(FLOAT))
        if not self._handle:
            raise RuntimeError(self._lib.jsr_graph_error().decode())
        self._closed = False
        capacity = int(os.environ.get(f'JSR_{self._kind.upper()}_CACHE', '1'))
        if not 1 <= capacity <= 16:
            self.close()
            raise ValueError('Graph cache capacity must be between 1 and 16')
        device = json.loads(self._lib.jsr_graph_device_info())
        default_budget = min(device['recommended_working_set_bytes'] * 0.25,
                             psutil.virtual_memory().available * 0.65)
        budget = int(float(os.environ.get(f'JSR_{self._kind.upper()}_CACHE_GIB', default_budget / 2**30)) * 2**30)
        if budget <= 0:
            self.close()
            raise ValueError('Graph cache budget must be positive')
        self._lib.jsr_graph_cache_policy(self._handle, capacity, budget)
        MODELS.add(self)
        self.contract = {'executor': 'MPSGraph', 'dtype': 'float32',
                         'reduced_precision_fast_math': False, 'weight_tensor_count': len(weights),
                         'folded_film': self._folded, 'cache_capacity': capacity, 'cache_budget_bytes': budget}

    def forward_residual_batch(self, inputs):
        array = np.ascontiguousarray(inputs, np.float32)
        if array.ndim == 3:
            array = array[None]
        if array.ndim != 4 or array.shape[1] != self.cin or min(array.shape) < 1:
            raise ValueError(f'Expected NCHW C={self.cin}, got {array.shape}')
        batch, _, height, width = array.shape
        if self._kind == 'rarm' and not self._released_controllers:
            # Refinement follows the completed merge; its Controller workspaces can be reclaimed.
            for model in list(MODELS):
                if model._kind == 'controller':
                    model.release_workspaces()
            self._released_controllers = True
        with self._lock:
            if self._closed:
                raise RuntimeError('MPSGraph executor is closed')
            if array.shape != self._shape:
                device = json.loads(self._lib.jsr_graph_device_info())
                budget = min(device['recommended_working_set_bytes'] * 0.65, psutil.virtual_memory().available * 0.75)
                estimated = batch * height * width * self._workspace_elements_per_pixel * 4
                if estimated > budget:
                    raise MemoryError(f'MPSGraph tile estimate {estimated / 2**30:.2f} GiB exceeds available budget {budget / 2**30:.2f} GiB; use smaller tiles')
            output = np.empty((batch, self.cout, height, width), np.float32)
            start = time.perf_counter()
            status = self._lib.jsr_graph_forward(self._handle, array.ctypes.data_as(FLOAT),
                output.ctypes.data_as(FLOAT), batch, height, width)
            if status:
                raise RuntimeError(self._lib.jsr_graph_error().decode())
            self._shape = array.shape
            device = json.loads(self._lib.jsr_graph_device_info())
            metric = METRICS.setdefault(self._kind, {'calls': 0, 'seconds': 0.0, 'peak_metal_allocated_bytes': 0})
            metric['calls'] += 1
            metric['seconds'] += time.perf_counter() - start
            metric['peak_metal_allocated_bytes'] = max(metric['peak_metal_allocated_bytes'], device['allocated_bytes'])
            metric['peak_rss_bytes'] = max(metric.get('peak_rss_bytes', 0), psutil.Process().memory_info().rss)
            metric['native'] = json.loads(self._lib.jsr_graph_metrics(self._handle))
            metric['folded_film'] = self._folded
        if not np.isfinite(output).all():
            raise FloatingPointError('MPSGraph output contains non-finite values')
        return output

    def release_workspaces(self):
        with self._lock:
            if not self._closed:
                self._lib.jsr_graph_release_workspaces(self._handle)
                self._shape = None

    def close(self):
        with self._lock:
            if not self._closed:
                self._lib.jsr_graph_destroy(self._handle)
                self._handle = None
                self._closed = True

    def __del__(self):
        if getattr(self, '_handle', None):
            self.close()


def rarm_class(original):
    class MetalGraphRArm(NativeGraph, original):
        def __init__(self, weights):
            from wgpu_greenfilm_rarm import validate_weights
            self.width, self.blocks = validate_weights(weights)
            NativeGraph.__init__(self, weights, 6, 3)
            self.contract['architecture'] = 'GreenFiLMColorDiffRArm'
    return MetalGraphRArm


def controller_class(original):
    class MetalGraphController(NativeGraph, original):
        def __init__(self, weights):
            from wgpu_unet_tiled import validate_weights
            self.cin, self.cout, self.width, self.depth = validate_weights(weights)
            NativeGraph.__init__(self, weights, self.cin, self.cout, controller=True)
            self.contract['architecture'] = 'LocalV7Controller'

        def forward(self, inputs):
            array = np.asarray(inputs)
            if array.ndim != 3 or min(array.shape[1:]) < 8:
                raise ValueError('Controller input must be CHW with H,W >= 8')
            return self.forward_residual_batch(array)[0]

        def forward_buffer(self, inputs):
            if os.environ.get("JSR_NATIVE_FUSION", "0") == "1":
                from native_fusion import NativeFeatures
                if isinstance(inputs, NativeFeatures):
                    return inputs.session.controller(self)
            import wgpu_buf as gb
            return gb.upload(self.forward(inputs))
    return MetalGraphController


def install():
    import wgpu_greenfilm_rarm
    import wgpu_unet_tiled
    for module, name, factory in [(wgpu_greenfilm_rarm, 'GreenFiLMTiledRArm', rarm_class),
                                  (wgpu_unet_tiled, 'TiledUNet', controller_class)]:
        original = getattr(module, name)
        if original.__module__ != __name__:
            setattr(module, name, factory(original))
