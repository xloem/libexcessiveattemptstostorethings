#!/usr/bin/env python3

import anyio
import asyncclick as click

from bulletprooftoilet import bitcoin, blockchain_module, electrum_client_2, util

import bitcoinx

import electrumx.lib.coins as coins

import datetime, logging, random, re, sys

@click.command()
@click.option('--addr', default='1PTtzfR9ZpLzFsbp6bKVmQtWa5zsd9KotD', help='address to use')
@click.option('--priv-key', help='can use a private key if you want but it could be displayed while running')
@click.option('--coin', default='BitcoinSV', help='Name of coin to use')
@click.option('--net', default='mainnet', help='Coin network to use')
@click.option('--regexp', default=None, help='regexp string to filter by')
@click.option('--tag', default=None, help='specify a tag string instead of an address')
@click.option('--prefix-null', default=True)
                        # note: this private key is not private
async def main(no_strip = False, priv_key = None, addr = '1PTtzfR9ZpLzFsbp6bKVmQtWa5zsd9KotD', coin = 'BitcoinSV', net = 'mainnet', regexp=None, prefix_null = True, tag = None):
    #logging.basicConfig(level=logging.DEBUG)
    if priv_key is not None:
        addr = bitcoin.privkey2addr(bitcoin.hex2privkey(priv_key))
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

    if tag is not None:
        script_pubkey = bitcoin.bytes_to_op_return_script(tag, add_null_prefix = prefix_null)
        scripthex = script_pubkey.to_hex()
        history = await blockchain.output_history(scripthex)
    else:
        history = await blockchain.addr_history(addr)
    for items in history:
        txid = items['tx_hash']
        height = items['height']
        header = await blockchain.header(height)
        datestr =datetime.datetime.fromtimestamp(header.timestamp).isoformat()
        txhex = await blockchain.tx(None, height, txid, None)
        tx = bitcoinx.Tx.from_hex(txhex)
        data = []
        for output in tx.outputs:
            script = output.script_pubkey
            output = repr([*script.ops_and_items()])
            data.append(output)

        if regexp is not None:
            data = [data for data in data if re.match(regexp, data)]

        if len(data) > 0:
            print(datestr, header.hash_hex, txid)
            for item in data:
                print(item)

if __name__ == '__main__':
    main(_anyio_backend='asyncio')
