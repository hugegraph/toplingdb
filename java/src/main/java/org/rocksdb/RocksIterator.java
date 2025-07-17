// Copyright (c) 2011-present, Facebook, Inc.  All rights reserved.
//  This source code is licensed under both the GPLv2 (found in the
//  COPYING file in the root directory) and Apache 2.0 License
//  (found in the LICENSE.Apache file in the root directory).

package org.rocksdb;

import static org.rocksdb.util.BufferUtil.CheckBounds;

import java.nio.ByteBuffer;
import sun.misc.Unsafe;

/**
 * <p>An iterator that yields a sequence of key/value pairs from a source.
 * Multiple implementations are provided by this library.
 * In particular, iterators are provided
 * to access the contents of a Table or a DB.</p>
 *
 * <p>Multiple threads can invoke const methods on an RocksIterator without
 * external synchronization, but if any of the threads may call a
 * non-const method, all threads accessing the same RocksIterator must use
 * external synchronization.</p>
 *
 * @see org.rocksdb.RocksObject
 */
public class RocksIterator extends AbstractRocksIterator<RocksDB> {
  protected RocksIterator(final RocksDB rocksDB, final long nativeHandle) {
    super(rocksDB, nativeHandle);
  }

  /**
   * <p>Return the key for the current entry.  The underlying storage for
   * the returned slice is valid only until the next modification of
   * the iterator.</p>
   *
   * <p>REQUIRES: {@link #isValid()}</p>
   *
   * @return key for the current entry.
   */
  public byte[] key() {
    assert(isOwningHandle());
    assert(isValid());
    long keyPtr = getZeroCopyKeyPtr();
    long keyLen = getZeroCopyKeyLen();
    byte[] key = new byte[(int)keyLen];
    myUnsafe.copyMemory(null, keyPtr, key, Unsafe.ARRAY_BYTE_BASE_OFFSET, keyLen);
    return key;
  }

  private static final Unsafe myUnsafe = DirectSlice.getUnsafe();
  public static Unsafe getUnsafe() {
    return myUnsafe;
  }
  public final long getZeroCopyKeyPtr() {
    assert(isOwningHandle());
    // static_assert(offsetof(JZeroCopyIter, key.data_) == 8); // in C++
    return myUnsafe.getLong(nativeHandle_ + 8);
  }
  public final long getZeroCopyKeyLen() {
    assert(isOwningHandle());
    // static_assert(offsetof(JZeroCopyIter, key.size_) == 16); // in C++
    return myUnsafe.getLong(nativeHandle_ + 16);
  }
  public final long getZeroCopyValuePtr() {
    assert(isOwningHandle());
    // static_assert(offsetof(JZeroCopyIter, value.data_) == 24); // in C++
    return myUnsafe.getLong(nativeHandle_ + 24);
  }
  public final long getZeroCopyValueLen() {
    assert(isOwningHandle());
    // static_assert(offsetof(JZeroCopyIter, value.size_) == 32); // in C++
    return myUnsafe.getLong(nativeHandle_ + 32);
  }
  public final boolean isValueFetched() {
    assert(isOwningHandle());
    // if not fetched, call this.value() will fetch the value
    return getZeroCopyValuePtr() != 0;
  }
  public final void fetchValue() {
    assert(isOwningHandle());
    if (getZeroCopyValuePtr() == 0) {
      byte[] val = value0(nativeHandle_ | 1); // or 1 indicate just do fetch
      assert(val == null); // just fetch the value, not copy it, must be null
      // this will not copy the value, just set the zero-copy pointer
      assert(getZeroCopyValuePtr() != 0);
    }
  }
  public final void nextWithValue() {
    assert(isOwningHandle());
    assert((nativeHandle_ & 7L) == 0L);
    next0(nativeHandle_ | 1); // or 1 indicate that we are fetching the value
  }
  public final void prevWithValue() {
    assert(isOwningHandle());
    assert((nativeHandle_ & 7L) == 0L);
    prev0(nativeHandle_ | 1); // or 1 indicate that we are fetching the value
  }
  public final void seekToFirstWithValue() {
    assert (isOwningHandle());
    assert((nativeHandle_ & 7L) == 0L);
    seekToFirst0(nativeHandle_ | 1);
  }
  public final void seekToLastWithValue() {
    assert (isOwningHandle());
    assert((nativeHandle_ & 7L) == 0L);
    seekToLast0(nativeHandle_ | 1);
  }
  public final void seekWithValue(final byte[] target) {
    assert (isOwningHandle());
    assert((nativeHandle_ & 7L) == 0L);
    seek0(nativeHandle_ | 1, target, target.length);
  }
  public final void seekForPrevWithValue(final byte[] target) {
    assert (isOwningHandle());
    assert((nativeHandle_ & 7L) == 0L);
    seekForPrev0(nativeHandle_ | 1, target, target.length);
  }
  public final void seekWithValue(final ByteBuffer target) {
    assert (isOwningHandle());
    assert((nativeHandle_ & 7L) == 0L);
    if (target.isDirect()) {
      seekDirect0(nativeHandle_ | 1, target, target.position(), target.remaining());
    } else {
      seekByteArray0(nativeHandle_ | 1, target.array(), target.arrayOffset() + target.position(),
          target.remaining());
    }
    target.position(target.limit());
  }
  public final void seekForPrevWithValue(final ByteBuffer target) {
    assert (isOwningHandle());
    assert((nativeHandle_ & 7L) == 0L);
    if (target.isDirect()) {
      seekForPrevDirect0(nativeHandle_ | 1, target, target.position(), target.remaining());
    } else {
      seekForPrevByteArray0(nativeHandle_ | 1, target.array(), target.arrayOffset() + target.position(),
          target.remaining());
    }
    target.position(target.limit());
  }

