// API 客户端：统一处理后端 {code, message, data, trace_id} 响应格式
import axios from "axios";

const client = axios.create({
  baseURL: "/api/v1",
  timeout: 30000,
});

// 请求拦截：生成/透传 trace_id，与后端链路关联
client.interceptors.request.use((config) => {
  config.headers["X-Trace-Id"] = `req-${Math.random().toString(16).slice(2, 10)}`;
  return config;
});

// 响应拦截：业务错误码统一转成可捕获的错误
client.interceptors.response.use(
  (response) => {
    const body = response.data;
    if (body && typeof body.code === "number" && body.code !== 0) {
      return Promise.reject(
        new Error(body.message || `错误码 ${body.code}（trace: ${body.trace_id}）`)
      );
    }
    return body;
  },
  (error) => {
    if (error.response?.data?.message) {
      return Promise.reject(new Error(error.response.data.message));
    }
    return Promise.reject(new Error(`网络错误：${error.message}`));
  }
);

export const resumeApi = {
  upload(file, onProgress) {
    const form = new FormData();
    form.append("file", file);
    return client.post("/resumes", form, {
      headers: { "Content-Type": "multipart/form-data" },
      onUploadProgress: (e) => {
        if (onProgress && e.total) {
          onProgress(Math.round((e.loaded / e.total) * 100));
        }
      },
    });
  },
  list: () => client.get("/resumes"),
  getStructure: (id) => client.get(`/resumes/${id}/structure`),
  remove: (id) => client.delete(`/resumes/${id}`),
};

// 诊断相关接口（设计文档 7.1 #3/#4/#5/#6/#7）
export const diagnosisApi = {
  submitJd: (payload) => client.post("/job-descriptions", payload),
  run: (payload) => client.post("/diagnoses", payload),
  getDiagnosis: (id) => client.get(`/diagnoses/${id}`),
  getReport: (resumeId) => client.get(`/reports/${resumeId}`),
  // FR-13：导出自包含 HTML 报告（blob；业务错误时返回的是 JSON 错误体，由调用方解析）
  exportReport: (resumeId) =>
    client.get(`/reports/${resumeId}/export`, { responseType: "blob" }),
};

// 优化模块接口（设计文档 7.1 #9-#18）
export const optimizeApi = {
  // O-01/O-02：基于问题项发起改写 / 查询改写结果
  generateRewrite: (payload) => client.post("/rewrites", payload),
  getRewrite: (id) => client.get(`/rewrites/${id}`),
  listRewrites: (resumeId) => client.get(`/resumes/${resumeId}/rewrites`),
  // O-03：应用单条改写到草稿
  applyRewrite: (id) => client.post(`/rewrites/${id}/apply`),
  // O-04：草稿内容与手工编辑（同样产生新版本）
  getDraftByResume: (resumeId) => client.get(`/resumes/${resumeId}/draft`),
  editField: (draftId, payload) => client.patch(`/drafts/${draftId}/fields`, payload),
  // O-03/NFR-10：版本历史与回滚
  listRevisions: (draftId) => client.get(`/drafts/${draftId}/revisions`),
  rollback: (draftId, payload) => client.post(`/drafts/${draftId}/rollback`, payload),
  // O-06/O-07：批量应用（服务端只接受 auto_safe）
  batchApply: (draftId, payload) => client.post(`/drafts/${draftId}/batch-apply`, payload),
  // O-05：导出并自动复检
  exportDraft: (draftId) => client.post(`/drafts/${draftId}/export`),
  // O-09：优化前后三类差异对比
  comparison: (draftId) => client.get(`/drafts/${draftId}/comparison`),
  // O-08：依据岗位匹配结果生成定制草稿版本（只重排，不新增事实）
  createTailor: (payload) => client.post("/tailors", payload),
  // 用户自带模型：连接自检（不发简历内容，只探连通性与鉴权）
  testModel: (payload) => client.post("/model-settings/test", payload),
};

// 亮点挖掘接口（FR-09：候选清单 → 追问 → 合成预览 → 确认写入）
export const highlightApi = {
  listCandidates: (resumeId) =>
    client.get(`/resumes/${resumeId}/highlight-candidates`),
  questions: (payload) => client.post("/highlights/questions", payload),
  compose: (payload) => client.post("/highlights/compose", payload),
  confirm: (payload) => client.post("/highlights/confirm", payload),
};

export default client;
