import { useQuery } from "@tanstack/react-query";
import { endpoints, queryKeys, type Tract } from "../../shared/api";

// 地块台账: 服务端状态单一真相(TanStack Query)。
export function useTracts() {
  return useQuery<Tract[]>({
    queryKey: queryKeys.tracts,
    queryFn: endpoints.listTracts,
  });
}
