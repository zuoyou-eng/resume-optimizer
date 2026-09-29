"""图片 OCR 提取器（FR-01：支持图片格式上传）。

设计要点（对应设计文档原则二：外部依赖可替换、可隔离）：

1. **零硬依赖**：本机 Python 3.14 暂无 onnxruntime / paddlepaddle 的 wheel，
   本地 OCR 库（RapidOCR / PaddleOCR）无法安装。因此默认后端走
   **Windows 内置 WinRT OCR 引擎**（Windows.Media.Ocr，Win10/11 自带，
   支持中文与英文），通过 PowerShell 子进程调用，无需安装任何第三方包。

2. **后端可替换**：`OcrBackend` 协议与 `TextExtractor` 同构。将来 Python
   出现 OCR wheel 时，只需新增一个后端实现并在 `_BACKENDS` 注册，
   上层（上传 → 解析 → 结构化）完全不用改。

3. **优雅降级**：OCR 引擎不可用（非 Windows / 未装语言包 / PowerShell 缺失）时
   抛出带可操作提示的 BizError，而不是让请求崩溃或返回静默空结果。

4. **两个 OCR 特有的后处理**（这是 OCR 能接进结构化引擎的关键）：
   - **字间空白规整**：OCR 常把「姓 名 ： 张 三」这类中文按字切开，
     若不处理，章节关键词（如"教育背景"）永远匹配不上。
   - **阅读顺序还原**：OCR 引擎逐行返回且不保证阅读顺序，必须按坐标重排，
     否则两栏简历会被读成"左右交错"的乱序文本。
"""
from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass

from app.config import settings
from app.errors import BizError, ErrorCode
from app.parser.base import ExtractedDocument, TextExtractor

# ---- OCR 后端协议：与 TextExtractor 同构，便于替换 ----
class OcrBackend:
    """OCR 后端协议：输入图片绝对路径，返回带坐标的文本行。"""

    name: str = "base"

    def recognize(self, file_path: str) -> list["OcrLine"]:  # pragma: no cover
        raise NotImplementedError


@dataclass
class OcrLine:
    """一行 OCR 结果：文本 + 左上角坐标（用于还原阅读顺序）。"""

    text: str
    top: float = 0.0
    left: float = 0.0


# ---- 后端一：Windows 内置 WinRT OCR（零依赖，默认） ----
_PS_SCRIPT = r"""
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType=WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Foundation, ContentType=WindowsRuntime]
$null = [Windows.Storage.StorageFile, Windows.Foundation, ContentType=WindowsRuntime]
$null = [Windows.Globalization.Language, Windows.Foundation, ContentType=WindowsRuntime]

function Await($op, $type) {
    $m = [System.WindowsRuntimeSystemExtensions].GetMethods() |
        Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 `
            -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' } |
        Select-Object -First 1
    if ($m) {
        $task = $m.MakeGenericMethod($type).Invoke($null, @($op))
        $task.Wait()
        return $task.Result
    }
    return $null
}

$path = $env:RESUME_OCR_PATH
if (-not $path -or -not (Test-Path $path)) { exit 3 }
# 规范化为 Windows 路径（反斜杠）：WinRT 的 StorageFile 不接受正斜杠相对路径
$path = (Resolve-Path $path).Path

$file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($path)) ([Windows.Storage.StorageFile])
$stream = Await ($file.OpenAsync(0)) ([Windows.Storage.Streams.IRandomAccessStream])
$decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
$bitmap = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])

# 优先中文，其次英文，最后退回用户配置文件语言
$engine = $null
foreach ($tag in @('zh-Hans-CN', 'zh-CN', 'en-US')) {
    $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage([Windows.Globalization.Language]::new($tag))
    if ($null -ne $engine) { break }
}
if ($null -eq $engine) { $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages() }
if ($null -eq $engine) { exit 4 }

$result = Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
$sb = New-Object Text.StringBuilder
foreach ($line in $result.Lines) {
    # WinRT 互操作的两处 PowerShell 投影陷阱（均实测确认）：
    # 1) $line.Words[0] 实际返回整行所有词，.BoundingRect 因而得到一组 Rect；
    #    取其第一个即为该行最左/最上的词，正好是还原阅读顺序需要的锚点。
    # 2) Rect 的 X/Y 取值为 Object[]，不能强转 [double]（会抛转换异常），
    #    但字符串化后是空格分隔的数值列表，取首项即可。
    $top = '0'
    $left = '0'
    try {
        $rect = $line.Words[0].BoundingRect
        $top = ("$($rect.Y)" -split ' ')[0]
        $left = ("$($rect.X)" -split ' ')[0]
        if (-not $top) { $top = '0' }
        if (-not $left) { $left = '0' }
    } catch { }
    [void]$sb.Append($top)
    [void]$sb.Append("`t")
    [void]$sb.Append($left)
    [void]$sb.Append("`t")
    [void]$sb.Append($line.Text)
    [void]$sb.Append("`n")
}
[Console]::Out.Write($sb.ToString())
"""


