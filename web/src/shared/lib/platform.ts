/**
 * 运行环境抽象(为桌面壳 Tauri 预留防腐缝)。
 * 业务代码经此判断能力, 不直接读 window 专有对象;
 * 桌面壳日后注入原生实现(文件读写 / 离线瓦片), Web 用浏览器默认。
 */
export type Platform = "web" | "desktop";

export function currentPlatform(): Platform {
  // Tauri 注入全局 __TAURI__; 无则为 Web。仅探测存在性, 不耦合具体 API。
  const w = globalThis as Record<string, unknown>;
  return "__TAURI__" in w ? "desktop" : "web";
}

export const isDesktop = (): boolean => currentPlatform() === "desktop";
export const isWeb = (): boolean => currentPlatform() === "web";
