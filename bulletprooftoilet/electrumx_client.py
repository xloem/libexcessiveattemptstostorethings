import electrumx

import aiorpcx, ssl

import asyncio, collections, datetime, random, struct

import bitcoinx

import logging
logging.basicConfig(level=logging.INFO)

class ClientEnv(electrumx.Env):
    def __init__(self, coin_name, network = 'mainnet'):
        coin = electrumx.lib.coins.Coin.lookup_coin_class(coin_name, network)   
        super().__init__(coin)
        self.peer_announce = False
    def required(self, envvar):
        return self.default(envvar, None)

#BlockHeader = collections.namedtuple('BlockHeader', 'version prevhash merkleroot time nBits nonce')
#
#class Block:
#    def __init__(self, height, peermanager):
#        self._height = height
#        self._peermanager = peermanager
#        self._header = None
#        self._hash = None
#        self._txids = None
#        self.logger = peermanager.logger
#        #self._have_last_txid = False
#    @property
#    def height(self):
#        return self._height
#    async def header(self):
#        if self._header is None:
#            self.logger.info(f'Caching blockheader @{self._height} ...')
#            hex = await self._peermanager.request(str, 'blockchain.block.header', self._height)
#            bin = bytes.fromhex(hex)
#            version, prevhash, merkleroot, time, nBits, nonce = struct.unpack('<L32s32sLLL', bin)
#            prevhash = prevhash[::-1].hex()
#            merkleroot = merkleroot.hex()
#            time = datetime.datetime.fromtimestamp(time)
#            self._hash = electrumx.lib.hash.double_sha256(bin)[::-1].hex()
#            self._header = BlockHeader(version, prevhash, merkleroot, time, nBits, nonce)
#        return self._header
#    async def hash(self):
#        if self._hash is None:
#            await self.header()
#        return self._hash
#    async def txids(self):
#        if self._txids is None:
#            self.logger.info(f'Caching txids @{self._height} ...')
#            txids = []
#            while True:
#                try:
#                    txid = await self._peermanager.transaction_id_from_pos(self._height, len(txids))
#                    txids.append(txid)
#                    yield txid
#                except aiorpcx.RPCError as error:
#                    if error.args[0] != electrumx.server.session.BAD_REQUEST:
#                        raise
#                    break
#            self._txids = txids
#        else:
#            for txid in self._txids:
#                yield txid

def PeerSession(handlers):
    class PeerSession(electrumx.server.peers.PeerSession):
        async def handle_request(self, request):
            handler = handlers.get(request.method)
            if handler is not None:
                #import pdb; pdb.set_trace()
                return await aiorpcx.handler_invocation(handler, request)()
            else:
                return await super().handle_request(request)
    return PeerSession

