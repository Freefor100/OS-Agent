export type EvidenceSource = {
  work_id: string;
  display_name: string;
  commit?: string;
  path?: string;
  locator?: string;
  object_hash?: string;
  line_start?: number;
  line_end?: number;
  page?: number;
  paragraph?: number;
  format?: string;
};

export type EvidenceReference = {
  document: string;
  section: string;
  label: string;
  view: "overview" | "lineage" | "architecture" | "risk" | "modules" | "evidence" | string;
  anchor: string;
};

export type EvidenceCard = {
  evidence_id: string;
  kind: "source_span" | "document_span" | "git_commit" | "fingerprint_comparison" | "search_result" | string;
  title: string;
  source: EvidenceSource;
  excerpt: string;
  facts: Array<{ label: string; value: unknown }>;
  table?: { columns: string[]; rows: unknown[][] };
  references: EvidenceReference[];
};

export type ReportSection = {
  id: string;
  title: string;
  markdown: string;
  evidence_ids: string[];
};

export type ModuleReview = {
  module_id: string;
  title: string;
  status: string;
  originality: string;
  base_delta: string;
  anchors: string[];
  markdown: string;
  evidence_ids: string[];
};

export type ReviewReportData = {
  generated_by: string;
  schema: string;
  identity: {
    work_id: string;
    display_name: string;
    school: string;
    team: string;
    work_name: string;
  };
  base: {
    status: "accepted" | "no_reliable_base" | string;
    display_name: string;
    commit: string;
    target_introduction_commit: string;
    direction: string;
    confidence: string;
  };
  sections: ReportSection[];
  modules: ModuleReview[];
  evidence: EvidenceCard[];
  optional_sections: {
    doc_claim: boolean;
    cheat: boolean;
    ai: boolean;
  };
};

export type IndexItem = {
  work_id: string;
  display_name: string;
  school: string;
  team: string;
  work_name: string;
  base?: {
    display_name: string;
    relation: string;
    confidence: string;
  };
  risk_tags: string[];
  module_summary: Record<string, number>;
  public_paths: {
    markdown?: string;
    html?: string;
    data?: string;
  };
};
