import bit

def params2utxo(amount, txid, txindex, scriptpubkey = None, confirmations = None):
    return bit.network.meta.Unspent(amount, confirmations, scriptpubkey, txid, txindex)
