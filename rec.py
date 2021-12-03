#!/usr/bin/env python3

import asyncio
import datetime
import os
import random
import sys
import tempfile
import threading
import time
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
    sys.argv.append(fifo)
    try:
        asciinema()
    except SystemExit:
        pass

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

def compress_data(in_fifo, out_fifo, eof_event):
    compression_params = zstandard.ZstdCompressionParameters.from_level(22, write_checksum=True, enable_ldm=True)
    # open call below blocks until data available
    with open(in_fifo, 'rb') as uncompressed_stream, open(out_fifo, 'wb') as compressed_stream:
        zstd = zstandard.ZstdCompressor(compression_params = compression_params)

        with zstd.stream_writer(compressed_stream) as zstdsink:
            while True:
                new_data = uncompressed_stream.read1(1024 * 1024 * 1024)
                if len(new_data) > 0:
                    zstdsink.write(new_data)
                    zstdsink.flush()
                elif eof_event.is_set():
                    break
                else:
                    time.sleep(0.2)

def send_data(in_fifo, filename):
    with open(in_fifo, 'r') as compressed_stream:
        asyncio.run(stream_up(compressed_stream, filename + '.zst', 'asciinema.zst'))

 
def main():
    is_help = '--help' in sys.argv or '-h' in sys.argv
    if is_help:
        produce_data('/dev/null')
    else:
        date = datetime.datetime.now().isoformat(timespec = 'seconds')
        fn = date + '.cast'
        with temp_fifo(fn) as uncompressed_fifo, temp_fifo(fn) as compressed_fifo:
            eof_event = threading.Event()
            data_compressor = threading.Thread(target = compress_data, args=(uncompressed_fifo, compressed_fifo, eof_event))
            data_compressor.start()
            data_sender = threading.Thread(target = send_data, args=(compressed_fifo, fn))
            data_sender.start()

            # asciinema wants to be main thread
            generated_data = produce_data(uncompressed_fifo)

            eof_event.set()
            data_compressor.join()
            data_sender.join()

main()

