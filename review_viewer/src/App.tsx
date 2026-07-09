import { useEffect, useState } from "react";
import { loadInitialData } from "./data";
import { IndexView } from "./components/IndexView";
import { ReportView } from "./components/ReportView";
import type { ReviewReportData, IndexItem } from "./types";

type State = {
  loading: boolean;
  index: IndexItem[];
  report: ReviewReportData | null;
  error: string;
};

export default function App() {
  const [state, setState] = useState<State>({ loading: true, index: [], report: null, error: "" });

  useEffect(() => {
    loadInitialData()
      .then((data) => setState({ loading: false, index: data.index, report: data.report, error: "" }))
      .catch((error: Error) => setState({ loading: false, index: [], report: null, error: error.message }));
  }, []);

  if (state.loading) {
    return <div className="loading">读取评审数据…</div>;
  }
  if (state.error) {
    return <div className="loading error">读取失败：{state.error}</div>;
  }
  if (state.report) {
    return <ReportView report={state.report} onBack={state.index.length ? () => setState((prev) => ({ ...prev, report: null })) : undefined} />;
  }
  return <IndexView index={state.index} onOpenReport={(item) => openReport(item, setState)} />;
}

function openReport(item: IndexItem, setState: React.Dispatch<React.SetStateAction<State>>) {
  const path = item.public_paths?.data;
  if (!path) return;
  fetch(path, { cache: "no-store" })
    .then((response) => {
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return response.json() as Promise<ReviewReportData>;
    })
    .then((report) => setState((prev) => ({ ...prev, report })))
    .catch((error: Error) => setState((prev) => ({ ...prev, error: error.message })));
}
