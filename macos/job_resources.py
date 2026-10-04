"""Reserve export scratch space and record resources during a native RAW job."""
from pathlib import Path
import shutil
import threading
import json

import psutil


class JobResources:
    def __init__(self, output, raw_frame=None, mmap_dir=None, frames=14):
        self.output = Path(output)
        self.output.mkdir(parents=True, exist_ok=True)
        if raw_frame:
            import rawpy
            with rawpy.imread(str(raw_frame)) as raw:
                height, width = raw.sizes.height, raw.sizes.width
            export_bytes = height * width * 4 * 3 * 2
            cache_exists = Path(mmap_dir or self.output / 'NEWHOMOG_cache_mmap').is_dir()
            required = export_bytes * 8 + (0 if cache_exists else height * width * frames * 8) + 512 * 2**20
            if shutil.disk_usage(self.output).free < required:
                raise OSError(f'RAW job needs {required / 2**30:.1f} GiB free for its cache and export workspace')
        self.stop = threading.Event()
        self.minimum_free_bytes = shutil.disk_usage(self.output).free
        self.peak_rss_bytes = 0
        self.thread = threading.Thread(target=self.sample, daemon=True)
        self.thread.start()

    def sample(self):
        process = psutil.Process()
        while not self.stop.is_set():
            self.minimum_free_bytes = min(self.minimum_free_bytes, shutil.disk_usage(self.output).free)
            self.peak_rss_bytes = max(self.peak_rss_bytes, process.memory_info().rss)
            self.stop.wait(1)

    def close(self):
        self.stop.set()
        self.thread.join()
        result = {'minimum_free_disk_bytes': self.minimum_free_bytes, 'peak_rss_bytes': self.peak_rss_bytes}
        (self.output / 'RESOURCES.json').write_text(json.dumps(result, indent=2))
        return result
