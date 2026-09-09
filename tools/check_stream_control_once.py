#!/usr/bin/env python3
"""Receive one frame, exercise one control, receive one more, then stop."""
import asyncio
import json
import struct

from aiohttp import ClientSession, WSMsgType


async def receive_frame(ws):
    while True:
        message = await ws.receive(timeout=6)
        if message.type == WSMsgType.TEXT:
            state = json.loads(message.data)
            if state.get('error'):
                raise RuntimeError(state['error'])
        elif message.type == WSMsgType.BINARY:
            size = struct.unpack('<I', message.data[:4])[0]
            return json.loads(message.data[4:4 + size])
        else:
            raise RuntimeError(f'Stream closed before a frame: {message.type}')


async def main():
    async with ClientSession() as session:
        async with session.ws_connect('http://127.0.0.1:8080/ws') as ws:
            state = await ws.receive_json(timeout=2)
            if not state.get('connected'):
                raise RuntimeError(state.get('error') or 'Instrument is not connected.')
            scale = state['values'][':CHAN1:SCAL']

            first = await receive_frame(ws)
            print(json.dumps({'first_frame_channels': [c['channel'] for c in first['channels']],
                              'first_frame_ms': first['acquisition_ms']}), flush=True)

            response = await session.post('http://127.0.0.1:8080/api/action', json={
                'action': 'command', 'command': f':CHAN1:SCAL {scale}'})
            body = await response.json()
            if response.status != 200:
                raise RuntimeError(body.get('error', f'HTTP {response.status}'))
            print(json.dumps({'control': 'CH1 scale unchanged', 'value': scale}), flush=True)

            second = await receive_frame(ws)
            print(json.dumps({'second_frame_channels': [c['channel'] for c in second['channels']],
                              'second_frame_ms': second['acquisition_ms']}), flush=True)

            response = await session.post('http://127.0.0.1:8080/api/action', json={
                'action': 'command', 'command': '*IDN?'})
            body = await response.json()
            if response.status != 200:
                raise RuntimeError(body.get('error', f'HTTP {response.status}'))
            print(json.dumps({'idn_after_test': body['result']}), flush=True)


if __name__ == '__main__':
    asyncio.run(main())
