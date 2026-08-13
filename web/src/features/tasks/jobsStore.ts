import { create } from "zustand";
import { persist } from "zustand/middleware";

/**
 * 任务中心的客户端状态：待命队列 + 已提交台账 + 表单草稿。
 *
 * 为什么要持久化(localStorage)：台账页往往有多条「未检测」需要连续补参数，用户会在
 * ledger 与 tasks 之间反复跳转。页面卸载不能丢掉已经攒好的队列和正在填写的参数，
 * 否则「点未检测 → 补参数 → 加入队列 → 回台账 → 点下一条」这条主流程根本走不通。
 */

/** 待命项：一张影像 + 它自己完整的一套推理参数(与后端 BatchInferItem 一一对应)。 */
export interface PendingTask {
  id: string;
  /** 服务器可访问的影像文件路径；与 imageKey 二选一。 */
  inputPath?: string;
  /** 已上传影像的存储 key；与 inputPath 二选一。 */
  imageKey?: string;
  /** 列表展示名(文件名)。 */
  displayName: string;
  /** 完整路径，用于 Tooltip 展示。 */
  fullPath: string;
  /** 是否来自本地上传(上传项无法回填表单，只能删除重来)。 */
  fromUpload: boolean;
  tractId?: string;
  phaseId?: string;
  tileSize?: number;
  /** 0~0.5 的小数，与后端字段同单位。 */
  overlapRate?: number;
  dsm?: string;
  dem?: string;
  las?: string;
  exportFmt?: string;
}

/** 已提交作业：一次提交 = 一个后端作业 = 1~N 条待命项。 */
export interface SubmittedJob {
  jobId: string;
  /** 概述名：单条为文件名，多条为「N 张影像」。 */
  filename: string;
  itemCount: number;
  tractId?: string;
  phaseId?: string;
  submittedAt: number;
}

/** 左侧「推理参数」表单的草稿(跨页面/刷新保持)。 */
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

let idSeed = 0;

/** 生成待命项本地 ID(仅用于列表 key 与增删改定位，不下发后端)。 */
export function newPendingId(): string {
  idSeed += 1;
  return `p_${Date.now().toString(36)}_${idSeed}`;
}

interface JobsState {
  pending: PendingTask[];
  submitted: SubmittedJob[];
  draft: FormDraft;
  /** 最近一次删除的快照，支撑「撤销」；不持久化。 */
  lastRemoved: { task: PendingTask; index: number } | null;

  enqueue: (tasks: PendingTask[]) => void;
  removePending: (id: string) => void;
  undoRemove: () => void;
  movePending: (id: string, direction: -1 | 1) => void;
  clearPending: () => void;
  /** 把待命项弹回左侧表单继续编辑(上传来源的项不支持)。 */
  editPending: (id: string) => void;

  addJob: (job: SubmittedJob) => void;
  clearSubmitted: () => void;

  patchDraft: (patch: Partial<FormDraft>) => void;
  /** 只清空输入项，保留其余参数作为下一张影像的默认值。 */
  clearDraftInput: () => void;
  resetDraft: () => void;
}

function draftFromTask(task: PendingTask): FormDraft {
  return {
    ...EMPTY_DRAFT,
    inputPath: task.inputPath ?? "",
    tractId: task.tractId ?? "",
    phaseId: task.phaseId ?? "",
    tileSize: task.tileSize ?? null,
    overlapPercent:
      typeof task.overlapRate === "number" ? Math.round(task.overlapRate * 100) : null,
    exportFmt: task.exportFmt ?? EMPTY_DRAFT.exportFmt,
    dsmOpen: Boolean(task.dsm),
    dsm: task.dsm ?? "",
    demOpen: Boolean(task.dem),
    dem: task.dem ?? "",
    lasOpen: Boolean(task.las),
    las: task.las ?? "",
  };
}

export const useJobsStore = create<JobsState>()(
  persist(
    (set, get) => ({
      pending: [],
      submitted: [],
      draft: EMPTY_DRAFT,
      lastRemoved: null,

      enqueue: (tasks) =>
        set((s) => (tasks.length ? { pending: [...s.pending, ...tasks] } : s)),

      removePending: (id) =>
        set((s) => {
          const index = s.pending.findIndex((t) => t.id === id);
          if (index < 0) return s;
          return {
            pending: s.pending.filter((t) => t.id !== id),
            lastRemoved: { task: s.pending[index], index },
          };
        }),

      undoRemove: () =>
        set((s) => {
          if (!s.lastRemoved) return s;
          const next = [...s.pending];
          next.splice(Math.min(s.lastRemoved.index, next.length), 0, s.lastRemoved.task);
          return { pending: next, lastRemoved: null };
        }),

      movePending: (id, direction) =>
        set((s) => {
          const index = s.pending.findIndex((t) => t.id === id);
          const target = index + direction;
          if (index < 0 || target < 0 || target >= s.pending.length) return s;
          const next = [...s.pending];
          [next[index], next[target]] = [next[target], next[index]];
          return { pending: next };
        }),

      clearPending: () => set({ pending: [], lastRemoved: null }),

      editPending: (id) => {
        const task = get().pending.find((t) => t.id === id);
        if (!task || task.fromUpload) return;
        set((s) => ({
          pending: s.pending.filter((t) => t.id !== id),
          draft: draftFromTask(task),
          lastRemoved: null,
        }));
      },

      addJob: (job) => set((s) => ({ submitted: [job, ...s.submitted] })),

      clearSubmitted: () => set({ submitted: [] }),

      patchDraft: (patch) => set((s) => ({ draft: { ...s.draft, ...patch } })),

      clearDraftInput: () => set((s) => ({ draft: { ...s.draft, inputPath: "" } })),

      resetDraft: () => set({ draft: EMPTY_DRAFT }),
    }),
    {
      name: "4estds.tasks.queue.v1",
      // lastRemoved 是一次性的撤销缓冲，跨会话恢复毫无意义。
      partialize: (s) => ({ pending: s.pending, submitted: s.submitted, draft: s.draft }),
    },
  ),
);
