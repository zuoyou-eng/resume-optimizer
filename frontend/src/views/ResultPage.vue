<template>
  <div v-loading="loading">
    <template v-if="!loading && data.resume_id">
      <!-- 标题区 -->
      <div class="page-hero">
        <div class="kicker">Parse Result · 机器阅读输出</div>
        <h1>解析结果</h1>
        <p>
          以下字段由规则引擎确定性输出——相同输入必得相同结果。
          每个字段的来源与命中规则，可在末尾的「解析轨迹」中逐条核对。
        </p>
      </div>

      <!-- 元信息 -->
      <div class="result-meta">
        <span class="meta-chip">resume_id<b class="mono">{{ shortId }}</b></span>
        <span class="meta-chip">engine<b class="mono">{{ data.rule_version }}</b></span>
        <span class="meta-chip">trace<b class="mono">{{ traceCount }}</b></span>
        <span class="meta-chip">unmapped<b class="mono" :style="data.unrecognized?.length ? 'color: var(--amber)' : ''">{{ data.unrecognized?.length || 0 }}</b></span>
        <el-button class="meta-refresh" text @click="load">
          <el-icon style="margin-right: 4px"><refresh /></el-icon>重新解析
        </el-button>
        <router-link :to="`/resumes/${route.params.id}/diagnose`" class="to-diagnose">
          三维度诊断 →
        </router-link>
        <router-link :to="`/resumes/${route.params.id}/draft`" class="to-draft">
          草稿工作台 →
        </router-link>
        <router-link :to="`/resumes/${route.params.id}/highlight`" class="to-highlight">
          亮点挖掘 →
        </router-link>
      </div>

      <!-- [01] 基本信息 -->
      <section class="panel" style="--i: 1">
        <header class="mod-head">
          <span class="mod-no">[ F.01 ]</span>
          <h2 class="mod-title">基本信息</h2>
          <span class="mod-en">basic_info</span>
          <span class="mod-count">取自首屏与联系区</span>
        </header>
        <div class="mod-body">
          <div class="id-row">
            <span class="id-name" :class="{ blank: !basic.name }">{{ basic.name || "姓名未识别" }}</span>
            <span class="id-chips">
              <span v-if="basic.degree" class="chip sig">{{ basic.degree }}</span>
              <span v-if="basic.city" class="chip amber">{{ basic.city }}</span>
            </span>
          </div>
          <div class="kv-grid">
            <div class="kv">
              <span class="kv-k">Phone · 电话</span>
              <span class="kv-v" :class="{ blank: !basic.phone }">{{ basic.phone || "-" }}</span>
            </div>
            <div class="kv">
              <span class="kv-k">Email · 邮箱</span>
              <span class="kv-v" :class="{ blank: !basic.email }">{{ basic.email || "-" }}</span>
            </div>
            <div class="kv">
              <span class="kv-k">City · 所在城市</span>
              <span class="kv-v" :class="{ blank: !basic.city }">{{ basic.city || "-" }}</span>
            </div>
          </div>
        </div>
      </section>

      <!-- [02] 教育背景 -->
      <section v-if="data.structure.education.length" class="panel" style="--i: 2">
        <header class="mod-head">
          <span class="mod-no">[ F.02 ]</span>
          <h2 class="mod-title">教育背景</h2>
          <span class="mod-en">education</span>
          <span class="mod-count"><b>{{ data.structure.education.length }}</b> 段</span>
        </header>
        <div class="mod-body">
          <div class="entries">
            <div class="entry is-edu" v-for="(item, i) in data.structure.education" :key="'edu' + i">
              <div class="entry-head">
                <span class="entry-name" :class="{ blank: !item.school }">{{ item.school || "（学校未识别）" }}</span>
                <span v-if="item.degree" class="chip sig">{{ item.degree }}</span>
                <span v-if="item.major" class="entry-role">{{ item.major }}</span>
                <span v-if="item.period" class="entry-period">{{ item.period }}</span>
              </div>
              <div v-if="item.description" class="entry-desc">{{ item.description }}</div>
            </div>
          </div>
        </div>
      </section>

      <!-- [03] 实习 / 工作经历 -->
      <section v-if="data.structure.experience.length" class="panel" style="--i: 3">
        <header class="mod-head">
          <span class="mod-no">[ F.03 ]</span>
          <h2 class="mod-title">实习 / 工作经历</h2>
          <span class="mod-en">experience</span>
          <span class="mod-count"><b>{{ data.structure.experience.length }}</b> 段</span>
        </header>
        <div class="mod-body">
          <div class="entries">
            <div class="entry" v-for="(item, i) in data.structure.experience" :key="'exp' + i">
              <div class="entry-head">
                <span class="entry-name" :class="{ blank: !item.company }">{{ item.company || "（单位未识别）" }}</span>
                <span v-if="item.role" class="entry-role">{{ item.role }}</span>
                <span v-if="item.period" class="entry-period">{{ item.period }}</span>
              </div>
              <div v-if="item.description" class="entry-desc">{{ item.description }}</div>
            </div>
          </div>
        </div>
      </section>

      <!-- [04] 项目经历 -->
      <section v-if="data.structure.projects.length" class="panel" style="--i: 4">
        <header class="mod-head">
          <span class="mod-no">[ F.04 ]</span>
          <h2 class="mod-title">项目经历</h2>
          <span class="mod-en">projects</span>
          <span class="mod-count"><b>{{ data.structure.projects.length }}</b> 段</span>
        </header>
        <div class="mod-body">
          <div class="entries">
            <div class="entry" v-for="(item, i) in data.structure.projects" :key="'prj' + i">
              <div class="entry-head">
                <span class="entry-name" :class="{ blank: !item.name }">{{ item.name || "（项目名未识别）" }}</span>
                <span v-if="item.role" class="entry-role">{{ item.role }}</span>
                <span v-if="item.period" class="entry-period">{{ item.period }}</span>
              </div>
              <div v-if="item.description" class="entry-desc">{{ item.description }}</div>
            </div>
          </div>
        </div>
      </section>

      <!-- [05] 技能 -->
      <section v-if="data.structure.skills.length" class="panel" style="--i: 5">
        <header class="mod-head">
          <span class="mod-no">[ F.05 ]</span>
          <h2 class="mod-title">专业技能</h2>
          <span class="mod-en">skills</span>
          <span class="mod-count"><b>{{ data.structure.skills.length }}</b> 项</span>
        </header>
        <div class="mod-body">
          <div class="skill-grid">
            <span class="skill" v-for="(s, i) in data.structure.skills" :key="'sk' + i">{{ s }}</span>
          </div>
        </div>
      </section>

      <!-- [06] 荣誉奖项 -->
      <section v-if="data.structure.honors.length" class="panel" style="--i: 6">
        <header class="mod-head">
          <span class="mod-no">[ F.06 ]</span>
          <h2 class="mod-title">荣誉奖项</h2>
          <span class="mod-en">honors</span>
          <span class="mod-count"><b>{{ data.structure.honors.length }}</b> 项</span>
        </header>
        <div class="mod-body">
          <ul class="honors">
            <li v-for="(h, i) in data.structure.honors" :key="'hn' + i">
              <span class="h-no">{{ String(i + 1).padStart(2, "0") }}</span>
              <span>{{ h }}</span>
            </li>
          </ul>
        </div>
      </section>

      <!-- [!] FR-03：未识别内容显式保留 -->
      <section v-if="data.unrecognized.length" class="panel keep-panel" style="--i: 7">
        <header class="mod-head">
          <span class="mod-no" style="color: var(--amber); background: var(--amber-soft); border-color: var(--amber-line)">[ ! ]</span>
          <h2 class="mod-title">未识别内容</h2>
          <span class="mod-en">unmapped</span>
          <span class="mod-count">原文原样保留 · 未丢弃</span>
        </header>
        <div class="mod-body">
          <div class="keep">
            <div class="keep-head">
              <el-icon><warning-filled /></el-icon>
              有 {{ data.unrecognized.length }} 段内容未能归入结构化字段
              <span class="unmapped">UNMAPPED</span>
            </div>
            <ul>
              <li v-for="(u, i) in data.unrecognized" :key="'un' + i">
                {{ u.text }}
                <span class="reason">reason: {{ u.reason }}</span>
              </li>
            </ul>
          </div>
        </div>
      </section>

      <!-- [LOG] 解析轨迹 -->
      <section class="panel" style="--i: 8">
        <header class="mod-head">
          <span class="mod-no">[ LOG ]</span>
          <h2 class="mod-title">解析轨迹</h2>
          <span class="mod-en">trace_log</span>
          <span class="mod-count"><b>{{ traceCount }}</b> 条记录</span>
        </header>
        <div class="mod-body">
          <div class="logbox" :class="{ open: traceOpen }">
            <button class="logbox-head" @click="traceOpen = !traceOpen">
              <el-icon><terminal /></el-icon>
              <span>tail -f parse_trace.log</span>
              <el-icon class="caret"><arrow-right /></el-icon>
            </button>
            <div v-show="traceOpen" class="logbox-body">
              <div class="logline" v-for="(t, i) in data.trace" :key="'tr' + i">
                <span class="ln">{{ String(i + 1).padStart(2, "0") }}</span>
                <span class="field">{{ t.field }}</span>
                <span class="arrow">→</span>
                <span class="value">{{ t.extracted }}</span>
                <span class="src">← {{ t.source_region }}</span>
                <span class="rule">{{ t.rule_applied }}</span>
              </div>
              <div v-if="!traceCount" class="log-empty">// no trace records</div>
            </div>
          </div>
        </div>
      </section>
    </template>

    <!-- 空状态 -->
    <div v-else-if="!loading" class="panel" style="--i: 1">
      <div class="blank">
        <div class="blank-glyph">[ × ]</div>
        <div class="blank-t">未找到该简历的解析结果</div>
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
import { resumeApi } from "../api/client";

