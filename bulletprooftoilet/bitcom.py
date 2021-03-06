import bitcoinx
from collections import namedtuple
from dataclasses import dataclass, fields, MISSING
import asyncio, mimetypes, time, typing

from . import bitcoin

convert_bytes_to = {
    str: lambda bytes: bytes.decode(),
    int: int,
    bytes: bytes,
}

convert_to_bytes = {
    str: lambda str: '\0' if str is None else str.encode(),
    int: lambda int: '\0' if int is None else str(int).encode(),
    bytes: '\0' if bytes is None else bytes
}

class bitcom:
    bitcom = None
    Op = namedtuple('Op', 'output_idx op_idx op item')
    @classmethod
    def from_tx(cls, tx):
        if type(tx) is str:
            tx = bitcoinx.Tx.from_hex(tx)
        ops = []
        for output_idx, output in enumerate(tx.outputs):
            script = output.script_pubkey
            found_data = False
            for op_idx, ((op, item), opitem) in enumerate(zip(script.ops_and_items(), script.ops())):
                if not found_data:
                    if op == bitcoinx.script.OP_RETURN:
                        found_data = True
                    continue
                ops.append(bitcom.Op(output_idx, op_idx, op, item or opitem))
        offset = 1
        bitcom_value = convert_bytes_to[str](ops[0].item)
        if cls.bitcom not in (None, bitcom_value):
            raise TypeError(bitcom_value)
        params = []
        cls_fields = list(fields(cls))
        for idx, field in enumerate(cls_fields):
            if field.default is not MISSING and offset + idx >= len(ops):
                break
            if typing.get_origin(field.type) is list and idx + 1 == len(cls_fields):
                item_type, = typing.get_args(field.type)
                params.append([convert_bytes_to[item_type](item.item) for item in ops[offset + idx:]])
            else:
                params.append(convert_bytes_to[field.type](ops[offset + idx].item))
        result = cls(*params)
        result.bitcom = bitcom_value
        result.tx = tx
        return result
    def to_pushdata_list(self):
        cls_fields = list(fields(self))
        result = []
        result.append(convert_to_bytes[str](self.bitcom))
        for idx, field in enumerate(cls_fields):
            value = getattr(self, field.name)
            if typing.get_origin(field.type) is list and idx + 1 == len(cls_fields):
                item_type, = typing.get_args(field.type)
                for item in value:
                    if callable(item):
                        item = item(self)
                    result.append(convert_to_bytes[item_type](item))
            else:
                if callable(value):
                    value = value(self)
                result.append(convert_to_bytes[field.type](value))
        return result
    def to_new_tx(self, privkey, unspents, min_fee, fee_per_kb, change_addr = None, forkid = True):
        from . import bitcoin
        pushdata = self.to_pushdata_list()
        tx, unspent, fee, remaining = bitcoin.op_return(privkey, unspents, min_fee, fee_per_kb, *pushdata, change_addr = change_addr, forkid = forkid)
        return tx, unspent, fee, remaining

@dataclass
class B(bitcom):
    bitcom = '19HxigV4QyBv3tHpQVcUEQyq1pzZVdoAut'  # https://b.bitdb.network/
    data : bytes
    media_type : str
    encoding : str = None
    filename : str = None

B.OVERHEAD_BYTES = len(
    B(b'', '').to_new_tx(
        bitcoin.PrivateKey.from_random(),
        [bitcoin.params2utxo(100000000, bitcoinx.sha256(b'')[::-1].hex(), 0)],
        200, 200
    )[0].bytes)

@dataclass
class BCAT(bitcom):
    bitcom = '15DHFxWZJT58f9nhyGnsRBqrgwK4W6h4Up'  # https://bcat.bico.media/
    info : str
    mime : str
    charset : str
    name : str
    flag : str
    parts : typing.List[bytes]
        
@dataclass
class BCATPART(bitcom):
    bitcom = '1ChDHzdd1H4wSjgGMHyndZm6qxEDGjqpJL'  # https://bcat.bico.media/ (raw data only after prefix)
    data : bytes

