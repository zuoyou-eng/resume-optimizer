"""草稿字段与结构化简历的双向转换（O-04）。

草稿是**字段级文本**的扁平列表，便于逐字段编辑与版本快照；
结构体是嵌套 dict，供诊断模块直接消费。两者需要无损互转。

`fields_to_lines` 把草稿序列化成标准排版的文本行——复检（O-05）时用它
重新走一遍"解析 → 诊断"，从而得到可与优化前对比的 ATS 结论。
"""
from typing import Any

# 扁平字段名前缀 → 结构体键
_LIST_SECTIONS = ("education", "experience", "projects")
_SCALAR_SECTIONS = ("skills", "honors")

# 反向序列化时使用的标准小标题（与解析器的章节关键词对齐）
_SECTION_TITLES = {
    "education": "教育背景",
    "experience": "实习经历",
    "projects": "项目经历",
    "skills": "专业技能",
    "honors": "荣誉奖项",
}

# 条目内字段的输出顺序
_ENTRY_FIELD_ORDER = {
    "education": ["school", "major", "degree", "period", "description"],
    "experience": ["company", "role", "period", "description"],
    "projects": ["name", "role", "period", "description"],
}


def structure_to_fields(structure: dict, unrecognized: list | None = None) -> list[dict]:
    """结构化简历 → 扁平字段列表（草稿初始内容，source=parsed）。

    `unrecognized` 是解析时无法归类的内容（FR-03）。它必须进入草稿：
    诊断模块会针对这些内容报出问题项，若草稿里没有对应字段，
    用户点"改写"只会得到"字段不存在"的死胡同，既改不了也删不掉。
    """
    fields: list[dict] = []

    basic = (structure or {}).get("basic_info") or {}
    for key in ("name", "phone", "email", "city"):
        fields.append(
            {
                "field_name": f"basic_info.{key}",
                "value": basic.get(key) or "",
                "source": "parsed",
                "version_no": 1,
            }
        )
    for key, value in (basic.get("extra") or {}).items():
        fields.append(
            {
                "field_name": f"basic_info.extra.{key}",
                "value": str(value),
                "source": "parsed",
                "version_no": 1,
            }
        )

    for section in _LIST_SECTIONS:
        for idx, item in enumerate((structure or {}).get(section) or []):
            for key in _ENTRY_FIELD_ORDER[section]:
                fields.append(
                    {
                        "field_name": f"{section}[{idx}].{key}",
                        "value": (item or {}).get(key) or "",
                        "source": "parsed",
                        "version_no": 1,
                    }
                )

    for section in _SCALAR_SECTIONS:
        for idx, value in enumerate((structure or {}).get(section) or []):
            fields.append(
                {
                    "field_name": f"{section}[{idx}]",
                    "value": value or "",
                    "source": "parsed",
                    "version_no": 1,
                }
            )

    # 未识别内容：source 单独标记，前端据此提示"机器读不了，需人工处理"
    for idx, item in enumerate(unrecognized or []):
        text = item.get("text") if isinstance(item, dict) else item
        if text is None or not str(text).strip():
            continue
        fields.append(
            {
                "field_name": f"unrecognized[{idx}]",
                "value": str(text),
                "source": "unrecognized",
                "version_no": 1,
            }
        )

    return fields


