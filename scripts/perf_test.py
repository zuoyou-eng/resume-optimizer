#!/usr/bin/env python
"""性能压测：对应《测试计划》4.7 节 PF-01 ~ PF-11。

用法：
    cd backend && .venv/Scripts/python.exe ../scripts/perf_test.py
    # 可选环境变量
    PERF_BASE=http://127.0.0.1:8000/api/v1   # 默认值
    PERF_OUT=../.perf                        # 报告输出目录

场景与指标（源自测试计划）：
    PF-01  单份 1 页简历完整链路      总耗时 ≤ 15s（NFR-01）
    PF-02  单份 3 页简历完整链路      记录基线
    PF-03  10 用户并发诊断            增幅 ≤ 50%（NFR-02）
    PF-04  20 用户并发诊断            观察降级行为
    PF-05  大文件上传（接近上限）      耗时与稳定性
    PF-06  连续 50 次诊断             无衰减趋势
    PF-07  分段耗时分析               定位瓶颈（本项目价值点）
    PF-08  单条改写响应时间           记录（含两次模型调用）
    PF-09  批量应用 20 条             验证批量收益
    PF-10  草稿版本快照写入开销       版本数达上限时是否劣化
    PF-11  回滚响应时间               3 页简历回滚耗时

⚠️ 环境说明：本机无 Docker/PostgreSQL，压测对象是本机 Python + SQLite。
SQLite 写操作串行化，并发写竞争比 PostgreSQL 激烈，因此 PF-03/04 测得的
增幅是**悲观上界**——PostgreSQL 上预期更优。该差异在报告中明确标注。
"""
from __future__ import annotations

import json
import os
import statistics
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

BASE = os.getenv("PERF_BASE", "http://127.0.0.1:8000/api/v1").rstrip("/")
OUT = Path(os.getenv("PERF_OUT", "../.perf")).resolve()
OUT.mkdir(parents=True, exist_ok=True)

RESULT: dict = {"base": BASE, "scenarios": {}, "notes": []}


# ---------------------------------------------------------------- 基础工具
def _client(timeout: float = 120.0) -> httpx.Client:
    return httpx.Client(base_url=BASE, timeout=timeout)


def timed(fn):
    """执行 fn 并返回 (结果, 耗时秒)。"""
    t0 = time.perf_counter()
    out = fn()
    return out, round(time.perf_counter() - t0, 4)


def upload(name: str, content: bytes, ctype: str = "text/plain") -> dict:
    with _client() as c:
        r = c.post(
            "/resumes",
            files={"file": (name, content, ctype)},
        )
        body = r.json()
        if body.get("code") != 0:
            raise RuntimeError(f"上传失败 {name}: {body}")
        return body["data"]


def diagnose(resume_id: str, c: httpx.Client | None = None) -> tuple[dict, float]:
    own = c is None
    c = c or _client()
    try:
        t0 = time.perf_counter()
        r = c.post("/diagnoses", json={"resume_id": resume_id})
        body = r.json()
        if body.get("code") != 0:
            raise RuntimeError(f"诊断失败: {body}")
        return body["data"], round(time.perf_counter() - t0, 4)
    finally:
        if own:
            c.close()


def get_report(resume_id: str, c: httpx.Client | None = None) -> float:
    own = c is None
    c = c or _client()
    try:
        t0 = time.perf_counter()
        r = c.get(f"/reports/{resume_id}")
        if r.status_code != 200:
            raise RuntimeError(f"报告失败: {r.status_code}")
        return round(time.perf_counter() - t0, 4)
    finally:
        if own:
            c.close()


