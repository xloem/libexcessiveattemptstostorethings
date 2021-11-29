import asyncio, logging, struct, time

import aiorpcx, ssl, bit

class Header:
    size = 80
    def __init__(self, raw, height):
        self.raw = raw
        self.height = height
    @staticmethod
    def fromfields(version, prev_hash_hex, merkle_root_hex, timestamp, bits, nonce, height):
        raw = struct.pack('<L32s32sLLL', version, bytes.fromhex(prev_hash_hex)[::-1], bytes.fromhex(merkle_root_hex)[::-1], timestamp, bits, nonce)
        return Header(raw, height)
    @staticmethod
    def fromhex(hex, height):
        return Header(bytes.fromhex(hex), height)
    @property
    def version(self):
        return struct.unpack('<L', self.raw[:4])[0]
    @property
    def prev_hash_raw(self):
        return struct.unpack('32s', self.raw[4:36])[0]
    @property
    def merkle_root_raw(self):
        return struct.unpack('32s', self.raw[36:68])[0]
    @property
    def timestamp(self):
        return struct.unpack('<L', self.raw[68:72])[0]
    @property
    def bits(self):
        return struct.unpack('<L', self.raw[72:76])[0]
    @property
    def nonce(self):
        return struct.unpack('<L', self.raw[76:80])[0]
    @property
    def hex(self):
        return self.raw.hex()
    @property
    def hash_raw(self):
        return bit.crypto.double_sha256(self.raw)
    @property
    def hash_hex(self):
        return self.hash_raw[::-1].hex()
    @property
    def prev_hash_hex(self):
        return self.prev_hash[::-1].hex()
    @property
    def merkle_root_hex(self):
        return self.merkle_root[::-1].hex()

class ElectrumClient:
    def __init__(self, peerstr = 'localhost:50001:t', keepalive_seconds = 450):
        self.keepalive_seconds = keepalive_seconds
        host, port, kind = peerstr.split(':')
        if kind not in 'st':
            raise AssertionError('expected :s for ssl or :t for tcp')

        class Session(aiorpcx.RPCSession):
            async def handle_request(session, request):
                print('handle request:', request)
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
        self.logger = logging.getLogger(self.__class__.__name__).getChild(peerstr)

    async def init(self):
        transport, protocol = await self.client.create_connection()
        session = protocol.session
        assert isinstance(session, aiorpcx.session.SessionBase)
        self.transport = transport
        self.protocol = protocol
        self.session = session
        
        banner = await self.request(str, 'server.banner')
        donation_address = await self.request(str, 'server.donation_address')
        if banner:
            print(self.host, banner)
        if donation_address:
            print(f'Donate to {self.host}:', donation_address)

        self.keepalive_task = asyncio.create_task(self._keepalive())

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
        txid = await self.request(str, 'blockchain.transaction.broadcast', txbytes.hex())
        return txid

    async def min_fee(self):
        return await self.request(float, 'blockchain.relayfee') * 100000000

    async def fee_per_kb(self, blocks):
        return await self.request(float, 'blockchain.estimatefee', blocks) * 100000000

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
                await self.request('server.ping')
            else:
                await asyncio.sleep(self.keepalive_seconds - seconds_since_last_message)

    async def request(self, type, message, *params):
        try:
            async with aiorpcx.timeout_after(10):
                print('->', message, *params)
                result = await self.session.send_request(message, params)
                print('<-', result)   
                if not isinstance(result, type):
                    raise Exception(f'{message} return bad result type {type(result).__name__}')
                self.last_message_received_at = time.time()
                return result
        except aiorpcx.TaskTimeout:
            print('timeout, reconnecting')
            await self.delete()
            await self.init()
            return await self.request(type, message, *params)