  @Override
  public final boolean isValid() {
    assert(isOwningHandle());
    return getZeroCopyKeyPtr() != 0;
  }

  /**
   * <p>Return the key for the current entry.  The underlying storage for
   * the returned slice is valid only until the next modification of
   * the iterator.</p>
   *
   * <p>REQUIRES: {@link #isValid()}</p>
   *
   * @param key the out-value to receive the retrieved key.
   * @return The size of the actual key. If the return key is greater than
   *     the length of the buffer {@code key}, then it indicates that the size of the
   *     input buffer {@code key} is insufficient and partial result will
   *     be returned.
   */
  public int key(final byte[] key) {
    assert isOwningHandle();
    long keyLen = getZeroCopyKeyLen();
    long len = Math.min((long)key.length, keyLen);
    long ptr = getZeroCopyKeyPtr();
    myUnsafe.copyMemory(null, ptr, key, Unsafe.ARRAY_BYTE_BASE_OFFSET, len);
    return (int)keyLen;
  }

  /**
   * <p>Return the key for the current entry.  The underlying storage for
   * the returned slice is valid only until the next modification of
   * the iterator.</p>
   *
   * <p>REQUIRES: {@link #isValid()}</p>
   *
   * @param key the out-value to receive the retrieved key.
   * @param offset in {@code key} at which to place the retrieved key
   * @param len limit to length of received key returned
   * @return The size of the actual key. If the return key is greater than
   *     {@code len}, then it indicates that the size of the
   *     input buffer {@code key} is insufficient and partial result will
   *     be returned.
   */
  public int key(final byte[] key, final int offset, final int len) {
    assert isOwningHandle();
    CheckBounds(offset, len, key.length);
    long keyLen = getZeroCopyKeyLen();
    long cplen = Math.min((long)len, keyLen);
    long ptr = getZeroCopyKeyPtr();
    long keyOffset = Unsafe.ARRAY_BYTE_BASE_OFFSET + offset;
    myUnsafe.copyMemory(null, ptr, key, keyOffset, cplen);
    return (int)keyLen;
  }

  /**
   * <p>Return the key for the current entry.  The underlying storage for
   * the returned slice is valid only until the next modification of
   * the iterator.</p>
   *
   * <p>REQUIRES: {@link #isValid()}</p>
   *
   * @param key the out-value to receive the retrieved key.
   *     It is using position and limit. Limit is set according to key size.
   * @return The size of the actual key. If the return key is greater than the
   *     length of {@code key}, then it indicates that the size of the
   *     input buffer {@code key} is insufficient and partial result will
   *     be returned.
   */
  public int key(final ByteBuffer key) {
    assert isOwningHandle();
    long zcKeyPtr = getZeroCopyKeyPtr();
    long zcKeyLen = getZeroCopyKeyLen();
    final int result;
    if (key.isDirect()) {
      if (DirectSlice.supportDirectBorrowMemory(key)) { // do zero copy:
        DirectSlice.directBorrowMemoryUnchecked(key, zcKeyPtr, zcKeyLen);
        result = (int)zcKeyLen; // just reset the buffer, no copy
        return result;
      } else {
        result = keyDirect0(nativeHandle_, key, key.position(), key.remaining());
        assert result == zcKeyLen;
      }
    } else {
      assert key.hasArray();
      long keyOffset = Unsafe.ARRAY_BYTE_BASE_OFFSET + key.arrayOffset() + key.position();
      long cplen = Math.min((long)key.remaining(), zcKeyLen);
      myUnsafe.copyMemory(null, zcKeyPtr, key.array(), keyOffset, cplen);
      result = (int)zcKeyLen;
    }
    key.limit(Math.min(key.position() + result, key.limit()));
    return result;
  }

