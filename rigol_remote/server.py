"""Local HTTP/WebSocket server. One owner of the instrument, bounded frame queues."""
import argparse
import asyncio
import base64
import contextlib
import csv
import io
import json
import logging
import time
from pathlib import Path
from urllib.parse import urlsplit

from aiohttp import web, WSMsgType

from .scope import Scope, numeric, pack_frame
from .scpi import Preamble, SCPIError

ROOT = Path(__file__).resolve().parent.parent
LOG = logging.getLogger('rigol_remote')
WORKBENCH = web.AppKey('workbench', object)


class Workbench:
    def __init__(self):
        self.scope = Scope()
        self.clients = {}
        self.mode = 'waveform'
        self.target_fps = 10
        self.streaming = True
        self.measurements = []
        self.measured = {}
        self.error = None
        self.running = True
        self.waiting_channels = []

    def status(self):
        return {'type': 'state', **self.scope.info(), 'mode': self.mode,
                'target_fps': self.target_fps, 'streaming': self.streaming,
                'measurements': self.measured, 'error': self.error}

    async def broadcast(self, payload):
        # Reliable state notifications are small. A blocked browser is disconnected
        # instead of stalling acquisition indefinitely.
        async def send(ws):
            try:
                await asyncio.wait_for(ws.send_json(payload), 1)
            except (OSError, RuntimeError, asyncio.TimeoutError):
                await ws.close()
        await asyncio.gather(*(send(ws) for ws in list(self.clients)))

    def frame(self, data):
        for queue in self.clients.values():
            if queue.full():
                queue.get_nowait()
            queue.put_nowait(data)

    async def acquire(self):
        previous = None
        fps = 0
        while self.running:
            started = time.perf_counter()
            if not self.scope.connected or not self.clients or not self.streaming:
                previous = None
                await asyncio.sleep(0.1)
                continue
            try:
                if self.mode == 'screen':
                    data = await self.scope.screenshot()
                    self.frame(data)
                else:
                    frame = await self.scope.capture()
                    self.waiting_channels = frame.get('waiting_channels', [])
                    now = time.perf_counter()
                    if previous is not None:
                        current = 1 / max(now - previous, 1e-6)
                        fps = current if not fps else fps * 0.8 + current * 0.2
                    previous = now
                    self.frame(pack_frame(frame, round(fps, 1)))
            except (SCPIError, ValueError, OSError) as exc:
                self.error = str(exc)
                self.streaming = False
                if self.scope.transport:
                    await self.scope.transport.close()
                LOG.warning('Acquisition: %s', exc)
                await self.broadcast(self.status())
            interval = 1 / (min(self.target_fps, 3) if self.mode == 'screen' else self.target_fps)
            if self.mode == 'waveform' and self.waiting_channels:
                interval = max(interval, 1.0)
            # The DS1000Z firmware needs breathing room between transfers. On
            # hardware, never hammer DATA? back-to-back even if the target rate
            # is higher than the measured transfer rate.
            cooldown = 0.001 if self.scope.demo else 0.05
            await asyncio.sleep(max(cooldown, interval - (time.perf_counter() - started)))

    async def poll(self):
        next_measurement = 0
        index = 0
        while self.running:
            await asyncio.sleep(0.2)
            if not self.scope.connected or not self.clients or self.error:
                continue
            try:
                if (self.measurements and time.monotonic() >= next_measurement
                        and self.scope.state.get(':TRIG:STAT') != 'WAIT'):
                    setting = self.measurements[index % len(self.measurements)]
                    index += 1
                    channel, item = setting['channel'], setting['item']
                    if self.scope.state.get(f':CHAN{channel}:DISP') != '1':
                        value = None
                    else:
                        async with self.scope.operation_lock:
                            if not self.scope.connected:
                                continue
                            reply = await self.scope.transport.query(f':MEAS:ITEM? {item},CHAN{channel}')
                            value = numeric(reply)
                    # DS1000Z returns dimensionless duty/overshoot fractions.
                    if value is not None and item in {'PDUT', 'NDUT', 'OVER', 'PRES'}:
                        value *= 100
                    key = f'{channel}:{item}'
                    self.measured[key] = {'value': value, 'timestamp': time.time()}
                    await self.broadcast({'type': 'measurement', 'key': key, **self.measured[key]})
                    next_measurement = time.monotonic() + 2.0
            except (SCPIError, OSError, ValueError) as exc:
                self.error = str(exc)
                self.streaming = False
                if self.scope.transport:
                    await self.scope.transport.close()
                await self.broadcast(self.status())


