// Copyright 2014-2023 Bloomberg Finance L.P.
// SPDX-License-Identifier: Apache-2.0
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

// bmqp_confirmmessageiterator.cpp                                    -*-C++-*-
#include <bmqp_confirmmessageiterator.h>

#include <bmqscm_version.h>
// BDE
#include <bdlbb_blob.h>
#include <bsl_iostream.h>
#include <bsls_performancehint.h>

namespace BloombergLP {
namespace bmqp {

// ----------------------------
// class ConfirmMessageIterator
// ----------------------------

void ConfirmMessageIterator::copyFrom(const ConfirmMessageIterator& src)
{
    d_blobIter      = src.d_blobIter;
    d_advanceLength = src.d_advanceLength;

    if (!src.d_header.isSet()) {
        d_header.reset();
        d_message.reset();
    }
    else {
        d_header.reset(src.d_header.blob(),
                       src.d_header.position(),
                       src.d_header.length(),
                       true,
                       false);

        if (src.d_message.isSet()) {
            d_message.reset(src.d_message.blob(),
                            src.d_message.position(),
                            d_header->perMessageWords() *
                                Protocol::k_WORD_SIZE,
                            true,
                            false);
        }
    }
}

int ConfirmMessageIterator::next()
{
    enum RcEnum {
        // Value for the various RC error categories
        rc_HAS_NEXT = 1  // There is another message after this
                         // one
        ,
        rc_AT_END = 0  // This is the last message
        ,
        rc_INVALID = -1  // The Iterator is an invalid state
        ,
        rc_NOT_ENOUGH_BYTES = -2  // The number of bytes in the blob is
                                  // less than the payload size of the
                                  // message declared in the header
        ,
        rc_INVALID_ADVANCE_LENGTH = -3  // Advance length is not positive
    };

    if (BSLS_PERFORMANCEHINT_PREDICT_UNLIKELY(!isValid())) {
        BSLS_PERFORMANCEHINT_UNLIKELY_HINT;
        return rc_INVALID;  // RETURN
    }

    if (d_blobIter.advance(d_advanceLength) == false) {
        d_header.reset();
        return rc_AT_END;  // RETURN
    }

    // Update 'advanceLength' for next iteration.
    // NOTE: We do it at every 'next' (even if the value is always going to be
    //       the same) because in 'reset()', we first set it to the size of the
    //       'ConfirmHeader', since first 'next()' should move beyond the
    //       'ConfirmHeader'.
    d_advanceLength = d_header->perMessageWords() * Protocol::k_WORD_SIZE;

    // Validation: must ensure that 'd_advanceLength > 0' after update, or
    // iteration process via 'next()' might be infinite
    if (BSLS_PERFORMANCEHINT_PREDICT_UNLIKELY(d_advanceLength == 0)) {
        BSLS_PERFORMANCEHINT_UNLIKELY_HINT;
        return rc_INVALID_ADVANCE_LENGTH;  // RETURN
    }

    // Update ConfirmMessage, supporting protocol evolution by reading as many
    // bytes as the header declares (and not as many as the size of the struct)
    d_message.reset(d_blobIter.blob(),
                    d_blobIter.position(),
                    d_header->perMessageWords() * Protocol::k_WORD_SIZE,
                    true,
                    false);

    if (BSLS_PERFORMANCEHINT_PREDICT_UNLIKELY(!d_message.isSet())) {
        BSLS_PERFORMANCEHINT_UNLIKELY_HINT;
        return rc_NOT_ENOUGH_BYTES;  // RETURN
    }

    return rc_HAS_NEXT;
}

int ConfirmMessageIterator::reset(const bdlbb::Blob* blob,
                                  const EventHeader& eventHeader)
{
    // PRECONDITIONS
    BSLS_ASSERT_SAFE(blob);

    enum RcEnum {
        // Value for the various RC error categories
        rc_SUCCESS = 0  // Success
        ,
        rc_INVALID_EVENTHEADER = -1  // The blob doesn't contain a complete
                                     // EventHeader, or is not followed by a
                                     // ConfirmHeader
        ,
        rc_INVALID_CONFIRMHEADER = -2  // The blob doesn't contain a complete
                                       // ConfirmHeader
        ,
        rc_NOT_ENOUGH_BYTES = -3  // The number of bytes in the blob is
                                  // less than the header size declared
                                  // in the header
    };

    d_blobIter.reset(blob, bmqu::BlobPosition(), blob->length(), true);

    // Skip the EventHeader to point to the ConfirmHeader
    bool rc = d_blobIter.advance(eventHeader.headerWords() *
                                 Protocol::k_WORD_SIZE);

    if (BSLS_PERFORMANCEHINT_PREDICT_UNLIKELY(!rc)) {
        BSLS_PERFORMANCEHINT_UNLIKELY_HINT;
        // Set the iterator to invalid state
        d_header.reset();
        return rc_INVALID_EVENTHEADER;  // RETURN
    }

    // Read ConfirmHeader, supporting protocol evolution by reading up to size
    // of the struct bytes (-1 parameter), and then resizing the proxy to match
    // the size declared in the header
    //
    // NOTE: not sure the resize is actually really needed, if we consider all
    //       new fields will be defaulted to zero and we won't need to check
    //       whether they were present or not).
    d_header.reset(blob,
                   d_blobIter.position(),
                   -ConfirmHeader::k_MIN_HEADER_SIZE,
                   true,
                   false);

    if (BSLS_PERFORMANCEHINT_PREDICT_UNLIKELY(!d_header.isSet())) {
        BSLS_PERFORMANCEHINT_UNLIKELY_HINT;
        return rc_INVALID_CONFIRMHEADER;  // RETURN
    }

    const int headerSize = d_header->headerWords() * Protocol::k_WORD_SIZE;
    if (BSLS_PERFORMANCEHINT_PREDICT_UNLIKELY(
            headerSize < ConfirmHeader::k_MIN_HEADER_SIZE)) {
        BSLS_PERFORMANCEHINT_UNLIKELY_HINT;
        // Header is declaring less bytes than expected, probably this is
        // because header is malformed.
        // Explicitly reset the proxy so that isValid() returns false.
        d_header.reset();
        return rc_INVALID_CONFIRMHEADER;  // RETURN
    }

    if (BSLS_PERFORMANCEHINT_PREDICT_UNLIKELY(headerSize >
                                              d_blobIter.remaining())) {
        BSLS_PERFORMANCEHINT_UNLIKELY_HINT;
        // The header is declaring more bytes than are left in the blob.
        // Explicitly reset the proxy so that isValid() returns false.
        d_header.reset();
        return rc_NOT_ENOUGH_BYTES;  // RETURN
    }

    d_header.resize(headerSize);
    if (BSLS_PERFORMANCEHINT_PREDICT_UNLIKELY(!d_header.isSet())) {
        BSLS_PERFORMANCEHINT_UNLIKELY_HINT;
        return rc_INVALID_CONFIRMHEADER;  // RETURN
    }

    // Reset the current message
    d_message.reset();

    // Below code snippet is needed so that 'next()' works seamlessly during
    // first invocation too, by skipping over the 'ConfirmHeader'.
    d_advanceLength = headerSize;

    return rc_SUCCESS;
}

void ConfirmMessageIterator::dumpBlob(bsl::ostream& stream)
{
    static const int k_MAX_BYTES_DUMP = 128;

    // For now, print only the beginning of the blob.. we may later on print
    // also the bytes around the current position
    if (d_blobIter.blob()) {
        stream << bmqu::BlobStartHexDumper(d_blobIter.blob(),
                                           k_MAX_BYTES_DUMP);
    }
    else {
        stream << "/no blob/";
    }
}

}  // close package namespace
}  // close enterprise namespace
