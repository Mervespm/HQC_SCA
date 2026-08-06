"""HQC-128 reference model (Python) — ground truth for the SCA attack simulation.

This is a faithful, self-consistent model of the HQC-128 IND-CPA PKE that the
Caliptra/Yale decap RTL implements. It is NOT claimed bit-exact to the official
KATs (the sampler/serialisation differ); it IS exact in the algebra that the
chosen-ciphertext key-recovery attack relies on:

  * ring            R = F2[X]/(X^n - 1),  n = 17669
  * private key     sk = (x, y),  x,y sparse, weight w = 66
  * public key      pk = (h, s = x + h*y)
  * ciphertext      c = (u, v),  u = r1 + h*r2,  v = encode(m) (+) trunc(s*r2 + e)
  * decrypt         m' = Decode( v (+) trunc(u*y) )
                       = Decode( encode(m) (+) (x*r2 (+) e (+) r1*y)|_{n1n2} )
    (the h*y*r2 term cancels because s = x + h*y — verified by roundtrip below)

  * code = concatenated  RS(46,16) over GF(2^8)  ⊗  duplicated RM(1,7) (x3 -> 384)
           n1 = 46 RS symbols, n2 = 384 bits/block, n1*n2 = 17664 = n1n2

Validation (run this file):
  * GF(256) inverse/log round-trips
  * RM(1,7) encode->decode with up to (dmin-1)/2 bit errors per block
  * RS(46,16) encode->decode with up to t=15 symbol errors
  * full HQC encrypt->decrypt round-trip over many random messages/keys
"""
import random

# =============================== HQC-128 params =============================== #
N      = 17669      # ambient ring size (prime)
N1     = 46         # RS codeword length (symbols over GF(2^8))
K1     = 16         # RS message length (symbols)  -> k = 128-bit message
RS_T   = (N1 - K1) // 2   # = 15 correctable symbol errors
N2     = 384        # RM block length (bits) = 128 * MULT
MULT   = 3          # RM duplication multiplicity
N1N2   = N1 * N2    # 17664
W      = 66         # weight of secret x, y
WR     = 75         # weight of r1, r2
WE     = 75         # weight of e
MASK_N   = (1 << N) - 1
MASK_C   = (1 << N1N2) - 1

# =============================== GF(2^8) =============================== #
GF_POLY = 0x11D     # x^8 + x^4 + x^3 + x^2 + 1  (HQC RS field)
_gf_exp = [0] * 512
_gf_log = [0] * 256


def _init_gf():
    x = 1
    for i in range(255):
        _gf_exp[i] = x
        _gf_log[x] = i
        x <<= 1
        if x & 0x100:
            x ^= GF_POLY
    for i in range(255, 512):
        _gf_exp[i] = _gf_exp[i - 255]


_init_gf()


def gf_mul(a, b):
    if a == 0 or b == 0:
        return 0
    return _gf_exp[_gf_log[a] + _gf_log[b]]


def gf_inv(a):
    return _gf_exp[255 - _gf_log[a]]


def gf_pow(a, p):
    if a == 0:
        return 0
    return _gf_exp[(_gf_log[a] * p) % 255]


# =============================== Reed-Solomon (46,16), t=15 =============================== #
def _rs_generator():
    """g(x) = prod_{i=1}^{2t} (x - alpha^i), returned low-order-first."""
    g = [1]
    for i in range(1, 2 * RS_T + 1):
        root = _gf_exp[i]
        ng = [0] * (len(g) + 1)
        for j in range(len(g)):
            ng[j] ^= gf_mul(g[j], root)
            ng[j + 1] ^= g[j]
        g = ng
    return g


_RS_G = _rs_generator()


def rs_encode(msg):
    """msg: list of K1 symbols (high-order first). Returns N1 systematic symbols."""
    assert len(msg) == K1
    # systematic: parity = (msg * x^{2t}) mod g
    par = [0] * (2 * RS_T)
    for s in msg:
        fb = s ^ par[0]
        par = par[1:] + [0]
        if fb:
            for j in range(2 * RS_T):
                par[j] ^= gf_mul(_RS_G[2 * RS_T - 1 - j], fb)
    return list(msg) + par     # [message(16) | parity(30)]  length 46


def _rs_syndromes(cw):
    S = [0] * (2 * RS_T)
    for j in range(2 * RS_T):
        acc = 0
        aj = _gf_exp[j + 1]
        for c in cw:                       # Horner, high-order first
            acc = gf_mul(acc, aj) ^ c
        S[j] = acc
    return S


