import aiorpcx, ssl
import threading

import asyncio, collections, concurrent.futures, datetime, random, struct

import logging
logging.basicConfig(level=logging.INFO)

import bitcoinx

from . import util

# electrum uses ANDROID_DATA to enable the use of android java, which is not available in android terminal emulators
import os
if 'ANDROID_DATA' in os.environ and not 'ANDROID_ARGUMENT' in os.environ:
    del os.environ['ANDROID_DATA']

class Electrum:
    def __init__(self, electrum, net = None, userdirsuffix = '', **options):
        self.electrum = electrum
        if net is None:
            net = self.electrum.constants.net
        self._net = net
        self.config = self.electrum.simple_config.SimpleConfig(
            options,
            read_user_dir_function = lambda: self.electrum.util.user_dir() + userdirsuffix
        )
        
    async def init(self): 

        # main electrum client hardcodes bitcoin-only servers, makes reuse harder
        # this can replace the server member function of Network, to use configured servers
        class constants:
            net = self._net

        pick_random_server = None
        constants.net = self._net

        def Interface(*params, **kwparams):
            interface = self.electrum.interface.Interface(*params, **kwparams)
            new_interface = mutation.replace(interface)
            assert new_interface is not interface or type(interface) is Interface
            return interface

        def Network(config, *params, **kwparams):
            if config.get('server') is None:
                config.set_key('server', pick_random_server(allowed_protocols = 's').to_json())
            new_Network = mutation.replace(self.electrum.network.Network)
            assert new_Network is not self.electrum.network.Network
            network = new_Network(config, *params, **kwparams)
            #network = self.electrum.network.Network(config, *params, **kwparams)
            #network = mutation.replace(network)
            return network

        mutation = None
        mutation = util.GlobalMutation(constants = constants, Interface = Interface, Network = Network)
        pick_random_server = mutation.replace(self.electrum.network.pick_random_server)
        assert pick_random_server is not self.electrum.network.pick_random_server
        #mutation = util.GlobalMutation(constants = constants)
        #class network_mod:
        #    for name in dir(self.electrum.network):
        #        locals()[name], _ = mutation.replace(getattr(self.electrum.network, name))
        #mutation = util.GlobalMutation(constants = constants, network = network_mod)
        #class interface_mod:
        #    for name in dir(self.electrum.interface):
        #        locals()[name], _ = mutation.replace(getattr(self.electrum.interface, name))
        #mutation = util.GlobalMutation(constants = constants, network = network_mod, interface = interface_mod)
        class blockchain_mod:
            for name in dir(self.electrum.blockchain):
                locals()[name] = mutation.replace(getattr(self.electrum.blockchain, name))
        #mutation = util.GlobalMutation(constants = constants, network = network_mod, interface = interface_mod, blockchain = blockchain_mod)
        #blockchain_mod = mutation.replace(self.electrum.blockchain)
        #assert blockchain_mode is not self.electrum.blockchain
        #mutation = util.GlobalMutation(constants = constants, blockchain = blockchain_mod, interface = interface_mod, network = network_mod)
        mutation = util.GlobalMutation(constants = constants, Interface = Interface, Network = Network, pick_random_server = pick_random_server, blockchain = blockchain_mod)

        class Daemon(self.electrum.daemon.Daemon):
            pass
        Daemon = mutation.replace(Daemon)

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

        await asyncio.get_event_loop().run_in_executor(None, make_network)

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

    async def pos_txid(self, height, pos):
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

    async def tx(self, blockhash, blockheight, txhash, txpos):
        # i briefly glanced at bitcoin-core electrum library 2021 and it appeared that it verified the txid matched the data here
        try:
            hex = await self.network.get_transaction(txhsah)
        except self.electrum.network.UntrustedServerReturnedError as e:
            if not isinstance(e.original_exception, aiorpcx.jsonrpc.RPCError):
                raise
            raise KeyError(txid)
        return bitcoinx.Tx.from_hex(hex)

    async def addr_txids(self, addr):
        # scripthash format is electrum-specific and documented in the electrum project
        raise AssertionError('this might call interface.get_history_for_scripthash')

    async def addr_utxos(self, addr):
        # scripthash format is electrum-specific and documented in the electrum project
        raise AssertionError('this might call interface.listunspect_for_scripthash')

    async def addr_balance(self, addr):
        # scripthash format is electrum-specific and documented in the electrum project
        raise AssertionError('this might call interface.get_balance_for_scripthash')

    async def estimate_fee(self, blocks, probability):
        raise AssertionError('this might call interface.get_fee_histogram / interface.get_relay_fee / interface.get_estimatefee')

    async def broadcast(self, txbytes) -> str:
        raise AssertionError()

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

