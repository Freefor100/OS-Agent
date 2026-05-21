# Feature Schema Bank

This directory defines the structured feature layer used by OS-Agent D.

The natural-language QA files under `core/describe_stage_qa/` remain the
human-readable question view. At load time each question is enriched with a
stable `feature_id`, evidence requirements, negative-search policy, tri-state
rubric, anti-examples, and graph tags.

The v1 bank uses stage defaults plus deterministic per-question feature
synthesis, so all 02-09 technical questions are covered without duplicating the
full question text in another large JSON file.
