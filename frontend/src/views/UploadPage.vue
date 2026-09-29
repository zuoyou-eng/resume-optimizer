<template>
  <div>
    <!-- 标题区 -->
    <div class="page-hero">
      <div class="kicker">Input Channel · 步骤 01</div>
      <h1>让<em class="hl">机器</em>把你的简历读一遍</h1>
      <p>
        支持 PDF / DOCX / TXT / MD / 图片（PNG、JPG、BMP、WebP，走系统 OCR），单文件不超过 10MB。
        上传后由规则引擎完成结构化解析——
        每条信息都可回溯到原文与命中规则，无法归类的内容会被显式保留，而不是静默丢弃。
      </p>
    </div>

    <!-- 上传通道 -->
    <section class="panel" style="--i: 1">
      <header class="mod-head">
        <span class="mod-no">[ 01 ]</span>
        <h2 class="mod-title">选择文件</h2>
        <span class="mod-en">select_file</span>
        <span class="mod-count">本地解析 · 不上传第三方</span>
      </header>

      <div class="mod-body">
        <div class="dropper">
          <span class="crop tl"></span><span class="crop tr"></span>
          <span class="crop bl"></span><span class="crop br"></span>

          <el-upload
            drag
            :auto-upload="false"
            :limit="1"
            :on-change="onFileChange"
            :on-exceed="onExceed"
            :file-list="fileList"
            accept=".pdf,.docx,.txt,.md,.png,.jpg,.jpeg,.bmp,.webp"
          >
            <div class="drop-glyph">[ ↓ ]</div>
            <div class="drop-title">把简历文件拖到这里</div>
            <div class="drop-hint">or click to browse · one file at a time</div>
            <template #tip>
              <div class="fmt-row">
                <span class="fmt-chip">PDF</span>
                <span class="fmt-chip">DOCX</span>
                <span class="fmt-chip">TXT</span>
                <span class="fmt-chip">MD</span>
                <span class="fmt-chip">PNG</span>
                <span class="fmt-chip">JPG</span>
                <span class="fmt-chip">BMP</span>
                <span class="fmt-chip">WEBP</span>
              </div>
            </template>
          </el-upload>
        </div>

        <!-- 已选文件条 -->
        <div v-if="selectedFile" class="file-strip">
          <div class="fs-ico">
            <el-icon><document /></el-icon>
          </div>
          <div class="fs-meta">
            <div class="fs-name">{{ selectedFile.name }}</div>
            <div class="fs-sub">{{ formatSize(selectedFile.size) }} · {{ extOf(selectedFile.name) }}</div>
          </div>
          <el-button text class="fs-clear" @click="clearFile">
            <el-icon><close /></el-icon>
          </el-button>
        </div>

        <div class="act-row">
          <el-button
            type="primary"
            size="large"
            :loading="uploading"
            :disabled="!selectedFile || uploading"
            @click="doUpload"
          >
            {{ uploading ? `解析中 ${progress}%` : "开始解析 →" }}
          </el-button>
          <span v-if="!selectedFile" class="act-note">awaiting file ...</span>
        </div>

        <!-- 分段式进度条：仪器风格 -->
        <div v-if="uploading" class="segbar">
          <i v-for="n in 12" :key="n" class="seg" :class="{ lit: progress >= (n * 100) / 12 }"></i>
          <span class="seg-num">{{ String(progress).padStart(3, "0") }}%</span>
        </div>

        <el-alert
          v-if="error"
          :title="error"
          type="error"
          show-icon
          :closable="false"
          class="err-alert"
        />
      </div>
    </section>

    <!-- 最近上传 -->
    <section class="panel" style="--i: 2">
      <header class="mod-head">
        <span class="mod-no">[ 02 ]</span>
        <h2 class="mod-title">最近上传</h2>
        <span class="mod-en">recent_inputs</span>
        <span class="mod-count"><b>{{ recent.length }}</b> 条</span>
      </header>

      <el-table :data="recent" v-loading="loadingList" class="recent-table">
        <el-table-column label="文件名" prop="original_name" show-overflow-tooltip min-width="180" />
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
        <el-table-column label="操作" width="112" align="right">
          <template #default="{ row }">
            <router-link class="link-act" :to="`/resumes/${row.id}/structure`">查看 →</router-link>
          </template>
        </el-table-column>
        <template #empty>
          <div class="empty-tip">// 暂无上传记录 —— 拖入第一份简历试试</div>
        </template>
      </el-table>
    </section>
  </div>
</template>

<script setup>
import { onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { ElMessage } from "element-plus";
import { resumeApi } from "../api/client";

const router = useRouter();
const fileList = ref([]);
const selectedFile = ref(null);
const uploading = ref(false);
const progress = ref(0);
const error = ref("");
const recent = ref([]);
const loadingList = ref(false);

const ALLOWED = ["pdf", "docx", "txt", "md", "png", "jpg", "jpeg", "bmp", "webp"];
const MAX_SIZE = 10 * 1024 * 1024;

function extOf(name) {
  return (name.split(".").pop() || "").toLowerCase();
}

function formatSize(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function onFileChange(file) {
  error.value = "";
  const ext = extOf(file.name);
  if (!ALLOWED.includes(ext)) {
    error.value = `不支持的文件类型：.${ext}（仅支持 ${ALLOWED.join(" / ")}）`;
    fileList.value = [];
    selectedFile.value = null;
    return;
  }
  if (file.size > MAX_SIZE) {
    error.value = `文件过大：${formatSize(file.size)}（上限 10MB）`;
    fileList.value = [];
    selectedFile.value = null;
    return;
  }
  selectedFile.value = file.raw;
}

function onExceed() {
  error.value = "一次只能上传一个文件，请先移除已选文件";
}

function clearFile() {
  selectedFile.value = null;
  fileList.value = [];
  progress.value = 0;
}

async function doUpload() {
  if (!selectedFile.value) return;
  uploading.value = true;
  progress.value = 0;
  error.value = "";
  try {
    const body = await resumeApi.upload(selectedFile.value, (p) => {
      progress.value = p;
    });
    ElMessage.success("解析完成");
    router.push(`/resumes/${body.data.resume_id}/structure`);
  } catch (e) {
    error.value = e.message;
  } finally {
    uploading.value = false;
  }
}

async function loadRecent() {
  loadingList.value = true;
  try {
    const body = await resumeApi.list();
    recent.value = (body.data || []).slice(0, 5);
  } catch (e) {
    recent.value = [];
  } finally {
    loadingList.value = false;
  }
}

function formatTime(iso) {
  if (!iso) return "-";
  return new Date(iso).toLocaleString("zh-CN", { hour12: false });
}

onMounted(loadRecent);
</script>

<style scoped>
/* 去掉 Element Plus 拖拽区默认内边距与边框，交由 .dropper 控制 */
:deep(.el-upload__tip) {
  margin-top: 0;
}

:deep(.el-upload-dragger) {
  padding: 0;
  border: none;
  background: transparent;
  width: 100%;
  border-radius: 0;
}

:deep(.el-upload--text) {
  width: 100%;
}

:deep(.el-upload-dragger.is-drag) {
  background: transparent;
  border: none;
}

:deep(.el-upload-dragger.is-drag .drop-title) {
  color: var(--sig);
}

.err-alert {
  margin-top: 16px;
}

:deep(.el-alert--error) {
  --el-alert-bg-color: var(--red-soft);
  --el-alert-border-color: var(--red-line);
  border-radius: 3px;
}

:deep(.el-alert__title) {
  color: var(--red);
  font-size: 13px;
}

:deep(.el-alert__icon) {
  color: var(--red);
}
</style>
