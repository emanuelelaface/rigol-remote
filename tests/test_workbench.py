import asyncio
import io
import json
import struct
import unittest
import zipfile

from aiohttp import WSMsgType
from aiohttp.test_utils import TestClient, TestServer

from rigol_remote.scope import Scope, DemoConnection, pack_frame
from rigol_remote.scpi import SCPIError
from rigol_remote.server import create_app, WORKBENCH, Workbench


class ScopeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.scope = Scope()
        await self.scope.connect(demo=True)

    async def asyncTearDown(self):
        await self.scope.disconnect()

    async def test_connect_preserves_acquisition_state(self):
        self.assertEqual(self.scope.state[':TRIG:STAT'], 'TD')
        self.assertEqual(self.scope.channel_count, 2)
        self.assertFalse(self.scope.wave_touched)

    async def test_disabled_channel_is_not_transferred(self):
        await self.scope.command(':CHAN2:DISP 0')
        frame = await self.scope.capture()
        self.assertEqual([c['channel'] for c in frame['channels']], [1])

    async def test_enabled_math_trace_is_transferred_and_packed(self):
        await self.scope.command(':MATH:SCAL 2')
        await self.scope.command(':MATH:OFFS -0.75')
        await self.scope.command(':MATH:DISP 1')
        frame = await self.scope.capture()
        self.assertEqual([item['channel'] for item in frame['channels']], [1, 2, 'MATH'])
        math_trace = frame['channels'][-1]
        self.assertEqual(math_trace['source'], 'MATH')
        self.assertEqual(math_trace['operation'], 'ADD')
        self.assertEqual(math_trace['scale'], 2)
        self.assertEqual(math_trace['offset'], -0.75)
        self.assertEqual(len(math_trace['data']), 1200)
        packet = pack_frame(frame, 10)
        size = struct.unpack('<I', packet[:4])[0]
        header = json.loads(packet[4:4+size])
        self.assertEqual(header['channels'][-1]['channel'], 'MATH')
        self.assertEqual(header['channels'][-1]['start'], 2400)

    async def test_math_position_changes_metadata_without_cancelling_in_samples(self):
        await self.scope.command(':STOP')
        await self.scope.command(':MATH:DISP 1')
        before = (await self.scope.capture())['channels'][-1]
        await self.scope.command(':MATH:OFFS -1')
        after = (await self.scope.capture())['channels'][-1]
        self.assertEqual(before['data'], after['data'])
        self.assertEqual(before['offset'], 0)
        self.assertEqual(after['offset'], -1)

    async def test_fft_trace_carries_its_frequency_axis(self):
        await self.scope.read_fields([
            ':MATH:SCAL', ':MATH:OFFS', ':MATH:FFT:UNIT',
            ':MATH:FFT:HSC', ':MATH:FFT:HCEN'])
        await self.scope.command(':MATH:OPER FFT')
        await self.scope.command(':MATH:DISP 1')
        frame = await self.scope.capture()
        spectrum = frame['channels'][-1]
        self.assertEqual(spectrum['operation'], 'FFT')
        self.assertEqual(spectrum['unit'], 'dB')
        self.assertEqual(spectrum['frequency_scale'], 1000)
        self.assertEqual(spectrum['frequency_center'], 5000)

    async def test_zero_point_math_trace_waits_without_data_or_disconnect(self):
        await self.scope.command(':MATH:DISP 1')
        query = self.scope.transport.query
        sent = []

        async def math_not_ready(command, timeout=None):
            sent.append(command)
            if (command.endswith(':WAV:PRE?')
                    and (':WAV:SOUR MATH' in command
                         or self.scope.transport.state[':WAV:SOUR'] == 'MATH')):
                return '0,0,0,1,2.000000e-06,-1.200000e-03,0,4.000000e+03,0,127'
            return await query(command, timeout)

        self.scope.transport.query = math_not_ready
        frame = await self.scope.capture()
        self.assertEqual([item['channel'] for item in frame['channels']], [1, 2])
        self.assertEqual(frame['waiting_channels'], ['MATH'])
        self.assertTrue(self.scope.connected)
        self.assertEqual(sent.count(':WAV:DATA?'), 2)

    async def test_uncaptured_rigol_record_never_requests_waveform_data(self):
        # Exact reply observed on DS1202Z-E firmware 00.06.03.SP2 in WAIT.
        query = self.scope.transport.query
        sent = []

        async def no_record(command, timeout=None):
            sent.append(command)
            if command == ':TRIG:STAT?':
                return 'WAIT'
            return await query(command, timeout)

        self.scope.transport.query = no_record
        self.scope.state[':TRIG:STAT'] = 'WAIT'
        for _ in range(3):
            frame = await self.scope.capture()
            self.assertEqual(frame['waiting_channels'], [1, 2])
            self.assertEqual(frame['channels'], [])
        self.assertTrue(self.scope.connected)
        self.assertFalse(self.scope.wave_touched)
        self.assertFalse(any(':WAV:' in command for command in sent))
        self.assertFalse(any('DATA?' in command for command in sent))
        self.scope.transport.query = query
        self.assertEqual(len((await self.scope.capture())['channels']), 2)

    async def test_cancelled_background_capture_does_no_instrument_io(self):
        query = self.scope.transport.query
        calls = []

        async def tracked(command, timeout=None):
            calls.append(command)
            return await query(command, timeout)

        self.scope.transport.query = tracked
        self.assertIsNone(await self.scope.capture(lambda: False))
        self.assertEqual(calls, [])

    async def test_malformed_preamble_disconnects_before_data_query(self):
        query = self.scope.transport.query
        sent = []

        async def malformed(command, timeout=None):
            sent.append(command)
            if command.endswith(':WAV:PRE?'):
                return 'unexpected reply'
            return await query(command, timeout)

        self.scope.transport.query = malformed
        with self.assertRaisesRegex(SCPIError, 'unexpected reply'):
            await self.scope.capture()
        self.assertFalse(any('DATA?' in command for command in sent))
        self.assertFalse(self.scope.connected)

    async def test_real_binary_query_replaces_connection_and_discards_tail(self):
        class FakeTransport:
            def __init__(self):
                self.events = []
                self.connected = True

            async def close(self):
                self.events.append('close')
                self.connected = False

            async def open(self):
                self.events.append('open')
                self.connected = True

            async def query(self, command, timeout=None):
                self.events.append(('query', command, timeout))
                return b'waveform'

        transport = FakeTransport()
        self.scope.demo = False
        self.scope.transport = transport
        result = await self.scope._binary_query(':WAV:DATA?', timeout=5)
        self.assertEqual(result, b'waveform')
        self.assertEqual(transport.events, [
            'close', 'open', ('query', ':WAV:DATA?', 5), 'close', 'open'])
        self.assertTrue(transport.connected)

    async def test_disposable_binary_socket_does_not_publish_false_disconnect(self):
        closed = asyncio.Event()
        release = asyncio.Event()

        class BlockingTransport:
            connected = True

            async def close(self):
                self.connected = False
                closed.set()

            async def open(self):
                if release.is_set():
                    self.connected = True

            async def query(self, command, timeout=None):
                await release.wait()
                return b'waveform'

        self.scope.demo = False
        self.scope.transport = BlockingTransport()
        transfer = asyncio.create_task(self.scope._binary_query(':WAV:DATA?'))
        await closed.wait()
        self.assertFalse(self.scope.transport.connected)
        self.assertTrue(self.scope.connected)
        release.set()
        self.assertEqual(await transfer, b'waveform')
        self.assertTrue(self.scope.connected)

    async def test_binary_console_query_replaces_connection(self):
        class FakeTransport:
            def __init__(self):
                self.events = []
                self.connected = True

            async def execute(self, command):
                self.events.append(('execute', command))
                return b'binary result'

            async def close(self):
                self.events.append('close')
                self.connected = False

            async def open(self):
                self.events.append('open')
                self.connected = True

        transport = FakeTransport()
        self.scope.demo = False
        self.scope.transport = transport
        result = await self.scope.command(':SYST:SET?')
        self.assertEqual(result, b'binary result')
        self.assertEqual(transport.events, [
            ('execute', ':SYST:SET?'), 'close', 'open'])

    async def test_field_read_rejects_binary_reply_and_closes(self):
        class FakeTransport:
            connected = True

            async def query(self, command):
                return b'wrong reply type'

            async def close(self):
                self.connected = False

        transport = FakeTransport()
        self.scope.demo = False
        self.scope.transport = transport
        with self.assertRaisesRegex(SCPIError, 'Unexpected binary reply'):
            await self.scope.read_fields([':CHAN1:SCAL'])
        self.assertFalse(transport.connected)

    async def test_waveform_packet_carries_calibration_and_samples(self):
        frame = await self.scope.capture()
        packet = pack_frame(frame, 20)
        size = struct.unpack('<I', packet[:4])[0]
        header = json.loads(packet[4:4+size])
        self.assertEqual(header['fps'], 20)
        self.assertEqual(header['channels'][1]['start'], 1200)
        self.assertEqual(len(packet)-4-size, 2400)
        self.assertEqual(header['channels'][0]['preamble']['format'], 0)

    async def test_full_memory_requires_stop(self):
        with self.assertRaisesRegex(SCPIError, 'Stop the oscilloscope'):
            await self.scope.memory(1)
        self.assertEqual(await self.scope.transport.query(':TRIG:STAT?'), 'TD')

    async def test_memory_export_restores_transfer_settings(self):
        await self.scope.command(':STOP')
        await self.scope.transport.query(':WAV:SOUR CHAN2')
        data = await self.scope.memory(1)
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            self.assertEqual(len(archive.read('channel1.bin')), 1200)
            self.assertEqual(json.loads(archive.read('metadata.json'))['channel'], 1)
        self.assertEqual(await self.scope.transport.query(':WAV:SOUR?'), 'CHAN2')
        self.assertEqual(await self.scope.transport.query(':WAV:MODE?'), 'NORM')
        self.assertEqual(await self.scope.transport.query(':TRIG:STAT?'), 'STOP')

    async def test_disconnect_preserves_channel_and_run_settings(self):
        await self.scope.command(':CHAN1:SCAL 2')
        await self.scope.command(':STOP')
        transport = self.scope.transport
        await self.scope.disconnect()
        self.assertEqual(transport.state[':CHAN1:SCAL'], '2')
        self.assertEqual(transport.state[':TRIG:STAT'], 'STOP')
        self.assertFalse(self.scope.connected)

    async def test_demo_does_not_pretend_to_support_unknown_commands(self):
        with self.assertRaisesRegex(SCPIError, 'not simulated'):
            await self.scope.command(':NO:SUCH:COMMAND 1')


class ServerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.app = create_app(demo=True)
        self.client = TestClient(TestServer(self.app))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()

    async def test_serves_frontend_without_external_assets(self):
        for path in ['/', '/styles.css', '/app.js', '/plot.js', '/controls.js', '/api/catalog']:
            response = await self.client.get(path)
            self.assertEqual(response.status, 200, path)
        response = await self.client.get('/requirements.txt')
        self.assertEqual(response.status, 404)

    async def test_command_roundtrip_and_error(self):
        self.app[WORKBENCH].mode = 'screen'
        started = asyncio.get_running_loop().time()
        response = await self.client.post('/api/action', json={
            'action': 'command', 'command': ':CHAN1:SCAL 2'})
        self.assertEqual(response.status, 200)
        self.assertEqual((await response.json())['state']['values'][':CHAN1:SCAL'], '2')
        self.assertGreater(self.app[WORKBENCH].acquire_after - started, 1.4)
        response = await self.client.post('/api/action', json={'action':'command','command':'invalid'})
        self.assertEqual(response.status, 400)
        self.assertIn('error', await response.json())

    async def test_removing_measurements_does_no_instrument_io(self):
        workbench = self.app[WORKBENCH]
        workbench.measurements = [{'channel': 1, 'item': 'VMAX'}]
        workbench.measured = {'1:VMAX': {'value': 1.2, 'timestamp': 1}}
        query = workbench.scope.transport.query
        calls = []

        async def tracked(command, timeout=None):
            calls.append(command)
            return await query(command, timeout)

        workbench.scope.transport.query = tracked
        response = await self.client.post('/api/action', json={
            'action': 'measurements', 'items': []})
        self.assertEqual(response.status, 200)
        state = (await response.json())['state']
        self.assertTrue(state['connected'])
        self.assertEqual(workbench.measurements, [])
        self.assertEqual(workbench.measured, {})
        self.assertEqual(calls, [])

    async def test_channel_scale_refreshes_source_trigger_level_in_waveform_view(self):
        scope = self.app[WORKBENCH].scope
        query = scope.transport.query
        queries = []

        async def changed_level(command, timeout=None):
            if command == ':TRIG:EDGE:LEV?':
                queries.append(command)
                return '7.500000e-01'
            return await query(command, timeout)

        scope.transport.query = changed_level
        response = await self.client.post('/api/action', json={
            'action': 'stream', 'mode': 'waveform', 'enabled': False})
        self.assertEqual(response.status, 200)
        response = await self.client.post('/api/action', json={
            'action': 'command', 'command': ':CHAN1:SCAL 2'})
        self.assertEqual(response.status, 200)
        state = (await response.json())['state']
        self.assertEqual(queries, [':TRIG:EDGE:LEV?'])
        self.assertEqual(state['values'][':TRIG:EDGE:LEV'], '7.500000e-01')

    async def test_rejects_cross_origin_control(self):
        response = await self.client.post('/api/action', json={'action':'disconnect'}, headers={'Origin':'https://unrelated.example'})
        self.assertEqual(response.status, 403)
        self.assertTrue(self.app[WORKBENCH].scope.connected)

    async def test_rejects_non_json_control(self):
        response = await self.client.post('/api/action', data='{"action":"disconnect"}')
        self.assertEqual(response.status, 415)

    async def test_websocket_streams_bounded_binary_frames_and_pause_keeps_running(self):
        ws = await self.client.ws_connect('/ws')
        initial = await ws.receive_json()
        self.assertTrue(initial['demo'])
        async with asyncio.timeout(3):
            async for msg in ws:
                if msg.type == WSMsgType.BINARY:
                    self.assertGreater(len(msg.data), 2400)
                    break
        response = await self.client.post('/api/action', json={'action':'stream','enabled':False})
        self.assertEqual(response.status, 200)
        self.assertEqual((await response.json())['state']['values'][':TRIG:STAT'], 'TD')
        self.assertEqual(len(self.app[WORKBENCH].clients), 1)
        self.assertTrue(all(q.maxsize == 1 for q in self.app[WORKBENCH].clients.values()))
        await ws.close()

    async def test_slow_client_keeps_only_latest_frame(self):
        workbench = Workbench()
        queue = asyncio.Queue(maxsize=1)
        workbench.clients[object()] = queue
        for number in range(100):
            workbench.frame(bytes([number]))
        self.assertEqual(queue.qsize(), 1)
        self.assertEqual(queue.get_nowait(), bytes([99]))

    async def test_acquisition_error_closes_connection_and_is_not_retried(self):
        class FakeTransport:
            connected = True

            async def close(self):
                self.connected = False

        class BrokenScope:
            def __init__(self):
                self.transport = FakeTransport()
                self.calls = 0
                self.demo = False

            @property
            def connected(self):
                return self.transport.connected

            def info(self):
                return {'connected': self.connected, 'demo': False, 'values': {}}

            async def capture(self, allowed=None):
                self.calls += 1
                raise SCPIError('bad instrument reply')

        class Client:
            closed = False

            async def send_json(self, payload):
                pass

            async def close(self):
                self.closed = True

        workbench = Workbench()
        workbench.scope = BrokenScope()
        workbench.clients[Client()] = asyncio.Queue(maxsize=1)
        task = asyncio.create_task(workbench.acquire())
        await asyncio.sleep(.25)
        workbench.running = False
        await task
        self.assertEqual(workbench.scope.calls, 1)
        self.assertFalse(workbench.scope.connected)
        self.assertFalse(workbench.streaming)
        self.assertEqual(workbench.error, 'bad instrument reply')

    async def test_csv_is_calibrated_and_identifies_instrument(self):
        await self.app[WORKBENCH].scope.capture()
        response = await self.client.get('/api/waveforms.csv')
        self.assertEqual(response.status, 200)
        text = await response.text()
        self.assertIn('DS1202Z-E', text)
        self.assertIn('channel,sample,time_s,amplitude,unit', text)
        self.assertEqual(len(text.splitlines()), 2404)

    async def test_memory_download_and_demo_screen_error(self):
        response = await self.client.get('/api/memory.zip?channel=1')
        self.assertEqual(response.status, 400)
        response = await self.client.get('/api/screenshot.png')
        self.assertEqual(response.status, 400)
        self.assertIn('demo', (await response.json())['error'])
