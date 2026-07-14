import { useEffect, useId, useRef } from "react";
import { Code2, FileText, GitCommitHorizontal, GitCompareArrows, Search } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import mermaid from "mermaid";
import type { EvidenceCard } from "../types";

type Props = {
  markdown: string;
  evidenceById: Map<string, EvidenceCard>;
  onSelectEvidence: (id: string) => void;
};

export function EvidenceChip({ evidence, id, onSelect }: { evidence?: EvidenceCard; id: string; onSelect: (id: string) => void }) {
  const Icon = evidenceIcon(evidence?.kind);
  return (
    <button className={`evidence-chip evidence-kind-${evidence?.kind ?? "unknown"}`} onClick={() => onSelect(id)} title={evidence?.title ?? id}>
      <Icon size={12} aria-hidden="true" /><span>{id}</span>
    </button>
  );
}

export function MarkdownBody({ markdown, evidenceById, onSelectEvidence }: Props) {
  const linked = markdown.replace(/\[@(E\d{3,})\]/g, "[@$1](#evidence-$1)");
  return (
    <div className="markdown-body">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        urlTransform={(url) => url}
        components={{
          a: ({ href, children }) => {
            const match = /^#evidence-(E\d{3,})$/.exec(href ?? "");
            if (match) {
              return <EvidenceChip evidence={evidenceById.get(match[1])} id={match[1]} onSelect={onSelectEvidence} />;
            }
            return <a href={href}>{children}</a>;
          },
          code: ({ className, children }) => {
            const language = /language-(\w+)/.exec(className ?? "")?.[1];
            if (language === "mermaid") return <Mermaid source={String(children).trim()} />;
            return <code className={className}>{children}</code>;
          }
        }}
      >
        {linked}
      </ReactMarkdown>
    </div>
  );
}

function evidenceIcon(kind?: string) {
  if (kind === "source_span") return Code2;
  if (kind === "document_span") return FileText;
  if (kind === "git_commit") return GitCommitHorizontal;
  if (kind === "fingerprint_comparison") return GitCompareArrows;
  return Search;
}

function Mermaid({ source }: { source: string }) {
  const host = useRef<HTMLSpanElement>(null);
  const id = useId().replace(/:/g, "");
  useEffect(() => {
    let active = true;
    mermaid.initialize({
      startOnLoad: false,
      securityLevel: "strict",
      theme: "base",
      themeVariables: {
        primaryColor: "#e7f2f1",
        primaryBorderColor: "#00747c",
        primaryTextColor: "#172125",
        lineColor: "#53656b",
        secondaryColor: "#fff3dc",
        tertiaryColor: "#f3f5f4",
        fontFamily: '"Noto Sans SC", "Microsoft YaHei", sans-serif'
      }
    });
    mermaid.render(`kernel-map-${id}`, source).then(({ svg }) => {
      if (active && host.current) host.current.innerHTML = svg;
    }).catch(() => {
      if (active && host.current) host.current.textContent = source;
    });
    return () => { active = false; };
  }, [id, source]);
  return <span className="mermaid-canvas" ref={host} aria-label="内核架构图" />;
}
