# Arbiter — Project Documentation

**Author**: Ian Sun | isun@bu.edu
**Course**: CS412 Full-Stack Development, Boston University
**Instructor**: Aaron Stevens
**Semester**: Spring 2026

---

## What Arbiter Solves

Every major conference — RSAC, Gartner, industry summits — produces what I call Type 3 Schizophrenia: every session and vendor asserts primacy simultaneously, with no arbitration layer. Identity is the new perimeter. No, fix vulnerability management first. AI changes everything. No, get your fundamentals straight.

Existing conference apps (Whova, Eventee, Cvent) optimize for engagement: bookmarks, gamification, networking, lead capture for vendors. Not one of them helps the attendee leave with something coherent to present to their organization Monday morning.

Arbiter is built for Catherine's success condition, not the conference organizer's. Catherine is a competent mid-career security manager whose board sent her to the conference with a specific question to answer. She takes careful notes across four days and comes home less able to prioritize than when she left — not because she wasn't paying attention, but because the field gave her cacophony instead of coherence.

Arbiter changes that.

---

## The Three Phases

**MVP scope**: sessions only. Vendor visits are deferred to v2.

### Phase 1: Before the Conference
Catherine provides her role, industry, and the specific question her organization sent her to answer. Arbiter recommends sessions worth prioritizing before she arrives — during a low-pressure window when she can think clearly, ask colleagues, and reference documents. She walks into the conference with a shortlist, not a 400-session agenda.

### Phase 2: During the Conference
Catherine logs sessions and quick notes at the break — the form is designed for 30-second entry. Arbiter dynamically replans: should she skip a planned session in favor of something better given what she has already heard? It also produces a preliminary board recommendation that updates as the day progresses.

### Phase 3: After the Conference
Arbiter produces the final board-ready priority ordering — structured with top priorities, contradiction resolutions, and Monday morning talking points Catherine can present directly.

---

## Data Models

### Conference
Represents a conference event. The root model — all other models relate to it directly or through Attendee.

| Field | Type | Notes |
|---|---|---|
| name | CharField | Conference name |
| location | CharField | City/venue |
| start_date | DateField | |
| end_date | DateField | |
| description | TextField | Optional |

### Attendee
Represents a user's presence at a specific conference. The board_question field is the decision architecture the field never built, now expressed as a database field. User is ForeignKey (not OneToOneField) so a user can attend multiple conferences. unique_together on (user, conference) prevents duplicate registrations.

| Field | Type | Notes |
|---|---|---|
| user | ForeignKey(User) | Django auth user |
| conference | ForeignKey(Conference) | |
| role | CharField | e.g. "Security Manager" |
| industry | CharField | e.g. "Financial Services" |
| board_question | TextField | The specific question the org sent them to answer |
| bio | TextField | Optional additional context |
| created_at | DateTimeField | Auto |

### Session
Represents a single session on the conference agenda.

| Field | Type | Notes |
|---|---|---|
| conference | ForeignKey(Conference) | |
| title | CharField | |
| speaker | CharField | Optional |
| topic_area | CharField | e.g. "Identity", "AI", "Compliance" |
| time_slot | DateTimeField | |
| description | TextField | Optional |

### AttendanceLog
Records planned and actual attendance. Two booleans work together for gap analysis: planned=True/attended=False means she planned it but skipped it; planned=False/attended=True means she attended without planning it.

`unique_together = [('attendee', 'session')]` — prevents double-logging the same session, which would break gap analysis counts.

| Field | Type | Notes |
|---|---|---|
| attendee | ForeignKey(Attendee) | |
| session | ForeignKey(Session) | |
| notes | TextField | What Catherine heard |
| contradiction_flagged | BooleanField | Did this contradict something else? |
| contradiction_notes | TextField | What the contradiction was |
| planned | BooleanField | True = intended to attend |
| attended | BooleanField | True = actually attended |
| timestamp | DateTimeField | Auto |

### Synthesis
Persisted record of one AI-generated deliverable. Every AI call (session_plan, dynamic_replan, final_board_rec) writes a new Synthesis row rather than returning an ephemeral response. Multiple rows per (attendee, phase) are intentional — the history IS the product story ("preliminary board rec that updates as the day progresses"). `content` is the raw AI output; `edited_content` is Catherine's post-hoc edits (the export endpoint prefers `edited_content` when present, enforcing the review-before-present workflow at the schema layer rather than the UX layer). `cites` is the M2M to AttendanceLog that gives the v2 citation-required hallucination mitigation somewhere to attach.

| Field | Type | Notes |
|---|---|---|
| attendee | ForeignKey(Attendee) | related_name='syntheses' |
| phase | CharField | choices: 'plan', 'preliminary', 'final' |
| content | JSONField | Raw AI output |
| edited_content | JSONField | Catherine's edits; nullable |
| model_used | CharField | OpenRouter model id used for this row |
| cites | ManyToManyField(AttendanceLog) | related_name='cited_by'; which logs this synthesis was derived from |
| created_at | DateTimeField | Auto |

**VendorVisit**: deferred to v2.

---

## AI Layer

The AI layer lives in `arbiter/ai_services.py` and makes three calls through OpenRouter. The manual `contradiction_flagged` boolean is the reliable path — AI contradiction detection is an enhancement on top, not a replacement.