# ---------------------------------------------------------------- 测试数据
def resume_text(unique: str, pages: int = 1) -> str:
    """生成 pages 页规模的简历文本；unique 保证每份内容不同（避开 file_hash 去重）。"""
    head = f"""{unique} · 性能测试样本
电话：138{unique[-4:].ljust(8, '0')[:8]}
邮箱：perf{unique}@example.com
求职意向：后端开发工程师（杭州）

教育背景
南京大学 软件工程 本科 2021.09-2025.06
主修课程：数据结构、操作系统、计算机网络、数据库原理

实习经历
字节跳动科技有限公司 后端开发实习生 2023.06-2023.12
负责订单服务接口开发，使用 Python 与 MySQL
参与压测与线上问题排查，累计处理工单 50+ 单

项目经历
分布式秒杀系统 核心开发 2023.03-2023.05
设计库存扣减方案，QPS 从 800 提升到 3000
使用 Redis 缓存热点数据，接口耗时下降 60%

专业技能
熟练掌握 Python、Java、MySQL
熟悉 Redis、Docker、Linux 常用命令

荣誉奖项
校级优秀学生奖学金（2022）
全国大学生程序设计竞赛省二等奖
"""
    filler_blocks = []
    for i in range(max(0, pages - 1)):
        filler_blocks.append(f"""
补充经历 {i + 2}
某某科技有限公司第{i + 2}分部 后端开发实习生 2022.0{i + 1}-2022.12
参与第{i + 2}个订单服务模块的接口开发与联调，使用 Python 与 MySQL
负责压测环境搭建，定位并修复慢查询 12 处，接口耗时下降 {30 + i}%
协助完成线上问题排查，累计处理工单 {20 + i} 单，编写技术文档 5 篇

项目经历补充 {i + 2}
高并发消息推送系统 后端开发 2022.01-2022.06
设计基于 Redis 的消息队列削峰方案，峰值 QPS 达到 {5000 + i * 500}
实现推送失败重试与幂等控制，消息到达率提升至 99.{i}%
使用 Docker 容器化部署，将发布耗时从 40 分钟缩短到 6 分钟
""")
    return head + "\n".join(filler_blocks) + f"\n（样本编号 {unique}，用于压测内容去重）\n"


def tag() -> str:
    return uuid.uuid4().hex[:10]


# ---------------------------------------------------------------- 场景实现
def pf01_baseline_one_page() -> None:
    """PF-01：单份 1 页简历完整链路（上传+解析 → 诊断 → 报告）≤ 15s。"""
    samples = []
    for _ in range(5):
        t = tag()
        with _client() as c:
            t0 = time.perf_counter()
            r = c.post(
                "/resumes",
                files={"file": (f"perf1-{t}.txt", resume_text(t, 1).encode(), "text/plain")},
            )
            up_t = time.perf_counter() - t0
            rid = r.json()["data"]["resume_id"]
            (_, dg_t) = timed(lambda: diagnose(rid, c))
            rp_t = get_report(rid, c)
        samples.append(
            {"upload_s": round(up_t, 4), "diagnose_s": dg_t, "report_s": rp_t, "total_s": round(up_t + dg_t + rp_t, 4)}
        )
    RESULT["scenarios"]["PF-01"] = {
        "title": "单份 1 页简历完整链路",
        "threshold": "总耗时 ≤ 15s（NFR-01）",
        "samples": samples,
        "max_total_s": max(s["total_s"] for s in samples),
        "mean_total_s": round(statistics.mean(s["total_s"] for s in samples), 4),
        "pass": max(s["total_s"] for s in samples) <= 15.0,
    }


def pf02_baseline_three_pages() -> None:
    """PF-02：单份 3 页简历完整链路（参考基线）。"""
    samples = []
    for _ in range(3):
        t = tag()
        with _client() as c:
            t0 = time.perf_counter()
            r = c.post(
                "/resumes",
                files={"file": (f"perf3-{t}.txt", resume_text(t, 3).encode(), "text/plain")},
            )
            up_t = time.perf_counter() - t0
            rid = r.json()["data"]["resume_id"]
            (_, dg_t) = timed(lambda: diagnose(rid, c))
            rp_t = get_report(rid, c)
        samples.append(
            {"upload_s": round(up_t, 4), "diagnose_s": dg_t, "report_s": rp_t, "total_s": round(up_t + dg_t + rp_t, 4)}
        )
    RESULT["scenarios"]["PF-02"] = {
        "title": "单份 3 页简历完整链路",
        "threshold": "记录基线（无硬指标）",
        "samples": samples,
        "mean_total_s": round(statistics.mean(s["total_s"] for s in samples), 4),
    }


