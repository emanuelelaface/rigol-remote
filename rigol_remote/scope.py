"""Instrument state, calibrated acquisition, and a deterministic offline demo."""
import asyncio
import io
import json
import math
import re
import struct
import time
import zipfile
from dataclasses import asdict

from .scpi import Preamble, SCPIConnection, SCPIError, WaveformNotReady, validate_command

CORE = [':TRIG:STAT', ':TRIG:MODE', ':TRIG:SWE', ':TIM:MAIN:SCAL',
        ':TIM:MAIN:OFFS', ':TIM:MODE', ':ACQ:SRAT', ':ACQ:MDEP', ':ACQ:TYPE',
        ':MATH:DISP', ':MATH:OPER']
CHANNEL_UNITS = {'VOLT': 'V', 'AMP': 'A', 'WATT': 'W', 'UNKN': ''}
CHANNEL_FIELDS = ['DISP', 'SCAL', 'OFFS', 'COUP', 'PROB', 'BWL', 'INV', 'VERN', 'UNIT']


def numeric(value):
    try:
        number = float(value)
        return number if math.isfinite(number) and abs(number) < 1e30 else None
    except (TypeError, ValueError):
        return None


class Scope:
    def __init__(self):
        self.transport = None
        self.state = {}
        self.idn = ''
        self.host = ''
        self.port = 5555
        self.channel_count = 2
        self.demo = False
        self.saved_wave = {}
        self.wave_touched = False
        self.last_frame = None
        self.wave_configured = False
        self.generation = 0
        self.operation_lock = asyncio.Lock()
        self.binary_transfer = False

    @property
    def connected(self):
        # Binary replies use a disposable socket. The session stays logically
        # connected during that deliberate close/reopen window.
        return (self.transport is not None
                and (self.transport.connected or self.binary_transfer))

    def info(self):
        return {'connected': self.connected, 'demo': self.demo, 'idn': self.idn,
                'host': self.host, 'port': self.port, 'channel_count': self.channel_count,
                'values': dict(self.state), 'generation': self.generation}

    async def connect(self, host='', port=5555, demo=False):
        async with self.operation_lock:
            await self._disconnect()
            self.demo = demo
            self.host, self.port = ('demo', 0) if demo else (host, port)
            self.transport = DemoConnection() if demo else SCPIConnection(host, port)
            try:
                await self.transport.open()
                self.idn = await self.transport.query('*IDN?')
                if not isinstance(self.idn, str) or 'RIGOL' not in self.idn.upper():
                    raise SCPIError('The address did not identify a Rigol oscilloscope.')
                model = self.idn.split(',')[1].strip().upper()
                if not re.fullmatch(r'(?:DS|MSO)1\d{2}[24]Z(?:.*)?', model):
                    raise SCPIError(f'{model}: this driver supports the DS1000Z / DS1000Z-E protocol.')
                self.channel_count = 4 if re.match(r'(?:DS|MSO)1\d{2}4Z', model) else 2
                for field in ['SOUR', 'MODE', 'FORM', 'STAR', 'STOP']:
                    self.saved_wave[field] = await self.transport.query(f':WAV:{field}?')
                await self.sync(full=True)
                # Connecting is read-only. Waveform transfer is configured lazily,
                # and only after an acquisition is actually available.
                self.wave_configured = False
            except BaseException:
                await self._disconnect()
                raise
            return self.info()

    async def _disconnect(self):
        self.binary_transfer = False
        if self.transport:
            if self.connected and self.saved_wave and self.wave_touched:
                try:
                    await self.transport.transaction(
                        [f':WAV:{k} {v}' for k, v in self.saved_wave.items()])
                except SCPIError:
                    pass
            await self.transport.close()
        self.transport = None
        self.state = {}
        self.saved_wave = {}
        self.wave_touched = False
        self.last_frame = None
        self.idn = ''
        self.generation += 1

    async def disconnect(self):
        async with self.operation_lock:
            await self._disconnect()

    async def sync(self, full=False):
        fields = list(CORE)
        for ch in range(1, self.channel_count + 1):
            fields += [f':CHAN{ch}:{key}' for key in (CHANNEL_FIELDS if full else CHANNEL_FIELDS[:3])]
        for field in fields:
            value = await self.transport.query(field + '?')
            if not isinstance(value, str):
                raise SCPIError(f'Unexpected binary reply to {field}?')
            self.state[field] = value
        if self.state.get(':TRIG:MODE') == 'EDGE':
            for key in ['SOUR', 'SLOP', 'LEV']:
                self.state[f':TRIG:EDGE:{key}'] = await self.transport.query(f':TRIG:EDGE:{key}?')
        if self.state.get(':MATH:DISP') in ('1', 'ON'):
            for key in ['SCAL', 'OFFS']:
                self.state[f':MATH:{key}'] = await self.transport.query(f':MATH:{key}?')
            if self.state[':MATH:OPER'] == 'FFT':
                for key in ['UNIT', 'HSC', 'HCEN']:
                    self.state[f':MATH:FFT:{key}'] = await self.transport.query(
                        f':MATH:FFT:{key}?')

    async def command(self, command, refresh_fields=()):
        command = validate_command(command)
        if not isinstance(refresh_fields, (list, tuple)) or len(refresh_fields) > 3:
            raise ValueError('Refresh at most three settings after a command.')
        for field in refresh_fields:
            if (not isinstance(field, str) or '?' in field or ';' in field
                    or not field.startswith((':', '*'))):
                raise ValueError('Expected a SCPI setting name to refresh.')
        async with self.operation_lock:
            if not self.connected:
                raise SCPIError('Connect an oscilloscope first.')
            result = await self.transport.execute(command)
            if isinstance(result, bytes) and not self.demo:
                # A binary console query may have the same undocumented tail as
                # waveform/screenshot transfers. Never use that socket again.
                transport = self.transport
                await transport.close()
                await transport.open()
            if '?' in command and isinstance(result, str):
                self.state[command.replace('?', '')] = result
            if '?' not in command:
                upper = command.upper()
                for part in upper.split(';'):
                    key, separator, value = part.strip().partition(' ')
                    if separator and key in self.state:
                        self.state[key] = value.strip()
                if upper in (':RUN', ':RUNNING'):
                    self.state[':TRIG:STAT'] = 'RUN'
                elif upper in (':STOP',):
                    self.state[':TRIG:STAT'] = 'STOP'
                elif upper in (':SING', ':SINGLE'):
                    self.state[':TRIG:STAT'] = 'WAIT'
                elif upper in (':AUT', ':AUTOSCALE'):
                    self.state[':TRIG:STAT'] = 'AUTO'
                # Only a raw waveform command can invalidate transfer setup.
                if upper.startswith((':WAV:', ':WAVEFORM:')):
                    self.wave_configured = False
                self.generation += 1
                # Give the front-panel operation time to settle before the next
                # explicitly requested read or waveform frame.
                await asyncio.sleep(0.15)
                if refresh_fields:
                    await asyncio.sleep(0.1)
                    for field in refresh_fields:
                        value = await self.transport.query(field + '?')
                        if not isinstance(value, str):
                            await self.transport.close()
                            raise SCPIError(
                                f'Unexpected binary reply to {field}? Connection closed.')
                        self.state[field] = value
            return result

    async def read_fields(self, fields):
        if not isinstance(fields, list) or len(fields) > 50:
            raise ValueError('Read at most 50 settings per request.')
        result = {}
        async with self.operation_lock:
            if not self.connected:
                raise SCPIError('Connect an oscilloscope first.')
            for field in fields:
                if not isinstance(field, str) or '?' in field or ';' in field:
                    raise ValueError('Expected a SCPI setting name.')
                value = await self.transport.query(field + '?')
                if not isinstance(value, str):
                    await self.transport.close()
                    raise SCPIError(f'Unexpected binary reply to {field}? Connection closed.')
                self.state[field] = result[field] = value
        return result

    async def _binary_query(self, command, timeout=None):
        """Read one binary response on a disposable TCP connection.

        DS1202Z-E firmware 00.06.03.SP2 can leave waveform bytes after the
        declared IEEE block. Reusing that socket makes the next text query read
        those samples as its reply. A clean connection boundary is the only
        reliable framing boundary offered by the raw TCP service.
        """
        if self.demo:
            return await self.transport.query(command, timeout=timeout)

        transport = self.transport
        self.binary_transfer = True
        try:
            await transport.close()
            await transport.open()
            result = await transport.query(command, timeout=timeout)
            await transport.close()  # Discard any undocumented trailing bytes.
            await transport.open()   # Clean text-command connection for later use.
            return result
        except BaseException:
            # Do not reconnect or retry after a failed binary transfer.
            await transport.close()
            raise
        finally:
            self.binary_transfer = False

    async def capture(self, allowed=None):
        channels = []
        waiting_channels = []
        start = time.perf_counter()
        async with self.operation_lock:
            if allowed is not None and not allowed():
                return None
            if not self.connected:
                raise SCPIError('Connect an oscilloscope first.')
            enabled = [ch for ch in range(1, self.channel_count + 1)
                       if self.state.get(f':CHAN{ch}:DISP') in ('1', 'ON')]
            sources = [(ch, f'CHAN{ch}') for ch in enabled]
            if self.state.get(':MATH:DISP') in ('1', 'ON'):
                sources.append(('MATH', 'MATH'))
            trigger_status = self.state.get(':TRIG:STAT')
            if trigger_status == 'WAIT':
                trigger_status = await self.transport.query(':TRIG:STAT?')
                self.state[':TRIG:STAT'] = trigger_status
            if trigger_status == 'WAIT':
                return {'channels': [],
                        'waiting_channels': [channel for channel, _ in sources],
                        'timestamp': time.time(),
                        'acquisition_ms': (time.perf_counter() - start) * 1000,
                        'generation': self.generation,
                        'time_scale': numeric(self.state.get(':TIM:MAIN:SCAL')) or 0.001,
                        'time_offset': numeric(self.state.get(':TIM:MAIN:OFFS')) or 0}
            if not self.wave_configured:
                await self.transport.transaction([':WAV:MODE NORM;:WAV:FORM BYTE;:WAV:STAR 1;:WAV:STOP 1200'])
                await asyncio.sleep(0.05)
                self.wave_configured = True
                self.wave_touched = True
            for channel, source in sources:
                # Read calibration with each trace, including changes made on the
                # physical front panel. No interpolation or invented acquisitions.
                pre = await self.transport.query(f':WAV:SOUR {source};:WAV:PRE?')
                try:
                    p = Preamble.parse(pre)
                except WaveformNotReady:
                    waiting_channels.append(channel)
                    continue
                except SCPIError:
                    # Never leave polling active after a malformed response.
                    # In particular, do not request DATA? to try to recover.
                    await self.transport.close()
                    raise
                data = await self._binary_query(':WAV:DATA?')
                if not isinstance(data, bytes) or not 1 <= len(data) <= 1200:
                    await self.transport.close()
                    raise SCPIError('Expected 1–1200 BYTE screen samples.')
                is_math = channel == 'MATH'
                math_operation = self.state.get(':MATH:OPER') if is_math else None
                math_unit = ('dB' if math_operation == 'FFT'
                             and self.state.get(':MATH:FFT:UNIT') == 'DB' else 'V')
                # MATH preambles are useful for converting BYTE samples back to
                # values, but some firmware revisions do not keep their Y origin
                # aligned with the position shown on the display. Use the MATH
                # display controls for placement, falling back to the preamble
                # only when those settings have not been read yet.
                display_scale = (numeric(self.state.get(':MATH:SCAL'))
                                 if is_math else None)
                display_offset = (numeric(self.state.get(':MATH:OFFS'))
                                  if is_math else None)
                channels.append({'channel': channel, 'source': source,
                                 'operation': math_operation,
                                 'preamble': asdict(p), 'data': data,
                                 'scale': (display_scale if display_scale
                                           and display_scale > 0 else p.y_increment * 25),
                                 'offset': (display_offset if display_offset is not None
                                            else p.y_origin * p.y_increment),
                                 'frequency_scale': (numeric(self.state.get(':MATH:FFT:HSC'))
                                                     if is_math and math_operation == 'FFT'
                                                     else None),
                                 'frequency_center': (numeric(self.state.get(':MATH:FFT:HCEN'))
                                                      if is_math and math_operation == 'FFT'
                                                      else None),
                                 'unit': (math_unit if is_math else
                                          CHANNEL_UNITS.get(
                                              self.state.get(f':CHAN{channel}:UNIT'), 'V'))})
            frame = {'channels': channels, 'timestamp': time.time(),
                     'waiting_channels': waiting_channels,
                     'acquisition_ms': (time.perf_counter() - start) * 1000,
                     'generation': self.generation,
                     'time_scale': numeric(self.state.get(':TIM:MAIN:SCAL')) or 0.001,
                     'time_offset': numeric(self.state.get(':TIM:MAIN:OFFS')) or 0}
            self.last_frame = frame
            return frame

    async def screenshot(self, allowed=None):
        async with self.operation_lock:
            if allowed is not None and not allowed():
                return None
            if self.demo:
                raise SCPIError('The demo has no physical screen. Export the waveform as PNG instead.')
            if not self.connected:
                raise SCPIError('Connect an oscilloscope first.')
            data = await self._binary_query(':DISP:DATA? ON,OFF,PNG', timeout=20)
            if not isinstance(data, bytes) or not data.startswith(b'\x89PNG\r\n\x1a\n'):
                await self.transport.close()
                raise SCPIError('The instrument did not return a PNG image.')
            return data

    async def memory(self, channel):
        async with self.operation_lock:
            if not self.connected or channel not in range(1, self.channel_count + 1):
                raise ValueError('Select an available channel.')
            if await self.transport.query(':TRIG:STAT?') != 'STOP':
                raise SCPIError('Stop the oscilloscope before downloading acquisition memory.')
            if self.state.get(f':CHAN{channel}:DISP') != '1':
                raise SCPIError('Enable the selected channel before capturing its memory.')
            saved = {key: await self.transport.query(f':WAV:{key}?')
                     for key in ['SOUR', 'MODE', 'FORM', 'STAR', 'STOP']}
            try:
                await self.transport.transaction([f':WAV:SOUR CHAN{channel};:WAV:MODE RAW;:WAV:FORM BYTE'])
                pre = Preamble.parse(await self.transport.query(':WAV:PRE?'))
                if not 1 <= pre.points <= 24_000_000:
                    raise SCPIError('Unsupported acquisition memory size.')
                data = bytearray()
                for first in range(1, pre.points + 1, 250_000):
                    last = min(first + 249_999, pre.points)
                    chunk = await self._binary_query(
                        f':WAV:STAR {first};:WAV:STOP {last};:WAV:DATA?', timeout=30)
                    if not isinstance(chunk, bytes) or len(chunk) != last - first + 1:
                        await self.transport.close()
                        raise SCPIError('Incomplete acquisition memory block.')
                    data.extend(chunk)
                meta = {'idn': self.idn, 'channel': channel, 'timestamp': time.time(),
                        'preamble': asdict(pre), 'encoding': 'unsigned 8-bit samples',
                        'amplitude': '(sample - y_origin - y_reference) * y_increment',
                        'unit': CHANNEL_UNITS.get(self.state.get(f':CHAN{channel}:UNIT'), 'V'),
                        'time_seconds': '(index - x_reference) * x_increment + x_origin'}
                output = io.BytesIO()
                with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_STORED) as archive:
                    archive.writestr(f'channel{channel}.bin', data)
                    archive.writestr('metadata.json', json.dumps(meta, indent=2))
                return output.getvalue()
            finally:
                if self.connected:
                    await self.transport.transaction([f':WAV:{key} {value}' for key, value in saved.items()])


