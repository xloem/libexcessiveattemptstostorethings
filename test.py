import asyncio

from bulletprooftoilet import electrumx_client, blockchain_module, bitcom

blockchainmodule = blockchain_module.BlockchainModule(electrumx_client.ElectrumXClient())

async def main():
    bm0 = await blockchainmodule.submodules()
    bm1 = await bm0[0].submodules();
    BJPG_TXID = 'a3907e5b910f798c8d0fb450d483a0aefa5ce40ac74064b377603e5ea51deccb'
    print('block 0 txids:', [txid async for txid in bm1[0].items()])
    print('downloading a jpeg image from transaction ' + BJPG_TXID)
    tx = await blockchainmodule.blockchain.peermanager.tx(BJPG_TXID)
    BJPG = bitcom.B.from_tx(tx)
    with open(f'{BJPG_TXID}.jpg', 'wb') as jpgout:
        jpgout.write(BJPG.data)
        print(f'wrote {BJPG.media_type} to {BJPG_TXID}.jpg')

asyncio.run(main())
