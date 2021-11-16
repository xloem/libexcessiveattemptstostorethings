import asyncio

from bulletprooftoilet import electrumx_client, blockchain_module

blockchainmodule = blockchain_module.BlockchainModule(electrumx_client.ElectrumXClient())

async def main():
    bm0 = await blockchainmodule.submodules()
    bm1 = await bm0[0].submodules();
    print([txid async for txid in bm1[0].items()])
    tx = await bm0[0].blockchain.peermanager.tx('a3907e5b910f798c8d0fb450d483a0aefa5ce40ac74064b377603e5ea51deccb')
    from bulletprooftoilet import bitcom
    print(bitcom.BCAT(tx))

asyncio.run(main())
