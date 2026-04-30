# Arbiter — the final project

A smart conference companion app for security professionals. Built for
the CS412 final project, designed against a real product thesis.

## What it is, in one paragraph

Most conference apps (Whova, Cvent, Sched, Eventee) optimize for the
*conference organizer's* success: registration, networking, vendor lead
capture. Arbiter optimizes for the *attendee's external audience*. The
mid-career security manager whose board sent her to RSAC with a specific
question. The CISO who has to present a one-page priority deck on Monday
morning. The IT director whose CFO wants to know what $15K of conference
spend produced. Arbiter helps her arrive prepared, capture what she
heard, and leave with a board-ready synthesis grounded in the question
her organization actually asked.

The differentiator is `board_question` as a first-class data field.
Every AI recommendation is grounded in it. Every page renders it
visibly. The UI treats it as a pull quote because that's what it is:
the question every other piece of synthesis answers against.

## Quickstart

From the `django/` directory:

```bash
# 1. Install dependencies
pipenv install

# 2. Configure environment
cp .env.example .env
# Then edit .env and paste your real OPENROUTER_API_KEY
# (sign up at https://openrouter.ai if you don't have one;
# free LLaMA 3.3 70B works for the demo)

# 3. Set up the database
pipenv run python manage.py migrate

# 4. Load the SecureWorld Boston 2026 agenda (69 sessions)
pipenv run python manage.py load_secureworld arbiter/secureworld.html

# 5. Seed demo users, attendees, attendance logs, vendor visits
pipenv run python manage.py seed_demo

# 6. Run the dev server
pipenv run python manage.py runserver

# 7. Visit http://127.0.0.1:8000/arbiter/
```

## Sample user credentials

Sign in at `/arbiter/accounts/login/`:

| Username    | Password              | Persona                                                                                     |
|-------------|-----------------------|---------------------------------------------------------------------------------------------|
| `catherine` | `arbiter-demo-2026`   | Security Manager, Financial Services. Canonical demo user. 4 attendance logs and 3 vendor visits seeded. |
| `marcus`    | `arbiter-demo-2026`   | CISO, Healthcare                                                                            |
| `priya`     | `arbiter-demo-2026`   | VP of Security, SaaS / Technology                                                           |
| `david`     | `arbiter-demo-2026`   | IT Director, Manufacturing                                                                  |

The dashboard, attendance log, vendor list, and synthesis history all
populate immediately for `catherine` after `seed_demo`.

## Required environment variables

In `.env` (gitignored; see `.env.example` for the template):

| Variable             | Required   | Purpose                                              |
|----------------------|------------|------------------------------------------------------|
| `DJANGO_SECRET_KEY`  | Yes        | Standard Django secret                               |
| `DJANGO_DEBUG`       | Yes        | `True` in dev, `False` in prod                       |
| `OPENROUTER_API_KEY` | Yes for AI | OpenRouter API key (free tier works)                 |
| `OPENROUTER_MODEL`   | No         | Defaults to `meta-llama/llama-3.3-70b-instruct:free` |

Without `OPENROUTER_API_KEY` set, the AI synthesis features fail
gracefully (the views catch the exception and surface a Django
`messages.error` redirect back to the dashboard). Everything else
works.

---

## How Arbiter works

### The three phases

Catherine's experience of a conference has three temporal phases, and
Arbiter has a distinct AI surface for each:

**Before.** She tells Arbiter what her board sent her to answer, picks
the conference she's attending, and optionally describes how she plans
to spend her non-session time. The AI reads the full agenda and her
context, returns a prioritized session shortlist with reasoning.

