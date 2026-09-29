"""图片 OCR 提取器测试（FR-01：支持图片格式上传）。

分三层，与设计文档 8.1 的测试分层对应：
  A. 纯逻辑层（必跑）：OCR 后处理与阅读顺序还原，零外部依赖、零随机性
  B. 安全校验层（必跑）：图片魔术字节校验，防伪装文件（NFR-05）
  C. 真实 OCR 层（条件跳过）：仅在 Windows 且系统 OCR 引擎可用时运行

C 层刻意做成条件跳过而非 mock：OCR 的正确性只能用真实引擎验证，
mock 只能证明"我调用了它"，证明不了"它读对了"。
"""
import os
import sys
from io import BytesIO

import pytest

from app.errors import BizError, ErrorCode
from app.parser.image_parser import (
    ImageExtractor,
    OcrLine,
    WindowsOcrBackend,
    _split_columns,
    normalize_ocr_line,
    restore_reading_order,
)


# ---------- A. 纯逻辑层 ----------
class TestOcrNormalization:
    """OCR 系统性伪影规整：每一条都对应实测遇到过的真实识别错误。"""

    def test_cjk_char_spacing_removed(self):
        """OCR 把中文按字切开：「姓 名 ： 张 三」→「姓名：张三」。"""
        assert normalize_ocr_line("姓 名 ： 张 三") == "姓名：张三"
        assert normalize_ocr_line("教 育 背 景") == "教育背景"

    def test_latin_cjk_boundary_space_kept(self):
        """中英之间的空格必须保留，否则技能切分与 JD 匹配都会失真。"""
        assert normalize_ocr_line("使用 Python 与 FastAPI") == "使用 Python 与 FastAPI"

    def test_fullwidth_dot_to_halfwidth(self):
        """全角间隔号"．"(U+FF0E) 是 OCR 常见日期分隔伪影。"""
        assert normalize_ocr_line("2021 ． 09 一 2025 ． 06") == "2021.09-2025.06"

    def test_cjk_one_as_date_hyphen(self):
        """汉字"一"夹在数字之间 = 被误识的日期连字符。"""
        assert normalize_ocr_line("2023.06 一 2023.12") == "2023.06-2023.12"

    def test_digit_spacing_collapsed(self):
        """手机号与数量被按位切开：1 0 → 10。"""
        assert normalize_ocr_line("日均支撑 1 0 万次调用") == "日均支撑10万次调用"

    def test_punct_digit_spacing_removed(self):
        assert normalize_ocr_line("校级优秀学生奖学金（ 2022 ）") == "校级优秀学生奖学金（2022）"

    def test_contact_line_joined(self):
        assert normalize_ocr_line("电话： 13800138000 邮箱： wangwu@example.com") == (
            "电话：13800138000邮箱： wangwu@example.com"
        )

    def test_misread_list_dot_fixed_in_list_line(self):
        """行内已是列表时，把误识成句点的顿号还原——否则技能最后几项被粘成一项。"""
        assert normalize_ocr_line("Photoshop 、 Python 、 FastAPl. MySQL") == (
            "Photoshop 、 Python 、 FastAPl、MySQL"
        )

    def test_misread_list_dot_not_applied_to_prose(self):
        """安全底线：英文散文的句末标点绝不能被当成列表分隔符。"""
        for prose in ("Built APIs. Led the team.", "e.g. FastAPI is great."):
            assert normalize_ocr_line(prose) == prose

    def test_empty_and_whitespace(self):
        assert normalize_ocr_line("") == ""
        assert normalize_ocr_line("   ") == ""


class TestReadingOrder:
    """阅读顺序还原：OCR 引擎不保证返回顺序，必须按坐标重排。"""

    def test_single_line_untouched(self):
        assert restore_reading_order([OcrLine("only", 10, 10)]) == [OcrLine("only", 10, 10)]

    def test_single_column_sorted_by_top(self):
        lines = [OcrLine("C", 50, 10), OcrLine("A", 0, 10), OcrLine("B", 25, 10)]
        assert [ln.text for ln in restore_reading_order(lines)] == ["A", "B", "C"]

    def test_two_column_read_left_column_first(self):
        """两栏简历必须「左栏读完再读右栏」，否则会读成左右交错的乱序文本。"""
        lines = [
            OcrLine("左一", 0, 10),
            OcrLine("右一", 0, 600),
            OcrLine("左二", 40, 10),
            OcrLine("右二", 40, 600),
        ]
        assert [ln.text for ln in restore_reading_order(lines)] == ["左一", "左二", "右一", "右二"]

    def test_row_tolerance_groups_same_line(self):
        """同一行内高度差在容差内的片段按横向排序。"""
        lines = [OcrLine("右", 10, 200), OcrLine("左", 12, 10)]
        assert [ln.text for ln in restore_reading_order(lines)] == ["左", "右"]

    def test_narrow_indent_not_treated_as_column(self):
        """右侧只有孤立缩进（不足 2 行）时不拆栏，避免把单栏读成两栏。"""
        lines = [OcrLine("A", 0, 10), OcrLine("B", 30, 10), OcrLine("C", 60, 400)]
        assert [ln.text for ln in restore_reading_order(lines)] == ["A", "B", "C"]

    def test_split_columns_requires_enough_lines(self):
        assert _split_columns([OcrLine("a", 0, 10), OcrLine("b", 0, 500)], 1000) is None


