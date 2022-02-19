#!/usr/bin/env python3

import asyncio, logging, random, sys

from bulletprooftoilet import pycoinnet_019
from bulletprooftoilet import electrum_client_2
from bulletprooftoilet import electrum_client
from bulletprooftoilet import electrumx_client
from bulletprooftoilet import blockchain_module
from bulletprooftoilet import bitcoin
from bulletprooftoilet import bitcom
from bulletprooftoilet import util
#from bulletprooftoilet import electrum_client_2, electrum_client, electrumx_client, blockchain_module, bitcoin, bitcom, util

import electrumx.lib.coins as coins

#def excepthook(type, obj, tb):
#    import pdb; pdb.set_trace()
#sys.excepthook = excepthook

async def main():
    # note: this private key is not private
    privkey = bitcoin.hex2privkey('088412ca112561ff5db3db83e2756fe447d36ba3c556e158c8f016a2934f7279')

    logging.basicConfig(level=logging.DEBUG)

    #blockchainmodule = blockchain_module.BlockchainModule(electrum_client.Electrum(electrum))
    #blockchainmodule = blockchain_module.BlockchainModule(electrum_client.ElectrumSV())
    #blockchainmodule = blockchain_module.BlockchainModule(electrumx_client.ElectrumX())

    coin = coins.BitcoinSV
    while True:
        try:
            peer = random.choice(coin.PEERS)
            blockchainmodule = blockchain_module.BlockchainModule(electrum_client_2.ElectrumClient(peer, coin=coin))
            await blockchainmodule.blockchain.init()
            break
        except OSError:
            continue
    pycoinnet_019.BitcoinSV['seed_host_port_pairs'] = pycoinnet_019.BitcoinSV['seed_host_port_pairs'][:5]
    backup_client = pycoinnet_019.PycoinnetClient(**pycoinnet_019.BitcoinSV)
    await backup_client.init()
    blockchainmodule.blockchain.broadcast = backup_client.broadcast

    bm0 = await blockchainmodule.submodules()
    bm1 = await bm0[0].submodules();
    BJPG_TXID = 'a3907e5b910f798c8d0fb450d483a0aefa5ce40ac74064b377603e5ea51deccb'
    #print('block 0 txids:', [txid async for txid in bm1[0].items()])
    #example_height = 100002
    #print(f'block {example_height} txids:', [txid async for txid in bm1[example_height].items()])

    #print('downloading a jpeg image from transaction ' + BJPG_TXID)
    #tx = await blockchainmodule.blockchain.tx(None, None, BJPG_TXID, None)
    #BJPG = bitcom.B.from_tx(tx)
    #with open(f'{BJPG_TXID}.jpg', 'wb') as jpgout:
    #    jpgout.write(BJPG.data)
    #    print(f'wrote {BJPG.media_type} to {BJPG_TXID}.jpg')

    blockchain = blockchainmodule.blockchain
    scripthash = blockchain.addr_to_scripthash(bitcoin.privkey2addr(privkey))

    addr = bitcoin.privkey2addr(privkey)
    addr_updates = await blockchain.watch_addr(addr)
    header_updates = await blockchain.watch_headers()
    addr_and_header_updates = util.Queues(addr_updates, header_updates)

    #utxos = await blockchainmodule.blockchain.addr_utxos(privkey.public_key.to_address().to_string())
    #print('utxos', utxos)
    #fee_per_kb = await blockchainmodule.blockchain.estimate_fee_per_kb(6, 0.25)
    #print('fee per kb:', fee_per_kb)
    unspents = await blockchain.addr_unspents(addr)
    min_fee = await blockchain.min_fee()
    fee_per_kb = await blockchain.fee_per_kb(1000)
    tx, unspent, fee, balance = bitcoin.op_return(privkey, unspents, min_fee, fee_per_kb, 'hello', 'world', forkid = True)#utxos, fee_per_kb, 'hello', 'world')
    print('sending tx:', tx.hash_hex)
    txid = await blockchainmodule.blockchain.broadcast(tx.bytes)
    print('sent', txid)

    #await asyncio.sleep(60*30)

    in_chain = False
    while True:
        updates_by_queue = await addr_and_header_updates.get()
        if header_updates in updates_by_queue:
            print('New block mined.')
        if addr_updates in updates_by_queue:
            print('Tx status change.')
        in_mempool = False
        for entry in await blockchainmodule.blockchain.addr_mempool(addr):
            if entry['tx_hash'] == txid:
                in_mempool = True
                print('Tx is in the mempool')
                break
        if not in_mempool and header_updates in updates_by_queue:
            in_chain = False
            for entry in await blockchainmodule.blockchain.addr_history(addr):
                if entry['tx_hash'] == txid:
                    in_chain = True
                    height = entry['height']
                    break
            if in_chain:
                tip_height = await blockchain.height()
                print(f'tx at height {height}, tip {tip_height}, {tip_height - height + 1} confirmations')
        if not in_chain and not in_mempool:
            print('tx lost?')

asyncio.get_event_loop().run_until_complete(main())
#asyncio.run(main())
