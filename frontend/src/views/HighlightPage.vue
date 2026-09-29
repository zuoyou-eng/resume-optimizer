<template>
  <div class="highlight-page">
    <!-- ============ H.00 头部：状态与步骤 ============ -->
    <section class="panel" style="--i: 1">
      <div class="mod-head">
        <span class="mod-no">[ H.00 ]</span>
        <span class="mod-title">亮点挖掘</span>
        <span class="mod-en">highlight_mining</span>
        <router-link :to="`/resumes/${route.params.id}/structure`" class="hd-link mono is-first">
          ← 解析结果
        </router-link>
        <router-link :to="`/resumes/${route.params.id}/diagnose`" class="hd-link mono">
          诊断报告 →
        </router-link>
        <router-link :to="`/resumes/${route.params.id}/draft`" class="hd-link mono">
          草稿工作台 →
        </router-link>
      </div>

      <div class="mod-body">
        <div class="kv-grid">
          <div class="kv">
            <div class="kv-k mono">resume · 简历</div>
            <div class="kv-v mono">{{ shortId }}</div>
          </div>
          <div class="kv">
            <div class="kv-k mono">candidates · 可挖条目</div>
            <div class="kv-v mono">{{ candidateCount }}</div>
          </div>
          <div class="kv">
            <div class="kv-k mono">target · 当前对象</div>
            <div class="kv-v mono" :class="{ blank: !selected }">
              {{ selected ? selected.item_title || selected.label : "未选择" }}
            </div>
          </div>
        </div>

        <!-- 步骤条：候选 → 追问 → 预览 → 写入 -->
        <ol class="step-bar">
          <li v-for="s in steps" :key="s.no" :class="{ on: step >= s.no, cur: step === s.no }">
            <span class="sb-no mono">{{ s.no }}</span>
            <span class="sb-name">{{ s.name }}</span>
            <span class="sb-en mono">{{ s.en }}</span>
          </li>
        </ol>
      </div>
    </section>

    <div class="hl-cols">
      <!-- ============ H.01 左列：候选清单 ============ -->
      <div class="col-left">
        <section class="panel" style="--i: 2">
          <div class="mod-head">
            <span class="mod-no">[ H.01 ]</span>
            <span class="mod-title">平淡经历清单</span>
            <span class="mod-en">candidate_queue</span>
            <span class="mod-count"><b>{{ candidates.length }}</b> candidates</span>
          </div>
          <div class="mod-body">
            <div v-if="loadingCandidates" class="empty-tip mono">// 正在检索内容质量诊断结论…</div>
            <div v-else-if="!candidates.length" class="empty-tip mono">
              // 没有可挖掘的平淡经历 —— 诊断未报出经历类问题，或各条目已达标
            </div>
            <div v-else class="cand-list">
              <button
                v-for="c in candidates"
                :key="c.field_name"
                class="cand-row"
                :class="{ active: selected && selected.field_name === c.field_name }"
                @click="pick(c)"
              >
                <div class="cand-top">
                  <span class="cand-title">{{ c.item_title || c.label }}</span>
                  <span class="sev-tag mono" :class="`sev-${c.severity}`">{{ c.severity }}</span>
                </div>
                <div class="cand-snippet">{{ c.snippet || "（无原文片段）" }}</div>
                <div class="cand-cats">
                  <span v-for="cat in c.categories" :key="cat" class="cat-tag mono">{{ cat }}</span>
                  <span class="cand-n mono">{{ c.issue_count }} issues</span>
                </div>
              </button>
            </div>
          </div>
        </section>
      </div>

      <!-- ============ 右列：随步骤切换 ============ -->
      <div class="col-right">
        <!-- 未选择：引导 -->
        <section v-if="step === 0" class="panel" style="--i: 3">
          <div class="mod-head">
            <span class="mod-no">[ H.02 ]</span>
            <span class="mod-title">选择挖掘对象</span>
            <span class="mod-en">select_target</span>
          </div>
          <div class="mod-body">
            <div class="guide">
              <div class="guide-glyph mono">[ ? ]</div>
              <div class="guide-tx">
                <p>从左侧清单选一段<b>平淡的经历描述</b>，系统会按「动作 → 量化 → 结果 → 佐证」逐层追问。</p>
                <p class="dim">
                  你只需回答自己真实做过的事；合成只使用<b>原文 + 你的回答</b>中的事实，
                  未经你确认不会写入任何内容。
                </p>
              </div>
            </div>
          </div>
        </section>

        <!-- 步骤 1：分层追问 -->
        <section v-else-if="step === 1" class="panel" style="--i: 3">
          <div class="mod-head">
            <span class="mod-no">[ H.02 ]</span>
            <span class="mod-title">分层追问</span>
            <span class="mod-en">layered_questions</span>
            <span class="mod-count">{{ answeredCount }}/{{ questions.length }} answered</span>
          </div>
          <div class="mod-body">
            <div class="orig-block">
              <div class="ob-hd mono">original · 当前描述</div>
              <div class="ob-body">{{ currentValue || "（该字段当前为空）" }}</div>
            </div>

            <div v-for="q in questions" :key="q.layer" class="q-block" :class="{ needed: q.needed }">
              <div class="q-top">
                <span class="q-layer mono">{{ q.label }}</span>
                <span class="q-flag mono" :class="q.needed ? 'is-need' : 'is-opt'">
                  {{ q.needed ? "建议回答" : "可跳过" }}
                </span>
              </div>
              <div class="q-text">{{ q.question }}</div>
              <div class="q-hint">{{ q.hint }}</div>
              <div class="q-example mono">{{ q.example }}</div>
              <el-input
                v-model="answers[q.layer]"
                type="textarea"
                :rows="2"
                resize="none"
                :placeholder="q.needed ? '如实回答即可，可留空跳过' : '没有可跳过'"
              />
            </div>

            <div class="q-actions">
              <el-button text class="ghost-btn" @click="backToCandidates">← 换一段</el-button>
              <el-button type="primary" class="sig-btn" :loading="composing" @click="doCompose">
                合成预览 →
              </el-button>
            </div>
            <div v-if="error" class="err-line mono">ERR: {{ error }}</div>
          </div>
        </section>

        <!-- 步骤 2：合成预览 -->
        <section v-else-if="step === 2" class="panel" style="--i: 3">
          <div class="mod-head">
            <span class="mod-no">[ H.03 ]</span>
            <span class="mod-title">合成预览</span>
            <span class="mod-en">compose_preview</span>
            <span class="mod-count" :class="preview && preview.status === 'rejected' ? 'is-bad' : 'is-ok'">
              {{ preview && preview.status === 'rejected' ? "rejected" : "composed" }}
            </span>
          </div>
          <div class="mod-body">
            <!-- 拒绝路径：宁可不输出，也不给可能编造的内容 -->
            <div v-if="preview && preview.status === 'rejected'" class="reject-block">
              <div class="rb-hd mono">[ × ] 合成被拒绝</div>
              <p class="rb-tx">{{ preview.reason }}</p>
              <p class="dim">请调整回答后重试；系统不会展示可能包含编造内容的预览。</p>
            </div>

            <template v-else-if="preview">
              <!-- before / after -->
              <div class="ba-grid">
                <div class="ba-col">
                  <div class="ba-hd mono">before · 原文</div>
                  <div class="ba-body">{{ preview.before || "（空）" }}</div>
                </div>
                <div class="ba-arrow mono">→</div>
                <div class="ba-col is-after">
                  <div class="ba-hd mono">after · 候选（可微调）</div>
                  <el-input
                    v-model="afterText"
                    type="textarea"
                    :rows="4"
                    resize="none"
                    class="ba-editor"
                  />
                </div>
              </div>

              <!-- 分段来源标注 -->
              <div class="seg-block">
                <div class="sb-hd mono">segments · 段落来源</div>
                <div class="seg-list">
                  <span v-for="(s, i) in preview.segments" :key="i" class="seg-tag mono" :class="`src-${s.source}`">
                    {{ sourceLabel(s.source) }}
                  </span>
                </div>
                <div class="seg-note dim">每段只来自原文或你的某一层回答；系统不做任何发挥。</div>
              </div>

              <!-- 事实守恒 -->
              <div class="fc-block" :class="preview.fact_check.passed ? 'is-pass' : 'is-fail'">
                <div class="fc-hd mono">
                  fact_check · 事实守恒
                  <b>{{ preview.fact_check.passed ? "PASSED" : "FAILED" }}</b>
                </div>
                <div class="fc-body mono dim">
                  facts {{ (preview.fact_check.facts_before || []).length }} → {{ (preview.fact_check.facts_after || []).length }}
                  <template v-if="(preview.fact_check.added || []).length">
                    · 新增 {{ preview.fact_check.added.length }} 项
                  </template>
                  <template v-if="(preview.fact_check.violated || []).length">
                    · 丢失 {{ preview.fact_check.violated.length }} 项
                  </template>
                </div>
              </div>

              <!-- 仍缺失的层 -->
              <div v-if="(preview.missing_layers || []).length" class="miss-block">
                <span class="miss-hd mono">missing_layers</span>
                <span v-for="m in preview.missing_layers" :key="m" class="miss-tag mono">{{ layerLabel(m) }}</span>
                <span class="miss-note dim">这些层还没答，现在写入也允许，但回答后会更出彩</span>
              </div>
            </template>

            <div class="q-actions">
              <el-button text class="ghost-btn" @click="backToQuestions">← 重新回答</el-button>
              <el-button
                v-if="preview && preview.status === 'composed'"
                type="primary"
                class="sig-btn"
                :loading="confirming"
                @click="doConfirm"
              >
                确认写入草稿 →
              </el-button>
            </div>
            <div v-if="error" class="err-line mono">ERR: {{ error }}</div>
          </div>
        </section>

        <!-- 步骤 3：写入成功 -->
        <section v-else class="panel" style="--i: 3">
          <div class="mod-head">
            <span class="mod-no">[ H.04 ]</span>
            <span class="mod-title">写入完成</span>
            <span class="mod-en">committed</span>
            <span class="mod-count is-ok">v{{ doneVersion }}</span>
          </div>
          <div class="mod-body">
            <div class="done-block">
              <div class="done-glyph mono">[ ✓ ]</div>
              <div class="done-tx">
                <p>已写入草稿并产生新版本 <b class="mono">v{{ doneVersion }}</b>（操作类型 highlight）。</p>
                <p class="dim">
                  写入内容服务端已复核事实守恒；如需调整，可随时在草稿工作台编辑或回滚版本。
                </p>
              </div>
            </div>
            <div class="q-actions">
              <el-button text class="ghost-btn" @click="backToCandidates">← 继续挖其他</el-button>
              <router-link :to="`/resumes/${route.params.id}/draft`">
                <el-button type="primary" class="sig-btn">去草稿工作台 →</el-button>
              </router-link>
            </div>
          </div>
        </section>
      </div>
    </div>
  </div>
