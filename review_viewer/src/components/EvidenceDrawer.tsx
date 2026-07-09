import { X } from "lucide-react";
import type { EvidenceCard } from "../types";

type Props = {
  evidence: EvidenceCard | null;
  onClose: () => void;
};

export function EvidenceDrawer({ evidence, onClose }: Props) {
  return (
    <aside className={`evidence-drawer ${evidence ? "open" : ""}`} aria-live="polite">
      <div className="drawer-head">
        <div>
          <div className="eyebrow">Evidence</div>
          <h2>{evidence?.evidence_id ?? "选择证据"}</h2>
        </div>
        <button className="icon-button" onClick={onClose} aria-label="关闭证据">
          <X size={18} />
        </button>
      </div>
      {evidence ? (
        <div className="drawer-body">
          <h3>{evidence.title}</h3>
          <dl>
            <dt>类型</dt>
            <dd>{evidence.kind}</dd>
            <dt>来源</dt>
            <dd>{evidence.display_owner}</dd>
            <dt>位置</dt>
            <dd>
              {evidence.canonical_path} {evidence.locator}
            </dd>
            <dt>Commit</dt>
            <dd>{evidence.commit}</dd>
            <dt>置信度</dt>
            <dd>{evidence.confidence}{evidence.verified ? " / verified" : " / unverified"}</dd>
          </dl>
          <blockquote>{evidence.excerpt}</blockquote>
          <div className="supports">
            {evidence.supports.map((item) => (
              <span className="badge badge-muted" key={item}>
                {item}
              </span>
            ))}
          </div>
        </div>
      ) : (
        <p className="drawer-empty">点击正文中的证据 chip 查看来源、路径和摘录。</p>
      )}
    </aside>
  );
}