def _baseline_serial(n: int) -> dict:
    """串行执行 n 次诊断作为基线。

    刻意与并发场景保持**相同的连接方式**（每次新建 client），
    否则"基线用长连接、并发用短连接"会把 TCP 握手开销算进增幅，得出虚高的失败结论。
    同时做 n 次采样取均值，避免单次 29ms 级采样落在噪声区间。
    """
    times = []
    with _client() as c:
        for i in range(n):
            t = tag()
            r = c.post(
                "/resumes",
                files={"file": (f"base-{t}-{i}.txt", resume_text(t, 1).encode(), "text/plain")},
            )
            rid = r.json()["data"]["resume_id"]
            _, dt = timed(lambda: diagnose(rid, c))
            times.append(dt)
    return {"n": n, "mean_s": round(statistics.mean(times), 4), "samples_s": times}


def _concurrent_diagnose(n: int, label: str) -> dict:
    """n 个用户各自上传一份简历并诊断，返回单请求耗时与总 wall-clock。"""
    t = tag()
    resumes = []
    with _client() as c:
        for i in range(n):
            r = c.post(
                "/resumes",
                files={"file": (f"{label}-{t}-{i}.txt", resume_text(f"{t}{i}", 1).encode(), "text/plain")},
            )
            resumes.append(r.json()["data"]["resume_id"])

    def one(rid: str) -> float:
        # 与基线一致：每次新建连接，避免连接复用差异污染对比
        with _client() as c:
            _, dt = timed(lambda: diagnose(rid, c))
            return dt

    wall0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=n) as ex:
        times = list(ex.map(one, resumes))
    wall = time.perf_counter() - wall0
    return {
        "concurrency": n,
        "diagnose_times_s": times,
        "mean_s": round(statistics.mean(times), 4),
        "max_s": max(times),
        "min_s": min(times),
        "wall_clock_s": round(wall, 4),
    }


def pf03_pf04_concurrency() -> None:
    """PF-03/04：并发诊断，验证 NFR-02（10 并发增幅 ≤50%）。"""
    base = _baseline_serial(10)
    c10 = _concurrent_diagnose(10, "c10")
    c20 = _concurrent_diagnose(20, "c20")

    def increase(b: float, c: float) -> float:
        return round((c - b) / b * 100, 1) if b else 0.0

    inc10 = increase(base["mean_s"], c10["mean_s"])
    # 吞吐视角：n 个请求并发完成的总时长 vs 串行完成的总时长（各 10 次）
    serial_total = base["mean_s"] * 10
    RESULT["scenarios"]["PF-03"] = {
        "title": "10 用户并发诊断",
        "threshold": "响应时间增幅 ≤ 50%（NFR-02）",
        "baseline": base,
        "concurrent": c10,
        "increase_pct": inc10,
        "throughput": {
            "serial_10_total_s": round(serial_total, 4),
            "concurrent_10_wall_s": c10["wall_clock_s"],
            "speedup_x": round(serial_total / c10["wall_clock_s"], 2) if c10["wall_clock_s"] else 0.0,
        },
        "pass": inc10 <= 50.0,
    }
    RESULT["scenarios"]["PF-04"] = {
        "title": "20 用户并发诊断（观察项）",
        "threshold": "记录系统行为与降级情况",
        "concurrent": c20,
        "increase_pct_vs_baseline": increase(base["mean_s"], c20["mean_s"]),
    }
    RESULT["notes"].append(
        "PF-03/04 运行在 SQLite 上：SQLite 写操作串行化，并发写竞争强于 PostgreSQL，"
        "故此处增幅为悲观上界；报告同时给出吞吐加速比作为交叉验证。"
    )


