<template>
  <div>
    <!-- 标题区 -->
    <div class="page-hero">
      <div class="kicker">Archive · 已导入样本</div>
      <h1>简历列表</h1>
      <p>所有上传过的简历及其解析状态。删除为软删除——删除后该简历的解析结果将立即不可访问。</p>
    </div>

    <!-- 统计条 -->
    <div class="stat-row">
      <div class="stat">
        <div class="stat-num">{{ rows.length }}</div>
        <div class="stat-label">total · 全部</div>
      </div>
      <div class="stat">
        <div class="stat-num sig">{{ parsedCount }}</div>
        <div class="stat-label">parsed · 成功</div>
      </div>
      <div class="stat">
        <div class="stat-num red">{{ failedCount }}</div>
        <div class="stat-label">failed · 失败</div>
      </div>
      <div class="stat">
        <div class="stat-num">{{ totalSize }}</div>
        <div class="stat-label">size · 占用</div>
      </div>
    </div>

    <!-- 记录表 -->
    <section class="panel" style="--i: 1">
      <header class="mod-head">
        <span class="mod-no">[ 01 ]</span>
        <h2 class="mod-title">全部记录</h2>
        <span class="mod-en">records</span>
        <span class="mod-count">
          <el-button class="refresh-btn" text @click="load">
            <el-icon style="margin-right: 4px"><refresh /></el-icon>重新加载
          </el-button>
        </span>
      </header>

      <el-table :data="rows" v-loading="loading" class="list-table">
        <el-table-column label="文件名" prop="original_name" show-overflow-tooltip min-width="180" />
        <el-table-column label="格式" width="84">
          <template #default="{ row }">
            <span class="ext-badge">{{ row.file_type }}</span>
          </template>
        </el-table-column>
        <el-table-column label="大小" width="104">
          <template #default="{ row }">
            <span class="mono" style="font-size: 12px; color: var(--ink-3)">{{ formatSize(row.file_size) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="96">
          <template #default="{ row }">
            <span class="chip" :class="row.status === 'parsed' ? 'sig' : ''" v-if="row.status === 'parsed'">PARSED</span>
            <span class="chip" style="color: var(--red); border-color: var(--red-line)" v-else>FAILED</span>
          </template>
        </el-table-column>
        <el-table-column label="上传时间" width="186">
          <template #default="{ row }">
            <span class="mono" style="font-size: 12px; color: var(--ink-3)">{{ formatTime(row.created_at) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="330" align="right">
          <template #default="{ row }">
            <router-link class="link-act" :to="`/resumes/${row.id}/structure`">查看 →</router-link>
            <router-link class="link-act diag" :to="`/resumes/${row.id}/diagnose`">诊断</router-link>
            <router-link class="link-act draft" :to="`/resumes/${row.id}/draft`">草稿</router-link>
            <router-link class="link-act mine" :to="`/resumes/${row.id}/highlight`">挖亮点</router-link>
            <el-popconfirm
              :title="`确认删除「${row.original_name}」？`"
              confirm-button-text="删除"
              confirm-button-type="danger"
              cancel-button-text="取消"
              width="230"
              @confirm="remove(row)"
            >
              <template #reference>
                <el-button link type="danger" size="small" class="del-btn">删除</el-button>
              </template>
            </el-popconfirm>
          </template>
        </el-table-column>

        <template #empty>
          <div class="empty-tip">// 暂无简历 —— 先去上传页导入第一份</div>
        </template>
      </el-table>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import { resumeApi } from "../api/client";

const rows = ref([]);
const loading = ref(false);

const parsedCount = computed(() => rows.value.filter((r) => r.status === "parsed").length);
const failedCount = computed(() => rows.value.filter((r) => r.status !== "parsed").length);
const totalSize = computed(() => {
  const bytes = rows.value.reduce((s, r) => s + (r.file_size || 0), 0);
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
});

async function load() {
  loading.value = true;
  try {
    const body = await resumeApi.list();
    rows.value = body.data || [];
  } catch (e) {
    rows.value = [];
  } finally {
    loading.value = false;
  }
}

async function remove(row) {
  try {
    await resumeApi.remove(row.id);
    ElMessage.success("已删除");
    load();
  } catch (e) {
    ElMessage.error(e.message);
  }
}

function formatSize(bytes) {
  if (bytes == null) return "-";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function formatTime(iso) {
  if (!iso) return "-";
  return new Date(iso).toLocaleString("zh-CN", { hour12: false });
}

onMounted(load);
</script>

<style scoped>
.ext-badge {
  display: inline-block;
  font-size: 10px;
  font-family: var(--mono);
  letter-spacing: 0.08em;
  color: var(--ink-2);
  background: var(--panel-3);
  border: 1px solid var(--line);
  border-radius: 3px;
  padding: 2px 7px;
  text-transform: uppercase;
}

.refresh-btn {
  color: var(--sig);
  font-family: var(--mono);
  font-size: 11px;
  letter-spacing: 0.06em;
}

.del-btn {
  margin-left: 12px;
  font-family: var(--mono);
  font-size: 11px;
  letter-spacing: 0.06em;
}

/* 操作列的「诊断」入口与「查看」拉开间距 */
.link-act.diag {
  margin-left: 14px;
}

.link-act.draft {
  margin-left: 14px;
  color: var(--amber);
}

.link-act.mine {
  margin-left: 14px;
  color: var(--amber);
  font-weight: 700;
}

:deep(.el-table__body-wrapper) {
  border-bottom: none;
}
</style>
