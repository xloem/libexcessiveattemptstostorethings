import math, struct

try:
    from .bitcoin_bit import *
except ModuleNotFoundError:
    raise

try:
    from .bitcoin_bitcoinx import *
except ModuleNotFoundError:
    raise

try:
    import pycoin
except ModuleNotFoundError:
    pass

hex2tx = Tx.from_hex

hex2privkey = PrivateKey.from_hex
privkey2addr = PrivateKey.addr_str.fget

class InsufficientFunds(OverflowError):
    def __init__(self, balance, needed):
        self.balance = balance
        self.needed = needed
        super().__init__(balance, needed)

class TooLongMempoolChain(OverflowError):
    def __init__(self, length = None):
        self.length = length
        super().__init__(length)

class InsufficientFee(OverflowError):
    def __init__(self, message):
        self.message = message
        super().__init__(message)

class MempoolConflict(OverflowError):
    def __init__(self, message = None):
        self.message = message
        super().__init__(message)

async def input2utxo(input, blockchain):
    txid = input.prev_hash
    txpos = input.prev_idx
    if txid == b'\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0' and txpos == 4294967295:
        amnt = 'block reward'
        script_pubkey = None # doesn't seem immediately needed, spending time elsewhere
    else:
        txid = txid[::-1].hex()
        tx = await blockchain.tx(None, None, txid, None)
        tx = hex2tx(tx)
        output = tx2outputs(tx)[txpos]
        amnt = output2value(output)
        script_pubkey = output.script_pubkey
    return params2utxo(amnt, txid, txpos, script_pubkey)

class Header:
    size = 80
    def __init__(self, raw, height):
        self.raw = raw
        self.height = height
    @staticmethod
    def fromfields(version, prev_hash_hex, merkle_root_hex, timestamp, bits, nonce, height):
        raw = struct.pack('<L32s32sLLL', version, bytes.fromhex(prev_hash_hex)[::-1], bytes.fromhex(merkle_root_hex)[::-1], timestamp, bits, nonce)
        return Header(raw, height)
    @staticmethod
    def fromhex(hex, height):
        return Header(bytes.fromhex(hex), height)
    @property
    def version(self):
        return struct.unpack('<L', self.raw[:4])[0]
    @property
    def prev_hash_raw(self):
        return struct.unpack('32s', self.raw[4:36])[0]
    @property
    def merkle_root_raw(self):
        return struct.unpack('32s', self.raw[36:68])[0]
    @property
    def timestamp(self):
        return struct.unpack('<L', self.raw[68:72])[0]
    @property
    def bits(self):
        return struct.unpack('<L', self.raw[72:76])[0]
    @property
    def nonce(self):
        return struct.unpack('<L', self.raw[76:80])[0]
    @property
    def hex(self):
        return self.raw.hex()
    @property
    def hash_raw(self):
        return bit.crypto.double_sha256(self.raw)
    @property
    def hash_hex(self):
        return self.hash_raw[::-1].hex()
    @property
    def prev_hash_hex(self):
        return self.prev_hash[::-1].hex()
    @property
    def merkle_root_hex(self):
        return self.merkle_root[::-1].hex()

#def send(privkey, unspents, min_fee, fee_per_kb, dest_addr, dest_sats, change_addr = None, forkid = False):
#    privkey = PrivateKey(privkey)
#    pubkey = privkey.pub
#    scriptpubkey = pubkey.p2pkh
#    if change_addr is None:
#        change_addr = pubkey.addr
#    elif not instanceof(change_addr, bitcoinx.Address):
#        change_addr = bitcoinx.P2PKH_Address.from_string(change_addr)
#    if not instanceof(dest_addr, bitcoinx.Address):
#        dest_addr = bitcoinx.P2PKH_Address.from_string(dest_addr)
#    inputs = []
#    value = 0
#    for unspent in unspents:
#        value += unspent.amount
#        inputs.append(bitcoinx.TxInput(bytes.fromhex(unspent.txid)[::-1], unspent.txindex, scriptpubkey, 0))
#    dest_output = bitcoinx.TxOutput(dest_sats, dest_addr.to_script())
#    fee_output = bitcoinx.TxOutput(value, change_addr.to_script())
#    dest_output_idx = 0
#    fee_output_idx = 1
#    outputs = [None, None]
#    outputs[dest_output_idx] = dest_output
#    outputs[fee_output_idx] = fee_output
#    tx = bitcoinx.Tx(1, inputs, outputs, 0)
    

