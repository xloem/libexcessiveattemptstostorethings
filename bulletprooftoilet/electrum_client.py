import aiorpcx, ssl
import threading

import asyncio, collections, concurrent.futures, datetime, random, struct

import logging
logging.basicConfig(level=logging.INFO)

import bitcoinx

#class ClientEnv(electrumx.Env):
#    def __init__(self, coin_name, network = 'mainnet'):
#        coin = electrumx.lib.coins.Coin.lookup_coin_class(coin_name, network)   
#        super().__init__(coin)
#        self.peer_announce = False
#    def required(self, envvar):
#        return self.default(envvar, None)
#
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
#
#class PeerManager(electrumx.server.peers.PeerManager):
#    def __init__(self, coin_name, network = 'mainnet'):
#        env = ClientEnv(coin_name, network)
#        self.our_height = 0
#        self.our_hash = env.coin.GENESIS_HASH
#        self.clients = []
#        self._active_peer = None
#        self._active_session = None
#        # db = electrumx.server.db.DB(env)
#        super().__init__(env, None)
#
#    async def peersession(self):
#        if self._active_peer is not None and self._active_peer.bad:
#            await self._active_session.close()
#            self._active_peer = None
#        if self._active_peer is None:
#            client = None
#            while client is None or peer.bad:
#                while len(self.clients) == 0:
#                    await asyncio.sleep(0.2)
#                peer, client = random.choice(self.clients)
#            self._active_session = await client.__aenter__()
#            self._active_peer = peer
#        return self._active_peer, self._active_session
#
#    async def request(self, type, message, *params):
#        peer, session = await self.peersession()
#        from electrumx.server.peers import assert_good
#        result = await session.send_request(message, params)
#        assert_good(message, result, type)
#        return result
#
#    async def transaction_id_from_pos(self, height, tx_pos, merkle=False):
#        return await self.request(dict if merkle else str, 'blockchain.transaction.id_from_pos', height, tx_pos, merkle)
#
#    async def blockheader(self, height):
#        hex = await self.request(str, 'blockchain.block.header', height)
#        bin = bytes.fromhex(hex)
#        version, time, nBits, nonce = struct.unpack('<L32x32xLLL', bin)
#        prevhash, merkleroot = hex[8:8+64], hex[8+64:8+64+64]
#        time = datetime.datetime.fromtimestamp(time)
#        hash = electrumx.lib.hash.double_sha256(bin).hex()
#        return BlockHeader(hash, height, version, prevhash, merkleroot, time, nBits, nonce)
#
#    async def transaction_ids(self, height):
#        pos = 0
#        while True:
#            try:
#                yield await self.transaction_id_from_pos(height, pos)
#                pos += 1
#            except aiorpcx.RPCError as error:
#                if error.args[0] != electrumx.server.session.BAD_REQUEST:
#                    raise
#                break
#
#    async def tx(self, hash, verbose = False):
#        return await self.request(dict if verbose else str, 'blockchain.transaction.get', hash, verbose)
#
#    async def _verify_peer(self, session, peer):
#        await super()._verify_peer(session, peer)
#
#        kind, port, family = peer.connection_tuples()[0]
#        kwargs = {'family': family}
#        if kind == 'SSL':
#            kwargs['ssl'] = ssl.SSLContext(ssl.PROTOCOL_TLS)
#        if self.env.force_proxy or peer.is_tor:
#            if not self.proxy:
#                return
#            kwargs['proxy'] = self.proxy
#            kwargs['resolve'] = not peer.is_tor
#
#        client = aiorpcx.connect_rs(peer.host, port, session_factory=electrumx.server.peers.PeerSession, **kwargs)
#
#        self.clients.append((peer, client))
#
#    async def _send_headers_subscribe(self, session):    
#        from electrumx.server.peers import BadPeerError, assert_good
#        from electrumx.lib.hash import hash_to_hex_str, double_sha256
#        # mutated from electrumx/server/peers.py PeerManager._send_headers_subscribe
#        message = 'blockchain.headers.subscribe'
#        result = await session.send_request(message)
#        assert_good(message, result, dict)
#
#        our_height = self.our_height
#        our_hash = self.our_hash
#
#        their_height = result.get('height')
#        if not isinstance(their_height, int):
#            raise BadPeerError(f'invalid height {their_height}')
#        if (our_height - their_height) > 0:
#            raise BadPeerError(f'bad height {their_height:,d} '
#                               f'(ours: {our_height:,d})')
#
#        # Check prior header too in case of hard fork.
#        check_height = min(our_height, their_height)
#        message = 'blockchain.block.header'
#        their_header = await session.send_request(message, [check_height])
#        assert_good(message, their_header, str)
#        their_hash = hash_to_hex_str(double_sha256(bytes.fromhex(their_header)))
#        if our_hash != their_hash:
#            raise BadPeerError(f'our hash {our_hash}@{check_height} and '
#                               f'theirs {their_hash}@{check_height} differ')
#
#        # verify we can get coinbase txids
#        message = 'blockchain.transaction.id_from_pos'
#        genesis_coinbase_txid = await session.send_request(message, [0, 0])
#        assert_good(message, genesis_coinbase_txid, str)
#
#        if our_height < their_height:
#            message = 'blockchain.block.header'
#            their_header = await session.send_request(message, [their_height])
#            assert_good(message, their_header, str)
#            their_hash = hash_to_hex_str(double_sha256(bytes.fromhex(their_header)))
#            self.our_height = their_height
#            self.our_hash = their_hash
#

