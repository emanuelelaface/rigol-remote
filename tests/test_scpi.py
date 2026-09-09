import asyncio
import json
import unittest
from pathlib import Path

from rigol_remote.scpi import Preamble, SCPIConnection, SCPIError, WaveformNotReady, validate_command


class CalibrationTests(unittest.TestCase):
    def test_voltage_and_time_use_all_calibration_fields(self):
        pre = Preamble.parse('0,0,1200,1,0.000001,-0.0006,2,0.02,25,127')
        self.assertAlmostEqual(pre.voltage(177), 0.5)
        self.assertAlmostEqual(pre.time(602), 0)

    def test_rejects_invalid_preamble_and_wrong_format(self):
        for response in ['1,0,1200,1,1,0,0,1,0,127', '0,0,1200,1,nan,0,0,1,0,127', '0,0,0,1,1,0,0,1,0,127', 'garbage']:
            with self.subTest(response=response), self.assertRaises(SCPIError):
                Preamble.parse(response)

    def test_zero_point_math_preamble_is_waiting_not_corrupt(self):
        response = '0,0,0,1,2.000000e-06,-1.200000e-03,0,4.000000e+03,0,127'
        with self.assertRaises(WaveformNotReady):
            Preamble.parse(response)

    def test_commands_cannot_desynchronize_reply_count(self):
        for command in [':A?;:B?', ':A?;:RUN', ':RUN\n*IDN?', ':CHAN<n>:SCAL 1', ':RUN;STOP', '', 'hello']:
            with self.subTest(command=command), self.assertRaises(ValueError):
                validate_command(command)
        self.assertEqual(validate_command(':CHAN1:SCAL 1;:CHAN1:SCAL?'), ':CHAN1:SCAL 1;:CHAN1:SCAL?')

    def test_catalog_does_not_include_pdf_pagination(self):
        entries = json.loads((Path(__file__).parents[1] / 'rigol_remote/catalog.json').read_text())
        self.assertGreater(len(entries), 350)
        self.assertTrue(all('Chapter ' not in form and 'Syntax ' not in form for e in entries for form in e['forms']))


class TransportTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.received = []
        self.connections = 0
        self.writers = []
        self.error = '0,"No error"'
        self.server = await asyncio.start_server(self.handle, '127.0.0.1', 0)
        self.connection = SCPIConnection('127.0.0.1', self.server.sockets[0].getsockname()[1], timeout=.15)
        await self.connection.open()

    async def asyncTearDown(self):
        await self.connection.close()
        for writer in self.writers:
            writer.close()
        self.server.close()
        await self.server.wait_closed()

    async def handle(self, reader, writer):
        self.connections += 1
        self.writers.append(writer)
        try:
            while line := await reader.readline():
                command = line.decode().strip()
                self.received.append(command)
                if '?' not in command:
                    continue
                if command == ':BLOCK?':
                    # Header, count and data fragmented; payload itself includes LF.
                    for chunk in [b'#', b'1', b'5', b'a\n', b'bcd', b'\r', b'\n']:
                        writer.write(chunk)
                        await writer.drain()
                        await asyncio.sleep(.001)
                    continue
                if command == ':NOEND?':
                    writer.write(b'#13abc')
                elif command == ':TRUNCATED?':
                    writer.write(b'#15abc')
                    await writer.drain()
                    writer.close()
                    return
                elif command == ':OVERSIZE?':
                    writer.write(b'#9999999999')
                elif command == ':BADHEADER?':
                    writer.write(b'#0')
                elif command == ':NONASCII?':
                    writer.write(b'~\xff~\n')
                elif command == ':TIMEOUT?':
                    continue
                elif command == ':SYSTem:ERRor?':
                    writer.write((self.error+'\n').encode())
                else:
                    writer.write((command+' reply\n').encode())
                await writer.drain()
        except (ConnectionError, asyncio.CancelledError):
            pass

    async def test_fragmented_block_and_following_text(self):
        self.assertEqual(await self.connection.query(':BLOCK?'), b'a\nbcd')
        self.assertEqual(await self.connection.query('*IDN?'), '*IDN? reply')

    async def test_binary_block_without_terminator(self):
        self.assertEqual(await self.connection.query(':NOEND?'), b'abc')
        self.assertEqual(await self.connection.query(':NEXT?'), ':NEXT? reply')

    async def test_concurrent_queries_use_one_connection_and_correct_replies(self):
        commands = [f':VALUE{i}?' for i in range(30)]
        results = await asyncio.gather(*(self.connection.query(c) for c in commands))
        self.assertEqual(results, [c+' reply' for c in commands])
        self.assertEqual(self.connections, 1)

    async def test_write_does_not_generate_automatic_queries(self):
        await self.connection.execute(':CHAN1:SCAL 1')
        await asyncio.sleep(.01)
        self.assertEqual(self.received, [':CHAN1:SCAL 1'])

    async def test_instrument_error_can_be_queried_explicitly(self):
        self.error = '-222,"Data out of range"'
        await self.connection.execute(':CHAN1:SCAL -1')
        self.assertEqual(await self.connection.query(':SYSTem:ERRor?'), self.error)
        self.assertTrue(self.connection.connected)

    async def test_partial_block_closes_connection(self):
        with self.assertRaises(SCPIError):
            await self.connection.query(':TRUNCATED?')
        self.assertFalse(self.connection.connected)

    async def test_timeout_closes_connection_and_is_not_retried(self):
        with self.assertRaises(SCPIError):
            await self.connection.query(':TIMEOUT?')
        self.assertFalse(self.connection.connected)
        self.assertEqual(self.received, [':TIMEOUT?'])

    async def test_cancellation_invalidates_stream(self):
        task = asyncio.create_task(self.connection.query(':TIMEOUT?'))
        await asyncio.sleep(.02)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertFalse(self.connection.connected)

    async def test_oversized_block_is_rejected(self):
        with self.assertRaisesRegex(SCPIError, '32 MB'):
            await self.connection.query(':OVERSIZE?')

    async def test_indefinite_block_is_rejected(self):
        with self.assertRaisesRegex(SCPIError, 'definite-length'):
            await self.connection.query(':BADHEADER?')

    async def test_binary_bytes_in_text_reply_close_connection(self):
        with self.assertRaisesRegex(SCPIError, 'binary bytes'):
            await self.connection.query(':NONASCII?')
        self.assertFalse(self.connection.connected)
