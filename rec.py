#!/usr/bin/env python3

# thoughts on mempool exhaustion:
## when per-kb fee is lower than a node is configured for, it by default only allows 25 unconfirmed chained txs
## if fee is higher, it is more like a 10k chain

import asyncio
import curses
import datetime
import io
import logging
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

import segno
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

def err2str(error):
    return ''.join(traceback.format_exception(type(error), error, error.__traceback__))

## dual-stream logging config from stackoverflow

#Get the root logger
logger = logging.getLogger()
#Have to set the root logger level, it defaults to logging.WARNING
logger.setLevel(logging.NOTSET)

logging_handler_file = logging.FileHandler("rec.log")
logging_handler_file.setLevel(logging.DEBUG)
logger.addHandler(logging_handler_file)

logging_handler_err = logging.StreamHandler(sys.stderr)
logging_handler_err.setLevel(logging.WARNING)
logger.addHandler(logging_handler_err)

## ##

def produce_data(fifo):
    sys.argv[1:1] = ['rec']
    sys.argv.append(fifo)
    try:
        asciinema()
    except SystemExit:
        pass
    except Exception as e:
        logging.getLogger().error(err2str(e))

async def stream_up(stream, filename, info):
    # note: this private key is not private
    privkey = bitcoin.hex2privkey('088412ca112561ff5db3db83e2756fe447d36ba3c556e158c8f016a2934f7279')

    coin = coins.BitcoinSV
    fee_per_kb = 250
    mempool_depth = 25
    block_seconds = 600

    peer = 'sv.usebsv.com s'
    while True:
        try:
            blockchain = electrum_client_2.ElectrumClient(peer, coin=coin)
            await blockchain.init()
            break
        except OSError:
            peer = random.choice(coin.PEERS)
            continue

    min_fee = await blockchain.min_fee()
    primary_fee_per_kb = await blockchain.fee_per_kb(1000)
    global xfer_seconds
    xfer_seconds = block_seconds / mempool_depth

    curses.setupterm()
    tput = {
        cap : curses.tigetstr(cap).decode()
        for cap in ['sc', 'rc', 'cup', 'el']
    }
    #statline = curses.tparm(tput['cup'].encode(), 2, 2).decode()
    #statline2 = curses.tparm(tput['cup'].encode(), 3, 2).decode()

    total_fee = 0
    start_time = time.time()
    last_time = start_time

    def progress_msg(msg):
            sys.stderr.write(tput['sc'])# + statline)
            lines = msg.split('\n')
            for idx, line in enumerate(lines):
                sys.stderr.write(curses.tparm(tput['cup'].encode(), idx, 0).decode() + tput['el'])
                sys.stderr.write(line)
                blockchain.logger.info(line)
            sys.stderr.write(tput['rc'])
            sys.stderr.flush()
    
    async def progress(tx, fee, balance, status = ''):
        if balance < fee:
            addr = bitcoin.privkey2addr(privkey)
            buf = io.StringIO()
            segno.make(addr).terminal(buf, border=1)
            msg = buf.getvalue() + f'INSUFFICIENT FUNDS PLEASE SEND {-balance} SAT TO {addr}'
            progress_msg(msg)
        else:
            nonlocal total_fee, last_time
            total_fee += fee
            if fee > 0:
                last_time = time.time()
            if last_time != start_time:
                rate = int(total_fee * 60 * 60 * 24 / (last_time - start_time) + 0.5) / 100_000_000
            else:
                rate = '[no xfer yet]'
            if tx is not None and not status:
                status = tx.hash_hex
            msg = f'[[ FEE: {total_fee} sat ({rate} coin/day) ]]'
            if status:
                msg += '\n' + f'[[ {status} ]]'
            progress_msg(msg)
        #if balance >= fee and tx is not None:
        #    if not flush_lock.locked():
        #        await flush_lock.acquire()
    #await flush_lock.acquire()

    try:
        bcat, unspent = await bitcom.stream_up(filename, stream, privkey, blockchain, bcatinfo = info, buffer = False, progress = progress, fee_per_kb = fee_per_kb, primary_fee_per_kb = primary_fee_per_kb, max_mempool_chain_length = mempool_depth)

        print('flushing:', bcat.tx.hash_hex, flush=True)

        downpipe = await blockchain.watch_headers()
        while True:
            header = await downpipe.get()
            tx = await blockchain.tx(None, None, bcat.tx.hash_hex, None, verbose = True)
            if 'blockheight' in tx:
                depth = header.height + 1 - tx['blockheight']
                print(f'flush {depth}: {header.hash_hex}', flush=True)
                if depth >= 6:
                    break
            else:
                print(f'{header.hash_hex} did not resolve clog, waiting ..', flush=True)

        await blockchain.delete()
    except Exception as e:
        logging.getLogger().error(err2str(e))

#flush_lock = asyncio.Lock()
xfer_seconds = 600
def compress_data(in_fifo, out_fifo, eof_event, tee_file = None):
    compression_params = zstandard.ZstdCompressionParameters.from_level(22, write_checksum=True, enable_ldm=True)
    if tee_file is None:
        tee_file = '/dev/null'
    else:
        tee_file += '.zst'
    # open call below blocks until data available
    with open(in_fifo, 'rb') as uncompressed_stream, open(out_fifo, 'wb') as compressed_stream, open(tee_file, 'wb') as compressed_tee_stream:
        class Tee:
            def write(self, data):
                compressed_stream.write(data)
                compressed_tee_stream.write(data)
            def flush(self):
                compressed_stream.flush()
                compressed_tee_stream.flush()
        tee = Tee()
        zstd = zstandard.ZstdCompressor(compression_params = compression_params)
        last_time = time.time()
        try:
            with zstd.stream_writer(tee) as zstdsink:
                while True:
                    new_data = uncompressed_stream.read1(1024 * 1024 * 1024)
                    if len(new_data) > 0:
                        zstdsink.write(new_data)
                        now = time.time()
                        if now - last_time >= xfer_seconds:
                        #if flush_lock.locked():
                        #    flush_lock.release()
                            zstdsink.flush()
                            last_time = now
                    elif eof_event.is_set():
                        break
                    else:
                        time.sleep(0.2)
        except Exception as e:
            logging.getLogger().error(err2str(e))

def send_data(in_fifo, filename):
    with open(in_fifo, 'r') as compressed_stream:
        asyncio.run(stream_up(compressed_stream, filename + '.zst', 'asciinema.zst'))

 
def main():
    is_help = '--help' in sys.argv or '-h' in sys.argv
    if is_help:
        produce_data('/dev/null')
    else:
        if sys.argv[-1][0] != '-' and len(sys.argv) > 1:
            teefile = sys.argv.pop()
        else:
            teefile = None
        #logging.basicConfig(level = logging.WARN)
        #logging.basicConfig(level = logging.DEBUG)
        date = datetime.datetime.now().isoformat(timespec = 'seconds')
        if teefile is None:
            fn = date + '.cast'
        else:
            fn = os.path.basename(teefile)
        with temp_fifo(fn) as uncompressed_fifo, temp_fifo(fn) as compressed_fifo:
            eof_event = threading.Event()
            data_compressor = threading.Thread(target = compress_data, args=(uncompressed_fifo, compressed_fifo, eof_event, teefile))
            data_compressor.start()
            data_sender = threading.Thread(target = send_data, args=(compressed_fifo, fn))
            data_sender.start()

            # asciinema wants to be main thread
            generated_data = produce_data(uncompressed_fifo)

            eof_event.set()
            data_compressor.join()
            data_sender.join()

main()

