import base64
import random
import struct

from loguru import logger

P = 1  # num _prefix_token
# H = 896  # tokens_embed_size
H = 1536  # tokens_embed_size
VALS = [0.0, 1e-4, 1e-3, 1e-2, 5e-2, 1e-1, 2e-1, 5e-1, 1.0, 2.0]


def f32_to_bf16_u16(x: float) -> int:
    """float32 -> bf16 (truncate) -> u16"""
    u32 = struct.unpack("<I", struct.pack("<f", x))[0]
    return (u32 >> 16) & 0xFFFF


def make_soft_prefix_b64_constant(P: int, H: int, val: float) -> str:
    """arrange bf16 little-endian u16 in P*H groups to create base64"""
    u16 = f32_to_bf16_u16(val)
    raw = struct.pack("<H", u16) * (P * H)
    return base64.b64encode(raw).decode("ascii")


def make_random_soft_prefix_b64() -> str:
    v = random.choice(VALS)
    logger.info(f"Selected soft prefix value: {v}")
    sp_b64 = make_soft_prefix_b64_constant(P, H, v)
    return sp_b64
