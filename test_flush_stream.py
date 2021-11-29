import asyncio, random, sys

from bulletprooftoilet import electrum_client_2, bitcoin, bitcom

import electrumx.lib.coins as coins

async def main():
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


    print('WARN: bugs not fixed yet')
    print('=> Provide waste on stdin to flush it down the cryptographic toilet in a corrupt, broken manner <=')
    bcat, unspent = await bitcom.stream_up('test.txt', sys.stdin, privkey, blockchain, bcatinfo = 'testing', buffer = False)

    await blockchain.delete()

    print('WARN: bugs not fixed yet')
    print('flush was:', bcat.tx.hex_hash())

asyncio.run(main())
