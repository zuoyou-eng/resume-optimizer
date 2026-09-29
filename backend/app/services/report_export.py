"""诊断报告导出（FR-13）：把综合报告渲染为自包含 HTML，便于分享与存档。

设计要点：
1. **数据单一来源**：分组与排序直接复用 DiagnosisService.get_report 与 runner 产出的
   issue_summary.groups，导出层不做任何重新分组或重新排序——否则导出的报告会和界面不一致。
2. **安全底线**：所有用户内容（问题描述、原文片段、evidence、JD 文本）一律 html.escape
   后写入，防止简历内容破坏报告结构或注入脚本。
3. **自包含**：内联 CSS、无外部字体/脚本依赖，单文件可离线打开；@media print 下切换为
   纸面白底，可直接打印或"打印成 PDF"存档。
"""
from html import escape

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.diagnosis.models import SEVERITY_LABELS
from app.errors import trace_id_var
from app.models import Diagnosis
from app.services.diagnosis_service import DiagnosisService

# 分组元信息与前端 DiagnosePage 保持一致（FR-11 三组）
GROUP_META = [
    ("high_impact_easy", "01", "影响大 · 好改", "先改这些，性价比最高"),
    ("high_impact_hard", "02", "影响大 · 难改", "需要补充真实经历或信息"),
    ("low_impact", "03", "影响小", "时间充裕时再处理"),
]

VERDICT_LABELS = {
    "correct": "正确读取",
    "lost": "丢失",
    "misplaced": "错位",
    "fabricated": "编造",
}
MATCH_LABELS = {"covered": "已覆盖", "partial": "部分覆盖", "missing": "完全缺失"}