class PeerManager(electrumx.server.peers.PeerManager):
    def __init__(self, coin_name, network = 'mainnet'):
        env = ClientEnv(coin_name, network)
        self.our_height = 0
        self.our_hash = env.coin.GENESIS_HASH
        self.clients = []
        self._active_peer = None
        self._active_session = None
        self._scripthash_queues = {}
        self._header_queues = set()
        # db = electrumx.server.db.DB(env)
        super().__init__(env, None)

    async def peersession(self):
        if self._active_peer is not None and self._active_peer.bad:
            await self._active_session.close()
            self._active_peer = None
        if self._active_peer is None:
            client = None
            while client is None or peer.bad:
                while len(self.clients) == 0:
                    await asyncio.sleep(0.2)
                peer, client = random.choice(self.clients)
            self._active_session = await client.__aenter__()
            self._active_peer = peer
        return self._active_peer, self._active_session

    async def request(self, type, message, *params):
        peer, session = await self.peersession()
        from electrumx.server.peers import assert_good
        try:
            result = await session.send_request(message, params)
        except aiorpcx.curio.TaskTimeout as e:
            print(et)
            return self.request(type, message, *params)
        assert_good(message, result, type)
        return result

    async def transaction_id_from_pos(self, height, tx_pos, merkle=False):
        return await self.request(dict if merkle else str, 'blockchain.transaction.id_from_pos', height, tx_pos, merkle)

    #async def blockheader(self, height):
    #    hex = await self.request(str, 'blockchain.block.header', height)
    #    bin = bytes.fromhex(hex)
    #    version, time, nBits, nonce = struct.unpack('<L32x32xLLL', bin)
    #    prevhash, merkleroot = hex[8:8+64], hex[8+64:8+64+64]
    #    time = datetime.datetime.fromtimestamp(time)
    #    hash = electrumx.lib.hash.double_sha256(bin).hex()
    #    return BlockHeader(hash, height, version, prevhash, merkleroot, time, nBits, nonce)

    #async def transaction_ids(self, height):
    #    # presently unused
    #    pos = 0
    #    while True:
    #        try:
    #            yield await self.transaction_id_from_pos(height, pos)
    #            pos += 1
    #        except aiorpcx.RPCError as error:
    #            if error.args[0] != electrumx.server.session.BAD_REQUEST:
    #                raise
    #            break

    async def tx(self, hash, verbose = False):
        return await self.request(dict if verbose else str, 'blockchain.transaction.get', hash, verbose)

    async def _verify_peer(self, session, peer):
        await super()._verify_peer(session, peer)

        kind, port, family = peer.connection_tuples()[0]
        kwargs = {'family': family}
        if kind == 'SSL':
            kwargs['ssl'] = ssl.SSLContext(ssl.PROTOCOL_TLS)
        if self.env.force_proxy or peer.is_tor:
            if not self.proxy:
                return
            kwargs['proxy'] = self.proxy
            kwargs['resolve'] = not peer.is_tor

        handlers = {
            'blockchain.scripthash.subscribe':self.on_scripthash,
            'blockchain.headers.subscribe':self.on_header,
        }
        client = aiorpcx.connect_rs(peer.host, port, session_factory=PeerSession(handlers), **kwargs)

        self.clients.append((peer, client))

    async def on_scripthash(self, scripthash, statehash):
        try:
            for queue in self._scripthash_queues[scripthash]:
                await queue.put(statehash)
        except:
            print('WARNING: subscribed but no queue', scripthash, statehash)

    async def on_header(self, header):
        print('dbgheader', header)
        for queue in self._header_queues:
            await queue.put(header)

    async def _send_headers_subscribe(self, session):    
        from electrumx.server.peers import BadPeerError, assert_good
        from electrumx.lib.hash import hash_to_hex_str, double_sha256
        # mutated from electrumx/server/peers.py PeerManager._send_headers_subscribe
        message = 'blockchain.headers.subscribe'
        result = await session.send_request(message)
        assert_good(message, result, dict)

        our_height = self.our_height
        our_hash = self.our_hash

        their_height = result.get('height')
        if not isinstance(their_height, int):
            raise BadPeerError(f'invalid height {their_height}')
        if (our_height - their_height) > 0:
            raise BadPeerError(f'bad height {their_height:,d} '
                               f'(ours: {our_height:,d})')

        # Check prior header too in case of hard fork.
        check_height = min(our_height, their_height)
        message = 'blockchain.block.header'
        their_header = await session.send_request(message, [check_height])
        assert_good(message, their_header, str)
        their_hash = hash_to_hex_str(double_sha256(bytes.fromhex(their_header)))
        if our_hash != their_hash:
            raise BadPeerError(f'our hash {our_hash}@{check_height} and '
                               f'theirs {their_hash}@{check_height} differ')

        ## verify we can get coinbase txids from empty blocks
        # never mind, they can be extracted from the merkle root in the header
        #message = 'blockchain.transaction.id_from_pos'
        #genesis_coinbase_txid = await session.send_request(message, [0, 0])
        #assert_good(message, genesis_coinbase_txid, str)

        if our_height < their_height:
            message = 'blockchain.block.header'
            their_header = await session.send_request(message, [their_height])
            assert_good(message, their_header, str)
            their_hash = hash_to_hex_str(double_sha256(bytes.fromhex(their_header)))
            self.our_height = their_height
            self.our_hash = their_hash