class Electrum:
    def __init__(self, electrum, userdirsuffix = '', default_servers = None, **options):
        # can likely access other networks by changing SimpleConfig.
        # SimpleConfig.get('server') shows initial default server
        # --> it turns out network checks are hardcoded into electrum by referencing electrum.constants.  it's designed for 1-process-per-network.
        self.electrum = electrum
        self.default_servers = default_servers if default_servers is not None else self.electrum.net.DEFAULT_SERVERS
        if options.get('server') is None:
            default_server = random.choice([*self.default_servers.items()])
            if 's' in default_server[1]:
                default_server = f'{default_server[0]}:{default_server[1]["s"]}:s'
            else:
                default_server = f'{default_server[0]}:{default_server[1]["t"]}:t'
            options['server'] = default_server
        self.config = self.electrum.simple_config.SimpleConfig(
            options,
            read_user_dir_function = lambda: self.electrum.util.user_dir() + userdirsuffix
        )
        
    async def init(self): 
        # network.start or Daemon.__init__ shouldn't be called inside an async loop
        # because it will pause the async loop, waiting for another async event to finish
        # so it is called in another thread (the default executor is a thread pool)
        loop = asyncio.get_event_loop()
        def make_network():
            asyncio.set_event_loop(loop)
            #self.network = self.electrum.network.Network(config)
            #self.network.start()
            self.daemon = self.electrum.daemon.Daemon(self.config)
            self.network = self.daemon.network

        # main electrum client hardcodes bitcoin-only servers, makes reuse harder
        # this can replace the server member function of Network, to use configured servers
        def get_network_servers():
            with self.network.recent_servers_lock:
                out = dict()
                # add servers received from main interface
                server_peers = self.network.server_peers
                if server_peers:
                    out.update(self.electrum.network.filter_version(server_peers.copy()))
    
                out.update(self.default_servers)
                # add recent servers
                for server in self.network._recent_servers:
                    port = str(server.port)
                    if server.host in out:
                        out[server.host].update({server.protocol: port})
                    else:
                        out[server.host] = {server.protocol: port}
                # potentially filter out some
                if self.config.get('noonion'):
                    out = filter_noonion(out)
                return out

        await asyncio.get_event_loop().run_in_executor(None, make_network)
        self.network.get_servers = get_network_servers

        self.logger = self.daemon.logger
        
        while not self.network.is_connected():
            await asyncio.sleep(0.5)

    async def delete(self):
        #await self.network.stop()
        await self.daemon.stop()
    
    async def height(self):
        return self.network.get_local_height()

    async def _header_dict(self, height):
        header_dict = self.network.interface.blockchain.read_header(height)   
        if header_dict is None:
            await self.network.interface.request_chunk(height)
            header_dict = self.network.interface.blockchain.read_header(height)   
        return header_dict

    async def header(self, height):
        # bin = bytes.fromhex(hex)
        header_dict = await self._header_dict(height)
        # {'version': 1, 'prev_block_hash': '0000000000000000000000000000000000000000000000000000000000000000', 'merkle_root': '4a5e1e4baab89f3a32518a88c31bc87f618f76673e2cc77ab2127b7afdeda33b', 'timestamp': 1231006505, 'bits': 486604799, 'nonce': 2083236893, 'block_height': 0}
        version = header_dict['version']
        prev_hash = bytes.fromhex(header_dict['prev_block_hash'])
        merkle_root = bytes.fromhex(header_dict['merkle_root'])
        timestamp = header_dict['timestamp']
        bits = header_dict['bits']
        nonce = header_dict['nonce']
        raw = struct.pack('<L32s32sLLL', version, prev_hash, merkle_root, timestamp, bits, nonce)
        hash = bitcoinx.double_sha256(raw)[::-1].hex()
        return bitcoinx.Header(version, prev_hash, merkle_root, timestamp, bits, nonce, hash, raw, height)

    async def txids(self, height):
        pos = 0
        while True:
            try:
                leaf_pos_in_tree, tx_hash = await self.txid_for_pos(height, pos)
                yield tx_hash
            except self.electrum.network.UntrustedServerReturnedError as e:
                if not isinstance(e.original_exception, aiorpcx.jsonrpc.RPCError):
                    raise
                break
            pos += 1

    async def txid_for_pos(self, height, pos):
        result = await self.network.get_txid_from_txpos(height, pos, True)
        header = await self._header_dict(height)
        tx_hash = result['tx_hash']
        merkle_branch = result['merkle']
        # raises self.electrum.verifier.MerkleVerificationFailure if fails verification
        # 1 may need to be subtracted from this if coinbase transactions are index 0
        leaf_pos_in_tree = result.get('pos', pos)
        self.electrum.verifier.verify_tx_is_in_block(tx_hash, merkle_branch, leaf_pos_in_tree, header, height)
        #self.electrum.verifier.verify_tx_is_in_block(tx_hash, merkle_branch, pos, header, height)
        return (leaf_pos_in_tree, tx_hash)

    async def tx(self, txid):
        # i briefly glanced at bitcoin-core electrum library 2021 and it appeared that it verified the txid matched the data here
        try:
            hex = await self.network.get_transaction(txid)
        except self.electrum.network.UntrustedServerReturnedError as e:
            if not isinstance(e.original_exception, aiorpcx.jsonrpc.RPCError):
                raise
            raise KeyError(txid)
        return bitcoinx.Tx.from_hex(hex)

    #async def blockheaders(self, start_height, ct):
    #    return await

