#!/usr/bin/env python3
"""Read a few diagnostic replies, once. Never request waveform data or write settings."""
import argparse
import socket
import time

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('host')
parser.add_argument('--port', type=int, default=5555)
args = parser.parse_args()
for command in ['*IDN?', ':TRIGger:STATus?', ':WAVeform:FORMat?', ':WAVeform:MODE?', ':WAVeform:PREamble?']:
    print(command, flush=True)
    try:
        with socket.create_connection((args.host, args.port), 2) as sock:
            sock.settimeout(2)
            sock.sendall((command + '\n').encode('ascii'))
            with sock.makefile('rb') as stream:
                reply = stream.readline(4096)
            print(repr(reply), flush=True)
            if not reply.endswith(b'\n'):
                break
    except OSError as exc:
        print(f'STOP: {exc}', flush=True)
        break
    time.sleep(.1)