class ElectrumX:
    def __init__(self, coin_name = 'BitcoinSV', network = 'mainnet'):
        self.peermanager = PeerManager(coin_name, network)
        self.max_header_chunk = 2016
        #self._blocks = {}
        self._headers = {}
        self._txids_by_height = {}
        self.name = f'{coin_name}-{network}'
        self.logger= self.peermanager.logger
        self.merkle = electrumx.lib.merkle.Merkle()

    #async def peers(self):
    #
    async def init(self):
        logging.basicConfig(level=logging.INFO)
        await aiorpcx.TaskGroup().spawn(self.peermanager.discover_peers())

    async def delete(self):
        pass

    async def height(self):
        while self.peermanager.our_height == 0:
            await asyncio.sleep(0.2)
        return self.peermanager.our_height

    async def header(self, height):
        result = self._headers.get(height)
        if result is None:
            chunksize = self.max_header_chunk
            start = height - (height % chunksize)
            self.logger.warning(f'Fetching block headers {start} - {start + chunksize} ...  this be improved to use e.g. electrum.server.block_processor.BlockProcessor or its daemon, and its databsae')
            # this can also provide merkle proofs if a checkpoint is included
            result = await self.peermanager.request(dict, 'blockchain.block.headers', start, chunksize)
            self.max_header_chunk = result['max']
            hex = result['hex']
            count = result['count']
            headers = bytes.fromhex(result['hex'])
            del result
            for headeridx in range(count):
                header_height = start + headeridx
                raw = headers[headeridx * 80:(headeridx+1)*80]
                header = await self.bytes2header(raw, header_height)
                if header_height == height:
                    result = header
        return result

    async def bytes2header(self, raw, header_height):
        version, prev_hash, merkle_root, timestamp, bits, nonce = struct.unpack('<L32s32sLLL', raw)
        prev_hash = prev_hash[::-1].hex()
        merkle_root = merkle_root[::-1].hex()
        hash = bitcoinx.double_sha256(raw)[::-1].hex()
        header = bitcoinx.Header(version, prev_hash, merkle_root, timestamp, bits, nonce, hash, raw, header_height)
        print('TODO: form chain from headers')
        #if header_height > 0:
        #    if (await self.header(header_height - 1)).hash != header.prev_hash:
        #        raise AssertionError('TODO: chain link incorrect.  if this check is commented out the system will function but some data will be corrupt or malicious')
        if header_height in self._headers:
            raise AssertionError('chain reorg unhandled')
        self._headers[header_height] = header
        return header

    async def txids(self, height):
        txids = self._txids_by_height.get(height)
        if txids is None:
            merkle_root = (await self.header(height)).merkle_root
            merkle_root = bytes.fromhex(merkle_root)[::-1]
            txids = []
            while True:
                try:
                    txid_dict = await self.peermanager.transaction_id_from_pos(height, len(txids), True)
                    txid = bytes.fromhex(txid_dict['tx_hash'])[::-1]
                    proof = [bytes.fromhex(hash)[::-1] for hash in txid_dict['merkle']]
                    calculated_root = self.merkle.root_from_proof(txid, proof, len(txids))
                    if calculated_root != merkle_root:
                        raise AssertionError('TODO: merkle verification failed.  if this check is commented out the system will function but some data will be corrupt or malicious')
                    yield txid[::-1].hex()
                    txids.append(txid)
                    if len(proof) and proof[0] != txid:
                        txid, proof[0] = proof[0], txid
                        assert self.merkle.root_from_proof(txid, proof, len(txids)) == merkle_root
                        yield txid[::-1].hex()
                        txids.append(txid)
                except aiorpcx.RPCError as error:
                    if error.args[0] != electrumx.server.session.BAD_REQUEST:
                        raise
                    break
            if len(txids) == 0:
                txid = merkle_root
                yield txid[::-1].hex()
                txids.append(txid)
            self._txids_by_height[height] = txids
        else:
            for txid in txids:
                yield txid
        #async for txid in self.block(height).txids():
        #    yield txid

    #def block(self, height):
    #    block = self._blocks.get(height)
    #    if block is None:
    #        block = Block(height, self.peermanager)
    #        self._blocks[height] = block
    #    return block

    async def tx(self, blockhash, blockheight, txhash, txpos, verbose = False):
        return await self.peermanager.tx(txhash, verbose)

    async def broadcast(self, txbytes) -> str:
        txid = await self.peermanager.request(str, 'blockchain.transaction.broadcast', txbytes.hex())
        #await self.peermanager.request(list, 'blockchain.scripthash.subscribe', hashx)
        return txid

    async def estimate_fee(self, bytect, blocks, probability):
        fee_per_kb = await self.peermanager.request(float, 'blockchain.estimatefee', blocks)#, 'CONSERVATIVE' if probability > .5 else 'ECONOMICAL')
        min_fee = await self.peermanager.request(float, 'blockchain.relayfee')
        return int(max(min_fee, fee_per_kb * bytect / 1024) * 100000000)

    def addr_to_scripthash(self, addr):
        # scripthash format is electrum-specific and documented in the electrum project
        script = self.peermanager.env.coin.pay_to_address_script(addr)
        hash = electrumx.lib.hash.sha256(script)
        return hash[::-1].hex()

    async def addr_utxos(self, addr):
        # presently returns a list of dicts:
        # [{ 'tx_hash': hex, 'tx_pos': int, 'height': int, 'value': int }, ...]
        scripthash = self.addr_to_scripthash(addr)
        return await self.peermanager.request(list, 'blockchain.scripthash.listunspent', scripthash)

    async def addr_txids(self, addr):
        scripthash = self.addr_to_scripthash(addr)
        return await self.peermanager.request(list, 'blockchain.scripthash.get_history', scripthash)
        return await self.peermanager.request(list, 'blockchain.scripthash.get_mempool', scripthash)

    async def addr_balance(self, addr):
        scripthash = self.addr_to_scripthash(addr)
        return await self.peermanager.request(list, 'blockchain.scripthash.get_balance', scripthash)

    async def addr_get_mempool(self, addr):
        scripthash = self.addr_to_scripthash(addr)
        # presently a list of dicts containing 'tx_hash' and 'height'
        return await self.peermanager.request(list, 'blockchain.scripthash.get_mempool', scripthash)

    async def addr_get_history(self, addr):
        # all txs including mempool
        scripthash = self.addr_to_scripthash(addr)
        # presently a list of dicts containing 'tx_hash', 'height', and 'fee'
        return await self.peermanager.request(list, 'blockchain.scripthash.get_history', scripthash)

    async def watch_address(self, addr):
        scripthash = self.addr_to_scripthash(addr)
        queue = asyncio.Queue()
        try:
            if scripthash not in self.peermanager._scripthash_queues:
                self.peermanager._scripthash_queues[scripthash] = set([queue])
                statehash = await self.peermanager.request(str, 'blockchain.scripthash.subscribe', scripthash)
            else:
                self.peermanager._scripthash_queues[scripthash].add(queue)
                statehash = None
            while True:
                if statehash is not None:
                    yield statehash
                statehash = await queue.get()
        finally:
            self.peermanager._scripthash_queues[scripthash].remove(queue)
            if len(self.peermanager._scripthash_queues[scripthash]) == 0:
                try:
                    await self.peermanager.request(str, 'blockchain.scripthash.unsubscribe', scripthash)
                except:
                    pass

    async def watch_headers(self):
        queue = asyncio.Queue()
        try:
            if len(self.peermanager._header_queues) == 0:
                self.peermanager._header_queues.add(queue)
                header = await self.peermanager.request(dict, 'blockchain.headers.subscribe')
            else:
                self.peermanager._header_queues.add(queue)
                header = None
            while True:
                header = await self.bytes2header(bytes.fromhex(header['hex']), header['height'])
                if header is not None:
                    yield header
                header = await queue.get()
        finally:
            self.peermanager._header_queues.remove(queue)
            if len(self.peermanager._header_queues) == 0:
                try:
                    await self.peermanager.request(str, 'blockchain.headers.unsubscribe')
                except:
                    pass

