"""纯文本 / Markdown 提取器。编码探测：utf-8 优先，gbk 回退。"""
from app.parser.base import ExtractedDocument, TextExtractor


class PlainTextExtractor(TextExtractor):
    name = "plain-text"

    def extract(self, file_path: str) -> ExtractedDocument:
        text = self._read(file_path)
        lines = [ln.strip() for ln in text.splitlines()]
        paragraphs = [ln for ln in lines if ln]
        return ExtractedDocument(paragraphs=paragraphs, pages=1, source=self.name)

    @staticmethod
    def _read(file_path: str) -> str:
        raw = open(file_path, "rb").read()
        for encoding in ("utf-8", "gb18030", "gbk", "latin-1"):
            try:
                return raw.decode(encoding)
            except UnicodeDecodeError:
                continue
        return raw.decode("utf-8", errors="replace")
