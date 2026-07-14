import { ArrowUpRight, Check, Copy, X } from "lucide-react";
import { useState } from "react";
import type { EvidenceCard, EvidenceReference } from "../types";

type Props = {
  evidence: EvidenceCard | null;
  total: number;
  onClose: () => void;
  onNavigate: (reference: EvidenceReference) => void;
};

export function EvidenceDrawer({ evidence, total, onClose, onNavigate }: Props) {
  const [copied, setCopied] = useState(false);
  const copyLocator = () => {
    if (!evidence) return;
    const source = evidence.source;
    navigator.clipboard?.writeText([source.path, source.locator, source.commit, source.object_hash].filter(Boolean).join(" "));
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1200);
  };
  return (
    <aside className={`evidence-drawer ${evidence ? "open" : ""}`} aria-live="polite">
      <header className="drawer-head">
        <div><span className="section-code">EVIDENCE</span><h2>{evidence ? evidence.evidence_id : "证据面板"}</h2></div>
        <div className="drawer-actions">
          {evidence && <button className="icon-button" onClick={copyLocator} title="复制证据位置" aria-label="复制证据位置">{copied ? <Check size={17} /> : <Copy size={17} />}</button>}
          <button className="icon-button drawer-close" onClick={onClose} title="关闭证据" aria-label="关闭证据"><X size={18} /></button>
        </div>
      </header>
      {evidence ? <EvidenceContent evidence={evidence} onNavigate={onNavigate} /> : <div className="drawer-empty"><div className="evidence-counter">{total}</div><p>点击正文中的证据编号，查看锁定的源码、文档、提交、指纹比较或检索事实。</p></div>}
    </aside>
  );
}

function EvidenceContent({ evidence, onNavigate }: { evidence: EvidenceCard; onNavigate: (reference: EvidenceReference) => void }) {
  const source = evidence.source;
  return <div className="drawer-body">
    <div className={`evidence-type evidence-type-${evidence.kind}`}>{kindLabel(evidence.kind)}</div>
    <h3>{evidence.title}</h3>
    <dl className="source-meta">
      <dt>来源</dt><dd>{source.display_name}</dd>
      {source.path && <><dt>路径</dt><dd><code>{source.path}</code></dd></>}
      {source.locator && <><dt>位置</dt><dd>{source.locator}</dd></>}
      {source.commit && <><dt>Commit</dt><dd><code>{source.commit}</code></dd></>}
      {source.object_hash && <><dt>对象</dt><dd><code>{source.object_hash}</code></dd></>}
    </dl>

    {evidence.facts.length > 0 && <div className="fact-block"><h4>事实摘要</h4><dl className="fact-list">{evidence.facts.map((fact, index) => <div key={`${fact.label}-${index}`}><dt>{fact.label}</dt><dd>{formatValue(fact.value)}</dd></div>)}</dl></div>}

    <Excerpt evidence={evidence} />
    {evidence.table && evidence.table.rows.length > 0 && <EvidenceTable evidence={evidence} />}

    <div className="reference-block">
      <h4>正文引用</h4>
      {evidence.references.length ? evidence.references.map((reference, index) => (
        <button key={`${reference.document}-${reference.section}-${index}`} className="reference-link" onClick={() => onNavigate(reference)}>
          <span><strong>{reference.label}</strong><small>{reference.document} · {reference.section}</small></span><ArrowUpRight size={15} />
        </button>
      )) : <p className="muted-copy">当前公开内容没有引用此证据。</p>}
    </div>
  </div>;
}

function Excerpt({ evidence }: { evidence: EvidenceCard }) {
  const start = evidence.source.line_start;
  const lines = evidence.excerpt.split("\n");
  const lineNumbered = typeof start === "number";
  return <div className="excerpt evidence-excerpt"><h4>{evidence.kind === "git_commit" ? "提交信息" : "固定内容"}</h4>
    {lineNumbered ? <pre className="line-code">{lines.map((line, index) => <span key={index}><i>{start + index}</i><code>{line || " "}</code></span>)}</pre> : <pre>{evidence.excerpt || "（无文本内容）"}</pre>}
  </div>;
}

function EvidenceTable({ evidence }: { evidence: EvidenceCard }) {
  const table = evidence.table!;
  return <div className="evidence-table-wrap"><table className="evidence-table"><thead><tr>{table.columns.map((column) => <th key={column}>{column}</th>)}</tr></thead><tbody>{table.rows.map((row, rowIndex) => <tr key={rowIndex}>{row.map((value, columnIndex) => <td key={columnIndex}>{formatValue(value)}</td>)}</tr>)}</tbody></table></div>;
}

function formatValue(value: unknown): string {
  if (Array.isArray(value)) return value.join(", ") || "-";
  if (value === null || value === undefined || value === "") return "-";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function kindLabel(kind: string) {
  return ({
    source_span: "源码",
    document_span: "文档",
    git_commit: "Git Commit",
    fingerprint_comparison: "指纹比较",
    search_result: "检索结果"
  } as Record<string, string>)[kind] ?? kind;
}
