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
