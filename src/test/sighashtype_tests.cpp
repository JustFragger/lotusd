// Copyright (c) 2018-2019 The Bitcoin developers
// Distributed under the MIT software license, see the accompanying
// file COPYING or http://www.opensource.org/licenses/mit-license.php.

#include <script/sighashtype.h>

#include <streams.h>

#include <test/util/setup_common.h>

#include <boost/test/unit_test.hpp>

#include <set>

BOOST_FIXTURE_TEST_SUITE(sighashtype_tests, BasicTestingSetup)

static void CheckSigHashType(SigHashType t, BaseSigHashType baseType,
                             bool isDefined, uint32_t forkValue, bool hasForkId,
                             bool hasLotus, uint32_t unusedBits,
                             bool hasAnyoneCanPay) {
    BOOST_CHECK(t.getBaseType() == baseType);
    BOOST_CHECK_EQUAL(t.isDefined(), isDefined);
    BOOST_CHECK_EQUAL(t.getForkValue(), forkValue);
    BOOST_CHECK_EQUAL(t.getUnusedBits(), unusedBits);
    BOOST_CHECK_EQUAL(t.hasForkId(), hasForkId);
    BOOST_CHECK_EQUAL(t.hasLotus(), hasLotus);
    BOOST_CHECK_EQUAL(t.hasAnyoneCanPay(), hasAnyoneCanPay);
}

BOOST_AUTO_TEST_CASE(sighash_construction_test) {
    // Check default values.
    CheckSigHashType(SigHashType(), BaseSigHashType::ALL, true, 0, false, false,
                     0, false);

    // Check all possible permutations.
    std::set<BaseSigHashType> baseTypes{
        BaseSigHashType::UNSUPPORTED, BaseSigHashType::ALL,
        BaseSigHashType::NONE, BaseSigHashType::SINGLE};
    std::set<uint32_t> forkValues{0, 1, 0x123456, 0xfedcba, 0xffffff};
    std::set<uint32_t> algorithmValues{SIGHASH_LEGACY, SIGHASH_FORKID,
                                       SIGHASH_LOTUS};
    std::set<bool> anyoneCanPayFlagValues{false, true};

    for (BaseSigHashType baseType : baseTypes) {
        for (uint32_t forkValue : forkValues) {
            for (uint32_t algorithm : algorithmValues) {
                for (bool hasAnyoneCanPay : anyoneCanPayFlagValues) {
                    SigHashType t = SigHashType()
                                        .withBaseType(baseType)
                                        .withForkValue(forkValue)
                                        .withAlgorithm(algorithm)
                                        .withAnyoneCanPay(hasAnyoneCanPay);
                    bool hasForkId = algorithm == SIGHASH_FORKID;
                    bool hasLotus = algorithm == SIGHASH_LOTUS;

                    bool isDefined = baseType != BaseSigHashType::UNSUPPORTED;
                    CheckSigHashType(t, baseType, isDefined, forkValue,
                                     hasForkId, hasLotus, 0, hasAnyoneCanPay);

                    // Also check all possible alterations.
                    CheckSigHashType(t.withAlgorithm(hasForkId
                                                         ? SIGHASH_FORKID
                                                         : SIGHASH_LEGACY),
                                     baseType, isDefined, forkValue, hasForkId,
                                     false, 0, hasAnyoneCanPay);
                    CheckSigHashType(t.withAlgorithm(!hasForkId
                                                         ? SIGHASH_FORKID
                                                         : SIGHASH_LEGACY),
                                     baseType, isDefined, forkValue, !hasForkId,
                                     false, 0, hasAnyoneCanPay);
                    CheckSigHashType(t.withAnyoneCanPay(hasAnyoneCanPay),
                                     baseType, isDefined, forkValue, hasForkId,
                                     hasLotus, 0, hasAnyoneCanPay);
                    CheckSigHashType(t.withAnyoneCanPay(!hasAnyoneCanPay),
                                     baseType, isDefined, forkValue, hasForkId,
                                     hasLotus, 0, !hasAnyoneCanPay);

                    for (BaseSigHashType newBaseType : baseTypes) {
                        bool isNewDefined =
                            newBaseType != BaseSigHashType::UNSUPPORTED;
                        CheckSigHashType(t.withBaseType(newBaseType),
                                         newBaseType, isNewDefined, forkValue,
                                         hasForkId, hasLotus, 0,
                                         hasAnyoneCanPay);
                    }

                    for (uint32_t newForkValue : forkValues) {
                        CheckSigHashType(t.withForkValue(newForkValue),
                                         baseType, isDefined, newForkValue,
                                         hasForkId, hasLotus, 0,
                                         hasAnyoneCanPay);
                    }
                }
            }
        }
    }
}

BOOST_AUTO_TEST_CASE(sighash_serialization_test) {
    std::set<uint32_t> forkValues{0, 1, 0xab1fe9, 0xc81eea, 0xffffff};

    // Test all possible sig hash values embedded in signatures.
    for (uint32_t sigHashType = 0x00; sigHashType <= 0xff; sigHashType++) {
        for (uint32_t forkValue : forkValues) {
            uint32_t rawType = sigHashType | (forkValue << 8);

            uint32_t baseType = rawType & SIGHASH_BASE_TYPE_MASK;
            uint32_t unused = rawType & SIGHASH_UNUSED_MASK;
            bool hasForkId =
                (rawType & SIGHASH_ALGORITHM_MASK) == SIGHASH_FORKID;
            bool hasLotus =
                (rawType & SIGHASH_ALGORITHM_MASK) == SIGHASH_LOTUS;
            bool hasAnyoneCanPay = (rawType & SIGHASH_ANYONECANPAY) != 0;

            uint32_t noflag =
                sigHashType & ~(SIGHASH_ALGORITHM_MASK | SIGHASH_ANYONECANPAY);
            bool isDefined = (noflag != 0) && (noflag <= SIGHASH_SINGLE);
            if ((sigHashType & 0x20) && !(sigHashType & SIGHASH_FORKID)) {
                // Lotus sighash without FORKID is invalid
                isDefined = false;
            }

            const SigHashType tbase(rawType);

            // Check deserialization.
            CheckSigHashType(tbase, BaseSigHashType(baseType), isDefined,
                             forkValue, hasForkId, hasLotus, unused,
                             hasAnyoneCanPay);

            // Check raw value.
            BOOST_CHECK_EQUAL(tbase.getRawSigHashType(), rawType);

            // Check serialization/deserialization.
            uint32_t unserializedOutput;
            (CDataStream(SER_DISK, 0) << tbase) >> unserializedOutput;
            BOOST_CHECK_EQUAL(unserializedOutput, rawType);
        }
    }
}

BOOST_AUTO_TEST_SUITE_END()
