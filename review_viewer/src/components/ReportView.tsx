import { ArrowLeft } from "lucide-react";
import { useMemo, useState } from "react";
import type { ReviewReportData, EvidenceCard } from "../types";
import { EvidenceDrawer } from "./EvidenceDrawer";
import { MarkdownBody } from "./MarkdownBody";
import { ModuleLedger } from "./ModuleLedger";

type Props = {
  report: ReviewReportData;
  onBack?: () => void;
};

export function ReportView({ report, onBack }: Props) {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const evidenceById = useMemo(() => new Map(report.evidence.map((item) => [item.evidence_id, item])), [report.evidence]);
  const selectedEvidence: EvidenceCard | null = selectedId ? evidenceById.get(selectedId) ?? null : null;
  const openEvidence = (id: string) => setSelectedId(id.replace(/^@/, ""));
  return (
    <div className="report-shell">
      <aside className="section-nav">
        {onBack && (
          <button className="icon-text" onClick={onBack}>
            <ArrowLeft size={16} /> 返回索引
          </button>
        )}
        <div className="nav-title">章节</div>
        {report.sections.map((section) => (
          <a href={`#${section.id}`} key={section.id}>{section.title}</a>
        ))}
      </aside>
      <main className="report-main">
        <header className="identity-strip">
          <div>
            <div className="eyebrow">评审报告</div>
            <h1>{report.identity.display_name}</h1>
            <p>{report.identity.school} / {report.identity.team}</p>
          </div>
          <div className="identity-flags">
            <span className="badge badge-muted">{report.modules.length} 个模块</span>
            {report.optional_sections.cheat && <span className="badge badge-risk">测试风险</span>}
            {report.optional_sections.ai && <span className="badge badge-risk">AI/历史风险</span>}
          </div>
        </header>
        <ModuleLedger modules={report.modules} onSelectEvidence={openEvidence} />
        {report.sections.map((section) => (
          <section className="report-section" id={section.id} key={section.id}>
            <MarkdownBody markdown={section.markdown} onSelectEvidence={openEvidence} />
          </section>
        ))}
      </main>
      <EvidenceDrawer evidence={selectedEvidence} onClose={() => setSelectedId(null)} />
    </div>
  );
}