  /**
   * <p>Return the value for the current entry.  The underlying storage for
   * the returned slice is valid only until the next modification of
   * the iterator.</p>
   *
   * <p>REQUIRES: !AtEnd() &amp;&amp; !AtStart()</p>
   * @return value for the current entry.
   */
  public byte[] value() {
    assert(isOwningHandle());
    fetchValue();
    long valueLen = getZeroCopyValueLen();
    long valuePtr = getZeroCopyValuePtr();
    byte[] value = new byte[(int)valueLen];
    myUnsafe.copyMemory(null, valuePtr, value, Unsafe.ARRAY_BYTE_BASE_OFFSET, valueLen);
    return value;
  }

  /**
   * <p>Return the value for the current entry.  The underlying storage for
   * the returned slice is valid only until the next modification of
   * the iterator.</p>
   *
   * <p>REQUIRES: {@link #isValid()}</p>
   *
   * @param value the out-value to receive the retrieved value.
   *     It is using position and limit. Limit is set according to value size.
   * @return The size of the actual value. If the return value is greater than the
   *     length of {@code value}, then it indicates that the size of the
   *     input buffer {@code value} is insufficient and partial result will
   *     be returned.
   */
  public int value(final ByteBuffer value) {
    assert isOwningHandle();
    final int result;
    if (value.isDirect()) {
      if (DirectSlice.supportDirectBorrowMemory(value)) { // do zero copy:
        fetchValue();
        long valuePtr = getZeroCopyValuePtr();
        long valueLen = getZeroCopyValueLen();
        DirectSlice.directBorrowMemoryUnchecked(value, valuePtr, valueLen);
        result = (int)valueLen; // just reset the buffer, no copy
        return result;
      } else {
        result = valueDirect0(nativeHandle_, value, value.position(), value.remaining());
      }
    } else if (isValueFetched()) {
      assert value.hasArray();
      long valuePtr = getZeroCopyValuePtr();
      long valueLen = getZeroCopyValueLen();
      long cplen = Math.min((long)value.remaining(), valueLen);
      long valueOffset = Unsafe.ARRAY_BYTE_BASE_OFFSET + value.arrayOffset() + value.position();
      myUnsafe.copyMemory(null, valuePtr, value.array(), valueOffset, cplen);
      result = (int)valueLen;
    } else {
      assert value.hasArray();
      result = valueByteArray0(
          nativeHandle_, value.array(), value.arrayOffset() + value.position(), value.remaining());
    }
    value.limit(Math.min(value.position() + result, value.limit()));
    return result;
  }

  /**
   * <p>Return the value for the current entry.  The underlying storage for
   * the returned slice is valid only until the next modification of
   * the iterator.</p>
   *
   * <p>REQUIRES: {@link #isValid()}</p>
   *
   * @param value the out-value to receive the retrieved value.
   * @return The size of the actual value. If the return value is greater than the
   *     length of {@code value}, then it indicates that the size of the
   *     input buffer {@code value} is insufficient and partial result will
   *     be returned.
   */
  public int value(final byte[] value) {
    assert isOwningHandle();
    fetchValue();
    long valueLen = getZeroCopyValueLen();
    long valuePtr = getZeroCopyValuePtr();
    long cplen = Math.min((long)value.length, valueLen);
    myUnsafe.copyMemory(null, valuePtr, value, Unsafe.ARRAY_BYTE_BASE_OFFSET, cplen);
    return (int)valueLen;
  }

  /**
   * <p>Return the value for the current entry.  The underlying storage for
   * the returned slice is valid only until the next modification of
   * the iterator.</p>
   *
   * <p>REQUIRES: {@link #isValid()}</p>
   *
   * @param value the out-value to receive the retrieved value.
   * @param offset the offset within value at which to place the result
   * @param len the length available in value after offset, for placing the result
   * @return The size of the actual value. If the return value is greater than {@code len},
   *     then it indicates that the size of the
   *     input buffer {@code value} is insufficient and partial result will
   *     be returned.
   */
  public int value(final byte[] value, final int offset, final int len) {
    assert isOwningHandle();
    CheckBounds(offset, len, value.length);
    fetchValue();
    long valueLen = getZeroCopyValueLen();
    long valuePtr = getZeroCopyValuePtr();
    long cplen = Math.min((long)len, valueLen);
    long valueOffset = Unsafe.ARRAY_BYTE_BASE_OFFSET + offset;
    myUnsafe.copyMemory(null, valuePtr, value, valueOffset, cplen);
    return (int)valueLen;
  }

