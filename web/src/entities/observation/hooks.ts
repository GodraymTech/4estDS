import { useQuery } from "@tanstack/react-query";
import {
  endpoints,
  queryKeys,
  type FeatureCollection,
  type GeometryKind,
} from "../../shared/api";

// 某地块的观测要素(单木点/树冠面)。enabled: 无选中地块时不请求。
export function useObservations(
  tractId: string | undefined,
  geometry: GeometryKind,
  options?: { tiffId?: string; phaseId?: string; tiffName?: string },
) {
  return useQuery<FeatureCollection>({
    queryKey: queryKeys.observations(tractId ?? "", geometry, options),
    queryFn: () => endpoints.getObservations(tractId as string, geometry, options),
    enabled: Boolean(tractId),
    staleTime: 30_000,
    gcTime: 60_000,
    structuralSharing: false,
  });
}
