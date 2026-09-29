<template>
  <div class="draft-page">
    <!-- ============ 头部：草稿状态 ============ -->
    <section class="panel" style="--i: 1">
      <div class="mod-head">
        <span class="mod-no">[ D.00 ]</span>
        <span class="mod-title">草稿工作台</span>
        <span class="mod-en">draft_workspace</span>
        <router-link :to="`/resumes/${route.params.id}/structure`" class="hd-link mono is-first">
          ← 解析结果
        </router-link>
        <router-link :to="`/resumes/${route.params.id}/diagnose`" class="hd-link mono">
          诊断报告 →
        </router-link>
      </div>

      <div class="draft-hd">
        <div class="kv-grid">
          <div class="kv">
            <div class="kv-k mono">resume · 简历</div>
            <div class="kv-v mono">{{ shortId }}</div>
          </div>
          <div class="kv">
            <div class="kv-k mono">draft · 草稿</div>
            <div class="kv-v mono" :class="{ blank: !draft }">
              {{ draft ? draft.draft_id.slice(0, 8) : "未创建" }}
            </div>
          </div>
          <div class="kv">
            <div class="kv-k mono">version · 版本</div>
            <div class="kv-v mono" :class="{ blank: !draft }">
              {{ draft ? `v${draft.current_version}` : "-" }}
            </div>
          </div>
          <div class="kv">
            <div class="kv-k mono">status · 状态</div>
            <div class="kv-v mono">
              <span v-if="draft" class="chip" :class="draft.status === 'exported' ? 'sig' : ''">
                {{ draft.status }}
              </span>
              <span v-else class="blank">-</span>
            </div>
          </div>
          <div class="kv">
            <div class="kv-k mono">rewritten · 已改写字段</div>
            <div class="kv-v mono" :class="{ blank: !draft }">
              {{ draft ? draft.rewritten_count : "-" }}
            </div>
          </div>
          <div class="kv">
            <div class="kv-k mono">fields · 字段总数</div>
            <div class="kv-v mono" :class="{ blank: !draft }">
              {{ draft ? draft.field_count : "-" }}
            </div>
          </div>
        </div>
      </div>
    </section>

    <!-- ============ 主体：左问题清单 / 右草稿内容 ============ -->
    <div class="draft-cols">
      <!-- ---------- 左列 ---------- -->
      <div class="col-left">
        <!-- 问题清单：改写的入口 -->
        <section class="panel" style="--i: 2">
          <div class="mod-head">
            <span class="mod-no">[ O.01 ]</span>
            <span class="mod-title">问题清单</span>
            <span class="mod-en">issue_queue</span>
            <span class="mod-count">{{ issues.length }} issues</span>
          </div>

          <div v-if="!hasReport" class="empty-tip mono">
            // 尚未运行诊断 —— 先去<a class="ilink" :href="`/resumes/${route.params.id}/diagnose`">诊断报告</a>页生成问题清单
          </div>
          <div v-else-if="!issues.length" class="empty-tip mono">
            // 没有问题项 —— 该简历在当前规则下全部通过
          </div>
          <div v-else class="issue-list">
            <div v-for="it in issues" :key="it.issue_id" class="issue-row" :class="{ 'is-active': activeRewrite?.issue_id === it.issue_id }">
              <div class="ir-top">
                <span class="sev" :class="`sev-${it.severity}`">{{ it.severity_label || it.severity }}</span>
                <span class="ir-cat mono">{{ it.category }}</span>
                <span class="ir-spacer"></span>
                <span v-if="rewriteOf(it.issue_id)" class="mini-tag mono">已改写</span>
                <button class="mini-btn mono" :disabled="busy" @click="generate(it)">
                  改写 →
                </button>
              </div>
              <div class="ir-problem">{{ it.problem }}</div>
              <div class="ir-loc mono">
                <span class="ir-field">{{ (it.location || {}).field || "-" }}</span>
                <span class="ir-snippet">{{ (it.location || {}).snippet || "" }}</span>
              </div>
            </div>
          </div>
        </section>

        <!-- 改写详情：before / after / 改动点 / 事实比对 -->
        <section v-if="activeRewrite" class="panel" style="--i: 3">
          <div class="mod-head">
            <span class="mod-no">[ O.02 ]</span>
            <span class="mod-title">改写详情</span>
            <span class="mod-en">rewrite_detail</span>
            <span class="risk-badge" :class="riskClass">
              {{ activeRewrite.risk_level || "no_rewrite" }}
            </span>
          </div>

          <div class="rw-meta">
            <span class="mono">target · {{ activeRewrite.target_field }}</span>
            <span class="mono">status · {{ activeRewrite.status }}</span>
            <span class="mono">model · {{ activeRewrite.model_version }}</span>
            <span class="mono">reproducible · {{ activeRewrite.reproducible }}</span>
          </div>

          <div v-if="activeRewrite.reason" class="rw-reason mono">{{ activeRewrite.reason }}</div>

          <!-- 降级 / 拒绝提示 -->
          <div v-if="activeRewrite.status !== 'generated'" class="rw-blocked">
            <b>{{ activeRewrite.status === "rejected" ? "已拒绝输出" : "仅建议，不可应用" }}</b>
            <p>
              {{
                activeRewrite.status === "rejected"
                  ? "改写后的文本与原文事实不一致（新增或改变了事实），按设计文档「宁可改写失败也不返回可能编造的内容」拒绝输出。"
                  : "该问题只能由你补充真实信息后手动修改，系统不做代写。"
              }}
            </p>
          </div>

          <template v-else>
            <div class="ba-grid">
              <div class="ba-col">
                <div class="ba-hd mono">before · 原文</div>
                <div class="ba-body">{{ activeRewrite.before }}</div>
              </div>
              <div class="ba-col is-after">
                <div class="ba-hd mono">after · 改写后</div>
                <div class="ba-body">{{ activeRewrite.after }}</div>
              </div>
            </div>

            <!-- 改动点：按 change_class 着色 -->
            <div class="cp-block">
              <div class="cp-hd mono">
                change_points · 改动点
                <span class="cp-count">{{ activeRewrite.change_points.length }}</span>
              </div>
              <div v-if="!activeRewrite.change_points.length" class="cp-empty mono">// 无改动点</div>
              <div v-else class="cp-list">
                <div v-for="(cp, i) in activeRewrite.change_points" :key="i" class="cp-row" :class="`cp-${cp.change_class}`">
                  <span class="cp-class mono">{{ cp.change_class_label }}</span>
                  <span class="cp-text mono">
                    <span class="cp-before">「{{ cp.before_text }}」</span>
                    <span class="cp-arrow">→</span>
                    <span class="cp-after">「{{ cp.after_text }}」</span>
                  </span>
                </div>
              </div>
            </div>

            <!-- 事实比对：凭什么说没编造（仅改写产出时才有比对） -->
            <div class="fc-block" :class="factCheckState.cls">
              <div class="fc-hd mono">
                fact_check · 事实守恒
                <b>{{ factCheckState.label }}</b>
              </div>
              <div v-if="hasFactCheck" class="fc-body mono">
                <span>preserved · {{ factCheck.preserved?.length || 0 }}</span>
                <span>violated · {{ factCheck.violated?.length || 0 }}</span>
                <span>added · {{ factCheck.added?.length || 0 }}</span>
              </div>
              <div v-else class="fc-body mono dim">// 未产出改写文本，无事实比对</div>
              <div v-if="hasFactCheck && !factCheck.passed" class="fc-detail">
                <div v-for="(f, i) in (factCheck.violated || [])" :key="`v${i}`" class="mono">
                  被改变 {{ f.kind }}: {{ f.value }}
                </div>
                <div v-for="(f, i) in (factCheck.added || [])" :key="`a${i}`" class="mono">
                  新增 {{ f.kind }}: {{ f.value }}
                </div>
              </div>
            </div>

            <!-- 风险判定依据 -->
            <div v-if="activeRewrite.risk_reasons?.length" class="rr-block">
              <div class="rr-hd mono">risk_reasons · 分级依据</div>
              <ul class="rr-list">
                <li v-for="(r, i) in activeRewrite.risk_reasons" :key="i" class="mono">{{ r }}</li>
              </ul>
            </div>

            <div class="rw-actions">
              <el-button
                v-if="activeRewrite.risk_level === 'auto_safe'"
                type="primary"
                :loading="busy"
                @click="apply(activeRewrite)"
              >
                应用到草稿
              </el-button>
              <span v-else-if="activeRewrite.status === 'generated'" class="rw-warn mono">
                needs_review · 逐条人工确认后才能应用（批量应用仅接受 auto_safe）
              </span>
            </div>
          </template>
        </section>

        <!-- 改写记录：批量应用安全修正的选区 -->
        <section v-if="rewrites.length" class="panel" style="--i: 4">
          <div class="mod-head">
            <span class="mod-no">[ O.06 ]</span>
            <span class="mod-title">改写记录</span>
            <span class="mod-en">rewrite_log</span>
            <button
              class="mini-btn solid mono"
              :disabled="busy || !safeUnapplied.length"
              @click="batchApply"
            >
              批量应用安全修正 ({{ safeUnapplied.length }})
            </button>
          </div>
          <div class="rw-list">
            <div v-for="r in rewrites" :key="r.rewrite_id" class="rw-row">
              <span class="rw-idx mono">{{ r.rewrite_id.slice(0, 6) }}</span>
              <span class="rw-field mono">{{ r.target_field }}</span>
              <span class="risk-badge sm" :class="r.risk_level">{{ r.risk_level }}</span>
              <span class="rw-flag mono" :class="r.applied ? 'is-applied' : ''">
                {{ r.applied ? "applied" : "pending" }}
              </span>
              <span class="rw-spacer"></span>
              <button class="mini-btn mono" @click="openRewrite(r.rewrite_id)">查看</button>
            </div>
          </div>
        </section>
      </div>

      <!-- ---------- 右列 ---------- -->
      <div class="col-right">
        <!-- 草稿字段 -->
        <section class="panel" style="--i: 2">
          <div class="mod-head">
            <span class="mod-no">[ O.04 ]</span>
            <span class="mod-title">草稿内容</span>
            <span class="mod-en">draft_fields</span>
          </div>

          <div v-if="!draft" class="empty-tip mono">
            // 还没有草稿 —— 在左侧选一条问题点「改写」并应用后，草稿会自动从解析结果初始化
          </div>
          <div v-else class="field-list">
            <div
              v-for="(f, i) in draft.fields"
              :key="f.field_name"
              class="field-row"
              :class="{ 'is-unrecognized': f.source === 'unrecognized' }"
            >
              <div class="fl-top">
                <span class="fl-no mono">{{ String(i + 1).padStart(2, "0") }}</span>
                <span class="fl-name mono">{{ f.field_name }}</span>
                <span class="fl-src mono" :class="`src-${f.source}`">{{ f.source }}</span>
                <span class="fl-spacer"></span>
                <button class="mini-btn mono" @click="startEdit(i)">编辑</button>
              </div>
              <div v-if="editingIndex !== i" class="fl-value" :class="{ blank: !f.value }">
                {{ f.value || "- 空 -" }}
              </div>
              <div v-else class="fl-editor">
                <el-input v-model="editValue" type="textarea" :autosize="{ minRows: 2, maxRows: 6 }" />
                <div class="fl-editor-actions">
                  <span class="mono warn">手工编辑同样会产生一个新版本（NFR-10）</span>
                  <span class="fl-spacer"></span>
                  <el-button size="small" @click="editingIndex = -1">取消</el-button>
                  <el-button size="small" type="primary" :loading="busy" @click="saveEdit(i)">
                    保存
                  </el-button>
                </div>
              </div>
              <div v-if="f.source === 'unrecognized' && editingIndex !== i" class="fl-hint">
                该段内容无法归入任何字段，机器读取时会丢失——建议改写到上方对应字段，或确认后删除。
              </div>
            </div>
          </div>
        </section>

        <!-- 版本历史 -->
        <section v-if="draft" class="panel" style="--i: 3">
          <div class="mod-head">
            <span class="mod-no">[ O.03 ]</span>
            <span class="mod-title">版本历史</span>
            <span class="mod-en">revisions · 全量快照</span>
            <span class="mod-count">current v{{ draft.current_version }}</span>
          </div>
          <div v-if="!revisions.length" class="empty-tip mono">// 暂无版本记录</div>
          <div v-else class="rev-list">
            <div v-for="r in revisions" :key="r.revision_no" class="rev-row">
              <span class="rev-no mono">v{{ String(r.revision_no).padStart(2, "0") }}</span>
              <span class="rev-op mono" :class="`op-${r.operation}`">{{ r.operation }}</span>
              <span class="rev-fields mono">{{ r.field_count }} fields</span>
              <span class="rev-time mono">{{ fmtTime(r.created_at) }}</span>
              <span class="rev-spacer"></span>
              <button
                class="mini-btn mono"
                :disabled="busy || r.revision_no === draft.current_version"
                @click="doRollback(r.revision_no)"
              >
                回滚
              </button>
            </div>
          </div>
        </section>

        <!-- 导出与复检 -->
        <section v-if="draft" class="panel" style="--i: 4">
          <div class="mod-head">
            <span class="mod-no">[ O.05 ]</span>
            <span class="mod-title">导出与复检</span>
            <span class="mod-en">export + recheck</span>
            <button class="mini-btn solid mono" :disabled="busy" @click="doExport">
              导出并复检 →
            </button>
          </div>
          <div v-if="!exportResult" class="empty-tip mono">
            // 导出会写出 txt + docx，并自动对草稿内容做一次复检
          </div>
          <div v-else class="export-block">
            <div class="kv-grid">
              <div class="kv">
                <div class="kv-k mono">txt · 纯文本</div>
                <div class="kv-v mono">{{ exportResult.files.txt }}</div>
              </div>
              <div class="kv">
                <div class="kv-k mono">docx · Word</div>
                <div class="kv-v mono">{{ exportResult.files.docx }}</div>
              </div>
            </div>
            <div class="recheck-row">
              <span class="mono">recheck · 复检健康分</span>
              <b class="mono" :class="scoreClass(exportResult.recheck.total_score)">
                {{ exportResult.recheck.total_score }}
              </b>
              <span class="mono dim">issues {{ exportResult.recheck.issue_count }}</span>
            </div>
          </div>
        </section>

        <!-- 三类差异对比 -->
        <section v-if="draft" class="panel" style="--i: 5">
          <div class="mod-head">
            <span class="mod-no">[ O.09 ]</span>
            <span class="mod-title">优化前后对比</span>
            <span class="mod-en">comparison</span>
            <button class="mini-btn solid mono" :disabled="busy" @click="loadComparison">
              生成对比 →
            </button>
          </div>
          <div v-if="!comparison" class="empty-tip mono">
            // 对比需要先有解析基准；解析规则版本不一致时会拒绝并提示不可比
          </div>
          <template v-else>
            <div class="score-diff">
              <div class="sd-cell">
                <div class="sd-k mono">before</div>
                <div class="sd-v mono">{{ comparison.score_diff.before }}</div>
              </div>
              <div class="sd-arrow mono">→</div>
              <div class="sd-cell is-after">
                <div class="sd-k mono">after</div>
                <div class="sd-v mono">{{ comparison.score_diff.after }}</div>
              </div>
              <div class="sd-cell is-delta">
                <div class="sd-k mono">delta</div>
                <div class="sd-v mono" :class="comparison.score_diff.delta >= 0 ? 'up' : 'down'">
                  {{ comparison.score_diff.delta >= 0 ? "+" : "" }}{{ comparison.score_diff.delta }}
                </div>
              </div>
            </div>

            <div class="dim-diff">
              <div v-for="(d, k) in comparison.score_diff.dimensions" :key="k" class="dd-row">
                <span class="dd-name mono">{{ d.label }}</span>
                <span class="dd-bar"><i :style="{ width: Math.max(0, Math.min(100, d.after)) + '%' }"></i></span>
                <span class="dd-num mono">{{ d.before }} → {{ d.after }}</span>
                <span class="dd-delta mono" :class="d.delta >= 0 ? 'up' : 'down'">
                  {{ d.delta >= 0 ? "+" : "" }}{{ d.delta }}
                </span>
              </div>
            </div>

            <div class="cmp-sub">
              <div class="cs-hd mono">parse_diff · 机器读取改善</div>
              <div class="cs-body">
                <span class="mono">
                  救回字段：<b class="sig-t">{{ comparison.parse_diff.recovered.length }}</b>
                  {{ comparison.parse_diff.recovered.join("、") || "无" }}
                </span>
                <span class="mono">
                  问题数：{{ comparison.parse_diff.issue_count.before }} → {{ comparison.parse_diff.issue_count.after }}
                </span>
              </div>
            </div>

            <div class="cmp-sub">
              <div class="cs-hd mono">content_diff · 内容改动（来自版本记录，可追溯）</div>
              <div v-if="!comparison.content_diff.length" class="empty-tip mono">// 无内容改动</div>
              <div v-else class="cd-list">
                <div v-for="c in comparison.content_diff" :key="c.revision_no" class="cd-row">
                  <span class="cd-no mono">v{{ c.revision_no }}</span>
                  <span class="cd-op mono">{{ c.operation }}</span>
                  <span class="cd-field mono">{{ c.field_name }}</span>
                </div>
              </div>
            </div>
          </template>
        </section>

        <!-- O.08 定制版本：按岗位匹配结果重排，只调顺序不新增事实 -->
        <section v-if="draft" class="panel" style="--i: 6">
          <div class="mod-head">
            <span class="mod-no">[ O.08 ]</span>
            <span class="mod-title">定制版本</span>
            <span class="mod-en">tailor · 面向目标岗位</span>
            <button class="mini-btn solid mono" :disabled="busy || !draft.jd_id" @click="runTailor">
              生成定制版本 →
            </button>
          </div>
          <div v-if="!draft.jd_id" class="empty-tip mono">
            // 需要目标岗位：请先到<a
              class="ilink"
              :href="`/resumes/${route.params.id}/diagnose`"
              >诊断报告</a
            >页提交 JD 并完成诊断
          </div>
          <div v-else-if="!tailorResult" class="empty-tip mono">
            // 将按岗位匹配结果重排经历与技能（只调顺序，不改内容、不新增事实）
          </div>
          <template v-else>
            <div class="tailor-summary">
              <span class="mono">岗位 <b>{{ tailorResult.jd_title }}</b></span>
              <span class="mono">要求 {{ tailorResult.requirement_count }} 项 · 缺口 {{ tailorResult.gap_count }} 项</span>
              <span class="mono">当前版本 <b>v{{ tailorResult.current_version }}</b></span>
            </div>
            <div v-if="!tailorResult.changed" class="empty-tip mono">
              // 当前字段顺序已贴合该岗位，无需调整
            </div>
            <div v-else class="move-list">
              <div v-for="(m, i) in tailorResult.moves" :key="i" class="move-row" :class="'mv-' + m.action">
                <span class="mv-act mono">{{ m.action }}</span>
                <span class="mv-field mono">{{ m.field_name }}</span>
                <span class="mv-idx mono">{{ m.from_index }} → {{ m.to_index }}</span>
                <span class="mv-hits mono">hits {{ m.hits }}</span>
                <span class="mv-reason">{{ m.reason }}</span>
              </div>
            </div>
            <div v-if="tailorResult.changed" class="tailor-foot">
              只调整顺序，内容逐字不变；不满意可在版本历史回滚到定制前。
            </div>
          </template>
        </section>

        <!-- 模型接入：用户自带模型。配置仅存浏览器，服务端不落库 -->
        <section class="panel" style="--i: 7">
          <div class="mod-head">
            <span class="mod-no">[ AI ]</span>
            <span class="mod-title">模型接入</span>
            <span class="mod-en">model · 用户自带</span>
            <span class="engine-flag mono" :class="aiReady ? 'is-on' : 'is-off'">
              <i class="led" />{{ aiReady ? "AI 已启用" : "规则引擎" }}
            </span>
          </div>

          <div class="ms-consent">
            <b>填写后会发生什么：</b>点「改写」时，<b>该字段的简历原文</b>会发送到你填写的接口地址；
            API Key <b>只保存在你自己的浏览器里</b>，服务端收到后仅用于当次请求，不写入数据库、不记入日志。
            不填写则始终使用内置规则引擎（只做标点/错别字/日期等确定性修正，不代写内容）。
          </div>

          <div class="ms-grid">
            <label class="ms-field">
              <span class="ms-label mono">接口地址 base_url</span>
              <el-input
                v-model="aiForm.base_url"
                placeholder="https://api.deepseek.com（兼容 OpenAI 即可）"
                size="small"
                :disabled="busy"
              />
            </label>
            <label class="ms-field">
              <span class="ms-label mono">模型名称 model</span>
              <el-input
                v-model="aiForm.model"
                placeholder="deepseek-chat"
                size="small"
                :disabled="busy"
              />
            </label>
            <label class="ms-field ms-wide">
              <span class="ms-label mono">API Key</span>
              <el-input
                v-model="aiForm.api_key"
                type="password"
                show-password
                placeholder="sk-..."
                size="small"
                :disabled="busy"
              />
            </label>
          </div>

          <div class="ms-actions">
            <el-checkbox v-model="aiForm.remember" :disabled="busy">在此浏览器记住配置</el-checkbox>
            <span class="ms-spacer" />
            <button class="mini-btn mono" :disabled="busy || !aiReady" @click="testAi">
              测试连接
            </button>
            <button class="mini-btn solid mono" :disabled="busy || !aiReady" @click="saveAi">
              保存并启用
            </button>
            <button v-if="aiSaved" class="mini-btn mono" :disabled="busy" @click="clearAi">
              清除
            </button>
          </div>

          <div v-if="aiTesting" class="ms-result mono is-pending">// 正在连接接口…</div>
          <div v-else-if="aiTest" class="ms-result mono" :class="aiTest.ok ? 'is-ok' : 'is-err'">
            {{ aiTest.ok ? "[ ok ]" : "[ err ]" }} {{ aiTest.msg }}
          </div>
          <div v-else-if="aiSaved" class="ms-result mono is-saved">
            // 已启用：后续点「改写」将改用你的模型。模型产出的改写需人工确认后才能应用。
          </div>
        </section>
      </div>
    </div>
  </div>