**Every AI call must persist its output to a new Synthesis row** before returning. This is non-negotiable: it powers caching across page refreshes (critical for the free LLaMA tier's rate limits), enables the "evolving preliminary board rec" demo surface, and gives citations and edits somewhere to live. AI endpoints should read from the latest Synthesis when available and only re-call the LLM on meaningful state changes.

### session_plan (before phase)
**Purpose**: Given Catherine's organizational context and the full session list, recommend which sessions to prioritize.

**Input**: role, industry, board_question + full Session list (titles, topic areas, times)
**Output**: prioritized shortlist with reasoning grounded in the board question

### dynamic_replan (during phase)
**Purpose**: Given what Catherine has already attended, should she adjust her plan? Also produces a preliminary board rec.

**Input**: attendee context + planned sessions + attended sessions with notes + remaining sessions

**Output**: structured JSON with two keys:
```json
{
  "replan_suggestions": [...],
  "preliminary_priorities": [...]
}
```
The structured response format is required — the downstream UI renders these two outputs separately and will break on unstructured text.

### final_board_rec (after phase)
**Purpose**: Produce the deliverable Catherine presents Monday morning.

**Input**: full AttendanceLog set with notes and contradiction flags + attendee context
**Output**:
1. Top 3 priorities given the board question, with reasoning
2. Key contradictions encountered and how to resolve them
3. Monday morning talking points ready to present directly

**Design note for all three calls**: Be explicit in prompts. LLaMA is more literal than Claude — do not assume it will infer the connection between session topic and organizational mandate without being told. Define contradiction explicitly: priority disagreement counts, topic diversity does not.

---

## Views Reference

| View | Type | Purpose |
|---|---|---|
| ConferenceListView | ListView | Browse available conferences |
| ConferenceDetailView | DetailView | Conference detail with session list |
| AttendeeCreateView | CreateView | Onboarding: create User + Attendee + capture board_question |
| AttendeeUpdateView | UpdateView | Edit profile and organizational context |
| SessionListView | ListView | Sessions filtered by conference |
| SessionDetailView | DetailView | Session detail |
| SessionCreateView | CreateView | Add a session to a conference |
| AttendanceLogCreateView | CreateView | Log that you attended a session |
| AttendanceLogListView | ListView | Your attendance log for the day |
| session_plan | Function-based | Before phase AI call |
| dynamic_replan | Function-based | During phase AI call + preliminary board rec |
| final_board_rec | Function-based | After phase AI call |
| gap_analysis | Function-based | Planned vs attended diff |

---

## Auth and Privacy

All views require authentication. Attendees can only access their own data — views filter by `request.user` before returning any queryset.

**Session create/update/delete: staff only.** Use `UserPassesTestMixin` with `test_func` returning `request.user.is_staff`. Any authenticated attendee being able to add sessions would let them inject fake sessions into the conference agenda. Catherine is an attendee, not a conference organizer.

**Conference delete cascade**: deleting a Conference cascades to all Sessions, Attendees, and AttendanceLogs attached to it. Intentional for test data cleanup — understand this before deleting any Conference with real data attached.

Registration flow (option b):
1. User fills out UserCreationForm fields
2. Plus role, industry, board_question (required), bio (optional), and selects a Conference
3. CreateView creates User, then creates Attendee linked to that User and that Conference in one flow
4. Redirect to that conference's session list after registration

Registering for an additional conference is a separate post-login action — not part of initial signup. Attendee is conference-scoped by design.

Sensitive fields (board_question, bio, AttendanceLog.notes) are never logged, never exposed in error messages, and never shared with third parties. Explicit consent to data collection is disclosed at the registration form before submission.

---

## Environment Variables Required

```
SECRET_KEY=
DEBUG=False
DATABASE_URL=
OPENROUTER_API_KEY=
OPENROUTER_MODEL=meta-llama/llama-3.3-70b-instruct:free
ALLOWED_HOSTS=
```

---

## Coding Standards

Per CS412 requirements:

Every Python file begins with:
```python
# Author: Ian Sun | isun@bu.edu
# Description: [brief description of this file's purpose]
```

Every function and method includes a docstring:
```python
def final_board_rec(attendee):
    """
    Calls the OpenRouter API to generate a board-ready priority ordering
    from the attendee's full day of session logs and contradiction flags.

    Args:
        attendee: Attendee model instance with related AttendanceLogs prefetched

    Returns:
        dict with keys: priorities, contradictions, talking_points
    """
```

---

## Deployment

Hosted on Railway. Environment variables set in Railway dashboard — never in code. Static files served via WhiteNoise. Database: PostgreSQL on Railway.

Deploy command: `python manage.py migrate && python manage.py collectstatic --noinput`

---

## What Makes Arbiter Different From Existing Conference Apps

| Feature | Whova / Eventee / Cvent | Arbiter |
|---|---|---|
| Session discovery | Yes | Yes |
| Personalized agenda | Behavioral (what you click) | Mandate-driven (what your org needs) |
| Organizational context as data entity | No | Yes — board_question field |
| Contradiction detection | No | Yes |
| Dynamic replanning during conference | No | Yes |
| Preliminary board rec updating in real time | No | Yes |
| Board-ready synthesis | No | Yes |
| Planned vs actual gap analysis | No | Yes |
| Optimizes for | Engagement | Catherine's Monday morning |