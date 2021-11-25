import asyncio 

import bitcoinx

from bulletprooftoilet import electrum_client, electrumx_client, blockchain_module, bitcom

#blockchainmodule = blockchain_module.BlockchainModule(electrumx_client.ElectrumXClient())
#import electrum

# note: this private key is not private
privkey = bitcoinx.PrivateKey.from_hex('088412ca112561ff5db3db83e2756fe447d36ba3c556e158c8f016a2934f7279')

async def opreturn(privkey, blockchain, *items, forkid = False):
    if type(privkey) is not bitcoinx.PrivateKey:
        privkey = bitcoinx.PrivateKey(privkey)
    pubkey = privkey.public_key
    scriptpubkey = pubkey.P2PKH_script()
    inputs = []
    value = 0
    utxos = await blockchain.addr_utxos(pubkey.to_address().to_string())
    for utxo in utxos:
        value += utxo['value']
        inputs.append(bitcoinx.TxInput(bytes.fromhex(utxo['tx_hash'])[::-1], utxo['tx_pos'], scriptpubkey, 0))

    script = bitcoinx.Script() << 0 << bitcoinx.OP_RETURN
    for item in items:
        if type(item) is not bytes:
            if type(item) is not str:
                item = str(item)
            item = bytes(item, 'utf-8')
        script = script << item
    data_output = bitcoinx.TxOutput(0, script)
    fee_output = bitcoinx.TxOutput(value, pubkey.P2PKH_script())
    tx = bitcoinx.Tx(1, inputs, [data_output, fee_output], 0)
    fee = await blockchain.estimate_fee(len(tx.to_bytes()), 6, 0.25)#int(fee_per_kb * len(tx.to_bytes()) / 1024)
    print('FEE:', fee)
    fee_output.value -= fee

    sighash = bitcoinx.SigHash.ALL
    if forkid:
        sighash = bitcoinx.SigHash(sighash | bitcoinx.SigHash.FORKID)
    #sig = privkey.sign(tx.to_bytes() + sighash.to_bytes(4, 'little'), bitcoinx.double_sha256)
    #sig += sighash.to_bytes(1, 'little')
    #scriptsig = bitcoinx.Script() << sig << pubkey.to_bytes()
    for idx, (utxo, input) in enumerate(zip(utxos, inputs)):
        #input.scriptsig = scriptsig
        input.script_sig = bitcoinx.Script() << privkey.sign(tx.signature_hash(idx, utxo['value'], scriptpubkey, sighash), None) + sighash.to_bytes(1, 'little') << pubkey.to_bytes()
    #sig = privkey.sign(tx.to_bytes() + sighash.to_bytes(4, 'little'), bitcoinx.double_sha256)

    return tx

async def main():
    #blockchainmodule = blockchain_module.BlockchainModule(electrum_client.Electrum(electrum))
    #blockchainmodule = blockchain_module.BlockchainModule(electrum_client.ElectrumSV())
    blockchainmodule = blockchain_module.BlockchainModule(electrumx_client.ElectrumX())
    bm0 = await blockchainmodule.submodules()
    bm1 = await bm0[0].submodules();
    BJPG_TXID = 'a3907e5b910f798c8d0fb450d483a0aefa5ce40ac74064b377603e5ea51deccb'
    print('block 0 txids:', [txid async for txid in bm1[0].items()])
    example_height = 100002
    print(f'block {example_height} txids:', [txid async for txid in bm1[example_height].items()])
    print('downloading a jpeg image from transaction ' + BJPG_TXID)
    tx = await blockchainmodule.blockchain.tx(None, None, BJPG_TXID, None)
    BJPG = bitcom.B.from_tx(tx)
    with open(f'{BJPG_TXID}.jpg', 'wb') as jpgout:
        jpgout.write(BJPG.data)
        print(f'wrote {BJPG.media_type} to {BJPG_TXID}.jpg')

    #utxos = await blockchainmodule.blockchain.addr_utxos(privkey.public_key.to_address().to_string())
    #print('utxos', utxos)
    #fee_per_kb = await blockchainmodule.blockchain.estimate_fee_per_kb(6, 0.25)
    #print('fee per kb:', fee_per_kb)
    tx = await opreturn(privkey, blockchainmodule.blockchain, 'hello', 'world', forkid = True)#utxos, fee_per_kb, 'hello', 'world')
    print('sending tx:', tx.hex_hash())
    txid = await blockchainmodule.blockchain.broadcast(tx.to_bytes())
    print('sent', txid)

    #print('staying live for 30 minutes to see if some library outputs something')
    #await asyncio.sleep(30*60)

asyncio.run(main())
