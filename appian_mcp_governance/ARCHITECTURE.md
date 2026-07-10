# Scoring Model, Architecture & Dependencies

Companion to `PLAN.md`. This is a design document only — **no code has been
written yet, pending confirmation** (see Section 4).

---

## 1. What needs defined scoring

The brief calls Layer 1 a "rules table," which is right, but a rules table
still needs its input dimensions and escalation logic nailed down before
it's codeable. Four things need a defined scoring/classification model;
one thing (provenance) is deliberately *not* scored, and one (drift) uses a
different kind of score entirely.

### 1.1 Tier classification — base table

Primary key: **(object_type × action_type × environment) → base tier**

**Object types** (draft, from public Appian docs — needs a real Appian
admin/platform review before being trusted against a live tenant, per
`PLAN.md` Section 4.2):

| Object type | Notes |
|---|---|
| Process model | Core workflow logic |
| Record type | Data model + record actions |
| Expression rule | Reusable logic, high fan-out risk |
| Decision table | Business rule logic |
| Interface | UI definition |
| Constant | Config value, looks trivial, can be high blast-radius if shared |
| Group | Security/permission boundary |
| Folder | Organizational, but folder-level permission changes cascade |
| Connected system / integration | External system credentials/config |
| Site | Public-facing surface |
| Subprocess (reusable) | Special case — see blast-radius modifier below |
| Document / data type | Lower risk generally |

**Action types**: `read`, `create`, `update`, `publish`, `delete`,
`move / reparent`, `permission-change`, `deploy`.

**Environment**: `dev/sandbox`, `test/UAT`, `production`.

**Base rule, stated once instead of as a full matrix** (the full matrix
is mechanical from these rules and belongs in a config file, not prose):

- `read` → always **Tier 0**, regardless of object type or environment.
- `create` / `update` on a **non-shared, draft-only** object in
  `dev/sandbox` or `test/UAT` → **Tier 1**.
- `publish`, `delete`, `move/reparent`, `permission-change`, or any write to
  a **group, folder, connected system, or site** → **Tier 2** minimum,
  regardless of environment.
- Any write action where `environment == production` → **Tier 3** floor,
  no exceptions, even if the same action would be Tier 1 in sandbox.
- `deploy` (package promotion across environments) → always **Tier 3**.

### 1.2 Escalation modifiers (applied after the base tier lookup)

These bump a tier up, never down — the base table is the floor:

| Modifier | Trigger | Effect |
|---|---|---|
| **Blast radius** | Target object is referenced by ≥1 other object (e.g. a reusable subprocess called by N process models, a group used by M objects) | +1 tier (Tier 1 → Tier 2 minimum) |
| **Reversibility** | Action has no native Appian revert/version-history path (e.g. hard delete) | Forced to Tier 2 minimum, even if base table said Tier 1 |
| **UUID collision** | Agent declares a "create" but the target UUID already exists in current tenant state (the core UUID-overwrite risk from the brief) | Forced to Tier 2 minimum **and** always routed through the diff gate, regardless of what tier the action would otherwise be — this is the single most important override in the whole system |
| **Untrusted provenance** | Content driving this call is tagged `untrusted` (see 1.3) and the tier is already 2/3 | No tier change, but **hard block**: cannot be auto-approved or approved by anything other than an explicit fresh human confirmation — this is enforcement, not scoring |

### 1.3 Provenance — deliberately binary, not scored

Per `PLAN.md` Section 4.3, this stays `trusted` / `untrusted`, no
confidence score. Scoring this on a gradient would invite exactly the kind
of "looks precise, isn't auditable" failure mode the whole project is
positioned against. The only thing that needs defining is **what tags as
`untrusted`**:

- Content read from an uploaded document, case record, or external
  integration payload → `untrusted`.
- Content that is the human operator's direct, current-turn instruction →
  `trusted`.
- Content read from Appian via a prior **Tier 0 read call** in the same
  session → `untrusted` by default (it's platform data, not operator
  instruction) **unless** explicitly re-confirmed by the human at the diff
  gate — which, for Tier 2/3, already happens by construction (Layer 3's
  approval step doubles as Layer 2's "trusted re-confirmation").

### 1.4 Drift score — a different kind of score, not a tier

Per governed object, a **baseline set of input → expected-output
assertions** is authored once. After each change set, re-run and produce:

- `pass_count / total_count` per object (simple ratio, not a tier)
- A **drift flag** (boolean) if any assertion that passed at baseline now
  fails
- A **reference drift** note if the object's dependency set changed (new/
  removed calls to other objects) even if all assertions still pass — this
  is the "many small safe-looking edits" case the brief calls out
  specifically