_CSS = """
:root { --ink:#1c2420; --muted:#6b7570; --line:#dfe3dd; --paper:#ffffff;
        --well:#f4f6f2; --sig:#1f7a5c; --amber:#a8752a; --bad:#b3402f; }
* { box-sizing:border-box; }
body { margin:0; background:#eceee9; color:var(--ink);
       font-family:"PingFang SC","Microsoft YaHei","Noto Sans SC",sans-serif;
       font-size:13.5px; line-height:1.75; }
.mono { font-family:"JetBrains Mono",Consolas,"Courier New",monospace; }
.page { max-width:860px; margin:32px auto; background:var(--paper);
        border:1px solid var(--line); border-radius:6px; overflow:hidden; }
.rp-head { padding:34px 40px 26px; background:#12211b; color:#e9f2ec; }
.rp-kicker { font-family:"JetBrains Mono",Consolas,monospace; font-size:11px;
             letter-spacing:.22em; text-transform:uppercase; color:#7fd4b4; }
.rp-head h1 { margin:10px 0 8px; font-size:24px; font-weight:700; letter-spacing:.02em; }
.rp-head p { margin:0; font-size:12.5px; color:#a9bcb1; }
.rp-meta { display:flex; flex-wrap:wrap; gap:8px 22px; margin-top:18px;
           font-family:"JetBrains Mono",Consolas,monospace; font-size:11px; color:#8fa79a; }
.rp-meta b { color:#cfe3d8; font-weight:600; }
.rp-body { padding:30px 40px 38px; }
section { margin-bottom:30px; }
.sec-hd { display:flex; align-items:baseline; gap:10px; padding-bottom:8px;
          border-bottom:2px solid var(--ink); margin-bottom:14px; }
.sec-no { font-family:"JetBrains Mono",Consolas,monospace; font-size:12px; color:var(--sig); }
.sec-hd h2 { margin:0; font-size:15.5px; font-weight:700; }
.sec-en { font-family:"JetBrains Mono",Consolas,monospace; font-size:10px;
          letter-spacing:.14em; text-transform:uppercase; color:var(--muted); }
.score-row { display:flex; align-items:flex-end; gap:26px; flex-wrap:wrap; }
.score-big { font-family:"JetBrains Mono",Consolas,monospace; font-size:52px;
             font-weight:700; line-height:1; }
.score-big i { font-size:16px; font-style:normal; color:var(--muted); }
.dim-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr));
            gap:10px; flex:1; min-width:300px; }
.dim-cell { border:1px solid var(--line); border-radius:4px; padding:10px 14px;
            background:var(--well); }
.dim-cell .dn { font-size:12px; font-weight:600; }
.dim-cell .de { font-family:"JetBrains Mono",Consolas,monospace; font-size:9.5px;
                letter-spacing:.12em; text-transform:uppercase; color:var(--muted); }
.dim-cell .ds { font-family:"JetBrains Mono",Consolas,monospace; font-size:24px;
                font-weight:700; margin-top:2px; }
.dim-cell .dc { font-size:11px; color:var(--muted); }
.s-good { color:var(--sig); } .s-mid { color:var(--amber); } .s-bad { color:var(--bad); }
.vgrid { display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:10px; }
.vcell { border:1px solid var(--line); border-radius:4px; padding:12px 14px; }
.vcell .vn { font-family:"JetBrains Mono",Consolas,monospace; font-size:26px; font-weight:700; }
.vcell .vt { font-size:12.5px; font-weight:600; margin-top:2px; }
.vcell .ve { font-family:"JetBrains Mono",Consolas,monospace; font-size:9.5px;
             letter-spacing:.12em; text-transform:uppercase; color:var(--muted); }
.v-ok .vn { color:var(--sig); } .v-lost .vn { color:var(--bad); }
.v-mis .vn { color:var(--amber); } .v-fab .vn { color:var(--bad); }
table { width:100%; border-collapse:collapse; font-size:12.5px; }
th { text-align:left; font-family:"JetBrains Mono",Consolas,monospace; font-size:10px;
     letter-spacing:.12em; text-transform:uppercase; color:var(--muted);
     padding:6px 10px; border-bottom:1.5px solid var(--ink); }
td { padding:8px 10px; border-bottom:1px solid var(--line); vertical-align:top; }
.mt-req { font-weight:600; width:34%; }
.mt-verdict { font-family:"JetBrains Mono",Consolas,monospace; font-size:11px;
              padding:1px 7px; border-radius:3px; }
.mv-covered { color:var(--sig); background:#e7f3ee; }
.mv-partial { color:var(--amber); background:#f7efe0; }
.mv-missing { color:var(--bad); background:#f8e9e6; }
.mt-hint { display:block; font-size:11px; color:var(--muted); margin-top:2px; }
.mt-ev { color:var(--muted); font-size:11.5px; }
.ig { margin-bottom:14px; border:1px solid var(--line); border-radius:4px; overflow:hidden; }
.ig-hd { display:flex; align-items:center; gap:10px; padding:9px 14px; background:var(--well); }
.ig-no { font-family:"JetBrains Mono",Consolas,monospace; font-size:11px; color:var(--sig); }
.ig-name { font-weight:700; font-size:13px; }
.ig-count { font-family:"JetBrains Mono",Consolas,monospace; font-size:11px;
            padding:0 7px; border-radius:8px; background:#fff; border:1px solid var(--line); }
.ig-desc { font-size:11px; color:var(--muted); margin-left:auto; }
.issue { padding:12px 16px; border-top:1px solid var(--line); }
.issue-hd { display:flex; align-items:center; gap:8px; flex-wrap:wrap; }
.sev { font-family:"JetBrains Mono",Consolas,monospace; font-size:10px; font-weight:700;
       padding:1px 8px; border-radius:3px; letter-spacing:.06em; }
.sev.s-critical { color:#fff; background:var(--bad); }
.sev.s-major { color:var(--amber); background:#f7efe0; }
.sev.s-minor { color:var(--muted); background:var(--well); }
.ii-cat { font-size:12px; font-weight:600; }
.ii-field { font-family:"JetBrains Mono",Consolas,monospace; font-size:10.5px;
            color:var(--muted); margin-left:auto; }
.ii-problem { margin:7px 0 0; font-size:13px; }
.ii-snippet { margin-top:6px; padding:7px 11px; background:var(--well);
              border-left:3px solid var(--line); border-radius:0 3px 3px 0;
              font-family:"JetBrains Mono",Consolas,monospace; font-size:11.5px;
              color:#4a554e; word-break:break-all; }
.ii-sug { margin-top:7px; font-size:12.5px; }
.ii-sug b { display:inline-block; margin-right:8px; font-size:10px; letter-spacing:.1em;
            color:var(--sig); font-family:"JetBrains Mono",Consolas,monospace; }
.ii-ev { margin-top:6px; font-size:11px; color:var(--muted); }
.ii-ev .mono { font-size:9.5px; letter-spacing:.1em; text-transform:uppercase;
               margin-right:7px; color:#9aa59e; }
.ii-conf { margin-left:9px; font-family:"JetBrains Mono",Consolas,monospace; }
.empty { padding:10px 16px; border-top:1px solid var(--line);
         font-family:"JetBrains Mono",Consolas,monospace; font-size:11px; color:var(--muted); }
.rp-foot { padding:18px 40px 26px; border-top:1px solid var(--line); background:var(--well);
           font-size:11.5px; color:var(--muted); line-height:1.8; }
.rp-foot b { color:var(--ink); }
@media print {
  body { background:#fff; font-size:12px; }
  .page { margin:0; border:none; border-radius:0; max-width:none; }
  .rp-head { background:#fff; color:var(--ink); border-bottom:2.5px solid var(--ink); }
  .rp-kicker { color:var(--sig); } .rp-head p { color:var(--muted); }
  .rp-meta { color:var(--muted); } .rp-meta b { color:var(--ink); }
  section { page-break-inside:avoid; } .issue { page-break-inside:avoid; }
}
"""


