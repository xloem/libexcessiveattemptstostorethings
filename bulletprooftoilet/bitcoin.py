import struct

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

def op_return(privkey, unspents, min_fee, fee_per_kb, *items, change_addr = None, forkid = False):
    if type(privkey) is not bitcoinx.PrivateKey:
        privkey = bitcoinx.PrivateKey(privkey)
    pubkey = privkey.public_key
    if change_addr is None:
        change_addr = pubkey.to_address()
    elif not instanceof(change_addr, bitcoinx.Address):
        change_addr = bitcoinx.P2PKH_Address.from_string(change_addr)
    scriptpubkey = pubkey.P2PKH_script()
    inputs = []
    value = 0
    for unspent in unspents:
        value += unspent.amount
        inputs.append(bitcoinx.TxInput(bytes.fromhex(unspent.txid)[::-1], unspent.txindex, scriptpubkey, 0))

    script = bitcoinx.Script() << 0 << bitcoinx.OP_RETURN
    for item in items:
        if type(item) is not bytes:
            if type(item) is not str:
                item = str(item)
            item = bytes(item, 'utf-8')
        script = script << item
    data_output = bitcoinx.TxOutput(0, script)
    fee_output = bitcoinx.TxOutput(value, change_addr.to_script())
    tx = bitcoinx.Tx(1, inputs, [data_output, fee_output], 0)
    #fee = await blockchain.estimate_fee(len(tx.to_bytes()), 6, 0.25)#int(fee_per_kb * len(tx.to_bytes()) / 1024)
    fee = int(max(min_fee, fee_per_kb * len(tx.to_bytes()) / 1024) + 0.5)
    print('FEE:', fee)
    fee_output.value -= fee

    sighash = bitcoinx.SigHash.ALL
    if forkid:
        sighash = bitcoinx.SigHash(sighash | bitcoinx.SigHash.FORKID)
    #sig = privkey.sign(tx.to_bytes() + sighash.to_bytes(4, 'little'), bitcoinx.double_sha256)
    #sig += sighash.to_bytes(1, 'little')
    #scriptsig = bitcoinx.Script() << sig << pubkey.to_bytes()
    for idx, (unspent, input) in enumerate(zip(unspents, inputs)):
        #input.scriptsig = scriptsig
        input.script_sig = bitcoinx.Script() << privkey.sign(tx.signature_hash(idx, unspent.amount, scriptpubkey, sighash), None) + sighash.to_bytes(1, 'little') << pubkey.to_bytes()
    #sig = privkey.sign(tx.to_bytes() + sighash.to_bytes(4, 'little'), bitcoinx.double_sha256)

    return tx
