# Author: Ian Sun | isun@bu.edu with help from Claude Code
# Description: Service layer for Arbiter's three AI synthesis calls. Each
# function (generate_session_plan, generate_dynamic_replan,
# generate_final_board_rec) builds a phase-specific prompt from an
# Attendee's data, calls OpenRouter through the OpenAI-compatible client,
# parses the structured JSON response, and persists a new Synthesis row.
# The view layer in arbiter/views.py invokes these functions and redirects
# to the synthesis detail page; nothing in this module touches HTTP
# directly.

from __future__ import annotations

import json
import logging
import re
from typing import Any

import openai
from django.conf import settings

from arbiter.models import (
    AttendanceLog, Attendee, Session, Synthesis, VendorVisit,
)


logger = logging.getLogger(__name__)


# Cap on description length per session when listing the agenda in a
# prompt. Keeps the request payload below ~30K tokens for the typical
# SecureWorld-scale conference (69 sessions). Without this, full
# descriptions blow past the LLaMA free-tier rate limits.
_MAX_DESCRIPTION_CHARS = 320


def _client() -> openai.OpenAI:
    """Return a configured OpenAI-compatible client pointed at OpenRouter.

    Reads the API key and model from Django settings so the model can be
    swapped via environment variable without touching this module.
    """
    return openai.OpenAI(
        base_url='https://openrouter.ai/api/v1',
        api_key=settings.OPENROUTER_API_KEY,
    )


def _attendee_header(attendee: Attendee) -> str:
    """Render the attendee context block included at the top of every
    prompt. Captures the organizational mandate and the optional
    non-session time budget that the before-phase planner respects."""
    name = attendee.user.first_name or attendee.user.username
    parts = [
        f"Attendee: {name}",
        f"Role: {attendee.role}",
        f"Industry: {attendee.industry}",
        f"Conference: {attendee.conference.name}",
        f"Board question: {attendee.board_question}",
    ]
    if attendee.bio:
        parts.append(f"Bio: {attendee.bio}")
    if attendee.non_session_time_budget:
        parts.append(
            f"Non-session time the attendee has planned: "
            f"{attendee.non_session_time_budget}"
        )
    return '\n'.join(parts)


def _format_session_list(sessions, include_descriptions: bool = True) -> str:
    """Render a session queryset for inclusion in a prompt. Each row
    starts with the session id (so the LLM can cite by id) followed by
    time, topic, title, and a truncated description."""
    lines = []
    for session in sessions:
        when = session.time_slot.strftime('%a %m/%d %I:%M %p')
        head = (
            f"[session_id={session.id}] {when} | "
            f"{session.topic_area} | {session.title}"
        )
        if session.speaker:
            head += f' — {session.speaker}'
        lines.append(head)
        if include_descriptions and session.description:
            desc = session.description.strip().replace('\n', ' ')
            if len(desc) > _MAX_DESCRIPTION_CHARS:
                desc = desc[:_MAX_DESCRIPTION_CHARS].rstrip() + '...'
            lines.append(f"    {desc}")
    return '\n'.join(lines)


def _format_logs(logs) -> str:
    """Render an AttendanceLog queryset for prompt inclusion. Surfaces
    notes, tension_notes, and contradiction flags so the LLM has all
    the signal Catherine captured."""
    if not logs:
        return '(no sessions logged yet)'
    lines = []
    for log in logs:
        when = log.session.time_slot.strftime('%a %m/%d %I:%M %p')
        head = (
            f"[log_id={log.id}] {when} | {log.session.topic_area} | "
            f"{log.session.title} (planned={log.planned}, "
            f"attended={log.attended})"
        )
        lines.append(head)
        if log.notes:
            lines.append(f"    Notes: {log.notes.strip()}")
        if log.tension_notes:
            lines.append(f"    Tension: {log.tension_notes.strip()}")
        if log.contradiction_flagged and log.contradiction_notes:
            lines.append(
                f"    Manually flagged contradiction: "
                f"{log.contradiction_notes.strip()}"
            )
    return '\n'.join(lines)


