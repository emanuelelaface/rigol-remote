#!/usr/bin/env python3
"""Bounded read-only check for the zero-preamble WAIT regression."""
import argparse
import asyncio
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rigol_remote.scope import Scope


async def check(host):
    scope = Scope()
    try:
        await scope.connect(host)
        print(json.dumps({'idn': scope.idn, 'status': scope.state[':TRIG:STAT']}, indent=2), flush=True)
        if scope.state[':TRIG:STAT'] == 'WAIT':
            frame = await scope.capture()
            print(json.dumps({'waiting_channels': frame['waiting_channels'],
                              'samples': {ch['channel']: len(ch['data']) for ch in frame['channels']}}), flush=True)
            if scope.wave_touched:
                raise RuntimeError('Regression: waveform settings were touched while waiting.')
        else:
            print('Waveform read skipped: trigger status is not WAIT.', flush=True)
        print('IDN after check:', await scope.transport.query('*IDN?'), flush=True)
    finally:
        await scope.disconnect()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('host')
    args = parser.parse_args()
    asyncio.run(check(args.host))
