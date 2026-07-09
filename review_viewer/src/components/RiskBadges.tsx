type Props = {
  tags: string[];
};

export function RiskBadges({ tags }: Props) {
  if (!tags.length) {
    return <span className="badge badge-muted">无公开风险</span>;
  }
  return (
    <span className="badge-row">
      {tags.map((tag) => (
        <span className="badge badge-risk" key={tag}>
          {label(tag)}
        </span>
      ))}
    </span>
  );
}

function label(tag: string): string {
  const map: Record<string, string> = {
    doc_claim_mismatch: "声明需复核",
    history_ai_signal: "AI/历史信号",
    cheat_or_prompt_injection_signal: "测试/提示风险"
  };
  return map[tag] ?? tag;
}
