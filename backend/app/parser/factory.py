"""提取器工厂：按文件类型选择提取器。"""
from app.parser.base import ExtractedDocument, TextExtractor
from app.parser.docx_parser import DocxExtractor
from app.parser.image_parser import ImageExtractor
from app.parser.pdf_parser import PdfExtractor
from app.parser.text_parser import PlainTextExtractor

_EXTRACTORS: dict[str, TextExtractor] = {
    ".pdf": PdfExtractor(),
    ".docx": DocxExtractor(),
    ".txt": PlainTextExtractor(),
    ".md": PlainTextExtractor(),
    # 图片格式：统一走 OCR（后端可替换，见 image_parser 模块文档字符串）
    ".png": ImageExtractor(),
    ".jpg": ImageExtractor(),
    ".jpeg": ImageExtractor(),
    ".bmp": ImageExtractor(),
    ".webp": ImageExtractor(),
}


def get_extractor(file_type: str) -> TextExtractor | None:
    """file_type 为小写扩展名（如 .pdf）。不支持的类型返回 None → 上层报 1001。"""
    return _EXTRACTORS.get(file_type.lower())