class WindowsOcrBackend(OcrBackend):
    """调用 Windows 内置 WinRT OCR 引擎（Windows.Media.Ocr）。

    通过 PowerShell 子进程执行；路径经环境变量传递，避免命令行编码问题
    （中文路径在 Windows 命令行上极易乱码）。
    """

    name = "windows-ocr"

    def __init__(self, timeout_seconds: int | None = None):
        self.timeout = timeout_seconds or settings.OCR_TIMEOUT_SECONDS

    def recognize(self, file_path: str) -> list[OcrLine]:
        if sys.platform != "win32":
            raise BizError(
                ErrorCode.PARSE_FAILED,
                "图片 OCR 需要 Windows 10/11 自带的识别引擎；当前运行环境不支持，"
                "请改用 PDF 或 Word 格式的简历",
            )

        cmd = [
            "powershell",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            _PS_SCRIPT,
        ]
        env = {**__import__("os").environ, "RESUME_OCR_PATH": file_path}

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout,
                env=env,
            )
        except subprocess.TimeoutExpired as e:
            raise BizError(
                ErrorCode.PARSE_FAILED, f"图片 OCR 识别超时（>{self.timeout}s），请重试"
            ) from e
        except FileNotFoundError as e:  # pragma: no cover - 无 PowerShell 的极端环境
            raise BizError(
                ErrorCode.PARSE_FAILED, "未找到 PowerShell，无法调用系统 OCR 引擎"
            ) from e

        # 退出码约定：3=路径无效，4=无可用 OCR 语言包
        if proc.returncode == 4:
            raise BizError(
                ErrorCode.PARSE_FAILED,
                "系统未安装 OCR 语言包。请在「设置 → 时间和语言 → 语言和区域」中"
                "添加中文语言包后重试",
            )
        if proc.returncode != 0:
            detail = (proc.stderr or "").strip().splitlines()
            tail = detail[-1] if detail else f"exit={proc.returncode}"
            raise BizError(ErrorCode.PARSE_FAILED, f"图片 OCR 识别失败：{tail}")

        return self._parse_output(proc.stdout)

    @staticmethod
    def _parse_output(stdout: str) -> list[OcrLine]:
        """解析 `top\tleft\ttext` 行；坐标缺失时退化为文档顺序。"""
        lines: list[OcrLine] = []
        for raw in stdout.splitlines():
            if not raw.strip():
                continue
            parts = raw.split("\t", 2)
            if len(parts) == 3:
                try:
                    top, left = float(parts[0]), float(parts[1])
                except ValueError:
                    lines.append(OcrLine(text=parts[2].strip()))
                    continue
                lines.append(OcrLine(text=parts[2].strip(), top=top, left=left))
            else:
                lines.append(OcrLine(text=raw.strip()))
        return [ln for ln in lines if ln.text]


