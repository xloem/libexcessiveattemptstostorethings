from .module import Module

import collections, datetime, logging, struct

import bitcoinx

# this might be even more organised if a Module introspected a class for functions that returned types

class BMBase(Module):
    def __init__(self, impl):
        self.blockchain = impl
        super().__init__()

class BlockchainModule(BMBase):
    def __init__(self, impl):
        super().__init__(impl)
        self.blocks = BlockchainBlocksModule(self.blockchain)
        self._init = False
    async def init(self):
        await self.blockchain.init()
        self._init = True
    async def delete(self):
        await self.blockchain.delete()
        self._init = False
    async def name(self):
        return self.blockchain.name
    async def submodules(self):
        if not self._init:
            await self.init()
        return [self.blocks]

class BlockchainBlocksModule(BMBase):
    blocks = None
    async def submodules(self):
        if self.blocks is None:
            self.blocks = []
        height = await self.blockchain.height()
        assert height > 0
        while height >= len(self.blocks):
            block = BlockchainBlockModule(self.blockchain, len(self.blocks))
            self.blocks.append(block)
        return self.blocks
    async def name(self):
        return 'blocks'

#BlockHeader = collections.namedtuple('BlockHeader', 'version prevhash merkleroot time nBits nonce')

class Block:
    def __init__(self, height, blockchain):
        self._height = height
        self._blockchain = blockchain
        self._header = None
        #self._hash = None
        self._txids = None
        self.logger = blockchain.logger
        #self._have_last_txid = False
    @property
    def height(self):
        return self._height
    async def header(self):
        if self._header is None:
            self.logger.info(f'Caching blockheader @{self._height} ...')
            self._header = await self._blockchain.header(self._height)
            #version, prevhash, merkleroot, time, nBits, nonce = struct.unpack('<L32s32sLLL', header)
            #prevhash = prevhash[::-1].hex()
            #merkleroot = merkleroot.hex()
            #time = datetime.datetime.fromtimestamp(time)
            # [::-1] reverses the bytes
            #self._hash = bitcoinx.double_sha256(header)[::-1].hex()
            #hash = bitcoinx.double_sha256(header)[::-1].hex()
            #self._header = BlockHeader(version, prevhash, merkleroot, time, nBits, nonce)
        return self._header
    async def hash(self):
        return (await self.header()).hash
    async def txids(self):
        if self._txids is None:
            self.logger.info(f'Caching txids @{self._height} ...')
            txids = []
            async for txid in self._blockchain.txids(self._height):
                txids.append(txid)
                yield txid
            self._txids = txids
        else:
            for txid in self._txids:
                yield txid
        
class BlockchainBlockModule(BMBase):
    def __init__(self, impl, height):
        super().__init__(impl)
        self._height = height
        self._block = None
    @property
    def block(self):
        if self._block is None:
            self._block = Block(self.height, self.blockchain)
        return self._block
    @property
    def height(self):
        return self._height
    async def name(self):
        return await self.block.hash()
    async def items(self):
        pos = 0
        header = await self.block.header()
        timestamp = header.timestamp
        time = datetime.datetime.fromtimestamp(timestamp)
        async for txid in self.block.txids():
            yield Module.Item(txid, time, (txid, pos))
            pos += 1
    async def data(self, txidpos):
        txid, pos = txidpos
        hex = await self.blockchain.tx(await self.block.hash(), self.height, txid, pos)
        return bytes.fromhex(hex)
