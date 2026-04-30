# Author: Ian Sun | isun@bu.edu
# Description: Data models for Arbiter, a smart conference companion app that
# helps attendees arbitrate conflicting conference content against their
# organization's specific decision question. Defines Conference, Attendee,
# Session, AttendanceLog, VendorVisit, and Synthesis, plus the foreign-key
# relationships between them.

from django.db import models
from django.contrib.auth.models import User


class Conference(models.Model):
    """A conference event. The root model for Arbiter: every other model
    relates to Conference either directly (Session, Attendee) or transitively
    through Attendee (AttendanceLog). A Conference can exist on its own without
    any attendees or sessions."""

    name = models.CharField(max_length=200)
    location = models.CharField(max_length=200)
    start_date = models.DateField()
    end_date = models.DateField()
    description = models.TextField(blank=True)

    class Meta:
        ordering = ['-start_date']

    def __str__(self):
        """Return a human-readable label combining conference name and year,
        used by the Django admin and any template rendering the object."""
        return f"{self.name} ({self.start_date.year})"


class Attendee(models.Model):
    """A user's registration at a specific conference, including the
    organizational context that drives every AI recommendation. board_question
    is the core differentiator: the specific question an attendee's
    organization sent them to answer, stored as a first-class database field
    rather than left implicit.

    user is a ForeignKey (not OneToOneField) so a single user may attend
    multiple conferences over time. The unique_together constraint on
    (user, conference) prevents a duplicate registration for the same
    conference."""

    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='attendees'
    )
    conference = models.ForeignKey(
        Conference, on_delete=models.CASCADE, related_name='attendees'
    )
    role = models.CharField(max_length=200)
    industry = models.CharField(max_length=200)
    board_question = models.TextField()
    bio = models.TextField(blank=True, null=True)
    non_session_time_budget = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [('user', 'conference')]

    def __str__(self):
        """Return a label pairing the username with the conference name so
        admin list views unambiguously identify which registration is which
        when a user has multiple."""
        return f"{self.user.username} @ {self.conference.name}"


class Session(models.Model):
    """A single session on a conference's agenda. Sessions are authored by the
    conference organizer (staff), not by individual attendees."""

    conference = models.ForeignKey(
        Conference, on_delete=models.CASCADE, related_name='sessions'
    )
    title = models.CharField(max_length=300)
    speaker = models.CharField(max_length=200, blank=True)
    topic_area = models.CharField(max_length=200)
    time_slot = models.DateTimeField()
    description = models.TextField(blank=True)

    class Meta:
        ordering = ['time_slot']

    def __str__(self):
        """Return the session title for admin and template display."""
        return self.title


class AttendanceLog(models.Model):
    """Records an attendee's relationship to a session across planning and
    execution. The (planned, attended) pair supports gap analysis:

        planned=True,  attended=False  -> planned but skipped
        planned=False, attended=True   -> attended without planning
        planned=True,  attended=True   -> attended as planned

    unique_together on (attendee, session) prevents double-logging the same
    session, which would break gap analysis counts.

    Catherine experiences the conference as a working professional taking
    notes, not as the operator of a contradiction-detection system. The
    note fields reflect that asymmetry: she captures what she heard and
    how it felt; the AI layer does the analytical work of finding
    contradictions across her logs.

    - notes: whatever she wrote down during or after the session, in
      whatever form she normally takes notes. Casual capture, not
      structured analysis.
    - tension_notes: a soft-signal check-in for the casual "this stuck
      out" or "this feels different from something I heard earlier"
      recognition. Catherine doesn't have to identify what differs from
      what; she just notices that something registered. The AI layer
      reads notes and tension_notes together to surface contradictions
      she didn't have to articulate analytically.
    - contradiction_flagged + contradiction_notes: an optional power-user
      toggle for the rare case where Catherine already knows two things
      contradict and wants to flag it explicitly. Stays as the canonical
      reliable path; the AI layer enhances rather than replaces it."""

    attendee = models.ForeignKey(
        Attendee, on_delete=models.CASCADE, related_name='logs'
    )
    session = models.ForeignKey(
        Session, on_delete=models.CASCADE, related_name='logs'
    )
    notes = models.TextField(blank=True)
    tension_notes = models.TextField(blank=True)
    contradiction_flagged = models.BooleanField(default=False)
    contradiction_notes = models.TextField(blank=True)
    planned = models.BooleanField(default=False)
    attended = models.BooleanField(default=False)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [('attendee', 'session')]
        ordering = ['-timestamp']

    def __str__(self):
        """Return a compact attendee / session / status string so admin list
        views convey planning state at a glance without opening each record."""
        status = []
        if self.planned:
            status.append('planned')
        if self.attended:
            status.append('attended')
        status_str = ', '.join(status) if status else 'no status'
        return f"{self.attendee} -> {self.session.title} ({status_str})"