def fields_to_structure(fields: list[dict]) -> dict:
    """扁平字段列表 → 结构化简历（供诊断模块直接消费）。"""
    structure: dict[str, Any] = {
        "basic_info": {"extra": {}},
        "education": [],
        "experience": [],
        "projects": [],
        "skills": [],
        "honors": [],
    }
    unrecognized: list[dict] = []

    def ensure(section: str, idx: int) -> dict:
        items = structure[section]
        while len(items) <= idx:
            items.append({})
        return items[idx]

    for f in fields or []:
        name = f.get("field_name") or ""
        value = f.get("value") or ""
        if not name:
            continue

        # 未识别内容原样回填（FR-03：进得了草稿就出得了结构体）
        if name.startswith("unrecognized[") and name.endswith("]"):
            idx_str = name[len("unrecognized[") : -1]
            if idx_str.isdigit():
                idx = int(idx_str)
                while len(unrecognized) <= idx:
                    unrecognized.append(
                        {"text": "", "reason": "无法归入已知字段（不在任何已识别章节内）"}
                    )
                unrecognized[idx]["text"] = value
            continue

        if name.startswith("basic_info."):
            key = name[len("basic_info.") :]
            if key.startswith("extra."):
                structure["basic_info"]["extra"][key[len("extra.") :]] = value
            elif key in ("name", "phone", "email", "city"):
                structure["basic_info"][key] = value
            continue

        for section in _LIST_SECTIONS:
            prefix = f"{section}["
            if name.startswith(prefix):
                rest = name[len(prefix) :]
                idx_str, _, key = rest.partition("].")
                if not idx_str.isdigit() or not key:
                    continue
                ensure(section, int(idx_str))[key] = value
                break
        else:
            for section in _SCALAR_SECTIONS:
                prefix = f"{section}["
                if name.startswith(prefix) and name.endswith("]"):
                    idx_str = name[len(prefix) : -1]
                    if not idx_str.isdigit():
                        continue
                    items = structure[section]
                    idx = int(idx_str)
                    while len(items) <= idx:
                        items.append("")
                    items[idx] = value

    # 清掉空条目，避免诊断模块把空 education[0] 报成区块异常
    for section in _LIST_SECTIONS:
        structure[section] = [
            item for item in structure[section] if any(str(v).strip() for v in item.values())
        ]
    structure["skills"] = [s for s in structure["skills"] if str(s).strip()]
    structure["honors"] = [h for h in structure["honors"] if str(h).strip()]
    structure["unrecognized"] = [u for u in unrecognized if str(u.get("text") or "").strip()]
    return structure


def fields_to_lines(fields: list[dict]) -> list[str]:
    """草稿 → 标准排版文本行（复检用：让解析器按规范重新读一遍）。"""
    lookup = {f.get("field_name"): (f.get("value") or "").strip() for f in fields or []}
    lines: list[str] = []

    name = lookup.get("basic_info.name", "")
    if name:
        lines.append(name)
    # 联系方式必须**各占一行**：解析器的基本信息扫描在一行内命中邮箱后即 continue，
    # 同行写在后面的电话号码会被跳过——复检时手机号就会"被读丢"。
    if lookup.get("basic_info.phone"):
        lines.append(f"电话：{lookup['basic_info.phone']}")
    if lookup.get("basic_info.email"):
        lines.append(f"邮箱：{lookup['basic_info.email']}")
    city = lookup.get("basic_info.city")
    if city:
        lines.append(f"求职意向：（{city}）")
    lines.append("")

    for section in _LIST_SECTIONS:
        indices = sorted(
            {
                int(name_str[len(section) + 1 : name_str.index("]")])
                for name_str in lookup
                if name_str.startswith(f"{section}[") and "]" in name_str
            }
        )
        if not indices:
            continue
        lines.append(_SECTION_TITLES[section])
        for idx in indices:
            header_parts = [
                lookup.get(f"{section}[{idx}].{k}", "")
                for k in _ENTRY_FIELD_ORDER[section]
                if k != "description"
            ]
            header = " ".join(p for p in header_parts if p)
            if header:
                lines.append(header)
            desc = lookup.get(f"{section}[{idx}].description", "")
            if desc:
                for para in desc.split("\n"):
                    if para.strip():
                        lines.append(para.strip())
        lines.append("")

    for section in _SCALAR_SECTIONS:
        values = [
            v
            for k, v in sorted(lookup.items())
            if k.startswith(f"{section}[") and k.endswith("]") and v
        ]
        if not values:
            continue
        lines.append(_SECTION_TITLES[section])
        lines.extend(values)
        lines.append("")

    # 未识别内容：必须显式成块输出。两个原因——
    # ① FR-03：导出时不允许静默丢失；
    # ② 复检要重新解析这些文本，用「未归类内容」标题才能让解析器
    #    继续把它们判为未识别，而不是吸进上一个章节，对比结论才可比。
    unrecognized_lines = [
        v
        for k, v in sorted(lookup.items())
        if k.startswith("unrecognized[") and k.endswith("]") and v
    ]
    if unrecognized_lines:
        lines.append("未归类内容（原样保留）")
        lines.extend(unrecognized_lines)
        lines.append("")

    while lines and not lines[-1]:
        lines.pop()
    return lines
