# Always-On Money-Earning Agent

**Goal**: An orchestrator agent that runs 24/7 on your Lenovo laptop, pursues your money-earning objectives, and coordinates specialized sub-agents based on your instructions.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    Lenovo Laptop (always-on)                             │
│                                                                         │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │              ORCHESTRATOR (main money agent)                       │  │
│  │  • Reads your instructions (config / DB)                           │  │
│  │  • Decides what to do next (LLM loop)                              │  │
│  │  • Invokes sub-agents, aggregates results                          │  │
│  │  • Surfaces actions to you (Telegram, dashboard)                   │  │
│  └─────────────────────────────┬─────────────────────────────────────┘  │
│                                │                                         │
│        ┌───────────────────────┼───────────────────────┐                 │
│        ▼                       ▼                       ▼                 │
│  ┌──────────────┐      ┌──────────────┐      ┌──────────────┐            │
│  │ Job Search   │      │ Freelance    │      │ OpenClaw     │            │
│  │ Agent        │      │ / Gig Agent │      │ (existing)   │            │
│  │              │      │              │      │              │            │
│  │ • Role map   │      │ • Upwork     │      │ • Automation │            │
│  │ • Outreach   │      │ • Fiverr     │      │ • Coding     │            │
│  │ • Pipeline   │      │ • Local gigs │      │ • System     │            │
│  └──────────────┘      └──────────────┘      └──────────────┘            │
│                                                                         │
│  State: data/money_agent.db  |  Instructions: config/money_instructions.yaml │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Core Concepts

### 1. User Instructions (your "north star")

Stored in `config/money_instructions.yaml` (or similar). You define:

- **Objectives**: e.g. "Earn $X/month via remote PM roles" or "Land 2 freelance gigs this quarter"
- **Constraints**: industries to avoid, companies to skip, hours you can work
- **Cadence**: how often to apply, check job boards, follow up
- **Channels**: job boards, Upwork, local Austin gigs, etc.

Example:

```yaml
objectives:
  - "Find remote product manager roles (Austin or US remote)"
  - "Apply to 5 relevant jobs per week"
  - "Respond to Upwork invites within 24h"

constraints:
  industries_avoid: ["crypto", "gambling"]
  min_comp: 120000
  work_style: "remote or hybrid Austin"

channels:
  job_search: true
  freelancing: true
  local_gigs: false  # enable when Austin business builder is wired

cadence:
  job_scan_hours: [8, 14, 20]   # check job boards 3x/day
  outreach_followup_days: 3
  weekly_goal_applications: 5
```

### 2. Orchestrator Loop

The main agent runs a **tick loop** (e.g. every 15–30 min or on a schedule):

1. **Load state**: last actions, pipeline, goals from `money_agent.db`
2. **Load instructions**: from `money_instructions.yaml`
3. **Ask LLM**: "Given state + instructions + time, what should I do next?"
4. **Execute**: call sub-agent(s) or tools (web search, email draft, etc.)
5. **Persist**: save results, update pipeline
6. **Notify**: send summary/actions to Telegram or dashboard

The orchestrator has tools like:

- `invoke_job_search_agent(task, context)` → runs job-search sub-agent
- `invoke_freelance_agent(task, context)` → runs freelance/gig sub-agent
- `invoke_openclaw(message)` → delegates to OpenClaw (already exists)
- `web_search`, `read_webpage` → for job board scraping, research
- `create_email_draft`, `search_emails` → for outreach
- `save_document` → store role maps, outreach templates, pipeline

### 3. Sub-Agents

Each sub-agent is a **focused module** with its own prompt + tools:

| Sub-Agent      | Purpose                          | Tools / Data                          |
|----------------|----------------------------------|---------------------------------------|
| **Job Search** | Role mapping, outreach, pipeline | Job-search-accelerator skill, web search, resume/RAG |
| **Freelance** | Upwork/Fiverr monitoring, proposals | Web scrape (or API if available), draft proposals |
| **OpenClaw**  | Automation, coding, system tasks | Already exists via `query_openclaw`   |

