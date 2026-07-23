"""Asset ID watermarking for intercepted Roblox textures.

Draws the asset ID (in red, top-left corner) onto PNG, JPEG, and
uncompressed KTX2 images so the ID is visible in-game.
"""

from __future__ import annotations

import io
import struct
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from ..cache.tools.rgba_ktx2 import (
    VK_FORMAT_R8G8B8A8_UNORM,
    KTX2_MAGIC,
    read_rgba8_ktx2,
    write_rgba8_ktx2,
)

_KTX2_MAGIC = KTX2_MAGIC
_PNG_MAGIC = b'\x89PNG\r\n\x1a\n'
_JPEG_MAGIC = b'\xff\xd8\xff'
_GZIP_MAGIC = b'\x1f\x8b'
_ZSTD_MAGIC = b'\x28\xb5\x2f\xfd'

_TEXT_COLOR = (255, 0, 0)
_TEXT_PADDING = 6


def _draw_id_on_image(img: Image.Image, asset_id: int | str) -> Image.Image:
    draw = ImageDraw.Draw(img)
    text = str(asset_id)
    bbox = draw.textbbox((0, 0), text)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    x = _TEXT_PADDING
    y = _TEXT_PADDING
    # semi-transparent background for readability
    bg_margin = 2
    draw.rectangle(
        [x - bg_margin, y - bg_margin, x + tw + bg_margin, y + th + bg_margin],
        fill=(0, 0, 0, 160),
    )
    draw.text((x, y), text, fill=_TEXT_COLOR)
    return img


def watermark_png(data: bytes, asset_id: int | str) -> bytes:
    img = Image.open(io.BytesIO(data)).convert('RGBA')
    img = _draw_id_on_image(img, asset_id)
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    return buf.getvalue()


def watermark_jpeg(data: bytes, asset_id: int | str) -> bytes:
    img = Image.open(io.BytesIO(data)).convert('RGBA')
    img = _draw_id_on_image(img, asset_id)
    buf = io.BytesIO()
    # convert back to RGB for JPEG
    img.convert('RGB').save(buf, format='JPEG', quality=90)
    return buf.getvalue()


def _is_ktx2_uncompressed(data: bytes) -> bool:
    """Check if this is an uncompressed RGBA8 KTX2 we can decode directly."""
    if len(data) < 104 or data[:12] != KTX2_MAGIC:
        return False
    vk_fmt, _ts, _w, _h, _d, _lc, _fc, _lc2, sc = struct.unpack_from('<9I', data, 12)
    return vk_fmt == VK_FORMAT_R8G8B8A8_UNORM and sc == 0


def watermark_ktx2(data: bytes, asset_id: int | str) -> bytes | None:
    """Watermark a KTX2 texture.

    Supports uncompressed RGBA8 KTX2 natively.  For BC1/BC3 compressed KTX2,
    decompresses to RGBA, draws, then re-encodes as uncompressed RGBA8 KTX2.
    """
    if data[:12] != KTX2_MAGIC:
        return None

    if _is_ktx2_uncompressed(data):
        result = read_rgba8_ktx2(data)
        if result is None:
            return None
        rgba, width, height = result
        arr = np.frombuffer(rgba, dtype=np.uint8).reshape(height, width, 4)
    else:
        # Try decoding compressed KTX2 (BC1/BC3) via orm_compositor logic
        try:
            from ..cache.tools.orm_compositor import _decode_bc_ktx2

            arr, width, height = _decode_bc_ktx2(data)
        except Exception:
            return None

    img = Image.fromarray(arr, 'RGBA')
    img = _draw_id_on_image(img, asset_id)
    rgba_bytes = img.tobytes()
    try:
        import tempfile

        with tempfile.NamedTemporaryFile(suffix='.ktx2', delete=False) as tf:
            tmp_path = Path(tf.name)
        try:
            write_rgba8_ktx2(rgba_bytes, width, height, tmp_path)
            result_bytes = tmp_path.read_bytes()
            return result_bytes
        finally:
            tmp_path.unlink(missing_ok=True)
    except Exception:
        return None


def watermark_image(data: bytes, asset_id: int | str, content_type: str = '') -> bytes | None:
    """Detect format and watermark the image.

    Returns modified bytes, or ``None`` if the format is unsupported or
    processing failed.
    """
    if not data:
        return None

    # Decompress gzip/zstd wrapper if present
    raw = data
    if data[:2] == _GZIP_MAGIC:
        import gzip

        try:
            raw = gzip.decompress(data)
        except Exception:
            return None
    elif data[:4] == _ZSTD_MAGIC:
        try:
            import zstandard

            raw = zstandard.ZstdDecompressor().decompress(
                data, max_output_size=64 * 1024 * 1024
            )
        except Exception:
            return None

    ct = content_type.lower()
    if raw[:12] == _KTX2_MAGIC and ('ktx2' in ct or ct in ('', 'application/octet-stream')):
        result = watermark_ktx2(raw, asset_id)
        if result is not None:
            return result
    if raw[:4] == _PNG_MAGIC or 'png' in ct:
        return watermark_png(raw, asset_id)
    if raw[:3] == _JPEG_MAGIC or 'jpeg' in ct or 'jpg' in ct:
        return watermark_jpeg(raw, asset_id)

    return None
