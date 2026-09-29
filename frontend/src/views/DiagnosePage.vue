<template>
  <div v-loading="loading">
    <!-- ===== 未诊断：发起体检 ===== -->
    <template v-if="!loading && !report">
      <div class="page-hero">
        <div class="kicker">Diagnosis · 三维度体检</div>
        <h1>让机器给这份简历做一次<span class="hl">全面体检</span></h1>
        <p>
          三个维度独立运行、互不影响：基础规范看排版与事实一致性，内容质量看每条经历有没有说服力，
          ATS 适配模拟招聘系统的读取过程。每条结论都附带判定依据，可逐条核对。
        </p>
      </div>

      <section class="panel" style="--i: 1">
        <header class="mod-head">
          <span class="mod-no">[ D.00 ]</span>
          <h2 class="mod-title">目标岗位</h2>
          <span class="mod-en">job_description</span>
          <span class="mod-count">可选 · 填了才做岗位匹配</span>
        </header>
        <div class="mod-body">
          <div class="jd-form">
            <input
              v-model="jdTitle"
              class="jd-input"
              type="text"
              placeholder="岗位名称，如：后端开发工程师"
              maxlength="200"
            />
            <textarea
              v-model="jdText"
              class="jd-textarea"
              rows="9"
              placeholder="粘贴岗位描述（职责 + 任职要求）。服务端会提取关键技能、学历与经验要求，再与简历逐项比对。"
              maxlength="20000"
            ></textarea>
            <div class="jd-foot">
              <span class="jd-hint">
                <b class="mono">{{ jdText.length }}</b> / 20000 字符 ·
                匹配维度为独立评分，<b>不计入健康分</b>
              </span>
              <el-button class="run-btn" :disabled="running" @click="start">
                <span v-if="!running">开始诊断 →</span>
                <span v-else>诊断中…</span>
              </el-button>
            </div>
          </div>
        </div>
      </section>

      <section class="panel" style="--i: 2">
        <header class="mod-head">
          <span class="mod-no">[ D.01 ]</span>
          <h2 class="mod-title">诊断维度</h2>
          <span class="mod-en">dimensions</span>
          <span class="mod-count"><b>3</b> 项质量维度 + 1 项匹配</span>
        </header>
        <div class="mod-body">
          <div class="dim-intro">
            <div class="dim-intro-item">
              <span class="di-no">01</span>
              <div>
                <b>基础规范 · norm</b>
                <p>标点混用、日期格式、时间线倒序与断层、联系方式、无关个人信息、错别字</p>
              </div>
            </div>
            <div class="dim-intro-item">
              <span class="di-no">02</span>
              <div>
                <b>内容质量 · content</b>
                <p>逐条判断经历描述有没有「做了什么 / 怎么做 / 结果如何」，以及量化、空话套话、注水</p>
              </div>
            </div>
            <div class="dim-intro-item">
              <span class="di-no">03</span>
              <div>
                <b>ATS 适配 · machine</b>
                <p>模拟招聘系统读取，逐字段给出「正确读取 / 丢失 / 错位 / 编造」四类结论</p>
              </div>
            </div>
            <div class="dim-intro-item is-opt">
              <span class="di-no">04</span>
              <div>
                <b>岗位匹配 · match</b>
                <p>提交 JD 后启用：关键要求逐项比对，输出匹配评分与缺口清单</p>
              </div>
            </div>
          </div>
        </div>
      </section>
    </template>

    <!-- ===== 已诊断：报告 ===== -->
    <template v-else-if="!loading && report">
      <div class="page-hero">
        <div class="kicker">Diagnosis Report · 综合报告</div>
        <h1>体检完成，共 <span class="hl">{{ report.issue_summary?.total || 0 }}</span> 项待改进</h1>
        <p>
          健康分只衡量简历本身的质量（基础规范 / 内容质量 / ATS 适配）；
          若提交了岗位描述，匹配分单独计算——它取决于岗位，不代表简历好坏。
        </p>
      </div>

      <!-- 总分 + 维度分 -->
      <div class="result-meta">
        <span class="meta-chip">resume_id<b class="mono">{{ shortId }}</b></span>
        <span class="meta-chip">health<b class="mono" :class="scoreClass(report.total_score)">{{ report.total_score }}</b></span>
        <span class="meta-chip">issues<b class="mono">{{ report.issue_summary?.total || 0 }}</b></span>
        <span class="meta-chip">reproducible<b class="mono">{{ report.reproducible ? "true" : "false" }}</b></span>
        <el-button class="meta-export" text :disabled="exporting" @click="exportReport">
          <el-icon style="margin-right: 4px"><download /></el-icon>
          {{ exporting ? "导出中…" : "导出报告 ↓" }}
        </el-button>
        <el-button class="meta-refresh" text @click="start">
          <el-icon style="margin-right: 4px"><refresh /></el-icon>重新诊断
        </el-button>
      </div>

      <section class="panel" style="--i: 1">
        <header class="mod-head">
          <span class="mod-no">[ R.01 ]</span>
          <h2 class="mod-title">维度得分</h2>
          <span class="mod-en">dimension_scores</span>
          <span class="mod-count">FR-10 综合健康分</span>
        </header>
        <div class="mod-body">
          <div class="dim-grid">
            <div
              v-for="(dim, key) in report.dimension_scores"
              :key="key"
              class="dim-card"
              :class="{ 'is-match': !dim.counted_in_health }"
            >
              <div class="dc-head">
                <span class="dc-name">{{ dim.label }}</span>
                <span class="dc-en mono">{{ key }}</span>
              </div>
              <div class="dc-score" :class="scoreClass(dim.score)">
                {{ dim.score }}<i>/100</i>
              </div>
              <div class="dc-bar"><i :style="{ width: dim.score + '%' }" :class="scoreClass(dim.score)"></i></div>
              <div class="dc-foot">
                <span><b class="mono">{{ dim.issue_count }}</b> 项问题</span>
                <span v-if="!dim.counted_in_health" class="dc-tag">不计入健康分</span>
                <span v-else class="dc-rule mono">rule {{ dim.rule_version }}</span>
              </div>
            </div>
          </div>
        </div>
      </section>

      <!-- ATS 四类结论 -->
      <section v-if="machineDetail" class="panel" style="--i: 2">
        <header class="mod-head">
          <span class="mod-no">[ R.02 ]</span>
          <h2 class="mod-title">ATS 读取结论</h2>
          <span class="mod-en">field_verdicts</span>
          <span class="mod-count"><b>{{ machineDetail.verdict_summary?.correct || 0 }}</b> 个字段正确读取</span>
        </header>
        <div class="mod-body">
          <div class="verdict-grid">
            <div class="verdict-cell is-ok">
              <span class="vc-no mono">{{ machineDetail.verdict_summary?.correct || 0 }}</span>
              <span class="vc-t">正确读取</span>
              <span class="vc-e mono">correct</span>
            </div>
            <div class="verdict-cell is-lost">
              <span class="vc-no mono">{{ machineDetail.verdict_summary?.lost || 0 }}</span>
              <span class="vc-t">丢失</span>
              <span class="vc-e mono">lost</span>
            </div>
            <div class="verdict-cell is-mis">
              <span class="vc-no mono">{{ machineDetail.verdict_summary?.misplaced || 0 }}</span>
              <span class="vc-t">错位</span>
              <span class="vc-e mono">misplaced</span>
            </div>
            <div class="verdict-cell is-fab">
              <span class="vc-no mono">{{ machineDetail.verdict_summary?.fabricated || 0 }}</span>
              <span class="vc-t">编造</span>
              <span class="vc-e mono">fabricated</span>
            </div>
          </div>

          <div class="logbox" :class="{ open: traceOpen }">
            <button class="logbox-head" @click="traceOpen = !traceOpen">
              <el-icon><terminal /></el-icon>
              <span>tail -f ats_verdicts.log</span>
              <el-icon class="caret"><arrow-right /></el-icon>
            </button>
            <div v-show="traceOpen" class="logbox-body">
              <div
                class="logline"
                :class="'v-' + pt.verdict"
                v-for="(pt, i) in machineDetail.parse_trace"
                :key="'pt' + i"
              >
                <span class="ln">{{ String(i + 1).padStart(2, "0") }}</span>
                <span class="field">{{ pt.field }}</span>
                <span class="arrow">→</span>
                <span class="value">{{ pt.extracted || "(空)" }}</span>
                <span class="verdict" :class="'v-' + pt.verdict">{{ pt.verdict }}</span>
                <span class="rule">{{ pt.rule_applied }}</span>
              </div>
            </div>
          </div>
        </div>
      </section>

      <!-- 岗位匹配明细 -->
      <section v-if="matchDetail" class="panel" style="--i: 3">
        <header class="mod-head">
          <span class="mod-no">[ R.03 ]</span>
          <h2 class="mod-title">岗位匹配明细</h2>
          <span class="mod-en">requirement_matches</span>
          <span class="mod-count">缺口 <b>{{ matchDetail.gaps?.length || 0 }}</b> 项</span>
        </header>
        <div class="mod-body">
          <table class="match-table">
            <thead>
              <tr>
                <th>岗位要求</th>
                <th>结论</th>
                <th>证据 / 说明</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(m, i) in matchDetail.matches" :key="'m' + i">
                <td class="mt-req">{{ m.requirement }}</td>
                <td>
                  <span class="mt-verdict" :class="'v-' + m.verdict">
                    {{ verdictLabel(m.verdict) }}
                  </span>
                  <span v-if="m.hint" class="mt-hint">{{ m.hint }}</span>
                </td>
                <td class="mt-ev">{{ m.evidence }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <!-- 问题清单（FR-11 按优先级排序） -->
      <section class="panel" style="--i: 4">
        <header class="mod-head">
          <span class="mod-no">[ R.04 ]</span>
          <h2 class="mod-title">问题清单</h2>
          <span class="mod-en">issue_queue</span>
          <span class="mod-count">按「影响大且好改 → 影响大难改 → 影响小」排序</span>
        </header>
        <div class="mod-body">
          <div
            v-for="group in issueGroups"
            :key="group.key"
            class="issue-group"
            :class="'g-' + group.key"
          >
            <button class="ig-head" @click="group.open = !group.open">
              <span class="ig-no">{{ group.no }}</span>
              <span class="ig-name">{{ group.name }}</span>
              <span class="ig-count mono">{{ group.items.length }}</span>
              <span class="ig-desc">{{ group.desc }}</span>
              <el-icon class="caret"><arrow-right /></el-icon>
            </button>
            <div v-show="group.open" class="ig-body">
              <div v-if="!group.items.length" class="ig-empty">// 该分组无问题</div>
              <div class="issue-item" v-for="issue in group.items" :key="issue.issue_id">
                <div class="ii-head">
                  <span class="sev" :class="'s-' + issue.severity">{{ issue.severity_label }}</span>
                  <span class="ii-cat">{{ issue.category }}</span>
                  <span class="ii-field mono">{{ issue.field }}</span>
                </div>
                <div class="ii-problem">{{ issue.problem }}</div>
                <div v-if="issue.snippet" class="ii-snippet">「{{ issue.snippet }}」</div>
                <div class="ii-sug"><b>建议</b>{{ issue.suggestion }}</div>
                <div v-if="issue.evidence" class="ii-ev">
                  <span class="mono">evidence</span>{{ issue.evidence }}
                  <span class="ii-conf mono">confidence {{ issue.confidence ?? 1.0 }}</span>
                </div>
                <!-- FR-12：报告层只读的修改建议（不落到草稿，落到草稿请去草稿工作台） -->
                <div class="ii-act">
                  <button
                    class="adv-btn"
                    :class="{ on: !!advice[issue.issue_id]?.data }"
                    :disabled="advice[issue.issue_id]?.loading"
                    @click="toggleAdvice(issue)"
                  >
                    <span v-if="advice[issue.issue_id]?.loading">生成建议中…</span>
                    <span v-else-if="advice[issue.issue_id]?.data">收起建议 ↑</span>
                    <span v-else>看修改建议 →</span>
                  </button>
                  <span class="adv-note-inline mono">FR-12 · 只读展示</span>
                </div>
                <div v-if="advice[issue.issue_id]?.error" class="adv-err">
                  <span class="mono">[ ! ]</span>{{ advice[issue.issue_id].error }}
                </div>
                <div v-else-if="advice[issue.issue_id]?.data" class="adv-panel">
                  <!-- 有安全改写：修改前后对照 + 改动点 -->
                  <template v-if="advice[issue.issue_id].data.status === 'generated'">
                    <div class="adv-cmp">
                      <div class="adv-side is-before">
                        <span class="adv-tag mono">before · 原句</span>
                        <p>{{ advice[issue.issue_id].data.before }}</p>
                      </div>
                      <span class="adv-arrow mono">→</span>
                      <div class="adv-side is-after">
                        <span class="adv-tag mono">after · 建议改为</span>
                        <p>{{ advice[issue.issue_id].data.after }}</p>
                      </div>
                    </div>
                    <div class="cp-block">
                      <div class="cp-hd mono">
                        change_points · 改动点
                        <span class="cp-count">{{ advice[issue.issue_id].data.change_points?.length || 0 }}</span>
                      </div>
                      <div v-if="!advice[issue.issue_id].data.change_points?.length" class="cp-empty mono">// 无改动点</div>
                      <div v-else class="cp-list">
                        <div
                          v-for="(cp, i) in advice[issue.issue_id].data.change_points"
                          :key="i"
                          class="cp-row"
                          :class="`cp-${cp.change_class}`"
                        >
                          <span class="cp-class mono">{{ cp.change_class_label }}</span>
                          <span class="cp-text mono">
                            <span class="cp-before">「{{ cp.before_text }}」</span>
                            <span class="cp-arrow">→</span>
                            <span class="cp-after">「{{ cp.after_text }}」</span>
                          </span>
                        </div>
                      </div>
                    </div>
                    <div class="adv-risk">
                      <span class="adv-risk-tag mono" :class="advice[issue.issue_id].data.risk_level">
                        {{ riskLabel(advice[issue.issue_id].data.risk_level) }}
                      </span>
                      <span
                        v-for="(r, i) in advice[issue.issue_id].data.risk_reasons || []"
                        :key="i"
                        class="adv-risk-reason"
                        >{{ r }}</span
                      >
                    </div>
                    <div class="adv-foot">
                      本面板为只读建议；要写入简历请到<b>草稿工作台</b>对同一条问题发起改写并应用。
                    </div>
                  </template>
                  <!-- 降级：只提示缺什么信息，不替用户编造内容 -->
                  <template v-else>
                    <div class="adv-fallback">
                      <div class="adv-fb-tag mono">[ ! ] suggestion_only · 无法安全改写</div>
                      <p class="adv-fb-reason">{{ advice[issue.issue_id].data.reason || "该问题无法由规则安全改写" }}</p>
                      <p class="adv-fb-hint">
                        系统只提示缺什么信息，<b>不替用户编造内容</b>。请按上方「建议」手动修改；
                        需要逐句落地时，可到草稿工作台用引导式亮点挖掘补齐真实信息。
                      </p>
                    </div>
                  </template>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>
    </template>

    <!-- 空状态 -->
    <div v-else-if="!loading" class="panel" style="--i: 1">
      <div class="blank">
        <div class="blank-glyph">[ × ]</div>
        <div class="blank-t">未找到该简历</div>
        <div class="blank-s">ERR: record not found or already deleted</div>
        <el-button type="primary" style="margin-top: 20px" @click="$router.push('/upload')">
          去上传一份 →
        </el-button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from "vue";
import { useRoute } from "vue-router";
import { ElMessage } from "element-plus";
import { diagnosisApi, optimizeApi } from "../api/client";

const route = useRoute();
const loading = ref(true);
const running = ref(false);
const report = ref(null);
const machineDetail = ref(null);
const matchDetail = ref(null);
const traceOpen = ref(true);
const exporting = ref(false);
// FR-12：按 issue_id 缓存报告层的只读修改建议
const advice = ref({});

const jdTitle = ref("");
const jdText = ref("");
const jdId = ref(null);

const shortId = computed(() => route.params.id.slice(0, 8));

const issueGroups = computed(() => {
  const groups = report.value?.issue_summary?.groups || {};
  const map = [
    { key: "high_impact_easy", no: "01", name: "影响大 · 好改", desc: "先改这些，性价比最高", items: groups.high_impact_easy || [] },
    { key: "high_impact_hard", no: "02", name: "影响大 · 难改", desc: "需要补充真实经历或信息", items: groups.high_impact_hard || [] },
    { key: "low_impact", no: "03", name: "影响小", desc: "时间充裕时再处理", items: groups.low_impact || [] },
  ];
  return map.map((g) => ({ ...g, open: g.no === "01" }));
});

function scoreClass(score) {
  if (score >= 85) return "s-good";
  if (score >= 60) return "s-mid";
  return "s-bad";
}

function verdictLabel(v) {
  return { covered: "已覆盖", partial: "部分覆盖", missing: "完全缺失" }[v] || v;
}

function riskLabel(level) {
  return { auto_safe: "auto_safe · 可安全应用", needs_review: "needs_review · 需人工确认" }[level] || level || "N/A";
}

// FR-12：复用改写引擎做只读展示。6001（字段不在草稿）/ 6002（事实校验失败）
// 由拦截器转成 Error  message，这里内联展示，不静默吞掉。
async function toggleAdvice(issue) {
  const cur = advice.value[issue.issue_id];
  if (cur && cur.data) {
    advice.value[issue.issue_id] = null;
    return;
  }
  advice.value[issue.issue_id] = { loading: true, data: null, error: "" };
  try {
    const body = await optimizeApi.generateRewrite({
      resume_id: route.params.id,
      issue_id: issue.issue_id,
    });
    advice.value[issue.issue_id] = { loading: false, data: body.data, error: "" };
  } catch (e) {
    advice.value[issue.issue_id] = { loading: false, data: null, error: e.message || "建议生成失败" };
  }
}

// FR-13：导出自包含 HTML 报告。业务错误（未诊断 2002 / 已删除 2003）时后端返回
// JSON 错误体、被 blob 包装，需先解析再决定是报错还是触发下载。
async function exportReport() {
  exporting.value = true;
  try {
    const blob = await diagnosisApi.exportReport(route.params.id);
    const text = await blob.text();
    try {
      const parsed = JSON.parse(text);
      if (parsed && typeof parsed.code === "number") {
        ElMessage.error(parsed.message || "导出失败");
        return;
      }
    } catch {
      /* 不是 JSON，即正常报告 */
    }
    const fileBlob = new Blob([text], { type: "text/html;charset=utf-8" });
    const url = URL.createObjectURL(fileBlob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `diagnosis-report-${route.params.id.slice(0, 8)}.html`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    ElMessage.success("报告已导出，可用浏览器打开或打印为 PDF");
  } catch (e) {
    ElMessage.error(e.message || "导出失败");
  } finally {
    exporting.value = false;
  }
}

async function start() {
  running.value = true;
  try {
    if (jdText.value.trim().length >= 10 && !jdId.value) {
      const jd = await diagnosisApi.submitJd({
        title: jdTitle.value,
        raw_text: jdText.value,
      });
      jdId.value = jd.data.jd_id;
      ElMessage.success("岗位描述已提交，匹配维度已启用");
    }
    const body = await diagnosisApi.run({
      resume_id: route.params.id,
      jd_id: jdId.value || undefined,
    });
    report.value = body.data;
    await loadDetails();
    ElMessage.success("诊断完成");
  } catch (e) {
    ElMessage.error(e.message || "诊断失败");
  } finally {
    running.value = false;
  }
}

async function loadDetails() {
  const ids = report.value?.diagnosis_ids || [];
  const details = await Promise.all(
    ids.map((id) => diagnosisApi.getDiagnosis(id).catch(() => null))
  );
  for (const d of details) {
    if (!d) continue;
    const data = d.data;
    if (data.dimension === "machine") {
      machineDetail.value = {
        verdict_summary: data.meta?.verdict_summary || {},
        parse_trace: data.meta?.parse_trace || [],
      };
    } else if (data.dimension === "match") {
      matchDetail.value = {
        matches: data.meta?.matches || [],
        gaps: data.meta?.gaps || [],
        jd_title: data.meta?.jd_title || "",
      };
    }
  }
}

async function load() {
  loading.value = true;
  try {
    const body = await diagnosisApi.getReport(route.params.id);
    report.value = body.data;
    await loadDetails();
    try {
      localStorage.setItem("ro:last-resume-id", route.params.id);
    } catch {
      /* 隐私模式下不可用，忽略 */
    }
  } catch {
    report.value = null;
  } finally {
    loading.value = false;
  }
}

onMounted(load);
</script>

<style scoped>
/* ---------- 岗位描述表单 ---------- */
.jd-form {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.jd-input,
.jd-textarea {
  width: 100%;
  box-sizing: border-box;
  background: var(--well, #0d1216);
  border: 1px solid rgba(79, 227, 165, 0.18);
  border-radius: 3px;
  color: var(--ink, #e6efe9);
  font-family: var(--mono);
  font-size: 12.5px;
  padding: 10px 12px;
  transition: border-color 0.18s ease, box-shadow 0.18s ease;
}

.jd-input::placeholder,
.jd-textarea::placeholder {
  color: rgba(230, 239, 233, 0.32);
}

.jd-input:focus,
.jd-textarea:focus {
  outline: none;
  border-color: var(--sig);
  box-shadow: 0 0 0 3px rgba(79, 227, 165, 0.1);
}

.jd-textarea {
  line-height: 1.7;
  resize: vertical;
}

.jd-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
}

.jd-hint {
  font-size: 11.5px;
  color: rgba(230, 239, 233, 0.45);
  font-family: var(--mono);
}

.jd-hint b {
  color: var(--sig);
}

.run-btn {
  background: var(--sig) !important;
  border-color: var(--sig) !important;
  color: #06231a !important;
  font-family: var(--mono) !important;
  font-weight: 700;
  letter-spacing: 0.04em;
  padding: 10px 22px !important;
  height: auto !important;
}

.run-btn:hover:not([disabled]) {
  box-shadow: 0 0 18px rgba(79, 227, 165, 0.35);
}

.run-btn[disabled] {
  opacity: 0.5;
}

/* ---------- 维度说明（未诊断态） ---------- */
.dim-intro {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 14px;
}

.dim-intro-item {
  display: flex;
  gap: 12px;
  padding: 14px;
  background: rgba(79, 227, 165, 0.04);
  border: 1px solid rgba(79, 227, 165, 0.12);
  border-radius: 3px;
}

.dim-intro-item.is-opt {
  background: rgba(245, 181, 71, 0.04);
  border-color: rgba(245, 181, 71, 0.16);
}

.di-no {
  font-family: var(--mono);
  font-size: 11px;
  color: var(--sig);
  letter-spacing: 0.08em;
  padding-top: 2px;
}

.is-opt .di-no {
  color: var(--amber);
}

.dim-intro-item b {
  font-size: 13px;
  letter-spacing: 0.02em;
}

.dim-intro-item p {
  margin: 5px 0 0;
  font-size: 11.5px;
  line-height: 1.65;
  color: rgba(230, 239, 233, 0.5);
}

/* ---------- 维度得分卡 ---------- */
.dim-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
  gap: 14px;
}

.dim-card {
  padding: 16px;
  background: rgba(255, 255, 255, 0.02);
  border: 1px solid rgba(79, 227, 165, 0.14);
  border-radius: 3px;
}

.dim-card.is-match {
  border-color: rgba(245, 181, 71, 0.2);
  background: rgba(245, 181, 71, 0.03);
}

.dc-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
}

.dc-name {
  font-size: 13px;
  font-weight: 700;
}

.dc-en {
  font-size: 10px;
  color: rgba(230, 239, 233, 0.35);
  letter-spacing: 0.06em;
}

.dc-score {
  font-family: var(--mono);
  font-size: 34px;
  font-weight: 700;
  line-height: 1.1;
  margin: 10px 0 8px;
  font-variant-numeric: tabular-nums;
}

.dc-score i {
  font-size: 12px;
  font-style: normal;
  opacity: 0.4;
  margin-left: 2px;
}

.dc-bar {
  height: 3px;
  background: rgba(255, 255, 255, 0.07);
  border-radius: 2px;
  overflow: hidden;
}

.dc-bar i {
  display: block;
  height: 100%;
  border-radius: 2px;
  transition: width 0.6s cubic-bezier(0.22, 1, 0.36, 1);
}

.dc-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-top: 10px;
  font-size: 10.5px;
  color: rgba(230, 239, 233, 0.45);
  flex-wrap: wrap;
}

.dc-foot b {
  color: var(--sig);
}

.dc-tag {
  color: var(--amber);
  border: 1px solid rgba(245, 181, 71, 0.3);
  border-radius: 2px;
  padding: 1px 6px;
}

.dc-rule {
  opacity: 0.5;
}

/* ---------- ATS 四类结论 ---------- */
.verdict-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
  gap: 12px;
  margin-bottom: 18px;
}

