from collections import namedtuple
from typing import List, Any, Iterable

class Module:
    Item = namedtuple('Item', 'name time id')
    async def name(self):
        name = self.__class__.__name__
        if name.endswith('Module'):
            return name[:-len('Module')]
        else:
            return name
    async def submodules(self) -> Iterable['Module']:
        return []
    async def items(self) -> Iterable[Item]:
        return []
    async def data(self, id) -> Iterable[bytes]:
        raise KeyError(id)
