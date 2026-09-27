"""图片处理：把截图压成适合手机端加载的 JPEG。

背景：此前 webui 的「粘贴截图」把 PNG 原样落盘，实测出现过单张 2.28 MB 的图
（而且内容往往只是源站 logo）。移动端首屏要等好几秒才显示，读者在图片加载完
之前就划走了；公众号/头条的图片上传也容易失败。

这里统一做：限宽 + 转 RGB（处理透明通道）+ JPEG 渐进式编码。
"""
from __future__ import annotations

import io

from PIL import Image, ImageSequence, UnidentifiedImageError

# 手机端正文宽度约 700~1080px，超过这个宽度对读者无意义，只增加体积
DEFAULT_MAX_WIDTH = 1080
DEFAULT_QUALITY = 82


def _flatten_to_rgb(img: Image.Image) -> Image.Image:
    """JPEG 不支持透明通道，含 alpha 的图先合成到白底上。"""
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        rgba = img.convert("RGBA")
        white = Image.new("RGB", rgba.size, (255, 255, 255))
        white.paste(rgba, mask=rgba.split()[-1])
        return white
    return img.convert("RGB")


def compress_to_jpeg(
    data: bytes,
    max_width: int = DEFAULT_MAX_WIDTH,
    quality: int = DEFAULT_QUALITY,
) -> tuple[bytes, bool]:
    """把任意常见图片字节压成 JPEG。

    返回 (jpeg 字节, 是否真的变小了)。无法识别或压缩后反而更大时，原样返回
    (data, False)，由调用方决定保留原文件——压图绝不能比不压更差。
    """
    try:
        with Image.open(io.BytesIO(data)) as src:
            # 动图只取第一帧：日报截图不需要动图
            frame = next(ImageSequence.Iterator(src))
            img = _flatten_to_rgb(frame)
            if max_width and img.width > max_width:
                ratio = max_width / img.width
                img = img.resize(
                    (max_width, max(1, round(img.height * ratio))),
                    Image.LANCZOS,
                )
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=quality, optimize=True, progressive=True)
    except (UnidentifiedImageError, OSError, ValueError):
        return data, False
    out = buf.getvalue()
    if not out or len(out) >= len(data):
        return data, False
    return out, True


def jpeg_bytes_from_png_file(path) -> tuple[bytes, bool]:
    return compress_to_jpeg(path.read_bytes())
