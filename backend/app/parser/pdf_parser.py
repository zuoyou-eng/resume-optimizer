"""PDF 提取器：pdfplumber（纯 Python 生态，跨平台兼容性好；PyMuPDF 为备选方案）。

依赖延迟导入：未安装 pdfplumber 时不影响其他格式与其他模块加载
（设计文档原则二：外部依赖可替换、可隔离）。
"""
from app.errors import BizError, ErrorCode
from app.parser.base import ExtractedDocument, TextExtractor


class PdfExtractor(TextExtractor):
    name = "pdfplumber"

    def extract(self, file_path: str) -> ExtractedDocument:
        try:
            import pdfplumber
        except ImportError as e:  # pragma: no cover
            raise BizError(
                ErrorCode.PARSE_FAILED, "PDF 解析依赖未安装（pdfplumber）"
            ) from e

        paragraphs: list[str] = []
        pages = 0
        try:
            with pdfplumber.open(file_path) as pdf:
                pages = len(pdf.pages)
                for page in pdf.pages:
                    text = page.extract_text() or ""
                    # 图片版 PDF 提取不到文本 → 交给上层判定为空内容（1003）
                    paragraphs.extend(
                        ln.strip() for ln in text.splitlines() if ln.strip()
                    )
        except Exception as e:
            raise BizError(ErrorCode.PARSE_FAILED, f"PDF 解析失败：{e}") from e

        return ExtractedDocument(paragraphs=paragraphs, pages=pages, source=self.name)