</template>

<script setup>
// FR-09 引导式亮点挖掘：候选清单 → 分层追问 → 合成预览 → 用户确认后写入草稿。
// 三条红线（与后端一致）：只用用户提供的事实、未经确认不写入、可跳过不逼编造。
import { computed, onMounted, ref } from "vue";
import { useRoute } from "vue-router";
import { ElMessage } from "element-plus";
import { highlightApi } from "../api/client";

const route = useRoute();
const resumeId = computed(() => route.params.id);
const shortId = computed(() => String(resumeId.value).slice(0, 8));

// 步骤：0 未选择 / 1 追问 / 2 预览 / 3 完成
const steps = [
  { no: 0, name: "选择", en: "select" },
  { no: 1, name: "追问", en: "questions" },
  { no: 2, name: "预览", en: "compose" },
  { no: 3, name: "写入", en: "commit" },
];
const step = ref(0);

const candidates = ref([]);
const loadingCandidates = ref(false);
const selected = ref(null);
const currentValue = ref("");
const questions = ref([]);
const answers = ref({});
const composing = ref(false);
const confirming = ref(false);
const preview = ref(null);
const afterText = ref("");
const doneVersion = ref(0);
const error = ref("");

const candidateCount = computed(() => candidates.value.length);
const answeredCount = computed(
  () => questions.value.filter((q) => (answers.value[q.layer] || "").trim()).length
);

