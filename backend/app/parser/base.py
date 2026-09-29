"""文本提取器接口（设计文档原则二：外部依赖可替换，测试时可换为固定输出的桩）。"""
from dataclasses import dataclass, field


@dataclass
class ExtractedDocument:
    """提取器统一输出：有序非空行 + 元信息。

    用"行"而非"大段文本"作为基本单位：章节切分、条目切分都以行为粒度，
    也让解析轨迹的 source_region 可以精确定位到行。
    """

    paragraphs: list[str] = field(default_factory=list)
    pages: int = 1
    source: str = ""


class TextExtractor:
    """所有提取器实现此接口。新增格式（如图片 OCR）只需新增一个实现类。"""

    name: str = "base"

    def extract(self, file_path: str) -> ExtractedDocument:  # pragma: no cover
        raise NotImplementedError
