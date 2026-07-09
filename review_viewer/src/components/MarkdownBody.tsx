import type { ReactNode } from "react";

type Props = {
  markdown: string;
  onSelectEvidence: (id: string) => void;
};

export function MarkdownBody({ markdown, onSelectEvidence }: Props) {
  const blocks = markdown.split(/\n{2,}/);
  return (
    <div className="markdown-body">
      {blocks.map((block, index) => renderBlock(block.trim(), index, onSelectEvidence))}
    </div>
  );
}

function renderBlock(block: string, key: number, onSelectEvidence: (id: string) => void): ReactNode {
  if (!block) return null;
  const fence = /^```([A-Za-z0-9_-]*)\n([\s\S]*)\n```$/.exec(block);
  if (fence) {
    return (
      <pre key={key} className={fence[1] === "mermaid" ? "mermaid-pre" : "code-pre"}>
        {fence[2]}
      </pre>
    );
  }
  const heading = /^(#{1,4})\s+(.+)$/.exec(block);
  if (heading) {
    const level = heading[1].length;
    const text = heading[2];
    if (level === 2) return <h2 key={key}>{text}</h2>;
    if (level === 3) return <h3 key={key}>{text}</h3>;
    return <h4 key={key}>{text}</h4>;
  }
  if (block.startsWith("- ")) {
    return (
      <ul key={key}>
        {block.split("\n").map((line) => (
          <li key={line}>{renderInline(line.replace(/^- /, ""), onSelectEvidence)}</li>
        ))}
      </ul>
    );
  }
  if (block.includes("\n|") || block.startsWith("|")) {
    return <pre key={key} className="table-pre">{block}</pre>;
  }
  return <p key={key}>{renderInline(block, onSelectEvidence)}</p>;
}

function renderInline(text: string, onSelectEvidence: (id: string) => void): ReactNode[] {
  const out: ReactNode[] = [];
  const regex = /(\[@E\d{3}\]|`[^`]+`)/g;
  let last = 0;
  let match: RegExpExecArray | null;
  while ((match = regex.exec(text))) {
    if (match.index > last) out.push(text.slice(last, match.index));
    const token = match[0];
    if (token.startsWith("[@")) {
      const id = token.slice(2, -1);
      out.push(
        <button className="evidence-chip" key={`${id}-${match.index}`} onClick={() => onSelectEvidence(id)}>
          @{id}
        </button>
      );
    } else {
      out.push(<code key={`${token}-${match.index}`}>{token.slice(1, -1)}</code>);
    }
    last = regex.lastIndex;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}
