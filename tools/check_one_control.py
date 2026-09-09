#!/usr/bin/env python3
"""Exercise one GUI control path once, without waveform acquisition."""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rigol_remote.scope import Scope


async def main(host):
    scope = Scope()
    try:
        await scope.connect(host)
        original = scope.state[':CHAN1:SCAL']
        await scope.command(f':CHAN1:SCAL {original}')
        readback = (await scope.read_fields([':CHAN1:SCAL']))[':CHAN1:SCAL']
        identity = await scope.transport.query('*IDN?')
        print(json.dumps({'idn': identity, 'written': original,
                          'readback': readback, 'connected': scope.connected}), flush=True)
    finally:
        scope.wave_touched = False
        await scope.disconnect()


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit(f'usage: {sys.argv[0]} HOST')
    asyncio.run(main(sys.argv[1]))