def _format_vendor_visits(visits) -> str:
    """Render a VendorVisit queryset for prompt inclusion. Same shape
    as _format_logs but anchored to vendor_name + category instead of a
    Session FK."""
    if not visits:
        return '(no vendor visits logged)'
    lines = []
    for visit in visits:
        head = (
            f"[vendor_id={visit.id}] {visit.vendor_name} "
            f"({visit.category})"
        )
        lines.append(head)
        if visit.notes:
            lines.append(f"    Notes: {visit.notes.strip()}")
        if visit.tension_notes:
            lines.append(f"    Tension: {visit.tension_notes.strip()}")
        if visit.contradiction_flagged and visit.contradiction_notes:
            lines.append(
                f"    Manually flagged contradiction: "
                f"{visit.contradiction_notes.strip()}"
            )
    return '\n'.join(lines)


def _call_llm(system_prompt: str, user_prompt: str) -> tuple[dict[str, Any], str]:
    """Issue an OpenRouter call expecting a JSON response.

    Args:
        system_prompt: instructions to the model. Should specify the
            exact output JSON shape — the LLaMA free-tier model is
            literal and will hallucinate structure without explicit
            schemas.
        user_prompt: the data the model is reasoning over. Built by
            the calling generate_* function.

    Returns:
        A tuple of (parsed_json, raw_response). The first element is
        the parsed dict, or an empty dict if parsing failed; the second
        is the raw model output for debugging or fallback display.
    """
    client = _client()
    response = client.chat.completions.create(
        model=settings.OPENROUTER_MODEL,
        messages=[
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': user_prompt},
        ],
        response_format={'type': 'json_object'},
        temperature=0.6,
    )
    raw = response.choices[0].message.content or ''
    try:
        return json.loads(raw), raw
    except json.JSONDecodeError:
        # Some models wrap JSON in prose or markdown fences; try to
        # extract the first JSON object substring as a fallback.
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0)), raw
            except json.JSONDecodeError:
                pass
        logger.error("Could not parse JSON from LLM response: %s", raw)
        return {}, raw


# ---------------------------------------------------------------------------
# Phase 1: Before — session plan recommendation
# ---------------------------------------------------------------------------

_SESSION_PLAN_SYSTEM = """\
You are an advisor sitting next to a security professional at a conference.
They have a specific question their board sent them to answer. Your job is
to recommend which sessions on the agenda will best help them answer that
question, weighted by their organizational context.

You must output JSON with this exact shape:

{
  "diagnosis": "1-2 sentences on what kinds of sessions will best serve the board question.",
  "recommended_sessions": [
    {"session_id": <int>, "rank": <int>, "rationale": "1-2 sentences on why this session fits."}
  ],
  "warnings": "Optional 1-2 sentences flagging time conflicts with the attendee's non-session budget, or gaps in the agenda relative to the board question."
}

Recommend 5-10 sessions, ranked by relevance to the board question. Only
cite sessions by their numeric session_id; do not invent titles. If the
attendee has a non-session time budget, do not recommend more sessions than
fit in their available time.
"""


def generate_session_plan(attendee: Attendee) -> Synthesis:
    """Before-phase synthesis: prioritized session shortlist. Reads the
    full agenda for the attendee's conference, asks the LLM to rank the
    most relevant sessions for the board question, and persists the
    result as a Synthesis row with phase='plan'.

    Args:
        attendee: the Attendee requesting the plan. Their context
            (role, industry, board_question, non_session_time_budget)
            shapes the recommendation.

    Returns:
        The newly created Synthesis instance. Even if the LLM response
        could not be parsed, a row is written with the raw text so
        nothing is silently lost.
    """
    sessions = (
        Session.objects
        .filter(conference=attendee.conference)
        .order_by('time_slot')
    )

    user_prompt = (
        f"{_attendee_header(attendee)}\n\n"
        f"Available sessions on the agenda:\n"
        f"{_format_session_list(sessions, include_descriptions=True)}"
    )

    parsed, raw = _call_llm(_SESSION_PLAN_SYSTEM, user_prompt)
    content = parsed if parsed else {'parse_error': True, 'raw': raw}

    return Synthesis.objects.create(
        attendee=attendee,
        phase=Synthesis.PHASE_PLAN,
        content=content,
        model_used=settings.OPENROUTER_MODEL,
    )