@web.middleware
async def protect_and_report(request, handler):
    origin = request.headers.get('Origin')
    if origin and urlsplit(origin).netloc != request.host:
        return web.json_response({'error': 'Cross-origin instrument control is disabled.'}, status=403)
    if request.method == 'POST' and request.content_type != 'application/json':
        return web.json_response({'error': 'Expected application/json.'}, status=415)
    try:
        return await handler(request)
    except (SCPIError, ValueError, TypeError, KeyError, OSError, asyncio.TimeoutError) as exc:
        message = str(exc) or 'The instrument did not respond.'
        LOG.warning('%s: %s', request.path, message)
        return web.json_response({'error': message}, status=400)


async def status(request):
    return web.json_response(request.app[WORKBENCH].status())


async def action(request):
    workbench = request.app[WORKBENCH]
    data = await request.json()
    if not isinstance(data, dict):
        raise ValueError('Expected a JSON object.')
    name = data.get('action')
    result = None
    try:
        if name == 'connect':
            workbench.streaming = False
            await workbench.scope.connect(data.get('host', ''), int(data.get('port', 5555)), data.get('demo') is True)
            workbench.measured.clear()
            workbench.mode = 'waveform'
            workbench.streaming = True
            workbench.error = None
        elif name == 'disconnect':
            workbench.streaming = False
            await workbench.scope.disconnect()
        elif name == 'command':
            result = await workbench.scope.command(data.get('command', ''))
            if isinstance(result, bytes):
                result = {'binary': base64.b64encode(result).decode(), 'length': len(result)}
        elif name == 'read':
            result = await workbench.scope.read_fields(data.get('fields', []))
        elif name == 'stream':
            mode = data.get('mode', workbench.mode)
            fps = int(data.get('fps', workbench.target_fps))
            if mode not in ('waveform', 'screen') or not 1 <= fps <= 60:
                raise ValueError('Choose waveform/screen and a target between 1 and 60 fps.')
            if mode == 'screen' and workbench.scope.demo:
                raise ValueError('Connect the instrument to view its physical screen.')
            workbench.mode, workbench.target_fps = mode, fps
            workbench.streaming = bool(data.get('enabled', workbench.streaming))
            workbench.error = None
        elif name == 'measurements':
            items = data.get('items', [])
            valid_items = {'VMAX','VMIN','VPP','VTOP','VBAS','VAMP','VAVG','VRMS','OVER','PRES',
                           'MAR','MPAR','PER','FREQ','RTIM','FTIM','PWID','NWID','PDUT','NDUT',
                           'TVMAX','TVMIN','PSLEW','NSLEW','VUPP','VMID','VLOW','VAR','PVRMS','PPUL','NPUL','PEDG','NEDG'}
            if not isinstance(items, list) or len(items) > 16:
                raise ValueError('Select at most 16 live measurements.')
            for item in items:
                if item.get('channel') not in range(1, workbench.scope.channel_count + 1) or item.get('item') not in valid_items:
                    raise ValueError('Invalid measurement source or item.')
            workbench.measurements = items
        else:
            raise ValueError('Unknown action.')
    except (SCPIError, OSError, asyncio.TimeoutError) as exc:
        workbench.error = str(exc) or 'The instrument did not respond.'
        workbench.streaming = False
        if workbench.scope.transport:
            await workbench.scope.transport.close()
        raise
    finally:
        await workbench.broadcast(workbench.status())
    return web.json_response({'result': result, 'state': workbench.status()})


async def websocket(request):
    workbench = request.app[WORKBENCH]
    ws = web.WebSocketResponse(heartbeat=20, max_msg_size=8192, compress=False)
    await ws.prepare(request)
    queue = asyncio.Queue(maxsize=1)
    workbench.clients[ws] = queue

    async def sender():
        while not ws.closed:
            data = await queue.get()
            await asyncio.wait_for(ws.send_bytes(data), 3)

    task = asyncio.create_task(sender())
    try:
        await ws.send_json(workbench.status())
        async for msg in ws:
            if msg.type == WSMsgType.ERROR:
                break
    finally:
        workbench.clients.pop(ws, None)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError, OSError, asyncio.TimeoutError, RuntimeError):
            await task
    return ws