def rs_decode(cw):
    """Correct up to t symbol errors; return the K1 message symbols."""
    cw = list(cw)
    S = _rs_syndromes(cw)
    if not any(S):
        return cw[:K1]
    # Berlekamp-Massey
    C = [1]; B = [1]; L = 0; m = 1; b = 1
    for n in range(2 * RS_T):
        d = S[n]
        for i in range(1, L + 1):
            d ^= gf_mul(C[i], S[n - i])
        if d == 0:
            m += 1
        elif 2 * L <= n:
            T = list(C)
            coef = gf_mul(d, gf_inv(b))
            while len(C) < len(B) + m:
                C.append(0)
            for i in range(len(B)):
                C[i + m] ^= gf_mul(coef, B[i])
            L = n + 1 - L; B = T; b = d; m = 1
        else:
            coef = gf_mul(d, gf_inv(b))
            while len(C) < len(B) + m:
                C.append(0)
            for i in range(len(B)):
                C[i + m] ^= gf_mul(coef, B[i])
            m += 1
    # Chien search for error positions (roots of locator)
    err_pos = []
    Ln = len(C) - 1
    for i in range(N1):
        # evaluate C at alpha^{-i}
        x = gf_inv(_gf_exp[i]) if i else 1
        acc = 0
        for j in range(len(C)):
            acc ^= gf_mul(C[j], gf_pow(x, j))
        if acc == 0:
            err_pos.append(i)
    if len(err_pos) != Ln:
        return cw[:K1]        # decode failure -> return as-is (uncorrected)
    # Forney: error values
    # locator derivative and evaluator
    Omega = [0] * (2 * RS_T)
    for i in range(len(S)):
        for j in range(len(C)):
            if i + j < 2 * RS_T:
                Omega[i + j] ^= gf_mul(S[i], C[j])
    for pos in err_pos:
        Xi = _gf_exp[pos]
        Xi_inv = gf_inv(Xi)
        # Omega(Xi_inv)
        num = 0
        for j in range(len(Omega)):
            num ^= gf_mul(Omega[j], gf_pow(Xi_inv, j))
        # locator derivative (odd terms) evaluated at Xi_inv
        den = 0
        for j in range(1, len(C), 2):
            den ^= gf_mul(C[j], gf_pow(Xi_inv, j - 1))
        if den == 0:
            return cw[:K1]
        mag = gf_mul(num, gf_inv(den))
        cw[N1 - 1 - pos] ^= mag      # position pos counts from low order
    return cw[:K1]


# =============================== Reed-Muller RM(1,7) x3 =============================== #
def _fht(a):
    """In-place fast Walsh-Hadamard transform, length 128."""
    h = 1
    n = len(a)
    while h < n:
        for i in range(0, n, h * 2):
            for j in range(i, i + h):
                x = a[j]; y = a[j + h]
                a[j] = x + y; a[j + h] = x - y
        h *= 2
    return a


def rm_encode_byte(sym):
    """8-bit symbol -> 128-bit RM(1,7) codeword, then duplicated x3 -> 384-bit int."""
    lin = sym & 0x7F           # 7 linear-functional bits
    const = (sym >> 7) & 1     # constant bit
    cw = 0
    for j in range(128):
        bit = (bin(lin & j).count("1") & 1) ^ const
        if bit:
            cw |= (1 << j)
    block = 0
    for c in range(MULT):
        block |= cw << (c * 128)
    return block               # 384-bit int


def rm_decode_block(block):
    """384-bit int -> 8-bit RS symbol via soft-combined FHT decode."""
    soft = [0] * 128
    for c in range(MULT):
        copy = (block >> (c * 128)) & ((1 << 128) - 1)
        for j in range(128):
            soft[j] += 1 - 2 * ((copy >> j) & 1)   # +1 for 0, -1 for 1
    F = _fht(list(soft))
    # peak by absolute value
    L = 0; best = -1
    for j in range(128):
        if abs(F[j]) > best:
            best = abs(F[j]); L = j
    const = 0 if F[L] > 0 else 1
    return (const << 7) | L


# =============================== concatenated code =============================== #
def encode_message(m_bytes):
    """16-byte message -> 17664-bit codeword (int)."""
    assert len(m_bytes) == K1
    rs = rs_encode(list(m_bytes))               # 46 symbols
    cw = 0
    for b in range(N1):
        cw |= rm_encode_byte(rs[b]) << (b * N2)
    return cw & MASK_C


def decode_codeword(cw):
    """17664-bit codeword (int) -> 16-byte message (bytes)."""
    syms = []
    for b in range(N1):
        block = (cw >> (b * N2)) & ((1 << N2) - 1)
        syms.append(rm_decode_block(block))
    msg = rs_decode(syms)
    return bytes(msg)


