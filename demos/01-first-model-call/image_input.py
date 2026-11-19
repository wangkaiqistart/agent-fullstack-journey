"""两个看图示例共用的输入处理：本地图片 → Base64 data URL。"""

import argparse
import base64
from pathlib import Path


def read_image_input():
    # 默认图片按脚本位置定位，直接点击运行也能找到。
    default_image = Path(__file__).resolve().parent / "assets" / "multimodal-example.png"
    parser = argparse.ArgumentParser(description="真实模型图片理解示例")
    parser.add_argument(
        "image", nargs="?", default=str(default_image),
        help="本地 PNG/JPEG/WebP 路径，或模型服务可访问的 HTTPS 图片地址",
    )
    parser.add_argument(
        "--question",
        default="图中有几个彩色形状？分别是什么形状和颜色？最后读出底部的编号。用中文简短回答。",
        help="随图片一起发送给模型的问题",
    )
    args = parser.parse_args()

    # 网络图片只传地址；由远程模型服务获取图片，不在本机下载。
    if args.image.startswith("https://"):
        return args.image, args.question

    # MIME 类型必须与图片实际格式对应；改扩展名不会转换图片格式。
    path = Path(args.image).expanduser()
    mime_types = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
    }
    mime_type = mime_types.get(path.suffix.lower())
    if not mime_type:
        raise ValueError("请提供 PNG/JPEG/WebP 图片；SVG 或 PDF 需先转换为图片")
    try:
        image_bytes = path.read_bytes()
    except OSError:
        raise ValueError("无法读取图片，请检查文件路径和权限") from None
    if not image_bytes:
        raise ValueError("图片文件为空")

    # Base64 把二进制变成字符串，便于放入 JSON；它不会压缩或加密图片。
    image_base64 = base64.b64encode(image_bytes).decode("ascii")
    image_url = f"data:{mime_type};base64,{image_base64}"
    return image_url, args.question

