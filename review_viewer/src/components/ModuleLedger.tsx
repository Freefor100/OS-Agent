import type { EvidenceCard, ModuleReview } from "../types";
import { EvidenceChip } from "./MarkdownBody";

type Props = {
  modules: ModuleReview[];
  evidenceById: Map<string, EvidenceCard>;
  onSelectEvidence: (id: string) => void;
};

export function ModuleLedger({ modules, evidenceById, onSelectEvidence }: Props) {
  return (
    <section className="ledger" aria-label="真实工作量模块账本">
      <header className="section-heading">
        <div><span className="section-code">WORK LEDGER</span><h2>模块工作量账本</h2></div>
        <span className="section-count">{modules.length} 个已分析模块</span>
      </header>
      <div className="ledger-table" role="table">
        <div className="ledger-row ledger-labels" role="row">
          <span>模块 / 代码锚点</span><span>实现</span><span>来源归属</span><span>Base 差异</span><span>证据</span>
        </div>
        {modules.map((module) => (
          <div className="ledger-row" role="row" key={module.module_id} id={`module-${module.module_id}`}>
            <div className="module-name"><strong>{module.title}</strong><small>{module.anchors.slice(0, 3).join(" · ") || "未提取公开锚点"}</small></div>
            <span className={`state state-${module.status}`}>{statusLabel(module.status)}</span>
            <span>{originalityLabel(module.originality)}</span>
            <span>{deltaLabel(module.base_delta)}</span>
            <span className="evidence-list">
              {module.evidence_ids.slice(0, 4).map((id) => <EvidenceChip evidence={evidenceById.get(id)} id={id} key={id} onSelect={onSelectEvidence} />)}
            </span>
          </div>
        ))}
      </div>
    </section>
  );
}

function statusLabel(value: string) {
  return ({ implemented: "已实现", partial: "部分实现", minimal: "最小实现", absent: "未实现" } as Record<string, string>)[value] ?? value;
}
function originalityLabel(value: string) {
  return ({ novel: "独立新增", adapted_major: "主要改写", adapted_minor: "局部适配", inherited: "继承", external: "外部模块", uncertain: "不确定" } as Record<string, string>)[value] ?? value;
}
function deltaLabel(value: string) {
  return ({ major: "重大变化", minor: "局部变化", none: "无实质变化", unclear: "无法比较" } as Record<string, string>)[value] ?? value;
}
