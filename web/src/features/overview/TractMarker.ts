// 倒水滴地块标记(设计层): 构建纯 DOM 元素 + 自行绑定悬停/点击;
// map-core 仅负责将它定位到经纬度(anchor=bottom, 滴尖落地)。
export interface TractMarkerHandlers {
  onClick: () => void;
  onEnter: (rect: DOMRect) => void;
  onLeave: () => void;
}

const PUBLISHED_COLOR = "#1f8f68"; // 已检测
const DRAFT_COLOR = "#c6922e"; // 未检测

export function createTractMarkerElement(
  published: boolean,
  handlers: TractMarkerHandlers,
): HTMLElement {
  const el = document.createElement("div");
  el.style.cursor = "pointer";
  el.style.width = "26px";
  el.style.height = "34px";
  el.style.display = "grid";
  el.style.placeItems = "center";
  const color = published ? PUBLISHED_COLOR : DRAFT_COLOR;
  el.innerHTML =
    '<svg data-marker-glyph="true" width="26" height="34" viewBox="0 0 24 32" xmlns="http://www.w3.org/2000/svg" style="transition: transform 120ms ease; transform-origin: 50% 100%;">' +
    '<path d="M12 0 C5.4 0 0 5.4 0 12 C0 21 12 32 12 32 C12 32 24 21 24 12 C24 5.4 18.6 0 12 0 Z" ' +
    'fill="' +
    color +
    '" stroke="#ffffff" stroke-width="1.5"/>' +
    '<circle cx="12" cy="12" r="4.5" fill="#ffffff"/>' +
    "</svg>";
  el.addEventListener("mouseenter", () => {
    const glyph = el.querySelector<SVGElement>("[data-marker-glyph]");
    if (glyph) glyph.style.transform = "scale(1.15)";
    handlers.onEnter(el.getBoundingClientRect());
  });
  el.addEventListener("mouseleave", () => {
    const glyph = el.querySelector<SVGElement>("[data-marker-glyph]");
    if (glyph) glyph.style.transform = "scale(1)";
    handlers.onLeave();
  });
  el.addEventListener("click", (e) => {
    e.stopPropagation();
    handlers.onClick();
  });
  return el;
}
