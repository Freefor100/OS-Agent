import { ArrowUpRight, Filter, Search } from "lucide-react";
import { useMemo, useState } from "react";
import type { IndexItem } from "../types";
import { RiskBadges } from "./RiskBadges";

type Props = { index: IndexItem[]; onOpenReport: (item: IndexItem) => void };

export function IndexView({ index, onOpenReport }: Props) {
  const [query, setQuery] = useState("");
  const [base, setBase] = useState("all");
  const [riskOnly, setRiskOnly] = useState(false);
  const filtered = useMemo(() => index.filter((item) => {
    const q = query.trim().toLowerCase();
    const text = `${item.display_name} ${item.school} ${item.team} ${item.work_name} ${item.base?.display_name ?? ""}`.toLowerCase();
    const baseMatch = base === "all" || (base === "known" ? Boolean(item.base?.display_name) : !item.base?.display_name);
    return (!q || text.includes(q)) && baseMatch && (!riskOnly || item.risk_tags.length > 0);
  }), [base, index, query, riskOnly]);
  const withRisk = index.filter((item) => item.risk_tags.length).length;
  return <main className="index-view">
    <header className="index-header"><div className="product-mark"><span className="mark-glyph">OS</span><span><strong>分析比对智能体</strong><small>2026 · proj18</small></span></div><div className="index-stats"><span><strong>{index.length}</strong> 作品</span><span><strong>{withRisk}</strong> 公开复核项</span></div></header>
    <section className="index-title"><span className="section-code">REVIEW REGISTER</span><h1>小型操作系统分析比对结果</h1><p>面向内核赛道评委的来源、工作量、实现与风险索引。</p></section>
    <section className="toolbar" aria-label="筛选报告">
      <label className="search-box"><Search size={18} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索作品、学校、队伍或 Base" /></label>
      <label className="select-box"><Filter size={16} /><select value={base} onChange={(event) => setBase(event.target.value)}><option value="all">全部 Base 状态</option><option value="known">已确认 Base</option><option value="unknown">无可靠 Base</option></select></label>
      <label className="toggle"><input type="checkbox" checked={riskOnly} onChange={(event) => setRiskOnly(event.target.checked)} /><span>只看公开风险</span></label>
      <span className="result-count">{filtered.length} / {index.length}</span>
    </section>
    <section className="index-table-wrap">
      <table className="index-table">
        <thead><tr><th>作品</th><th>Base / 来源关系</th><th>工作量账本</th><th>公开风险</th><th><span className="sr-only">操作</span></th></tr></thead>
        <tbody>{filtered.map((item) => <tr key={item.work_id}>
          <td><strong>{item.display_name}</strong><small>{item.school} · {item.team}</small></td>
          <td><span>{item.base?.display_name || "无可靠 Base"}</span><small>{baseMeta(item)}</small></td>
          <td><LedgerMini values={item.module_summary} /></td>
          <td><RiskBadges tags={item.risk_tags || []} /></td>
          <td><button className="open-report" onClick={() => onOpenReport(item)}>打开报告<ArrowUpRight size={16} /></button></td>
        </tr>)}</tbody>
      </table>
      {!filtered.length && <div className="empty-result">没有符合当前筛选条件的报告。</div>}
    </section>
  </main>;
}

function baseMeta(item: IndexItem) {
  const version = [item.base?.ref, item.base?.commit?.slice(0, 10)].filter(Boolean).join("@");
  return [version, item.base?.relation, item.base?.confidence].filter(Boolean).join(" · ");
}

function LedgerMini({ values }: { values: Record<string, number> }) {
  return <div className="ledger-mini"><span className="mini-novel">新增 {values.novel ?? 0}</span><span>适配 {values.adapted ?? 0}</span><span>继承 {values.inherited ?? 0}</span><span>缺失 {values.absent ?? 0}</span></div>;
}
