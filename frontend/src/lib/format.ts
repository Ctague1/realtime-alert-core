export function formatTs(ts: string): string {
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return ts;
  return d.toLocaleTimeString([], { hour12: false });
}

export function ago(ts?: string | null): string {
  if (!ts) return "never";
  const secs = Math.round((Date.now() - Date.parse(ts)) / 1000);
  if (secs < 0) return "now";
  if (secs < 60) return `${secs}s ago`;
  if (secs < 3600) return `${Math.round(secs / 60)}m ago`;
  return `${Math.round(secs / 3600)}h ago`;
}