import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { endpoints, queryKeys } from "../../shared/api";
import type { EffectiveAreaImportSource, EffectiveAreaPutRequest } from "../../shared/api";

export function useEffectiveArea(tractPk?: string) {
  return useQuery({
    queryKey: queryKeys.effectiveArea(tractPk ?? ""),
    queryFn: () => endpoints.getEffectiveArea(tractPk as string),
    enabled: Boolean(tractPk),
  });
}

export function useSaveEffectiveArea(tractPk: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: EffectiveAreaPutRequest) => endpoints.putEffectiveArea(tractPk, body),
    onSuccess: (data) => {
      queryClient.setQueryData(queryKeys.effectiveArea(tractPk), data);
      void queryClient.invalidateQueries({ queryKey: queryKeys.tracts });
      void queryClient.invalidateQueries({ queryKey: queryKeys.assets });
      void queryClient.invalidateQueries({ queryKey: queryKeys.tractSummaries });
    },
  });
}

export function inspectEffectiveAreaImport(tractPk: string, source: EffectiveAreaImportSource) {
  return endpoints.inspectEffectiveAreaImport(tractPk, source);
}