**During.** She logs sessions as she attends them: notes the way she'd
write in any notebook, plus a casual soft-signal prompt ("did anything
in this session feel different from something you heard earlier?"). She
optionally logs vendor booth conversations on the same casual format.
Mid-conference, she can ask the AI to suggest plan adjustments and
produce a preliminary board recommendation that updates as the day
progresses.

**After.** She triggers the final synthesis. The AI reads everything
she captured and produces a board-ready document: a diagnosis of what
was pulling against what, contradictions resolved against the board
question, three priorities with rationale, Monday morning talking
points. Each claim cites the AttendanceLog or VendorVisit it was drawn
from. She reviews, edits the prose if she wants, presents.

### Catherine, the persona

The product is built for a specific user shape: a competent mid-career
security professional whose organization sent her to a conference to
answer a specific strategic question. She is neurotypical. She does not
experience the conference as a series of clean intellectual
contradictions; she experiences it as diffuse overwhelm, a feeling of
not being able to prioritize without quite knowing why.

This shapes the data model. The `tension_notes` field on AttendanceLog
and VendorVisit asks her a casual question ("did anything feel
different from something you heard earlier?") rather than the
analytical one ("describe the contradiction"). She doesn't have to
identify what contradicts what. The AI does that work, reading her
notes and tension prompts together.

The `contradiction_flagged` boolean stays available for the rare case
where she has the explicit version in mind, tucked behind an advanced
disclosure on the form.

### The board question

The architectural differentiator. A free-text TextField on the Attendee
model. Catherine writes it once at registration, refines it on her
profile if needed. Every AI prompt opens with it. Every synthesis is
anchored against it. The UI renders it as a pull quote in italic Source
Serif on the dashboard and on every synthesis page.

Catherine's seeded board question:

> What should our security investment priority be for the next fiscal
> year given a flat budget? Present the top three priorities with
> rationale for the April 27 board meeting.

Specific. Time-bound. Tied to a real decision. The clearer the
question, the sharper the synthesis it grounds.

---

## Architecture

### Data model (six models)

Defined in [arbiter/models.py](arbiter/models.py).

| Model            | Purpose                                                                                                              | Key fields                                                                                                  |
|------------------|----------------------------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------|
| **Conference**   | Standalone root model. Every other model relates to it directly or transitively.                                     | name, location, start_date, end_date, description                                                           |
| **Attendee**     | A user's registration at a specific conference plus their organizational context. FK to User and Conference. unique_together on the pair. | role, industry, **board_question**, bio, **non_session_time_budget**                                        |
| **Session**      | One session on a conference's agenda. Staff-managed.                                                                 | conference, title, speaker, topic_area, time_slot, description                                              |
| **AttendanceLog**| Records planned and actual attendance plus notes. The `(planned, attended)` pair forms the gap-analysis truth table. | session, notes, **tension_notes**, contradiction_flagged, contradiction_notes, planned, attended, timestamp |
| **VendorVisit**  | Booth conversations from the expo floor. Mirrors AttendanceLog's note-field semantics. No uniqueness constraint so the same vendor can be logged across multiple days. | vendor_name, category, notes, **tension_notes**, contradiction_flagged, contradiction_notes, timestamp     |
| **Synthesis**    | Persisted AI-generated deliverable. Multiple rows per (attendee, phase) is intentional — the history of the recommendation IS the product story. | phase, content (JSON), edited_text (TextField), model_used, cites (M2M to AttendanceLog), created_at         |

Conference is the standalone model in the structural sense (no foreign
keys; satisfies the CS412 rubric requirement). Attendee is the center
of gravity in the product sense (it's where the UI is anchored). The
distinction is intentional: a conference exists in the world
independently; an attendee is a relationship between a User and a
Conference.

### App layout

```
django/
├── arbiter/                    # the final-project app
│   ├── ai_services.py          # OpenRouter calls, prompt construction, citation attachment
│   ├── admin.py                # all six models registered with custom list displays
│   ├── apps.py
│   ├── forms.py                # AttendanceLogForm, VendorVisitForm, RegistrationForm,
│   │                           #   AttendeeForm, SynthesisEditForm
│   ├── models.py               # Conference, Attendee, Session, AttendanceLog, VendorVisit, Synthesis
│   ├── secureworld.html        # SecureWorld Boston 2026 agenda HTML, used by load_secureworld
│   ├── secureworldscraper.py   # BeautifulSoup parser, infers topic_area from keywords
│   ├── urls.py                 # 25+ named URL patterns
│   ├── views.py                # CBVs for CRUD; FBVs for AI calls and gap analysis
│   ├── management/
│   │   └── commands/
│   │       ├── load_secureworld.py    # parses agenda HTML into Session rows
│   │       └── seed_demo.py           # idempotent demo data: users, attendees, logs, vendors
│   ├── migrations/
│   ├── static/arbiter/
│   │   └── arbiter.css         # working register + document register styles
│   └── templates/arbiter/      # ~20 templates extending base.html
├── cs412/                      # Django project shell (settings, root urls)
└── manage.py
```

### AI synthesis layer

[arbiter/ai_services.py](arbiter/ai_services.py) exposes three
functions, each corresponding to one phase. All three:

- Use OpenRouter's OpenAI-compatible API
- Default to LLaMA 3.3 70B Instruct on the free tier
- Build phase-specific prompts with attendee context, agenda data, and Catherine's logs
- Force structured JSON output via `response_format={'type': 'json_object'}`
- Fall back gracefully on parse failures (regex extraction, then raw text capture in `Synthesis.content`)
- Persist a new `Synthesis` row per call (multiple rows per phase intentional — the evolution is the product story)
- Treat vendor pitches as lower epistemic weight than session content, with explicit prompt instruction
- Use neutral framing for tensions ("the conference surfaced tension between X and Y") rather than adversarial language

The three calls:

| Function                            | Phase   | Reads                                                        | Returns                                                              |
|-------------------------------------|---------|--------------------------------------------------------------|----------------------------------------------------------------------|
| `generate_session_plan(attendee)`   | Before  | Attendee context + non_session_time_budget + full agenda     | `diagnosis`, `recommended_sessions`, `warnings`                      |
| `generate_dynamic_replan(attendee)` | During  | Attendee context + logs + vendor visits + remaining sessions | `diagnosis`, `replan_suggestions`, `preliminary_priorities`          |
| `generate_final_board_rec(attendee)`| After   | Attendee context + all logs + all vendor visits              | `diagnosis`, `contradictions`, `priorities`, `talking_points`        |

Each call also returns `supporting_log_ids` and `supporting_vendor_ids`
arrays inside its priority and contradiction items. The
`SynthesisDetailView` resolves these into actual model objects so the
template can render them as clickable links pointing back to the
original AttendanceLog or VendorVisit edit pages.

### Two-register design system

CSS tokens defined in [arbiter/static/arbiter/arbiter.css](arbiter/static/arbiter/arbiter.css):

| Token         | Value     | Used for                                                            |
|---------------|-----------|---------------------------------------------------------------------|
| `--bg`        | `#FAF8F4` | Warm off-white page background                                      |
| `--surface`   | `#FFFFFF` | Card surfaces atop the background                                   |
| `--ink`       | `#1A1F2E` | Deep charcoal primary text                                          |
| `--ink-soft`  | `#5C6370` | Secondary text, eyebrow labels                                      |
| `--rule`      | `#E5E0D8` | Hairline borders                                                    |
| `--ai`        | `#3B5BA5` | Slate blue: AI provenance, citations, topic categorization          |
| `--tension`   | `#C8853D` | Amber: tension flags, contradictions, "edited" markers              |

Two type families:

- **Inter** for the working register: notebook feel, dense but
  considered, used on dashboard, attendance, vendor, profile,
  registration, conference list, session list. Reading-width column
  where appropriate.
- **Source Serif 4** for the document register: generous spacing,
  italic accents, used on the synthesis detail page only. Plus a peek
  on the dashboard's `board_question` pull quote.

The two registers serve different jobs. Working surfaces are where
Catherine *captures* content. The document surface is where she *reads
and presents* the deliverable. The visual language signals which mode
she's in.

---

## Feature surface

### Onboarding

- **`/arbiter/`** — landing page for anonymous visitors. Authenticated users redirect to dashboard.
- **`/arbiter/register/`** — combined User + Attendee signup in one atomic transaction. Three grouped fieldsets (Account, Conference, Context). The `board_question` field gets visually distinct slate-blue card treatment.
- **`/arbiter/accounts/login/`** and **`/logout/`** — Django auth wrapped in working-register styling.

### Dashboard

**`/arbiter/dashboard/`** — the authenticated workspace surface. Top to bottom:

1. Greeting + conference registration line
2. **Board question pull quote** in italic Source Serif inside a slate-blue tinted card
3. Three primary action cards: Log a session, Log a vendor, Get my board recommendation (the third is a POST form with a loading indicator)
4. Two secondary AI triggers: Plan my sessions (before), Replan + preliminary rec (during)
5. Latest synthesis preview with View history link
6. Non-session time budget block (or empty-state encouragement)
7. Two-column Recent activity: sessions and vendors, side by side

### Conferences and sessions

- **`/arbiter/conferences/`** — every conference as a card with session count, "Registered" chip when applicable
- **`/arbiter/conferences/<pk>/`** — single conference page with the agenda regrouped by day and time, sessions render as exclusive-open accordion cards (`<details name="agenda">`, native HTML, no JS)
- **`/arbiter/sessions/`** — cross-conference browse with conference + topic filter dropdowns
- **`/arbiter/sessions/<pk>/`** — single session detail with "Log this session" CTA that deep-links to the AttendanceLog form with the session pre-selected

### Attendance log (full CRUD)

The natural CRUD demonstration for the rubric. One workflow exercises all four operations:

1. **Create**: log a session (notes + tension prompt + planned/attended toggles)
2. **Read**: list view shows every log Catherine has, newest first
3. **Update**: edit a log to add notes or fix a misflagged entry
4. **Delete**: remove a wrongly logged session

URLs at `/arbiter/attendance/`, `/log/`, `/<pk>/edit/`, `/<pk>/delete/`. All ownership-scoped via `get_queryset` filtering by `attendee__user=request.user`.

### Vendor visits

Parallel CRUD surface for booth conversations. Same notebook card treatment as attendance logs. The form is optimized for ~30-second mobile entry between sessions: vendor name, category, notes, tension prompt, with the contradiction toggle and notes tucked behind an advanced disclosure.

URLs at `/arbiter/vendors/`, `/log/`, `/<pk>/edit/`, `/<pk>/delete/`.

### Profile

**`/arbiter/profile/`** — edit form for the active Attendee. Five fields: role, industry, board_question (rendered prominently in slate-blue card), bio, non_session_time_budget. Resolves the user's most recent Attendee via `_AttendeeRequiredMixin.get_active_attendee()` so URL-pk-guessing is impossible.

### Synthesis

- **`/arbiter/synthesis/`** — chronological list of every recommendation Catherine has generated. Each card shows phase, conference, generation timestamp, "Edited" tag if applicable, diagnosis snippet.
- **`/arbiter/synthesis/<pk>/`** — single synthesis rendered in the document register (Source Serif, generous spacing, numbered priorities with serif numerals, citation footnotes). Two render paths: structured AI content (with clickable citations) when `edited_text` is empty; the user's plain-text version (with linebreaks-preserved paragraphs) when populated.
- **`/arbiter/synthesis/<pk>/edit/`** — single 24-row textarea pre-populated with a plain-text rendering of the AI's structured output. Catherine edits prose, never JSON. The original `content` field is never overwritten.

### Gap analysis report

**`/arbiter/gap/`** — satisfies the rubric's "search/filter producing a meaningful report" requirement. Filter bar with topic dropdown and text search across session titles, notes, tension_notes, and contradiction_notes. The report aggregates each topic_area into three counts: planned-and-attended, planned-but-skipped, unplanned-drop-ins. Tells Catherine something she didn't see by reading rows individually: which topic areas pulled her off her plan.

### Staff-only Session management

For agenda authors (the conference organizer in the real-product framing; the developer in the class-project framing). URLs at `/arbiter/sessions/new/`, `/<pk>/edit/`, `/<pk>/delete/`. Gated by `StaffRequiredMixin`. Day-to-day session loading happens via the `load_secureworld` management command instead.

---

## Authorization model

Defense in depth across the view layer:

- **`LoginRequiredMixin`** on every authenticated view
- **`_AttendeeRequiredMixin`** on AttendanceLog, Vendor, Synthesis, and Profile views: redirects users with no Attendee row to registration, since those flows depend on having one
- **`StaffRequiredMixin`** on Session create/update/delete: prevents attendees from injecting fake sessions into a conference's agenda
- **Ownership scoping via `get_queryset`** on every user-data view: AttendanceLog, VendorVisit, Synthesis, Profile. URL-pk-guessing returns 404, not 403

The seeded users are non-staff. Only the developer's superuser can author the agenda through the staff-only Session views; for normal use, `load_secureworld` and `seed_demo` populate the data.

---

## Loading state and error handling

- **AI buttons** on the dashboard intercept `submit` events via vanilla JS, disable the button, change the label to "Generating recommendation" with a pulsing dot, dim and pulse the whole card. The OpenRouter call to LLaMA 3.3 70B can take 5-30 seconds; without this feedback users may re-click and stack duplicate requests against the rate-limited free tier.
- **AI views** wrap the OpenRouter call in `try/except`, log the exception, surface a Django `messages.error` to the user, and redirect back to the dashboard. JSON parse failures fall through to a `parse_error: True` Synthesis row with the raw model output preserved for review.
- **JSON output validation** is best-effort. The fallback path tries a regex extract for JSON-wrapped-in-prose responses; if even that fails, the raw text is preserved on the Synthesis row and the detail page renders it inside a `<pre>` block with a "could not be parsed" notice.

---

## Acknowledged limitations and v2 roadmap

Things deliberately deferred from v1, in roughly the order I'd build them post-class:

1. **Confidentiality flags on AttendanceLog and VendorVisit.** Notes from a closed-door / Chatham House / NDA-bound session shouldn't go to a third-party AI service unmodified. Three flag levels (public, anonymize, exclude) plus prompt-level honoring of each.
2. **Per-speaker / per-source credibility.** The vendor-vs-session weighting is a heuristic that doesn't catch sponsored sessions or vendor employees on panels. v2 captures speaker affiliation on the Session row and lets Catherine flag a session as vendor-sponsored.
3. **Engagement-aware synthesis.** Sparse notes today produce confidently-hallucinated synthesis. v2 detects sparse logs, asks the AI to degrade its confidence accordingly, or prompts Catherine to revisit her notes before generating.
4. **Citation enrichment in the edited path.** Once Catherine edits the plain-text synthesis, citation links become text mentions. v2 could keep them clickable via Markdown-style anchors that survive the edit round-trip.
5. **Web search integration.** OpenRouter's `:online` model variants append live web search results to the prompt, which would help with current-events references (recent CVEs, vendor announcements, regulatory news). Costs pennies per call but breaks the free-tier commitment. One env var change to enable.
6. **Organization model above Attendee.** The enterprise wedge: multiple Attendees from the same organization sharing a board_question, the AI synthesizing across the team rather than per-attendee. Architecturally clean, requires a v3 schema migration.
7. **LLM-based topic classification** to replace the current keyword-rule topic_area inference in `secureworldscraper.py`.
8. **Per-section structured edit form** for Synthesis to replace the single-textarea plain-text edit.
9. **Multi-conference flow for an existing user.** Currently signup creates one Attendee for one Conference. "Register for another" is a separate post-class feature.
10. **Self-hosted Inter and Source Serif** via local woff2 instead of Google Fonts CDN.

---

## CS412 rubric mapping

| Requirement                                          | How Arbiter satisfies it                                                                                                                       |
|------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------|
| ≥4 models with FK relationships, one standalone      | 6 models. Conference is standalone. Attendee, Session, AttendanceLog, VendorVisit, Synthesis all chain off it.                                |
| Forms for all four CRUD operations                   | AttendanceLog has full CRUD via dedicated forms. VendorVisit too. Plus Attendee profile, registration, synthesis edit, staff-only Session CRUD. |
| Generic CBVs + FBVs where needed                     | CBVs on every CRUD surface. FBVs on the three AI endpoints and gap_analysis (where structured CBV scaffolding would not save more than it cost). |
| URL mapping                                          | 25+ named URLs across 8 logical sections, all under `/arbiter/`.                                                                              |
| Multiple HTML templates with navigation              | ~20 templates, all extending `base.html` with context-aware nav.                                                                              |
| Searching/filtering producing a meaningful report    | Gap analysis: filter by topic, text search across notes, planned-vs-attended breakdown by topic_area. Plus session list filtering by conference and topic. |
| Visually appealing UI                                | Two-register design system (Inter + Source Serif), considered typography hierarchy, hover states, document-register synthesis page, responsive. |
| Documentation                                        | Header comments and docstrings on every Python file, this README, agent-instruction file at `arbiter/CLAUDE.md`.                              |
| External API (extra credit)                          | OpenRouter integration with three structured-output AI calls + JSON parse fallback + citation enrichment.                                     |
| Implementing things not covered in class             | LLM-based synthesis grounded in web-scraped seed data, BeautifulSoup parsing into Django ORM, accordion UX with native exclusive-open `<details>`, two-register design system, citation enrichment from AI output to clickable links, JSON-mode prompt engineering with structured-output fallback. |

---
