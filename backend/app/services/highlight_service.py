"""FR-09 引导式亮点挖掘服务层（候选清单 → 追问 → 合成预览 → 确认写入）。

与诊断、改写两个模块的边界：
  - 候选清单复用**内容质量诊断**（FR-05）的结论——诊断说"缺什么"，
    挖掘就问什么，两个模块不会各说各话；
  - 写入复用**改写服务**的草稿/版本机制（同一套 NFR-10 撤销链），
    因此本类继承 RewriteService，而非复制其字段与快照逻辑。

安全边界：字段名做白名单校验（只允许经历类描述字段），
confirm 的服务端事实复核不信任何前端传入的中间状态。
"""
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.diagnosis.base import DiagnosisContext
from app.diagnosis.content import MODULE as content_module
from app.diagnosis.models import SEVERITY_ORDER
from app.errors import BizError, ErrorCode
from app.models import ParseResult
from app.optimize import highlight
from app.services.rewrite_service import RewriteService

# 允许挖掘的字段：经历类描述（FR-09 的对象是"经历"）
_FIELD_RE = re.compile(r"^(experience|projects)\[\d+\]\.description$")

# 候选门槛：命中这些类别的经历描述"还能挖得更出彩"
_MINING_CATEGORIES = {
    "要素缺失·做了什么",
    "要素缺失·怎么做",
    "要素缺失·结果如何",
    "缺少量化结果",
    "表达力度弱",
    "描述过于简略",
    "描述缺失",
    "空话套话",
}