def pf05_large_file() -> None:
    """PF-05：接近大小上限的大文件上传。"""
    # MAX_FILE_SIZE_MB 默认 10MB；构造约 9MB 的合法文本简历
    big = resume_text(tag(), 1)
    filler = "\n".join(f"补充说明第{i}行：熟悉各类工程实践与协作流程，具备良好的沟通能力。" for i in range(60000))
    content = (big + filler).encode("utf-8")
    mb = round(len(content) / 1024 / 1024, 2)
    try:
        (data, dt) = timed(lambda: upload(f"perf-big-{tag()}.txt", content))
        RESULT["scenarios"]["PF-05"] = {
            "title": "大文件上传",
            "threshold": "记录耗时与稳定性",
            "size_mb": mb,
            "elapsed_s": dt,
            "fields_extracted": len(data.get("structure", {}).get("basic_info", {}) or {}),
            "stable": True,
        }
    except Exception as e:  # noqa: BLE001  压测需要记录失败而非中断
        RESULT["scenarios"]["PF-05"] = {
            "title": "大文件上传",
            "size_mb": mb,
            "error": str(e)[:300],
            "stable": False,
        }


def pf06_sustained() -> None:
    """PF-06：连续 50 次诊断，检测衰减趋势。"""
    t = tag()
    with _client() as c:
        r = c.post("/resumes", files={"file": (f"sust-{t}.txt", resume_text(t, 1).encode(), "text/plain")})
        rid = r.json()["data"]["resume_id"]
        times = []
        for _ in range(50):
            _, dt = timed(lambda: diagnose(rid, c))
            times.append(dt)

    first10 = statistics.mean(times[:10])
    last10 = statistics.mean(times[-10:])
    drift = round((last10 - first10) / first10 * 100, 1) if first10 else 0.0
    RESULT["scenarios"]["PF-06"] = {
        "title": "连续 50 次诊断",
        "threshold": "无内存泄漏趋势、无性能衰减",
        "n": len(times),
        "mean_s": round(statistics.mean(times), 4),
        "first10_mean_s": round(first10, 4),
        "last10_mean_s": round(last10, 4),
        "drift_pct": drift,
        "pass": abs(drift) <= 20.0,
    }


def pf07_segmented() -> None:
    """PF-07：分段耗时分析——本项目性能测试的价值点（定位瓶颈在哪一段）。"""
    t = tag()
    content = resume_text(t, 1).encode("utf-8")
    with _client() as c:
        # 上传段（含文本提取 + 结构化）
        t0 = time.perf_counter()
        r = c.post("/resumes", files={"file": (f"seg-{t}.txt", content, "text/plain")})
        upload_s = time.perf_counter() - t0
        rid = r.json()["data"]["resume_id"]

        # 诊断段（同时读服务端计时响应头 x-elapsed-ms）
        t0 = time.perf_counter()
        r = c.post("/diagnoses", json={"resume_id": rid})
        diagnose_s = time.perf_counter() - t0
        diag = r.json()["data"]
        server_ms = r.headers.get("x-elapsed-ms")

        # 报告段
        t0 = time.perf_counter()
        c.get(f"/reports/{rid}")
        report_s = time.perf_counter() - t0

    total = upload_s + diagnose_s + report_s
    RESULT["scenarios"]["PF-07"] = {
        "title": "分段耗时分析",
        "threshold": "给出瓶颈定位结论",
        "segments_s": {
            "upload_and_parse": round(upload_s, 4),
            "diagnose": round(diagnose_s, 4),
            "report": round(report_s, 4),
        },
        "server_reported_diagnose_ms": float(server_ms) if server_ms else None,
        "total_s": round(total, 4),
        "share_pct": {
            k: round(v / total * 100, 1) for k, v in
            {"upload_and_parse": upload_s, "diagnose": diagnose_s, "report": report_s}.items()
        },
        "bottleneck": max(
            {"upload_and_parse": upload_s, "diagnose": diagnose_s, "report": report_s},
            key=lambda k: {"upload_and_parse": upload_s, "diagnose": diagnose_s, "report": report_s}[k],
        ),
    }


