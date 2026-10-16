"""Exercise the packaged Z8 batch protocol using two prepared fixture bursts."""
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
        reply = json.loads(worker.stdout.readline())
        assert reply['id'] == serial
        if 'error' in reply:
            raise RuntimeError(reply['error'])
        return reply['result']
    try:
        scanned = request('jsr/batch-scan', {'folder':str(args.fixtures.resolve()),'engine':'fastk14','recursive':True})
        groups = scanned['groups']
        assert len(groups) == 2, scanned
        jobs, results = [], []
        for group in groups:
            selected = request('jsr/select', {'paths':group['selected'],'engine':'fastk14','batch':True})
            preset = request('jsr/camera-preset', {'selection_id':selected['selection_id']})
            payload = {'engine':'fastk14','selection_id':selected['selection_id'],'camera_preset':'z8',
                'output':str(args.output.resolve()),'prefix':group['id'],'dng':True,'tiff':True,
                'preview':False,'memory':4,'host_memory':12,'cpu_cores':4,'color':'libraw'}
            assert request('jsr/batch-validate',payload)['valid']
            jobs.append((payload,preset,selected))
        for payload,preset,selected in jobs:
            start = time.monotonic()
            task = request('jsr/start',payload)
            while time.monotonic()-start < 300:
                status = request('jsr/status')
                if status['state'] != 'running':
                    break
                time.sleep(.5)
            else:
                raise RuntimeError('Batch fixture timeout')
            if status['state'] != 'complete':
                raise RuntimeError(status['log'])
            output = Path(task['output'])
            audit = json.loads((output/'CAMERA_PRESET.json').read_text())
            result = json.loads((output/'RESULT.json').read_text())
            assert audit['iso'] == preset['iso']
            assert result['reference'] in selected['paths']
            assert list(output.glob('*.dng'))
            results.append({'group':payload['prefix'],'state':status['state'],'iso':audit['iso'],
                            'seconds':round(time.monotonic()-start,2)})
        request('jsr/start',jobs[0][0]);time.sleep(.5)
        assert request('jsr/cancel')['state'] == 'cancelled'
        assert request('jsr/select',{'paths':[]})['paths'] == []
        request('jsr/batch-clear-selections')
        report = {'groups':results,'cancel':'passed','selection_reset':'passed','fixtures':'synthetic; not Z8 photographic accuracy validation'}
        (args.output/'report.json').write_text(json.dumps(report,indent=2))
        print(json.dumps(report,indent=2))
    finally:
        worker.stdin.close()
        worker.wait(timeout=20)


if __name__ == '__main__':
    main()
