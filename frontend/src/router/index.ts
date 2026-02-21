import { createRouter, createWebHistory } from "vue-router";

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: "/",
      name: "analysis",
      component: () => import("@/views/AnalysisView.vue"),
    },
  ],
});

export default router;
