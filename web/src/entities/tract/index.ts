// tract 实体公共出口: 类型 + 查询 hooks(封装服务端状态)。
export type { TiffAsset, Tract, TractImagery, TractSummary } from "../../shared/api";
export { useTiffs, useTracts, useTractImagery, useTractSummary, useTractSummaries } from "./hooks";
