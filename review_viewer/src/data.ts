import type { ReviewReportData, IndexItem } from "./types";

declare global {
  interface Window {
    __OS_REVIEW_REPORT__?: ReviewReportData;
    __OS_REVIEW_INDEX__?: IndexItem[];
  }
}

const demoReport: ReviewReportData = {
  generated_by: "demo",
  schema: "report_data.v1",
  identity: {
    work_id: "demo",
    display_name: "北京大学 数理基础队《DemoOS》",
    school: "北京大学",
    team: "数理基础队",
    work_name: "DemoOS"
  },
  sections: [
    {
      id: "base",
      title: "Base 与来源关系",
      markdown: "## Base 与来源关系\n\nBase 方向为 `likely_inherited`，核心证据见 [@E001]。",
      evidence_ids: ["E001"]
    }
  ],
  modules: [
    {
      module_id: "memory-vm",
      title: "内存、虚拟内存与页缓存",
      status: "implemented",
      originality: "adapted_major",
      base_delta: "major",
      anchors: ["kernel/mm/page_cache.c", "handle_page_fault", "page_cache_get"],
      markdown: "## 实现内容\n\n目标作品新增了 `handle_page_fault` 与 `page_cache_get` 的协作路径 [@E001]。",
      evidence_ids: ["E001"]
    }
  ],
  evidence: [
    {
      evidence_id: "E001",
      kind: "source_span",
      owner: "target",
      display_owner: "北京大学 数理基础队《DemoOS》",
      canonical_path: "kernel/mm/page_cache.c",
      commit: "abc001",
      locator: "L12-L198",
      title: "页缓存路径",
      excerpt: "handle_page_fault -> page_cache_get",
      supports: ["module:memory-vm"],
      confidence: "strong",
      verified: true
    }
  ],
  evidence_graph: {
    markdown_claims: {
      claims: [
        { claim_id: "section:base", kind: "section", title: "Base 与来源关系", evidence_ids: ["E001"] },
        { claim_id: "module:memory-vm", kind: "module", title: "内存、虚拟内存与页缓存", evidence_ids: ["E001"] }
      ],
      evidence_to_claims: { E001: ["section:base", "module:memory-vm"] }
    },
    evidence_map: {
      schema: "review_case.evidence_map.v1",
      evidence_map: [],
      domains: { work_amount: ["E001"], module_implementation: ["E001"] },
      agents: { "module-memory-vm": ["E001"] },
      modules: { "memory-vm": ["E001"] }
    }
  },
  optional_sections: { cheat: false, ai: false, prompt_injection: false }
};

const demoIndex: IndexItem[] = [
  {
    work_id: "demo",
    display_name: "北京大学 数理基础队《DemoOS》",
    school: "北京大学",
    team: "数理基础队",
    work_name: "DemoOS",
    base: { display_name: "公开教学基座《DemoBase》", relation: "likely_inherited", confidence: "high" },
    risk_tags: [],
    module_summary: { novel: 0, adapted: 1, inherited: 0, absent: 0 },
    public_paths: {}
  }
];

export async function loadInitialData(): Promise<{ index: IndexItem[]; report: ReviewReportData | null }> {
  if (window.__OS_REVIEW_REPORT__) {
    return { index: window.__OS_REVIEW_INDEX__ ?? [], report: window.__OS_REVIEW_REPORT__ };
  }
  const reportPath = new URLSearchParams(window.location.search).get("report") ?? "report_data.json";
  const indexPath = "site_index.json";
  const [index, report] = await Promise.all([tryFetchJson<IndexItem[]>(indexPath), tryFetchJson<ReviewReportData>(reportPath)]);
  if (report) {
    return { index: index ?? [], report };
  }
  return { index: index ?? demoIndex, report: null };
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

export function demo(): { index: IndexItem[]; report: ReviewReportData } {
  return { index: demoIndex, report: demoReport };
}
