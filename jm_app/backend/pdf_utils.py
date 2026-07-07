from pathlib import Path
from typing import Iterable, List

from PIL import Image


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


def collect_images(directory: Path) -> List[Path]:
    return sorted(
        path
        for path in directory.iterdir()
        if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
    )


def image_to_rgb(image: Image.Image) -> Image.Image:
    if image.mode == "RGB":
        return image.copy()
    if image.mode in {"RGBA", "LA"}:
        background = Image.new("RGB", image.size, "white")
        background.paste(image, mask=image.getchannel("A"))
        return background
    return image.convert("RGB")


def images_to_pdf(image_paths: Iterable[Path], pdf_path: Path):
    paths = list(image_paths)
    if not paths:
        raise ValueError("没有可写入 PDF 的图片")

    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    first = None
    rest = []
    try:
        for index, path in enumerate(paths):
            with Image.open(path) as image:
                rgb = image_to_rgb(image)
            if index == 0:
                first = rgb
            else:
                rest.append(rgb)
        first.save(pdf_path, "PDF", save_all=True, append_images=rest, resolution=100.0)
    finally:
        for image in rest:
            image.close()
        if first is not None:
            first.close()
