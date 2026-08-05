import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { endpoints, queryKeys } from "../../shared/api";
import type { ReviewMode, ReviewPatch } from "../../shared/api";

export function useReviews() {
  return useQuery({ queryKey: queryKeys.reviews, queryFn: () => endpoints.listReviews() });
}

export function useReview(sessionId: string) {
  return useQuery({ queryKey: queryKeys.review(sessionId), queryFn: () => endpoints.getReview(sessionId), enabled: Boolean(sessionId) });
}

export function useReviewWorkspace(sessionId: string) {
  return useQuery({
    queryKey: queryKeys.reviewWorkspace(sessionId),
    queryFn: () => endpoints.getReviewWorkspace(sessionId),
    enabled: Boolean(sessionId),
  });
}

export function useCreateReview() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: { phase_id: string; tiff_id: string; mode: ReviewMode }) => endpoints.createReview(body),
    onSuccess: () => void client.invalidateQueries({ queryKey: queryKeys.reviews }),
  });
}

export function useDeleteReview() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (sessionId: string) => endpoints.deleteReview(sessionId),
    onSuccess: () => void client.invalidateQueries({ queryKey: queryKeys.reviews }),
  });
}

export function useReviewCommand(sessionId: string) {
  const client = useQueryClient();
  const sync = (patch: ReviewPatch) => {
    client.setQueryData(queryKeys.reviewWorkspace(sessionId), (current: unknown) => ({
      ...(current as Record<string, unknown> ?? {}),
      revision: patch.revision,
      items: patch.items,
    }));
    void client.invalidateQueries({ queryKey: queryKeys.review(sessionId) });
  };
  return useMutation({
    mutationFn: (body: { revision: number; operation_id: string; operations: Array<Record<string, unknown>> }) =>
      endpoints.applyReviewOperations(sessionId, body),
    onSuccess: sync,
  });
}

export function operationId(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}
