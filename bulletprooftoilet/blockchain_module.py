from .module import Module

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
        while height >= len(self.blocks):
            block = BlockchainBlockModule(self.blockchain, len(self.blocks))
            self.blocks.append(block)
        return self.blocks
    async def name(self):
        return 'blocks'
        
class BlockchainBlockModule(BMBase):
    def __init__(self, impl, height):
        super().__init__(impl)
        self.height = height
    @property
    def block(self):
        return self.blockchain.block(self.height)
    async def name(self):
        return await self.block.hash()
    async def items(self):
        pos = 0
        async for txid in self.blockchain.txids(self.height):
            yield Module.Item(txid, (await self.block.header()).time, (txid, pos))
            pos += 1
    async def data(self, txidpos):
        txid, pos = txidpos
        hex = await self.blockchain.tx(await self.block.hash(), self.height, txid, pos)
        return bytes.fromhex(hex)
