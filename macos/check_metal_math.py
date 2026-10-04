"""Verify the stable learned-merge tanh on the actual Metal device."""
from pathlib import Path
import json
import os
import sys

import numpy as np


def main():
    os.environ['WGPU_BACKEND_TYPE'] = 'Metal'
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'Core-Only-Source-Code'))
    import wgpu_buf as gb
    x = np.concatenate([np.linspace(-30, 30, 6001, dtype=np.float32),
                        np.asarray([-1000, -100, -50, 50, 100, 1000], dtype=np.float32)])
    device = gb.dev()
    inputs = gb.upload(x)
    outputs = gb.upload(np.zeros((len(x), 2), np.float32))
    shader = f'''
@group(0) @binding(0) var<storage, read> x: array<f32>;
@group(0) @binding(1) var<storage, read_write> y: array<f32>;
@compute @workgroup_size(64)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {{
    let i = gid.x;
    if (i >= {len(x)}u) {{ return; }}
    let z = x[i];
    let e = exp(-2.0 * abs(z));
    y[2u * i] = tanh(z);
    y[2u * i + 1u] = sign(z) * (1.0 - e) / (1.0 + e);
}}
'''
    pipeline = device.create_compute_pipeline(layout='auto', compute={
        'module': device.create_shader_module(code=shader), 'entry_point': 'main'})
    group = gb.bind(pipeline, [inputs, outputs])
    encoder = device.create_command_encoder()
    compute = encoder.begin_compute_pass()
    compute.set_pipeline(pipeline)
    compute.set_bind_group(0, group, [], 0, 99)
    compute.dispatch_workgroups((len(x) + 63) // 64)
    compute.end()
    device.queue.submit([encoder.finish()])
    result = outputs.numpy()
    error = float(np.max(np.abs(result[:, 1] - np.tanh(x))))
    assert np.isfinite(result[:, 1]).all() and error < 1e-6
    report = {'adapter': gb.info(), 'samples': len(x),
              'builtin_tanh_nonfinite_inputs': x[~np.isfinite(result[:, 0])].tolist(),
              'stable_tanh_max_abs_error': error}
    output = Path(__file__).resolve().parent / 'validation' / 'metal-numerics.json'
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(report, indent=2))
    print(json.dumps(report))


if __name__ == '__main__':
    main()