class HighlightService(RewriteService):
    """亮点挖掘服务。继承 RewriteService 以复用草稿/字段/版本三件套。"""

    # ---------- 内部：解析结果与字段 ----------
    def _get_parse(self, resume_id: str) -> ParseResult:
        parse = (
            self.db.execute(
                select(ParseResult)
                .where(ParseResult.resume_id == resume_id)
                .order_by(ParseResult.created_at.desc())
            )
            .scalars()
            .first()
        )
        if parse is None:
            raise BizError(ErrorCode.PARSE_FAILED, "该简历尚未完成解析，无法挖掘亮点")
        return parse

    def _check_field(self, field_name: str) -> None:
        if not field_name or not _FIELD_RE.match(field_name):
            raise BizError(
                ErrorCode.REWRITE_TARGET_NOT_FOUND,
                "亮点挖掘仅支持实习/项目经历的描述字段",
            )

    def _field_value(self, draft, field_name: str) -> str:
        for f in draft.fields or []:
            if f.get("field_name") == field_name:
                return f.get("value") or ""
        return ""

    @staticmethod
    def _item_title(structure: dict, section: str, idx: int) -> str:
        items = structure.get(section) or []
        if idx >= len(items):
            return ""
        item = items[idx] or {}
        if section == "projects":
            return str(item.get("name") or item.get("role") or "")
        return " · ".join(
            str(v) for v in (item.get("company"), item.get("role")) if v
        )

    # ---------- 候选清单 ----------
    def candidates(self, resume_id: str) -> dict:
        """可挖掘的平淡经历清单：复用 FR-05 结论，按"最值得挖"排序。"""
        self._get_resume(resume_id)
        parse = self._get_parse(resume_id)
        ctx = DiagnosisContext(
            resume_id=resume_id,
            structure=parse.structure or {},
            trace=parse.trace or [],
            unrecognized=parse.unrecognized or [],
        )
        result = content_module.diagnose(ctx)

        grouped: dict[str, dict] = {}
        for issue in result.issues:
            # Location 是 dataclass（原则三的定位契约），取属性而非 dict.get
            location = issue.location
            field_name = getattr(location, "field", "") or ""
            if not _FIELD_RE.match(field_name):
                continue
            if issue.category not in _MINING_CATEGORIES:
                continue
            entry = grouped.setdefault(
                field_name,
                {
                    "field_name": field_name,
                    "label": highlight.field_label(field_name),
                    "item_title": "",
                    "snippet": getattr(location, "snippet", "") or "",
                    "categories": [],
                    "issue_count": 0,
                    "severity": issue.severity,
                },
            )
            entry["categories"].append(issue.category)
            entry["issue_count"] += 1
            # 记录该字段的最高严重度
            if SEVERITY_ORDER.index(issue.severity) < SEVERITY_ORDER.index(
                entry["severity"]
            ):
                entry["severity"] = issue.severity

        # 补上条目名称（公司·职位 / 项目名），让用户知道在挖哪一段
        structure = parse.structure or {}
        for field_name, entry in grouped.items():
            section = field_name.split("[")[0]
            idx = int(field_name.split("[")[1].split("]")[0])
            entry["item_title"] = self._item_title(structure, section, idx)
            desc = self._description_of(structure, section, idx)
            entry["layers"] = [
                q.layer for q in highlight.build_questions(desc)
            ]

        candidates = sorted(
            grouped.values(),
            key=lambda c: (
                SEVERITY_ORDER.index(c["severity"]),
                -c["issue_count"],
                c["field_name"],
            ),
        )
        return {
            "resume_id": resume_id,
            "candidate_count": len(candidates),
            "candidates": candidates,
        }

    @staticmethod
    def _description_of(structure: dict, section: str, idx: int) -> str:
        items = structure.get(section) or []
        if idx >= len(items):
            return ""
        return str((items[idx] or {}).get("description") or "")

    # ---------- 追问序列 ----------
    def questions(self, resume_id: str, field_name: str) -> dict:
        """生成分层追问（按草稿中的当前值判定缺什么）。"""
        self._get_resume(resume_id)
        self._check_field(field_name)
        draft = self._get_or_create_draft(resume_id)
        value = self._field_value(draft, field_name)
        return {
            "resume_id": resume_id,
            "field_name": field_name,
            "item_label": highlight.field_label(field_name),
            "current_value": value,
            "questions": [q.to_dict() for q in highlight.build_questions(value)],
            "layer_order": highlight.LAYER_ORDER,
        }

    # ---------- 合成预览（不落库） ----------
    def compose(self, resume_id: str, field_name: str, answers: dict) -> dict:
        """合成候选描述并做事实守恒自检；**不写入任何数据**。"""
        self._get_resume(resume_id)
        self._check_field(field_name)
        draft = self._get_or_create_draft(resume_id)
        value = self._field_value(draft, field_name)
        result = highlight.compose(value, answers or {})
        return {
            "resume_id": resume_id,
            "field_name": field_name,
            "item_label": highlight.field_label(field_name),
            **result.to_dict(),
        }

    # ---------- 确认写入（FR-09：由用户确认后才写入） ----------
    def confirm(
        self, resume_id: str, field_name: str, after_text: str, answers: dict
    ) -> dict:
        """用户确认后写入草稿并产生新版本。

        服务端复核（不信前端）：① 字段白名单；② 事实守恒——
        写入文本的事实必须全部来自「原文 + 用户答案」，否则 6002 拒绝。
        """
        self._get_resume(resume_id)
        self._check_field(field_name)
        draft = self._get_or_create_draft(resume_id)
        original = self._field_value(draft, field_name)
        after_text = (after_text or "").strip()
        if not after_text:
            raise BizError(ErrorCode.REWRITE_TARGET_NOT_FOUND, "确认写入的文本不能为空")

        check = highlight.verify_facts(original, answers or {}, after_text)
        if not check.passed:
            detail = "、".join(
                f"{f['kind']}:{f['value']}" for f in (check.added or check.violated)
            )
            raise BizError(
                ErrorCode.REWRITE_FACT_CHECK_FAILED,
                f"写入内容包含原文与回答之外的事实（{detail}），已拒绝",
            )

        self._set_field(draft, field_name, after_text, source="highlight")
        self._snapshot(draft, operation="highlight")
        self.db.commit()
        return {
            "draft_id": draft.id,
            "current_version": draft.current_version,
            "field": field_name,
            "value": after_text,
            "fact_check": check.to_dict(),
        }