# 后端注册表：将来有 Python OCR wheel 时在此追加即可
_BACKENDS: list[OcrBackend] = [WindowsOcrBackend()]


# ---- 后处理：字间空白规整 ----
_CJK = r"一-鿿㐀-䶿"
_CJK_PUNCT = r"　-〿！-｜"  # 全角标点：，。、；：？！（）《》【】等
# 中文汉字之间 / 汉字与中文标点之间的空格：OCR 常见伪影，直接删除
_SPACED_CJK_RE = re.compile(
    rf"(?<=[{_CJK}{_CJK_PUNCT}])[ \t]+(?=[{_CJK}{_CJK_PUNCT}])"
)
# 全角标点与数字之间的空格："（ 2022 ）" → "（2022）"
_PUNCT_DIGIT_SPACE_RE = re.compile(
    rf"(?<=[{_CJK_PUNCT}])[ \t]+(?=\d)|(?<=\d)[ \t]+(?=[{_CJK_PUNCT}])"
)
_WHITESPACE_RUN_RE = re.compile(r"[ \t]{2,}")
# OCR 系统性伪影：全角间隔号"．"(U+FF0E) 常被用于日期分隔，结构化引擎只认半角 "."
_FULLWIDTH_DOT_RE = re.compile(r"[．·]")
# 汉字"一"夹在两个数字之间：OCR 把日期区间的连字符误识成"一"
# （结构化引擎的区间分隔只认 - – — ~ 至，不含"一"）
_CJK_ONE_BETWEEN_DIGITS_RE = re.compile(r"(?<=\d)\s*一\s*(?=\d)")
# 数字之间的空格："1 0 万次" → "10 万次"（手机号 11 位连写否则匹配不上）
_DIGIT_SPACE_DIGIT_RE = re.compile(r"(?<=\d)[ \t]+(?=\d)")
# 数字与中文之间的空格："10 万次" → "10万次"
_DIGIT_CJK_SPACE_RE = re.compile(r"(?<=\d)[ \t]+(?=[一-鿿])")
_CJK_DIGIT_SPACE_RE = re.compile(r"(?<=[一-鿿])[ \t]+(?=\d)")
# 数字与小数点之间的空格："2021 . 09" → "2021.09"（日期分隔符被 OCR 拆开）
_DOT_SPACE_RE = re.compile(r"(?<=\d)[ \t]*\.[ \t]*(?=\d)")
# OCR 常把中文顿号"、"误识为英文句点："FastAPI. MySQL" 应为 "FastAPI、MySQL"，
# 导致技能列表最后几项被粘成一项。仅在「本行已是列表」时才替换——
# 英文散文的句末标点不会被误判（散文行不会同时含有 、 , ， 等分隔符）。
_LIST_DELIM_RE = re.compile(r"[、,，/|;；]")
_MISREAD_LIST_DOT_RE = re.compile(r"(?<=[A-Za-z0-9])\.\s+(?=[A-Za-z])")


def _fix_misread_list_dots(text: str) -> str:
    if not _LIST_DELIM_RE.search(text):
        return text
    return _MISREAD_LIST_DOT_RE.sub("、", text)


def normalize_ocr_line(text: str) -> str:
    """规整单行 OCR 文本的字间空白与系统性识别伪影。

    只删「中文与中文之间」的空格，保留中英之间的空格——
    「使用 Python 与 FastAPI」这类技术名词分隔必须留着，
    否则技能切分与 JD 匹配都会失真。
    """
    text = _SPACED_CJK_RE.sub("", text)
    text = _WHITESPACE_RUN_RE.sub(" ", text)
    text = _FULLWIDTH_DOT_RE.sub(".", text)
    text = _CJK_ONE_BETWEEN_DIGITS_RE.sub("-", text)
    text = _PUNCT_DIGIT_SPACE_RE.sub("", text)
    text = _DOT_SPACE_RE.sub(".", text)
    text = _fix_misread_list_dots(text)
    text = _DIGIT_SPACE_DIGIT_RE.sub("", text)
    text = _DIGIT_CJK_SPACE_RE.sub("", text)
    text = _CJK_DIGIT_SPACE_RE.sub("", text)
    return text.strip()


