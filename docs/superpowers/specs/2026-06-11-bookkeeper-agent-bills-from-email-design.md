# Bookkeeper Agent — Design Spec

**Date:** 2026-06-11
**Repo:** https://github.com/csears17/bookkeeper-agent
**Status:** Approved design, pre-implementation
**First slice:** Bills from email → QuickBooks Online (draft-for-approval)

---

## 1. Purpose & context

An internal, Claude-powered agent for **Cole's own bookkeeping practice**. It runs
continuously, reads the mailboxes Cole keeps per client, and turns incoming vendor
invoices into QuickBooks Online (QBO) bills — **proposing** each write and waiting for
Slack approval before anything touches a client's books.

This is **not** the Coast Finance SaaS. It is a single-operator internal tool. The
"tenants" are Cole's client companies (7–15 of them), and Cole is the sole trusted
approver. There is no customer-facing product, no end-user auth, nothing to sell.

The agent is built to **grow**: bills-from-email is the first capability, but the
architecture (connectors + tools + a single write-gate + cost meter + audit log) is
general so future capabilities — posting journal entries, categorizing Ramp
transactions, categorizing QBO transactions, and a conversational "ask it to do more"
Slack channel — slot in as new tools rather than rewrites.

**Top priority: security and clarity across multiple books.** The nightmare case — a
bill landing in the wrong company's books — is designed out structurally (see §5).

---

## 2. Scope

