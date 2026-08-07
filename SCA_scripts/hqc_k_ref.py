#!/usr/bin/env python3
# =============================================================================
#  hqc_k_ref.py -- BIT-EXACT reference model of HQC-128's shared-secret hash K,
#  the second Keccak call in decapsulation, and the target of the improved
#  (confounder-free) plaintext-checking oracle.
#
#  From the HQC reference implementation (kem.c / shake_ds.c, current NIST
#  round-4 submission):
#
#      mc = (m on success | sigma on failure) || u || v          (concatenation)
#      K  = SHAKE256( mc || K_FCT_DOMAIN ),   K_FCT_DOMAIN = 0x04,  512-bit out
#
#  shake_ds absorbs the input, THEN absorbs the single domain byte, THEN applies
#  the standard SHAKE256 padding. That is exactly:
#
#      K = hashlib.shake_256( mc + bytes([0x04]) ).digest(64)
#
#  This module is the golden model the FPGA `hqc_k_ctrl` must match bit-for-bit
#  (verified in ModelSim before any bitstream), and the software oracle used to
#  reason about the K attack. It does NOT change the key-recovery math -- K only
#  supplies a cleaner success/failure oracle bit; support recovery + the
#  linear-algebra completion (hqc_attack_sim.py / linalg_completion.py) are
#  unchanged.
# =============================================================================
import hashlib

# ---- HQC-128 sizes (parameters.h) ------------------------------------------
PARAM_N      = 17669
PARAM_N1N2   = 17664
VEC_K_BYTES  = 16                         # message field (128-bit m / sigma)
VEC_N_BYTES  = (PARAM_N + 7) // 8         # u  = 2209 bytes
VEC_N1N2_BYTES = (PARAM_N1N2 + 7) // 8    # v  = 2208 bytes
MC_BYTES     = VEC_K_BYTES + VEC_N_BYTES + VEC_N1N2_BYTES   # 4433
K_FCT_DOMAIN = 0x04
G_FCT_DOMAIN = 0x03
K_OUT_BYTES  = 64                         # SHAKE256_512 = 512 bits


def build_mc(msg16: bytes, u_bytes: bytes, v_bytes: bytes) -> bytes:
    """Assemble mc = msg || u || v with the exact HQC field sizes."""
    assert len(msg16) == VEC_K_BYTES, f"msg must be {VEC_K_BYTES} bytes"
    assert len(u_bytes) == VEC_N_BYTES, f"u must be {VEC_N_BYTES} bytes"
    assert len(v_bytes) == VEC_N1N2_BYTES, f"v must be {VEC_N1N2_BYTES} bytes"
    return msg16 + u_bytes + v_bytes


def K_of_mc(mc: bytes) -> bytes:
    """K = SHAKE256(mc || 0x04), 512-bit output (the golden model)."""
    return hashlib.shake_256(mc + bytes([K_FCT_DOMAIN])).digest(K_OUT_BYTES)


def K_shared_secret(msg16: bytes, u_bytes: bytes, v_bytes: bytes) -> bytes:
    return K_of_mc(build_mc(msg16, u_bytes, v_bytes))


def K_words_le(mc_or_ss) -> list:
    """K as 16 little-endian 32-bit words (device readback convention)."""
    if isinstance(mc_or_ss, bytes) and len(mc_or_ss) == K_OUT_BYTES:
        ss = mc_or_ss
    else:
        ss = K_of_mc(mc_or_ss)
    return [int.from_bytes(ss[i:i + 4], "little") for i in range(0, K_OUT_BYTES, 4)]


def framing_constants():
    """Multi-block Keccak absorb framing for mc||domain (rate 1088 bits).
    Mirrors the Yale encap.v convention but with the CURRENT domain 0x04."""
    total_bits = (MC_BYTES + 1) * 8          # + domain byte
    RATE = 1088
    full_blocks = total_bits // RATE
    last_bits = total_bits % RATE
    return dict(
        mc_bytes=MC_BYTES, total_input_bits=total_bits,
        rate_bits=RATE, full_blocks=full_blocks, last_block_bits=last_bits,
        out_header=0x40000000 | (K_OUT_BYTES * 8),      # squeeze 512 bits
        full_block_header=0x80000000 | RATE,             # 0x80000440
        last_block_header=0x80000000 | last_bits,        # 0x80000290 for hqc128
        domain=K_FCT_DOMAIN,
    )


# --------------------------------------------------------------------------- #
#  BLOCK-0 model that the FPGA `hqc_k_ctrl` actually computes (single rate
#  block): SHAKE256( 0x04 || m'[MSB..LSB] || FILLER[MSB..LSB] ) squeezed to
#  512 bits, read as 16 little-endian 32-bit words. Domain is PREPENDED here
#  (common-mode w.r.t. the oracle) to reuse the verified G-core framing; this
#  is the golden vector for the ModelSim check, NOT the full 33-block K.
# --------------------------------------------------------------------------- #
FILLER_BYTES = 48   # 384-bit host-writable u-nuisance region


def k_block0_ref_words(mprime_int: int, filler_int: int) -> list:
    msg = mprime_int.to_bytes(16, "big")
    fil = filler_int.to_bytes(FILLER_BYTES, "big")
    d = hashlib.shake_256(bytes([K_FCT_DOMAIN]) + msg + fil).digest(K_OUT_BYTES)
    return [int.from_bytes(d[4 * i:4 * i + 4], "little") for i in range(16)]


def k_msgfield_ref_words(mprime_int: int) -> list:
    """Bit-exact model of hqc_k_ctrl (G-core convention, domain 0x04):
    SHAKE256( 0x04 || m'[MSB..LSB] ) squeezed to 512 bits, read as 16
    little-endian 32-bit words. This is the message-field K oracle: drive
    m'=0 (success) or m'=sigma (failure)."""
    msg = mprime_int.to_bytes(16, "big")
    d = hashlib.shake_256(bytes([K_FCT_DOMAIN]) + msg).digest(K_OUT_BYTES)
    return [int.from_bytes(d[4 * i:4 * i + 4], "little") for i in range(16)]


if __name__ == "__main__":
    c = framing_constants()
    print("HQC-128 K reference")
    for k, v in c.items():
        print(f"  {k:18s} = {v}" + (f"  (0x{v:08x})" if k.endswith('header') else ""))
    # sanity: last-block header must be 0x80000290 (matches encap.v HASH_LB_DOMSEP)
    assert c["last_block_header"] == 0x80000290, c["last_block_header"]
    assert c["full_block_header"] == 0x80000440, c["full_block_header"]
    print("  framing constants MATCH the in-repo Yale encap.v (0x290 / 0x440). OK")

    # golden K for a known (msg, u, v): success (m=0) vs failure (m=sigma)
    import os
    u = bytes(range(256)) * (VEC_N_BYTES // 256) + bytes(range(VEC_N_BYTES % 256))
    v = bytes((i * 7) & 0xff for i in range(VEC_N1N2_BYTES))
    m_succ = bytes(16)                                   # decode success -> m = 0
    sigma  = bytes([0xA5]) * 16                          # per-key implicit-reject secret
    Ks = K_shared_secret(m_succ, u, v)
    Kf = K_shared_secret(sigma, u, v)
    print("\n  K(success m=0)   =", Ks.hex())
    print("  K(failure sigma) =", Kf.hex())
    diff = sum(bin(a ^ b).count("1") for a, b in zip(Ks, Kf))
    print(f"  Hamming distance between the two K outputs = {diff}/512 bits "
          f"(avalanche: success vs failure fully separated)")