  static final boolean DEFAULT_EAGER_FETCH_VALUE;
  static {
    String eagerFetchValue = System.getenv("TOPLINGDB_EAGER_FETCH_VALUE");
    if (eagerFetchValue == null) {
      DEFAULT_EAGER_FETCH_VALUE = false; // default to false
    } else {
      DEFAULT_EAGER_FETCH_VALUE = Boolean.parseBoolean(eagerFetchValue);
    }
  }
  private int eagerFetchValue_ = DEFAULT_EAGER_FETCH_VALUE ? 1 : 0;
  public final void enableEagerFetchValue(boolean eager) {
    eagerFetchValue_ = eager ? 1 : 0;
  }
  public final boolean isDefaultEagerFetchValue() {
    return eagerFetchValue_ != 0;
  }
  @Override public final void seekToFirst() {
    assert(isOwningHandle());
    seekToFirst0(nativeHandle_ | eagerFetchValue_);
  }
  @Override public final void seekToLast() {
    assert(isOwningHandle());
    seekToLast0(nativeHandle_ | eagerFetchValue_);
  }

  @Override public final void seek(final byte[] target) {
    assert (isOwningHandle());
    seek0(nativeHandle_ | eagerFetchValue_, target, target.length);
  }

  @Override public final void seekForPrev(final byte[] target) {
    assert (isOwningHandle());
    seekForPrev0(nativeHandle_ | eagerFetchValue_, target, target.length);
  }

  @Override public final void seek(final ByteBuffer target) {
    assert (isOwningHandle());
    long handle = nativeHandle_ | eagerFetchValue_;
    if (target.isDirect()) {
      seekDirect0(handle, target, target.position(), target.remaining());
    } else {
      int offset = target.arrayOffset() + target.position();
      seekByteArray0(handle, target.array(), offset, target.remaining());
    }
    target.position(target.limit());
  }

  @Override public final void seekForPrev(final ByteBuffer target) {
    assert (isOwningHandle());
    long handle = nativeHandle_ | eagerFetchValue_;
    if (target.isDirect()) {
      seekForPrevDirect0(handle, target, target.position(), target.remaining());
    } else {
      int offset = target.arrayOffset() + target.position();
      seekForPrevByteArray0(handle, target.array(), offset, target.remaining());
    }
    target.position(target.limit());
  }

  @Override public final void next() {
    assert (isOwningHandle());
    next0(nativeHandle_ | eagerFetchValue_);
  }

  @Override public final void prev() {
    assert (isOwningHandle());
    prev0(nativeHandle_ | eagerFetchValue_);
  }

  @Override protected final native void disposeInternal(final long handle);
  @Override final native boolean isValid0(long handle);
  @Override final native void seekToFirst0(long handle);
  @Override final native void seekToLast0(long handle);
  @Override final native void next0(long handle);
  @Override final native void prev0(long handle);
  @Override final native void refresh0(long handle);
  @Override final native void seek0(long handle, byte[] target, int targetLen);
  @Override final native void seekForPrev0(long handle, byte[] target, int targetLen);
  @Override
  final native void seekDirect0(long handle, ByteBuffer target, int targetOffset, int targetLen);
  @Override
  final native void seekByteArray0(long handle, byte[] target, int targetOffset, int targetLen);
  @Override
  final native void seekForPrevDirect0(
      long handle, ByteBuffer target, int targetOffset, int targetLen);
  @Override
  final native void seekForPrevByteArray0(
      long handle, byte[] target, int targetOffset, int targetLen);
  @Override final native void status0(long handle) throws RocksDBException;

  private native byte[] key0(long handle);
  private native byte[] value0(long handle);
  private native int keyDirect0(long handle, ByteBuffer buffer, int bufferOffset, int bufferLen);
  private native int keyByteArray0(long handle, byte[] array, int arrayOffset, int arrayLen);
  private native int valueDirect0(long handle, ByteBuffer buffer, int bufferOffset, int bufferLen);
  private native int valueByteArray0(long handle, byte[] array, int arrayOffset, int arrayLen);
}