async def screenshot(request):
    data = await request.app[WORKBENCH].scope.screenshot()
    return web.Response(body=data, content_type='image/png',
                        headers={'Content-Disposition': 'attachment; filename="rigol-screen.png"'})


async def export_csv(request):
    scope = request.app[WORKBENCH].scope
    frame = scope.last_frame
    if not frame or not frame['channels']:
        raise ValueError('Acquire a waveform before exporting.')
    output = io.StringIO(newline='')
    writer = csv.writer(output)
    writer.writerow(['# Instrument', scope.idn])
    writer.writerow(['# Retrieved UTC epoch', frame['timestamp']])
    writer.writerow(['# Screen samples; channels retrieved sequentially'])
    writer.writerow(['channel', 'sample', 'time_s', 'amplitude', 'unit'])
    for ch in frame['channels']:
        p = Preamble(**ch['preamble'])
        for index, sample in enumerate(ch['data']):
            writer.writerow([ch['channel'], index, f'{p.time(index):.12g}', f'{p.voltage(sample):.12g}', ch['unit']])
    return web.Response(text=output.getvalue(), content_type='text/csv',
                        headers={'Content-Disposition': 'attachment; filename="rigol-waveforms.csv"'})


async def memory(request):
    data = await request.app[WORKBENCH].scope.memory(int(request.query.get('channel', '1')))
    return web.Response(body=data, content_type='application/zip',
                        headers={'Content-Disposition': 'attachment; filename="rigol-memory.zip"'})


async def static_file(request):
    name = request.match_info.get('name', 'index.html')
    if name not in ('index.html', 'app.js', 'styles.css', 'plot.js', 'controls.js', 'favicon.svg'):
        raise web.HTTPNotFound()
    return web.FileResponse(ROOT / 'frontend' / name, headers={'Cache-Control': 'no-cache'})


async def catalog(request):
    return web.FileResponse(Path(__file__).with_name('catalog.json'))


def create_app(host=None, instrument_port=5555, demo=False):
    app = web.Application(middlewares=[protect_and_report], client_max_size=65536)
    workbench = Workbench()
    app[WORKBENCH] = workbench

    async def lifecycle(app):
        if host or demo:
            try:
                await workbench.scope.connect(host or '', instrument_port, demo)
            except (SCPIError, OSError, ValueError) as exc:
                workbench.error = str(exc)
                LOG.warning('Connect: %s', exc)
        tasks = [asyncio.create_task(workbench.acquire()), asyncio.create_task(workbench.poll())]
        yield
        for ws in list(workbench.clients):
            await ws.close(code=1001, message=b'Server shutdown')
        workbench.running = False
        _, pending = await asyncio.wait(tasks, timeout=20)
        for task in pending:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await workbench.scope.disconnect()

    app.cleanup_ctx.append(lifecycle)
    app.add_routes([web.get('/', static_file), web.get('/api/state', status), web.post('/api/action', action),
                    web.get('/ws', websocket), web.get('/api/catalog', catalog),
                    web.get('/api/screenshot.png', screenshot), web.get('/api/waveforms.csv', export_csv),
                    web.get('/api/memory.zip', memory), web.get('/{name}', static_file)])
    return app


def main():
    parser = argparse.ArgumentParser(description='Rigol Remote — DS1000Z / DS1000Z-E workbench')
    parser.add_argument('--host', default='127.0.0.1', help='HTTP bind address (default: localhost)')
    parser.add_argument('--port', type=int, default=8080, help='HTTP port')
    parser.add_argument('--scope', help='Oscilloscope IP address; connect without changing RUN/STOP')
    parser.add_argument('--scope-port', type=int, default=5555)
    parser.add_argument('--demo', action='store_true', help='Start with simulated signals')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
    web.run_app(create_app(args.scope, args.scope_port, args.demo), host=args.host, port=args.port,
                access_log=None, print=lambda message: print(f'Rigol Remote\n{message}'))


if __name__ == '__main__':
    main()
