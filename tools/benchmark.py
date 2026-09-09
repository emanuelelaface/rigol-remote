#!/usr/bin/env python3
"""Read-only acquisition benchmark; restores waveform transfer settings on exit."""
import argparse
import asyncio
import json
import statistics
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rigol_remote.scpi import SCPIConnection, Preamble


async def benchmark(host, port, frames):
    scope = SCPIConnection(host, port)
    await scope.open()
    saved = {}
    result = {'idn': await scope.query('*IDN?'), 'frames_per_test': frames}
    try:
        for field in ['SOURce', 'MODE', 'FORMat', 'STARt', 'STOP']:
            saved[field] = await scope.query(f':WAVeform:{field}?')
        active = [ch for ch in (1, 2) if await scope.query(f':CHANnel{ch}:DISPlay?') == '1']
        result['channels'] = active
        await scope.transaction([':WAVeform:MODE NORMal;:WAVeform:FORMat BYTE;:WAVeform:STARt 1;:WAVeform:STOP 1200'])
        for mode in ['binary', 'png']:
            durations, sizes = [], []
            for _ in range(frames if mode == 'binary' else min(frames, 5)):
                start = time.perf_counter()
                size = 0
                if mode == 'binary':
                    for ch in active:
                        pre = await scope.query(f':WAVeform:SOURce CHANnel{ch};:WAVeform:PREamble?')
                        p = Preamble.parse(pre)
                        data = await scope.query(':WAVeform:DATA?')
                        assert isinstance(data, bytes), data
                        size += len(data)
                        result.setdefault('preambles', {})[str(ch)] = p.__dict__
                else:
                    data = await scope.query(':DISPlay:DATA? ON,OFF,PNG', timeout=30)
                    assert isinstance(data, bytes) and data.startswith(b'\x89PNG'), repr(data)[:80]
                    size = len(data)
                durations.append(time.perf_counter() - start)
                sizes.append(size)
            result[mode] = {'fps': round(1/statistics.mean(durations), 2),
                            'mean_ms': round(statistics.mean(durations)*1000, 2),
                            'bytes_per_frame': round(statistics.mean(sizes))}
        print(json.dumps(result, indent=2), flush=True)
    finally:
        if scope.connected:
            for field in ['SOURce', 'MODE', 'FORMat', 'STARt', 'STOP']:
                if field in saved:
                    await scope.transaction([f':WAVeform:{field} {saved[field]}'])
            try:
                result['error'] = await scope.query(':SYSTem:ERRor?')
            except Exception as exc:
                result['restore_error'] = str(exc)
        await scope.close()
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('host')
    parser.add_argument('--port', type=int, default=5555)
    parser.add_argument('--frames', type=int, default=20)
    args = parser.parse_args()
    asyncio.run(benchmark(args.host, args.port, args.frames))
