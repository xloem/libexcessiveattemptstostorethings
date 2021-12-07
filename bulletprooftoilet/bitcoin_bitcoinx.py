import bitcoinx

def Compose(cls):
    name = cls.__module__.split('.', 1)[0]
    class Compose:
        def __init__(self, impl : cls):
            setattr(self, name, impl)
    return Compose

class Tx(Compose(bitcoinx.Tx)):
    def __init__(self, src):
        if type(src) is bytes:
            src = bitcoinx.Tx(bytes)
        elif type(src) is str:
            src = bitcoinx.Tx.from_hex(hex)
        elif type(src) is Tx:
            src = src.bitcoinx
        super().__init__(src)
    @property
    def bytes(self):
        return self.bitcoinx.to_bytes()
    @property
    def hex(self):
        return self.bitcoinx.to_hex()
    @property
    def hash_hex(self):
        return self.bitcoinx.hex_hash()
    @staticmethod
    def from_bytes(bytes):
        return Tx(bitcoinx.Tx(bytes))
    @staticmethod
    def from_hex(hex):
        return Tx(bitcoinx.Tx.from_hex(hex))
    @property
    def inputs(self):
        return self.bitcoinx.inputs
    @property
    def outputs(self):
        return self.bitcoinx.outputs

class Output(Compose(bitcoinx.TxOutput)):
    @property
    def value(self):
        return self.bitcoinx.value

#class Input(Compose(bitcoinx.TxOutput)):
#    @property
#    def value(self):
#        return self.bitcoinx.value

class PrivateKey(Compose(bitcoinx.PrivateKey)):
    def __init__(self, src = None):
        if type(src) is str:
            src = bitcoinx.PrivateKey.from_hex(hex)
        elif type(src) is bytes:
            src = bitcoinx.PrivateKey(bytes)
        elif src is None:
            src = bitcoinx.PrivateKey.from_random()
        elif type(src) is PrivateKey:
            src = src.bitcoinx
        super().__init__(src)
    @property
    def addr_str(self):
        return self.bitcoinx.public_key.to_address().to_string()
    @property
    def pub(self):
        return PublicKey(self.bitcoinx.public_key)
    @staticmethod
    def from_hex(hex):
        return PrivateKey(bitcoinx.PrivateKey.from_hex(hex))
    @staticmethod
    def from_bytes(bytes):
        return PrivateKey(bitcoinx.PrivateKey(bytes))
    @staticmethod
    def from_random():
        return PrivateKey(bitcoinx.PrivateKey.from_random())

class PublicKey(Compose(bitcoinx.PublicKey)):
    @property
    def addr(self):
        return self.bitcoinx.to_address()
    @property
    def addr_str(self):
        return self.bitcoinx.to_address().to_string()
    @property
    def p2pkh(self):
        return self.bitcoinx.P2PKH_script()

def tx2outputs(tx):
    return tx.outputs

def output2value(output):
    return output.value