This is a reporting metric, not a gate — it doesn't block anything by
itself in v1, it produces the periodic drift report. (Whether a repeated
drift flag should *eventually* escalate future changes to that object to
Tier 2 is a reasonable v2 idea, not in scope now.)

---

## 2. Architecture

### 2.1 Components

| # | Component | Responsibility | Depends on |
|---|---|---|---|
| 1 | **Rules/Config Store** | YAML/JSON: object & action taxonomy, tier base table, escalation modifiers, approver config, provenance policy. Governance-as-code — versioned in this repo. | — |
| 2 | **Audit Logger** | `emit_log_event()` — one seam, JSONL append-only log of every tool call: actor, tool, object/uuid, action, tier, provenance, decision, approver, latency. | — |
| 3 | **Mock Appian MCP Server** | Stub backend implementing `list_objects`, `get_object`, `create_object`, `update_object`, `publish_object`, `delete_object` against JSON fixture objects (process models, record types, expression rules with realistic UUIDs). Stands in for the real Appian MCP server until Phase 6. | — |
| 4 | **Dispatcher / Proxy core** | The single choke point. Every tool call from the agent passes through here, in this order: log intent → classify (3) → provenance-check → branch (Tier 0/1 pass through, Tier 2/3 → diff gate) → execute against backend (Mock or real) → log outcome. | 1, 2, 3 |
| 5 | **Risk Classifier** | Pure function: `classify(object_type, action_type, environment, blast_radius, reversible, uuid_collision) -> (tier, rationale)`. Implements 1.1/1.2. No side effects, fully unit-testable. | 1 |
| 6 | **Provenance Tagger** | Tags each inbound content unit `trusted`/`untrusted`, threads the tag through the call context, enforces the hard block in 1.2. | 2 |
| 7 | **Diff / Dry-Run Gate** | For Tier 2/3 only: calls backend's `get_object` for current state, computes a structured diff vs proposed change, renders it, hands to Approval Channel. | 3, 4, 5 |
| 8 | **Approval Channel** | Pluggable interface (`ApprovalChannel.request(diff) -> Decision`). v1 implementation: CLI prompt. Slack/web UI are future implementations of the same interface — dispatcher never changes. | 7 |
| 9 | **Drift / Eval Harness** | Offline, not in the live call path. Loads baseline assertions per object, re-runs against backend, produces drift report. Runs after a change set or on a schedule. | 2, 3 |
| 10 | **CLI entrypoints** | `run-proxy`, `run-drift-report`, `--fixtures` demo mode (mirrors the existing `job_search` module's `--fixtures --dry-run` convention for consistency in this repo). | 1–9 |

### 2.2 Data / control flow

```
                 ┌─────────────────────┐
   Agent (e.g.   │                     │
   Claude Code / │──tool call─────────▶│  4. Dispatcher (choke point)
   any MCP        │                     │        │
   client)       │◀──result/decision───│        │  a. log intent (2)
                 └─────────────────────┘        │  b. classify (5, uses 1)
                                                  │  c. provenance check (6)
                                                  │  d. tier branch:
                                                  │
                                     Tier 0/1 ────┼───▶ execute directly ──▶ backend (3)
                                                  │                              │
                                     Tier 2/3 ────┤                              │
                                                  ▼                              │
                                         7. Diff/Dry-Run Gate ◀──current state───┘
                                                  │
                                                  ▼
                                         8. Approval Channel (CLI v1)
                                                  │
                                     approve ─────┼───▶ execute ──▶ backend (3)
                                     reject ──────┴───▶ abort, log decision (2)

                                         9. Drift Harness runs separately,
                                            post-change-set, against backend (3),
                                            writes drift report.
```

### 2.3 Data model (shapes flowing between components)

- `ToolCallEvent`: `{actor, tool_name, object_type, object_uuid, action, environment, args, provenance, timestamp}`
- `ClassificationResult`: `{tier, rationale, modifiers_applied: []}`
- `DiffResult`: `{object_uuid, current_state, proposed_state, field_diffs: [], uuid_collision: bool}`
- `ApprovalDecision`: `{decision: approve|reject, approver_id, timestamp, comment}`
- `AuditLogEvent`: superset of the above, one JSONL line per tool call, terminal record.
- `DriftReport`: `{object_uuid, baseline_pass_count, current_pass_count, drift_flag, reference_drift_notes, generated_at}`

### 2.4 Open architecture decision — needs your call, not mine

**Does Phase 1 speak actual MCP protocol (JSON-RPC over stdio/SSE via the
`mcp` Python SDK), or an in-process Python interface for now, upgraded to
real MCP transport once pointed at a real Appian MCP server?**

- **In-process interface first (recommended):** Dispatcher, Mock server,
  and CLI are plain Python function calls. Zero protocol dependency, fastest
  to build and test, all the governance logic (classification, diff,
  approval, drift) is fully exercised and demoable. The MCP transport layer
  becomes a thin adapter added in Phase 6 — it doesn't change any
  governance logic, only how calls arrive/leave.
- **Real MCP protocol from Phase 1:** More representative of the final
  deployed shape, lets you literally point Claude Code at the mock server
  today to demo the interception live. Costs an extra dependency (`mcp`
  Python SDK) and more moving parts (transport, schema registration) before
  any governance logic exists.

Leaning towards the in-process-first option given the brief's own
"observability before intelligence" sequencing principle, but this is your
call to make now since it affects Phase 1's very first line of code.

---

## 3. Dependencies

### 3.1 External libraries

- Python stdlib only for the governance core: `json`, `dataclasses`,
  `argparse`, `difflib` (or a small hand-rolled structured dict-diff).
- `pyyaml` — only if the rules table is authored as YAML rather than JSON
  (readability vs. zero-dependency tradeoff — minor, default to JSON to add
  nothing new, matches `job_search/config.py`'s plain-Python-dict style).
- `pytest` — already a dev dependency in this repo.
- `mcp` (official Python MCP SDK) — **only** if Section 2.4 is resolved in
  favor of real MCP protocol from Phase 1; otherwise deferred to Phase 6.

### 3.2 Build-order dependency graph (not the same as the phase numbers in `PLAN.md` — this is what technically depends on what)

```
1. Rules/Config Store  ─┐
2. Audit Logger         ├──▶ 4. Dispatcher core ──▶ 5. Risk Classifier
3. Mock MCP Server     ─┘         │                      │
                                   │                      ▼
                                   │              6. Provenance Tagger
                                   ▼
                          7. Diff/Dry-Run Gate ──▶ 8. Approval Channel (CLI)
                                   │
3. Mock MCP Server ────────────────┘

2. Audit Logger  ─┐
3. Mock MCP Server├──▶ 9. Drift/Eval Harness   (parallel branch, independent of 4–8)

1–9 ──▶ 10. CLI entrypoints
```

Practical read: **1, 2, 3 have no dependencies and can be built in any
order (or in parallel)**. Everything else in the live-call path funnels
through **4 (Dispatcher)**, which is why it's the first thing built after
the three leaf components. The **Drift Harness (9)** is a separate branch
that only needs the logger and backend — it can be built any time after 2
and 3, independent of the dispatcher/classifier/gate work.

### 3.3 Mapping to `PLAN.md` phases

| PLAN.md phase | Components delivered |
|---|---|
| Phase 1 | 1, 2, 3, 4 (skeleton — pass-through only, no real classification yet) |
| Phase 2 | 5, wired into 4 |
| Phase 3 | 6, wired into 4 |
| Phase 4 | 7, 8 |
| Phase 5 | 9 |
| Phase 6 | Swap 3 (mock) for a real MCP transport to a real tenant; everything else unchanged |

---

## 4. Confirmation checklist before Phase 1 starts

1. Scoring model in Section 1 (base tier table, escalation modifiers,
   provenance-is-binary, drift-is-separate) — accept as-is, or change
   something?
2. Architecture in Section 2 — accept the 10-component split and the
   dispatcher-as-single-choke-point design?
3. **Section 2.4 — in-process interface first, or real MCP protocol from
   Phase 1?** This is the one decision that changes Phase 1's actual first
   lines of code, so it's the one most worth confirming explicitly.
4. JSON (not YAML) for the rules config, per 3.1 — fine, or prefer YAML?

Nothing further will be built until you confirm.
