# Portable reconstruction optimizations

`reconstruction_optimizations.py` provides opt-in NumPy and scheduler helpers for application backends. The published WGPU executors and weight files retain their defaults. This module has no macOS or Metal imports.

## Affine FiLM folding

`fold_film(weights)` composes the affine 3×3 green guide with each pointwise gamma/beta projection. For guide `G*x+g` and projection `P*y+p`, the result is `(P*G)*x+(P*g+p)`. The guide has no intervening activation. Composition uses FP64 followed by FP32 storage, preserves physical-edge padding, and leaves the supplied arrays unchanged. An executor consumes the `folded_gammas.*` and `folded_betas.*` tensors directly; the existing WGPU executor continues to consume original weights. Zero folded weights admit a constant-output specialization in the consuming backend.

## Independent refinement context

`refinement_halo(requested, original, blocks=8, tta_codes=(0,))` selects native-pixel context independently of fusion. The eight-block network has radius 17 output pixels; radius-16 local amplitude raises the composed radius to 33. A native halo of 24 supplies 48 output pixels. Reduced context is restricted to that network and TTA1. Fusion retains its original halo. For the validated 384-pixel tiling, reducing refinement halo from 48 to 24 lowers processed pixels from 150,080,000 to 122,654,720 (18.27%).

## CPU chunk reuse

`install_chunk_reuse(Reconstructor)` wraps `merge_tile` and `_tile_chunks`. The first pass uses `warn=True`; its completed chunks are replayed for the same arguments with `warn=False`. Changed arguments and incomplete first passes regenerate chunks. Cache lifetime ends on success or exception. Chunk consumers treat arrays as read-only. GPU upload reuse belongs to the consuming backend.

These are application integration helpers. The public core contains networks and normalization; its full reconstruction scheduler is distributed in the official application. A maintainer integrates the helpers at network creation and the two-pass scheduler. Windows performance requires a run in that application.

## Validation

```sh
python -m unittest discover -s Core-Only-Source-Code -p test_reconstruction_optimizations.py -v
```

Install `Core-Only-Source-Code/requirements.txt` first. Tests cover published K14 weights, nonzero synthetic FiLM projections, physical edges, input preservation, context guards, cache identity, argument changes, incomplete passes and exception cleanup. Full-image measurements for the Apple backend include these helpers and are documented in that backend's benchmark contribution.
