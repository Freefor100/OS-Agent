export type EvidenceCard = {
  evidence_id: string;
  kind: string;
  owner: string;
  display_owner: string;
  canonical_path: string;
  commit: string;
  locator: string;
  title: string;
  excerpt: string;
  supports: string[];
  confidence: "strong" | "medium" | "weak" | string;
  verified: boolean;
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
  sections: ReportSection[];
  modules: ModuleReview[];
  evidence: EvidenceCard[];
  evidence_graph?: {
    markdown_claims: {
      claims: Array<{
        claim_id: string;
        kind: string;
        title: string;
        evidence_ids: string[];
      }>;
      evidence_to_claims: Record<string, string[]>;
    };
    evidence_map: {
      schema: string;
      evidence_map: Array<Record<string, unknown>>;
      domains: Record<string, string[]>;
      agents: Record<string, string[]>;
      modules: Record<string, string[]>;
    };
  };
  optional_sections: {
    cheat: boolean;
    ai: boolean;
    prompt_injection: boolean;
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