class VendorVisit(models.Model):
    """Records an attendee's visit to a vendor booth on the expo floor.
    Vendor pitches produce signal that should feed the synthesis: a
    booth claiming "our solution makes Zero Trust easy" is contradiction-
    relevant against a session that argued "Zero Trust has been captured
    by vendors." The AI layer reads VendorVisits alongside
    AttendanceLogs.

    Same advisor-not-detector framing as AttendanceLog: Catherine notes
    what the booth said and how it felt; the AI does the analytical
    work of finding contradictions across her vendor visits and session
    notes. The note-field semantics mirror AttendanceLog exactly:

    - notes: what the booth pitched, captured the way she'd note it
      between sessions. Quick, casual.
    - tension_notes: a soft-signal check-in for the casual "this stuck
      out" or "this feels different from something I heard earlier"
      recognition. Catherine doesn't have to articulate what differs
      from what.
    - contradiction_flagged + contradiction_notes: an optional
      power-user toggle for the rare case where she has already
      identified two specific things that contradict and wants to flag
      it explicitly.

    Note: there is no unique_together constraint on
    (attendee, vendor_name) because a vendor's booth might pitch
    different things across multiple days of a conference, and Catherine
    should be able to log Day 1's Okta visit alongside Day 2's Okta
    visit without one overwriting the other. This is intentionally
    different from AttendanceLog, where unique_together(attendee,
    session) is correct because a session is a single time-bounded
    event."""

    attendee = models.ForeignKey(
        Attendee, on_delete=models.CASCADE, related_name='vendor_visits'
    )
    vendor_name = models.CharField(max_length=200)
    category = models.CharField(max_length=200)
    notes = models.TextField(blank=True)
    tension_notes = models.TextField(blank=True)
    contradiction_flagged = models.BooleanField(default=False)
    contradiction_notes = models.TextField(blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-timestamp']

    def __str__(self):
        """Return attendee / vendor name pair so admin list views read
        cleanly when the same attendee has multiple vendor visits."""
        return f"{self.attendee} -> {self.vendor_name}"


class Synthesis(models.Model):
    """Persisted record of an AI-generated deliverable for one attendee. Each
    call to the AI layer (session_plan, dynamic_replan, final_board_rec)
    writes a new Synthesis row rather than returning an ephemeral response,
    so the evolution of Catherine's board recommendation across the day
    becomes auditable, cacheable, editable, and exportable.

    Multiple rows per (attendee, phase) are intentional — the history is the
    product story ("preliminary board rec that updates as the day
    progresses"), so there is no unique_together constraint. UIs that want
    "the latest" should order by `-created_at` and take the first row.

    content holds the raw AI output; edited_content holds Catherine's
    post-hoc edits, if any. The export endpoint should prefer
    edited_content when present so the review-before-present workflow is
    structurally enforced rather than left to UX. cites is a many-to-many
    back to AttendanceLog so every claim the AI makes can be traced to the
    specific notes it was derived from — the structural hook for the v2
    citation-required hallucination mitigation."""

    PHASE_PLAN = 'plan'
    PHASE_PRELIMINARY = 'preliminary'
    PHASE_FINAL = 'final'
    PHASE_CHOICES = [
        (PHASE_PLAN, 'Pre-conference session plan'),
        (PHASE_PRELIMINARY, 'Preliminary board recommendation'),
        (PHASE_FINAL, 'Final board recommendation'),
    ]

    attendee = models.ForeignKey(
        Attendee, on_delete=models.CASCADE, related_name='syntheses'
    )
    phase = models.CharField(max_length=20, choices=PHASE_CHOICES)
    content = models.JSONField()
    # edited_content is the legacy structured-edit field. Editing JSON
    # turned out to be hostile UX, so the v1 edit flow uses edited_text
    # below — a plain-text version Catherine can edit freely. Kept as
    # a column for backward compat and a possible v2 structured editor.
    edited_content = models.JSONField(null=True, blank=True)
    edited_text = models.TextField(blank=True)
    model_used = models.CharField(max_length=200)
    cites = models.ManyToManyField(
        AttendanceLog, blank=True, related_name='cited_by'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name_plural = 'Syntheses'

    def __str__(self):
        """Return attendee, phase label, and timestamp so admin list views
        convey which synthesis is which when an attendee has several from
        across the day."""
        return (
            f"{self.attendee} \u2014 {self.get_phase_display()} "
            f"({self.created_at:%Y-%m-%d %H:%M})"
        )

