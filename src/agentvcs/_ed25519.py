"""Vendored pure-Python Ed25519 (RFC 8032) — the cryptographic substrate of the Soul.

agentvcs has one hard rule: **zero runtime dependencies, pure stdlib**. But the
DeSoc identity layer needs *asymmetric* signatures — the whole point is that a
third party (an orchestrator, a marketplace, another agent) can verify an agent's
signed history holding only its **public** Soul id, never its secret key. Symmetric
HMAC can't do that: verifying would require sharing the secret, which destroys
provenance.

So we vendor the public-domain reference Ed25519 implementation (Bernstein et al.,
the one shipped with the NaCl test vectors and reproduced in RFC 8032's appendix).
It is deterministic (same message + key → same signature, so signed commits keep a
stable content id), self-contained, and depends only on ``hashlib``. It is the
*slow* reference variant — fine at human/agent commit rates, not for a hot loop.

For a production Web3 deployment this module is the single swap point: drop in
libsodium / an Ethereum ECDSA signer behind the same ``publickey / sign / verify``
surface and nothing else in agentvcs changes.

Public domain. API intentionally tiny: ``publickey(seed) -> pk``,
``sign(msg, seed) -> sig``, ``verify(sig, msg, pk) -> bool``. All bytes.
"""
from __future__ import annotations

import hashlib

b = 256
q = 2 ** 255 - 19
ell = 2 ** 252 + 27742317777372353535851937790883648493


def _H(m: bytes) -> bytes:
    return hashlib.sha512(m).digest()


def _expmod(base: int, e: int, m: int) -> int:
    return pow(base, e, m)


def _inv(x: int) -> int:
    return _expmod(x, q - 2, q)


_d = -121665 * _inv(121666) % q
_I = _expmod(2, (q - 1) // 4, q)


def _xrecover(y: int) -> int:
    xx = (y * y - 1) * _inv(_d * y * y + 1)
    x = _expmod(xx, (q + 3) // 8, q)
    if (x * x - xx) % q != 0:
        x = (x * _I) % q
    if x % 2 != 0:
        x = q - x
    return x


_By = 4 * _inv(5)
_Bx = _xrecover(_By)
_B = [_Bx % q, _By % q]

# Affine Edwards addition — correct but does a modular inverse per add. Kept only
# for the single addition the verify equation needs; the scalar multiply below uses
# inversion-free extended coordinates instead, which is ~2 orders of magnitude faster.
def _edwards(P, Q):
    x1, y1 = P
    x2, y2 = Q
    x3 = (x1 * y2 + x2 * y1) * _inv(1 + _d * x1 * x2 * y1 * y2)
    y3 = (y1 * y2 + x1 * x2) * _inv(1 - _d * x1 * x2 * y1 * y2)
    return [x3 % q, y3 % q]


# --- extended homogeneous coordinates (X:Y:Z:T), x=X/Z, y=Y/Z, T=XY/Z ---
_d2 = (2 * _d) % q


def _to_ext(P):
    x, y = P
    return (x % q, y % q, 1, (x * y) % q)


def _ext_add(P, Q):
    # unified twisted-Edwards addition (a = -1), no inversions (RFC 8032 appendix)
    X1, Y1, Z1, T1 = P
    X2, Y2, Z2, T2 = Q
    A = ((Y1 - X1) * (Y2 - X2)) % q
    B = ((Y1 + X1) * (Y2 + X2)) % q
    C = (T1 * _d2 * T2) % q
    D = (Z1 * 2 * Z2) % q
    E = (B - A) % q
    F = (D - C) % q
    G = (D + C) % q
    H = (B + A) % q
    return ((E * F) % q, (G * H) % q, (F * G) % q, (E * H) % q)


def _scalarmult(P, e: int):
    """Return ``e * P`` in affine [x, y]. Double-and-add in extended coordinates;
    a single inversion converts back to affine at the very end."""
    Q = (0, 1, 1, 0)  # identity
    R = _to_ext(P)
    for i in reversed(range(e.bit_length() + 1)):
        Q = _ext_add(Q, Q)
        if (e >> i) & 1:
            Q = _ext_add(Q, R)
    X, Y, Z, _T = Q
    zi = _inv(Z)
    return [(X * zi) % q, (Y * zi) % q]


def _encodeint(y: int) -> bytes:
    return y.to_bytes(b // 8, "little")


def _encodepoint(P) -> bytes:
    x, y = P
    val = y | ((x & 1) << (b - 1))
    return val.to_bytes(b // 8, "little")


def _bit(h: bytes, i: int) -> int:
    return (h[i // 8] >> (i % 8)) & 1


def _secret_scalar(seed: bytes) -> tuple[int, bytes]:
    h = _H(seed)
    a = 2 ** (b - 2) + sum(2 ** i * _bit(h, i) for i in range(3, b - 2))
    return a, h


def publickey(seed: bytes) -> bytes:
    """Derive the 32-byte public key (the verifiable Soul id) from a 32-byte seed."""
    a, _ = _secret_scalar(seed)
    return _encodepoint(_scalarmult(_B, a))


def _Hint(m: bytes) -> int:
    h = _H(m)
    return sum(2 ** i * _bit(h, i) for i in range(2 * b))


def sign(msg: bytes, seed: bytes, pk: bytes | None = None) -> bytes:
    """Deterministically sign ``msg`` with the 32-byte ``seed``. Returns 64 bytes."""
    a, h = _secret_scalar(seed)
    if pk is None:
        pk = _encodepoint(_scalarmult(_B, a))
    r = _Hint(h[b // 8:b // 4] + msg)
    R = _scalarmult(_B, r)
    S = (r + _Hint(_encodepoint(R) + pk + msg) * a) % ell
    return _encodepoint(R) + _encodeint(S)


def _isoncurve(P) -> bool:
    x, y = P
    return (-x * x + y * y - 1 - _d * x * x * y * y) % q == 0


def _decodeint(s: bytes) -> int:
    return int.from_bytes(s, "little")


def _decodepoint(s: bytes):
    y = int.from_bytes(s, "little") & ((1 << (b - 1)) - 1)
    x = _xrecover(y)
    if x & 1 != _bit(s, b - 1):
        x = q - x
    P = [x, y]
    if not _isoncurve(P):
        raise ValueError("decoding point that is not on curve")
    return P


def verify(sig: bytes, msg: bytes, pk: bytes) -> bool:
    """True iff ``sig`` is a valid Ed25519 signature of ``msg`` under public key
    ``pk``. Never raises on a bad/garbage signature — returns False."""
    try:
        if len(sig) != b // 4 or len(pk) != b // 8:
            return False
        R = _decodepoint(sig[:b // 8])
        A = _decodepoint(pk)
        S = _decodeint(sig[b // 8:b // 4])
        h = _Hint(_encodepoint(R) + pk + msg)
        return _scalarmult(_B, S) == _edwards(R, _scalarmult(A, h))
    except (ValueError, IndexError):
        return False
