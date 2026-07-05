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
) {
  return useQuery<FeatureCollection>({
    queryKey: queryKeys.observations(tractId ?? "", geometry),
    queryFn: () => endpoints.getObservations(tractId as string, geometry),
    enabled: Boolean(tractId),
    staleTime: 15_000,
    gcTime: 45_000,
    structuralSharing: false,
  });
}
