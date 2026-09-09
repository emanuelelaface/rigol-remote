#!/usr/bin/env python3
"""One bounded real-instrument check. Never retry after a failed reply."""
import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rigol_remote.scope import Scope
from rigol_remote.scpi import SCPIError


async def check(host, frames):
    scope = Scope()
    succeeded = False
    try:
        async with asyncio.timeout(30):
            await scope.connect(host)
            print(json.dumps({'connected': scope.idn,
                              'trigger': scope.state[':TRIG:STAT']}), flush=True)

            if scope.state[':TRIG:STAT'] == 'WAIT':
                await scope.command(':TFOR')
                await asyncio.sleep(.3)

            for index in range(frames):
                frame = await scope.capture()
                if frame['waiting_channels'] and not frame['channels']:
                    raise SCPIError('Trigger still waiting; no waveform transfer attempted.')
                print(json.dumps({
                    'frame': index + 1,
                    'channels': {item['channel']: len(item['data'])
                                 for item in frame['channels']},
                    'milliseconds': round(frame['acquisition_ms'], 1),
                }), flush=True)

                if index + 1 == frames // 2:
                    scale = scope.state[':CHAN1:SCAL']
                    await scope.command(f':CHAN1:SCAL {scale}')
                    value = (await scope.read_fields([':CHAN1:SCAL']))[':CHAN1:SCAL']
                    print(json.dumps({'control': 'CH1 scale unchanged',
                                      'readback': value}), flush=True)
                await asyncio.sleep(.2)

            identity = await scope.transport.query('*IDN?')
            if identity != scope.idn:
                raise SCPIError(f'Unexpected final identity reply: {identity!r}')
            print(json.dumps({'final_idn': identity, 'result': 'PASS'}), flush=True)
            succeeded = True
    finally:
        if not succeeded:
            # A failed exchange is a hard stop: close only, with no restoration
            # writes and no attempt to reconnect or probe the instrument.
            scope.wave_touched = False
        await scope.disconnect()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('host')
    parser.add_argument('--frames', type=int, default=6, choices=range(1, 11))
    args = parser.parse_args()
    asyncio.run(check(args.host, args.frames))
