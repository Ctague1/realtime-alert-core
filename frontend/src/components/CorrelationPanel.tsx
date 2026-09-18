import type { Correlation } from "../types";
import { CorrelationRow } from "./CorrelationRow";

const PREVIEW_COUNT = 5;

interface Props {
  correlations: Correlation[];
  /** True count of correlations, from /stats. */
  total: number;
  viewAllHref: string;
}

export function CorrelationPanel({ correlations, total, viewAllHref }: Props) {
  const shown = correlations.slice(0, PREVIEW_COUNT);

  return (
    <section className="panel correlation-panel">
      <div className="panel-head">
        <h2 className="panel-title">Correlations & escalations</h2>
        <span className="panel-count">{total.toLocaleString()}</span>
      </div>
      {total === 0 && <div className="empty">No patterns detected yet.</div>}
      {total > 0 && (
        <div className="correlation-list">
          {shown.map((c) => (
            <CorrelationRow key={c.correlation_id} correlation={c} />
          ))}
        </div>
      )}
      {total > PREVIEW_COUNT && (
        <a className="panel-more" href={viewAllHref}>
          View all {total.toLocaleString()} correlations
        </a>
      )}
    </section>
  );
}