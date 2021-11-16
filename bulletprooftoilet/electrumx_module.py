from .module import Module
from .blockchain_module import BlockchainModule
from .electrumx_client import ElectrumXClient

import electrumx

class ElectrumXModule(Module):
    _submodules = None
    async def submodules(self):
        if self._submodules is None:
            submodules = []
            for name, coin in electrumx.lib.coins.__dict__.items():
                if type(coin) is type and issubclass(coin, electrumx.lib.coins.Coin) and coin.PEERS:
                    coinmodule = self._make_submodule(coin)
                    yield coinmodule
                    submodules.append(coinmodule)
            self._submodules = submodules
        else:
           for coinmodule in self._submodules:
                yield coinmodule
    def _make_submodule(self, coin):
        module = BlockchainModule(ElectrumXClient(coin_name = coin.NAME, network = coin.NET))
        return module


