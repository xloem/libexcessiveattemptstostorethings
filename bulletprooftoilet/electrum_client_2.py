import asyncio, logging, time

import aiorpcx, ssl, bit

from .bitcoin import Header, TooLongMempoolChain, InsufficientFee, MempoolConflict

class ElectrumClient:
    def __init__(self, peer = 'localhost:50001:t', coin = None, keepalive_seconds = 900 / 4, max_transaction_size = 1_000_000_000):
        if ' ' in peer and coin is not None:
            host = peer.split(' ')[0]
            kind = peer.split(' ')[-1]
            port = coin.PEER_DEFAULT_PORTS[kind]
            peer = f'{host}:{port}:{kind}'
        else:
            host, port, kind = peer.split(':')
        self.keepalive_seconds = keepalive_seconds
        self._max_transaction_size = max_transaction_size
        if kind not in 'st':
            raise AssertionError('expected :s for ssl or :t for tcp')

        class Session(aiorpcx.RPCSession):
            async def handle_request(session, request):
                self.logger.debug(f'handle request: {request}')
                #import pdb; pdb.set_trace()
                handler = None
                if isinstance(request, aiorpcx.Notification):
                    if request.method == 'blockchain.headers.subscribe':
                        handler = self.on_header
                    elif request.method == 'blockchain.scripthash.subscribe':
                        handler = self.on_scripthash
                return await aiorpcx.handler_invocation(handler, request)()

        kwargs = {}
        if kind == 's':
            kwargs['ssl'] = ssl.SSLContext(ssl.PROTOCOL_TLS)
        if host.endswith('.onion'):
            kwargs['proxy'] = '127.0.0.1:9050'
            kwargs['resolve'] = False
        kwargs['session_factory'] = Session

        self.host, self.port, self.rs_kwargs = host, port, kwargs
        self.client = aiorpcx.connect_rs(self.host, self.port, **kwargs)

        self._headers = []
        self._txids = {}
        self._max_header_chunk = 2016
        self.header_queues = set()
        self.scripthash_queues = {}
        self.logger = logging.getLogger(self.__class__.__name__).getChild(peer)

    async def init(self):
        transport, protocol = await self.client.create_connection()
        session = protocol.session
        assert isinstance(session, aiorpcx.session.SessionBase)
        self.transport = transport
        self.protocol = protocol
        self.session = session

        self.last_message_received_at = time.time()
        self.keepalive_task = asyncio.create_task(self._keepalive())
        
        banner = await self.request(str, 'server.banner')
        donation_address = await self.request(str, 'server.donation_address')
        if banner:
            self.logger.info(f'{self.host} {banner}')
        if donation_address:
            self.logger.info(f'Donate to {self.host}: {donation_address}')

        # this immediately gets the tip header
        await self.on_header(await self.request(dict, 'blockchain.headers.subscribe'))

        for scripthash in self.scripthash_queues:
            await self.request(str, 'blockchain.scripthash.subscribe', scripthash)

    async def delete(self):
        self.keepalive_task.cancel()
        await self.session.close()
        self.keepalive_task = None
        self.transport, self.protocol, self.session = None, None, None

    async def height(self):
        assert len(self._headers) == self._headers[-1].height + 1
        return len(self._headers) - 1

    async def max_transaction_size(self):
        return self._max_transaction_size

    async def header(self, height):
        result = self._headers[height] if height < len(self._headers) else None
        if result is None:
            start = height - (height % self._max_header_chunk)
            result = await self.request(dict, 'blockchain.block.headers', start, self._max_header_chunk)
            self._max_header_chunk = result['max']
            count = result['count']
            if len(self._headers) < count + start:
                self._headers.extend((None for count in range(count + start - len(self._headers))))
            headers = bytes.fromhex(result['hex'])
            del result
            for headeridx in range(count):
                header_height = start + headeridx
                offset = headeridx * Header.size
                raw = headers[offset : offset + Header.size]
                header = Header(raw, header_height)
                self._headers[header_height] = header
                if header_height == height:
                    result = header
        return result

    async def txid_from_pos(self, height, tx_pos, merkle = False):
        return await self.request(dict if merkle else str, 'blockchain.transaction.id_from_pos', height, tx_pos, merkle)

    async def txids(self, height):
        txids = self._txids.get(height)
        if txids is None:
            txids = []
            while True:
                try:
                    txid_hex = await self.txid_from_pos(height, len(txids))
                    txid_raw = bytes.fromhex(txid_hex)[::-1]
                    txids.append(txid_raw)
                    yield txid_hex
                except aiorpcx.RPCError as error:
                    if error.code != 1: # BAD_REQUEST
                        raise
                    break
            if len(txids) == 0:
                header = await self.header(height)
                txid_raw = header.merkle_root_raw
                yield txid_raw[::-1].hex()
                txids.append(txid_raw)
            self._txids[height] = txids
        else:
            for txid in txids:
                yield txid[::-1].hex()

    async def tx(self, blockhash, blockheight, txhash, txpos, verbose = False):
        if blockhash is not None and blockheight is not None:
            header = await self.header(blockheight)
            assert blockhash is header.hash_hex
        if blockheight is not None and txpos is not None:
            fetched_txhash = await self.txid_from_pos(blockheight, txpos)
            if txhash is not None:
                assert fetched_txhash == txhash
            else:
                txhash = fetched_txhash
        return await self.request(dict if verbose else str, 'blockchain.transaction.get', txhash, verbose)

    async def broadcast(self, txbytes) -> str:
        try:
            txid = await self.request(str, 'blockchain.transaction.broadcast', txbytes.hex())
        except aiorpcx.jsonrpc.RPCError as error:
            if error.code == 1: # BAD_REQUEST
                if 'too-long-mempool-chain' in error.message:
                    raise TooLongMempoolChain()
                elif '66: mempool min fee not met' in error.message:
                    raise InsufficientFee(error.message)
                elif 'txn-mempool-conflict' in error.message:
                    self.logger.error(f'{txid} IS A DOUBLE SPEND')
                    raise MempoolConflict()
                elif 'Transaction already in the mempool' in error.message:
                    txid = Tx.from_bytes(txbytes).hash_hex
                    self.logger.error(f'{txid} SENT TO MEMPOOL ALREADY CONTAINING IT')
            raise
        return txid

    async def min_fee(self):
        return await self.request(float, 'blockchain.relayfee') * 100000000

    async def fee_per_kb(self, blocks):
        return await self.request(float, 'blockchain.estimatefee', blocks) * 100000000

    async def peers(self):
        result = []
        peers = await self.request(list, 'server.peers.subscribe')
        for ip, host, (ver, *kinds) in peers:
            if host.endswith('.onion'):
                kind = random.choice(kinds)
            else:
                host = ip
                for kind in kinds:
                    if kind[0] == 's':
                        break
            result.append(f'{host}:{kind[1:]}:{kind[0]}')
        return result

    @staticmethod
    def addr_to_p2pkh(addr):
        return bit.transaction.address_to_scriptpubkey(addr)

    @staticmethod
    def script_to_scripthash(script):
        # input/output indexing format used by electrum protocol
        scripthash = bit.crypto.sha256(script)
        return scripthash[::-1].hex()

    @classmethod
    def addr_to_scripthash(cls, addr):
        return cls.script_to_scripthash(cls.addr_to_p2pkh(addr))

    async def addr_unspents(self, addr):
        script = self.addr_to_p2pkh(addr)
        scripthash = self.script_to_scripthash(script)
        utxos = await self.request(list, 'blockchain.scripthash.listunspent', scripthash)
        unspents = []
        height = await self.height() + 1
        for utxo in utxos:
            unspent = bit.network.meta.Unspent(utxo['value'], height - utxo['height'], script, utxo['tx_hash'], utxo['tx_pos'], 'p2pkh')
            unspents.append(unspent)
        return unspents

    async def addr_balance(self, addr):
        script = self.addr_to_p2pkh(addr)
        scripthash = self.script_to_scripthash(script)
        return await self.request(list, 'blockchain.scripthash.get_balance', scripthash)

    async def addr_mempool(self, addr):
        script = self.addr_to_p2pkh(addr)
        scripthash = self.script_to_scripthash(script)
        # presently a list of dicts containing 'tx_hash' and 'height'
        return await self.request(list, 'blockchain.scripthash.get_mempool', scripthash)

    async def addr_history(self, addr):
        # all txs including mempool
        script = self.addr_to_p2pkh(addr)
        return await self.output_history(script)

    async def output_history(self, script):
        scripthash = self.script_to_scripthash(script)
        # presently a list of dicts containing 'tx_hash', 'height', and 'fee'
        return await self.request(list, 'blockchain.scripthash.get_history', scripthash)

    async def watch_addr(self, addr):
        script = self.addr_to_p2pkh(addr)
        scripthash = self.script_to_scripthash(script)
        queue = asyncio.Queue()
        if scripthash not in self.scripthash_queues:
            self.scripthash_queues[scripthash] = set([queue])
            initial_statehash = await self.request(str, 'blockchain.scripthash.subscribe', scripthash)
            await self.on_scripthash(scripthash, initial_statehash)
        else:
            self.scripthash_queues[scripthash].add(queue)
        return queue

    async def watch_headers(self):
        queue = asyncio.Queue()
        self.header_queues.add(queue)
        return queue

    async def on_header(self, headerdict):
        height = headerdict['height']
        while len(self._headers) > height + 1:
            self._headers.pop()
            if len(self._headers) in self._txids:
                del self._txids[len(self._headers)]
            #self._headers = self.headers[:header.height + 1]
        if len(self._headers) <= height:
            self._headers.extend((None for count in range(1 + height - len(self._headers))))
        #header = await self.header(height)
        header = self.dict2header(headerdict)
        self._headers[height] = header
        await asyncio.gather(*(queue.put(header) for queue in self.header_queues))

    async def on_scripthash(self, scripthash, statehash):
        #import pdb; pdb.set_trace()
        await asyncio.gather(*(queue.put(statehash) for queue in self.scripthash_queues[scripthash]))

    def dict2header(self, dict):
        return Header(
            bytes.fromhex(dict['hex']),
            dict['height']
        )
        #return Header.fromfields(
        #    version = dict['version'],
        #    prev_hash_hex = dict['prev_block_hash'],
        #    merkle_root_hex = dict['merkle_root'],
        #    timestamp = dict['timestamp'],
        #    bits = dict['bits'],
        #    nonce = dict['nonce'],
        #    height = dict['block_height']
        #)

    async def _keepalive(self):
        while True:
            now = time.time()
            seconds_since_last_message = now - self.last_message_received_at
            if seconds_since_last_message >= self.keepalive_seconds:
                self.last_message_received_at = now
                await self.request(type(None), 'server.ping')
            else:
                await asyncio.sleep(self.keepalive_seconds - seconds_since_last_message)

    async def request(self, type, message, *params):
        if not hasattr(self, 'pending_request_count'):
            self.pending_request_count = 0
        try:
            self.pending_request_count += 1
            async with aiorpcx.timeout_after(10):
                self.logger.debug(f'-> {message} {params}')
                result = await self.session.send_request(message, params)
                self.pending_request_count -= 1
                self.logger.debug(f'<- {result}')   
                if not isinstance(result, type):
                    raise Exception(f'{message} return bad result type {type(result).__name__}')
                self.last_message_received_at = time.time()
                return result
        except aiorpcx.TaskTimeout:
            self.pending_request_count -= 1
            self.logger.warn('timeout, reconnecting')
            await self.delete()
            if self.pending_request_count != 0:
                # all requests should be restarted here.  could use a taskgroup
                raise ExceptioN(f'Timeout restarted client but {self.pending_request_count} requests were pending, use taskgroup?')
            await self.init()
            return await self.request(type, message, *params)
        except aiorpcx.jsonrpc.RPCError as error:
            self.pending_request_count -= 1
            if 'too-long-mempool-chain' not in error.message:
                self.logger.warn(error.message)
            else:
                self.logger.info(error.message)
            if error.code == aiorpcx.jsonrpc.JSONRPC.EXCESSIVE_RESOURCE_USAGE:
                await asyncio.sleep(0.2)
                return await self.request(type, message, *params)
            else:
                raise
