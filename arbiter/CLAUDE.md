# CLAUDE.md — Arbiter Project Instructions

## What Arbiter Is

Arbiter is a smart conference companion app built as a CS412 final project at Boston University. It solves Type 3 Schizophrenia: the field-level failure where every conference session and vendor asserts primacy simultaneously, leaving attendees with contradictory notes and no coherent organizational takeaway. Existing conference apps (Whova, Eventee, Cvent) optimize for engagement. Arbiter optimizes for Catherine's success condition: leaving the conference with something she can present to her board Monday morning.

The app operates across three phases:
- **Before**: attendee provides organizational context, Arbiter recommends sessions and builds a plan
- **During**: attendee logs actual attendance and notes, Arbiter dynamically replans (should she skip a planned session in favor of a better one?) and produces a preliminary board recommendation that updates as the day progresses
- **After**: Arbiter produces the final board-ready priority ordering Catherine presents Monday morning

**MVP scope**: sessions only. Vendor visits are deferred to v2.

## Project Structure Rules

- All work lives under a single Django app called `arbiter` — do not create additional apps
- The existing git repository and deployment must continue to work
- Follow Stevens' CS412 coding standards: header comments on every file, docstrings on every function/method
- Every file must begin with: name, BU email, brief description of the file's purpose

## Tech Stack

- **Framework**: Django (Python)
- **Database**: SQLite for development, PostgreSQL for deployment
- **AI layer**: OpenRouter API (OpenAI-compatible), starting with `meta-llama/llama-3.3-70b-instruct:free`
- **Deployment**: Railway (existing deployment)
- **Auth**: Django's built-in auth system with LoginRequiredMixin throughout

## Data Models

All models live in `arbiter/models.py`.

### Conference
```
name: CharField(max_length=200)
location: CharField(max_length=200)
start_date: DateField()
end_date: DateField()
description: TextField(blank=True)
```

### Attendee
Represents a user's presence at a specific conference, including their organizational context.
The board_question field is the core differentiator — the decision architecture the field never built, now a database field.
NOTE: user is ForeignKey not OneToOneField — a user may attend multiple conferences over time.

```
user: ForeignKey(User, on_delete=CASCADE)
conference: ForeignKey(Conference, on_delete=CASCADE)
role: CharField(max_length=200)
industry: CharField(max_length=200)
board_question: TextField()
bio: TextField(blank=True, null=True)
created_at: DateTimeField(auto_now_add=True)

class Meta:
    unique_together = [('user', 'conference')]
```

### Session
```
conference: ForeignKey(Conference, on_delete=CASCADE)
title: CharField(max_length=300)
speaker: CharField(max_length=200, blank=True)
topic_area: CharField(max_length=200)
time_slot: DateTimeField()
description: TextField(blank=True)
```

### AttendanceLog
Two booleans work together for gap analysis:
- planned=True, attended=False → she planned this but skipped it
- planned=False, attended=True → she attended without planning it
- planned=True, attended=True → attended as planned

```
attendee: ForeignKey(Attendee, on_delete=CASCADE)
session: ForeignKey(Session, on_delete=CASCADE)
notes: TextField(blank=True)
contradiction_flagged: BooleanField(default=False)
contradiction_notes: TextField(blank=True)
planned: BooleanField(default=False)
attended: BooleanField(default=False)
timestamp: DateTimeField(auto_now_add=True)

class Meta:
    unique_together = [('attendee', 'session')]
```

