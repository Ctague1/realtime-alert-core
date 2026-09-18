import { useCallback, useEffect, useRef, useState } from "react";
import type { Page } from "../types";

export interface UsePaginatedResult<T> {
  data: Page<T> | null;
  loading: boolean;
  error: string | null;
  page: number;
  pageSize: number;
  setPage: (page: number) => void;
  setPageSize: (size: number) => void;
  refetch: () => void;
}

/**
 * Server-side pagination state. Re-fetches whenever ``page``, ``pageSize``
 * or ``paramsKey`` change; a change in ``paramsKey`` (i.e. filters) resets
 * back to page 1 without issuing a redundant request for the stale page.
 */
export function usePaginated<T>(
  fetcher: (page: number, pageSize: number) => Promise<Page<T>>,
  paramsKey: string,
  initialPageSize = 50,
): UsePaginatedResult<T> {
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(initialPageSize);
  const [data, setData] = useState<Page<T> | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);

  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;
  const lastKeyRef = useRef(paramsKey);

  useEffect(() => {
    const keyChanged = lastKeyRef.current !== paramsKey;
    lastKeyRef.current = paramsKey;
    if (keyChanged && page !== 1) {
      // Filters changed while on a later page: reset to page 1 (the state
      // update below triggers a single fetch for the new page).
      setPage(1);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    (async () => {
      try {
        const result = await fetcherRef.current(page, pageSize);
        if (!cancelled) setData(result);
      } catch (err) {
        if (!cancelled) setError(String(err));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [page, pageSize, paramsKey, refreshKey]);

  // Keep the current page valid when the result set shrinks.
  useEffect(() => {
    if (!data) return;
    if (data.total_pages === 0) {
      if (page !== 1) setPage(1);
      return;
    }
    if (page > data.total_pages) setPage(data.total_pages);
  }, [data, page]);

  const refetch = useCallback(() => setRefreshKey((k) => k + 1), []);
  return { data, loading, error, page, pageSize, setPage, setPageSize, refetch };
}