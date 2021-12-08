#!/usr/bin/env python3

import asyncio, logging, random, sys

from bulletprooftoilet import electrum_client_2, bitcoin, bitcom

import electrumx.lib.coins as coins

async def main():
    logging.basicConfig(level = logging.DEBUG)

    # note: this private key is not private
    privkey = bitcoin.hex2privkey('088412ca112561ff5db3db83e2756fe447d36ba3c556e158c8f016a2934f7279')

    coin = coins.BitcoinSV
    while True:
        try:
            peer = random.choice(coin.PEERS)
            blockchain = electrum_client_2.ElectrumClient(peer, coin=coin)
            await blockchain.init()
            break
        except OSError:
            continue


    print('\n=> Provide waste on stdin to flush it down the cryptographic toilet in a corrupt, broken manner <=\n')
    bcat, unspent = await bitcom.stream_up('test.txt', sys.stdin, privkey, blockchain, bcatinfo = 'testing', buffer = False, buffer_min_fee_txs = False, fee_per_kb = 250, primary_fee_per_kb = (await blockchain.fee_per_kb(1000)))

    await blockchain.delete()

    print('flush was:', bcat.tx.hash_hex)

asyncio.run(main())
