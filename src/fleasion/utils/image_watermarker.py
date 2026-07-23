"""Asset ID watermarking + texture optimizer for intercepted Roblox textures.

* Watermarking  – draws the asset ID onto PNG, JPEG, and KTX2 images.
* Optimizer     – reduces texture quality (resize + JPEG compression) for
                  maximum performance.  Can be chained before watermarking.
"""

from __future__ import annotations

import io
import struct
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

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


# ── helpers ──────────────────────────────────────────────────────────


def _decompress_raw(data: bytes) -> bytes | None:
    """Decompress gzip/zstd wrapper; return raw bytes or *data* unchanged."""
    if not data:
        return None
    if data[:2] == _GZIP_MAGIC:
        import gzip

        try:
            return gzip.decompress(data)
        except Exception:
            return None
    if data[:4] == _ZSTD_MAGIC:
        try:
            import zstandard

            return zstandard.ZstdDecompressor().decompress(
                data, max_output_size=64 * 1024 * 1024
            )
        except Exception:
            return None
    return data


def _resize_down(img: Image.Image, max_size: int) -> Image.Image:
    """Downscale *img* so the longest side ≤ *max_size*."""
    w, h = img.size
    if w <= max_size and h <= max_size:
        return img
    ratio = min(max_size / w, max_size / h)
    new_size = (round(w * ratio), round(h * ratio))
    return img.resize(new_size, Image.LANCZOS)


# ── watermarking ─────────────────────────────────────────────────────


def watermark_image(data: bytes, asset_id: int | str, content_type: str = '') -> bytes | None:
    """Detect format and watermark the image.

    Returns modified bytes, or ``None`` if the format is unsupported or
    processing failed.
    """
    raw = _decompress_raw(data)
    if raw is None:
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


# ── texture optimizer ───────────────────────────────────────────────


def _decode_raw_to_pil(raw: bytes, ct: str) -> Image.Image | None:
    """Decode raw image bytes (PNG/JPEG/KTX2) to a PIL RGBA Image."""
    if raw[:12] == _KTX2_MAGIC and ('ktx2' in ct or ct in ('', 'application/octet-stream')):
        return _decode_ktx2_to_pil(raw)
    try:
        return Image.open(io.BytesIO(raw)).convert('RGBA')
    except Exception:
        return None


def _decode_ktx2_to_pil(data: bytes) -> Image.Image | None:
    """Decode KTX2 to PIL RGBA Image."""
    if _is_ktx2_uncompressed(data):
        result = read_rgba8_ktx2(data)
        if result is None:
            return None
        rgba, width, height = result
        arr = np.frombuffer(rgba, dtype=np.uint8).reshape(height, width, 4)
        return Image.fromarray(arr, 'RGBA')
    try:
        from ..cache.tools.orm_compositor import _decode_bc_ktx2

        arr, width, height = _decode_bc_ktx2(data)
        return Image.fromarray(arr, 'RGBA')
    except Exception:
        return None


def _is_alpha_used(img: Image.Image) -> bool:
    """Quick check whether an RGBA image actually uses alpha transparency."""
    if img.mode != 'RGBA':
        return False
    alpha = img.getchannel('A')
    extrema = alpha.getextrema()
    return extrema != (255, 255)


def _should_encode_as_jpeg(is_jpeg_original: bool, img: Image.Image, jpeg_quality: int) -> bool:
    """Heuristic: prefer JPEG output when quality ≤ 90 and image is opaque."""
    if jpeg_quality >= 95:
        return False  # near-lossless, no reason to switch
    if is_jpeg_original:
        return True
    return not _is_alpha_used(img)


_EXTREME_TEX_SIZE = 4  # px — tiny flat-color texture for extreme mode


def _average_color(img: Image.Image) -> tuple[int, ...]:
    """Return the mean color as an RGBA tuple rounded to int."""
    arr = np.asarray(img, dtype=np.float64)
    mean = arr.mean(axis=(0, 1)).round().astype(np.uint8)
    return tuple(mean)


def _make_extreme_texture(img: Image.Image, jpeg_quality: int) -> bytes:
    """Replace *img* with a tiny flat-color JPEG."""
    color = _average_color(img.convert('RGBA'))
    flat = Image.new('RGB', (_EXTREME_TEX_SIZE, _EXTREME_TEX_SIZE), color[:3])
    buf = io.BytesIO()
    flat.save(buf, format='JPEG', quality=jpeg_quality, optimize=True)
    return buf.getvalue()


def optimize_image(
    data: bytes,
    max_size: int = 512,
    jpeg_quality: int = 50,
    content_type: str = '',
    extreme: bool = False,
) -> bytes | None:
    """Downscale and/or re-encode a texture to reduce size.

    Returns the optimized bytes, or ``None`` if the format is unsupported
    or processing failed.

    * ``data``         – raw image bytes (may be gzip/zstd wrapped).
    * ``max_size``     – downscale so the longest side ≤ this value.
    * ``jpeg_quality`` – 1–100 quality for JPEG re-encoding (ignored for PNG/KTX2).
    * ``content_type`` – HTTP content-type hint for format detection.
    * ``extreme``      – when ``True``, replace texture with a 4×4 flat-color
                         JPEG of the average colour (aggressive optimisation).
    """
    raw = _decompress_raw(data)
    if raw is None:
        return None

    ct = content_type.lower()

    # ── detect original format ──
    is_jpeg = bool(raw[:3] == _JPEG_MAGIC or 'jpeg' in ct or 'jpg' in ct)
    is_png = bool(raw[:4] == _PNG_MAGIC or 'png' in ct)
    is_ktx2 = bool(
        raw[:12] == _KTX2_MAGIC and ('ktx2' in ct or ct in ('', 'application/octet-stream'))
    )

    if not (is_jpeg or is_png or is_ktx2):
        return None

    # ── decode ──
    if is_ktx2:
        img = _decode_ktx2_to_pil(raw)
    else:
        try:
            img = Image.open(io.BytesIO(raw)).convert('RGBA')
        except Exception:
            return None

    if img is None:
        return None

    # ── extreme mode – flat colour ──
    if extreme:
        return _make_extreme_texture(img, jpeg_quality)

    # ── resize ──
    img = _resize_down(img, max_size)

    # ── re-encode ──
    use_jpeg = _should_encode_as_jpeg(is_jpeg, img, jpeg_quality)

    if is_ktx2:
        # Keep as KTX2, just resized
        rgba_bytes = img.tobytes()
        try:
            import tempfile

            with tempfile.NamedTemporaryFile(suffix='.ktx2', delete=False) as tf:
                tmp_path = Path(tf.name)
            try:
                write_rgba8_ktx2(rgba_bytes, img.width, img.height, tmp_path)
                return tmp_path.read_bytes()
            finally:
                tmp_path.unlink(missing_ok=True)
        except Exception:
            return None

    if use_jpeg:
        buf = io.BytesIO()
        img.convert('RGB').save(buf, format='JPEG', quality=jpeg_quality, optimize=True)
        result = buf.getvalue()
    else:
        buf = io.BytesIO()
        img.save(buf, format='PNG', optimize=True)
        result = buf.getvalue()

    # Don't return if we somehow made it *larger* (unlikely, but be safe)
    if len(result) >= len(data):
        return None
    return result