class TestOutputParsing:
    """后端输出解析：坐标缺失时退化为文档顺序，不能丢行。"""

    def test_parse_with_coordinates(self):
        out = "44\t19\t姓名：张三\n103\t20\t教育背景\n"
        lines = WindowsOcrBackend._parse_output(out)
        assert len(lines) == 2
        assert lines[0].text == "姓名：张三"
        assert (lines[0].top, lines[0].left) == (44.0, 19.0)

    def test_parse_without_coordinates(self):
        assert WindowsOcrBackend._parse_output("just text\n")[0].text == "just text"

    def test_parse_skips_blank_lines(self):
        assert WindowsOcrBackend._parse_output("a\n\n  \nb\n") == [OcrLine("a"), OcrLine("b")]

    def test_parse_bad_coordinate_falls_back(self):
        lines = WindowsOcrBackend._parse_output("notanumber\t20\t文本\n")
        assert lines[0].text == "文本"
        assert (lines[0].top, lines[0].left) == (0.0, 0.0)


class TestGracefulDegradation:
    """依赖缺失/平台不符时必须给出可操作提示，而不是崩溃或静默返回空。"""

    def test_non_windows_raises_actionable_error(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "linux")
        with pytest.raises(BizError) as exc:
            WindowsOcrBackend().recognize("/tmp/x.png")
        assert exc.value.code == ErrorCode.PARSE_FAILED
        assert "PDF 或 Word" in exc.value.message

    def test_missing_file_exit_code(self, monkeypatch):
        """路径不存在时后端以退出码 3 结束，Python 侧转为解析失败而非崩溃。"""
        if sys.platform != "win32":
            pytest.skip("OCR 仅 Windows 可用")
        with pytest.raises(BizError) as exc:
            WindowsOcrBackend(timeout_seconds=30).recognize("Z:\\不存在的文件.png")
        assert exc.value.code == ErrorCode.PARSE_FAILED


# ---------- B. 安全校验层：图片魔术字节 ----------
class TestImageMagicBytes:
    """图片格式必须过魔术字节校验，防止把可执行文件改名成 .png 上传（NFR-05）。"""

    def test_png_signature_accepted(self):
        assert _magic_ok_png(b"\x89PNG\r\n\x1a\n" + b"rest")

    def test_exe_renamed_to_png_rejected(self):
        assert not _magic_ok_png(b"MZ\x90\x00" + b"\x00" * 100)

    def test_pdf_renamed_to_png_rejected(self):
        assert not _magic_ok_png(b"%PDF-1.7 ...")

    def test_webp_requires_composite_signature(self):
        """WebP 的 RIFF 与 WAV/AVI 共用，必须再看第 8 字节起的 WEBP。"""
        from app.services.resume_service import _magic_ok

        wav_renamed = b"RIFF" + b"\x10\x00\x00\x00" + b"WAVEfmt "
        assert not _magic_ok(".webp", wav_renamed), "WAV 改名成 .webp 必须被拒"
        real_webp = b"RIFF" + b"\x10\x00\x00\x00" + b"WEBPVP8 "
        assert _magic_ok(".webp", real_webp)

    def test_docx_alternatives_still_work(self):
        """回归：docx 的 PK\\x03\\x04 与 PK\\x05\\x06 是「任一」而非「全部」命中。"""
        from app.services.resume_service import _magic_ok

        assert _magic_ok(".docx", b"PK\x03\x04" + b"\x00" * 50)
        assert _magic_ok(".docx", b"PK\x05\x06" + b"\x00" * 50)
        assert not _magic_ok(".docx", b"PK\x01\x02" + b"\x00" * 50)

    def test_pdf_signature_unaffected(self):
        from app.services.resume_service import _magic_ok

        assert _magic_ok(".pdf", b"%PDF-1.4\n...")
        assert not _magic_ok(".pdf", b"\x89PNG\r\n\x1a\n")


def _magic_ok_png(content: bytes) -> bool:
    from app.services.resume_service import _magic_ok

    return _magic_ok(".png", content)


