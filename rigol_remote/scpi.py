"""A single, serialized SCPI stream. Never retry a write after a timeout."""
import asyncio
import math
import re
import socket
from dataclasses import dataclass


class SCPIError(Exception):
    """An instrument or protocol error that is safe to show to the operator."""


class WaveformNotReady(SCPIError):
    """The scope has no captured record yet; DATA? must not be sent."""


def validate_command(command: str) -> str:
    if not isinstance(command, str) or not command.strip():
        raise ValueError('Enter a SCPI command.')
    command = command.strip()
    if len(command) > 4096 or any(ord(c) < 32 or ord(c) > 126 for c in command):
        raise ValueError('Use one ASCII SCPI line, at most 4096 characters.')
    if '<' in command or '>' in command:
        raise ValueError('Replace the parameter placeholders before sending.')
    parts = command.split(';')
    if any(not p.strip().startswith((':', '*')) for p in parts):
        raise ValueError('Each command must start with : or * (including after ;).')
    if command.count('?') > 1 or any('?' in p for p in parts[:-1]):
        raise ValueError('Send one query at a time, at the end of the command line.')
    return command


@dataclass(frozen=True)
class Preamble:
    format: int
    mode: int
    points: int
    count: int
    x_increment: float
    x_origin: float
    x_reference: float
    y_increment: float
    y_origin: float
    y_reference: float

    @classmethod
    def parse(cls, response: str):
        try:
            fields = [float(v) for v in response.split(',')]
            if len(fields) != 10 or not all(math.isfinite(v) for v in fields):
                raise ValueError
            if fields[0] != 0:
                raise ValueError
            if fields[2] == 0 and fields[4] == 0 and fields[7] == 0:
                raise WaveformNotReady('Waiting for an acquisition; no waveform data requested.')
            if fields[2] <= 0 or fields[4] <= 0 or fields[7] <= 0:
                raise ValueError
            return cls(*(int(v) for v in fields[:4]), *fields[4:])
        except (AttributeError, TypeError, ValueError) as exc:
            raise SCPIError(f'Invalid BYTE waveform preamble: {response!r}') from exc

    def voltage(self, sample: int) -> float:
        return (sample - self.y_origin - self.y_reference) * self.y_increment

    def time(self, index: int) -> float:
        return (index - self.x_reference) * self.x_increment + self.x_origin


class SCPIConnection:
    MAX_BLOCK = 32 * 1024 * 1024

    def __init__(self, host: str, port: int = 5555, timeout: float = 5):
        if not isinstance(host, str) or not re.fullmatch(r'[a-zA-Z0-9_.:%-]{1,253}', host):
            raise ValueError('Enter a valid IP address or hostname.')
        if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
            raise ValueError('Port must be between 1 and 65535.')
        self.host, self.port, self.timeout = host, port, timeout
        self.reader = self.writer = None
        self.lock = asyncio.Lock()

    @property
    def connected(self):
        return self.writer is not None and not self.writer.is_closing()

    async def open(self):
        self.reader, self.writer = await asyncio.wait_for(
            asyncio.open_connection(self.host, self.port, limit=self.MAX_BLOCK), self.timeout)
        sock = self.writer.get_extra_info('socket')
        if sock:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)

    async def close(self):
        writer, self.writer = self.writer, None
        self.reader = None
        if writer:
            writer.close()
            try:
                await asyncio.wait_for(writer.wait_closed(), 1)
            except (OSError, asyncio.TimeoutError):
                pass

    async def _reply(self):
        # Firmware varies in its block terminator. Consume optional CR/LF before
        # the next reply, without waiting for a terminator that might be absent.
        first = await self.reader.readexactly(1)
        skipped = 0
        while first in (b'\r', b'\n'):
            skipped += 1
            if skipped > 8:
                raise SCPIError('Too many empty SCPI replies.')
            first = await self.reader.readexactly(1)
        if first == b'#':
            digit = await self.reader.readexactly(1)
            if digit not in b'123456789':
                raise SCPIError('Expected an IEEE 488.2 definite-length binary block.')
            length_text = await self.reader.readexactly(int(digit))
            if not length_text.isdigit():
                raise SCPIError('Invalid binary block length.')
            length = int(length_text)
            if length > self.MAX_BLOCK:
                raise SCPIError('Instrument reply exceeds the 32 MB limit.')
            return await self.reader.readexactly(length)
        line = first + await self.reader.readline()
        if not line.endswith(b'\n'):
            raise SCPIError('Instrument disconnected during a text reply.')
        try:
            text = line.decode('ascii').strip()
        except UnicodeDecodeError as exc:
            raise SCPIError('Received binary bytes where a text SCPI reply was expected.') from exc
        if any(ord(character) < 32 or ord(character) == 127 for character in text):
            raise SCPIError('Received control bytes where a text SCPI reply was expected.')
        return text

    async def _exchange(self, command: str):
        if not self.connected:
            raise SCPIError('The instrument is disconnected. Connect again to resume.')
        query = '?' in command
        self.writer.write((command + '\n').encode('ascii'))
        await self.writer.drain()
        # Writes produce no reply on the DS1000Z raw TCP service. A following
        # query in the same serialized transaction is the ordering barrier.
        return await self._reply() if query else None

    async def transaction(self, commands, timeout=None):
        commands = [validate_command(c) for c in commands]
        async with self.lock:
            try:
                async with asyncio.timeout(timeout or self.timeout):
                    return [await self._exchange(c) for c in commands]
            except asyncio.CancelledError:
                await self.close()  # Interrupted replies cannot be reused safely.
                raise
            except (OSError, asyncio.TimeoutError, asyncio.IncompleteReadError, SCPIError) as exc:
                await self.close()
                detail = str(exc) or 'The instrument did not respond before the timeout.'
                raise SCPIError(detail) from exc

    async def query(self, command, timeout=None):
        return (await self.transaction([command], timeout))[0]

    async def execute(self, command):
        command = validate_command(command)
        if '?' in command:
            return await self.query(command, timeout=15)
        # The raw TCP service produces no acknowledgement for writes. Do not
        # follow every front-panel command with a burst of status/error queries:
        # firmware 00.06.03.SP2 can become unresponsive under that pattern.
        await self.transaction([command], timeout=5)
        return None
