#!/usr/bin/env python3
"""Force one acquisition and read CH1 once; stop at the first failed reply."""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rigol_remote.scope import Scope
from rigol_remote.scpi import Preamble, SCPIError


async def main(host):
    scope = Scope()
    changed = []
    try:
        await scope.connect(host)
        transport = scope.transport
        print(f'Connected: {scope.idn}', flush=True)

        status = scope.state[':TRIG:STAT']
        if status == 'WAIT':
            error = (await transport.transaction([':TFORce', ':SYSTem:ERRor?']))[-1]
            if not str(error).startswith(('0,', '+0,')):
                raise SCPIError(f'Force trigger failed: {error}')
            await asyncio.sleep(0.25)
            status = await transport.query(':TRIGger:STATus?')
        print(f'Trigger status: {status}', flush=True)

        desired = {'MODE': 'NORM', 'FORM': 'BYTE', 'STAR': '1', 'STOP': '1200', 'SOUR': 'CHAN1'}
        commands = []
        for key, value in desired.items():
            current = scope.saved_wave[key]
            same = current == value or (key in {'STAR', 'STOP'} and int(float(current)) == int(value))
            if not same:
                commands.append(f':WAV:{key} {value}')
                changed.append(key)
        if commands:
            error = (await transport.transaction([*commands, ':SYSTem:ERRor?']))[-1]
            if not str(error).startswith(('0,', '+0,')):
                raise SCPIError(f'Waveform setup failed: {error}')

        raw_preamble = await transport.query(':WAVeform:PREamble?')
        print(f'Preamble: {raw_preamble}', flush=True)
        preamble = Preamble.parse(raw_preamble)
        data = await transport.query(':WAVeform:DATA?', timeout=5)
        if not isinstance(data, bytes) or len(data) != preamble.points:
            raise SCPIError(f'Expected {preamble.points} samples, received {len(data) if isinstance(data, bytes) else type(data).__name__}.')
        print(json.dumps({'channel': 1, 'samples': len(data),
                          'first_samples': list(data[:8])}), flush=True)
        print('IDN after waveform:', await transport.query('*IDN?'), flush=True)
    finally:
        if scope.connected and changed:
            restore = [f':WAV:{key} {scope.saved_wave[key]}' for key in changed]
            await scope.transport.transaction([*restore, ':SYSTem:ERRor?'])
        # Prevent Scope.disconnect from restoring the same settings a second time.
        scope.wave_touched = False
        await scope.disconnect()


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit(f'usage: {sys.argv[0]} HOST')
    asyncio.run(main(sys.argv[1]))
