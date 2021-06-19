#!/usr/bin/env python3
# Copyright (c) 2021 The Bitcoin developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.
"""Test building avalanche proofs and using them to add avalanche peers."""
import base64
from decimal import Decimal

from test_framework.avatools import (
    create_coinbase_stakes,
    create_stakes,
)
from test_framework.key import ECKey, bytes_to_wif
from test_framework.messages import (
    AvalancheDelegation,
    AvalancheProof,
    FromHex,
)
from test_framework.p2p import P2PInterface
from test_framework.test_framework import BitcoinTestFramework
from test_framework.test_node import ErrorMatch
from test_framework.util import (
    append_config,
    assert_equal,
    wait_until,
    assert_raises_rpc_error,
)

AVALANCHE_MAX_PROOF_STAKES = 1000

PROOF_DUST_THRESHOLD = 1.0
"""Minimum amount per UTXO in a proof (in coins, not in satoshis)"""


def add_interface_node(test_node) -> str:
    """Create a mininode, connect it to test_node, return the nodeid
    of the mininode as registered by test_node.
    """
    n = P2PInterface()
    test_node.add_p2p_connection(n)
    n.wait_for_verack()
    return test_node.getpeerinfo()[-1]['id']


class AvalancheProofTest(BitcoinTestFramework):
    def set_test_params(self):
        self.setup_clean_chain = True
        self.num_nodes = 1
        self.extra_args = [['-enableavalanche=1', '-avacooldown=0'], ]
        self.supports_cli = False
        self.rpc_timeout = 120

    def run_test(self):
        node = self.nodes[0]

        addrkey0 = node.get_deterministic_priv_key()
        blockhashes = node.generatetoaddress(100, addrkey0.address)

        self.log.info(
            "Make build a valid proof and restart the node to use it")
        privkey = ECKey()
        privkey.set(bytes.fromhex(
            "12b004fff7f4b69ef8650e767f18f11ede158148b425660723b9f9a66e61f747"), True)

        def get_hex_pubkey(privkey):
            return privkey.get_pubkey().get_bytes().hex()

        proof_master = get_hex_pubkey(privkey)
        proof_sequence = 11
        proof_expiration = 12
        stakes = create_coinbase_stakes(node, [blockhashes[0]], addrkey0.key)
        proof = node.buildavalancheproof(
            proof_sequence, proof_expiration, proof_master, stakes)

        self.log.info("Test decodeavalancheproof RPC")
        proofobj = FromHex(AvalancheProof(), proof)
        decodedproof = node.decodeavalancheproof(proof)
        assert_equal(decodedproof["sequence"], proof_sequence)
        assert_equal(decodedproof["expiration"], proof_expiration)
        assert_equal(decodedproof["master"], proof_master)
        assert_equal(decodedproof["proofid"], f"{proofobj.proofid:0{64}x}")
        assert_equal(
            decodedproof["limitedid"],
            f"{proofobj.limited_proofid:0{64}x}")
        assert_equal(decodedproof["stakes"][0]["txid"], stakes[0]["txid"])
        assert_equal(decodedproof["stakes"][0]["vout"], stakes[0]["vout"])
        assert_equal(decodedproof["stakes"][0]["height"], stakes[0]["height"])
        assert_equal(
            decodedproof["stakes"][0]["iscoinbase"],
            stakes[0]["iscoinbase"])
        assert_equal(
            decodedproof["stakes"][0]["signature"],
            base64.b64encode(proofobj.stakes[0].sig).decode("ascii"))

        # Invalid hex (odd number of hex digits)
        assert_raises_rpc_error(-22, "Proof must be an hexadecimal string",
                                node.decodeavalancheproof, proof[:-1])
        # Valid hex but invalid proof
        assert_raises_rpc_error(-22, "Proof has invalid format",
                                node.decodeavalancheproof, proof[:-2])

        # Restart the node, making sure it is initially in IBD mode
        minchainwork = int(node.getblockchaininfo()["chainwork"], 16) + 1
        self.restart_node(0, self.extra_args[0] + [
            "-avaproof={}".format(proof),
            "-avamasterkey=cND2ZvtabDbJ1gucx9GWH6XT9kgTAqfb6cotPt5Q5CyxVDhid2EN",
            "-minimumchainwork=0x{:x}".format(minchainwork),
        ])

        self.log.info(
            "The proof verification should be delayed until IBD is complete")
        assert node.getblockchaininfo()["initialblockdownload"] is True
        # Our proof cannot be verified during IBD, so we should have no peer
        assert not node.getavalanchepeerinfo()
        # Mining a few more blocks should cause us to leave IBD
        node.generate(2)
        # Our proof is now verified and our node is added as a peer
        assert node.getblockchaininfo()["initialblockdownload"] is False
        wait_until(lambda: len(node.getavalanchepeerinfo()) == 1, timeout=5)

        if self.is_wallet_compiled():
            self.log.info(
                "A proof using the maximum number of stakes is accepted...")

            new_blocks = node.generate(AVALANCHE_MAX_PROOF_STAKES // 10 + 1)
            # confirm the coinbase UTXOs
            node.generate(101)
            too_many_stakes = create_stakes(
                node, new_blocks, AVALANCHE_MAX_PROOF_STAKES + 1)
            maximum_stakes = too_many_stakes[:-1]
            good_proof = node.buildavalancheproof(
                proof_sequence, proof_expiration,
                proof_master, maximum_stakes)
            peerid1 = add_interface_node(node)
            assert node.addavalanchenode(peerid1, proof_master, good_proof)

            self.log.info(
                "A proof using too many stakes should be rejected...")
            too_many_utxos = node.buildavalancheproof(
                proof_sequence, proof_expiration,
                proof_master, too_many_stakes)
            peerid2 = add_interface_node(node)
            assert not node.addavalanchenode(
                peerid2, proof_master, too_many_utxos)

        self.log.info("Generate delegations for the proof")

        # Stack up a few delegation levels
        def gen_privkey():
            pk = ECKey()
            pk.generate()
            return pk

        delegator_privkey = privkey
        delegation = None
        for _ in range(10):
            delegated_privkey = gen_privkey()
            delegation = node.delegateavalancheproof(
                proof,
                bytes_to_wif(delegator_privkey.get_bytes()),
                get_hex_pubkey(delegated_privkey),
                delegation,
            )
            delegator_privkey = delegated_privkey

        random_privkey = gen_privkey()
        random_pubkey = get_hex_pubkey(random_privkey)

        # Invalid proof
        no_stake = node.buildavalancheproof(
            proof_sequence, proof_expiration, proof_master, [])
        assert_raises_rpc_error(-8, "The proof is invalid",
                                node.delegateavalancheproof,
                                no_stake,
                                bytes_to_wif(privkey.get_bytes()),
                                random_pubkey,
                                )

        # Invalid privkey
        assert_raises_rpc_error(-5, "The private key is invalid",
                                node.delegateavalancheproof,
                                proof,
                                bytes_to_wif(bytes(32)),
                                random_pubkey,
                                )

        # Invalid delegation
        bad_dg = AvalancheDelegation()
        assert_raises_rpc_error(-8, "The supplied delegation is not valid",
                                node.delegateavalancheproof,
                                proof,
                                bytes_to_wif(privkey.get_bytes()),
                                random_pubkey,
                                bad_dg.serialize().hex(),
                                )

        # Wrong privkey, does not match the proof
        assert_raises_rpc_error(-8, "The private key does not match the proof or the delegation",
                                node.delegateavalancheproof,
                                proof,
                                bytes_to_wif(random_privkey.get_bytes()),
                                random_pubkey,
                                )

        # Wrong privkey, match the proof but does not match the delegation
        assert_raises_rpc_error(-8, "The private key does not match the proof or the delegation",
                                node.delegateavalancheproof,
                                proof,
                                bytes_to_wif(privkey.get_bytes()),
                                random_pubkey,
                                delegation,
                                )

        # Test invalid proofs
        dust = node.buildavalancheproof(
            proof_sequence, proof_expiration, proof_master,
            create_coinbase_stakes(node, [blockhashes[0]], addrkey0.key, amount="0"))

        dust_amount = Decimal(f"{PROOF_DUST_THRESHOLD * 0.9999:.4f}")
        dust2 = node.buildavalancheproof(
            proof_sequence, proof_expiration, proof_master,
            create_coinbase_stakes(node, [blockhashes[0]], addrkey0.key,
                                   amount=str(dust_amount)))

        duplicate_stake = node.buildavalancheproof(
            proof_sequence, proof_expiration, proof_master,
            create_coinbase_stakes(node, [blockhashes[0]] * 2, addrkey0.key))

        bad_sig = ("0b000000000000000c0000000000000021030b4c866585dd868a9d62348"
                   "a9cd008d6a312937048fff31670e7e920cfc7a7440105c5f72f5d6da3085"
                   "583e75ee79340eb4eff208c89988e7ed0efb30b87298fa30000000000f20"
                   "52a0100000003000000210227d85ba011276cf25b51df6a188b75e604b3"
                   "8770a462b2d0e9fb2fc839ef5d3faf07f001dd38e9b4a43d07d5d449cc0"
                   "f7d2888d96b82962b3ce516d1083c0e031773487fc3c4f2e38acd1db974"
                   "1321b91a79b82d1c2cfd47793261e4ba003cf5")

        self.log.info("Check the verifyavalancheproof RPC")

        assert_raises_rpc_error(-8, "Proof must be an hexadecimal string",
                                    node.verifyavalancheproof, "f00")
        assert_raises_rpc_error(-8, "Proof has invalid format",
                                    node.verifyavalancheproof, "f00d")

        def check_verifyavalancheproof_failure(proof, message):
            assert_raises_rpc_error(-8, "The proof is invalid: " + message,
                                    node.verifyavalancheproof, proof)

        check_verifyavalancheproof_failure(no_stake, "no-stake")
        check_verifyavalancheproof_failure(dust, "amount-below-dust-threshold")
        check_verifyavalancheproof_failure(duplicate_stake, "duplicated-stake")
        check_verifyavalancheproof_failure(bad_sig, "invalid-signature")
        if self.is_wallet_compiled():
            check_verifyavalancheproof_failure(
                too_many_utxos, "too-many-utxos")

        # Good proof
        assert node.verifyavalancheproof(proof)

        self.log.info("Bad proof should be rejected at startup")

        self.stop_node(0)

        node.assert_start_raises_init_error(
            self.extra_args[0] + [
                "-avasessionkey=0",
            ],
            expected_msg="Error: the avalanche session key is invalid",
        )

        node.assert_start_raises_init_error(
            self.extra_args[0] + [
                "-avaproof={}".format(proof),
            ],
            expected_msg="Error: the avalanche master key is missing for the avalanche proof",
        )

        node.assert_start_raises_init_error(
            self.extra_args[0] + [
                "-avaproof={}".format(proof),
                "-avamasterkey=0",
            ],
            expected_msg="Error: the avalanche master key is invalid",
        )

        def check_proof_init_error(proof, message):
            node.assert_start_raises_init_error(
                self.extra_args[0] + [
                    "-avaproof={}".format(proof),
                    "-avamasterkey=cND2ZvtabDbJ1gucx9GWH6XT9kgTAqfb6cotPt5Q5CyxVDhid2EN",
                ],
                expected_msg="Error: " + message,
            )

        check_proof_init_error(no_stake,
                               "the avalanche proof has no stake")
        check_proof_init_error(dust,
                               "the avalanche proof stake is too low")
        check_proof_init_error(dust2,
                               "the avalanche proof stake is too low")
        check_proof_init_error(duplicate_stake,
                               "the avalanche proof has duplicated stake")
        check_proof_init_error(bad_sig,
                               "the avalanche proof has invalid stake signatures")
        if self.is_wallet_compiled():
            # The too many utxos case creates a proof which is that large that it
            # cannot fit on the command line
            append_config(node.datadir, ["avaproof={}".format(too_many_utxos)])
            node.assert_start_raises_init_error(
                self.extra_args[0] + [
                    "-avamasterkey=cND2ZvtabDbJ1gucx9GWH6XT9kgTAqfb6cotPt5Q5CyxVDhid2EN",
                ],
                expected_msg="Error: the avalanche proof has too many utxos",
                match=ErrorMatch.PARTIAL_REGEX,
            )


if __name__ == '__main__':
    AvalancheProofTest().main()