const route = useRoute();
const loading = ref(true);
const data = ref({});
const traceOpen = ref(true);

const basic = computed(() => data.value.structure?.basic_info || {});

const shortId = computed(() => (data.value.resume_id || "").slice(0, 8));

const traceCount = computed(() => (data.value.trace || []).length);

const EMPTY_STRUCTURE = {
  basic_info: {},
  education: [],
  experience: [],
  projects: [],
  skills: [],
  honors: [],
};

async function load() {
  loading.value = true;
  try {
    const body = await resumeApi.getStructure(route.params.id);
    data.value = {
      ...body.data,
      structure: { ...EMPTY_STRUCTURE, ...(body.data.structure || {}) },
    };
    rememberResume(route.params.id);
  } catch (e) {
    data.value = {};
  } finally {
    loading.value = false;
  }
}

// 记录最近查看的简历，供侧边栏「三维度诊断」入口直接跳转
function rememberResume(id) {
  try {
    localStorage.setItem("ro:last-resume-id", id);
  } catch {
    /* 隐私模式下 localStorage 不可用，忽略即可 */
  }
}

onMounted(load);
</script>

<style scoped>
.meta-refresh {
  margin-left: auto;
  color: var(--sig);
  font-family: var(--mono);
  font-size: 11px;
  letter-spacing: 0.06em;
}

