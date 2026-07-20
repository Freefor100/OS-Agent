import { ArrowLeft, Boxes, Database, FileSearch, GitCompareArrows, Network, ShieldAlert } from "lucide-react";
import { useMemo, useState } from "react";
import type { ReviewReportData, EvidenceCard, EvidenceReference, ModuleReview, ReportSection } from "../types";
import { EvidenceDrawer } from "./EvidenceDrawer";
import { MarkdownBody } from "./MarkdownBody";
import { ModuleLedger } from "./ModuleLedger";

type Props = { report: ReviewReportData; onBack?: () => void };
type ViewId = "overview" | "lineage" | "architecture" | "risk" | "modules" | "evidence";

const VIEW_DEFS: Array<{ id: ViewId; label: string; titles: string[]; icon: typeof FileSearch }> = [
  { id: "overview", label: "总览", titles: ["整体结论", "重点结论"], icon: FileSearch },
  { id: "lineage", label: "来源与工作量", titles: ["真实工作量分层", "Base、其他来源与同届传播关系"], icon: GitCompareArrows },
  { id: "architecture", label: "内核架构", titles: ["内核架构图"], icon: Network },
  { id: "risk", label: "声明与风险", titles: ["文档声明审查", "开发历史与 AI 使用", "测评定向与结果真实性"], icon: ShieldAlert },
  { id: "modules", label: "模块实现", titles: ["模块实现细节及 Base 差异"], icon: Boxes },
  { id: "evidence", label: "证据索引", titles: ["证据索引"], icon: Database }
];

export function ReportView({ report, onBack }: Props) {
  const views = useMemo(() => VIEW_DEFS.map((view) => ({ ...view, sections: report.sections.filter((section) => view.titles.includes(section.title)) })).filter((view) => view.sections.length), [report.sections]);
  const requestedView = window.location.hash.slice(1) as ViewId;
  const [active, setActive] = useState<ViewId>(views.some((view) => view.id === requestedView) ? requestedView : (views[0]?.id ?? "overview"));
  const [selectedId, setSelectedId] = useState<string | null>(new URLSearchParams(window.location.search).get("evidence"));
  const evidenceById = useMemo(() => new Map(report.evidence.map((item) => [item.evidence_id, item])), [report.evidence]);
  const selectedEvidence: EvidenceCard | null = selectedId ? evidenceById.get(selectedId) ?? null : null;
  const current = views.find((view) => view.id === active) ?? views[0];
  const navigateReference = (reference: EvidenceReference) => {
    const nextView = views.some((view) => view.id === reference.view) ? reference.view as ViewId : "overview";
    setSelectedId(null);
    setActive(nextView);
    history.replaceState(null, "", `#${nextView}`);
    window.setTimeout(() => document.getElementById(reference.anchor)?.scrollIntoView({ behavior: "smooth", block: "start" }), 40);
  };
  return (
    <div className="report-app">
      <header className="topbar">
        <div className="product-mark"><span className="mark-glyph">OS</span><span><strong>分析比对智能体</strong><small>源码评审工作台</small></span></div>
        <div className="topbar-actions">
          <span className="version-lock">报告已锁定 · {report.evidence.length} 条证据</span>
          {onBack && <button className="icon-text" onClick={onBack}><ArrowLeft size={16} />返回索引</button>}
        </div>
      </header>

      <div className="source-rail" aria-label="Base 到目标作品的来源轨迹">
        <div className="rail-node rail-base"><span>BASE</span><strong>{report.base.status === "accepted" ? report.base.display_name : "无可靠 Base"}</strong><small>{shortCommit(report.base.commit) || report.base.status}</small></div>
        <div className="rail-link"><span>引入 / 适配</span><i /></div>
        <div className="rail-node rail-target"><span>TARGET</span><strong>{report.identity.display_name}</strong><small>{report.identity.school} · {report.identity.team}</small></div>
        <div className="rail-link"><span>代码增量</span><i /></div>
        <div className="rail-node rail-delta"><span>REVIEW</span><strong>{report.modules.length} 个模块</strong><small>{report.base.direction || "自身实现分析"}</small></div>
      </div>

      <div className="report-layout">
        <nav className="view-nav" aria-label="报告视图">
          <div className="nav-caption">阅读视图</div>
          {views.map(({ id, label, icon: Icon }) => (
            <button key={id} className={active === id ? "active" : ""} onClick={() => { setActive(id); history.replaceState(null, "", `#${id}`); }} title={label}>
              <Icon size={17} /><span>{label}</span>
            </button>
          ))}
          <div className="nav-rule" />
          <div className="nav-meta"><span>证据覆盖</span><strong>{report.evidence.length}</strong></div>
          <div className="nav-meta"><span>公开专题</span><strong>{Number(report.optional_sections.doc_claim) + Number(report.optional_sections.cheat) + Number(report.optional_sections.ai)}</strong></div>
        </nav>

        <main className="report-main">
          <header className="report-heading">
            <span className="section-code">{current?.id.toUpperCase()}</span>
            <h1>{current?.label}</h1>
            <p>{viewDescription(current?.id)}</p>
          </header>
          {current?.id === "overview" && <ModuleLedger modules={report.modules} evidenceById={evidenceById} onSelectEvidence={setSelectedId} />}
          {current?.sections.map((section) => <ReportSectionBlock key={section.id} section={section} evidenceById={evidenceById} onEvidence={setSelectedId} />)}
          {current?.id === "modules" && <ModuleFragments modules={report.modules} evidenceById={evidenceById} onEvidence={setSelectedId} />}
        </main>

        <EvidenceDrawer evidence={selectedEvidence} total={report.evidence.length} onClose={() => setSelectedId(null)} onNavigate={navigateReference} />
      </div>
      {selectedEvidence && <button className="drawer-backdrop" aria-label="关闭证据" onClick={() => setSelectedId(null)} />}
    </div>
  );
}

