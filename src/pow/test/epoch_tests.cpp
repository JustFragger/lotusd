// Copyright (c) 2021 The Logos Foundation
// Distributed under the MIT software license, see the accompanying
// file COPYING or http://www.opensource.org/licenses/mit-license.php.

#include <chain.h>
#include <chainparams.h>
#include <config.h>
#include <consensus/activation.h>
#include <pow/pow.h>
#include <primitives/blockhash.h>

#include <test/util/setup_common.h>

#include <boost/test/unit_test.hpp>

BOOST_FIXTURE_TEST_SUITE(epoch_tests, BasicTestingSetup)

static void SetMTP(std::array<CBlockIndex, 12> &blocks, int64_t mtp) {
    size_t len = blocks.size();

    for (size_t i = 0; i < len; ++i) {
        blocks[i].nTime = mtp + (i - (len / 2));
    }

    BOOST_CHECK_EQUAL(blocks.back().GetMedianTimePast(), mtp);
}

static BlockHash BKH(std::string str) {
    return BlockHash(uint256S(str));
}

BOOST_AUTO_TEST_CASE(epoch_test) {
    DummyConfig regConfig(CBaseChainParams::REGTEST);
    const Consensus::Params &regParams =
        regConfig.GetChainParams().GetConsensus();
    // epoch hash for regtest min PoW
    BOOST_CHECK(!CheckProofOfWork(
        BKH("7fffff0000000000000000000000000000000000000000000000000000000001"),
        0x207fffff, regParams));
    BOOST_CHECK(CheckProofOfWork(
        BKH("7fffff0000000000000000000000000000000000000000000000000000000000"),
        0x207fffff, regParams));
    BOOST_CHECK(!IsEpochBlockHash(
        BKH("00068067f97f97f97f97f97f97f97f97f97f97f97f97f97f97f97f97f97f97fa"),
        0x207fffff));
    BOOST_CHECK(IsEpochBlockHash(
        BKH("00068067f97f97f97f97f97f97f97f97f97f97f97f97f97f97f97f97f97f97f9"),
        0x207fffff));

    DummyConfig mainConfig(CBaseChainParams::MAIN);
    const Consensus::Params &mainParams =
        mainConfig.GetChainParams().GetConsensus();
    // epoch hash for mainnet min pow
    BOOST_CHECK(!CheckProofOfWork(
        BKH("0000000010000000000000000000000000000000000000000000000000000001"),
        0x1c100000, mainParams));
    BOOST_CHECK(CheckProofOfWork(
        BKH("0000000010000000000000000000000000000000000000000000000000000000"),
        0x1c100000, mainParams));
    BOOST_CHECK(!IsEpochBlockHash(
        BKH("000000000000d00d00d00d00d00d00d00d00d00d00d00d00d00d00d00d00d00e"),
        0x1c100000));
    BOOST_CHECK(IsEpochBlockHash(
        BKH("000000000000d00d00d00d00d00d00d00d00d00d00d00d00d00d00d00d00d00d"),
        0x1c100000));
    // epoch hash for bits 0x1c013b00
    BOOST_CHECK(!CheckProofOfWork(
        BKH("00000000013b0000000000000000000000000000000000000000000000000001"),
        0x1c013b00, mainParams));
    BOOST_CHECK(CheckProofOfWork(
        BKH("00000000013b0000000000000000000000000000000000000000000000000000"),
        0x1c013b00, mainParams));
    BOOST_CHECK(!IsEpochBlockHash(
        BKH("0000000000001000000000000000000000000000000000000000000000000001"),
        0x1c013b00));
    BOOST_CHECK(IsEpochBlockHash(
        BKH("0000000000001000000000000000000000000000000000000000000000000000"),
        0x1c013b00));
}

BOOST_AUTO_TEST_CASE(get_next_epoch_block_hash_test) {
    DummyConfig config(CBaseChainParams::MAIN);
    const Consensus::Params &params = config.GetChainParams().GetConsensus();
    // Check activation
    std::array<CBlockIndex, 12> blocks;
    for (size_t i = 1; i < blocks.size(); ++i) {
        blocks[i].pprev = &blocks[i - 1];
    }
    const uint256 prevEpochHash = uint256S(
        "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef");
    const uint256 aboveEpochHash = uint256S(
        "0000000000001000000000000000000000000000000000000000000000000001");
    const uint256 enoughEpochHash = uint256S(
        "0000000000001000000000000000000000000000000000000000000000000000");
    blocks.back().hashEpochBlock = prevEpochHash;
    const auto activation =
        gArgs.GetArg("-exodusactivationtime", params.exodusActivationTime);

    // before activation
    SetMTP(blocks, activation - 1);
    BOOST_CHECK(!IsExodusEnabled(params, &blocks.back()));
    CBlockHeader header;
    header.nBits = 0x1c013b00;
    // before block 5040, lucky hash doesn't result in new epoch
    header.hashPrevBlock = BlockHash(enoughEpochHash);
    header.nHeight = 5039;
    BOOST_CHECK_EQUAL(prevEpochHash,
                      GetNextEpochBlockHash(&header, &blocks.back(), params));
    // after block 5040, unlucky hash doesn't prevent new epoch
    header.nHeight = 5040;
    header.hashPrevBlock = BlockHash(aboveEpochHash);
    BOOST_CHECK_EQUAL(aboveEpochHash,
                      GetNextEpochBlockHash(&header, &blocks.back(), params));

    // after activation
    SetMTP(blocks, activation);
    BOOST_CHECK(IsExodusEnabled(params, &blocks.back()));
    // before block 5040, prev hash not sufficient for new epoch
    header.hashPrevBlock = BlockHash(aboveEpochHash);
    header.nHeight = 5039;
    BOOST_CHECK_EQUAL(prevEpochHash,
                      GetNextEpochBlockHash(&header, &blocks.back(), params));
    // after block 5040, prev hash still not sufficient for new epoch
    header.nHeight = 5040;
    BOOST_CHECK_EQUAL(prevEpochHash,
                      GetNextEpochBlockHash(&header, &blocks.back(), params));
    // before block 5040, prev hash sufficient for new epoch
    header.hashPrevBlock = BlockHash(enoughEpochHash);
    header.nHeight = 5039;
    BOOST_CHECK_EQUAL(enoughEpochHash,
                      GetNextEpochBlockHash(&header, &blocks.back(), params));
    // after block 5040, prev hash sufficient for new epoch
    header.hashPrevBlock = BlockHash(enoughEpochHash);
    header.nHeight = 5040;
    BOOST_CHECK_EQUAL(enoughEpochHash,
                      GetNextEpochBlockHash(&header, &blocks.back(), params));
}

BOOST_AUTO_TEST_SUITE_END()