/* 跳转诊断的入口：与重新解析按钮并列，置于 meta 行末端 */
.to-diagnose {
  font-family: var(--mono);
  font-size: 11px;
  letter-spacing: 0.06em;
  color: var(--sig);
  text-decoration: none;
  border: 1px solid rgba(79, 227, 165, 0.35);
  border-radius: 2px;
  padding: 6px 12px;
  white-space: nowrap;
  transition: background 0.18s ease, box-shadow 0.18s ease;
}

.to-diagnose:hover {
  background: rgba(79, 227, 165, 0.1);
  box-shadow: 0 0 14px rgba(79, 227, 165, 0.2);
}

.to-draft {
  font-family: var(--mono);
  font-size: 11px;
  letter-spacing: 0.06em;
  color: var(--amber);
  text-decoration: none;
  border: 1px solid rgba(245, 181, 71, 0.35);
  border-radius: 2px;
  padding: 6px 12px;
  white-space: nowrap;
  transition: background 0.18s ease, box-shadow 0.18s ease;
}

.to-draft:hover {
  background: rgba(245, 181, 71, 0.1);
  box-shadow: 0 0 14px rgba(245, 181, 71, 0.2);
}

/* 亮点挖掘入口：实心琥珀，与草稿的描边样式区分 */
.to-highlight {
  font-family: var(--mono);
  font-size: 11px;
  letter-spacing: 0.06em;
  color: #10160f;
  font-weight: 700;
  text-decoration: none;
  background: var(--amber);
  border: 1px solid var(--amber);
  border-radius: 2px;
  padding: 6px 12px;
  white-space: nowrap;
  transition: filter 0.18s ease, box-shadow 0.18s ease;
}

.to-highlight:hover {
  filter: brightness(1.12);
  box-shadow: 0 0 14px rgba(245, 181, 71, 0.3);
}

.keep-panel .mod-body {
  padding-top: 0;
}
</style>
