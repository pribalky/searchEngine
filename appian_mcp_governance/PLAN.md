# Governed Agentic Layer for Appian MCP — Open Questions, Gates & Build Plan

Status: draft v1, hashed out without live user confirmation (interactive Q&A
did not come back in this session — see "Assumptions made without
confirmation" below). Nothing here is executed yet; this is the scoping
artifact the build plan should be checked against before Phase 1 code lands.

---

## 0. Why this lives in this repo

This branch (`claude/appian-mcp-governance-raaphi`) was created against
`pribalky/searchengine`, which today is an unrelated UK job-search pipeline
(`job_search/`). There is no existing Appian-related code here. This plan
assumes the intent is to house the new portfolio project in a new top-level
folder (`appian_mcp_governance/`) in this same repo, leaving `job_search/`
untouched — not to replace or repurpose the job-search pipeline. **Flag this
if the actual intent was a separate repo.**

---

## 1. Open questions from the brief (Section 9) — hashed out

| # | Open question | Resolution |
|---|---|---|
| 1 | Which Appian MCP variant(s) does the org have enabled? | **Cannot be resolved by me — org-specific fact.** Treated as unconfirmed. Design decision: build the governance layer variant-agnostic, with the write-capable path (Tier 1–3) as the primary target since that's where the real risk sits, and the read-only Dev MCP as a strict subset that only ever exercises Tier 0. This means Phase 1–5 don't block on the answer; only a real-tenant Phase 6 demo does. |
| 2 | What sandbox/non-prod tenant is available? | **Cannot be resolved by me.** Not needed until Phase 6. Phase 1–5 build and test against a mock Appian MCP server (stub tool-call interface + fixture objects: sample process models, record types, expression rules with realistic UUIDs) so the governance logic is fully built and demoable without waiting on tenant provisioning. |
| 3 | Who are the internal stakeholders for Tier 2/3 approval? | **Cannot be resolved by me.** For the build, the approver is modeled as a role (`approver_id`, `approver_name`) parameterized in config — pluggable now, name a real person/forum before any real Tier 2/3 action ever executes against a live tenant. Given the author's own CoE role, the natural candidate is the Architecture Governance forum or a named senior architect, but this must come from you, not be assumed. |
| 4 | What existing logging/observability tooling should this integrate with? | **Cannot be resolved by me.** Default: structured JSON-lines logging to a local/append-only file (`logs/mcp_governance.jsonl`) as the source of truth, cheap and dependency-free, with a documented seam (one function: `emit_log_event()`) to redirect to Splunk/ELK/whatever the org already runs, without touching call sites. |

**Bottom line:** none of the four open questions block starting the build.
They block only the *real-tenant* demo (Phase 6). Phases 1–5 are fully
buildable and demoable today against mocks.

---

## 2. Assumptions made without confirmation (flag any of these to override)

Interactive clarification didn't come back in this session, so these
defaults were chosen to keep momentum. Cheap to change — say the word and
they get revised before more code depends on them.

| Decision | Default chosen | Why | How to override |
|---|---|---|---|
| Build order | Mock Appian MCP server first, real tenant later | Unblocks Phase 1–5 entirely; matches "observability before intelligence" principle already in the brief | Say if you already have live sandbox access today and want Phase 1 pointed at it directly |
| MCP variant to design for | Write-capable (full MCP), with read-only Dev MCP as a Tier-0-only subset | Full MCP is where the actual governance problem (UUID overwrite, Tier 2/3 writes) lives; designing for it also covers the read-only case for free | Say if only Dev MCP (read-only) will ever be available — this simplifies Layers 1/3 substantially (no write gate needed at all, just provenance + drift) |
| Language/stack | Python | Matches this repo's existing `job_search/` code, one toolchain, reuse of existing config/logging conventions | Say if you'd rather use TypeScript (closer to the MCP reference SDK ecosystem) |
| Tier 2/3 approval UX for v1 | CLI prompt (proxy pauses, prints diff, waits for y/n) | Fastest to build, sufficient for an internal demo; designed behind an `ApprovalChannel` interface so Slack/Teams/web UI can be swapped in later with no core changes | Say if you want Slack/Teams webhook or a small web UI built as the v1 approval surface instead |
| Repo/folder | `appian_mcp_governance/` inside `pribalky/searchengine`, this branch | Matches the branch/repo you're already on | Say if this should be a separate repo |

---

## 3. Prerequisites (needed before each phase, not before starting)

- **Phase 1 (proxy skeleton + logging):** none. Buildable now with mocks.
- **Phase 2 (risk classification engine):** none — rules table is authored
  from the brief's own tier definitions (Section 4, Layer 1) plus Appian
  object/action taxonomy, which can be drafted from public Appian docs and
  refined later against real object types.
- **Phase 3 (provenance tagging):** none — this is a wrapper around however
  content enters agent context; works identically against mock or real MCP.
- **Phase 4 (diff/dry-run gate):** needs a `get_object_state(uuid)` call
  against *something* — mock fixtures are sufficient to prove the mechanism;
  the UUID-collision scenario can be simulated directly (seed a fixture
  object, then feed the agent a "hallucinated" UUID that collides with it).
- **Phase 5 (drift/eval harness):** needs baseline test cases per governed
  object — for the mock phase, hand-author 3–5 fixture objects with simple
  expected-behavior assertions (e.g., an expression rule's output for given
  inputs) to prove the harness catches drift.
- **Phase 6 (real tenant demo + rollout):** **hard-blocked** on the four
  unresolved org-specific questions above (MCP variant enabled, sandbox
  tenant + credentials, named approver, logging-tool integration target).
  Nothing in Phase 6 should be attempted until those are answered.

---

## 4. Mandatory options (decisions that must be locked before Phase 2 code, since they shape the rules table and data model)

1. **Tier taxonomy is fixed as given in the brief** (Tier 0 Read / Tier 1
   Reversible write / Tier 2 Irreversible or cross-object write / Tier 3
   Cross-system or production-published) — no changes proposed, it's already
   clean and audit-explainable. Locking this in as-is.
2. **Classification key = (object_type × action_type × environment).** Needs
   an authoritative list of Appian object types (process model, record type,
   expression rule, group, folder, connected system, site, subprocess) and
   action types (create, read, update, publish, delete, move/reparent,
   permission-change) before the rules table can be exhaustive. Draft list
   will ship in Phase 2 from public Appian docs; **must be reviewed by
   someone with real Appian admin/platform knowledge before being trusted
   for a live tenant** — this is exactly the kind of thing that looks
   complete but silently misses an object type.
3. **Provenance model = binary (`trusted` / `untrusted`) per the brief**,
   not a graded/confidence-scored model. Simpler to reason about and audit;
   locking this in as-is rather than over-engineering a scored system nobody
   asked for.
4. **Diff gate scope = every Tier 2/3 write, no exceptions**, including
   writes an agent claims are "just a draft" — the enforcement point is the
   tier classification, not agent self-reporting.

---

## 5. Hard gates (block progress entirely, not just Phase 6)

- **No write action ever executes against a real Appian tenant without
  passing through the Tier classifier and, for Tier 2/3, the diff gate.**
  This is non-negotiable per the brief's own thesis and is the thing the
  whole project exists to guarantee — it gets enforced at the proxy's single
  choke point (every tool call passes through one dispatcher function), not
  scattered across call sites, so there's one place to audit.
- **No live/production Appian credentials get used in this build session or
  committed to the repo.** Mock-first isn't just a sequencing convenience,
  it's the safety rail — this environment has no verified access to any real
  Appian tenant, and it shouldn't invent or request credentials.
- **Untrusted-tagged content can never itself trigger a Tier 2/3 call**
  (brief Section 4, Layer 2) — enforced as a hard check in the dispatcher,
  not a convention agents are asked to follow.
- **Phase 6 (real tenant) is gated on the four open org-questions above.**
  Not a soft preference — the plan should not proceed to a real tenant until
  those are answered by you.

---

## 6. Revised phase plan

| Phase | Deliverable | Blocked on |
|---|---|---|
| 0 | This document — scoping, defaults, gates | — (done, pending your review) |
| 1 | Mock Appian MCP server (stub tool-call interface + fixture objects); proxy skeleton that intercepts every tool call; structured JSONL logging (actor, input, output, latency, timestamp) for every call, no intelligence yet | Nothing — buildable now |
| 2 | Risk classification rules table (object × action × env → tier) + dispatcher hook: Tier 0/1 pass through, Tier 2/3 pause | Nothing — buildable now; rules table needs your review before trusting it against a real tenant later |
| 3 | Provenance tagging wrapper (trusted/untrusted) + hard rule enforcement in dispatcher | Nothing — buildable now |
| 4 | Diff/dry-run gate: fetch current state (mock), diff vs proposed, CLI approval prompt; UUID-collision scenario demoed explicitly | Nothing — buildable now |
| 5 | Drift/eval harness: baseline test cases for 3–5 fixture objects, re-run after each change set, drift report | Nothing — buildable now |
| 6 | Point at a real non-prod Appian tenant; live demo; internal rollout package (architecture diagram, demo script, governance-mapping one-pager) | **Hard-blocked** on: MCP variant confirmed, sandbox tenant + credentials, named Tier 2/3 approver, logging-tool integration decision |

---

## 7. Next step

If the defaults in Section 2 are acceptable, Phase 1 (mock MCP server +
proxy skeleton + logging) can start immediately — say so and it'll be built
on this branch. If any default should change (especially stack choice or
mock-vs-real sequencing), say which one before Phase 1 code lands, since
Phase 2's rules table and Phase 4's diff format both take a dependency on
Phase 1's data shapes.
