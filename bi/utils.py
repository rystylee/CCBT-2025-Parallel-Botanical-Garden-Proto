import base64
import random
import struct

from loguru import logger

P = 1  # num _prefix_token
H = 1536  # tokens_embed_size
VALS = [0.0, 1e-4, 1e-3, 1e-2]  # default fallback


def f32_to_bf16_u16(x: float) -> int:
    """float32 -> bf16 (truncate) -> u16"""
    u32 = struct.unpack("<I", struct.pack("<f", x))[0]
    return (u32 >> 16) & 0xFFFF


def make_soft_prefix_b64_constant(P: int, H: int, val: float) -> str:
    """arrange bf16 little-endian u16 in P*H groups to create base64"""
    u16 = f32_to_bf16_u16(val)
    raw = struct.pack("<H", u16) * (P * H)
    return base64.b64encode(raw).decode("ascii")


def make_random_soft_prefix_b64(config: dict | None = None) -> str:
    vals = VALS
    if config is not None:
        vals = config.get("stack_flow_llm", {}).get("soft_prefix_vals", VALS)
    v = random.choice(vals)

def override_soft_prefix_val(sp_b64: str, config: dict | None = None) -> str:
    """Replace the val in a received soft_prefix with a random val from config."""
    vals = VALS
    if config is not None:
        vals = config.get("stack_flow_llm", {}).get("soft_prefix_vals", VALS)
    v = random.choice(vals)
    logger.info(f"Override soft prefix val: {v}")
    return make_soft_prefix_b64_constant(P, H, v)