</template>

<script setup>
// 草稿工作台（V1.1 模块四）：问题项 → 改写 → 应用到草稿 → 版本管理 → 导出复检 → 三类差异对比。
// 关键约束：风险分级判定只在服务端做，前端传入 needs_review 的改写一律被服务端拒绝（6003）。
import { computed, onMounted, ref } from "vue";
import { useRoute } from "vue-router";
import { ElMessage, ElMessageBox } from "element-plus";
import { diagnosisApi, optimizeApi } from "../api/client";

const route = useRoute();
const busy = ref(false);

const report = ref(null);
const draft = ref(null);
const rewrites = ref([]);
const revisions = ref([]);
const activeRewrite = ref(null);
const exportResult = ref(null);
const comparison = ref(null);
const tailorResult = ref(null);

// ---- 用户自带模型（配置仅存浏览器，服务端不落库）----
const MODEL_KEY = "ro:model-settings";
const aiForm = ref({ base_url: "", api_key: "", model: "", remember: true });
const aiSaved = ref(false);
const aiTesting = ref(false);
const aiTest = ref(null);

const editingIndex = ref(-1);
const editValue = ref("");

const shortId = computed(() => route.params.id.slice(0, 8));
const hasReport = computed(() => !!report.value);
const issues = computed(() => report.value?.issues || []);

