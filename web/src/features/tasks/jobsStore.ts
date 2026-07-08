import { create } from "zustand";

// 已提交作业的客户端台账(后端无 GET /jobs 列表端点, 故跨页保留在 store)。
// 刷新页面会清空(P2: 后端提供作业列表后改为服务端真相)。
export interface SubmittedJob {
  jobId: string;
  filename: string;
  sourceKind?: "file" | "directory" | "upload";
  tractId?: string;
  phaseId?: string;
  submittedAt: number;
}

interface JobsState {
  jobs: SubmittedJob[];
  addJob: (job: SubmittedJob) => void;
  clear: () => void;
}

export const useJobsStore = create<JobsState>((set) => ({
  jobs: [],
  addJob: (job) => set((s) => ({ jobs: [job, ...s.jobs] })),
  clear: () => set({ jobs: [] }),
}));
