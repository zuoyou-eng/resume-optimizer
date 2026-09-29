"""O-08 定制版本生成的纯逻辑：依据 FR-08 匹配结果对草稿字段做**取舍与重组**。

红线（需求原文）：**只做取舍与重组，不新增事实**。据此本模块只做一件事——
在每个章节内部按"与目标岗位的相关度"做**稳定降序重排**：

  * experience / projects：条目相关度 = 组内全部文本命中的 JD 要求数量；
  * skills：单项技能命中任一 JD 要求即视为相关；
  * education / honors / basic_info / unrecognized：**不参与重排**——
    它们是身份与硬指标事实，排序不产生岗位价值，且荣誉排序自带时间/含金量语义。

"取舍"体现为**排序**而非删除：删除会静默丢失内容（与 FR-03 冲突），
且低相关经历对部分岗位仍有价值。每一次移动都记录原因（moves），用户可核对、
可通过回滚撤销（NFR-10）。

确定性保证：相同输入（字段 + 匹配结果）→ 相同输出。排序用稳定排序，
相关度相同的条目保持原有相对顺序（NFR-08）。
"""
import re
from dataclasses import dataclass, field

from app.diagnosis.match import contains_term

# 扁平字段名 → (section, idx, key)；basic_info.* / unrecognized 等不含 [idx] 的不匹配
_FIELD_RE = re.compile(r"^(?P<section>[a-z_]+)\[(?P<idx>\d+)\](?:\.(?P<key>[a-z_]+))?$")

# 参与岗位相关度重排的章节；其余章节保持原顺序
_SORTABLE_SECTIONS = ("experience", "projects", "skills")

# 单字段章节（每项一个字段，无子键）
_SINGLE_FIELD_SECTIONS = ("skills", "honors", "unrecognized")


@dataclass
class FieldGroup:
    """一个条目组：experience[2].* 四个字段，或 skills[3] 单字段。"""

    section: str
    index: int
    members: list[dict] = field(default_factory=list)
    hits: int = 0  # 命中的 JD 要求数量（-1 表示不参与重排）

    @property
    def sortable(self) -> bool:
        return self.section in _SORTABLE_SECTIONS

    @property
    def label(self) -> str:
        """组的人类可读标识（用于 moves 展示）。"""
        first = self.members[0] if self.members else {}
        name = first.get("field_name") or f"{self.section}[{self.index}]"
        if self.section in _SINGLE_FIELD_SECTIONS:
            return name
        return f"{self.section}[{self.index}]"


@dataclass
class TailorMove:
    field_name: str  # 组代表字段（如 experience[0].company / skills[1]）
    action: str  # promoted（前移）| demoted（后移）
    from_index: int
    to_index: int
    hits: int
    reason: str


@dataclass
class TailorPlan:
    fields: list[dict]
    moves: list[TailorMove]
    jd_title: str
    requirement_count: int
    gap_count: int

    @property
    def changed(self) -> bool:
        return bool(self.moves)


def _jd_requirements(match_meta: dict | None) -> list[str]:
    """从 match 维度 meta 提取 JD 要求清单（技能优先，无 kind 信息时取全部）。"""
    meta = match_meta or {}
    matches = meta.get("matches") or []
    requirements: list[str] = []
    for m in matches:
        req = (m.get("requirement") or "").strip()
        if req:
            requirements.append(req)
    return requirements


def _group_fields(fields: list[dict]) -> list[FieldGroup]:
    """把扁平字段列表分组为连续块（块间顺序 = 原顺序，块内保持原相对顺序）。"""
    groups: list[FieldGroup] = []
    current: FieldGroup | None = None
    for f in fields or []:
        name = f.get("field_name") or ""
        m = _FIELD_RE.match(name)
        if m is None:
            # 不可分组字段（basic_info.* 等）：各自成为独立固定组，保持原位
            g = FieldGroup(section="__fixed__", index=len(groups), members=[dict(f)])
            g.hits = -1
            groups.append(g)
            current = None
            continue
        section, idx = m.group("section"), int(m.group("idx"))
        if current is not None and current.section == section and current.index == idx:
            current.members.append(dict(f))
        else:
            current = FieldGroup(section=section, index=idx, members=[dict(f)])
            current.hits = -1 if section not in _SORTABLE_SECTIONS else 0
            groups.append(current)
    return groups


def _renumber(members: list[dict], section: str, new_index: int) -> list[dict]:
    """把组内字段的索引前缀改写为新位置（值不变）。"""
    out = []
    for f in members:
        name = f.get("field_name") or ""
        m = _FIELD_RE.match(name)
        if m is None:
            out.append(dict(f))
            continue
        key = m.group("key")
        new_name = f"{section}[{new_index}]" + (f".{key}" if key else "")
        out.append({**f, "field_name": new_name})
    return out


def plan_tailored(fields: list[dict], match_meta: dict | None) -> TailorPlan:
    """生成定制版本的重排计划（不改变任何字段值，只调整顺序与索引）。"""
    requirements = _jd_requirements(match_meta)
    meta = match_meta or {}
    groups = _group_fields(fields)

    # ① 相关度：命中 JD 要求的数量（词边界匹配，避免 "go" 命中 "django"）
    for g in groups:
        if not g.sortable or not requirements:
            continue
        text = " ".join(str(f.get("value") or "") for f in g.members).lower()
        g.hits = sum(1 for r in requirements if contains_term(text, r.lower()))

    # ② 按 section 连续块分别做稳定降序排序（块间顺序不变）
    moves: list[TailorMove] = []
    reordered: list[FieldGroup] = []
    i = 0
    while i < len(groups):
        g = groups[i]
        if not g.sortable:
            reordered.append(g)
            i += 1
            continue
        j = i
        block: list[FieldGroup] = []
        while j < len(groups) and groups[j].section == g.section and groups[j].sortable:
            block.append(groups[j])
            j += 1
        original_order = {id(b): k for k, b in enumerate(block)}
        sorted_block = sorted(block, key=lambda b: -b.hits)  # 稳定：同 hits 保持原序
        for new_idx, b in enumerate(sorted_block):
            old_idx = original_order[id(b)]
            if new_idx != old_idx:
                moves.append(
                    TailorMove(
                        field_name=b.label,
                        action="promoted" if new_idx < old_idx else "demoted",
                        from_index=old_idx,
                        to_index=new_idx,
                        hits=b.hits,
                        reason=(
                            f"命中 {b.hits} 项岗位要求"
                            if b.hits
                            else "未命中岗位要求，后移让位"
                        ),
                    )
                )
        reordered.extend(sorted_block)
        i = j

    # ③ 重编号并拼回（值原样保留）
    counters: dict[str, int] = {}
    new_fields: list[dict] = []
    for g in reordered:
        if g.section == "__fixed__":
            new_fields.extend(dict(f) for f in g.members)
            continue
        idx = counters.get(g.section, 0)
        counters[g.section] = idx + 1
        new_fields.extend(_renumber(g.members, g.section, idx))

    return TailorPlan(
        fields=new_fields,
        moves=moves,
        jd_title=(meta.get("jd_title") or "").strip(),
        requirement_count=len(requirements),
        gap_count=len(meta.get("gaps") or []),
    )
