"""Select refinement context independently from the RAW fusion context."""
import functools
import os


def install():
    from wgpu_v81_reconstructor import WgpuV81Reconstructor
    halo = int(os.environ.get('JSR_RARM_HALO', '48'))
    if halo < 17 or halo > 48:
        raise ValueError('JSR_RARM_HALO must be between 17 and 48 native pixels')
    from optimization_support import generic_optimizations
    optimizations = generic_optimizations()
    if optimizations is None:
        if halo != 48:
            raise RuntimeError('Reduced halo requires the portable reconstruction optimizations contribution')
        return
    original = WgpuV81Reconstructor.refine_tile
    if getattr(original, '_jsr_refine_schedule', False):
        return

    @functools.wraps(original)
    def refine(self, *args, **kwargs):
        if len(args) != 9 or kwargs:
            raise RuntimeError('Released refinement signature changed')
        selected = optimizations.refinement_halo(
            halo, args[-1], blocks=self.rarm.blocks, tta_codes=self.rarm_tta_codes)
        return original(self, *args[:-1], selected)

    refine._jsr_refine_schedule = True
    WgpuV81Reconstructor.refine_tile = refine