def _esc(value) -> str:
    return escape(str(value if value is not None else ""), quote=True)


def _score_class(score) -> str:
    try:
        s = float(score)
    except (TypeError, ValueError):
        return "s-good"
    if s >= 85:
        return "s-good"
    if s >= 60:
        return "s-mid"
    return "s-bad"


def _fmt_time(iso_text: str) -> str:
    # ISO → 可读时间（截到分钟，避免时区歧义带来的误导）
    return _esc((iso_text or "")[:16].replace("T", " "))


class ReportExportService:
    """FR-13：渲染自包含 HTML 诊断报告。"""

    def __init__(self, db: Session):
        self.db = db

    def export_html(self, resume_id: str) -> tuple[str, str]:
        """返回 (html 文本, 建议文件名)。未诊断 / 简历不存在时抛出业务错误。"""
        report = DiagnosisService(self.db).get_report(resume_id)
        details = self._dimension_details(report.get("diagnosis_ids") or [])
        html = _render_report(report, details)
        return html, f"diagnosis-report-{resume_id[:8]}.html"

    # ---------- 内部：按需拉取 machine / match 两个维度的明细 ----------
    def _dimension_details(self, diagnosis_ids: list[str]) -> dict:
        if not diagnosis_ids:
            return {}
        rows = (
            self.db.execute(select(Diagnosis).where(Diagnosis.id.in_(diagnosis_ids)))
            .scalars()
            .all()
        )
        details = {}
        for d in rows:
            if d.dimension == "machine":
                details["machine"] = d.meta or {}
            elif d.dimension == "match":
                details["match"] = d.meta or {}
        return details


