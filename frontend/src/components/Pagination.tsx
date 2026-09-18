interface Props {
  page: number;
  pageSize: number;
  total: number;
  totalPages: number;
  onPageChange: (page: number) => void;
  onPageSizeChange: (size: number) => void;
  pageSizeOptions?: number[];
}

export function Pagination({
  page,
  pageSize,
  total,
  totalPages,
  onPageChange,
  onPageSizeChange,
  pageSizeOptions = [25, 50, 100],
}: Props) {
  if (total === 0) return null;
  const from = (page - 1) * pageSize + 1;
  const to = Math.min(page * pageSize, total);
  const window = pageWindow(page, totalPages);

  return (
    <div className="pagination">
      <span className="page-info">
        Showing {from.toLocaleString()}–{to.toLocaleString()} of {total.toLocaleString()}
      </span>
      <div className="page-controls">
        <button
          className="page-btn"
          disabled={page <= 1}
          onClick={() => onPageChange(page - 1)}
          aria-label="Previous page"
        >
          ‹ Prev
        </button>
        {window.map((p, i) =>
          p === "…" ? (
            <span key={`gap-${i}`} className="page-gap">
              …
            </span>
          ) : (
            <button
              key={p}
              className={`page-btn ${p === page ? "active" : ""}`}
              onClick={() => onPageChange(p)}
              aria-label={`Page ${p}`}
              aria-current={p === page ? "page" : undefined}
            >
              {p}
            </button>
          ),
        )}
        <button
          className="page-btn"
          disabled={page >= totalPages}
          onClick={() => onPageChange(page + 1)}
          aria-label="Next page"
        >
          Next ›
        </button>
        <label className="page-size">
          <span>Rows</span>
          <select value={pageSize} onChange={(e) => onPageSizeChange(Number(e.target.value))}>
            {pageSizeOptions.map((size) => (
              <option key={size} value={size}>
                {size}
              </option>
            ))}
          </select>
        </label>
      </div>
    </div>
  );
}

function pageWindow(current: number, total: number): (number | "…")[] {
  if (total <= 7) return Array.from({ length: total }, (_, i) => i + 1);
  const wanted = new Set([1, 2, current - 1, current, current + 1, total - 1, total]);
  const pages = [...wanted].filter((p) => p >= 1 && p <= total).sort((a, b) => a - b);
  const out: (number | "…")[] = [];
  let prev = 0;
  for (const p of pages) {
    if (prev && p - prev > 1) out.push("…");
    out.push(p);
    prev = p;
  }
  return out;
}