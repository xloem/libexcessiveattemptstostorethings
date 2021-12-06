import asyncio, datetime, logging, math, random

import bit, bitcoinx

import electrumx.lib.coins as coins

from honorableneeded import bitcoin, electrum_client_2, util

async def main():
    print('can look for recent cheap fees to give you an idea of the bare minimum\n')
    coin_name = input('coin name ? ').replace(' ','')
    coin = coins.Coin.lookup_coin_class(coin_name, 'mainnet')
    cheapest_flat_fee = float('inf')
    cheapest_fee_rate = float('inf')
    cheapest_peer = None

    unvisited = set(coin.PEERS)
    visited = set()
    while unvisited:
        peer = unvisited.pop()
        visited.add(peer)
        print('peer', peer, end='\r', flush=True)
        try:
            blockchain = electrum_client_2.ElectrumClient(peer, coin=coin)
            await blockchain.init()
            for other in await blockchain.peers():
                if other not in visited:
                    unvisited.add(other)
            min_fee = await blockchain.min_fee()
            fee_rate = await blockchain.fee_per_kb(1000)
            if min_fee < cheapest_flat_fee or fee_rate < cheapest_fee_rate:
                print('peer', peer, ': ', end='')
                if min_fee < cheapest_flat_fee:
                    cheapest_flat_fee = min_fee
                    print('Found new lowest minimum fee', cheapest_flat_fee)
                if fee_rate <= cheapest_fee_rate:
                    cheapest_fee_rate = fee_rate
                    cheapest_peer = peer
                    print('Found new lowest fee per kb', cheapest_fee_rate)
            await blockchain.delete()
        except OSError:
            continue
        

    logging.basicConfig(level = logging.WARN)

    while True:
        try:
            peer = random.choice(coin.PEERS)
            blockchain = electrum_client_2.ElectrumClient(peer, coin=coin)
            await blockchain.init()
            break
        except OSError:
            continue

    reverse_block_queue = asyncio.Queue()
    forward_block_queue = await blockchain.watch_headers()
    print('starting')

    async def walk_headers_backward():
        for height in range(await blockchain.height(), -1, -1):
            header = await blockchain.header(height)
            await reverse_block_queue.put(header)

    backward_task = asyncio.create_task(walk_headers_backward())

    header_queues = util.Queues(forward_block_queue, reverse_block_queue)
    print('made queues')

    while True:
        headers = (await header_queues.get()).values()
        for header in headers:
            headerdate = datetime.datetime.fromtimestamp(header.timestamp).isoformat()
            print('block:', headerdate, header.hash_hex)
            txnum = 0
            async for txid in blockchain.txids(header.height):
                txnum += 1
                print('tx', txnum, end='\r', flush=True)
                tx = await blockchain.tx(None, header.height, txid, None)
                txlen = len(tx)/2
                tx = bitcoin.hex2tx(tx)
                fee_sum = 0
                for txinput in tx.inputs:
                    unspent = await bitcoin.input2utxo(txinput, blockchain)
                    if unspent.txid == '0000000000000000000000000000000000000000000000000000000000000000' or unspent.txid == b'\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0':
                        fee_sum = None
                        break
                    fee_sum += unspent.amount
                if fee_sum is None:
                    continue
                for txoutput in tx.outputs:
                    fee_sum -= txoutput.value
                fee_rate = int(1000 * fee_sum / txlen)
                if fee_sum < cheapest_flat_fee or fee_rate < cheapest_fee_rate:
                    print('tx', txnum, ': ', end='')
                    if fee_sum < cheapest_flat_fee:
                        cheapest_flat_fee = fee_sum
                        print('Found new lowest minimum fee', cheapest_flat_fee)
                    if fee_rate < cheapest_fee_rate:
                        cheapest_fee_rate = fee_rate
                        print('Found new lowest fee per kb', cheapest_fee_rate)
            print('processed block')

    
asyncio.run(main())