const factCheck = computed(() => activeRewrite.value?.fact_check || {});
// 只有真正产出改写文本时才有事实比对（suggestion_only / rejected 时后端返回 {}）
const hasFactCheck = computed(() => Object.keys(factCheck.value).length > 0);
const factCheckState = computed(() => {
  if (!hasFactCheck.value) return { cls: "is-none", label: "N/A" };
  return factCheck.value.passed
    ? { cls: "is-pass", label: "PASSED" }
    : { cls: "is-fail", label: "FAILED" };
});
// 风险等级徽标：未产出改写时没有分级
const riskClass = computed(() => activeRewrite.value?.risk_level || "none");

// 可批量应用：服务端只接受 auto_safe 且尚未应用过的改写
const safeUnapplied = computed(
  () => rewrites.value.filter((r) => r.risk_level === "auto_safe" && !r.applied && r.status === "generated")
);

// 三项都填了才认为可用；缺任何一项后端也无法调用
const aiReady = computed(() => {
  const f = aiForm.value;
  return !!(f.base_url.trim() && f.api_key.trim() && f.model.trim());
});

function scoreClass(s) {
  if (s >= 85) return "up";
  if (s >= 60) return "";
  return "down";
}

function fmtTime(iso) {
  if (!iso) return "-";
  const d = new Date(iso);
  const p = (n) => String(n).padStart(2, "0");
  return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

function rewriteOf(issueId) {
  return rewrites.value.find((r) => r.issue_id === issueId);
}

async function load() {
  try {
    localStorage.setItem("ro:last-resume-id", route.params.id);
  } catch {
    /* 隐私模式下不可用，忽略 */
  }
  // 诊断报告可能还没跑过：失败时不影响草稿工作台其余部分
  try {
    const r = await diagnosisApi.getReport(route.params.id);
    report.value = r.data;
  } catch {
    report.value = null;
  }
  await Promise.all([loadDraft(), loadRewrites()]);
}

async function loadDraft() {
  try {
    const body = await optimizeApi.getDraftByResume(route.params.id);
    draft.value = body.data?.draft_id ? body.data : null;
    if (draft.value) await loadRevisions();
    else revisions.value = [];
  } catch (e) {
    ElMessage.error(e.message || "草稿加载失败");
  }
}

async function loadRewrites() {
  try {
    const body = await optimizeApi.listRewrites(route.params.id);
    rewrites.value = body.data?.rewrites || [];
  } catch {
    rewrites.value = [];
  }
}

async function loadRevisions() {
  if (!draft.value) return;
  try {
    const body = await optimizeApi.listRevisions(draft.value.draft_id);
    revisions.value = body.data?.revisions || [];
  } catch {
    revisions.value = [];
  }
}

// O-01：基于问题项发起改写
async function generate(issue) {
  busy.value = true;
  try {
    const payload = {
      resume_id: route.params.id,
      issue_id: issue.issue_id,
    };
    // 仅在「保存并启用」后才带上模型配置：服务端据此在本次请求中改用 AI 引擎，
    // 否则用内置规则引擎。Key 只出现在这一次请求里，不落库、不记日志。
    if (aiSaved.value && aiReady.value) {
      payload.model_settings = {
        base_url: aiForm.value.base_url.trim(),
        api_key: aiForm.value.api_key.trim(),
        model: aiForm.value.model.trim(),
      };
    }
    const body = await optimizeApi.generateRewrite(payload);
    activeRewrite.value = body.data;
    await Promise.all([loadDraft(), loadRewrites()]);
    if (body.data.status === "generated") {
      // AI 产出的改写通常不是 auto_safe，必须逐条人工确认后才能应用
      const needReview = body.data.risk_level && body.data.risk_level !== "auto_safe";
      ElMessage.success(needReview ? "改写已生成，需人工确认后应用" : "改写已生成");
    } else if (body.data.status === "rejected") ElMessage.warning("改写被拒绝：事实不守恒");
    else ElMessage.info("该问题仅给建议，不做代写");
  } catch (e) {
    ElMessage.error(e.message || "改写失败");
  } finally {
    busy.value = false;
  }
}

// ---- 用户自带模型：读取 / 保存 / 清除 / 连接自检 ----
function loadAiSettings() {
  try {
    const raw = localStorage.getItem(MODEL_KEY);
    if (!raw) return;
    const saved = JSON.parse(raw);
    aiForm.value = {
      base_url: saved.base_url || "",
      api_key: saved.api_key || "",
      model: saved.model || "",
      remember: true,
    };
    aiSaved.value = aiReady.value;
  } catch {
    /* 隐私模式或本地数据损坏：忽略，用户可重新填写 */
  }
}

async function testAi() {
  if (!aiReady.value) {
    ElMessage.warning("请先填齐接口地址、API Key 与模型名称");
    return;
  }
  aiTesting.value = true;
  aiTest.value = null;
  try {
    const body = await optimizeApi.testModel({
      base_url: aiForm.value.base_url.trim(),
      api_key: aiForm.value.api_key.trim(),
      model: aiForm.value.model.trim(),
    });
    aiTest.value = { ok: true, msg: body.data?.detail || body.message };
  } catch (e) {
    // 后端把连通性/鉴权问题也归为 6008，但保留了具体原因，直接展示给用户排查
    aiTest.value = { ok: false, msg: e.message || "连接失败" };
  } finally {
    aiTesting.value = false;
  }
}

function saveAi() {
  if (!aiReady.value) {
    ElMessage.warning("请先填齐接口地址、API Key 与模型名称");
    return;
  }
  aiSaved.value = true;
  aiTest.value = null;
  if (aiForm.value.remember) {
    try {
      localStorage.setItem(
        MODEL_KEY,
        JSON.stringify({
          base_url: aiForm.value.base_url.trim(),
          api_key: aiForm.value.api_key.trim(),
          model: aiForm.value.model.trim(),
        })
      );
    } catch {
      ElMessage.info("浏览器不允许本地保存，配置仅在本次会话有效");
    }
  } else {
    try {
      localStorage.removeItem(MODEL_KEY);
    } catch {
      /* 忽略 */
    }
  }
  ElMessage.success("已启用你的模型；改写时将把该字段原文发送到该接口");
}

function clearAi() {
  aiSaved.value = false;
  aiTest.value = null;
  aiForm.value = { base_url: "", api_key: "", model: "", remember: true };
  try {
    localStorage.removeItem(MODEL_KEY);
  } catch {
    /* 忽略 */
  }
  ElMessage.success("已清除，后续改写使用内置规则引擎");
}

async function openRewrite(rewriteId) {
  try {
    const body = await optimizeApi.getRewrite(rewriteId);
    activeRewrite.value = body.data;
  } catch (e) {
    ElMessage.error(e.message || "改写记录不存在");
  }
}

// O-03：应用单条改写
async function apply(rw) {
  busy.value = true;
  try {
    await optimizeApi.applyRewrite(rw.rewrite_id);
    ElMessage.success("已应用到草稿");
    exportResult.value = null;
    comparison.value = null;
    await Promise.all([loadDraft(), loadRewrites()]);
  } catch (e) {
    ElMessage.error(e.message || "应用失败");
  } finally {
    busy.value = false;
  }
}

// O-06/O-07：批量应用（服务端强校验 auto_safe，needs_review 一律 6003）
async function batchApply() {
  if (!draft.value || !safeUnapplied.value.length) return;
  busy.value = true;
  try {
    const body = await optimizeApi.batchApply(draft.value.draft_id, {
      rewrite_ids: safeUnapplied.value.map((r) => r.rewrite_id),
    });
    ElMessage.success(`已批量应用 ${body.data.applied_count} 条确定性修正`);
    exportResult.value = null;
    comparison.value = null;
    await Promise.all([loadDraft(), loadRewrites()]);
  } catch (e) {
    ElMessage.error(e.message || "批量应用失败");
  } finally {
    busy.value = false;
  }
}

// O-04：手工编辑字段（同样产生新版本）
function startEdit(i) {
  editingIndex.value = i;
  editValue.value = draft.value.fields[i].value || "";
}

async function saveEdit(i) {
  const field = draft.value.fields[i];
  if (editValue.value === (field.value || "")) {
    editingIndex.value = -1;
    return;
  }
  busy.value = true;
  try {
    await optimizeApi.editField(draft.value.draft_id, {
      field_name: field.field_name,
      value: editValue.value,
    });
    ElMessage.success("字段已更新，新版本已生成");
    editingIndex.value = -1;
    exportResult.value = null;
    comparison.value = null;
    await loadDraft();
  } catch (e) {
    ElMessage.error(e.message || "保存失败");
  } finally {
    busy.value = false;
  }
}

// O-03/NFR-10：回滚到指定版本
async function doRollback(no) {
  try {
    await ElMessageBox.confirm(`将回滚到版本 v${no}，回滚本身也会生成一个新版本。确认继续？`, "回滚确认", {
      confirmButtonText: "回滚",
      cancelButtonText: "取消",
      type: "warning",
    });
  } catch {
    return;
  }
  busy.value = true;
  try {
    await optimizeApi.rollback(draft.value.draft_id, { revision_no: no });
    ElMessage.success(`已回滚到版本 ${no}`);
    exportResult.value = null;
    comparison.value = null;
    await loadDraft();
  } catch (e) {
    ElMessage.error(e.message || "回滚失败");
  } finally {
    busy.value = false;
  }
}

// O-05：导出并自动复检
async function doExport() {
  busy.value = true;
  try {
    const body = await optimizeApi.exportDraft(draft.value.draft_id);
    exportResult.value = body.data;
    ElMessage.success("已导出并完成复检");
  } catch (e) {
    ElMessage.error(e.message || "导出失败");
  } finally {
    busy.value = false;
  }
}

// O-09：三类差异对比
async function loadComparison() {
  busy.value = true;
  try {
    const body = await optimizeApi.comparison(draft.value.draft_id);
    comparison.value = body.data;
    ElMessage.success("对比已生成");
  } catch (e) {
    ElMessage.error(e.message || "对比失败");
  } finally {
    busy.value = false;
  }
}

// O-08：定制版本。只调顺序不新增事实；无移动时不产生新版本（changed=false）。
async function runTailor() {
  busy.value = true;
  try {
    const body = await optimizeApi.createTailor({
      resume_id: route.params.id,
      jd_id: draft.value.jd_id,
    });
    tailorResult.value = body.data;
    if (body.data.changed) {
      ElMessage.success(`定制版本已生成（v${body.data.current_version}）`);
      await loadDraft();
      await loadRevisions();
    } else {
      ElMessage.info("当前字段顺序已贴合该岗位，无需调整");
    }
  } catch (e) {
    ElMessage.error(e.message || "定制失败");
  } finally {
    busy.value = false;
  }
}

onMounted(() => {
  loadAiSettings();
  load();
});
</script>

<style scoped>
/* ============ 布局 ============ */
.draft-cols {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 14px;
  align-items: start;
}

@media (max-width: 1180px) {
  .draft-cols {
    grid-template-columns: minmax(0, 1fr);
  }
}

.col-left,
.col-right {
  display: flex;
  flex-direction: column;
  gap: 14px;
  min-width: 0;
}

/* ============ 头部链接 ============ */
.hd-link {
  color: var(--mut, #7d8c96);
  text-decoration: none;
  font-size: 12px;
  margin-left: 14px;
  transition: color 0.15s;
}

.hd-link.is-first {
  margin-left: auto;
}

.hd-link:hover {
  color: var(--sig);
}

/* ============ 问题清单 ============ */
.issue-list {
  display: flex;
  flex-direction: column;
}

.issue-row {
  padding: 11px 14px;
  border-bottom: 1px solid var(--line);
  transition: background 0.15s;
}

.issue-row:last-child {
  border-bottom: none;
}

.issue-row:hover {
  background: rgba(255, 255, 255, 0.015);
}

.issue-row.is-active {
  background: var(--sig-soft);
  box-shadow: inset 2px 0 0 var(--sig);
}

.ir-top {
  display: flex;
  align-items: center;
  gap: 8px;
}

.sev {
  font-size: 11px;
  padding: 1px 7px;
  border-radius: 2px;
  font-weight: 600;
  letter-spacing: 0.04em;
}

.sev-critical {
  color: #e5544b;
  background: rgba(229, 84, 75, 0.12);
  border: 1px solid rgba(229, 84, 75, 0.35);
}

.sev-major {
  color: var(--amber);
  background: var(--amber-soft);
  border: 1px solid var(--amber-line);
}

.sev-minor,
.sev-info {
  color: var(--mut, #7d8c96);
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid var(--line-hi);
}

.ir-cat {
  font-size: 11px;
  color: var(--mut, #7d8c96);
}

.ir-spacer,
.fl-spacer,
.rw-spacer,
.rev-spacer {
  flex: 1;
}

.ir-problem {
  margin-top: 6px;
  font-size: 13px;
  line-height: 1.55;
  color: var(--ink);
}

.ir-loc {
  margin-top: 5px;
  font-size: 11px;
  color: var(--mut, #7d8c96);
  display: flex;
  gap: 8px;
  min-width: 0;
}

.ir-field {
  color: #6fc3d8;
  flex-shrink: 0;
}

.ir-snippet {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.mini-btn {
  border: 1px solid var(--line-hi);
  background: transparent;
  color: var(--ink);
  font-size: 11px;
  padding: 3px 9px;
  border-radius: 2px;
  cursor: pointer;
  transition: all 0.15s;
  white-space: nowrap;
}

.mini-btn:hover:not(:disabled) {
  border-color: var(--sig-line);
  color: var(--sig);
  background: var(--sig-soft);
}

.mini-btn:disabled {
  opacity: 0.35;
  cursor: not-allowed;
}

.mini-btn.solid {
  border-color: var(--sig-line);
  color: var(--sig);
  background: var(--sig-soft);
}

.mini-btn.solid:hover:not(:disabled) {
  background: rgba(79, 227, 165, 0.18);
}

.mini-tag {
  font-size: 10px;
  color: var(--sig);
  border: 1px dashed var(--sig-line);
  padding: 2px 6px;
  border-radius: 2px;
}

.ilink {
  color: var(--sig);
}

/* ============ 改写详情 ============ */
.rw-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 18px;
  padding: 9px 14px;
  border-bottom: 1px solid var(--line);
  font-size: 11px;
  color: var(--mut, #7d8c96);
}

.rw-reason {
  padding: 8px 14px;
  border-bottom: 1px solid var(--line);
  font-size: 11px;
  color: var(--amber);
  background: var(--amber-soft);
  line-height: 1.6;
}

.risk-badge {
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.08em;
  padding: 2px 8px;
  border-radius: 2px;
  text-transform: uppercase;
}

.risk-badge.auto_safe {
  color: var(--sig);
  background: var(--sig-soft);
  border: 1px solid var(--sig-line);
}

.risk-badge.needs_review {
  color: var(--amber);
  background: var(--amber-soft);
  border: 1px solid var(--amber-line);
}

.risk-badge.none {
  color: var(--mut, #7d8c96);
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid var(--line-hi);
}

.fc-block.is-none {
  border-color: var(--line-hi);
  border-style: dashed;
}

.fc-block.is-none .fc-hd b {
  color: var(--mut, #7d8c96);
}

.risk-badge.sm {
  font-size: 9px;
  padding: 1px 6px;
}

.rw-blocked {
  margin: 14px;
  padding: 13px 15px;
  border: 1px solid var(--amber-line);
  background: var(--amber-soft);
  border-radius: 3px;
}

.rw-blocked b {
  color: var(--amber);
  font-size: 13px;
}

.rw-blocked p {
  margin: 6px 0 0;
  font-size: 12px;
  line-height: 1.65;
  color: var(--ink);
}

.ba-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 1px;
  background: var(--line);
  border-bottom: 1px solid var(--line);
}

@media (max-width: 720px) {
  .ba-grid {
    grid-template-columns: 1fr;
  }
}

.ba-col {
  background: var(--panel);
  padding: 11px 14px 13px;
  min-width: 0;
}

.ba-col.is-after {
  background: rgba(79, 227, 165, 0.04);
}

.ba-hd {
  font-size: 10px;
  letter-spacing: 0.1em;
  color: var(--mut, #7d8c96);
  text-transform: uppercase;
  margin-bottom: 7px;
}

.ba-col.is-after .ba-hd {
  color: var(--sig);
}

.ba-body {
  font-size: 13px;
  line-height: 1.7;
  color: var(--ink);
  word-break: break-word;
}

/* 改动点 */
.cp-block {
  padding: 12px 14px;
  border-bottom: 1px solid var(--line);
}

.cp-hd {
  font-size: 10px;
  letter-spacing: 0.1em;
  color: var(--mut, #7d8c96);
  text-transform: uppercase;
  display: flex;
  align-items: center;
  gap: 8px;
}

.cp-count {
  color: var(--sig);
  border: 1px solid var(--sig-line);
  border-radius: 2px;
  padding: 0 5px;
}

.cp-empty {
  margin-top: 8px;
  font-size: 11px;
  color: var(--mut, #7d8c96);
}

.cp-list {
  margin-top: 9px;
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.cp-row {
  display: flex;
  align-items: baseline;
  gap: 9px;
  font-size: 11.5px;
  padding: 5px 8px;
  border-radius: 2px;
  border-left: 2px solid var(--line-hi);
  background: rgba(255, 255, 255, 0.015);
}

.cp-class {
  flex-shrink: 0;
  font-size: 10px;
  padding: 1px 5px;
  border-radius: 2px;
  background: rgba(255, 255, 255, 0.05);
  color: var(--mut, #7d8c96);
}

/* 安全类别（标点/错别字/格式）= 信号绿；措辞 = 琥珀；结构 = 红 */
.cp-row.cp-punctuation,
.cp-row.cp-typo,
.cp-row.cp-format {
  border-left-color: var(--sig);
}

.cp-row.cp-punctuation .cp-class,
.cp-row.cp-typo .cp-class,
.cp-row.cp-format .cp-class {
  color: var(--sig);
  background: var(--sig-soft);
}

.cp-row.cp-wording {
  border-left-color: var(--amber);
}

.cp-row.cp-wording .cp-class {
  color: var(--amber);
  background: var(--amber-soft);
}

.cp-row.cp-structure {
  border-left-color: #e5544b;
}

.cp-row.cp-structure .cp-class {
  color: #e5544b;
  background: rgba(229, 84, 75, 0.1);
}

.cp-text {
  min-width: 0;
  word-break: break-word;
  line-height: 1.6;
}

.cp-before {
  color: var(--mut, #7d8c96);
  text-decoration: line-through;
  text-decoration-color: rgba(229, 84, 75, 0.5);
}

.cp-arrow {
  color: var(--sig);
  margin: 0 5px;
}

.cp-after {
  color: var(--ink);
}

/* 事实守恒 */
.fc-block {
  margin: 12px 14px;
  border: 1px solid var(--line-hi);
  border-radius: 3px;
  overflow: hidden;
}

.fc-block.is-pass {
  border-color: var(--sig-line);
}

.fc-block.is-fail {
  border-color: rgba(229, 84, 75, 0.4);
}

.fc-hd {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 7px 11px;
  font-size: 10px;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  background: rgba(255, 255, 255, 0.03);
  color: var(--mut, #7d8c96);
}

.fc-block.is-pass .fc-hd b {
  color: var(--sig);
}

.fc-block.is-fail .fc-hd b {
  color: #e5544b;
}

.fc-body {
  display: flex;
  gap: 18px;
  padding: 8px 11px;
  font-size: 11px;
  color: var(--ink);
}

.fc-detail {
  padding: 0 11px 9px;
  font-size: 11px;
  color: #e5544b;
  line-height: 1.7;
}

/* 分级依据 */
.rr-block {
  padding: 0 14px 12px;
}

.rr-hd {
  font-size: 10px;
  letter-spacing: 0.1em;
  color: var(--mut, #7d8c96);
  text-transform: uppercase;
}

.rr-list {
  margin: 7px 0 0;
  padding-left: 16px;
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.rr-list li {
  font-size: 11px;
  color: var(--ink);
  line-height: 1.6;
}

.rw-actions {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 14px;
  border-top: 1px solid var(--line);
}

.rw-warn {
  font-size: 11px;
  color: var(--amber);
  line-height: 1.5;
}

/* ============ 改写记录 ============ */
.rw-list {
  display: flex;
  flex-direction: column;
}

.rw-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 14px;
  border-bottom: 1px solid var(--line);
  font-size: 11px;
}

.rw-row:last-child {
  border-bottom: none;
}

.rw-idx {
  color: var(--mut, #7d8c96);
}

.rw-field {
  color: #6fc3d8;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.rw-flag {
  font-size: 10px;
  color: var(--amber);
}

.rw-flag.is-applied {
  color: var(--sig);
}

/* ============ 草稿字段 ============ */
.field-list {
  display: flex;
  flex-direction: column;
}

.field-row {
  padding: 10px 14px;
  border-bottom: 1px solid var(--line);
}

.field-row:last-child {
  border-bottom: none;
}

.fl-top {
  display: flex;
  align-items: center;
  gap: 9px;
}

.fl-no {
  font-size: 10px;
  color: var(--mut, #7d8c96);
}

.fl-name {
  font-size: 11.5px;
  color: #6fc3d8;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.fl-src {
  font-size: 9px;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  padding: 1px 5px;
  border-radius: 2px;
  border: 1px solid var(--line-hi);
  color: var(--mut, #7d8c96);
  flex-shrink: 0;
}

.fl-src.src-rewritten {
  color: var(--sig);
  border-color: var(--sig-line);
  background: var(--sig-soft);
}

.fl-src.src-manual {
  color: var(--amber);
  border-color: var(--amber-line);
  background: var(--amber-soft);
}

/* 未识别内容：机器读不了，必须人工处理——用虚边框 + 提示条区分于普通字段 */
.fl-src.src-unrecognized {
  color: #e5544b;
  border-color: rgba(229, 84, 75, 0.4);
  background: rgba(229, 84, 75, 0.08);
}

.field-row.is-unrecognized {
  background: rgba(229, 84, 75, 0.035);
  box-shadow: inset 2px 0 0 rgba(229, 84, 75, 0.5);
}

.fl-hint {
  margin-top: 6px;
  font-size: 11px;
  color: #e5544b;
  line-height: 1.5;
}

.fl-value {
  margin-top: 6px;
  font-size: 13px;
  line-height: 1.65;
  color: var(--ink);
  word-break: break-word;
  white-space: pre-wrap;
}

.fl-value.blank {
  color: var(--mut, #7d8c96);
  font-style: italic;
}

.fl-editor {
  margin-top: 8px;
}

.fl-editor-actions {
  margin-top: 8px;
  display: flex;
  align-items: center;
  gap: 8px;
}

.fl-editor-actions .mono {
  font-size: 10px;
  color: var(--amber);
}

/* ============ 版本历史 ============ */
.rev-list {
  display: flex;
  flex-direction: column;
}

.rev-row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 14px;
  border-bottom: 1px solid var(--line);
  font-size: 11px;
}

.rev-row:last-child {
  border-bottom: none;
}

.rev-no {
  color: var(--sig);
  font-weight: 700;
}

.rev-op {
  color: var(--amber);
}

.rev-op.op-apply,
.rev-op.op-batch_apply {
  color: var(--sig);
}

.rev-fields,
.rev-time {
  color: var(--mut, #7d8c96);
}

/* ============ 导出 ============ */
.export-block {
  padding-bottom: 6px;
}

.recheck-row {
  display: flex;
  align-items: baseline;
  gap: 12px;
  padding: 10px 14px 4px;
  font-size: 11px;
  color: var(--mut, #7d8c96);
}

.recheck-row b {
  font-size: 22px;
}

.recheck-row .up,
.sd-v.up,
.dd-delta.up {
  color: var(--sig);
}

.recheck-row .down,
.sd-v.down,
.dd-delta.down {
  color: #e5544b;
}

.recheck-row .dim {
  opacity: 0.7;
}

/* ============ 对比 ============ */
.score-diff {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 14px;
  border-bottom: 1px solid var(--line);
}

.sd-cell {
  text-align: center;
}

.sd-k {
  font-size: 10px;
  letter-spacing: 0.1em;
  color: var(--mut, #7d8c96);
  text-transform: uppercase;
}

.sd-v {
  font-size: 26px;
  font-weight: 700;
  color: var(--ink);
  line-height: 1.2;
}

.sd-cell.is-after .sd-v {
  color: var(--sig);
}

.sd-arrow {
  color: var(--mut, #7d8c96);
  font-size: 16px;
}

.sd-cell.is-delta .sd-v {
  font-size: 18px;
}

.dim-diff {
  padding: 11px 14px;
  border-bottom: 1px solid var(--line);
  display: flex;
  flex-direction: column;
  gap: 7px;
}

.dd-row {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 11px;
}

.dd-name {
  width: 92px;
  flex-shrink: 0;
  color: var(--ink);
}

.dd-bar {
  flex: 1;
  height: 4px;
  background: rgba(255, 255, 255, 0.05);
  border-radius: 2px;
  overflow: hidden;
}

.dd-bar i {
  display: block;
  height: 100%;
  background: linear-gradient(90deg, var(--sig-deep), var(--sig));
  border-radius: 2px;
  transition: width 0.4s ease;
}

.dd-num {
  color: var(--mut, #7d8c96);
  width: 78px;
  text-align: right;
  flex-shrink: 0;
}

.dd-delta {
  width: 34px;
  text-align: right;
  flex-shrink: 0;
  font-weight: 700;
}

.cmp-sub {
  padding: 11px 14px;
  border-bottom: 1px solid var(--line);
}

.cmp-sub:last-child {
  border-bottom: none;
}

.cs-hd {
  font-size: 10px;
  letter-spacing: 0.1em;
  color: var(--mut, #7d8c96);
  text-transform: uppercase;
  margin-bottom: 8px;
}

.cs-body {
  display: flex;
  flex-direction: column;
  gap: 5px;
  font-size: 11.5px;
  color: var(--ink);
  line-height: 1.6;
}

.sig-t {
  color: var(--sig);
}

.cd-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.cd-row {
  display: flex;
  gap: 12px;
  font-size: 11px;
}

.cd-no {
  color: var(--sig);
}

.cd-op {
  color: var(--amber);
}

.cd-field {
  color: #6fc3d8;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* ---------- O.08 定制版本 ---------- */
.tailor-summary {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 22px;
  font-size: 11.5px;
  color: var(--ink-4);
  margin-bottom: 12px;
}

.tailor-summary b {
  color: var(--sig);
  font-weight: 600;
}

.move-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.move-row {
  display: flex;
  align-items: baseline;
  gap: 10px;
  padding: 7px 11px;
  border-radius: 3px;
  background: rgba(230, 239, 233, 0.03);
  border-left: 2px solid transparent;
  font-size: 11.5px;
  line-height: 1.6;
}

.move-row.mv-promoted {
  border-left-color: var(--sig);
}

.move-row.mv-demoted {
  border-left-color: var(--amber);
}

.mv-act {
  flex: none;
  font-size: 10px;
  letter-spacing: 0.06em;
}

.move-row.mv-promoted .mv-act {
  color: var(--sig);
}

.move-row.mv-demoted .mv-act {
  color: var(--amber);
}

.mv-field {
  flex: none;
  color: #6fc3d8;
  max-width: 260px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.mv-idx {
  flex: none;
  color: var(--ink-4);
}

.mv-hits {
  flex: none;
  font-size: 10px;
  color: var(--ink-4);
  padding: 0 6px;
  border: 1px solid var(--line);
  border-radius: 2px;
}

.mv-reason {
  color: var(--ink-3, rgba(230, 239, 233, 0.6));
  min-width: 0;
}

.tailor-foot {
  margin-top: 12px;
  font-size: 11.5px;
  color: var(--ink-4);
}

/* ============ 模型接入（用户自带模型）============ */
.engine-flag {
  margin-left: auto;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 10.5px;
  letter-spacing: 0.04em;
  padding: 3px 8px;
  border: 1px solid var(--line);
  border-radius: 2px;
  color: var(--ink-3);
}

.engine-flag .led {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--ink-4);
}

.engine-flag.is-on {
  color: var(--sig);
  border-color: var(--sig-line);
  background: var(--sig-soft);
}

.engine-flag.is-on .led {
  background: var(--sig);
  box-shadow: 0 0 6px var(--sig);
}

.engine-flag.is-off .led {
  background: var(--ink-4);
}

.ms-consent {
  font-size: 12px;
  line-height: 1.75;
  color: var(--ink-2);
  background: var(--amber-soft);
  border-left: 2px solid var(--amber-line);
  padding: 10px 12px;
  margin-bottom: 14px;
}

.ms-consent b {
  color: var(--amber);
  font-weight: 600;
}

.ms-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.4fr) minmax(0, 1fr);
  gap: 10px 12px;
}

.ms-field {
  display: flex;
  flex-direction: column;
  gap: 5px;
  min-width: 0;
}

.ms-wide {
  grid-column: 1 / -1;
}

.ms-label {
  font-size: 10.5px;
  color: var(--ink-3);
  letter-spacing: 0.03em;
}

.ms-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 14px;
  flex-wrap: wrap;
}

.ms-spacer {
  flex: 1;
}

.ms-result {
  margin-top: 10px;
  font-size: 11.5px;
  padding: 8px 10px;
  border: 1px solid var(--line);
  border-radius: 2px;
  background: var(--panel-3);
  color: var(--ink-2);
  line-height: 1.6;
  word-break: break-all;
}

.ms-result.is-ok {
  color: var(--sig);
  border-color: var(--sig-line);
  background: var(--sig-soft);
}

.ms-result.is-err {
  color: var(--red);
  border-color: var(--red-line);
  background: var(--red-soft);
}

.ms-result.is-pending,
.ms-result.is-saved {
  color: var(--ink-3);
}
</style>