BCATPART.OVERHEAD_BYTES = len(
    BCATPART(b'').to_new_tx(
        bitcoin.PrivateKey.from_random(),
        [bitcoin.params2utxo(100000000, bitcoinx.sha256(b'')[::-1].hex(), 0)],
        200, 200
    )[0].bytes)

#async def autodata(filename, data, max_tx_size, media_type = None, encoding = None, bcatinfo = '', bcatflag = '\0'):
#    max_B_datalen = max_tx_size - B.OVERHEAD_BYTES
#    if len(data) <= max_B_datalen:
#        yield B(data, media_type, encoding, name)
#    else:
#        txs = []
#        for chunk_start in range(0, len(data), max_BCAT_datalen):
#            tx = BCATPART(data[chunk_start:chunk_start + max_BCAT_datalen])
#            yield tx
#            txs.append(tx)
#        tx = BCAT(bcatinfo, media_type, encoding, filename, bcatflag, *[tx.hash() for tx in txs])
#        yield tx

#    def to_new_tx(self, privkey, unspents, min_fee, fee_per_kb, change_addr = None, forkid = True):

async def default_progress(tx, fee, balance, status):
    pass

async def stream_up(filename, fileobj, privkey, blockchain, media_type = None, encoding = None, bcatinfo = '', bcatflag = '\0', buffer = True, forkid = True, progress = default_progress, min_fee = None, fee_per_kb = None, max_mempool_chain_length = 10000, block_seconds = 600, buffer_min_fee_txs = True, primary_min_fee = None, primary_fee_per_kb = None):

    last_block_time = (await blockchain.header(await blockchain.height())).timestamp

    if media_type is None:
        media_type, encoder = mimetypes.guess_type(filename)

    max_tx_size = await blockchain.max_transaction_size()
    max_B_datalen = max_tx_size - B.OVERHEAD_BYTES
    max_BCATPART_datalen = max_tx_size - BCATPART.OVERHEAD_BYTES

    addr = bitcoin.privkey2addr(privkey)
    utxos = await blockchain.addr_unspents(addr)
    if min_fee is None:
        min_fee = await blockchain.min_fee()
    min_fee = int(min_fee + 0.5)
    if fee_per_kb is None:
        fee_per_kb = await blockchain.fee_per_kb(100_000)
    secondary_min_fee = min_fee
    secondary_fee_per_kb = fee_per_kb
    if primary_min_fee is None:
        primary_min_fee = min_fee
    if primary_fee_per_kb is None:
        primary_fee_per_kb = fee_per_kb
    
    dataqueue = asyncio.Queue()
    from . import util
    import os
    flow_backed_up = False
    stream_open = True
    accumulated_mempool_length = len(await blockchain.addr_mempool(addr))
    def on_data():
        try:
            data = fileobj.buffer.read1()
            flow_backed_up = False
            dataqueue.put_nowait(data)
        except asyncio.QueueFull:
            flow_backed_up = True
            # we'll want to call this again when the queue drains
    asyncio.get_event_loop().add_reader(fileobj, on_data)
    blockqueue = await blockchain.watch_headers()
    blockordata = util.Queues(blockqueue, dataqueue)

    txhashes = []
    balance = 0 # for progress messages. be better to initialise this
    
    data = b''
    while True:
        updates_by_queue = await blockordata.get()
        current_time = time.time()
        if blockqueue in updates_by_queue:
            blockchain.logger.debug('block update')
            accumulated_mempool_length = len(await blockchain.addr_mempool(addr))
            if accumulated_mempool_length > 0:
                blockchain.logger.warn(f'{accumulated_mempool_length} txs were not confirmed')
            block_seconds = (block_seconds + (current_time - last_block_time)) / 2
            last_block_time = current_time
            min_fee = secondary_min_fee
            fee_per_kb = secondary_fee_per_kb
        if dataqueue in updates_by_queue:
            new_data = updates_by_queue[dataqueue]
            if len(new_data) > 0:
                blockchain.logger.debug('data update')
                data += new_data
            else:
                stream_open = False
            if flow_backed_up:
                on_data()
        elif len(data) == 0:
            continue
        while len(data) < max_BCATPART_datalen and dataqueue.qsize() > 0:
            data += dataqueue.get_nowait()
        if buffer and blockqueue not in update_by_queue and len(data) < max_BCATPART_datalen:
            continue
        if stream_open:
            expected_mempool_length = max_mempool_chain_length * (current_time - last_block_time) / block_seconds #/ 1.5
            blockchain.logger.debug(f'expected_mempool_length after {int(current_time - last_block_time)}s * {max_mempool_chain_length} / {block_seconds}s / 1.5 = {int(expected_mempool_length)}; accumulated = {accumulated_mempool_length}')
        else:
            expected_mempool_length = max_mempool_chain_length
        if expected_mempool_length < accumulated_mempool_length and stream_open:
            blockchain.logger.debug('waiting for mempool to drain')
            await progress(None, 0, balance, f'mempool filling. delaying to spread writes')
            continue
        to_flush = data[:max_BCATPART_datalen]
        data = data[len(to_flush):]
        if len(to_flush) == 0 and len(data) == 0 and not stream_open:
            blockchain.logger.debug('stream closed')
            break
        # now flush data
        # shred onto blockchain
        # later we can add features to shred even more here
        OBJ = BCATPART(to_flush)
        try:
            if accumulated_mempool_length >= max_mempool_chain_length:
                tx, unspent, fee, balance = OBJ.to_new_tx(privkey, utxos, primary_min_fee, primary_fee_per_kb, forkid = forkid)
            else:
                tx, unspent, fee, balance = OBJ.to_new_tx(privkey, utxos, min_fee, fee_per_kb, forkid = forkid)
            if fee_per_kb > 0 and fee == min_fee and buffer_min_fee_txs and stream_open:
                data = to_flush + data
                to_flush = to_flush[:0]
                blockchain.logger.debug(f'rebuffering until byte cost exceeds min fee of {min_fee}')
                continue
            tx_bytes = tx.bytes
            blockchain.logger.debug(f'broadcasting tx with fee of {fee} and size of {len(tx_bytes)}; {fee_per_kb}*{len(tx_bytes)/1000}={fee_per_kb*len(tx_bytes)//1000} overhead={len(tx_bytes)-len(to_flush)}')
            txid = await blockchain.broadcast(tx_bytes)
            accumulated_mempool_length += 1
            last_tx = tx_bytes
            await progress(tx, fee, balance, f'broadcast {txid}')
        except bitcoin.InsufficientFunds as insuf:
            await progress(None, insuf.needed, insuf.balance - insuf.needed, f'insufficient funds.  waiting on deposit')
            data = to_flush + data
            to_flush = to_flush[:0]
            blockchain.logger.debug('checking balance again')
            utxos = await blockchain.addr_unspents(addr)
            continue
        except bitcoin.InsufficientFee:
            if min_fee < primary_min_fee or fee_per_kb < primary_fee_per_kb:
                await progress(None, 0, balance, f'provided fee not sufficient, using primary fee')
                min_fee = primary_min_fee
                fee_per_kb = primary_fee_per_kb
                data = to_flush + data
                to_flush = to_flush[:0]
                continue
            raise
        except bitcoin.TooLongMempoolChain:
            await progress(None, 0, balance, f'mempool full. waiting for next block')
            max_mempool_chain_length = len(await blockchain.addr_mempool(addr))

            data = to_flush + data
            to_flush = to_flush[:0]
            blockchain.logger.debug('node mempool length reached')
            min_fee = primary_min_fee
            fee_per_kb = primary_fee_per_kb


            # tx, fee, balance = bitcoin.bumped_fee(privkey, tx, last_utxos, primary_min_fee, primary_fee_per_kb, privkey.pub.addr_str)
            # tx = tx.bytes
            # blockchain.logger.debug(f'broadcasting tx with fee of {fee} and size of {len(tx)}; {fee_per_kb}*{len(tx)/1000}={fee_per_kb*len(tx)//1000} overhead={len(tx)-len(to_flush)}')
            # txid = await blockchain.broadcast(tx)
            # await progress(tx, fee, balance, f'bump fee {txid}')
            continue
        except bitcoin.MempoolConflict:
            await progress(None, 0, balance, f'double spend encountered, recollecting utxos, private key must be doubly used, data might be lost')
            utxos = await blockchain.addr_unspents(addr)
            data = to_flush + data
            to_flush = to_flush[:0]
            continue
        unspent.txid = txid
        last_utxos = utxos
        utxos = [unspent]
        txhashes.append(bytes.fromhex(txid))#[::-1])
            # on bico.media, bcat txids are not byte-reversed !

    # flush
    if len(txhashes) > 1:
        OBJ = BCAT(bcatinfo, media_type, encoding, filename, bcatflag, txhashes)
        while True:
            try:
                blockchain.logger.debug('try flush')
                tx, unspent, fee, balance = OBJ.to_new_tx(privkey, utxos, min_fee, fee_per_kb, forkid = forkid)
                txid = await blockchain.broadcast(tx.bytes)
                await progress(tx, fee, balance, f'flush {txid}')
                break
            except bitcoin.InsufficientFunds as insuf:
                await progress(None, insuf.needed, insuf.balance - insuf.needed, 'insufficient funds. waiting for deposit')
                time.sleep(1)
                utxos = await blockchain.addr_unspents(addr)
                continue
            except bitcoin.TooLongMempoolChain:
                if min_fee < primary_min_fee or fee_per_kb < primary_fee_per_kb:
                    min_fee = primary_min_fee
                    fee_per_kb = primary_fee_per_kb
                else:
                    blockchain.logger.warn(f'Waiting for mempool to clear, size = {len(await blockchain.addr_mempool(addr))}')
                    await progress(None, 0, balance, 'mempool full, waiting for block')
                    await blockqueue.get()
                continue
        blockchain.logger.debug('flushed')
        unspent.txid = txid
    elif len(txhashes) == 0:
        blockchain.logger.debug('nothing to flush')
        return None, utxos[0]
    OBJ.tx = tx
    return OBJ, unspent
    