const SOURCE_LABELS = {
  original: "原文",
  action: "动作",
  quant: "量化",
  result: "结果",
  evidence: "佐证",
};

function sourceLabel(s) {
  return SOURCE_LABELS[s] || s;
}

function layerLabel(layer) {
  const q = questions.value.find((x) => x.layer === layer);
  return q ? q.label : layer;
}

async function loadCandidates() {
  loadingCandidates.value = true;
  try {
    const res = await highlightApi.listCandidates(resumeId.value);
    candidates.value = res.data?.candidates || [];
  } catch (e) {
    ElMessage.error(e.message || "候选清单加载失败");
  } finally {
    loadingCandidates.value = false;
  }
}

async function pick(c) {
  error.value = "";
  selected.value = c;
  answers.value = {};
  preview.value = null;
  try {
    const res = await highlightApi.questions({
      resume_id: resumeId.value,
      field_name: c.field_name,
    });
    questions.value = res.data?.questions || [];
    currentValue.value = res.data?.current_value || "";
    step.value = 1;
  } catch (e) {
    ElMessage.error(e.message || "追问生成失败");
  }
}

function backToCandidates() {
  step.value = 0;
  error.value = "";
  preview.value = null;
  loadCandidates();
}

function backToQuestions() {
  step.value = 1;
  error.value = "";
  preview.value = null;
}

