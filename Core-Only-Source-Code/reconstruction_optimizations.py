"""Compose the affine green guide with its spatially pointwise FiLM projections."""
import functools
import numpy as np


def fold_film(weights):
    from wgpu_greenfilm_rarm import validate_weights
    _, blocks = validate_weights(weights)
    guide = weights['guide.weight'].astype(np.float64)
    bias = weights['guide.bias'].astype(np.float64)
    result = {name: value for name, value in weights.items()
              if not name.startswith(('guide.', 'gammas.', 'betas.'))}
    for branch in ('gammas', 'betas'):
        for block in range(blocks):
            prefix = f'{branch}.{block}'
            projection = weights[prefix + '.weight'][:, :, 0, 0].astype(np.float64)
            result['folded_' + prefix + '.weight'] = np.ascontiguousarray(
                np.einsum('oc,cihw->oihw', projection, guide), np.float32)
            result['folded_' + prefix + '.bias'] = np.ascontiguousarray(
                projection @ bias + weights[prefix + '.bias'], np.float32)
    return result


def refinement_halo(requested, original, *, blocks, tta_codes):
    """Bound native context for the eight-block network and radius-16 amplitude."""
    if not 17 <= requested <= 48:
        raise ValueError('Refinement halo must be between 17 and 48 native pixels')
    if requested < 48 and (blocks != 8 or tuple(tta_codes) != (0,)):
        raise ValueError('Reduced halo requires the validated eight-block TTA1 network')
    return min(original, requested)


def install_chunk_reuse(reconstructor_class):
    """Reuse immutable chunks between the phase and learned passes of one tile.

    The scheduler marks its first pass with warn=True and replay with warn=False.
    Chunk arrays remain alive until merge_tile returns; consumers treat them as
    read-only. Calls outside a merge, or with changed arguments, regenerate data.
    """
    merge = reconstructor_class.merge_tile
    chunks = reconstructor_class._tile_chunks
    if getattr(merge, '_jsr_chunk_reuse', False):
        return

    def key(args, kwargs):
        def token(value):
            return id(value) if isinstance(value, np.ndarray) else value
        return tuple(map(token, args)), tuple(sorted(
            (name, token(value)) for name, value in kwargs.items() if name != 'warn'))

    @functools.wraps(merge)
    def merge_tile(self, *args, **kwargs):
        previous = getattr(self, '_jsr_chunk_cache', None)
        self._jsr_chunk_cache = {'key': None, 'chunks': [], 'complete': False}
        try:
            return merge(self, *args, **kwargs)
        finally:
            if previous is None:
                del self._jsr_chunk_cache
            else:
                self._jsr_chunk_cache = previous

    @functools.wraps(chunks)
    def tile_chunks(self, *args, **kwargs):
        cache = getattr(self, '_jsr_chunk_cache', None)
        current = key(args, kwargs)
        if cache is None:
            yield from chunks(self, *args, **kwargs)
        elif kwargs.get('warn', True):
            cache.update(key=current, chunks=[], complete=False)
            for chunk in chunks(self, *args, **kwargs):
                cache['chunks'].append(chunk)
                yield chunk
            cache['complete'] = True
        elif cache['complete'] and cache['key'] == current:
            yield from cache['chunks']
        else:
            yield from chunks(self, *args, **kwargs)

    merge_tile._jsr_chunk_reuse = True
    reconstructor_class.merge_tile = merge_tile
    reconstructor_class._tile_chunks = tile_chunks
