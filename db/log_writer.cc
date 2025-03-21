//  Copyright (c) 2011-present, Facebook, Inc.  All rights reserved.
//  This source code is licensed under both the GPLv2 (found in the
//  COPYING file in the root directory) and Apache 2.0 License
//  (found in the LICENSE.Apache file in the root directory).
//
// Copyright (c) 2011 The LevelDB Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file. See the AUTHORS file for names of contributors.

#include "db/log_writer.h"

#include <cstdint>

#include "file/writable_file_writer.h"
#include "rocksdb/env.h"
#include "rocksdb/io_status.h"
#include "util/coding.h"
#include "util/crc32c.h"
#include "util/udt_util.h"
#include "util/xxhash.h"
#include "rocksdb/write_batch.h"

namespace ROCKSDB_NAMESPACE {
namespace log {

Writer::Writer(std::unique_ptr<WritableFileWriter>&& dest, uint64_t log_number,
               bool recycle_log_files, bool manual_flush,
               CompressionType compression_type)
    : dest_(std::move(dest)),
      block_offset_(0),
      log_number_(log_number),
      recycle_log_files_(recycle_log_files),
      manual_flush_(manual_flush),
      compression_type_(compression_type),
      compress_(nullptr) {
  for (int i = 0; i <= kMaxRecordType; i++) {
    char t = static_cast<char>(i);
    type_crc_[i] = crc32c::Value(&t, 1);
  }
  log_offset_ = 0;
  memtable_as_log_index_ = false;
}

Writer::~Writer() {
  if (dest_) {
    WriteBuffer().PermitUncheckedError();
    Close().PermitUncheckedError();
  }
  if (compress_) {
    delete compress_;
  }
}

IOStatus Writer::WriteBuffer() {
  if (dest_->seen_error()) {
    return IOStatus::IOError("Seen error. Skip writing buffer.");
  }
  return dest_->Flush();
}

IOStatus Writer::Close() {
  IOStatus s;
  if (dest_) {
    if (memtable_as_log_index_) {
      // fault_injection_fs: TestFSWritableFile::Flush dose not flush
      // internal buffer, which flush internal buffer is `Sync`
      s = dest_->Sync(true); // Flush + Sync
      if (!s.ok()) {
        fprintf(stderr, "ERR: %s:%d: Writer::Close.Sync(%s) = %s\n",
                __FILE__, __LINE__, dest_->file_name().c_str(),
                s.ToString().c_str());
      }
      s = dest_->writable_file()->Truncate(log_offset_, IOOptions(), nullptr);
    }
    s = dest_->Close();
    dest_.reset();
  }
  return s;
}

void Writer::TruncateForMmap(FileSystem& fs, size_t file_size) {
  auto& fname = dest_->file_name();
  auto wfile = dest_->writable_file();
  // wfile->Truncate will change wfile->GetFileSize() which is really the
  // current offset of wfile, wfile->Append() also update it, this is not
  // like posix fs api: ftruncate does not affect file offset!
  // So we use fs.Truncate(fname) which will not affect GetFileSize(), but
  // fs.Truncate is "NotImplemented", so we call SetFileSize() at the end.
  // auto s = fs.Truncate(fname, file_size, IOOptions(), nullptr);
  if (file_size > (8ull<<40)) {
    fprintf(stderr,
      "WARN: Writer::TruncateForMmap: file_size %.6f TiB, reset to 32 GiB\n",
      file_size / double(1ull<<40));
    file_size = 32ull << 30; // 32G
  }
  if (0 == file_size) {
    file_size = size_t(1) << 30; // 1G
  }
  auto s = wfile->Truncate(file_size, IOOptions(), nullptr);
  TERARK_VERIFY_S(s.ok(), "truncate %s, %s", fname, s.ToString());
  mmap_reader_ = ReadonlyFileMmap::New(&s, fs, log_number_, fname);
  TERARK_VERIFY_S(s.ok(), "make mmap %s, %s", fname, s.ToString());
  TERARK_VERIFY_EQ(mmap_reader_->size_, file_size);
  wfile->SetFileSize(0); // this is just File Offset for Append
}

IOStatus Writer::AddRecord(const Slice& slice,
                           Env::IOPriority rate_limiter_priority) {
  const char* ptr = slice.data();
  size_t left = slice.size();

  if (memtable_as_log_index_) {
    IOStatus s = EmitPhysicalRecord(kFullType, ptr, left, rate_limiter_priority);
    if (!manual_flush_ && s.ok()) {
      s = dest_->Flush();
    }
    return s;
  }

  // Header size varies depending on whether we are recycling or not.
  const int header_size =
      recycle_log_files_ ? kRecyclableHeaderSize : kHeaderSize;

  // Fragment the record if necessary and emit it.  Note that if slice
  // is empty, we still want to iterate once to emit a single
  // zero-length record
  bool begin = true;
  int compress_remaining = 0;
  bool compress_start = false;
  if (compress_) {
    compress_->Reset();
    compress_start = true;
  }

  IOStatus s;
  do {
    const int64_t leftover = kBlockSize - block_offset_;
    assert(leftover >= 0);
    if (leftover < header_size) {
      // Switch to a new block
      if (leftover > 0) {
        // Fill the trailer (literal below relies on kHeaderSize and
        // kRecyclableHeaderSize being <= 11)
        assert(header_size <= 11);
        s = dest_->Append(Slice("\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00",
                                static_cast<size_t>(leftover)),
                          0 /* crc32c_checksum */, rate_limiter_priority);
        if (!s.ok()) {
          break;
        }
      }
      block_offset_ = 0;
    }

    // Invariant: we never leave < header_size bytes in a block.
    assert(static_cast<int64_t>(kBlockSize - block_offset_) >= header_size);

    const size_t avail = kBlockSize - block_offset_ - header_size;

    // Compress the record if compression is enabled.
    // Compress() is called at least once (compress_start=true) and after the
    // previous generated compressed chunk is written out as one or more
    // physical records (left=0).
    if (compress_ && (compress_start || left == 0)) {
      compress_remaining = compress_->Compress(slice.data(), slice.size(),
                                               compressed_buffer_.get(), &left);

      if (compress_remaining < 0) {
        // Set failure status
        s = IOStatus::IOError("Unexpected WAL compression error");
        s.SetDataLoss(true);
        break;
      } else if (left == 0) {
        // Nothing left to compress
        if (!compress_start) {
          break;
        }
      }
      compress_start = false;
      ptr = compressed_buffer_.get();
    }

    const size_t fragment_length = (left < avail) ? left : avail;

    RecordType type;
    const bool end = (left == fragment_length && compress_remaining == 0);
    if (begin && end) {
      type = recycle_log_files_ ? kRecyclableFullType : kFullType;
    } else if (begin) {
      type = recycle_log_files_ ? kRecyclableFirstType : kFirstType;
    } else if (end) {
      type = recycle_log_files_ ? kRecyclableLastType : kLastType;
    } else {
      type = recycle_log_files_ ? kRecyclableMiddleType : kMiddleType;
    }

    s = EmitPhysicalRecord(type, ptr, fragment_length, rate_limiter_priority);
    ptr += fragment_length;
    left -= fragment_length;
    begin = false;
  } while (s.ok() && (left > 0 || compress_remaining > 0));

  if (s.ok()) {
    if (!manual_flush_) {
      s = dest_->Flush(rate_limiter_priority);
    }
  }

  return s;
}

IOStatus Writer::AddCompressionTypeRecord() {
  // Should be the first record
  assert(block_offset_ == 0);

  if (memtable_as_log_index_) {
    return IOStatus::OK();
  }

  if (compression_type_ == kNoCompression) {
    // No need to add a record
    return IOStatus::OK();
  }

  CompressionTypeRecord record(compression_type_);
  std::string encode;
  record.EncodeTo(&encode);
  IOStatus s =
      EmitPhysicalRecord(kSetCompressionType, encode.data(), encode.size());
  if (s.ok()) {
    if (!manual_flush_) {
      s = dest_->Flush();
    }
    // Initialize fields required for compression
    const size_t max_output_buffer_len =
        kBlockSize - (recycle_log_files_ ? kRecyclableHeaderSize : kHeaderSize);
    CompressionOptions opts;
    constexpr uint32_t compression_format_version = 2;
    compress_ = StreamingCompress::Create(compression_type_, opts,
                                          compression_format_version,
                                          max_output_buffer_len);
    assert(compress_ != nullptr);
    compressed_buffer_ =
        std::unique_ptr<char[]>(new char[max_output_buffer_len]);
    assert(compressed_buffer_);
  } else {
    // Disable compression if the record could not be added.
    compression_type_ = kNoCompression;
  }
  return s;
}

IOStatus Writer::MaybeAddUserDefinedTimestampSizeRecord(
    const UnorderedMap<uint32_t, size_t>& cf_to_ts_sz,
    Env::IOPriority rate_limiter_priority) {
  std::vector<std::pair<uint32_t, size_t>> ts_sz_to_record;
  for (const auto& [cf_id, ts_sz] : cf_to_ts_sz) {
    if (recorded_cf_to_ts_sz_.count(cf_id) != 0) {
      // A column family's user-defined timestamp size should not be
      // updated while DB is running.
      assert(recorded_cf_to_ts_sz_[cf_id] == ts_sz);
    } else if (ts_sz != 0) {
      ts_sz_to_record.emplace_back(cf_id, ts_sz);
      recorded_cf_to_ts_sz_.insert(std::make_pair(cf_id, ts_sz));
    }
  }
  if (ts_sz_to_record.empty()) {
    return IOStatus::OK();
  }

  UserDefinedTimestampSizeRecord record(std::move(ts_sz_to_record));
  std::string encoded;
  record.EncodeTo(&encoded);
  RecordType type = recycle_log_files_ ? kRecyclableUserDefinedTimestampSizeType
                                       : kUserDefinedTimestampSizeType;
  return EmitPhysicalRecord(type, encoded.data(), encoded.size(),
                            rate_limiter_priority);
}

bool Writer::BufferIsEmpty() { return dest_->BufferIsEmpty(); }

IOStatus Writer::EmitPhysicalRecord(RecordType t, const char* ptr, size_t n,
                                    Env::IOPriority rate_limiter_priority) {
  if (memtable_as_log_index_) {
    ROCKSDB_VERIFY(!recycle_log_files_);
    ROCKSDB_VERIFY(!dest_->use_direct_io()); // must not use direct io
    RawRecHeader header;
    header.checksum = crc32c::Value(ptr, n);
    header.length = n;
    header.rec_type = t;
    IOStatus s = dest_->Append(Slice((char*)&header, sizeof(RawRecHeader)),
                               0 /* crc32c_checksum */, rate_limiter_priority);
    if (s.ok()) {
      s = dest_->Append(Slice(ptr, n), header.checksum, rate_limiter_priority);
      log_offset_ += sizeof(RawRecHeader) + n;
    }
    return s;
  }
  assert(n <= 0xffff);  // Must fit in two bytes

  size_t header_size;
  char buf[kRecyclableHeaderSize];

  // Format the header
  buf[4] = static_cast<char>(n & 0xff);
  buf[5] = static_cast<char>(n >> 8);
  buf[6] = static_cast<char>(t);

  uint32_t crc = type_crc_[t];
  if (t < kRecyclableFullType || t == kSetCompressionType ||
      t == kUserDefinedTimestampSizeType) {
    // Legacy record format
    assert(block_offset_ + kHeaderSize + n <= kBlockSize);
    header_size = kHeaderSize;
  } else {
    // Recyclable record format
    assert(block_offset_ + kRecyclableHeaderSize + n <= kBlockSize);
    header_size = kRecyclableHeaderSize;

    // Only encode low 32-bits of the 64-bit log number.  This means
    // we will fail to detect an old record if we recycled a log from
    // ~4 billion logs ago, but that is effectively impossible, and
    // even if it were we'dbe far more likely to see a false positive
    // on the 32-bit CRC.
    EncodeFixed32(buf + 7, static_cast<uint32_t>(log_number_));
    crc = crc32c::Extend(crc, buf + 7, 4);
  }

  // Compute the crc of the record type and the payload.
  uint32_t payload_crc = crc32c::Value(ptr, n);
  crc = crc32c::Crc32cCombine(crc, payload_crc, n);
  crc = crc32c::Mask(crc);  // Adjust for storage
  TEST_SYNC_POINT_CALLBACK("LogWriter::EmitPhysicalRecord:BeforeEncodeChecksum",
                           &crc);
  EncodeFixed32(buf, crc);

  // Write the header and the payload
  IOStatus s = dest_->Append(Slice(buf, header_size), 0 /* crc32c_checksum */,
                             rate_limiter_priority);
  if (s.ok()) {
    s = dest_->Append(Slice(ptr, n), payload_crc, rate_limiter_priority);
  }
  block_offset_ += header_size + n;
  return s;
}

}  // namespace log
}  // namespace ROCKSDB_NAMESPACE