## fileobj can be an io.BytesIO to wrap normal data
#def stream_up(filename, fileobj, privkey, blockchain, media_type = None, encoding = None, bcatinfo = '', bcatflag = '\0'):
#    max_tx_size = await blockchain.max_transaction_size()
#    max_B_datalen = max_tx_size - B.OVERHEAD_BYTES
#    max_BCAT_datalen = max_tx_size - BCATPART.OVERHEAD_BYTES
#    data = fileobj.read(max_BCAT_datalen)
#    if len(data) <= max_B_datalen:
#        yield B(data, media_type, encoding, name)
#    else:
#        txhashes = []
#        while True:
#            tx = BCATPART(data)
#            yield tx
#            txhashes.append(tx.hash())
#            if len(data) < max_BCAT_datalen:
#                break
#            data = fileobj.read(max_BCAT_datalen)
#        yield finalisebcat(filename, txhashes, media_type, encoding, bcatinfo, bcatflag)
#
#def bcat_from_txhashes(filename, txhashes, media_type = None, encoding = None, bcatinfo = '', bcatflag = '\0'):
##    if callable(filename):
##        filename = filename(txhashes)
#    return BCAT(bcatinfo, media_type, encoding, filename, bcatflag, *txhashes)

class D(bitcom):
    bitcom = '19iG3WTYSsbyos3uJ733yK4zEioi1FesNU'  # Dynamic - ownership over state of address
    key : str
    value : str
    type : str
    sequence : int

class AIP(bitcom):
    bitcom = '15PciHG22SNLQJXMoSUaWVi7WSqc7hCfva'  # https://github.com/BitcoinFiles/AUTHOR_IDENTITY_PROTOCOL

class MAP(bitcom):
    bitcom = '1PuQa7K62MiKCtssSLKy1kh56WWU7MtUR5'  # MAP protocol.
