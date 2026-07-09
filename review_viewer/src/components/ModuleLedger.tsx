import type { ModuleReview } from "../types";

type Props = {
  modules: ModuleReview[];
  onSelectEvidence: (id: string) => void;
};

export function ModuleLedger({ modules, onSelectEvidence }: Props) {
  return (
    <section className="module-ledger" aria-label="模块账本">
      <div className="ledger-head">
        <h2>真实工作账本</h2>
        <span>{modules.length} 个核心模块</span>
      </div>
      <div className="ledger-grid">
        {modules.map((module) => (
          <article className="module-row" key={module.module_id}>
            <div>
              <h3>{module.title}</h3>
              <p>{module.anchors.slice(0, 4).join(" / ")}</p>
            </div>
            <div className="module-state">
              <span className={`badge status-${module.status}`}>{module.status}</span>
              <span className="badge badge-muted">{module.originality}</span>
              <span className="badge badge-delta">{module.base_delta}</span>
            </div>
            <div className="evidence-list">
              {module.evidence_ids.map((id) => (
                <button className="evidence-chip" key={id} onClick={() => onSelectEvidence(id)}>
                  @{id}
                </button>
              ))}
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}
