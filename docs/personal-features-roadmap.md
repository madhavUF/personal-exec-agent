# Personal Features Roadmap

Features to make your agent "very very personal" — beyond Clawdbot.

---

## ✅ 1. Life Dashboard / Morning Brief (DONE)

**Status:** Implemented

- LLM-generated personalized brief at 8am
- Uses: calendar (today), goals, recent emails, weather
- Config: `config.yaml` → `morning_brief.weather_location`
- Test: `/brief` in Telegram

---

## 2. Relationship Graph

**Status:** Planned

- Track who matters: family, friends, colleagues
- "You haven't talked to Mom in 2 weeks"
- "John's birthday is next Tuesday"
- Store in memory with category `relationship`
- Proactive nudges based on last contact

---

## 4. Opportunity Radar

**Status:** Partial (recruiter exists)

- Jobs (recruiter agent)
- Gigs, events, talks
- "3 new PM roles matching your criteria"
- "AI in Product talk in Austin next week"
- Expand: configurable sources, filters

---

## 5. Decision Journal

**Status:** Planned

- Store decisions: "Deciding between X and Y — rationale: ..."
- Surfaces past reasoning when deciding again
- Tool: `save_decision`, `recall_decisions`
- Memory category: `decision`

---

## 6. Voice of You

**Status:** Planned

- Learn your communication style from sent emails
- Drafts that sound like you
- "Make it more casual" / "More formal"
- Use memory + sample emails for few-shot

---

## 7. Finance / Spend Awareness

**Status:** Planned

- Receipts (you forward or upload)
- Bill reminders (ATT, etc.)
- "You're over budget on dining"
- Tool: `log_transaction`, `get_spend_summary`
- Config: budget limits, bill due dates

---

## 8. Life Milestones and Rituals

**Status:** Planned

- "1 year since you started at Inductive Robotics"
- "Kids' school starts next week — checklist"
- Annual reviews, tax prep, renewals
- Memory: `milestone` category, date-based triggers

---

## 9. Context for External Agents

**Status:** Planned

- When you use ChatGPT/Clawdbot, inject: "User prefers X, avoid Y"
- Your agent as context layer for other tools
- Export: "My context for this task: ..."
- Browser extension or API for injection
