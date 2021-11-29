import bitcoinx
from collections import namedtuple
from dataclasses import dataclass, fields, MISSING
import typing

convert_bytes_to = {
    str: lambda bytes: bytes.decode(),
    int: int,
    bytes: bytes,
}

convert_to_bytes = {
    str: lambda str: str.encode(),
    int: lambda int: str(int).encode(),
    bytes: bytes
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
                params.append([convert_bytes_to[item_type](item) for item in ops[offset + idx:]])
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
            value = getttr(self, field.name)
            if typing.get_origin(field.type) is list and idx + 1 == len(cls_fields):
                item_type, = typing.get_args(field.type)
                result.extend([convert_to_bytes[item_type](item) for item in value])
            else:
                result.append(convert_to_bytes[field.type](value))
        return result
    def to_new_tx(self, privkey, unspents, min_fee, fee_per_kb, change_addr = None, forkid = True):
        from . import bitcoin
        pushdata = self.to_pushdata_list()
        return bitcoin.op_return(privkey, unspents, min_fee, fee_per_kb, *pushdata, change_addr, forkid)

@dataclass
class B(bitcom):
    bitcom = '19HxigV4QyBv3tHpQVcUEQyq1pzZVdoAut'  # https://b.bitdb.network/
    data : bytes
    media_type : str
    encoding : str = None
    filename : str = None

@dataclass
class BCAT(bitcom):
    bitcom = '15DHFxWZJT58f9nhyGnsRBqrgwK4W6h4Up'  # https://bcat.bico.media/
    info : str
    mime : str
    charset : str
    name : str
    flag : str
    parts : typing.List[bytes]

#class AutoBCAT(BCAT):
#    def __init__(self, 

@dataclass
class BCATPART(bitcom):
    bitcom = '1ChDHzdd1H4wSjgGMHyndZm6qxEDGjqpJL'  # https://bcat.bico.media/ (raw data only after prefix)
    data : bytes

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