class ElectrumSV(Electrum):
    DEFAULT_SERVERS = {
        'electrumx.bitcoinsv.io': {
            'pruning': '-',
            's': '50002',
            'version': '1.4'
        },
        'satoshi.vision.cash': {
            'pruning': '-',
            's': '50002',
            'version': '1.4'
        },
        'sv.usebsv.com': {
            'pruning': '-',
            's': '50002',
            't': '50001',
            'version': '1.4'
        },
        'sv.jochen-hoenicke.de': {
            'pruning': '-',
            's': '50002',
            't': '50001',
            'version': '1.4'
        },
        'sv.satoshi.io': {
            'pruning': '-',
            's': '50002',
            't': '50001',
            'version': '1.4',
        }
    }
    def __init__(self, userdirsuffix = '.bsv-servers', default_servers = DEFAULT_SERVERS, **options):
        import electrum
        super().__init__(
            electrum,
            userdirsuffix = userdirsuffix,
            default_servers = default_servers,
            **options
        )

#class ElectrumXClient:
#    def __init__(self, coin_name = 'BitcoinSV', network = 'mainnet'):
#        self.peermanager = PeerManager(coin_name, network)
#        self._blocks = {}
#        self.name = f'{coin_name}-{network}'
#
#    async def peers(self):
#
#    async def init(self):
#        await aiorpcx.TaskGroup().spawn(self.peermanager.discover_peers())
#
#    async def height(self):
#        while self.peermanager.our_height == 0:
#            await asyncio.sleep(0.2)
#        return self.peermanager.our_height
#
#    async def txids(self, height):
#        async for txid in self.block(height).txids():
#            yield txid
#
#    def block(self, height):
#        block = self._blocks.get(height)
#        if block is None:
#            block = Block(height, self.peermanager)
#            self._blocks[height] = block
#        return block
#
#    async def tx(self, blockhash, blockheight, txhash, txpos, verbose = False):
#        return await self.peermanager.tx(txhash, verbose)
