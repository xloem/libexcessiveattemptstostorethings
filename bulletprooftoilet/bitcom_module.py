from .module import Module
import bitcom

class B:
    def __init__(self, blockchain, txid):
        self.blockchain = blockchain
        self.txid = txid
        self._B = None
    async def name(self):
        await self.data()
        return self._B.filename
    async def data(self):
        if self._B is None:
            self._B = bitcom.B(await self.blockchain.tx(None, None, txid, None))
        return self._B.data

class BitcomModule(Module):
    def __init__(self, bitcom, blockchain):
        self.bitcom = bitcom
        self.blockchain = blockchain
