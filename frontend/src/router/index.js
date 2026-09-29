import { createRouter, createWebHistory } from "vue-router";

const routes = [
  { path: "/", redirect: "/upload" },
  { path: "/upload", name: "upload", component: () => import("../views/UploadPage.vue") },
  { path: "/resumes", name: "resumes", component: () => import("../views/ResumeListPage.vue") },
  {
    path: "/resumes/:id/structure",
    name: "structure",
    component: () => import("../views/ResultPage.vue"),
  },
  {
    path: "/resumes/:id/diagnose",
    name: "diagnose",
    component: () => import("../views/DiagnosePage.vue"),
  },
  {
    path: "/resumes/:id/draft",
    name: "draft",
    component: () => import("../views/DraftPage.vue"),
  },
  {
    path: "/resumes/:id/highlight",
    name: "highlight",
    component: () => import("../views/HighlightPage.vue"),
  },
];

export default createRouter({
  history: createWebHistory(),
  routes,
});
