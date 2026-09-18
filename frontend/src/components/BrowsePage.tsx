import type { ReactNode } from "react";
import { Pagination } from "./Pagination";
import { usePaginated } from "../hooks/usePaginated";
import type { Page } from "../types";

interface BrowsePageProps<T> {
  title: string;
  subtitle?: string;
  backHref?: string;
  filters?: (props: { setPage: (page: number) => void; refetch: () => void }) => ReactNode;
  fetcher: (page: number, pageSize: number) => Promise<Page<T>>;
  /** Serialized active filters; any change resets pagination to page 1. */
  paramsKey: string;
  renderRow: (item: T, ctx: { setPage: (page: number) => void; refetch: () => void }) => ReactNode;
  rowKey: (item: T) => string | number;
  emptyLabel: string;
  listClassName?: string;
  initialPageSize?: number;
}

/**
 * Shared layout for the dedicated "view all" pages: header, filter bar,
 * server-side paginated list, and loading / error / empty states.
 */
export function BrowsePage<T>({
  title,
  subtitle,
  backHref = "/",
  filters,
  fetcher,
  paramsKey,
  renderRow,
  rowKey,
  emptyLabel,
  listClassName = "browse-list",
  initialPageSize = 50,
}: BrowsePageProps<T>) {
  const { data, loading, error, page, pageSize, setPage, setPageSize, refetch } = usePaginated<T>(
    fetcher,
    paramsKey,
    initialPageSize,
  );
  const items = data?.items ?? [];
  const total = data?.total ?? 0;
  const totalPages = data?.total_pages ?? 0;
  const rowCtx = { setPage, refetch };

  return (
    <div className="browse-page">
      <header className="browse-head">
        <a className="back-link" href={`#${backHref}`}>
          ← Dashboard
        </a>
        <div className="browse-heading">
          <h1 className="browse-title">{title}</h1>
          {subtitle && <p className="browse-subtitle">{subtitle}</p>}
        </div>
        <span className="panel-count">{total.toLocaleString()}</span>
      </header>

      {filters && <div className="browse-filters">{filters(rowCtx)}</div>}

      {loading && !data && <div className="browse-status">Loading…</div>}
      {!loading && error && (
        <div className="browse-status browse-error">Failed to load: {error}</div>
      )}
      {!loading && !error && total === 0 && <div className="browse-status">{emptyLabel}</div>}
      {!loading && !error && total > 0 && (
        <>
          <div className={listClassName}>
            {items.map((item) => (
              <div key={rowKey(item)} className="browse-item">
                {renderRow(item, rowCtx)}
              </div>
            ))}
          </div>
          <Pagination
            page={page}
            pageSize={pageSize}
            total={total}
            totalPages={totalPages}
            onPageChange={setPage}
            onPageSizeChange={setPageSize}
          />
        </>
      )}
    </div>
  );
}