# ---- 后处理：阅读顺序还原 ----
def restore_reading_order(lines: list[OcrLine], page_width: float = 1000.0) -> list[OcrLine]:
    """把 OCR 行按版面重排为阅读顺序。

    单栏：按 top 聚成行、行内按 left 排序即可。
    两栏（简历常见）：若行的起点在横向上明显分成两簇且中间有足够宽的空白带，
    则按「左栏读完再读右栏」处理，避免左右交错。
    """
    if len(lines) < 2:
        return lines

    sorted_by_top = sorted(lines, key=lambda ln: (ln.top, ln.left))
    columns = _split_columns(sorted_by_top, page_width)
    if columns is None:
        return _sort_rows(sorted_by_top)
    return [ln for col in columns for ln in _sort_rows(col)]


def _split_columns(
    lines: list[OcrLine], page_width: float
) -> list[list[OcrLine]] | None:
    """检测两栏版面；不是两栏则返回 None。"""
    if len(lines) < 4:
        return None
    lefts = sorted(ln.left for ln in lines)
    # 找相邻起点间最大的空白带作为候选分栏线
    best_gap, best_at = 0.0, -1
    for i in range(len(lefts) - 1):
        gap = lefts[i + 1] - lefts[i]
        if gap > best_gap:
            best_gap, best_at = gap, i
    if best_at < 0 or best_gap < page_width * 0.12:
        return None

    split = (lefts[best_at] + lefts[best_at + 1]) / 2
    left_col = [ln for ln in lines if ln.left < split]
    right_col = [ln for ln in lines if ln.left >= split]
    # 两栏都必须有实质内容，否则视为单栏中的孤立缩进
    if len(left_col) < 2 or len(right_col) < 2:
        return None
    return [left_col, right_col]


def _sort_rows(lines: list[OcrLine], row_tolerance: float = 6.0) -> list[OcrLine]:
    """按纵向位置聚成行，行内按横向排序；容差内视为同一行。"""
    rows: list[list[OcrLine]] = []
    for ln in sorted(lines, key=lambda x: (x.top, x.left)):
        if rows and abs(ln.top - rows[-1][0].top) <= row_tolerance:
            rows[-1].append(ln)
        else:
            rows.append([ln])
    out: list[OcrLine] = []
    for row in rows:
        out.extend(sorted(row, key=lambda x: x.left))
    return out


# ---- 提取器 ----
class ImageExtractor(TextExtractor):
    """图片提取器：OCR 识别 → 空白规整 → 阅读顺序还原 → 交给结构化引擎。"""

    name = "windows-ocr"

    def extract(self, file_path: str) -> ExtractedDocument:
        backend = self._pick_backend()
        raw_lines = backend.recognize(file_path)

        if not raw_lines:
            # OCR 成功但一个字都没识别到：图片可能是空白/纯图形
            return ExtractedDocument(paragraphs=[], pages=1, source=backend.name)

        page_width = max((ln.left for ln in raw_lines), default=0.0) + 200.0
        ordered = restore_reading_order(raw_lines, page_width=page_width)

        paragraphs: list[str] = []
        for ln in ordered:
            text = normalize_ocr_line(ln.text)
            if text:
                paragraphs.append(text)

        return ExtractedDocument(
            paragraphs=paragraphs, pages=1, source=backend.name
        )

    @staticmethod
    def _pick_backend() -> OcrBackend:
        """按注册顺序挑选第一个可用后端。当前仅 Windows 内置引擎。"""
        return _BACKENDS[0]
