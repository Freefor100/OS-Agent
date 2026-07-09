# Evidence Contract

Evidence 是固定 JSONL。Agent 正文只引用 `[@E001]` 形式的 chip。

允许的 kind：`source_span`、`doc_claim`、`base_delta_summary`、`git_history`、`negative_search`、`artifact`、`risk_signal`。

强结论必须有一个 verified strong evidence，或两个 verified medium evidence。`verified=false` 只能支撑“不确定”。

结论和证据是多对多关系：一个结论可以引用多个 evidence，一个 evidence 也可以支撑多个结论域。编译阶段会把 正文引用关系和证据映射分别写入 `site/report_data.json` 的 `evidence_graph`。