async function doCompose() {
  error.value = "";
  composing.value = true;
  try {
    const res = await highlightApi.compose({
      resume_id: resumeId.value,
      field_name: selected.value.field_name,
      answers: answers.value,
    });
    preview.value = res.data || null;
    afterText.value = preview.value?.after || "";
    step.value = 2;
  } catch (e) {
    error.value = e.message || "合成失败";
  } finally {
    composing.value = false;
  }
}

async function doConfirm() {
  error.value = "";
  confirming.value = true;
  try {
    const res = await highlightApi.confirm({
      resume_id: resumeId.value,
      field_name: selected.value.field_name,
      after_text: afterText.value,
      answers: answers.value,
    });
    doneVersion.value = res.data?.current_version || 0;
    step.value = 3;
    ElMessage.success("已写入草稿");
  } catch (e) {
    // 6002：写入内容包含原文与回答之外的事实——服务端复核拒绝
    error.value = e.message || "写入失败";
  } finally {
    confirming.value = false;
  }
}

onMounted(loadCandidates);
</script>

<style scoped>
/* ============ 布局 ============ */
.hl-cols {
  display: grid;
  grid-template-columns: minmax(0, 5fr) minmax(0, 7fr);
  gap: 14px;
  align-items: start;
}

@media (max-width: 1180px) {
  .hl-cols {
    grid-template-columns: minmax(0, 1fr);
  }
}

.col-left,
.col-right {
  display: flex;
  flex-direction: column;
}

/* ============ 步骤条 ============ */
.step-bar {
  display: flex;
  gap: 8px;
  margin: 14px 0 0;
  padding: 0;
  list-style: none;
}

.step-bar li {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  background: var(--panel-2, rgba(255, 255, 255, 0.02));
  border: 1px solid var(--line);
  border-radius: 3px;
  transition: border-color 0.2s, background 0.2s;
}

.step-bar li.on {
  border-color: var(--sig-line);
}

.step-bar li.cur {
  background: var(--sig-soft);
}

.sb-no {
  font-size: 11px;
  font-weight: 700;
  color: var(--ink-4);
}

.step-bar li.on .sb-no {
  color: var(--sig);
}

.sb-name {
  font-size: 12.5px;
  font-weight: 600;
  color: var(--ink-3);
}

.step-bar li.on .sb-name {
  color: var(--ink);
}

.sb-en {
  margin-left: auto;
  font-size: 10px;
  color: var(--ink-4);
  letter-spacing: 0.08em;
}

/* ============ 候选清单 ============ */
.cand-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.cand-row {
  display: block;
  width: 100%;
  text-align: left;
  padding: 11px 12px;
  background: transparent;
  border: 1px solid var(--line);
  border-radius: 3px;
  cursor: pointer;
  transition: border-color 0.15s, background 0.15s, transform 0.15s;
  font-family: inherit;
  color: inherit;
}

.cand-row:hover {
  border-color: var(--line-hi);
  background: rgba(255, 255, 255, 0.015);
}

.cand-row.active {
  border-color: var(--sig);
  background: var(--sig-soft);
}

.cand-top {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 5px;
}