# ---------------------------------------------------------------------------
# Phase 2: During — dynamic replan + preliminary board rec
# ---------------------------------------------------------------------------

_DYNAMIC_REPLAN_SYSTEM = """\
You are an advisor sitting next to a security professional partway through
a conference. They have logged some sessions and possibly some vendor
visits. Help them: (1) decide what to attend next given what they have
already heard, (2) start synthesizing a preliminary board recommendation.

Output JSON with this exact shape:

{
  "diagnosis": "1-2 sentences naming what the attendee has heard so far and the tensions you can see.",
  "replan_suggestions": [
    {"action": "skip" | "attend", "session_id": <int>, "rationale": "1-2 sentences."}
  ],
  "preliminary_priorities": [
    {
      "rank": <int>,
      "title": "Short title (max 8 words).",
      "rationale": "2-3 sentences anchored in the board question.",
      "supporting_log_ids": [<int>, ...],
      "supporting_vendor_ids": [<int>, ...]
    }
  ]
}

Cite logs and vendor visits by their numeric ids. Treat vendor pitches as
lower epistemic weight than session content — vendors have skin in the
game in a way conference speakers usually do not. When notes overlap with
something else the attendee heard, surface it as a tension worth
examining; use neutral language ("tension between X and Y"), not
adversarial language. Produce 2-4 preliminary priorities.
"""


def generate_dynamic_replan(attendee: Attendee) -> Synthesis:
    """During-phase synthesis: replan + preliminary board rec. Reads
    everything the attendee has logged so far plus the remaining agenda,
    asks the LLM to suggest adjustments and surface preliminary
    priorities, persists the result as a Synthesis row with
    phase='preliminary'.

    Args:
        attendee: the Attendee requesting the replan.

    Returns:
        The newly created Synthesis instance, with cites populated to
        any AttendanceLog rows the model referenced in
        supporting_log_ids.
    """
    logs = (
        AttendanceLog.objects
        .filter(attendee=attendee)
        .select_related('session')
        .order_by('session__time_slot')
    )
    vendor_visits = (
        VendorVisit.objects
        .filter(attendee=attendee)
        .order_by('timestamp')
    )

    attended_session_ids = list(
        logs.filter(attended=True).values_list('session_id', flat=True)
    )
    remaining = (
        Session.objects
        .filter(conference=attendee.conference)
        .exclude(id__in=attended_session_ids)
        .order_by('time_slot')
    )

    user_prompt = (
        f"{_attendee_header(attendee)}\n\n"
        f"Sessions logged so far:\n{_format_logs(logs)}\n\n"
        f"Vendor visits logged so far:\n{_format_vendor_visits(vendor_visits)}\n\n"
        f"Remaining sessions on the agenda:\n"
        f"{_format_session_list(remaining, include_descriptions=False)}"
    )

    parsed, raw = _call_llm(_DYNAMIC_REPLAN_SYSTEM, user_prompt)
    content = parsed if parsed else {'parse_error': True, 'raw': raw}

    synthesis = Synthesis.objects.create(
        attendee=attendee,
        phase=Synthesis.PHASE_PRELIMINARY,
        content=content,
        model_used=settings.OPENROUTER_MODEL,
    )
    _attach_citations(synthesis, content, attendee)
    return synthesis


# ---------------------------------------------------------------------------
# Phase 3: After — final board recommendation
# ---------------------------------------------------------------------------