def _render_report(report: dict, details: dict) -> str:
    e = _esc
    dims = report.get("dimension_scores") or {}
    summary = report.get("issue_summary") or {}
    groups = summary.get("groups") or {}
    by_severity = summary.get("by_severity") or {}
    # 完整问题（含 evidence / confidence）按 issue_id 建索引，供分组条目补全判定依据
    full_issues = {i.get("issue_id"): i for i in (report.get("issues") or [])}

    parts: list[str] = []
    parts.append(
        "<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>简历诊断报告</title>"
        f"<style>{_CSS}</style></head><body><div class='page'>"
    )

    # ---------- 头部 ----------
    parts.append(
        "<header class='rp-head'>"
        "<div class='rp-kicker'>Diagnosis Report · 简历优化助手</div>"
        f"<h1>简历诊断报告 · 健康分 {_esc(report.get('total_score'))}</h1>"
        "<p>本报告由规则引擎自动生成，结论均可逐条核对判定依据；"
        "系统只提示缺什么信息，不替用户编造内容。</p>"
        "<div class='rp-meta'>"
        f"<span>resume <b>{e((report.get('resume_id') or '')[:8])}</b></span>"
        f"<span>issues <b>{_esc(summary.get('total', 0))}</b></span>"
        f"<span>generated <b>{_fmt_time(report.get('created_at'))}</b></span>"
        f"<span>trace <b>{e(trace_id_var.get())}</b></span>"
        "</div></header>"
    )
    parts.append("<div class='rp-body'>")

    # ---------- R.01 健康分与维度得分 ----------
    dim_cells = []
    for key, dim in dims.items():
        counted = dim.get("counted_in_health", True)
        dim_cells.append(
            f"<div class='dim-cell'><div class='dn'>{e(dim.get('label', key))}</div>"
            f"<div class='de'>{e(key)}</div>"
            f"<div class='ds {_score_class(dim.get('score'))}'>{_esc(dim.get('score'))}<i>/100</i></div>"
            f"<div class='dc'>{_esc(dim.get('issue_count', 0))} 项问题 · "
            f"{'计入健康分' if counted else '不计入健康分'} · rule {e(dim.get('rule_version', ''))}</div></div>"
        )
    sev_text = " · ".join(
        f"{SEVERITY_LABELS.get(sev, sev)} {by_severity.get(sev, 0)}" for sev in ("critical", "major", "minor")
    )
    parts.append(
        "<section><div class='sec-hd'><span class='sec-no'>[ R.01 ]</span>"
        "<h2>综合健康分</h2><span class='sec-en'>dimension_scores</span></div>"
        "<div class='score-row'>"
        f"<div class='score-big {_score_class(report.get('total_score'))}'>"
        f"{_esc(report.get('total_score'))}<i>/100</i></div>"
        f"<div class='dim-grid'>{''.join(dim_cells)}</div></div>"
        f"<p style='margin:12px 0 0;font-size:12px;color:var(--muted)'>问题分布：{e(sev_text)}。"
        "健康分只衡量简历本身的质量；岗位匹配分取决于岗位，不计入健康分。</p></section>"
    )

    # ---------- R.02 ATS 读取结论 ----------
    machine = details.get("machine") or {}
    vs = machine.get("verdict_summary") or {}
    if vs:
        cells = "".join(
            f"<div class='vcell {cls}'><div class='vn'>{_esc(vs.get(field, 0))}</div>"
            f"<div class='vt'>{label}</div><div class='ve'>{field}</div></div>"
            for field, label, cls in (
                ("correct", "正确读取", "v-ok"),
                ("lost", "丢失", "v-lost"),
                ("misplaced", "错位", "v-mis"),
                ("fabricated", "编造", "v-fab"),
            )
        )
        rows = "".join(
            f"<tr><td class='mono'>{e(pt.get('field'))}</td>"
            f"<td class='mono'>{e(pt.get('extracted')) or '（空）'}</td>"
            f"<td><span class='mt-verdict mv-{e(pt.get('verdict'))}'>"
            f"{e(VERDICT_LABELS.get(pt.get('verdict'), pt.get('verdict')))}</span></td>"
            f"<td class='mt-ev mono'>{e(pt.get('rule_applied'))}</td></tr>"
            for pt in (machine.get("parse_trace") or [])
        )
        parts.append(
            "<section><div class='sec-hd'><span class='sec-no'>[ R.02 ]</span>"
            "<h2>ATS 读取结论</h2><span class='sec-en'>field_verdicts</span></div>"
            f"<div class='vgrid'>{cells}</div>"
            "<table style='margin-top:14px'><thead><tr><th>字段</th><th>机器读到的值</th>"
            "<th>结论</th><th>命中规则</th></tr></thead>"
            f"<tbody>{rows}</tbody></table></section>"
        )

    # ---------- R.03 岗位匹配明细 ----------
    match = details.get("match") or {}
    if match:
        rows = "".join(
            f"<tr><td class='mt-req'>{e(m.get('requirement'))}</td>"
            f"<td><span class='mt-verdict mv-{e(m.get('verdict'))}'>"
            f"{e(MATCH_LABELS.get(m.get('verdict'), m.get('verdict')))}</span>"
            + (f"<span class='mt-hint'>{e(m.get('hint'))}</span>" if m.get("hint") else "")
            + f"</td><td class='mt-ev'>{e(m.get('evidence'))}</td></tr>"
            for m in (match.get("matches") or [])
        )
        gap_items = "".join(f"<li>{e(g)}</li>" for g in (match.get("gaps") or []))
        parts.append(
            "<section><div class='sec-hd'><span class='sec-no'>[ R.03 ]</span>"
            f"<h2>岗位匹配明细</h2><span class='sec-en'>{e(match.get('jd_title') or 'job_description')}</span></div>"
            "<table><thead><tr><th>岗位要求</th><th>结论</th><th>证据 / 说明</th></tr></thead>"
            f"<tbody>{rows}</tbody></table>"
            + (
                f"<p style='margin:12px 0 0'><b>缺口清单</b>（{len(match.get('gaps') or [])} 项）：</p>"
                f"<ul style='margin:6px 0 0;padding-left:20px;font-size:12.5px'>{gap_items}</ul>"
                if gap_items
                else ""
            )
            + "</section>"
        )

    # ---------- R.04 问题清单（分组直接复用报告层，不重新排序） ----------
    group_html = []
    for key, no, name, desc in GROUP_META:
        items = groups.get(key) or []
        issue_html = []
        for brief in items:
            full = full_issues.get(brief.get("issue_id")) or {}
            evidence = full.get("evidence")
            confidence = full.get("confidence")
            issue_html.append(
                f"<div class='issue'><div class='issue-hd'>"
                f"<span class='sev s-{e(brief.get('severity'))}'>{e(brief.get('severity_label') or SEVERITY_LABELS.get(brief.get('severity'), ''))}</span>"
                f"<span class='ii-cat'>{e(brief.get('category'))}</span>"
                f"<span class='ii-field'>{e(brief.get('field'))}</span></div>"
                f"<p class='ii-problem'>{e(brief.get('problem'))}</p>"
                + (
                    f"<div class='ii-snippet'>「{e(brief.get('snippet'))}」</div>"
                    if brief.get("snippet")
                    else ""
                )
                + f"<p class='ii-sug'><b>建议</b>{e(brief.get('suggestion'))}</p>"
                + (
                    f"<div class='ii-ev'><span class='mono'>evidence</span>{e(evidence)}"
                    f"<span class='ii-conf'>confidence {_esc(confidence if confidence is not None else 1.0)}</span></div>"
                    if evidence
                    else ""
                )
                + "</div>"
            )
        body = "".join(issue_html) or "<div class='empty'>// 该分组无问题</div>"
        group_html.append(
            f"<div class='ig'><div class='ig-hd'><span class='ig-no'>{no}</span>"
            f"<span class='ig-name'>{e(name)}</span><span class='ig-count'>{len(items)}</span>"
            f"<span class='ig-desc'>{e(desc)}</span></div>{body}</div>"
        )
    parts.append(
        "<section><div class='sec-hd'><span class='sec-no'>[ R.04 ]</span>"
        "<h2>问题清单</h2><span class='sec-en'>issue_queue</span></div>"
        + "".join(group_html)
        + "</section>"
    )

    # ---------- 页脚 ----------
    parts.append(
        "</div><footer class='rp-foot'>"
        "<b>使用说明</b>：① 问题清单按「影响大且好改 → 影响大难改 → 影响小」排序，建议按序处理；"
        "② 每条问题均附判定依据（evidence）与置信度，可逐条核对；"
        "③ 本报告只提示缺什么信息，<b>不替用户编造内容</b>——需要补写的经历请基于真实信息；"
        "④ 相同输入重复诊断结果一致（确定性输出），可复现、可核对。<br>"
        "由「简历优化助手」规则引擎生成 · 报告仅作为修改参考，不代表任何录用结论。"
        "</footer></div></body></html>"
    )
    return "".join(parts)
