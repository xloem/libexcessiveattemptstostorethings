import asyncio, datetime, logging, math, random

import bit, bitcoinx

import electrumx.lib.coins as coins

from honorableneeded import bitcoin, electrum_client_2, util

async def main():
    coin_name = 'BitcoinSV'
    # note: this private key is not private
    priv_key = bitcoin.hex2privkey('088412ca112561ff5db3db83e2756fe447d36ba3c556e158c8f016a2934f7279')

    fee_per_kb_probes = [125, 250, 500, 1000]

    fee_per_kb_probes.sort(reverse = True)

    addr = bitcoin.privkey2addr(privkey)
    coin = coins.Coin.lookup_coin_class(coin_name, 'mainnet')
    forkid = True

    client = electrum_client_2.LoadBalanced(coin.peers, coin = coin)

    await client.init()

    print(f'Will probe {len(client.peers)} peers for fee per kb amoung {fee_per_kb_probes}') 

    for addr, peer in client.peers.items():
        print(f'Probing {addr} ...')
        utxos = await peer.addr_utxos(addr)
        min_fee = await peer.min_fee()
        # want n such that n * fee_per_kb > min_fee
        # min_fee / fee_per_kb < n
        # n = ceil(min_fee / fee_per_kb)
        # n = 

        for idx, fee_per_kb in enumerate(fee_per_kb_probes):
            testmsg = 'test '
            datalen = min_fee // fee_per_kb
            tx, unspent, fee, balance = op_return(priv_key, utxos, min_fee, fee_per_kb, testmsg * (datalen/len(testmsg)), forkid = forkid)
            await peer.broadcast(tx.bytes)
        

asyncio.run(main())