### In scope (first build)
- Poll the administered mailboxes (one per client; mix of Google Workspace + Microsoft 365).
- Local pre-screen to drop obvious non-bills before any data leaves the machine.
- Claude classifies "is this an AP bill?" and, if so, extracts structured fields.
- Match to an existing QBO vendor; for an unknown vendor, **propose creating it** as part of the same approval.
- Propose an expense account/category from the client's **historical bills** for that vendor/item, with a confidence level and reasoning.
- Duplicate detection (vendor + invoice # + amount) — always on.
- Post a **Slack approval card** per bill (target company in bold, fields, suggested category, PDF).
- On approval: create vendor (if approved) → create bill → **attach the original PDF** to the QBO bill, in the correct company.
- **Level 0 autonomy** for all clients (nothing writes without Slack approval).
- Monthly **spend cap** with warning at 75% and hard stop at 100%.
- Append-only **audit log** of every read, proposal, approval/rejection, and write.

### Built but minimal (the bones, general by design)
- Connector layer, tool layer, the **write-gate**, the cost meter, and the audit log are
  capability-agnostic.

### Explicitly deferred to later slices
- Posting journal entries to QBO (e.g. driving the existing Stripe/Arketa/StubHub JE generators via API instead of CSV import).
- Categorizing Ramp transactions (+ asking when unsure).
- Categorizing QBO transactions.
- Autonomy **Level 1** (write-to-QBO-for-review) and **Level 2** (auto-post with receipt).
- Multiple Slack workspaces.
- The conversational Slack control plane ("ask it to do more"). The seam is built now; the channel is wired later.

---

## 3. Architecture

A single, always-on Python service. Small, single-purpose components communicating through
well-defined interfaces.

| Component | Job | Talks to |
|---|---|---|
| **Poller** | Every N minutes, ask each inbox "anything new since my last checkpoint?" | scheduler (self) |
| **Email connectors** | Read messages + download attachments. Two: Gmail + Microsoft Graph. | Gmail API, MS Graph |
| **Pre-screen** | *Local, no AI.* Drop obvious non-bills (no attachment + no AP keywords) before anything leaves the machine. | — |
| **Classifier/Extractor** | Claude decides "is this an AP bill?" and, if yes, extracts vendor, invoice #, dates, amount, line items. | Anthropic API |
| **Vendor matcher** | Match to an existing QBO vendor, or flag "new — propose creating." | QBO |
| **Categorizer** | Pull the client's past bills for that vendor/item; propose the account + confidence + reasoning. | QBO + Anthropic API |
| **Duplicate check** | vendor + invoice # + amount vs existing QBO bills → block dupes. | QBO |
| **Slack approval** | Post the bill card; wait for Approve / Edit / Reject. | Slack (Socket Mode) |
| **QBO writer** | On approval only: create vendor (if approved), create bill, attach PDF. | QBO |
| **Cost meter** | Convert each Claude call's token usage to USD; accumulate monthly; enforce the cap. | local DB |
| **Stores** | Encrypted tokens, client→inbox→company map, pending-bill queue, audit log, past corrections. | local SQLite |

### Engine
- **Claude API + tool use, manual agentic loop** (official Python `anthropic` SDK).
- Model **`claude-opus-4-8`** everywhere, with adaptive thinking. Per-capability model choice is changeable in config (e.g. a future cheaper pre-screen pass), but the default is Opus for everything.
- The **manual** loop (not the auto tool-runner) is deliberate: it lets the agent **pause before every financial write** and wait for Slack approval (human-in-the-loop), per Anthropic's guidance for self-hosted approval-gated agents.

### Three layers (extensibility)
1. **Connectors** — thin, well-bounded clients (Gmail, Graph, QBO, Slack; later Ramp).
2. **Tools** — each capability exposes typed tools to Claude (`extract_bill_fields`, `find_vendor`, `propose_category`, `check_duplicate`, and the write tool `create_bill`). New capability = new tools.
3. **The write-gate** — every book-mutating tool is tagged `requires_approval`. The loop intercepts those calls, routes to Slack, and executes only on approval (per the client's autonomy level). Read tools run freely.

### Two triggers, one core
- **Background poller** (scheduled inbox checks) — the first build.
- **Conversational Slack control plane** (deferred) — Cole messages the agent and it acts through the *same* tools and the *same* write-gate.

### Runtime
- **Dev/build:** Cole's Windows PC.
- **Production:** the Mac Mini (always-on, low-power, on-prem — keeps financial data off the cloud). Kept alive by `launchd`; while testing on the PC, by Task Scheduler / NSSM.
- The service is OS-agnostic; only the keep-alive mechanism differs. `.env` + encryption key + SQLite file copy across.
- **Networking:** Slack **Socket Mode** (outbound) + outbound API calls only → **no inbound ports, no router config, nothing exposed.**
- **Cloud (optional, later):** a small VM (~$7–12/mo) if Cole wants it off the home network; the Mac Mini is $0 incremental and more private.

### Storage
- **SQLite** (single local file). This is a single-operator internal tool, so Coast's
  multi-tenant Postgres + RLS would be overkill. Isolation between books is by company id
  in queries plus the structural binding in §5.

---

## 4. Data flow (one email)

```
poll inbox → new email → pre-screen
   ├─ not a candidate → DROP (log "screened, not AP"; no content kept)
   └─ candidate → Claude: is this a bill?
        ├─ no → DROP (no content kept)
        └─ yes → extract fields
              → QBO: match vendor + pull vendor history + dup check
              → Claude: propose category (+ confidence, + reasoning)
              → assemble draft bill (bound to THIS client's company)
              → Slack card  →  Cole approves
                    → QBO: create vendor? → create bill → attach PDF
                    → Slack receipt + audit log entry
```

- **Categorization** is history-driven: for each bill, pull the client's prior bills for
  the same vendor (and similar line items) from QBO, propose the account they used, with a
  confidence level and reasoning. New vendor / no precedent → lower confidence, flagged
  harder. Cole's corrections become precedent for next time.
- **Vendor handling:** match existing; for a new vendor, propose creating it (with parsed
  details) inside the same Slack approval — created only on approval.
- **PDF attachment:** the original invoice is attached to the QBO bill on post (audit trail).

---

## 5. Security, isolation & spend control

Security is the explicit top priority for this project (bank/financial data, multiple books).

### Multi-book isolation (core safety property)
- The `client → inbox → QBO-company` map is **fixed config**, never model-decided.
- A bill carries its origin company id from the moment it is read.
- The `create_bill` write tool **requires** that company id and **cannot** target another book.
- The Slack approval card always shows the **target company name in bold** for visual confirmation.

### Secrets & encryption
- Reuse Coast's `TokenCipher` (Fernet envelope encryption). All OAuth tokens (Gmail, Graph,
  QBO, Slack) encrypted at rest in SQLite.
- Encryption key in the OS keystore / env var, **never in git**.
- **Least-privilege scopes:** Gmail `gmail.readonly`, Graph `Mail.Read`, QBO
  `com.intuit.quickbooks.accounting`, Slack `chat:write` + interactivity. Nothing can send
  email, delete mail, or move money.

### Privacy / "forget" rule
- Local pre-screen drops obvious non-bills before anything is sent to Claude.
- **Confirmed bills:** persist extracted fields + the attachment + the source message id.
- **Everything else:** a metadata-only log line (message id, timestamp, "screened: not AP")
  — **never** the subject or body.
- Pursue org-level **Zero Data Retention** with Anthropic as a setup step. (Accurate framing:
  Anthropic does not train on API data; ZDR removes their short-term retention. It is an
  org-level arrangement, **not** a per-call toggle. The "forget" guarantee is enforced on
  our side regardless.)

### Spend cap (runaway-cost guard)
- The cost meter converts each Claude call's token usage to USD (Opus rate) and accumulates
  per calendar month in SQLite.
- A **hard gate** in front of the agentic loop:
  - **75%** of `MONTHLY_USD_CAP` → Slack **warning**.
  - **100%** → **hard stop**: the agent makes no further model calls and posts to Slack
    ("spend cap hit — paused until you raise it or the month rolls over").
- `MONTHLY_USD_CAP` lives in config, changeable anytime.
- Anthropic Console org-level spend limit set as a dumb backstop; the in-app cap is the
  granular control.

### Graduated autonomy (per client)
- **Level 0 (default, all clients):** Slack-approve before any write.
- **Level 1 (later):** write to QBO for review-in-QBO; Slack notifies.
- **Level 2 (later):** auto-post with a Slack receipt.
- Promote a client only when it has earned trust for *that* client.

### Audit log
- Append-only record of every read, proposed write, approval/rejection, and executed write
  — each stamped with the Claude `request_id` and the target company. Forensic trail across
  all books.

---

## 6. External setup (four developer apps)

All mailboxes are on **domains/tenants Cole administers** — the clean path.

| Service | What to create | Scope | Key point |
|---|---|---|---|
| **Google (Gmail)** | Cloud project → enable Gmail API → **service account** with **domain-wide delegation**, authorized in Workspace Admin for `gmail.readonly` | `gmail.readonly` | Reads mailboxes server-to-server — no per-account login, no refresh-token expiry, **no CASA review** (only possible because Cole administers the domain). |
| **Microsoft 365** | App registration in **Entra ID** → Graph **application** permission `Mail.Read` → admin consent | `Mail.Read` (app-only) | Lock down with an **application access policy** so the app reads only the specific client mailboxes, not the whole tenant. |
| **Intuit / QBO** | Intuit Developer account → one app → OAuth2 | `com.intuit.quickbooks.accounting` | Each client company authorizes once ("Connect to QuickBooks") → per-company `realmId` + refresh token (encrypted). No public App Store listing for private use, but **production keys require Intuit's app questionnaire**. |
| **Slack** | One Slack app → **Socket Mode** on | bot `chat:write` + interactivity | Socket Mode = app dials **out**; Approve/Reject buttons work with **no public webhook**. |

- **Note on QBO drafts:** QBO has no native "draft bill" state via API — relevant to a future
  autonomy Level 1 ("write to QBO for review"), which will need a specific technique (e.g.
  the QBO bill-approval workflow or a holding mechanism). Out of scope for the first build.
- **Today's task (no Mac needed):** create the four apps on their web dashboards and capture
  credentials into a gitignored `.env`.

---

## 7. Reliability & error handling

- **Token refresh/expiry:** QBO refresh tokens rotate (~100-day life) — refresh proactively;
  on a dead connection, Slack-alert naming the client. Same pattern for Google/Microsoft.
- **Idempotency (no double-posting):** danger case = crash *between* creating a vendor and
  the bill. Every write tool is idempotent — check-before-create plus the duplicate guard —
  so re-running never produces a second bill.
- **Poller checkpointing:** the per-inbox "last processed" marker advances **only after** an
  email is fully handled; a crash re-processes safely rather than skipping mail.
- **Claude API:** SDK auto-retries rate-limits/5xx; the spend-cap gate sits in front so
  retries can't blow the budget.
- **Pending bills survive restarts:** an unanswered Slack card stays queued in the DB and is
  re-surfaced on restart.

---

## 8. Testing

Mirrors the Coast approach (pytest, fake connectors, security tests as first-class).

- **Fake connectors** (FakeGmail / FakeGraph / FakeQBO / FakeSlack) so the suite never makes
  live calls.
- **Fixtures:** sample invoice PDFs for extraction; a newsletter and a personal email to
  prove non-AP classification.
- **Security/safety tests (first-class):**
  - **Privacy:** non-bill content is never persisted or logged.
  - **Company-binding:** a bill from client A's inbox *cannot* be written to client B.
  - **Spend cap:** hard stop fires at 100%.
  - **Duplicate:** same vendor + invoice # + amount is blocked.
- **Live integration:** against the **QBO sandbox** + a test mailbox before any real book is
  touched.

---

## 9. Open items / setup-time decisions
- Number of Workspace domains and 365 tenants (affects only how many one-time admin-consent
  clicks; does not change the design).
- Request org-level ZDR from Anthropic.
- Complete Intuit production-key questionnaire.
- Choose the QBO Level-1 "draft" technique when that slice is built.

---

## 10. Decisions log (from brainstorming)
- Whose books: **Cole's own practice** (7–15 client companies). Not the Coast SaaS.
- QBO platform: **QuickBooks Online only.**
- First capability: **bills from email** (most tedious; read + draft-for-approval).
- Email: **mix of Google Workspace + Microsoft 365**, all **administered by Cole**.
- Routing: **one inbox per client** → inbox = company (no guessing).
- Bill detection: **agent reads everything and judges**; non-AP content is immediately forgotten.
- Review surface: **Slack now**, with a per-client autonomy dial toward QBO drafts later.
- Categorization: **history-driven** (client's prior bills for that vendor/item) + confidence + correction loop.
- Vendor: **match, or propose-create on approval.**
- PDF: **attach original to the QBO bill** (default).
- Engine: **Claude API + manual tool-use loop, self-hosted, Opus 4.8 everywhere** (changeable).
- Spend cap: **warn at 75%, hard stop at 100%**, changeable.
- Runtime: **build on PC → deploy to Mac Mini.**
- Repo: **separate** (`bookkeeper-agent`), reusing Coast's `TokenCipher` pattern.