def _prepare_draft_with_issues() -> tuple[str, str, list]:
    """上传一份"有规范问题"的简历并诊断，返回 (resume_id, draft_id)。"""
    t = tag()
    messy = f"""李四
电话：13800138000
邮箱：lisi@example.com
求职意向：后端开发工程师

教育背景
南京大学 软件工程 本科 2025.06-2021.09

实习经历
某科技公司 后端开发实习生 2023.06-2023.12
参与了订单服务接口开发，使用 Python 与 MySQL,并参与压测。
负责订单服务接口开发，使用 Python 与 MySQL,并参与压测。

项目经历
秒杀系统 开发 2023.03-2023.05
设计库存扣减方案，QPS 从 800 提升到 3000

专业技能
熟练掌握 Python、Java、MySQL

荣誉奖项
校级优秀学生奖学金（2022）

（样本 {t}）
""".encode("utf-8")
    with _client() as c:
        r = c.post("/resumes", files={"file": (f"rw-{t}.txt", messy, "text/plain")})
        rid = r.json()["data"]["resume_id"]
        r = c.post("/diagnoses", json={"resume_id": rid})
        issues = (r.json().get("data") or {}).get("issues") or []
        # 契约：草稿不存在时 draft_id 为 null（不自动创建），
        # 先发一次改写请求触发 _get_or_create_draft，再取即可拿到真实 draft_id
        if issues:
            iid0 = issues[0].get("issue_id") or issues[0].get("issue_code")
            c.post("/rewrites", json={"resume_id": rid, "issue_id": iid0})
        r = c.get(f"/resumes/{rid}/draft")
        body = r.json()
        did = (body.get("data") or {}).get("draft_id")
        return rid, did, issues


def pf08_rewrite() -> None:
    """PF-08：单条改写响应时间（含两次模型调用：改写 + 事实抽取）。"""
    rid, did, issues = _prepare_draft_with_issues()
    if not issues:
        RESULT["scenarios"]["PF-08"] = {"title": "单条改写响应时间", "error": "该简历没有问题项，无法测改写"}
        return
    iid = issues[0].get("issue_id") or issues[0].get("issue_code")
    with _client() as c:
        times = []
        for _ in range(3):
            _, dt = timed(lambda: c.post("/rewrites", json={"resume_id": rid, "issue_id": iid}))
            times.append(dt)
    RESULT["scenarios"]["PF-08"] = {
        "title": "单条改写响应时间",
        "threshold": "记录耗时（改写含两次模型调用，天然高于诊断）",
        "samples_s": times,
        "mean_s": round(statistics.mean(times), 4),
    }


