export function formatAreaValue(m2: number | null | undefined): string {
  if (typeof m2 !== "number" || !Number.isFinite(m2) || m2 <= 0) return "-";
  if (m2 >= 1_000_000) return trimFixed(m2 / 1_000_000, 3) + " km\u00b2";
  if (m2 >= 10_000) return trimFixed(m2 / 10_000, 3) + " hm\u00b2";
  if (m2 >= 1) return trimFixed(m2, 2) + " m\u00b2";
  if (m2 >= 0.01) return trimFixed(m2, 3) + " m\u00b2";
  return m2.toExponential(2) + " m\u00b2";
}

function trimFixed(value: number, digits: number): string {
  return value.toLocaleString(undefined, {
    minimumFractionDigits: 0,
    maximumFractionDigits: digits,
  });
}
