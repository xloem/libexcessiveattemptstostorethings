#!/usr/bin/env python3

import asyncio
import datetime
import os
import random
import sys
import tempfile
import threading
from contextlib import contextmanager

from bulletprooftoilet import electrum_client_2, bitcoin, bitcom
import electrumx.lib.coins as coins

from asciinema.__main__ import main as asciinema

import zstandard

@contextmanager
def temp_fifo(name = 'fifo'):
    """Context Manager for creating named pipes with temporary names."""
    tmpdir = tempfile.mkdtemp()
    filename = os.path.join(tmpdir, name)  # Temporary filename
    try:
        os.mkfifo(filename)  # Create FIFO
        try:
            yield filename
        finally:
            os.unlink(filename)  # Remove file
    finally:
        os.rmdir(tmpdir)  # Remove directory

def produce_data(fifo):
    sys.argv[1:1] = ['rec']
    if '--help' not in sys.argv and '-h' not in sys.argv:
        sys.argv.append(fifo)
        print("Piping asciinema through", fifo)
    
    asciinema()

async def stream_up(stream, filename, info):
    # note: this private key is not private
    privkey = bitcoin.hex2privkey('088412ca112561ff5db3db83e2756fe447d36ba3c556e158c8f016a2934f7279')

    coin = coins.BitcoinSV
    while True:
        try:
            peer = random.choice(coin.PEERS)
            blockchain = electrum_client_2.ElectrumClient(peer, coin=coin)
            await blockchain.init()
            break
        except OSError:
            continue

    bcat, unspent = await bitcom.stream_up(filename, stream, privkey, blockchain, bcatinfo = info, buffer = False)

    await blockchain.delete()

    print('flush was:', bcat.tx.hex_hash())
 
async def main():
    date = datetime.datetime.now().isoformat(timespec = 'seconds')
    fn = date + '.cast.zst'
    with temp_fifo(fn) as fifo:
        with open(fifo, 'rb') as fifo_input, zstandard.ZstdCompressor() as zstd:
            zstd.copy_stream
        await stream_up(fifo, fn, 'asciinema.zst')

asyncio.run(main())