def pack_frame(frame, fps):
    metadata = {key: value for key, value in frame.items() if key != 'channels'}
    metadata.update(type='waveform', fps=fps, channels=[])
    samples = bytearray()
    for channel in frame['channels']:
        item = {key: value for key, value in channel.items() if key != 'data'}
        item.update(start=len(samples), length=len(channel['data']))
        metadata['channels'].append(item)
        samples.extend(channel['data'])
    header = json.dumps(metadata, separators=(',', ':'), allow_nan=False).encode()
    return struct.pack('<I', len(header)) + header + samples


class DemoConnection:
    """Simulates the controls used by the workbench; other commands fail explicitly."""
    def __init__(self):
        self.connected = False
        self.state = {':TRIG:STAT': 'TD', ':TRIG:MODE': 'EDGE', ':TRIG:SWE': 'AUTO',
                      ':TRIG:EDGE:SOUR': 'CHAN1', ':TRIG:EDGE:SLOP': 'POS', ':TRIG:EDGE:LEV': '0',
                      ':TRIG:COUP': 'DC', ':TRIG:HOLD': '1.6e-8', ':TRIG:NREJ': '0',
                      ':TIM:MAIN:SCAL': '0.0002', ':TIM:MAIN:OFFS': '0', ':TIM:MODE': 'MAIN',
                      ':TIM:DEL:ENAB': '0', ':TIM:DEL:SCAL': '0.00002', ':TIM:DEL:OFFS': '0',
                      ':ACQ:SRAT': '500000000', ':ACQ:MDEP': 'AUTO', ':ACQ:TYPE': 'NORM', ':ACQ:AVER': '16',
                      ':WAV:SOUR': 'CHAN1', ':WAV:MODE': 'NORM', ':WAV:FORM': 'BYTE', ':WAV:STAR': '1', ':WAV:STOP': '1200',
                      ':MATH:DISP': '0', ':MATH:OPER': 'ADD', ':MATH:SOUR1': 'CHAN1', ':MATH:SOUR2': 'CHAN2',
                      ':MATH:SCAL': '1', ':MATH:OFFS': '0', ':MATH:INV': '0', ':MATH:FFT:SOUR': 'CHAN1',
                      ':MATH:FFT:WIND': 'HANN', ':MATH:FFT:SPL': '1', ':MATH:FFT:UNIT': 'DB',
                      ':MATH:FFT:HSC': '1000', ':MATH:FFT:HCEN': '5000', ':MATH:FFT:MODE': 'TRAC',
                      ':CURS:MODE': 'OFF', ':CURS:MAN:TYPE': 'X', ':CURS:MAN:SOUR': 'CHAN1',
                      ':CURS:MAN:AX': '300', ':CURS:MAN:BX': '700', ':CURS:MAN:AY': '100', ':CURS:MAN:BY': '300',
                      ':DISP:TYPE': 'VECT', ':DISP:GRAD:TIME': 'MIN', ':DISP:WBR': '70', ':DISP:GRID': 'FULL', ':DISP:GBR': '40',
                      ':SYST:BEEP': '0', ':SYST:LOCK': '0', ':SYST:LANG': 'ENGL', ':SYST:PON': 'LAT',
                      ':MEAS:STAT:DISP': '0', ':MEAS:STAT:MODE': 'DIFF'}
        for ch in (1, 2):
            for key, value in {'DISP': '1', 'SCAL': '1', 'OFFS': '1.4' if ch == 1 else '-1.4',
                               'COUP': 'DC', 'PROB': '10', 'BWL': 'OFF', 'INV': '0', 'VERN': '0', 'UNIT': 'VOLT'}.items():
                self.state[f':CHAN{ch}:{key}'] = value
        self.phase = 0

    async def open(self):
        self.connected = True

    async def close(self):
        self.connected = False

    async def transaction(self, commands, timeout=None):
        return [await self.query(command) for command in commands]

    async def execute(self, command):
        return await self.query(validate_command(command))

    async def query(self, command, timeout=None):
        if not self.connected:
            raise SCPIError('Demo disconnected.')
        await asyncio.sleep(0.001)
        result = None
        for part in command.split(';'):
            key, _, value = part.strip().partition(' ')
            key = key.upper()
            query = key.endswith('?')
            key = key.rstrip('?')
            if key == '*IDN':
                result = 'RIGOL TECHNOLOGIES,DS1202Z-E,DEMO,SIMULATED'
            elif key == '*OPC':
                result = '1'
            elif key in (':SYST:ERR', ':SYSTEM:ERROR'):
                result = '0,"No error"'
            elif key in (':RUN', ':STOP', ':SING', ':SINGLE', ':TFOR', ':TFORCE'):
                self.state[':TRIG:STAT'] = 'STOP' if key in (':STOP', ':SING', ':SINGLE') else 'TD'
            elif key in (':AUT', ':AUTOSCALE'):
                self.state.update({':TIM:MAIN:SCAL': '0.0002', ':TRIG:STAT': 'TD'})
            elif key in (':CLE', ':CLEAR', ':MEAS:STAT:RES'):
                pass
            elif key == ':WAV:PRE':
                source = self.state[':WAV:SOUR']
                if source == 'MATH':
                    scale = float(self.state[':MATH:SCAL'])
                    offset = float(self.state[':MATH:OFFS'])
                else:
                    ch = int(source[-1])
                    scale = float(self.state[f':CHAN{ch}:SCAL'])
                    offset = float(self.state[f':CHAN{ch}:OFFS'])
                dt = float(self.state[':TIM:MAIN:SCAL']) / 100
                origin = -600*dt + float(self.state[':TIM:MAIN:OFFS'])
                result = f'0,0,1200,1,{dt},{origin},0,{scale/25},{offset/(scale/25)},127'
            elif key == ':WAV:DATA':
                source = self.state[':WAV:SOUR']
                p = Preamble.parse(await self.query(':WAV:PRE?'))
                if self.state[':TRIG:STAT'] != 'STOP':
                    self.phase += 0.005
                def analog(ch, i):
                    angle = 2 * math.pi * 1000 * p.time(i)
                    volts = (1.25*math.sin(angle) if ch == 1 else
                             0.8*math.sin(angle + 0.75))
                    volts += 0.018*math.sin(i*1.7+self.phase)
                    return -volts if self.state[f':CHAN{ch}:INV'] == '1' else volts
                def sample(i):
                    if source == 'MATH':
                        a, b = analog(1, i), analog(2, i)
                        operation = self.state[':MATH:OPER']
                        volts = {'ADD': a+b, 'SUBT': a-b, 'MULT': a*b,
                                 'DIV': a/b if abs(b) > .08 else 0,
                                 'ABS': abs(a), 'SQRT': math.sqrt(abs(a))}.get(
                                     operation, a+b)
                        if operation == 'FFT':
                            volts = 1.1 + .45*math.sin(i*.035) + .2*math.sin(i*.11)
                        if self.state[':MATH:INV'] == '1':
                            volts = -volts
                    else:
                        volts = analog(int(source[-1]), i)
                    # DS1000Z-E MATH screen bytes stay anchored around YREF;
                    # MATH:OFFS is applied by the display separately. Keep the
                    # demo faithful so visual tests catch offset cancellation.
                    origin = 0 if source == 'MATH' else p.y_origin
                    return max(0, min(255, round(volts/p.y_increment + origin + p.y_reference)))
                result = bytes(sample(i) for i in range(1200))
            elif key == ':MEAS:ITEM':
                item = value.split(',')[0].upper()
                ch = value[-1]
                amp = 1.25 if ch == '1' else 0.8
                result = str({'FREQ':1000, 'PER':0.001, 'VPP':amp*2, 'VRMS':amp/math.sqrt(2),
                              'VMAX':amp, 'VMIN':-amp, 'VAVG':0, 'PDUT':0.5, 'NDUT':0.5,
                              'PWID':0.0005, 'NWID':0.0005}.get(item, 9.9e37))
            elif key in self.state:
                if query:
                    result = self.state[key]
                else:
                    self.state[key] = value.upper()
            else:
                raise SCPIError(f'{key} is not simulated. Connect the instrument to use this command.')
        return result
