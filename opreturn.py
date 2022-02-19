#!/usr/bin/env python3

import anyio
import asyncclick as click

from bulletprooftoilet import bitcoin, blockchain_module, electrum_client_2, util

import electrumx.lib.coins as coins

import logging, random, sys

@click.command()
@click.option('--no-strip', default = False, help='Do not pass data through .strip()')
@click.option('--priv-key', default = '088412ca112561ff5db3db83e2756fe447d36ba3c556e158c8f016a2934f7279', help='note: this private key is not private')
@click.option('--coin', default='BitcoinSV', help='Name of coin to use')
@click.option('--net', default='mainnet', help='Coin network to use')
@click.option('--tag', help='Additional tag data to add as op_return outputs', multiple=True)
@click.option('--prefix-null', default=True)
                        # note: this private key is not private
async def main(no_strip = False, priv_key = '088412ca112561ff5db3db83e2756fe447d36ba3c556e158c8f016a2934f7279', coin = 'BitcoinSV', net = 'mainnet', tag = (), prefix_null = True):
    priv_key = bitcoin.hex2privkey(priv_key)
    logging.basicConfig(level=logging.DEBUG)

    coin = coins.Coin.lookup_coin_class(coin, net)
    while True:
        try:
            peer = random.choice(coin.PEERS)
            blockchainmodule = blockchain_module.BlockchainModule(electrum_client_2.ElectrumClient(peer, coin=coin))
            await blockchainmodule.blockchain.init()
            break
        except OSError:
            continue

    blockchain = blockchainmodule.blockchain
    addr = bitcoin.privkey2addr(priv_key)
    scripthash = blockchain.addr_to_scripthash(addr)
    addr_updates = await blockchain.watch_addr(addr)
    header_updates = await blockchain.watch_headers()
    addr_and_header_updates = util.Queues(addr_updates, header_updates)

    unspents = await blockchain.addr_unspents(addr)
    min_fee = await blockchain.min_fee()
    fee_per_kb = await blockchain.fee_per_kb(1000)

    waste = sys.stdin.read()
    if not no_strip:
        data = waste.strip()

    tx, unspent, fee, balance = bitcoin.op_return(priv_key, unspents, min_fee, fee_per_kb, waste, extra_lists_of_items = [[t] for t in tag], forkid = (coin is coins.BitcoinSV), add_null_prefix = prefix_null)

    txid = await blockchainmodule.blockchain.broadcast(tx.bytes)

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

if __name__ == '__main__':
    main(_anyio_backend='asyncio')