Sub-agents return structured results (e.g. JSON) so the orchestrator can decide next steps.

---

## Implementation Phases

### Phase 1: Orchestrator + Instructions (start here)

- [ ] `config/money_instructions.yaml` — your objectives, constraints, cadence
- [ ] `src/money_agent/orchestrator.py` — tick loop, LLM call, state load/save
- [ ] `data/money_agent.db` — SQLite for pipeline, last_run, actions
- [ ] Run as a background process or systemd/launchd service on the Lenovo

### Phase 2: Job Search Sub-Agent

- [ ] `src/money_agent/subagents/job_search.py` — uses job-search-accelerator workflow
- [ ] Tools: role map, positioning, outreach templates, application tracker
- [ ] Integrate with your existing RAG (resume, docs) and Gmail (outreach)

### Phase 3: Freelance / Gig Sub-Agent

- [ ] `src/money_agent/subagents/freelance.py` — monitor Upwork, Fiverr, etc.
- [ ] Web scrape or use APIs where available
- [ ] Draft proposals based on your instructions

### Phase 4: Always-On Deployment (Lenovo)

- [ ] `scripts/start_money_agent.sh` — start orchestrator + optional Telegram
- [ ] systemd (Linux) or launchd (macOS) for auto-restart
- [ ] Optional: run main `app.py` on Mac, money agent on Lenovo; they can share `data/` via sync or network

---

## Lenovo Setup Checklist

When you get the laptop:

1. **Clone repo** and install deps (`pip install -r requirements.txt`)
2. **Copy config** — `.env`, `credentials/.secrets.env`, `config/money_instructions.yaml`
3. **Edit instructions** — your objectives, constraints, cadence
4. **Run orchestrator** — `python -m src.money_agent.orchestrator` (or via script)
5. **Enable Telegram** — so the agent can push "5 new jobs to apply to" or "Upwork invite — draft response?"
6. **Auto-start** — systemd service or cron for the tick loop

---

## Data Flow Example

1. **8:00 AM** — Orchestrator tick: "Time to scan job boards"
2. **Orchestrator** → invokes Job Search Agent: "Find PM roles matching my criteria"
3. **Job Search Agent** → web_search, read_webpage, filters by instructions
4. **Returns** — list of 5 jobs with titles, companies, URLs
5. **Orchestrator** → saves to pipeline, creates Telegram message: "5 new jobs. Reply APPLY 1 to draft application."
6. **User** — "APPLY 1" via Telegram
7. **Orchestrator** → invokes Job Search Agent: "Draft application for job 1 using my resume"
8. **Job Search Agent** → RAG (resume), creates tailored draft
9. **Orchestrator** → create_email_draft or save_document, notify user

---

## Security & Privacy

- **Secrets**: Same pattern as main agent — `credentials/.secrets.env` for API keys
- **Approvals**: Sensitive actions (send email, submit application) can go through approval queue
- **Egress**: Web research for job boards — ensure `ALLOW_PUBLIC_WEB_RESEARCH` or allowlist as needed
- **Data**: Pipeline and instructions stay on your machine; no third-party job-board APIs required for MVP

---

## Quick Start

```bash
# Copy and edit your instructions
cp config/money_instructions.yaml.example config/money_instructions.yaml

# Run one tick
python -m src.money_agent.orchestrator

# Run continuously (every 30 min)
python -m src.money_agent.orchestrator --loop

# Or use the script
./scripts/start_money_agent.sh --loop 15
```

Enable web research for job scanning: set `ALLOW_PUBLIC_WEB_RESEARCH=true` in `.env` if using strict egress.

---

## Next Steps

1. Edit `config/money_instructions.yaml` with your objectives and constraints
2. Expand Job Search sub-agent to use job-search-accelerator references (role mapping, outreach templates)
3. Add Freelance sub-agent (Upwork/Fiverr monitoring)
4. Deploy to Lenovo: systemd service or cron for `--loop`
