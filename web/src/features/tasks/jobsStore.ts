import { create } from "zustand";
import { persist } from "zustand/middleware";

/**
 * 任务中心的客户端状态：已提交作业列表 + 表单草稿。
 *
 * 异步作业直接提交至后端的 Redis 任务队列，客户端仅记录已提交的作业以供队列追踪。
 */

/** 已提交作业：一次提交 = 一个独立的单图推理作业。 */
export interface SubmittedJob {
  jobId: string;
  filename: string;
  fullPath?: string;
  tractId?: string;
  phaseId?: string;
  tileSize?: number | null;
  overlapPercent?: number | null;
  submittedAt: number;
}

/** 左侧「推理参数」表单的草稿。 */
export interface FormDraft {
  inputPath: string;
  tractId: string;
  phaseId: string;
  tileSize: number | null;
  overlapPercent: number | null;
  exportFmt: string;
  dsmOpen: boolean;
  dsm: string;
  demOpen: boolean;
  dem: string;
  lasOpen: boolean;
  las: string;
}

export const EMPTY_DRAFT: FormDraft = {
  inputPath: "",
  tractId: "",
  phaseId: "",
  tileSize: null,
  overlapPercent: null,
  exportFmt: "shp",
  dsmOpen: false,
  dsm: "",
  demOpen: false,
  dem: "",
  lasOpen: false,
  las: "",
};

interface JobsState {
  submitted: SubmittedJob[];
  draft: FormDraft;

  addJob: (job: SubmittedJob) => void;
  clearSubmitted: () => void;

  patchDraft: (patch: Partial<FormDraft>) => void;
  /** 清空输入路径，保留其余参数作为下一次输入的默认值。 */
  clearDraftInput: () => void;
  resetDraft: () => void;
}

export const useJobsStore = create<JobsState>()(
  persist(
    (set) => ({
      submitted: [],
      draft: EMPTY_DRAFT,

      addJob: (job) => set((s) => ({ submitted: [job, ...s.submitted] })),

      clearSubmitted: () => set({ submitted: [] }),

      patchDraft: (patch) => set((s) => ({ draft: { ...s.draft, ...patch } })),

      clearDraftInput: () => set((s) => ({ draft: { ...s.draft, inputPath: "" } })),

      resetDraft: () => set({ draft: EMPTY_DRAFT }),
    }),
    {
      name: "4estds.tasks.queue.v1",
      // 仅持久化已提交作业；表单草稿由路由参数及当前操作驱动，不持久化避免残留污染。
      partialize: (s) => ({ submitted: s.submitted }),
    },
  ),
);