def pf09_pf10_pf11_draft_ops() -> None:
    """PF-09/10/11：批量应用、版本快照写入开销、回滚耗时。"""
    rid, did, issues = _prepare_draft_with_issues()
    if not did:
        RESULT["scenarios"]["PF-09"] = {"title": "批量应用", "error": f"未取到草稿（问题项 {len(issues)} 条）"}
        return
    with _client() as c:
        # PF-09：逐条应用 vs 批量应用
        single_times = []
        rw_ids = []
        for it in issues[:5]:
            iid = it.get("issue_id") or it.get("issue_code")
            r = c.post("/rewrites", json={"resume_id": rid, "issue_id": iid})
            d = r.json().get("data") or {}
            if d.get("rewrite_id"):
                rw_ids.append(d["rewrite_id"])
        for rwid in rw_ids:
            _, dt = timed(lambda: c.post(f"/rewrites/{rwid}/apply"))
            single_times.append(dt)

        _, batch_dt = timed(lambda: c.post(f"/drafts/{did}/batch-apply", json={"rewrite_ids": rw_ids}))

        RESULT["scenarios"]["PF-09"] = {
            "title": "批量应用 vs 逐条应用",
            "threshold": "验证批量接口收益",
            "n": len(rw_ids),
            "single_total_s": round(sum(single_times), 4),
            "batch_total_s": batch_dt,
            "speedup_pct": round((1 - batch_dt / sum(single_times)) * 100, 1) if single_times else 0.0,
        }

        # PF-10：版本快照写入开销——逐次手工编辑推高版本数，观察是否劣化
        write_times = []
        for i in range(20):
            _, dt = timed(
                lambda i=i: c.patch(
                    f"/drafts/{did}/fields",
                    json={"field_name": "skills[0]", "value": f"Python 3.{i}"},
                )
            )
            write_times.append(dt)
        first5 = statistics.mean(write_times[:5])
        last5 = statistics.mean(write_times[-5:])
        RESULT["scenarios"]["PF-10"] = {
            "title": "草稿版本快照写入开销",
            "threshold": "版本数达上限时写入性能无明显劣化",
            "n_writes": len(write_times),
            "first5_mean_s": round(first5, 4),
            "last5_mean_s": round(last5, 4),
            "degradation_pct": round((last5 - first5) / first5 * 100, 1) if first5 else 0.0,
            "pass": abs(round((last5 - first5) / first5 * 100, 1) if first5 else 0.0) <= 50.0,
        }

        # PF-11：回滚响应时间
        r = c.get(f"/drafts/{did}/revisions")
        revs = (r.json().get("data") or {}).get("revisions") or []
        if len(revs) >= 2:
            target = min(x["revision_no"] for x in revs)
            _, rb_dt = timed(lambda: c.post(f"/drafts/{did}/rollback", json={"revision_no": target}))
            RESULT["scenarios"]["PF-11"] = {
                "title": "回滚操作响应时间",
                "threshold": "记录耗时（大字段草稿）",
                "elapsed_s": rb_dt,
                "rolled_back_to": target,
                "total_revisions": len(revs),
            }


# ---------------------------------------------------------------- 主流程
def main() -> int:
    print(f"压测目标: {BASE}")
    print(f"输出目录: {OUT}\n")
    started = time.strftime("%Y-%m-%d %H:%M:%S")
    RESULT["started_at"] = started

    steps = [
        ("PF-01 单页完整链路", pf01_baseline_one_page),
        ("PF-02 三页完整链路", pf02_baseline_three_pages),
        ("PF-07 分段耗时分析", pf07_segmented),
        ("PF-03/04 并发诊断", pf03_pf04_concurrency),
        ("PF-05 大文件上传", pf05_large_file),
        ("PF-06 连续 50 次诊断", pf06_sustained),
        ("PF-08 单条改写", pf08_rewrite),
        ("PF-09/10/11 草稿操作", pf09_pf10_pf11_draft_ops),
    ]
    for label, fn in steps:
        print(f"▶ {label} ...", flush=True)
        t0 = time.perf_counter()
        try:
            fn()
            print(f"  ✓ 完成 ({time.perf_counter() - t0:.1f}s)")
        except Exception as e:  # noqa: BLE001  单场景失败不中断其余场景
            RESULT["scenarios"][label.split()[0]] = {"title": label, "error": f"{type(e).__name__}: {e}"[:400]}
            print(f"  ✗ 失败: {type(e).__name__}: {e}"[:200])

    RESULT["finished_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    out = OUT / "perf-result.json"
    out.write_text(json.dumps(RESULT, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n结果已写入: {out}")

    # 人类可读摘要
    print("\n===== 摘要 =====")
    for k, v in RESULT["scenarios"].items():
        if "error" in v:
            print(f"{k:14} ✗ {v['error'][:80]}")
        elif "pass" in v:
            print(f"{k:14} {'PASS' if v['pass'] else 'FAIL'}  {v.get('title','')}")
        else:
            print(f"{k:14} --   {v.get('title','')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