# ---------- C. 真实 OCR 层 ----------
def _find_cjk_font() -> str | None:
    """找一款系统中文字体；找不到则跳过真实 OCR 测试（不伪造通过）。"""
    candidates = [
        "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/simhei.ttf",
        "C:/Windows/Fonts/simsun.ttc",
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return None


def _render_resume_image(path: str, font_path: str) -> None:
    """用 Pillow 渲染一份与 examples/sample-resume.txt 同构的简历图片。"""
    from PIL import Image, ImageDraw, ImageFont

    def font(sz):
        return ImageFont.truetype(font_path, sz)

    img = Image.new("RGB", (900, 1200), "white")
    draw = ImageDraw.Draw(img)
    y = 50

    def line(text, size=26, x=60):
        nonlocal y
        draw.text((x, y), text, fill="black", font=font(size))
        y += int(size * 1.5)

    line("王五", 40)
    line("电话：13800138000    邮箱：wangwu@example.com", 22)
    line("求职意向：后端开发工程师", 22)
    y += 20
    line("教育背景", 30)
    line("南京大学  软件工程  本科  2021.09-2025.06", 24)
    y += 20
    line("实习经历", 30)
    line("某科技公司  后端开发实习生  2023.06-2023.12", 24)
    line("参与订单服务接口开发，使用 Python 与 FastAPI，日均支撑 10 万次调用", 22)
    y += 20
    line("项目经历", 30)
    line("分布式秒杀系统  核心开发  2023.03-2023.05", 24)
    line("设计库存扣减方案，QPS 从 800 提升到 3000", 22)
    y += 20
    line("专业技能", 30)
    line("Photoshop、Python、FastAPI、MySQL", 24)
    y += 20
    line("荣誉奖项", 30)
    line("校级优秀学生奖学金（2022）", 24)
    img.save(path)


@pytest.mark.skipif(sys.platform != "win32", reason="系统 OCR 引擎仅 Windows 可用")
class TestRealOcr:
    def test_extract_resume_image(self, tmp_path):
        font_path = _find_cjk_font()
        if font_path is None:
            pytest.skip("未找到中文字体，无法渲染测试图片")
        img = tmp_path / "resume.png"
        _render_resume_image(str(img), font_path)

        doc = ImageExtractor().extract(str(img))

        assert doc.source == "windows-ocr"
        assert doc.paragraphs, "OCR 应识别出文本行"
        joined = "".join(doc.paragraphs)
        # 章节标题与关键字段都应被读到（字间空白已规整）
        for expect in ("教育背景", "实习经历", "项目经历", "专业技能", "荣誉奖项"):
            assert expect in joined, f"章节「{expect}」未被 OCR 读到"
        assert "南京大学" in joined

    def test_image_flows_into_structurer(self, tmp_path):
        """OCR 输出必须能直接喂给结构化引擎并产出六大字段。"""
        from app.config import settings
        from app.parser.structurer import structure_document

        font_path = _find_cjk_font()
        if font_path is None:
            pytest.skip("未找到中文字体，无法渲染测试图片")
        img = tmp_path / "resume.png"
        _render_resume_image(str(img), font_path)

        doc = ImageExtractor().extract(str(img))
        result = structure_document(doc.paragraphs, settings.RULE_VERSION)
        s = result.structure
        basic = s["basic_info"]

        assert basic["name"] == "王五"
        assert basic["phone"] == "13800138000"
        assert basic["email"] == "wangwu@example.com"
        assert s["education"] and s["education"][0]["school"] == "南京大学"
        assert s["education"][0]["period"] == "2021.09-2025.06"
        assert s["experience"] and s["experience"][0]["company"] == "某科技公司"
        assert s["projects"]
        assert len(s["skills"]) >= 3
        assert s["honors"]

    def test_blank_image_yields_no_paragraphs(self, tmp_path):
        """纯白图：OCR 成功但无文本，上层据此判 1003，不静默产出空结构。"""
        from PIL import Image

        img = tmp_path / "blank.png"
        Image.new("RGB", (400, 200), "white").save(img)

        doc = ImageExtractor().extract(str(img))
        assert doc.paragraphs == []

    def test_upload_image_via_api(self, client, upload_dir, tmp_path):
        """端到端：上传真实 PNG → 解析成功 → 结构字段就位。"""
        font_path = _find_cjk_font()
        if font_path is None:
            pytest.skip("未找到中文字体，无法渲染测试图片")
        img = tmp_path / "resume.png"
        _render_resume_image(str(img), font_path)

        resp = client.post(
            "/api/v1/resumes",
            files={"file": ("resume.png", BytesIO(img.read_bytes()), "image/png")},
        )
        body = resp.json()
        assert body["code"] == 0
        data = body["data"]
        assert data["status"] == "parsed"
        assert data["structure"]["basic_info"]["email"] == "wangwu@example.com"
        assert data["structure"]["education"]

    def test_upload_fake_png_rejected(self, client, upload_dir):
        """安全：把 exe 改名成 .png 必须被魔术字节拦下（1001）。"""
        resp = client.post(
            "/api/v1/resumes",
            files={"file": ("resume.png", BytesIO(b"MZ\x90\x00" + b"\x00" * 200), "image/png")},
        )
        assert resp.json()["code"] == ErrorCode.FILE_TYPE_NOT_SUPPORTED
