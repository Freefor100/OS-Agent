import { useEffect, useRef, useState, type MouseEvent, type WheelEvent } from "react";
import mermaid from "mermaid";

type AnyRecord = Record<string, any>;

type ReportData = {
  report: AnyRecord;
  taxonomy: {
    modules: Array<{ id: string; title: string; nodeIds: string[]; scope: string }>;
    nodes: Record<string, { id: string; title: string; scope: string }>;
  };
  labels: AnyRecord;
  projectMeta: Array<{ label: string; value: string }>;
  projectProfile: AnyRecord;
  evidenceLabels: Record<string, string>;
  evidence: Record<string, AnyRecord>;
};

const DATA = readReportData();
const report = DATA.report;
const taxonomy = DATA.taxonomy;
const labels = DATA.labels;
const claims = new Map<string, AnyRecord>((report.claims || []).map((claim: AnyRecord) => [claim.claim_id, claim]));
const nodeReviews = new Map<string, AnyRecord>((report.node_reviews || []).map((review: AnyRecord) => [review.node_id, review]));
const moduleReviews = new Map<string, AnyRecord>((report.module_reviews || []).map((review: AnyRecord) => [review.module_id, review]));

function readReportData(): ReportData {
  const element = document.getElementById("report-data");
  if (!element?.textContent) throw new Error("missing embedded report data");
  return JSON.parse(element.textContent) as ReportData;
}

function textValue(value: unknown): string {
  return Array.isArray(value) ? value.join(" ") : String(value ?? "");
}

function shortText(value: unknown, limit: number): string {
  const text = String(value || "").replace(/\s+/g, " ").trim();
  return text.length <= limit ? text : `${text.slice(0, limit - 1)}...`;
}

function titleOf(id: string): string {
  return taxonomy.nodes[id]?.title || taxonomy.modules.find((module) => module.id === id)?.title || id;
}

function scopeOf(id: string): string {
  return taxonomy.nodes[id]?.scope || taxonomy.modules.find((module) => module.id === id)?.scope || "";
}

function claimList(ids: string[] | undefined): AnyRecord[] {
  return (ids || []).map((id) => claims.get(id)).filter(Boolean) as AnyRecord[];
}

function moduleNodes(moduleId: string): string[] {
  return taxonomy.modules.find((module) => module.id === moduleId)?.nodeIds || [];
}

function uniqueClaims(rows: AnyRecord[]): AnyRecord[] {
  const seen = new Set<string>();
  return rows.filter((claim) => {
    if (!claim || seen.has(claim.claim_id)) return false;
    seen.add(claim.claim_id);
    return true;
  });
}

function moduleStats(moduleId: string) {
  const nodes = moduleNodes(moduleId);
  let complete = 0;
  let partial = 0;
  let absent = 0;
  let independent = 0;
  let directEvidence = 0;
  for (const nodeId of nodes) {
    const review = nodeReviews.get(nodeId);
    if (!review) continue;
    const impl = review.implementation_degree?.level;
    const orig = review.originality?.level;
    if (impl === "complete") complete += 1;
    else if (["partial", "minimal", "unknown"].includes(impl)) partial += 1;
    else absent += 1;
    if (["independent", "substantial_rework"].includes(orig)) independent += 1;
    if (claimList(review.claim_ids).some((claim) => (claim.evidence_ids || []).length)) directEvidence += 1;
  }
  return { complete, partial, absent, independent, directEvidence, total: nodes.length };
}

function moduleEvidenceIds(moduleId: string): string[] {
  const review = moduleReviews.get(moduleId) || {};
  const ids: string[] = [];
  const add = (id: string) => {
    if (id && DATA.evidence[id] && !ids.includes(id)) ids.push(id);
  };
  for (const chain of review.key_chains || []) for (const id of chain.evidence_ids || []) add(id);
  for (const claim of claimList(review.featured_claim_ids)) for (const id of claim.evidence_ids || []) add(id);
  for (const nodeId of moduleNodes(moduleId)) {
    const nodeReview = nodeReviews.get(nodeId) || {};
    for (const claim of claimList(nodeReview.claim_ids)) for (const id of claim.evidence_ids || []) add(id);
  }
  return ids;
}

