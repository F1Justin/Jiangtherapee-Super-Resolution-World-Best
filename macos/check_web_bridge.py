"""Exercise packaged IPC, format mapping and cancellation with RAW fixtures."""
from pathlib import Path
import argparse
import json
import subprocess
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cli', type=Path, required=True)
    parser.add_argument('--fixtures', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    worker = subprocess.Popen([str(args.cli.resolve()), 'web-worker'], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    serial = 0
    def request(route, payload=None):
        nonlocal serial
        serial += 1
        worker.stdin.write(json.dumps({'id':serial,'route':route,'payload':payload or {}}) + '\n')
        worker.stdin.flush()
        line = worker.stdout.readline()
        if not line:
            raise RuntimeError('Worker exited')
        reply = json.loads(line)
        if reply['id'] != serial:
            raise RuntimeError('IPC response order')
        if 'error' in reply:
            raise ValueError(reply['error'])
        return reply['result']
    results = {}
    try:
        files = [str(p.resolve()) for p in sorted(args.fixtures.glob('*.dng'))]
        selected = request('jsr/select', {'paths':files,'engine':'fastk14'})
        payload = {'engine':'fastk14','mode':'full','output':str(args.output.resolve()),'prefix':'GUI_test',
                   'manual':True,'black':selected['black'],'read_noise':0,'fullwell':20000,
                   'memory':4,'host_memory':12,'cpu_cores':4,'dng':True,'tiff':True,'preview':False,
                   'format':'jpeg','quality':95,'color':'libraw'}
        for engine in ('fastk14', 'v98k14'):
            start = time.monotonic()
            task = request('jsr/start', {**payload,'engine':engine,'memory':None if engine=='v98k14' else 4})
            while time.monotonic() - start < 180:
                status = request('jsr/status')
                if status['state'] != 'running':
                    break
                time.sleep(.5)
            else:
                request('jsr/cancel')
                raise RuntimeError('Engine timeout')
            (args.output / (engine+'.log')).write_text(status['log'])
            if status['state'] != 'complete':
                raise RuntimeError(status['log'])
            import rawpy
            outputs = list(Path(task['output']).rglob('*.dng'))
            if not outputs:
                raise RuntimeError('Missing DNG')
            with rawpy.imread(str(outputs[0])) as raw:
                shape = list(raw.raw_image_visible.shape)
            if shape[:2] != [selected['height']*2,selected['width']*2] or len(shape) != 3 or shape[2] not in (3,4):
                raise RuntimeError('Output shape: '+str(shape))
            results[engine] = {'state':status['state'],'seconds':round(time.monotonic()-start,2),'shape':shape}
        task = request('jsr/start',payload)
        time.sleep(.5)
        cancelled = request('jsr/cancel')
        if cancelled['state'] != 'cancelled' or request('jsr/status')['state'] != 'cancelled':
            raise RuntimeError('Cancellation failed')
        results['cancel'] = cancelled
        try:
            request('jsr/start',{**payload,'mode':'roi','roi':[0,0,512,512]})
        except ValueError:
            results['reject_unsupported_roi'] = True
        else:
            raise RuntimeError('Accepted unsupported ROI')
        # A completed cancellation must leave the service ready for another selection.
        cleared = request('jsr/select',{'paths':[]})
        assert cleared['paths'] == []
        (args.output / 'report.json').write_text(json.dumps(results,indent=2))
        print(json.dumps(results,indent=2))
    finally:
        worker.stdin.close()
        worker.wait(timeout=15)


if __name__ == '__main__':
    main()
