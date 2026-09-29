<template>
  <div class="workspace">
    <div class="app-shell">
      <!-- 左侧：仪器控制台 -->
      <aside class="sidebar">
        <div class="brand">
          <div class="brand-mark">[ R ]</div>
          <div class="brand-name">简历优化助手</div>
          <div class="brand-sub">Resume Optimizer</div>
        </div>

        <nav class="side-nav">
          <div class="nav-label">工作区 / Workspace</div>
          <router-link class="nav-item" to="/upload">
            <span class="nav-idx">01</span>
            <el-icon class="nav-ico"><upload-filled /></el-icon>
            <span>上传简历</span>
          </router-link>
          <router-link class="nav-item" to="/resumes">
            <span class="nav-idx">02</span>
            <el-icon class="nav-ico"><files /></el-icon>
            <span>简历列表</span>
          </router-link>

          <div class="nav-label">路线图 / Roadmap</div>
          <router-link class="nav-item" :to="diagnoseLink">
            <span class="nav-idx">03</span>
            <el-icon class="nav-ico"><data-analysis /></el-icon>
            <span>三维度诊断</span>
          </router-link>
          <router-link class="nav-item" :to="draftLink">
            <span class="nav-idx">04</span>
            <el-icon class="nav-ico"><edit-pen /></el-icon>
            <span>草稿工作台</span>
          </router-link>
          <router-link class="nav-item" :to="highlightLink">
            <span class="nav-idx">05</span>
            <el-icon class="nav-ico"><magic-stick /></el-icon>
            <span>亮点挖掘</span>
          </router-link>
        </nav>

        <div class="side-foot">
          <div class="sf-row"><span>Engine</span><b>rule-1.0.0</b></div>
          <div class="sf-row"><span>Stage</span><b>V1.0</b></div>
          <div class="sf-row">
            <span>Status</span>
            <b :class="apiUp ? 'is-on' : 'is-off'"><i class="led"></i>{{ apiUp ? "Online" : "Offline" }}</b>
          </div>
        </div>
      </aside>

      <!-- 右侧：状态栏 + 内容 -->
      <div class="main-col">
        <header class="topbar">
          <div class="crumb">
            <span>resume_optimizer</span>
            <span class="crumb-sep">/</span>
            <span>{{ currentPath }}</span>
            <span class="crumb-sep">/</span>
            <span class="crumb-cur">{{ currentTitle }}</span>
          </div>
          <div class="topbar-right">
            <span class="tb-item">api<b :class="apiUp ? 'ok' : 'bad'">{{ apiUp ? "200" : "ERR" }}</b></span>
            <span class="tb-item">engine<b>rule-1.0.0</b></span>
            <span class="clock">{{ clock }}</span>
          </div>
        </header>

        <main class="page-body">
          <div class="page-inner">
            <router-view v-slot="{ Component }">
              <transition name="page" mode="out-in">
                <component :is="Component" />
              </transition>
            </router-view>
          </div>
        </main>
      </div>
    </div>
  </div>
</template>

<script setup>
// 应用外壳：深色仪器控制台。
// 顶栏每秒对时；「api 200 / ERR」每 20s 探测一次 /api/v1/health。
import { computed, onMounted, onUnmounted, ref } from "vue";
import { useRoute } from "vue-router";

const route = useRoute();
const apiUp = ref(false);
const clock = ref("--:--:--");
let timer = null;
let clockTimer = null;

const ROUTE_META = {
  upload: { path: "input", title: "上传简历 · Upload" },
  resumes: { path: "archive", title: "简历列表 · Archive" },
  structure: { path: "input", title: "解析结果 · Parse Result" },
  diagnose: { path: "diagnosis", title: "三维度诊断 · Diagnosis" },
  draft: { path: "optimize", title: "草稿工作台 · Draft Workspace" },
  highlight: { path: "optimize", title: "亮点挖掘 · Highlight Mining" },
};

// 诊断入口：优先跳到最近查看过的简历，没有记录时落到列表页让用户选
const LAST_RESUME_KEY = "ro:last-resume-id";

const diagnoseLink = computed(() => {
  let last = "";
  try {
    last = localStorage.getItem(LAST_RESUME_KEY) || "";
  } catch {
    last = "";
  }
  return last ? `/resumes/${last}/diagnose` : "/resumes";
});

// 草稿工作台入口：同样优先最近查看过的简历
const draftLink = computed(() => {
  let last = "";
  try {
    last = localStorage.getItem(LAST_RESUME_KEY) || "";
  } catch {
    last = "";
  }
  return last ? `/resumes/${last}/draft` : "/resumes";
});

// 亮点挖掘入口：同样优先最近查看过的简历
const highlightLink = computed(() => {
  let last = "";
  try {
    last = localStorage.getItem(LAST_RESUME_KEY) || "";
  } catch {
    last = "";
  }
  return last ? `/resumes/${last}/highlight` : "/resumes";
});

const currentPath = computed(() => ROUTE_META[route.name]?.path || "input");
const currentTitle = computed(() => ROUTE_META[route.name]?.title || "上传简历 · Upload");

function tick() {
  const d = new Date();
  const p = (n) => String(n).padStart(2, "0");
  clock.value = `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}

async function ping() {
  try {
    const res = await fetch("/api/v1/health");
    apiUp.value = res.ok;
  } catch {
    apiUp.value = false;
  }
}

onMounted(() => {
  tick();
  clockTimer = setInterval(tick, 1000);
  ping();
  timer = setInterval(ping, 20000);
});

onUnmounted(() => {
  clearInterval(timer);
  clearInterval(clockTimer);
});
</script>

<style scoped>
/* 路由切换：轻微上浮 + 淡入 */
.page-enter-active,
.page-leave-active {
  transition: opacity 0.2s ease, transform 0.2s ease;
}

.page-enter-from {
  opacity: 0;
  transform: translateY(6px);
}

.page-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}
</style>