function evidenceIdsFromClaims(rows: AnyRecord[]): string[] {
  const ids: string[] = [];
  for (const claim of rows) {
    for (const id of claim.evidence_ids || []) {
      if (id && DATA.evidence[id] && !ids.includes(id)) ids.push(id);
    }
  }
  return ids;
}

function nodeEvidenceIds(nodeId: string): string[] {
  const review = nodeReviews.get(nodeId) || {};
  const nodeClaims = uniqueClaims([...claimList(review.claim_ids), ...[...claims.values()].filter((claim) => claim.node_id === nodeId)]);
  return evidenceIdsFromClaims(nodeClaims);
}

function stripMermaidFence(value: unknown): string {
  const text = String(value || "").trim();
  if (!text.startsWith("```")) return text;
  const lines = text.split(/\r?\n/);
  if (lines[0]?.trim().toLowerCase().match(/^```(mermaid|mmd)?$/)) lines.shift();
  if (lines[lines.length - 1]?.trim() === "```") lines.pop();
  return lines.join("\n").trim();
}

function TextBlock({ value, className = "" }: { value: unknown; className?: string }) {
  if (Array.isArray(value)) {
    const rows = value.filter((row) => String(row ?? "").trim());
    if (!rows.length) return <p className="muted">未填写。</p>;
    return <ul className={`text-list ${className}`}>{rows.map((row, index) => <li key={index}>{String(row)}</li>)}</ul>;
  }
  return <div className={`text-block ${className}`}><p>{String(value ?? "")}</p></div>;
}

export default function App() {
  const [view, setView] = useState(initialView);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [expandedModules, setExpandedModules] = useState<Set<string>>(() => new Set([initialModuleFromView(initialView())]));

  const openView = (nextView: string) => {
    setView(nextView);
    const moduleId = initialModuleFromView(nextView);
    if (moduleId) {
      setExpandedModules((current) => {
        const next = new Set(current);
        next.add(moduleId);
        return next;
      });
    }
    setSidebarOpen(false);
    history.replaceState(null, "", nextView === "overview" ? "#overview" : `#${nextView.replace(":", "=")}`);
  };

  useEffect(() => {
    mermaid.initialize({ startOnLoad: false, securityLevel: "strict", theme: "default" });
    mermaid.run({ querySelector: ".mermaid" }).catch((error) => console.warn("Mermaid render failed", error));
  }, [view]);

  return (
    <>
      <div className="mobile-topbar">
        <button onClick={() => setSidebarOpen(!sidebarOpen)}>目录</button>
        <strong>{report.work.display_name} 评审报告</strong>
      </div>
      <div className="shell">
        <Sidebar
          view={view}
          openView={openView}
          sidebarOpen={sidebarOpen}
          expandedModules={expandedModules}
          setExpandedModules={setExpandedModules}
        />
        <main className="main"><div className="page"><Page view={view} openView={openView} /></div></main>
      </div>
    </>
  );
}

function Sidebar({ view, openView, sidebarOpen, expandedModules, setExpandedModules }: AnyRecord) {
  return (
    <aside className={`sidebar ${sidebarOpen ? "open" : ""}`}>
      <div className="brand">
        <h1 className="brand-title">{report.work.display_name} 评审报告</h1>
        <p className="brand-subtitle">来源关系、完整度、原创度与关键证据</p>
      </div>
      <button className={`nav-button ${view === "overview" ? "active" : ""}`} onClick={() => openView("overview")}>总体结果与架构</button>
      {taxonomy.modules.filter((module) => module.id !== "Metadata").map((module) => (
        <ModuleNav
          key={module.id}
          module={module}
          view={view}
          openView={openView}
          expandedModules={expandedModules}
          setExpandedModules={setExpandedModules}
        />
      ))}
      <a className="appendix-link" href={report.provenance_href || "provenance.html"} target="_blank">打开函数级技术溯源附录</a>
    </aside>
  );
}

function ModuleNav({ module, view, openView, expandedModules, setExpandedModules }: AnyRecord) {
  const stats = moduleStats(module.id);
  const nodeButtons = module.nodeIds.map((nodeId: string) => {
    const nodeReview = nodeReviews.get(nodeId) || {};
    const impl = nodeReview.implementation_degree?.level || "unknown";
    const orig = nodeReview.originality?.level || "unknown";
    return (
      <button key={nodeId} className={`node-button ${view === `node:${nodeId}` ? "active" : ""}`} onClick={() => openView(`node:${nodeId}`)}>
        <span className="node-title">{titleOf(nodeId)}</span>
        <span className="mini-row"><span className="mini">完整度：{labels.implementation[impl] || impl}</span><span className="mini orig">原创度：{labels.originality[orig] || orig}</span></span>
      </button>
    );
  });
  const open = expandedModules.has(module.id);
  const toggle = (event: MouseEvent<HTMLButtonElement>) => {
    event.stopPropagation();
    const next = new Set(expandedModules);
    if (next.has(module.id)) next.delete(module.id);
    else next.add(module.id);
    setExpandedModules(next);
  };
  return (
    <section className={`module ${open ? "open" : ""}`}>
      <div className={`module-button ${view === `module:${module.id}` ? "active" : ""}`}>
        <button className="module-toggle" type="button" onClick={toggle} aria-label={open ? "折叠模块" : "展开模块"}>{open ? "▾" : "▸"}</button>
        <button className="module-main" type="button" onClick={() => openView(`module:${module.id}`)}>
          <span className="module-name">{module.title}</span><span className="module-kpi">完成度 {stats.complete}/{stats.total}</span>
        </button>
      </div>
      <div className="node-list">{nodeButtons}</div>
    </section>
  );
}

function Page({ view, openView }: AnyRecord) {
  if (view === "overview") return <OverviewPage openView={openView} />;
  if (view.startsWith("module:")) return <ModulePage moduleId={view.slice(7)} openView={openView} />;
  if (view.startsWith("node:")) return <NodePage nodeId={view.slice(5)} />;
  return <OverviewPage openView={openView} />;
}

function OverviewPage({ openView }: AnyRecord) {
  const assessment = report.overall_assessment || {};
  return (
    <section>
      <div className="eyebrow">评委评审</div>
      <h1 className="title">{report.work.display_name} 内核实现评审报告</h1>
      <MetaGrid />
      <article className="hero-card">
        <h2>总体结论</h2>
        <TextBlock value={assessment.summary} className="lead" />
      </article>
      <div className="grid">
        <article className="card"><h2>来源与演进结论</h2><TextBlock value={assessment.source_relation} /></article>
        <article className="card"><h2>风险、缺失与不确定项</h2><TextBlock value={assessment.incomplete_or_risks} /></article>
      </div>
      <div className="summary-list">
        <SummaryCard title="主要继承部分" value={assessment.main_inherited} />
        <SummaryCard title="实质性修改部分" value={assessment.main_modified} />
        <SummaryCard title="相对独立实现部分" value={assessment.main_independent} />
        <SummaryCard title="报告生成依据" value={assessment.review_focus} />
      </div>
      <h2 className="section-title">内核架构图</h2>
      <ArchitectureView assessment={assessment} />
      <h2 className="section-title">代码语言与目录结构</h2>
      <article className="card"><ProjectProfileView /></article>
      <h2 className="section-title">框架实现度与原创度总览</h2>
      <div className="matrix">
        {taxonomy.modules.filter((module) => module.id !== "Metadata").map((module) => {
          const stats = moduleStats(module.id);
          const review = moduleReviews.get(module.id) || {};
          return (
            <article key={module.id} className="matrix-card" onClick={() => openView(`module:${module.id}`)}>
              <strong>{module.title}</strong>
              <TextBlock value={review.overview} />
              <div className="stat-row">
                <span className="status complete">完整 {stats.complete}</span>
                <span className="status partial">部分 {stats.partial}</span>
                <span className="status absent">缺失/不适用 {stats.absent}</span>
                <span className="status evidence">证据 {stats.directEvidence}</span>
              </div>
            </article>
          );
        })}
      </div>
    </section>
  );
}

function SummaryCard({ title, value }: { title: string; value: unknown }) {
  return <article className="summary-card"><h3>{title}</h3><TextBlock value={value} /></article>;
}

function MetaGrid() {
  return <div className="meta-grid">{(DATA.projectMeta || []).map((row) => <div key={row.label} className="meta-card"><span>{row.label}</span><strong>{row.value || "未知"}</strong></div>)}</div>;
}

function ProjectProfileView() {
  const profile = DATA.projectProfile || {};
  return (
    <>
      <div className="profile-grid">
        <div>
          <h3>语言/文件类型占比</h3>
          <LanguageBar rows={profile.languages || []} />
        </div>
        <div>
          <h3>目录结构</h3>
          <DirectoryTree node={profile.directoryTree} root />
        </div>
      </div>
    </>
  );
}

function LanguageBar({ rows }: { rows: AnyRecord[] }) {
  if (!rows.length) return <p className="muted">未能读取快照语言统计。</p>;
  const colors = ["#3572a5", "#89e051", "#dea584", "#6e4c13", "#f1e05a", "#e34c26", "#563d7c", "#9cdcfe"];
  return (
    <div className="language-panel">
      <div className="language-strip">
        {rows.map((row, index) => <span key={row.name} style={{ width: `${Number(row.percent).toFixed(1)}%`, background: colors[index % colors.length] }} />)}
      </div>
      <div className="language-legend">
        {rows.map((row, index) => (
          <div key={row.name} className="language-item">
            <span className="dot" style={{ background: colors[index % colors.length] }} />
            <strong>{row.name}</strong>
            <span>{Number(row.percent).toFixed(1)}%</span>
            <span>{row.files} 文件</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function DirectoryTree({ node, root = false }: { node: AnyRecord; root?: boolean }) {
  if (!node) return <p className="muted">未能读取目录结构。</p>;
  const children = node.children || [];
  if (root) return <div className="tree-root">{children.map((child: AnyRecord) => <DirectoryTree key={child.path} node={child} />)}</div>;
  const note = directoryNote(node.path);
  return (
    <details className="tree-node" open={(node.children || []).length <= 3}>
      <summary><span className="tree-name">{node.name}/</span><span>{node.files} 文件</span><span>{formatBytes(node.bytes)}</span>{note ? <span className="tree-note">{note}</span> : null}</summary>
      {children.length ? <div className="tree-children">{children.map((child: AnyRecord) => <DirectoryTree key={child.path} node={child} />)}</div> : null}
    </details>
  );
}

function directoryNote(path: string): string {
  const notes = report.overall_assessment?.directory_notes || {};
  if (notes && typeof notes === "object" && !Array.isArray(notes)) return String(notes[path] || "");
  return "";
}

function formatBytes(value: unknown): string {
  const bytes = Number(value || 0);
  if (bytes >= 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${bytes} B`;
}

function ArchitectureView({ assessment }: AnyRecord) {
  return <div className="architecture">{assessment.architecture_diagram ? <ArchitectureDiagram value={assessment.architecture_diagram} /> : null}<ArchitectureEdges edges={assessment.architecture_edges || []} />{assessment.architecture_overview ? <article className="arch-card"><h3>内核架构补充说明</h3><TextBlock value={assessment.architecture_overview} /></article> : null}</div>;
}

function ArchitectureDiagram({ value }: { value: unknown }) {
  const source = stripMermaidFence(value);
  const viewport = useRef<HTMLDivElement | null>(null);
  const [scale, setScale] = useState(1);
  const [offset, setOffset] = useState({ x: 0, y: 0 });
  const drag = useRef<{ x: number; y: number; ox: number; oy: number } | null>(null);
  const clampScale = (next: number) => Math.max(0.45, Math.min(2.4, Number(next.toFixed(2))));
  const zoom = (delta: number) => setScale((current) => clampScale(current + delta));
  const reset = () => {
    setScale(1);
    setOffset({ x: 0, y: 0 });
  };
  const onWheel = (event: WheelEvent<HTMLDivElement>) => {
    if (!event.ctrlKey && !event.metaKey) return;
    event.preventDefault();
    zoom(event.deltaY > 0 ? -0.08 : 0.08);
  };
  const onMouseDown = (event: MouseEvent<HTMLDivElement>) => {
    drag.current = { x: event.clientX, y: event.clientY, ox: offset.x, oy: offset.y };
  };
  const onMouseMove = (event: MouseEvent<HTMLDivElement>) => {
    if (!drag.current) return;
    const next = drag.current;
    setOffset({ x: next.ox + event.clientX - next.x, y: next.oy + event.clientY - next.y });
  };
  const stopDrag = () => {
    drag.current = null;
  };
  return (
    <article className="arch-card">
      <div className="arch-title-row">
        <h3>内核架构图（Agent 生成）</h3>
        <div className="diagram-tools">
          <button type="button" onClick={() => zoom(-0.15)}>-</button>
          <span>{Math.round(scale * 100)}%</span>
          <button type="button" onClick={() => zoom(0.15)}>+</button>
          <button type="button" onClick={reset}>重置</button>
        </div>
      </div>
      <div
        ref={viewport}
        className="mermaid-wrap pannable"
        onWheel={onWheel}
        onMouseDown={onMouseDown}
        onMouseMove={onMouseMove}
        onMouseUp={stopDrag}
        onMouseLeave={stopDrag}
      >
        <div className="mermaid-stage" style={{ transform: `translate(${offset.x}px, ${offset.y}px) scale(${scale})` }}>
          <div className="mermaid">{source}</div>
        </div>
      </div>
      <details className="diagram-source"><summary>查看 Mermaid 源码</summary><pre>{source}</pre></details>
    </article>
  );
}

function ArchitectureEdges({ edges }: { edges: AnyRecord[] }) {
  if (!edges.length) return <article className="arch-card"><p className="muted">缺少 Agent 根据代码阅读提交的架构关系。</p></article>;
  return <article className="arch-card"><h3>关键架构关系</h3><div className="edge-grid">{edges.map((edge, index) => <div key={index} className="edge-card"><strong>{edgeTitle(edge)}</strong><p>{edge.label || ""}</p>{edge.type ? <p className="muted">关系类型：{edge.type}</p> : null}</div>)}</div></article>;
}

function edgeTitle(edge: AnyRecord): string {
  const source = edgeEndpoint(edge, "source");
  const target = edgeEndpoint(edge, "target");
  if (source && target) return `${source} → ${target}`;
  return source || target || edge.type || "架构关系";
}

function edgeEndpoint(edge: AnyRecord, side: "source" | "target"): string {
  const sourceKeys = ["source_label", "from_label", "source", "from", "source_module", "from_module", "source_node", "from_node"];
  const targetKeys = ["target_label", "to_label", "target", "to", "target_module", "to_module", "target_node", "to_node"];
  const keys = side === "source" ? sourceKeys : targetKeys;
  const index = side === "source" ? 0 : 1;
  for (const key of keys) if (edge[key]) return titleOf(edge[key]);
  for (const key of ["node_ids", "module_ids"]) if (Array.isArray(edge[key]) && edge[key][index]) return titleOf(edge[key][index]);
  return "";
}

function ModulePage({ moduleId, openView }: AnyRecord) {
  const module = taxonomy.modules.find((row) => row.id === moduleId);
  const review = moduleReviews.get(moduleId) || {};
  const stats = moduleStats(moduleId);
  const evidenceIds = moduleEvidenceIds(moduleId);
  const featuredClaims = claimList(review.featured_claim_ids);
  return (
    <section>
      <div className="eyebrow">总体结果 / {module?.title || moduleId}</div>
      <h1 className="title">{module?.title || moduleId}</h1>
      <section className="module-hero"><h2>模块实现概述</h2><TextBlock value={review.overview} className="lead" /><div className="metrics"><Metric value={stats.complete} label="完整实现节点" /><Metric value={stats.partial} label="部分/最低限度节点" /><Metric value={stats.independent} label="独立或实质重写节点" /><Metric value={`${stats.directEvidence}/${stats.total}`} label="节点直接证据覆盖" /></div></section>
      <section className="module-layout">
        <div><article className="card"><h2>实现情况</h2><TextBlock value={review.implementation_summary} /></article><article className="card"><h2>与参考作品的关系</h2><TextBlock value={review.difference_summary} /></article><article className="card"><h2>原创工作位置</h2><TextBlock value={review.original_work_summary} /></article></div>
        <div><article className="card"><h2>未实现、不适用或需复核</h2><AbsentList moduleId={moduleId} /></article><article className="card"><h2>重点结论</h2>{featuredClaims.length ? featuredClaims.map((claim) => <CompactClaim key={claim.claim_id} claim={claim} />) : <p className="muted">本模块未单独置顶结论，节点页保留完整评审。</p>}</article></div>
      </section>
      <h2 className="section-title">关键机制链路</h2>
      <div className="chain-grid">{(review.key_chains || []).length ? (review.key_chains || []).map((chain: AnyRecord, index: number) => <ChainCard key={index} chain={chain} />) : <p className="muted">缺少关键机制链路。</p>}</div>
      <h2 className="section-title">节点覆盖与证据状态</h2>
      <NodeTable moduleId={moduleId} openView={openView} />
      <EvidenceSection title="本模块相关证据" ids={evidenceIds} />
    </section>
  );
}

function Metric({ value, label }: { value: unknown; label: string }) {
  return <div className="metric"><strong>{String(value)}</strong><span>{label}</span></div>;
}

function EvidencePills({ ids }: { ids: string[] }) {
  if (!ids.length) return <div className="evidence-pills"><span className="pill warn">本模块缺少已绑定证据锚点</span></div>;
  return <div className="evidence-pills">{ids.slice(0, 12).map((id) => { const evidence = DATA.evidence[id]; return <span key={id} className={`evidence-chip ${evidenceClass(evidence)}`}>{evidence.label} · {evidence.title}</span>; })}</div>;
}

function CompactClaim({ claim }: AnyRecord) {
  return <div className="claim-card"><div className="badge-row"><span className="badge conf">{labels.claim[claim.claim_type] || claim.claim_type}</span><span className="badge conf">置信度：{claim.confidence}</span></div><TextBlock value={claim.statement} /><div className="claim-actions"><EvidenceButtons claim={claim} /></div></div>;
}

function ChainCard({ chain }: AnyRecord) {
  const nodes = (chain.node_ids || []).map(titleOf).join(" → ");
  return <article className="chain-card"><h3>{chain.title || "关键机制"}</h3><p className="muted">{nodes}</p><TextBlock value={chain.explanation} /><EvidencePills ids={(chain.evidence_ids || []).filter((id: string) => DATA.evidence[id])} /></article>;
}

function AbsentList({ moduleId }: { moduleId: string }) {
  const rows = moduleNodes(moduleId).map((nodeId) => {
    const review = nodeReviews.get(nodeId) || {};
    const impl = review.implementation_degree?.level;
    if (!["absent", "not_applicable", "unknown", "minimal"].includes(impl)) return null;
    return <span key={nodeId} className="pill warn">{titleOf(nodeId)} · {labels.implementation[impl] || impl}</span>;
  }).filter(Boolean);
  return rows.length ? <div className="evidence-pills">{rows}</div> : <p className="muted">无明显缺失或不适用项。</p>;
}

function NodeTable({ moduleId, openView }: AnyRecord) {
  const moduleHasEvidence = moduleEvidenceIds(moduleId).length > 0;
  return <div className="node-table"><div className="node-row header"><span>节点</span><span>实现摘要</span><span>完整度</span><span>原创度</span><span>证据</span></div>{moduleNodes(moduleId).map((nodeId) => {
    const review = nodeReviews.get(nodeId) || {};
    const impl = review.implementation_degree?.level || "unknown";
    const orig = review.originality?.level || "unknown";
    const direct = claimList(review.claim_ids).some((claim) => (claim.evidence_ids || []).length);
    let evidenceState = ["none", "暂无证据"];
    if (direct) evidenceState = ["ok", "本节点有证据"];
    else if (["absent", "not_applicable"].includes(impl)) evidenceState = ["", "无需证据"];
    else if (moduleHasEvidence) evidenceState = ["warn", "引用模块证据"];
    return <div key={nodeId} className="node-row" onClick={() => openView(`node:${nodeId}`)}><strong>{titleOf(nodeId)}</strong><p>{shortText(textValue(review.overview), 96)}</p><span>{labels.implementation[impl] || impl}</span><span>{labels.originality[orig] || orig}</span><span className={`pill ${evidenceState[0]}`}>{evidenceState[1]}</span></div>;
  })}</div>;
}

function NodePage({ nodeId }: AnyRecord) {
  const review = nodeReviews.get(nodeId) || {};
  const impl = review.implementation_degree || {};
  const orig = review.originality || {};
  const nodeClaims = uniqueClaims([...claimList(review.claim_ids), ...[...claims.values()].filter((claim) => claim.node_id === nodeId)]);
  const evidenceIds = evidenceIdsFromClaims(nodeClaims);
  return <section><div className="eyebrow">{titleOf(nodeId.split(".")[0])} / {titleOf(nodeId)}</div><h1 className="title">{titleOf(nodeId)}</h1><div className="scope-box"><strong>功能范围：</strong>{scopeOf(nodeId)}</div><div className="grid"><article className="card"><div className="badge-row"><span className="badge impl">完整度：{labels.implementation[impl.level] || impl.level}</span></div><h3>完整度判断</h3><TextBlock value={impl.rationale} /></article><article className="card"><div className="badge-row"><span className="badge orig">原创度：{labels.originality[orig.level] || orig.level}</span></div><h3>原创度判断</h3><TextBlock value={orig.rationale} /></article></div><article className="card"><h2>{report.work.display_name} 中如何实现</h2><TextBlock value={review.overview} /></article><article className="card"><h2>与 {report.reference.display_name} 的差异</h2><TextBlock value={review.difference_from_reference} /></article><h2 className="section-title">节点结论</h2><div className="claim-list">{nodeClaims.map((claim) => <ClaimCard key={claim.claim_id} claim={claim} />)}</div><article className="card"><h2>风险、缺失与不确定项</h2><RiskList risks={review.risks} /></article><EvidenceSection title="本节点相关证据" ids={evidenceIds} /></section>;
}

function ClaimCard({ claim }: AnyRecord) {
  return <article className="claim-card"><div className="badge-row"><span className="badge conf">{labels.claim[claim.claim_type] || claim.claim_type}</span><span className="badge conf">置信度：{claim.confidence}</span></div><TextBlock value={claim.statement} /><div className="claim-actions"><EvidenceButtons claim={claim} /></div></article>;
}

function EvidenceButtons({ claim }: AnyRecord) {
  const ids = (claim.evidence_ids || []).filter((id: string) => DATA.evidence[id]);
  if (!ids.length) return <span className="pill none">未绑定关键证据</span>;
  return ids.map((id: string) => { const evidence = DATA.evidence[id]; return <a key={id} className={`evidence-button ${evidenceClass(evidence)}`} href={`#evidence-${id}`}>{evidence.category} {evidence.label}</a>; });
}

function RiskList({ risks }: { risks?: string[] }) {
  if (!risks || !risks.length) return <p className="muted">当前没有额外风险项。</p>;
  return <>{risks.map((risk, index) => <div key={index} className="risk">{risk}</div>)}</>;
}

function EvidenceSection({ title, ids }: { title: string; ids: string[] }) {
  if (!ids.length) return <section className="evidence-section"><h2 className="section-title">{title}</h2><p className="muted">该部分没有绑定关键证据。未实现、不适用或普通实现说明不强制要求证据锚点。</p></section>;
  return (
    <section className="evidence-section">
      <h2 className="section-title">{title}</h2>
      <div className="evidence-grid">{ids.map((id) => <EvidenceCard key={id} id={id} />)}</div>
    </section>
  );
}

function EvidenceCard({ id }: { id: string }) {
  const evidence = DATA.evidence[id];
  if (!evidence) return null;
  const location = [evidence.path, evidence.lineStart].filter(Boolean).join(":") || "结构化审计记录";
  return (
    <article id={`evidence-${id}`} className={`detail-card evidence-card ${evidenceClass(evidence)}`}>
      <div className="badge-row"><span className="badge conf">{evidence.category} {evidence.label}</span><span className="badge conf">{evidence.kindLabel}</span></div>
      <h3>{evidence.title}</h3>
      <p><strong>来源：</strong>{evidence.owner}</p>
      <p><strong>commit：</strong><code>{evidence.commit || ""}</code></p>
      <p><strong>位置：</strong><span className="location">{location}</span></p>
      <p><strong>验证状态：</strong>{evidence.verified ? "已验证" : "未验证"}</p>
      <pre>{evidence.excerpt}</pre>
    </article>
  );
}

function evidenceClass(evidence: AnyRecord): string {
  if (evidence.category === "审计证据") return "audit";
  if (evidence.category === "链路证据") return "link";
  if (evidence.category === "文档证据") return "doc";
  return "source";
}

function initialView(): string {
  const hash = decodeURIComponent(location.hash.slice(1));
  if (hash.startsWith("node=")) return `node:${hash.slice(5)}`;
  if (hash.startsWith("module=")) return `module:${hash.slice(7)}`;
  return "overview";
}

function initialModuleFromView(view: string): string {
  if (view.startsWith("module:")) return view.slice(7);
  if (view.startsWith("node:")) return view.slice(5).split(".")[0];
  return taxonomy.modules.find((module) => module.id !== "Metadata")?.id || "";
}
