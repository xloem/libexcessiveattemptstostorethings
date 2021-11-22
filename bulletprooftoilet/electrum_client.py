import aiorpcx, ssl
import threading

import asyncio, collections, concurrent.futures, datetime, random, struct

import logging
logging.basicConfig(level=logging.INFO)

import bitcoinx

from . import util

class Electrum:
    def __init__(self, electrum, net = None, userdirsuffix = '', **options):
        # can likely access other networks by changing SimpleConfig.
        # SimpleConfig.get('server') shows initial default server
        # --> it turns out network checks are hardcoded into electrum by referencing electrum.constants.  it's designed for 1-process-per-network.
        self.electrum = electrum
        if net is None:
            net = self.electrum.constants.net
        self._net = net
        #self.default_servers = default_servers if default_servers is not None else self.electrum.net.DEFAULT_SERVERS
        #if options.get('server') is None:
        #    default_server = random.choice([*self.default_servers.items()])
        #    if 's' in default_server[1]:
        #        default_server = f'{default_server[0]}:{default_server[1]["s"]}:s'
        #    else:
        #        default_server = f'{default_server[0]}:{default_server[1]["t"]}:t'
        #    options['server'] = default_server
        self.config = self.electrum.simple_config.SimpleConfig(
            options,
            read_user_dir_function = lambda: self.electrum.util.user_dir() + userdirsuffix
        )
        
    async def init(self): 

        constants = lambda: None

        pick_random_server = None
        constants.net = self._net

        def Interface(*params, **kwparams):
            interface = self.electrum.interface.Interface(*params, **kwparams)
            #interface.net = self._net
            interface, replaced = mutation.replace(interface)
            assert replaced
            #util.replace_all_global_members_with_self_members(interface, 'constants')
            return interface

        def Network(config, *params, **kwparams):
            Network, replaced = mutation.replace(self.electrum.network.Network)
            if config.get('server') is None:
                config.set_key('server', pick_random_server(allowed_protocols = 's').to_json())
            network = Network(config, *params, **kwparams)
            #network = self.electrum.network.Network(config, *params, **kwparams)
            #network, replaced = mutation.replace(network)
            assert replaced
            return network

        mutation = util.GlobalMutation(constants = constants, Interface = Interface, Network = Network)
        pick_random_server, replaced = mutation.replace(self.electrum.network.pick_random_server)
        mutation = util.GlobalMutation(constants = constants, Interface = Interface, Network = Network, pick_random_server = pick_random_server)

        Daemon, daemon_replaced = mutation.replace(self.electrum.daemon.Daemon)

        # network.start or Daemon.__init__ shouldn't be called inside an async loop
        # because it will pause the async loop, waiting for another async event to finish
        # so it is called in another thread (the default executor is a thread pool)
        loop = asyncio.get_event_loop()
        def make_network():
            asyncio.set_event_loop(loop)
            #self.network = self.electrum.network.Network(config)
            #self.network.start()
            self.daemon = Daemon(self.config)
            self.network = self.daemon.network

        ## main electrum client hardcodes bitcoin-only servers, makes reuse harder
        ## this can replace the server member function of Network, to use configured servers
        #def get_network_servers():
        #    with self.network.recent_servers_lock:
        #        out = dict()
        #        # add servers received from main interface
        #        server_peers = self.network.server_peers
        #        if server_peers:
        #            out.update(self.electrum.network.filter_version(server_peers.copy()))
    
        #        out.update(self.default_servers)
        #        # add recent servers
        #        for server in self.network._recent_servers:
        #            port = str(server.port)
        #            if server.host in out:
        #                out[server.host].update({server.protocol: port})
        #            else:
        #                out[server.host] = {server.protocol: port}
        #        # potentially filter out some
        #        if self.config.get('noonion'):
        #            out = filter_noonion(out)
        #        return out

        await asyncio.get_event_loop().run_in_executor(None, make_network)

        #self.network.get_servers = get_network_servers

        
        #self.network.net = self._net
        #mutation.replace(self.network)
        #mutation.replace(self.network.interface)
        #util.replace_all_global_members_with_self_members(self.network, 'constants')
        #self.network.Interface = Interface
        #util.replace_all_global_members_with_self_members(self.network, 'Interface')
        #util.replace_all_global_members_with_self_members(self.network.interface, 'constants')


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
        if header_dict is None:
            raise KeyError(height)
        version = header_dict['version']
        prev_hash = bytes.fromhex(header_dict['prev_block_hash'])[::-1]
        merkle_root = bytes.fromhex(header_dict['merkle_root'])[::-1]
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
                if not isinstance(e.original_exception, aiorpcx.jsonrpc.CodeMessageError):
                    raise
                break
            pos += 1

    async def txid_for_pos(self, height, pos):
        result = await self.network.get_txid_from_txpos(height, pos, True)
        header = await self._header_dict(height)
        tx_hash = result['tx_hash']
        merkle_branch = result['merkle']
        # raises self.electrum.verifier.MerkleVerificationFailure if fails verification
        # 1 may need to be subtracted from this if coinbase transactions are index 0?
        # NOTE: if the coinbase txid is missing, it can be extracted from the first merkle proof
        # NOTE2: we don't need any other merkle proofs if we're getting all the txids: a merkle proof just contains sibling txs
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

import electrum
class ElectrumSV(Electrum, electrum.constants.BitcoinMainnet):
    DEFAULT_SERVERS = {
        'electrumx.bitcoinsv.io': {
            'pruning': '-',
            's': '50002',
            'version': '1.20'
        },
        'satoshi.vision.cash': {
            'pruning': '-',
            's': '50002',
            'version': '1.20'
        },
        'sv.usebsv.com': {
            'pruning': '-',
            's': '50002',
            't': '50001',
            'version': '1.20'
        },
        'sv.jochen-hoenicke.de': {
            'pruning': '-',
            's': '50002',
            't': '50001',
            'version': '1.20'
        },
        'sv.satoshi.io': {
            'pruning': '-',
            's': '50002',
            't': '50001',
            'version': '1.20',
        }
    }
    CHECKPOINTS = []
    def __init__(self, userdirsuffix = '.bsv-servers', default_servers = DEFAULT_SERVERS, **options):
        import electrum
        super().__init__(
            electrum,
            net = self,
            userdirsuffix = userdirsuffix,
            default_servers = default_servers,
            **options
        )