.cand-title {
  font-size: 13px;
  font-weight: 700;
  color: var(--ink);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sev-tag {
  margin-left: auto;
  flex: none;
  font-size: 10px;
  letter-spacing: 0.06em;
  padding: 1px 6px;
  border-radius: 2px;
  border: 1px solid var(--line-hi);
  color: var(--ink-3);
}

.sev-tag.sev-critical {
  color: var(--danger, #e5544b);
  border-color: rgba(229, 84, 75, 0.4);
}

.sev-tag.sev-major {
  color: var(--amber);
  border-color: rgba(245, 181, 71, 0.35);
}

.cand-snippet {
  font-size: 12px;
  line-height: 1.6;
  color: var(--mut, #7d8c96);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.cand-cats {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 5px;
  margin-top: 7px;
}

.cat-tag {
  font-size: 10px;
  color: var(--ink-3);
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid var(--line);
  border-radius: 2px;
  padding: 1px 5px;
}

.cand-n {
  margin-left: auto;
  font-size: 10px;
  color: var(--ink-4);
}

/* ============ 引导 ============ */
.guide {
  display: flex;
  gap: 16px;
  padding: 18px 6px;
}

.guide-glyph {
  font-size: 26px;
  font-weight: 700;
  color: var(--sig);
  flex: none;
}

.guide-tx p {
  margin: 0 0 8px;
  font-size: 13px;
  line-height: 1.8;
  color: var(--ink-2, #b7c3cb);
}

.guide-tx p.dim {
  color: var(--mut, #7d8c96);
  font-size: 12px;
}

.guide-tx b {
  color: var(--sig);
}

/* ============ 追问 ============ */
.orig-block {
  border: 1px solid var(--line);
  border-radius: 3px;
  margin-bottom: 14px;
  overflow: hidden;
}

.ob-hd {
  font-size: 10px;
  letter-spacing: 0.1em;
  color: var(--ink-4);
  padding: 6px 10px;
  border-bottom: 1px solid var(--line);
  background: rgba(255, 255, 255, 0.015);
}

.ob-body {
  padding: 10px 12px;
  font-size: 12.5px;
  line-height: 1.7;
  color: var(--ink-2, #b7c3cb);
}

.q-block {
  border: 1px solid var(--line);
  border-left: 2px solid var(--line-hi);
  border-radius: 3px;
  padding: 11px 12px;
  margin-bottom: 10px;
  transition: border-color 0.2s;
}

.q-block.needed {
  border-left-color: var(--sig);
}

.q-top {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}

.q-layer {
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.06em;
  color: var(--sig);
}

.q-flag {
  font-size: 10px;
  padding: 1px 6px;
  border-radius: 2px;
}

.q-flag.is-need {
  color: var(--sig);
  background: var(--sig-soft);
  border: 1px solid var(--sig-line);
}

.q-flag.is-opt {
  color: var(--amber);
  background: rgba(245, 181, 71, 0.08);
  border: 1px solid rgba(245, 181, 71, 0.3);
}

.q-text {
  font-size: 13px;
  font-weight: 600;
  color: var(--ink);
  margin-bottom: 3px;
}

.q-hint {
  font-size: 11.5px;
  color: var(--mut, #7d8c96);
  margin-bottom: 3px;
}

.q-example {
  font-size: 11px;
  color: var(--ink-4);
  margin-bottom: 8px;
}

/* ============ 预览 ============ */
.ba-grid {
  display: grid;
  grid-template-columns: 1fr auto 1fr;
  gap: 10px;
  align-items: stretch;
  margin-bottom: 14px;
}

.ba-col {
  border: 1px solid var(--line);
  border-radius: 3px;
  overflow: hidden;
  min-width: 0;
}

.ba-col.is-after {
  border-color: var(--sig-line);
}

.ba-hd {
  font-size: 10px;
  letter-spacing: 0.1em;
  color: var(--ink-4);
  padding: 6px 10px;
  border-bottom: 1px solid var(--line);
  background: rgba(255, 255, 255, 0.015);
}

.ba-col.is-after .ba-hd {
  color: var(--sig);
}

.ba-body {
  padding: 10px 12px;
  font-size: 12.5px;
  line-height: 1.7;
  color: var(--ink-2, #b7c3cb);
  min-height: 74px;
}

.ba-arrow {
  align-self: center;
  color: var(--sig);
  font-size: 16px;
}

.ba-editor :deep(.el-textarea__inner) {
  background: rgba(255, 255, 255, 0.02);
  border: none;
  border-radius: 0;
  box-shadow: none;
  color: var(--ink);
  font-size: 12.5px;
  line-height: 1.7;
  padding: 10px 12px;
}

/* 段落来源 */
.seg-block {
  border: 1px solid var(--line);
  border-radius: 3px;
  padding: 10px 12px;
  margin-bottom: 12px;
}

.sb-hd {
  font-size: 10px;
  letter-spacing: 0.1em;
  color: var(--ink-4);
  margin-bottom: 8px;
}

.seg-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.seg-tag {
  font-size: 10.5px;
  padding: 2px 7px;
  border-radius: 2px;
  border: 1px solid var(--line-hi);
  color: var(--ink-3);
}

.seg-tag.src-original {
  color: var(--sig);
  border-color: var(--sig-line);
  background: var(--sig-soft);
}

.seg-tag.src-evidence {
  color: var(--amber);
  border-color: rgba(245, 181, 71, 0.3);
}

.seg-note {
  margin-top: 8px;
  font-size: 11px;
  color: var(--ink-4);
}

/* 事实守恒 */
.fc-block {
  border: 1px solid var(--line);
  border-radius: 3px;
  margin-bottom: 12px;
  overflow: hidden;
}

.fc-block.is-pass {
  border-color: var(--sig-line);
}

.fc-hd {
  display: flex;
  justify-content: space-between;
  font-size: 10px;
  letter-spacing: 0.1em;
  color: var(--ink-4);
  padding: 6px 10px;
  border-bottom: 1px solid var(--line);
  background: rgba(255, 255, 255, 0.015);
}

.fc-hd b {
  color: var(--ink-3);
}

.fc-block.is-pass .fc-hd b {
  color: var(--sig);
}

.fc-body {
  padding: 8px 10px;
  font-size: 11px;
}

/* 缺失层 */
.miss-block {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  border: 1px dashed rgba(245, 181, 71, 0.35);
  border-radius: 3px;
  padding: 9px 11px;
  margin-bottom: 12px;
}

.miss-hd {
  font-size: 10px;
  letter-spacing: 0.1em;
  color: var(--amber);
}

.miss-tag {
  font-size: 10.5px;
  color: var(--amber);
  background: rgba(245, 181, 71, 0.08);
  border: 1px solid rgba(245, 181, 71, 0.3);
  border-radius: 2px;
  padding: 1px 6px;
}

.miss-note {
  font-size: 11px;
  color: var(--ink-4);
}

/* 拒绝路径 */
.reject-block {
  border: 1px solid rgba(229, 84, 75, 0.4);
  border-radius: 3px;
  padding: 14px;
  margin-bottom: 12px;
}

.rb-hd {
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.08em;
  color: var(--danger, #e5544b);
  margin-bottom: 6px;
}

.rb-tx {
  margin: 0 0 6px;
  font-size: 12.5px;
  line-height: 1.7;
  color: var(--ink-2, #b7c3cb);
}

/* 完成 */
.done-block {
  display: flex;
  gap: 16px;
  padding: 14px 4px 4px;
}

.done-glyph {
  font-size: 24px;
  font-weight: 700;
  color: var(--sig);
  flex: none;
}

.done-tx p {
  margin: 0 0 8px;
  font-size: 13px;
  line-height: 1.8;
  color: var(--ink-2, #b7c3cb);
}

.done-tx p.dim {
  font-size: 12px;
  color: var(--mut, #7d8c96);
}

.done-tx b {
  color: var(--sig);
}

/* ============ 操作区 ============ */
.q-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 14px;
}

.ghost-btn {
  color: var(--mut, #7d8c96);
}

.ghost-btn:hover {
  color: var(--sig);
}

.sig-btn {
  --el-button-bg-color: var(--sig);
  --el-button-border-color: var(--sig);
  --el-button-hover-bg-color: var(--sig);
  --el-button-hover-border-color: var(--sig);
  --el-button-active-bg-color: var(--sig);
  --el-button-active-border-color: var(--sig);
  font-weight: 600;
}

.err-line {
  margin-top: 10px;
  font-size: 11px;
  color: var(--danger, #e5544b);
}

.is-bad {
  color: var(--danger, #e5544b);
}

.is-ok {
  color: var(--sig);
}
</style>