def bumped_fee(privkey, tx, utxos, min_fee, fee_per_kb, change_addr):
    if type(privkey) is str:
        privkey = PrivateKey.from_hex(privkey)
    elif type(privkey) is bytes:
        privkey = PrivateKey.from_bytes(privkey)
    pubkey = privkey.pub
    if type(tx) is bytes:
        tx = Tx.from_bytes(tx)
    elif type(tx) is str:
        tx = Tx.from_hex(tx)
    else:
        tx = Tx.from_bytes(tx.bytes)

    if not instanceof(change_addr, bitcoinx.Address):
        change_addr = bitcoinx.P2PKH_Address.from_string(change_addr)
    change_script = change_addr.to_script()
    scriptpubkey = pubkey.p2pkh

    fee = math.ceil(max(min_fee, fee_per_kb * len(tx.bytes) / 1000))
    available = sum((utxo.amount for utxo in utxos))
    replaced_fee = available - sum((output.value for output in tx.bitcoinx.outputs))
    diff = replaced_fee - fee
    available = replaced_fee
    for output in tx.bitcoinx.outputs:
        if diff <= 0:
            break
        if output.script_pubkey == change_script:
            available += output.value
            if diff > output.value:
                output.value -= diff
                diff = 0
            else:
                diff -= output.value
                output.value = 0
    if diff > 0:
        raise InsufficientFunds(available, fee)

    pubkeybytes = pubkey.bitcoinx.to_bytes()
    for idx, (unspent, input) in enumerate(zip(utxos, tx.bitcoinx.inputs)):
        ops = [*input.script_sig.ops()]
        if len(ops) == 2 and ops[-1] == pubkeybytes:
            sighash = bitcoinx.SigHash.from_bytes(ops[0][-1])
            input.script_sig = bitcoinx.Script() << privkey.bitcoinx.sign(tx.signature_hash(idx, unspent.amount, scriptpubkey, sighash), None) + sighash.to_bytes(1, 'little') << pubkey.bitcoinx.to_bytes()

    return tx, fee, available - fee

def bytes_to_op_return_script(*items, add_null_prefix = True):
    script = bitcoinx.Script()
    if add_null_prefix:
        script = script << 0
    script = script << bitcoinx.OP_RETURN
    for item in items:
        if type(item) is not bytes:
            if type(item) is not str:
                item = str(item)
            item = bytes(item, 'utf-8')
        script = script << item
    return script


def op_return(privkey, unspents, min_fee, fee_per_kb, *items, extra_lists_of_items = [], change_addr = None, fee_output_idx = 1, forkid = False, add_null_prefix = True):
    privkey = PrivateKey(privkey)
    pubkey = privkey.pub
    if change_addr is None:
        change_addr = pubkey.addr
    elif not instanceof(change_addr, bitcoinx.Address):
        change_addr = bitcoinx.P2PKH_Address.from_string(change_addr)
    scriptpubkey = pubkey.p2pkh
    inputs = []
    value = 0
    for unspent in unspents:
        value += unspent.amount
        inputs.append(bitcoinx.TxInput(bytes.fromhex(unspent.txid)[::-1], unspent.txindex, scriptpubkey, 0))

    lists_of_items = [items, *extra_lists_of_items]
    outputs = []
    for items in lists_of_items:
        script = bytes_to_op_return_script(*items, add_null_prefix = add_null_prefix)
        outputs.append(bitcoinx.TxOutput(0, script))
    fee_output = bitcoinx.TxOutput(value, change_addr.to_script())
    outputs.insert(fee_output_idx, fee_output)
    tx = bitcoinx.Tx(1, inputs, outputs, 0)
    
    #fee = await blockchain.estimate_fee(len(tx.to_bytes()), 6, 0.25)#int(fee_per_kb * len(tx.to_bytes()) / 1024)


    sighash = bitcoinx.SigHash.ALL
    if forkid:
        sighash = bitcoinx.SigHash(sighash | bitcoinx.SigHash.FORKID)
    #sig = privkey.sign(tx.to_bytes() + sighash.to_bytes(4, 'little'), bitcoinx.double_sha256)
    #sig += sighash.to_bytes(1, 'little')
    #scriptsig = bitcoinx.Script() << sig << pubkey.to_bytes()

    while True:
        # note, bsv code seems to use 1000 for 1 kb
        fee = math.ceil(max(min_fee, fee_per_kb * len(tx.to_bytes()) / 1000))
        if fee <= value - fee_output.value:
            # estimate met reality
            break
        if fee > value:
            raise InsufficientFunds(fee_output.value, fee)
        fee_output.value = value - fee
        for idx, (unspent, input) in enumerate(zip(unspents, inputs)):
            #input.scriptsig = scriptsig
            input.script_sig = bitcoinx.Script() << privkey.bitcoinx.sign(tx.signature_hash(idx, unspent.amount, scriptpubkey, sighash), None) + sighash.to_bytes(1, 'little') << pubkey.bitcoinx.to_bytes()
    #sig = privkey.sign(tx.to_bytes() + sighash.to_bytes(4, 'little'), bitcoinx.double_sha256)

    return Tx(tx), params2utxo(amount = fee_output.value, txid = tx.hex_hash(), txindex = fee_output_idx, scriptpubkey = fee_output.script_pubkey, confirmations = 0), fee, fee_output.value
