#!/usr/bin/env python3
# Copyright (c) 2021 The Logos Foundation
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.

from test_framework.blocktools import (
    create_coinbase,
    prepare_block,
)
from test_framework.messages import CBlock, uint256_from_compact
from test_framework.script import (
    CScript,
    OP_HASH160,
    OP_EQUAL,
)
from test_framework.p2p import (
    P2PDataStore,
)
from test_framework.test_framework import BitcoinTestFramework
from test_framework.util import assert_equal


ACTIVATION_TIME = 2000000000


class NewEpochHashTest(BitcoinTestFramework):
    def set_test_params(self):
        self.num_nodes = 1
        self.extra_args = [[
            '-whitelist=noban@127.0.0.1',
            f'-exodusactivationtime={ACTIVATION_TIME}',
        ]]

    def fail_block(self, block, reject_reason, force_send=False):
        self.nodes[0].p2p.send_blocks_and_test([block], self.nodes[0], success=False, force_send=force_send, reject_reason=reject_reason)

    def block_from_template(self, block_template):
        coinbase = create_coinbase(block_template['height'])
        coinbase.vout[1].scriptPubKey = CScript([OP_HASH160, bytes(20), OP_EQUAL])
        block = CBlock()
        block.hashPrevBlock = int(block_template['previousblockhash'], 16)
        block.nBits = 0x207fffff
        block.nTime = block_template['mintime']
        block.nHeight = block_template['height']
        block.hashEpochBlock = int(block_template['epochblockhash'], 16)
        block.vtx = [coinbase]
        return block

    def run_test(self):
        node = self.nodes[0]
        node.add_p2p_connection(P2PDataStore())

        # Block hash must be below this number to become an epoch block in the new epoch mechanism
        epoch_target = uint256_from_compact(0x207fffff) // 5040

        # OP_TRUE in P2SH
        address = node.decodescript('51')['p2sh']

        # Check epoch hash is 0 for the first 20 blocks
        for height in range(201, 221):
            block_template = node.getblocktemplate()
            assert_equal(block_template['epochblockhash'], '00' * 32)
            block = self.block_from_template(block_template)
            block.hashEpochBlock = 0
            prepare_block(block)
            node.p2p.send_blocks_and_test([block], node)
            del block
    
        # Move 7 block before end of legacy epoch
        node.generatetoaddress(4812, address)
        assert_equal(node.getblockcount(), 5032)

        self.log.info("Approach to just before upgrade activation")
        # Move our clock to the upgrade time so we will accept future-timestamped blocks.
        node.setmocktime(ACTIVATION_TIME)

        # Mine five blocks with timestamp starting at ACTIVATION_TIME-1
        for i in range(-1, 5):
            block_template = node.getblocktemplate()
            assert_equal(block_template['epochblockhash'], '00' * 32)
            block = self.block_from_template(block_template)
            block.nTime = ACTIVATION_TIME + i
            prepare_block(block)
            node.p2p.send_blocks_and_test([block], node)

        # We make block 5038 a lucky block, but new epoch mechanism not yet in place
        block_template = node.getblocktemplate()
        assert_equal(block_template['epochblockhash'], '00' * 32)
        block = self.block_from_template(block_template)
        prepare_block(block)
        while block.sha256 > epoch_target:
            block.nNonce += 1
            block.rehash()

        # Now just 1 block is missing for the end of legacy epoch
        assert_equal(node.getblockcount(), 5038)

        # The last block of the legacy epoch activates the new epoch mechanism
        block_template = node.getblocktemplate()
        # Previous block is lucky, but new epoch mechanism wasn't activated yet
        assert_equal(block_template['epochblockhash'], '00' * 32)
        activation_block = self.block_from_template(block_template)
        prepare_block(activation_block)
        node.p2p.send_blocks_and_test([activation_block], node)
        assert_equal(node.getblockcount(), 5039)

        # New rules activated, therefore, block 5040 still has epoch 0
        block_template = node.getblocktemplate()
        assert_equal(block_template['epochblockhash'], '00' * 32)

        # Find rare epoch hash (<1s on regtest):
        epoch_block = self.block_from_template(block_template)
        prepare_block(epoch_block)
        while epoch_block.sha256 > epoch_target:
            epoch_block.nNonce += 1
            epoch_block.rehash()
        node.p2p.send_blocks_and_test([epoch_block], node)

        # Block 5041 now has the new epoch hash
        block_template = node.getblocktemplate()
        assert_equal(block_template['epochblockhash'], epoch_block.hash)
        block = self.block_from_template(block_template)
        # Make sure block 5041 is *not* an epoch block
        prepare_block(block)
        while block.sha256 <= epoch_target:
            block.nNonce += 1
            block.rehash()
        node.p2p.send_blocks_and_test([block], node)

        # Block 5042 still requires block 5040's hash
        assert_equal(block_template['epochblockhash'], epoch_block.hash)

        # Reorg chain; we make the activation block lucky
        node.invalidateblock(activation_block.hash)
        assert_equal(node.getblockcount(), 5038)
        block_template = node.getblocktemplate()
        # Previous block was lucky, but new epoch mechanism wasn't activated yet
        assert_equal(block_template['epochblockhash'], '00' * 32)
        activation_block = self.block_from_template(block_template)
        prepare_block(activation_block)
        while activation_block.sha256 > epoch_target:
            activation_block.nNonce += 1
            activation_block.rehash()
        node.p2p.send_blocks_and_test([activation_block], node)

        # Epoch hash is now the hash of the (lucky) activation block
        block_template = node.getblocktemplate()
        assert_equal(block_template['epochblockhash'], activation_block.hash)
        block = self.block_from_template(block_template)
        prepare_block(block)
        # Make sure block 5040 is *not* an epoch block
        while block.sha256 <= epoch_target:
            block.nNonce += 1
            block.rehash()
        node.p2p.send_blocks_and_test([block], node)

        # Block 5041 still requires block 5039's hash
        block_template = node.getblocktemplate()
        assert_equal(block_template['epochblockhash'], activation_block.hash)


if __name__ == '__main__':
    NewEpochHashTest().main()