_FINAL_BOARD_REC_SYSTEM = """\
You are an advisor preparing a security manager's final board
recommendation after a conference. The attendee took notes across
sessions and vendor booths. Produce a coherent synthesis they can present
to their board on Monday morning.

The attendee experienced the conference as overwhelming, not as a series
of clean contradictions. First name the diffuse pulls — what was pulling
against what — before resolving them. Validate the experience by surfacing
the tensions the attendee did not have to articulate, then resolve them
in light of the board question.

Output JSON with this exact shape:

{
  "diagnosis": "2-3 sentences in second-person voice. Names what was pulling against what without resolving yet. Example: 'You heard X arguing fundamentals first, while Y pushed identity-led modernization, and the expo floor doubled down on Y.'",
  "contradictions": [
    {
      "between": "Plain-language description of the two opposing positions.",
      "resolution": "2-3 sentences on how to think about it given the board question.",
      "supporting_log_ids": [<int>, ...],
      "supporting_vendor_ids": [<int>, ...]
    }
  ],
  "priorities": [
    {
      "rank": <int>,
      "title": "Short title, max 8 words.",
      "rationale": "2-3 sentences anchored in the board question.",
      "supporting_log_ids": [<int>, ...],
      "supporting_vendor_ids": [<int>, ...]
    }
  ],
  "talking_points": [
    "Bullet ready for a Monday board presentation.",
    ...
  ]
}

Produce exactly 3 priorities, ranked. Cite logs and vendor visits by
their numeric ids. Treat vendor pitches as lower epistemic weight than
session content. Use neutral framing for tensions ("the conference
surfaced tension between X and Y"), not adversarial language. Talking
points should be concise, board-meeting-ready language.
"""


def generate_final_board_rec(attendee: Attendee) -> Synthesis:
    """After-phase synthesis: final board recommendation. Reads every
    log and vendor visit the attendee has captured, asks the LLM to
    produce the structured deliverable Catherine presents Monday
    morning, persists the result as a Synthesis row with phase='final'.

    Args:
        attendee: the Attendee requesting the final synthesis.

    Returns:
        The newly created Synthesis instance, with cites populated.
    """
    logs = (
        AttendanceLog.objects
        .filter(attendee=attendee)
        .select_related('session')
        .order_by('session__time_slot')
    )
    vendor_visits = (
        VendorVisit.objects
        .filter(attendee=attendee)
        .order_by('timestamp')
    )

    user_prompt = (
        f"{_attendee_header(attendee)}\n\n"
        f"Sessions she logged:\n{_format_logs(logs)}\n\n"
        f"Vendor visits she logged:\n{_format_vendor_visits(vendor_visits)}"
    )

    parsed, raw = _call_llm(_FINAL_BOARD_REC_SYSTEM, user_prompt)
    content = parsed if parsed else {'parse_error': True, 'raw': raw}

    synthesis = Synthesis.objects.create(
        attendee=attendee,
        phase=Synthesis.PHASE_FINAL,
        content=content,
        model_used=settings.OPENROUTER_MODEL,
    )
    _attach_citations(synthesis, content, attendee)
    return synthesis


def _attach_citations(
    synthesis: Synthesis,
    content: dict[str, Any],
    attendee: Attendee,
) -> None:
    """Walk the parsed AI output looking for supporting_log_ids and
    populate the Synthesis.cites M2M with the resolved AttendanceLog
    rows. Only logs owned by the attendee are linked, so a hallucinated
    or stale id silently drops out instead of cross-attaching."""
    if not content:
        return
    log_ids: set[int] = set()
    for section_name in ('priorities', 'preliminary_priorities', 'contradictions'):
        for item in content.get(section_name, []) or []:
            ids = item.get('supporting_log_ids') or []
            for raw_id in ids:
                try:
                    log_ids.add(int(raw_id))
                except (TypeError, ValueError):
                    continue
    if log_ids:
        owned_logs = AttendanceLog.objects.filter(
            id__in=log_ids,
            attendee=attendee,
        )
        synthesis.cites.set(owned_logs)
