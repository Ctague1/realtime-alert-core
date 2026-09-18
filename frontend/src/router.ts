import { useEffect, useState } from "react";

export interface Route {
  /** Normalized path, e.g. "/" or "/alarms". */
  path: string;
  /** Query params parsed from the hash, e.g. #/alarms?status=active. */
  params: URLSearchParams;
}

function parseHash(): Route {
  const raw = window.location.hash.replace(/^#/, "");
  const [path, query] = raw.split("?");
  const normalized = path.startsWith("/") ? path : `/${path}`;
  return {
    path: normalized === "" ? "/" : normalized,
    params: new URLSearchParams(query ?? ""),
  };
}

/** React hook that re-renders on hash changes (hash-based routing). */
export function useHashRoute(): Route {
  const [route, setRoute] = useState<Route>(parseHash);
  useEffect(() => {
    const onChange = () => setRoute(parseHash());
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return route;
}

/** Navigate to a hash route, e.g. setHash("/alarms"). */
export function setHash(path: string): void {
  const target = `#${path.startsWith("/") ? path : `/${path}`}`;
  if (window.location.hash === target) return;
  window.location.hash = target;
}