### Synthesis
Persisted record of one AI-generated deliverable. Every AI call writes a new
row rather than returning an ephemeral response, so the evolution of
Catherine's board rec across the day becomes auditable, cacheable, editable,
and exportable. Multiple rows per (attendee, phase) are intentional — the
history IS the product story ("preliminary board rec that updates as the day
progresses"), so there is no unique_together constraint. UIs that want "the
latest" should order by `-created_at` and take the first row.

- `content` holds the raw AI output.
- `edited_content` holds Catherine's post-hoc edits; the export endpoint
  prefers it when present, so the review-before-present workflow is
  enforced by schema rather than UX.
- `cites` is the structural hook for the v2 citation-required hallucination
  mitigation: every claim in `content` should reference the AttendanceLog(s)
  it was derived from.
- `model_used` preserves provenance when swapping OpenRouter models between
  runs (LLaMA vs Claude vs anything else).

```
attendee: ForeignKey(Attendee, on_delete=CASCADE, related_name='syntheses')
phase: CharField(choices=[
    ('plan', 'Pre-conference session plan'),
    ('preliminary', 'Preliminary board recommendation'),
    ('final', 'Final board recommendation'),
])
content: JSONField()
edited_content: JSONField(null=True, blank=True)
model_used: CharField(max_length=200)
cites: ManyToManyField(AttendanceLog, blank=True, related_name='cited_by')
created_at: DateTimeField(auto_now_add=True)

class Meta:
    ordering = ['-created_at']
    verbose_name_plural = 'Syntheses'
```

## AI Layer

The AI layer lives in `arbiter/ai_services.py`. It makes three OpenRouter API calls.
The manual contradiction_flagged boolean is the reliable path — AI contradiction detection
is an enhancement on top, not a replacement.

**Every AI call must persist its output to a new Synthesis row** before
returning. This is non-negotiable: it powers caching across page refreshes
(critical for the free LLaMA rate limits), enables the "evolving preliminary
board rec" demo surface, and gives citations and edits somewhere to live. AI
endpoints should read from the latest Synthesis when available and only
re-call the LLM on meaningful state changes (new AttendanceLog, edited
notes, phase transition).

### 1. Before Phase — Session Plan Recommendation
Input: attendee context (role, industry, board_question) + full Session list for the conference
Output: prioritized shortlist of recommended sessions with reasoning grounded in the board question

### 2. During Phase — Dynamic Replanning + Preliminary Board Rec
Input: attendee context + planned sessions + attended sessions so far (with notes) + remaining sessions
Output:
  - Should she skip any remaining planned sessions in favor of unplanned ones? Why?
  - Preliminary board recommendation based on what she has heard so far

### 3. After Phase — Final Board Rec
Input: full AttendanceLog set with notes and contradiction flags + attendee context
Output: final board-ready priority ordering with:
  - Top 3 priorities given the board question, with reasoning
  - Key contradictions encountered and how to resolve them
  - Monday morning talking points ready to present

### OpenRouter Setup
```python
import openai

client = openai.OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=settings.OPENROUTER_API_KEY,
)

response = client.chat.completions.create(
    model="meta-llama/llama-3.3-70b-instruct:free",
    messages=[...],
)
```

The model is configurable via `settings.OPENROUTER_MODEL` so it can be swapped without touching view code.

## Views

Use generic class-based views wherever possible. Function-based views only for AI calls and gap analysis.

Key views:
- Conference: ListView, DetailView
- Attendee: CreateView (signup + board_question capture), UpdateView
- Session: ListView (filtered by conference), DetailView, CreateView, UpdateView, DeleteView
- AttendanceLog: CreateView, UpdateView, DeleteView, ListView (per attendee)
- AI views (function-based): session_plan, dynamic_replan, final_board_rec
- Gap analysis view (function-based): planned vs attended diff

## Auth Requirements

- All views require login (LoginRequiredMixin or @login_required)
- Attendees can only see and modify their own data — filter all querysets by request.user
- Registration flow (option b): signup creates User + first Attendee for a conference selected during signup, in one flow. Additional conferences require a separate "register for conference" action post-login. Do not try to create a universal AttendeeProfile — Attendee is intentionally conference-scoped.
- Standard Django LoginView and LogoutView wired in urls.py
- **Session create/update/delete: staff only** — use UserPassesTestMixin with test_func returning request.user.is_staff. Attendees should not be able to inject fake sessions into the conference agenda.
- **Conference delete cascade**: deleting a Conference cascades to all Sessions, Attendees, and AttendanceLogs. Intentional for test cleanup — understand this before deleting anything with real data attached.

## URL Structure

```
/                           — landing/home
/accounts/login/            — login
/accounts/logout/           — logout
/register/                  — create User + Attendee
/conferences/               — ConferenceListView
/conferences/<pk>/          — ConferenceDetailView
/sessions/                  — SessionListView
/sessions/<pk>/             — SessionDetailView
/attendance/log/            — AttendanceLogCreateView
/attendance/                — AttendanceLogListView
/ai/plan/                   — session_plan recommendation (POST)
/ai/replan/                 — dynamic_replan + preliminary board rec (POST)
/ai/synthesize/             — final_board_rec (POST)
/gap/                       — gap analysis view
```

## UI Requirements

- Clean, professional styling — this is a demo to a potential employer
- Mobile-friendly (responsive)
- The onboarding form (board_question, role, industry) must feel intentional not like a default Django form
- Contradiction flags should be visually distinct (color or icon)
- The end of day synthesis output should be formatted as a readable deliverable, not raw JSON

## Data Privacy Requirements

- board_question, bio, and AttendanceLog notes are sensitive — never log or expose in error messages
- User data collected with explicit consent disclosed at signup
- User-controlled deletion: deleting an Attendee cascades to all their logs
- No data sharing or selling — document this clearly in the UI

## Seed Data

Budget time for convincing fixtures. The synthesis only works if sessions have real topic tension.
Minimum viable fixture set:
- One conference (e.g. "RSAC 2026")
- 8-10 sessions with genuinely contradictory topic areas
- One attendee with a specific board_question like "what should our security investment priority be for next fiscal year"

Example session pairs with real tension:
- "AI is the next big thing — prepare now" vs "Get your fundamentals straight before chasing trends"
- "Identity is the new perimeter" vs "Fix your vulnerability management first"
- "Regulators are demanding compliance action" vs "Regulation is insufficient and counterproductive"

## What NOT to Do

- Do not create additional Django apps beyond `arbiter`
- Do not implement VendorVisit — deferred to v2
- Do not use paid OpenRouter models without explicit instruction
- Do not store API keys in code — use environment variables
- Do not use inline styles — CSS in static files
- Do not skip docstrings — Stevens deducts for missing documentation
- Do not prioritize gap analysis over core CRUD and one working AI call — get the basics first