.verdict-cell {
  padding: 14px;
  border-radius: 3px;
  border: 1px solid;
  text-align: center;
}

.verdict-cell.is-ok {
  border-color: rgba(79, 227, 165, 0.25);
  background: rgba(79, 227, 165, 0.05);
}

.verdict-cell.is-lost {
  border-color: rgba(229, 84, 75, 0.3);
  background: rgba(229, 84, 75, 0.06);
}

.verdict-cell.is-mis {
  border-color: rgba(245, 181, 71, 0.28);
  background: rgba(245, 181, 71, 0.05);
}

.verdict-cell.is-fab {
  border-color: rgba(229, 84, 75, 0.45);
  background: rgba(229, 84, 75, 0.1);
}

.vc-no {
  display: block;
  font-size: 28px;
  font-weight: 700;
  line-height: 1.1;
  font-variant-numeric: tabular-nums;
}

.is-ok .vc-no { color: var(--sig); }
.is-lost .vc-no,
.is-fab .vc-no { color: #e5544b; }
.is-mis .vc-no { color: var(--amber); }

.vc-t {
  display: block;
  font-size: 12px;
  margin-top: 4px;
}

.vc-e {
  display: block;
  font-size: 9.5px;
  color: rgba(230, 239, 233, 0.3);
  letter-spacing: 0.08em;
  margin-top: 2px;
}

/* ATS 日志行的判定着色 */
.logline.v-correct .verdict { color: var(--sig); }
.logline.v-lost .verdict,
.logline.v-fabricated .verdict { color: #e5544b; }
.logline.v-misplaced .verdict { color: var(--amber); }

.logline .verdict {
  font-family: var(--mono);
  font-size: 10px;
  letter-spacing: 0.06em;
  padding: 1px 5px;
  border: 1px solid currentColor;
  border-radius: 2px;
  opacity: 0.9;
}

.logline.v-lost,
.logline.v-fabricated {
  background: rgba(229, 84, 75, 0.05);
}

.logline.v-misplaced {
  background: rgba(245, 181, 71, 0.05);
}

/* ---------- 岗位匹配表 ---------- */
.match-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}

.match-table th {
  text-align: left;
  font-family: var(--mono);
  font-size: 10px;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: rgba(230, 239, 233, 0.4);
  padding: 8px 10px;
  border-bottom: 1px solid rgba(79, 227, 165, 0.16);
}

.match-table td {
  padding: 10px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.04);
  vertical-align: top;
}

