import bitcoinx
from collections import namedtuple
from dataclasses import dataclass, fields, MISSING
import asyncio, mimetypes, typing

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
        bitcoinx.PrivateKey.from_random(), 
        [bitcoin.params2utxo(100000000, bitcoinx.sha256(b'')[::-1].hex(), 0)],
        200, 200
    )[0].to_bytes())

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
        bitcoinx.PrivateKey.from_random(),
        [bitcoin.params2utxo(100000000, bitcoinx.sha256(b'')[::-1].hex(), 0)],
        200, 200
    )[0].to_bytes())

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

async def stream_up(filename, fileobj, privkey, blockchain, media_type = None, encoding = None, bcatinfo = '', bcatflag = '\0', buffer = True, forkid = True, progress = lambda tx, fee, balance: None, min_fee = None, fee_per_kb = None):

    if media_type is None:
        media_type, encoder = mimetypes.guess_type(filename)

    max_tx_size = await blockchain.max_transaction_size()
    max_B_datalen = max_tx_size - B.OVERHEAD_BYTES
    max_BCATPART_datalen = max_tx_size - BCATPART.OVERHEAD_BYTES

    utxos = await blockchain.addr_unspents(bitcoin.privkey2addr(privkey))
    if min_fee is None:
        min_fee = await blockchain.min_fee()
    if fee_per_kb is None:
        fee_per_kb = await blockchain.fee_per_kb(100_000)
    
    dataqueue = asyncio.Queue()
    from . import util
    import os
    flow_backed_up = False
    def on_data():
        try:
            data = fileobj.buffer.read1()
            dataqueue.put_nowait(data)
            flow_backed_up = False
        except asyncio.QueueFull:
            flow_backed_up = True
            # we'll want to call this again when the queue drains
    asyncio.get_event_loop().add_reader(fileobj, on_data)
    blockqueue = await blockchain.watch_headers()
    blockordata = util.Queues(blockqueue, dataqueue)

    txhashes = []
    
    data = b''
    while True:
        updates_by_queue = await blockordata.get()
        if dataqueue in updates_by_queue:
            data += updates_by_queue[dataqueue]
            if flow_backed_up:
                on_data()
        elif len(data) == 0:
            continue
        while len(data) < max_BCATPART_datalen and dataqueue.qsize() > 0:
            data += dataqueue.get_nowait()
        if buffer and blockqueue not in update_by_queue and len(data) < max_BCATPART_datalen:
            continue
        to_flush = data[:max_BCATPART_datalen]
        data = data[len(to_flush):]
        if len(to_flush) == 0 and len(data) == 0:
            break
        # now flush data
        # shred onto blockchain
        # later we can add features to shred even more here
        OBJ = BCATPART(to_flush)
        try:
            tx, unspent, fee, balance = OBJ.to_new_tx(privkey, utxos, min_fee, fee_per_kb, forkid = forkid)
            txid = await blockchain.broadcast(tx.to_bytes())
            progress(tx, fee, balance)
        except bitcoin.InsufficientFunds as insuf:
            progress(None, insuf.needed, insuf.balance - insuf.needed)
            data = data + to_flush
            to_flush = to_flush[:0]
            utxos = await blockchain.addr_unspents(bitcoin.privkey2addr(privkey))
            continue
        unspent.txid = txid
        utxos = [unspent]
        txhashes.append(bytes.fromhex(txid))#[::-1])
            # on bico.media, bcat txids are not byte-reversed !

    if len(txhashes) > 1:
        OBJ = BCAT(bcatinfo, media_type, encoding, filename, bcatflag, txhashes)
        while True:
            try:
                tx, unspent, fee, balance = OBJ.to_new_tx(privkey, utxos, min_fee, fee_per_kb, forkid = forkid)
                txid = await blockchain.broadcast(tx.to_bytes())
                progress(tx, fee, balance)
                break
            except bitcoin.InsufficientFunds as insuf:
                progress(None, insuf.needed, insuf.balance - insuf.needed)
                utxos = await blockchain.addr_unspents(bitcoin.privkey2addr(privkey))
                continue
        unspent.txid = txid
    elif len(txhashes) == 0:
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
