import { useQuery } from "@tanstack/react-query";
import {
  endpoints,
  queryKeys,
  type Tract,
  type TractImagery,
  type TractSummary,
  type TiffAsset,
} from "../../shared/api";

// 地块台账: 服务端状态单一真相(TanStack Query)。
export function useTracts() {
  return useQuery<Tract[]>({
    queryKey: queryKeys.tracts,
    queryFn: endpoints.listTracts,
    staleTime: 30_000,
    gcTime: 180_000,
  });
}

export function useTiffs() {
  return useQuery<TiffAsset[]>({
    queryKey: queryKeys.tiffs,
    queryFn: endpoints.listTiffs,
    staleTime: 30_000,
    gcTime: 180_000,
  });
}

// 地块多时相真影像瓦片(无选中地块时不请求)。
export function useTractImagery(
  tractId: string | undefined,
  params?: { phaseId?: string; tiffName?: string },
) {
  const tiffRef = params?.tiffName;
  return useQuery<TractImagery>({
    queryKey: queryKeys.imagery(tractId ?? "", params?.phaseId, tiffRef),
    queryFn: () => endpoints.getImagery(tractId as string, params),
    enabled: Boolean(tractId),
    staleTime: 60_000,
    gcTime: 180_000,
  });
}

export function useTractSummary(tractId: string | undefined) {
  return useQuery<TractSummary>({
    queryKey: queryKeys.tractSummary(tractId ?? ""),
    queryFn: () => endpoints.getTractSummary(tractId as string),
    enabled: Boolean(tractId),
    staleTime: 60_000,
    gcTime: 180_000,
  });
}

export function useTractSummaries(enabled = true) {
  return useQuery<TractSummary[]>({
    queryKey: queryKeys.tractSummaries,
    queryFn: endpoints.listTractSummaries,
    enabled,
    staleTime: 60_000,
    gcTime: 180_000,
  });
}