.match-table tr:hover td {
  background: rgba(79, 227, 165, 0.03);
}

.mt-req {
  font-weight: 600;
  white-space: nowrap;
}

.mt-verdict {
  display: inline-block;
  font-family: var(--mono);
  font-size: 10px;
  padding: 2px 7px;
  border-radius: 2px;
  border: 1px solid currentColor;
}

.mt-verdict.v-covered { color: var(--sig); }
.mt-verdict.v-partial { color: var(--amber); }
.mt-verdict.v-missing { color: #e5544b; }

.mt-hint {
  display: block;
  font-size: 10px;
  color: rgba(230, 239, 233, 0.4);
  margin-top: 4px;
}

.mt-ev {
  color: rgba(230, 239, 233, 0.55);
  font-size: 11.5px;
  line-height: 1.6;
}

/* ---------- 问题清单分组 ---------- */
.issue-group {
  border: 1px solid rgba(79, 227, 165, 0.12);
  border-radius: 3px;
  margin-bottom: 12px;
  overflow: hidden;
}

.ig-head {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 14px;
  background: rgba(255, 255, 255, 0.02);
  border: none;
  cursor: pointer;
  color: inherit;
  text-align: left;
  transition: background 0.18s ease;
}

.ig-head:hover {
  background: rgba(79, 227, 165, 0.05);
}

.ig-no {
  font-family: var(--mono);
  font-size: 11px;
  color: var(--sig);
}

.ig-name {
  font-size: 13px;
  font-weight: 700;
}

.ig-count {
  font-size: 11px;
  color: var(--sig);
  border: 1px solid rgba(79, 227, 165, 0.3);
  border-radius: 2px;
  padding: 0 6px;
}

.ig-desc {
  font-size: 11px;
  color: rgba(230, 239, 233, 0.4);
  margin-left: auto;
}

.ig-head .caret {
  transition: transform 0.2s ease;
  color: rgba(230, 239, 233, 0.4);
  font-size: 12px;
}

.ig-body {
  padding: 4px 14px 14px;
}

.ig-empty {
  font-family: var(--mono);
  font-size: 11px;
  color: rgba(230, 239, 233, 0.3);
  padding: 12px 0;
}

/* ---------- 单条问题 ---------- */
.issue-item {
  padding: 14px 0;
  border-bottom: 1px solid rgba(255, 255, 255, 0.05);
}

.issue-item:last-child {
  border-bottom: none;
}

.ii-head {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 8px;
}

.sev {
  font-family: var(--mono);
  font-size: 10px;
  padding: 2px 7px;
  border-radius: 2px;
  border: 1px solid currentColor;
  letter-spacing: 0.04em;
}

.sev.s-critical { color: #e5544b; }
.sev.s-major { color: var(--amber); }
.sev.s-minor { color: rgba(230, 239, 233, 0.5); }
.sev.s-info { color: rgba(230, 239, 233, 0.35); }

.ii-cat {
  font-size: 12.5px;
  font-weight: 700;
}

.ii-field {
  font-size: 10.5px;
  color: rgba(230, 239, 233, 0.4);
  margin-left: auto;
}

.ii-problem {
  font-size: 12.5px;
  line-height: 1.7;
  color: rgba(230, 239, 233, 0.85);
}

.ii-snippet {
  margin-top: 8px;
  padding: 8px 10px;
  background: rgba(0, 0, 0, 0.25);
  border-left: 2px solid rgba(79, 227, 165, 0.4);
  font-size: 11.5px;
  line-height: 1.7;
  color: rgba(230, 239, 233, 0.65);
  border-radius: 0 2px 2px 0;
}

.ii-sug {
  margin-top: 8px;
  font-size: 12px;
  line-height: 1.7;
  color: var(--sig);
}

.ii-sug b {
  display: inline-block;
  font-family: var(--mono);
  font-size: 9.5px;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: rgba(79, 227, 165, 0.6);
  margin-right: 8px;
  border: 1px solid rgba(79, 227, 165, 0.3);
  border-radius: 2px;
  padding: 0 5px;
  vertical-align: 1px;
}

.ii-ev {
  margin-top: 8px;
  font-size: 11px;
  line-height: 1.65;
  color: rgba(230, 239, 233, 0.45);
}

.ii-ev > .mono {
  font-size: 9.5px;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: rgba(230, 239, 233, 0.3);
  margin-right: 8px;
}

.ii-conf {
  margin-left: 10px;
  color: rgba(230, 239, 233, 0.28);
}

/* ---------- FR-12 报告层只读建议 ---------- */
.ii-act {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 10px;
}

.adv-btn {
  font-family: var(--mono);
  font-size: 11px;
  letter-spacing: 0.06em;
  color: var(--sig);
  background: rgba(79, 227, 165, 0.07);
  border: 1px solid rgba(79, 227, 165, 0.28);
  border-radius: 3px;
  padding: 5px 12px;
  cursor: pointer;
  transition: background 0.18s ease, border-color 0.18s ease;
}

.adv-btn:hover:not(:disabled) {
  background: rgba(79, 227, 165, 0.14);
  border-color: rgba(79, 227, 165, 0.5);
}

.adv-btn:disabled {
  opacity: 0.55;
  cursor: wait;
}

.adv-btn.on {
  color: rgba(230, 239, 233, 0.75);
  border-color: rgba(230, 239, 233, 0.22);
  background: rgba(230, 239, 233, 0.05);
}

.adv-note-inline {
  font-size: 9.5px;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: rgba(230, 239, 233, 0.25);
}

.adv-err {
  margin-top: 10px;
  padding: 9px 12px;
  font-size: 12px;
  line-height: 1.6;
  color: #f0b3ad;
  background: rgba(229, 84, 75, 0.09);
  border-left: 2px solid #e5544b;
  border-radius: 0 3px 3px 0;
}

.adv-err > .mono {
  margin-right: 8px;
  color: #e5544b;
}

.adv-panel {
  margin-top: 10px;
  border: 1px solid rgba(230, 239, 233, 0.1);
  border-radius: 4px;
  background: rgba(10, 14, 16, 0.55);
  padding: 14px;
}

.adv-cmp {
  display: grid;
  grid-template-columns: 1fr auto 1fr;
  gap: 12px;
  align-items: stretch;
}

.adv-side {
  padding: 10px 12px;
  border-radius: 3px;
  background: var(--well, #0d1216);
  border: 1px solid rgba(230, 239, 233, 0.08);
}

.adv-side.is-after {
  border-color: rgba(79, 227, 165, 0.3);
  background: rgba(79, 227, 165, 0.05);
}

.adv-side p {
  margin: 8px 0 0;
  font-size: 12.5px;
  line-height: 1.7;
}

.adv-tag {
  font-size: 9.5px;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: rgba(230, 239, 233, 0.3);
}

.adv-side.is-after .adv-tag {
  color: rgba(79, 227, 165, 0.75);
}

.adv-arrow {
  align-self: center;
  color: var(--sig);
  font-size: 14px;
}

/* 改动点（与草稿工作台同口径：安全类信号绿 / 措辞琥珀 / 结构红） */
.cp-block {
  margin-top: 12px;
  border-top: 1px dashed rgba(230, 239, 233, 0.1);
  padding-top: 10px;
}

.cp-hd {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 9.5px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: rgba(230, 239, 233, 0.3);
}

.cp-count {
  padding: 0 6px;
  font-size: 10px;
  color: var(--sig);
  background: rgba(79, 227, 165, 0.1);
  border-radius: 2px;
}

.cp-empty {
  margin-top: 8px;
  font-size: 11px;
  color: rgba(230, 239, 233, 0.28);
}

.cp-list {
  margin-top: 8px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.cp-row {
  display: flex;
  align-items: baseline;
  gap: 10px;
  padding: 6px 10px;
  border-radius: 3px;
  background: rgba(230, 239, 233, 0.03);
  border-left: 2px solid transparent;
  font-size: 11.5px;
  line-height: 1.6;
}

.cp-row.cp-punctuation,
.cp-row.cp-typo,
.cp-row.cp-format {
  border-left-color: var(--sig);
}

.cp-row.cp-wording {
  border-left-color: var(--amber);
}

.cp-row.cp-structure {
  border-left-color: #e5544b;
}

.cp-class {
  flex: none;
  font-size: 10px;
  letter-spacing: 0.06em;
  color: rgba(230, 239, 233, 0.55);
}

.cp-row.cp-punctuation .cp-class,
.cp-row.cp-typo .cp-class,
.cp-row.cp-format .cp-class {
  color: var(--sig);
}

.cp-row.cp-wording .cp-class {
  color: var(--amber);
}

.cp-row.cp-structure .cp-class {
  color: #e5544b;
}

.cp-text {
  word-break: break-all;
}

.cp-before {
  color: rgba(230, 239, 233, 0.45);
  text-decoration: line-through;
  text-decoration-color: rgba(229, 84, 75, 0.5);
}

.cp-arrow {
  margin: 0 6px;
  color: rgba(230, 239, 233, 0.3);
}

.cp-after {
  color: var(--sig);
}

.adv-risk {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 12px;
}

.adv-risk-tag {
  font-size: 10px;
  letter-spacing: 0.08em;
  padding: 3px 9px;
  border-radius: 3px;
  color: var(--sig);
  background: rgba(79, 227, 165, 0.1);
  border: 1px solid rgba(79, 227, 165, 0.3);
}

.adv-risk-tag.needs_review {
  color: var(--amber);
  background: rgba(245, 181, 71, 0.1);
  border-color: rgba(245, 181, 71, 0.35);
}

.adv-risk-reason {
  font-size: 11.5px;
  color: rgba(230, 239, 233, 0.55);
}

.adv-foot {
  margin-top: 12px;
  font-size: 11.5px;
  line-height: 1.7;
  color: rgba(230, 239, 233, 0.45);
}

.adv-foot b {
  color: var(--sig);
  font-weight: 600;
}

/* 降级路径：只提示缺什么信息 */
.adv-fallback {
  padding: 4px 2px;
}

.adv-fb-tag {
  font-size: 10px;
  letter-spacing: 0.1em;
  color: var(--amber);
}

.adv-fb-reason {
  margin: 10px 0 0;
  font-size: 12.5px;
  line-height: 1.7;
  color: rgba(230, 239, 233, 0.8);
}

.adv-fb-hint {
  margin: 10px 0 0;
  font-size: 12px;
  line-height: 1.7;
  color: rgba(230, 239, 233, 0.45);
}

.adv-fb-hint b {
  color: var(--amber);
}

/* ---------- 分数着色 ---------- */
.s-good { color: var(--sig); }
.s-mid { color: var(--amber); }
.s-bad { color: #e5544b; }

.dc-bar i.s-good { background: var(--sig); }
.dc-bar i.s-mid { background: var(--amber); }
.dc-bar i.s-bad { background: #e5544b; }
</style>
