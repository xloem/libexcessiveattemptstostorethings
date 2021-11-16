import bitcoinx
from collections import namedtuple
from dataclasses import dataclass, fields

class bitcom:
    bitcom = None
    Op = namedtuple('Op', 'output_idx op_idx op item')
    def __init__(self, tx):
        if type(tx) is str:
            tx = bitcoinx.Tx.from_hex(tx)
        self.tx = tx
        self.ops = []
        for output_idx, output in enumerate(self.tx.outputs):
            for op_idx, (op, item) in enumerate(output.ops_and_items()):
                self.ops.append(bitcom.Op(output_idx, op_idx, op, item))
        self.offset = 1
        if not self.validate():
            raise TypeError(tx.to_hex())
        for idx, field in self.fields():
            setattr(self, field.name, field.type(self.ops[self.offset + idx].item))
    def __getitem__(self, idx):
        return self.ops[self.offset + len(self.fields()) + idx].item
    def validate(self):
        return self.ops[self.offset].op == 34 and self.__class__.bitcom in (None, self.bitcom)

@dataclass
class B(bitcom):
    bitcom : str = '19HxigV4QyBv3tHpQVcUEQyq1pzZVdoAut'  # https://b.bitdb.network/
    data : bytes
    media_type : str
    encoding : str
    filename : str

@dataclass
class BCAT(bitcom):
    bitcom : str = '15DHFxWZJT58f9nhyGnsRBqrgwK4W6h4Up'  # https://bcat.bico.media/
    info : str
    mime : str
    charset : str
    name : str
    flag : str

@dataclass
class BCATPART(bitcom):
    bitcom : str = '1ChDHzdd1H4wSjgGMHyndZm6qxEDGjqpJL'  # https://bcat.bico.media/ (raw data only after prefix)
    data : bytes

class D(bitcom):
    bitcom : str = '19iG3WTYSsbyos3uJ733yK4zEioi1FesNU'  # Dynamic - ownership over state of address
    key : str
    value : str
    type : str
    sequence : int

class AIP(bitcom):
    bitcom : str = '15PciHG22SNLQJXMoSUaWVi7WSqc7hCfva'  # https://github.com/BitcoinFiles/AUTHOR_IDENTITY_PROTOCOL

class MAP(bitcom):
    bitcom : str = '1PuQa7K62MiKCtssSLKy1kh56WWU7MtUR5'  # MAP protocol.
