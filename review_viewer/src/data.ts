import type { ReviewReportData, IndexItem } from "./types";

declare global {
  interface Window {
    __OS_REVIEW_REPORT__?: ReviewReportData;
    __OS_REVIEW_INDEX__?: IndexItem[];
  }
}

export async function loadInitialData(): Promise<{ index: IndexItem[]; report: ReviewReportData | null }> {
  if (window.__OS_REVIEW_REPORT__) {
    assertCurrentReport(window.__OS_REVIEW_REPORT__);
    return { index: window.__OS_REVIEW_INDEX__ ?? [], report: window.__OS_REVIEW_REPORT__ };
  }
  const reportPath = new URLSearchParams(window.location.search).get("report") ?? "report_data.json";
  const report = await tryFetchJson<ReviewReportData>(reportPath);
  if (report) {
    assertCurrentReport(report);
    return { index: [], report };
  }
  const index = await tryFetchJson<IndexItem[]>("site_index.json");
  if (index) return { index, report: null };
  throw new Error("当前目录没有 report_data.json 或 site_index.json");
}

function assertCurrentReport(report: ReviewReportData): void {
  if (report.schema !== "report_data.v3") {
    throw new Error(`不支持的报告数据版本：${String(report.schema || "missing")}`);
  }
}

async function tryFetchJson<T>(path: string): Promise<T | null> {
  try {
    const response = await fetch(path, { cache: "no-store" });
    if (!response.ok) return null;
    return (await response.json()) as T;
  } catch {
    return null;
  }
}