function ReportSectionBlock({ section, evidenceById, onEvidence }: { section: ReportSection; evidenceById: Map<string, EvidenceCard>; onEvidence: (id: string) => void }) {
  const body = section.markdown.replace(/^##\s+[^\n]+\n?/, "").trim();
  return <section className="document-section" id={section.id}><div className="section-marker"><span>{String(section.evidence_ids.length).padStart(2, "0")}</span><small>引用</small></div><article><h2>{section.title}</h2><MarkdownBody markdown={body} evidenceById={evidenceById} onSelectEvidence={onEvidence} /></article></section>;
}

function ModuleFragments({ modules, evidenceById, onEvidence }: { modules: ModuleReview[]; evidenceById: Map<string, EvidenceCard>; onEvidence: (id: string) => void }) {
  return <section className="module-fragments" aria-label="模块分析片段">
    <header className="section-heading"><div><span className="section-code">MODULE SOURCES</span><h2>模块分析片段</h2></div><span className="section-count">{modules.length} 个模块</span></header>
    {modules.map((module) => <article className="module-fragment" id={`module-${module.module_id}`} key={module.module_id}>
      <header><div><span>{statusLabel(module.status)}</span><span>{originalityLabel(module.originality)}</span><span>{deltaLabel(module.base_delta)}</span></div><h3>{module.title}</h3></header>
      <MarkdownBody markdown={module.markdown.replace(/^#\s+[^\n]+\n?/, "").trim()} evidenceById={evidenceById} onSelectEvidence={onEvidence} />
    </article>)}
  </section>;
}

function shortCommit(value: string) { return value ? value.slice(0, 10) : ""; }
function statusLabel(value: string) { return ({ implemented: "已实现", partial: "部分实现", minimal: "最小实现", absent: "未实现" } as Record<string, string>)[value] ?? value; }
function originalityLabel(value: string) { return ({ novel: "独立新增", adapted_major: "主要改写", adapted_minor: "局部适配", inherited: "继承", external: "外部模块", uncertain: "不确定" } as Record<string, string>)[value] ?? value; }
function deltaLabel(value: string) { return ({ major: "重大变化", minor: "局部变化", none: "无实质变化", unclear: "无法比较" } as Record<string, string>)[value] ?? value; }
function viewDescription(id?: ViewId) {
  return ({ overview: "先看整体判断与需要评委关注的结论。", lineage: "追溯主骨架来源，并分层核算选手的真实增量。", architecture: "从实际代码关系重建内核对象、控制流与依赖边界。", risk: "只展示已有公开 finding，不用空章节稀释重点。", modules: "逐模块解释实现机制，以及相对 Base 的继承、适配、新增与缺失。", evidence: "从结论返回源码、提交、文档和比较事实。" } as Record<ViewId, string>)[id ?? "overview"];
}