# =============================== ring arithmetic =============================== #
def rot(a, i):
    """Multiply ring element a (int) by X^i mod (X^n - 1) — a cyclic rotate."""
    i %= N
    if i == 0:
        return a
    return ((a << i) | (a >> (N - i))) & MASK_N


def ring_mul(a, positions):
    """a * b  where b is sparse, given as a list of exponents (set-bit positions)."""
    r = 0
    for i in positions:
        r ^= rot(a, i)
    return r


def sample_sparse(weight):
    """Return (int value, sorted positions) of a weight-`weight` ring element."""
    pos = random.sample(range(N), weight)
    v = 0
    for p in pos:
        v |= (1 << p)
    return v, sorted(pos)


def sample_dense():
    return random.getrandbits(N) & MASK_N


# =============================== KEM/PKE =============================== #
def keygen():
    x, xpos = sample_sparse(W)
    y, ypos = sample_sparse(W)
    h = sample_dense()
    s = x ^ ring_mul(h, ypos)            # s = x + h*y
    return dict(x=x, xpos=xpos, y=y, ypos=ypos, h=h, s=s)


def encrypt(pk, m_bytes):
    h, s = pk["h"], pk["s"]
    r1, r1pos = sample_sparse(WR)
    r2, r2pos = sample_sparse(WR)
    e, epos = sample_sparse(WE)
    u = r1 ^ ring_mul(h, r2pos)                       # u = r1 + h*r2
    tmp = ring_mul(s, r2pos) ^ e                      # s*r2 + e  (full ring)
    v = encode_message(m_bytes) ^ (tmp & MASK_C)      # + truncate(., n1n2)
    return u, v


def decrypt(sk, u, v):
    uy = ring_mul(u, sk["ypos"])                      # u*y (full ring)
    tmp = v ^ (uy & MASK_C)                           # v - trunc(u*y)
    return decode_codeword(tmp)


# =============================== self-tests =============================== #
def _test_gf():
    assert gf_mul(0, 5) == 0 and gf_mul(1, 5) == 5
    for a in range(1, 256):
        assert gf_mul(a, gf_inv(a)) == 1
    print("  [ok] GF(256) inverse round-trip (255 elements)")


def _test_rm():
    fails = 0
    for _ in range(200):
        sym = random.randint(0, 255)
        blk = rm_encode_byte(sym)
        # inject up to 31 bit errors per 128-copy region (well under RM radius x3)
        for _ in range(31):
            blk ^= 1 << random.randint(0, N2 - 1)
        if rm_decode_block(blk) != sym:
            fails += 1
    print(f"  [{'ok' if fails == 0 else 'FAIL'}] RM(1,7)x3 decode with 31 bit-errors/block: {200-fails}/200")
    return fails == 0


def _test_rs():
    fails = 0
    for _ in range(100):
        msg = [random.randint(0, 255) for _ in range(K1)]
        cw = rs_encode(msg)
        pos = random.sample(range(N1), RS_T)             # exactly t errors
        for p in pos:
            cw[p] ^= random.randint(1, 255)
        if rs_decode(cw) != msg:
            fails += 1
    print(f"  [{'ok' if fails == 0 else 'FAIL'}] RS(46,16) decode with {RS_T} symbol-errors: {100-fails}/100")
    return fails == 0


def _test_code_roundtrip():
    fails = 0
    for _ in range(50):
        m = bytes(random.randint(0, 255) for _ in range(K1))
        if decode_codeword(encode_message(m)) != m:
            fails += 1
    print(f"  [{'ok' if fails == 0 else 'FAIL'}] concatenated encode->decode (noiseless): {50-fails}/50")
    return fails == 0


def _test_hqc_roundtrip():
    fails = 0
    trials = 20
    for _ in range(trials):
        sk = keygen()
        pk = dict(h=sk["h"], s=sk["s"])
        m = bytes(random.randint(0, 255) for _ in range(K1))
        u, v = encrypt(pk, m)
        if decrypt(sk, u, v) != m:
            fails += 1
    print(f"  [{'ok' if fails == 0 else 'FAIL'}] full HQC encrypt->decrypt round-trip: {trials-fails}/{trials}")
    return fails == 0


def main():
    random.seed(1)
    print("HQC-128 reference model self-test:")
    _test_gf()
    ok = True
    ok &= _test_rm()
    ok &= _test_rs()
    ok &= _test_code_roundtrip()
    ok &= _test_hqc_roundtrip()
    print("\nALL SELF-TESTS PASSED" if ok else "\nSOME TESTS FAILED")
    return ok


if __name__ == "__main__":
    main()
