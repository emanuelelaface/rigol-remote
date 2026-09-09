#!/usr/bin/env python3
"""Open the GUI stream, receive one frame, then disconnect immediately."""
import asyncio
import json
import struct

from aiohttp import ClientSession, WSMsgType


async def main():
    async with ClientSession() as session:
        async with session.ws_connect('http://127.0.0.1:8080/ws') as ws:
            state = await ws.receive_json(timeout=2)
            print(json.dumps({'connected': state['connected'], 'idn': state['idn'],
                              'error': state['error']}), flush=True)
            while True:
                message = await ws.receive(timeout=5)
                if message.type == WSMsgType.TEXT:
                    status = json.loads(message.data)
                    if status.get('error'):
                        raise RuntimeError(status['error'])
                elif message.type == WSMsgType.BINARY:
                    size = struct.unpack('<I', message.data[:4])[0]
                    frame = json.loads(message.data[4:4 + size])
                    print(json.dumps({'channels': [c['channel'] for c in frame['channels']],
                                      'waiting_channels': frame['waiting_channels'],
                                      'acquisition_ms': frame['acquisition_ms']}), flush=True)
                    return
                elif message.type in {WSMsgType.ERROR, WSMsgType.CLOSED, WSMsgType.CLOSE}:
                    raise RuntimeError(f'WebSocket closed before a frame: {message.type}')


if __name__ == '__main__':
    asyncio.run(main())
