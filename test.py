import asyncio, random

import bitcoinx

from bulletprooftoilet import electrum_client_2, electrum_client, electrumx_client, blockchain_module, bitcom

import electrumx.lib.coins as coins

coin = coins.BitcoinSV
peer = random.choice(coin.PEERS)
host = peer.split(' ')[0]
kind = peer.split(' ')[-1]
port = coin.PEER_DEFAULT_PORTS[kind]
peer = f'{host}:{port}:{kind}'

#blockchainmodule = blockchain_module.BlockchainModule(electrumx_client.ElectrumXClient())
#import electrum

# note: this private key is not private
privkey = bitcoinx.PrivateKey.from_hex('088412ca112561ff5db3db83e2756fe447d36ba3c556e158c8f016a2934f7279')

async def opreturn(privkey, unspents, min_fee, fee_per_kb, *items, forkid = False):
    if type(privkey) is not bitcoinx.PrivateKey:
        privkey = bitcoinx.PrivateKey(privkey)
    pubkey = privkey.public_key
    scriptpubkey = pubkey.P2PKH_script()
    inputs = []
    value = 0
    for unspent in unspents:
        value += unspent.amount
        inputs.append(bitcoinx.TxInput(bytes.fromhex(unspent.txid)[::-1], unspent.txindex, scriptpubkey, 0))

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
    #fee = await blockchain.estimate_fee(len(tx.to_bytes()), 6, 0.25)#int(fee_per_kb * len(tx.to_bytes()) / 1024)
    fee = int(max(min_fee, fee_per_kb * len(tx.to_bytes()) / 1024) + 0.5)
    print('FEE:', fee)
    fee_output.value -= fee

    sighash = bitcoinx.SigHash.ALL
    if forkid:
        sighash = bitcoinx.SigHash(sighash | bitcoinx.SigHash.FORKID)
    #sig = privkey.sign(tx.to_bytes() + sighash.to_bytes(4, 'little'), bitcoinx.double_sha256)
    #sig += sighash.to_bytes(1, 'little')
    #scriptsig = bitcoinx.Script() << sig << pubkey.to_bytes()
    for idx, (unspent, input) in enumerate(zip(unspents, inputs)):
        #input.scriptsig = scriptsig
        input.script_sig = bitcoinx.Script() << privkey.sign(tx.signature_hash(idx, unspent.amount, scriptpubkey, sighash), None) + sighash.to_bytes(1, 'little') << pubkey.to_bytes()
    #sig = privkey.sign(tx.to_bytes() + sighash.to_bytes(4, 'little'), bitcoinx.double_sha256)

    return tx

class Queues:
    def __init__(self, *queues):
        self.queues = queues
        self.tasks = {}
    async def get(self):
        for queue in self.queues:
            if queue not in self.tasks:
                task = asyncio.create_task(queue.get())
                self.tasks[queue] = task
        queue_by_task = {task:queue for queue, task in self.tasks.items()}
        done, pending = await asyncio.wait(self.tasks.values(), return_when = asyncio.FIRST_COMPLETED)
        results = {queue_by_task[task]: task.result() for task in done}
        for queue in results:
            del self.tasks[queue]
        return results
        


async def main():
    #blockchainmodule = blockchain_module.BlockchainModule(electrum_client.Electrum(electrum))
    #blockchainmodule = blockchain_module.BlockchainModule(electrum_client.ElectrumSV())
    #blockchainmodule = blockchain_module.BlockchainModule(electrumx_client.ElectrumX())
    blockchainmodule = blockchain_module.BlockchainModule(electrum_client_2.ElectrumClient(peer))
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

    blockchain = blockchainmodule.blockchain
    scripthash = blockchain.addr_to_scripthash(privkey.public_key.to_address().to_string())

    addr = privkey.public_key.to_address().to_string()
    addr_updates = await blockchain.watch_addr(addr)
    header_updates = await blockchain.watch_headers()
    addr_and_header_updates = Queues(addr_updates, header_updates)

    #utxos = await blockchainmodule.blockchain.addr_utxos(privkey.public_key.to_address().to_string())
    #print('utxos', utxos)
    #fee_per_kb = await blockchainmodule.blockchain.estimate_fee_per_kb(6, 0.25)
    #print('fee per kb:', fee_per_kb)
    unspents = await blockchain.addr_unspents(addr)
    min_fee = await blockchain.min_fee()
    fee_per_kb = await blockchain.fee_per_kb(1000)
    tx = await opreturn(privkey, unspents, min_fee, fee_per_kb, 'hello', 'world', forkid = True)#utxos, fee_per_kb, 'hello', 'world')
    print('sending tx:', tx.hex_hash())
    txid = await blockchainmodule.blockchain.broadcast(tx.to_bytes())
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

asyncio.run(main())
