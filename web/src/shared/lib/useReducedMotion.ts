import { useEffect, useState } from "react";

const QUERY = "(prefers-reduced-motion: reduce)";

// 订阅系统“减少动效”偏好。CSS 媒体查询覆盖不到 JS 驱动的动效
// (如定时自动播放), 故以 Hook 形式暴露给组件自行降级。
export function useReducedMotion(): boolean {
  const [reduced, setReduced] = useState<boolean>(() => {
    if (typeof window === "undefined" || !window.matchMedia) return false;
    return window.matchMedia(QUERY).matches;
  });

  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) return;
    const mq = window.matchMedia(QUERY);
    const onChange = () => setReduced(mq.matches);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);

  return reduced;
}
