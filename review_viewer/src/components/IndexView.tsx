import { Search } from "lucide-react";
import { useMemo, useState } from "react";
import type { IndexItem } from "../types";
import { RiskBadges } from "./RiskBadges";

type Props = {
  index: IndexItem[];
  onOpenReport: (item: IndexItem) => void;
};

export function IndexView({ index, onOpenReport }: Props) {
  const [query, setQuery] = useState("");
  const [riskOnly, setRiskOnly] = useState(false);
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return index.filter((item) => {
      const haystack = `${item.display_name} ${item.school} ${item.team} ${item.work_name}`.toLowerCase();
      return (!q || haystack.includes(q)) && (!riskOnly || item.risk_tags.length > 0);
    });
  }, [index, query, riskOnly]);
  return (
    <main className="index-view">
      <header className="app-header">
        <div>
          <div className="eyebrow">OS-Agent</div>
          <h1>评审索引</h1>
        </div>
        <p>按作品名、学校、队伍、Base 关系和风险标签快速定位报告。</p>
      </header>
      <section className="toolbar" aria-label="过滤">
        <label className="search-box">
          <Search size={18} />
          <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索作品、学校或队伍" />
        </label>
        <label className="toggle">
          <input type="checkbox" checked={riskOnly} onChange={(event) => setRiskOnly(event.target.checked)} />
          只看公开风险
        </label>
      </section>
      <section className="index-table-wrap">
        <table className="index-table">
          <thead>
            <tr>
              <th>作品</th>
              <th>Base</th>
              <th>模块账本</th>
              <th>风险</th>
              <th>入口</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((item) => (
              <tr key={item.work_id}>
                <td>
                  <strong>{item.display_name}</strong>
                  <span>{item.school} / {item.team}</span>
                </td>
                <td>
                  <span>{item.base?.display_name || "未编译"}</span>
                  <small>{item.base?.relation} / {item.base?.confidence}</small>
                </td>
                <td>
                  <span className="ledger-mini">
                    N {item.module_summary?.novel ?? 0} / A {item.module_summary?.adapted ?? 0} / I {item.module_summary?.inherited ?? 0} / X {item.module_summary?.absent ?? 0}
                  </span>
                </td>
                <td><RiskBadges tags={item.risk_tags || []} /></td>
                <td>
                  <button className="text-button" onClick={() => onOpenReport(item)}>打开</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </main>
  );
}
