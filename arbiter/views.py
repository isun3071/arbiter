# Author: Ian Sun | isun@bu.edu
# Description: View classes and functions for the arbiter app. This file is
# the surface that arbiter/urls.py routes into. View bodies are intentionally
# minimal at this stage — most are scaffolded with the correct base class,
# model, and template_name so the server boots and the URL conf imports
# succeed. Real query logic, form handling, and AI integration land in
# subsequent passes.

import logging
from collections import OrderedDict

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.db import transaction
from django.db.models import Count, Q
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse, reverse_lazy
from django.views import View
from django.views.decorators.http import require_POST
from django.views.generic import (
    CreateView, DeleteView, DetailView, FormView, ListView, TemplateView,
    UpdateView,
)

from arbiter import ai_services
from arbiter.forms import (
    AttendanceLogForm, AttendeeForm, RegistrationForm, SynthesisEditForm,
    VendorVisitForm,
)
from arbiter.models import (
    Attendee, AttendanceLog, Conference, Session, Synthesis, VendorVisit,
)


logger = logging.getLogger(__name__)


class StaffRequiredMixin(UserPassesTestMixin):
    """Mixin restricting access to staff users.

    Used on Session create/update/delete views: an attendee must not be
    able to inject fake sessions into a conference's agenda. The reverse
    is enforced via UserPassesTestMixin which 403s non-staff users.
    """

    def test_func(self):
        """Return True when the requesting user is authenticated staff."""
        return self.request.user.is_authenticated and self.request.user.is_staff


class _AttendeeRequiredMixin(LoginRequiredMixin):
    """Mixin that ensures the signed-in user has at least one Attendee
    row before letting them reach AttendanceLog views. Users who land on
    the log surface without having registered for a conference are
    redirected to the registration flow rather than allowed to crash on
    a non-null FK.

    Composes with LoginRequiredMixin so an unauthenticated user is sent
    to the login page first; an authenticated user without an Attendee
    is sent to register.
    """

    def dispatch(self, request, *args, **kwargs):
        """Send authenticated users with no Attendee rows to register."""
        if request.user.is_authenticated and not request.user.attendees.exists():
            return redirect('arbiter:register')
        return super().dispatch(request, *args, **kwargs)

    def get_active_attendee(self):
        """Return the most recently created Attendee for the signed-in
        user. The most-recent rule maps to the natural expectation that
        a user is logging for their current conference; users with only
        one Attendee (the common case) get the only one.

        Returns:
            The Attendee instance, or None if the user has no Attendees.
            In practice this will not be None inside a view body because
            dispatch() above redirects in that case before reaching it.
        """
        return self.request.user.attendees.order_by('-created_at').first()


# ---------------------------------------------------------------------------
# Home and authentication
# ---------------------------------------------------------------------------

class HomeView(View):
    """Landing page for anonymous visitors; redirects authenticated
    users straight to their dashboard.

    The two surfaces serve different jobs (sales pitch vs. workspace),
    so the route is single but the rendering branches on auth state.
    Authenticated users hitting / never see the landing page; they go
    straight to their dashboard at /arbiter/dashboard/.
    """

    def get(self, request):
        """Render the landing page for anonymous users; redirect
        authenticated users to their dashboard."""
        if request.user.is_authenticated:
            return redirect('arbiter:dashboard')
        return render(request, 'arbiter/home.html')


class DashboardView(_AttendeeRequiredMixin, TemplateView):
    """Authenticated workspace surface. The single anchor view that
    shows Catherine her board_question (pull-quote treatment), her
    latest synthesis if one exists, her non_session_time_budget if
    set, and recent AttendanceLogs and VendorVisits side by side. Plus
    a "what's next" action row that points at the three primary
    workflows (log a session, log a vendor, get a board recommendation).

    Lives at /arbiter/dashboard/ rather than /arbiter/ so the marketing
    landing page can keep its own route. The HomeView redirects
    authenticated users here automatically.
    """

    template_name = 'arbiter/dashboard.html'

    def get_context_data(self, **kwargs):
        """Provide the active Attendee plus the five most recent
        AttendanceLogs and VendorVisits for the dashboard preview lists,
        and the latest Synthesis row if any AI calls have already run."""
        context = super().get_context_data(**kwargs)
        attendee = self.get_active_attendee()
        context['attendee'] = attendee
        context['recent_logs'] = (
            AttendanceLog.objects
            .filter(attendee=attendee)
            .select_related('session', 'session__conference')
            .order_by('-timestamp')[:5]
        )
        context['recent_vendors'] = (
            VendorVisit.objects
            .filter(attendee=attendee)
            .order_by('-timestamp')[:5]
        )
        context['latest_synthesis'] = (
            Synthesis.objects
            .filter(attendee=attendee)
            .order_by('-created_at')
            .first()
        )
        return context


# ---------------------------------------------------------------------------
# Attendee — registration and profile
# ---------------------------------------------------------------------------

class AttendeeCreateView(FormView):
    """Signup flow that creates a User and an Attendee in one form
    submission. RegistrationForm handles the model creation; this view
    handles the surrounding HTTP concerns: redirecting authenticated
    users away from the signup page, wrapping the create in an atomic
    transaction so a partial failure can't strand a User without an
    Attendee, and signing the new account in automatically so the user
    lands directly on their dashboard.

    Implemented as FormView (not CreateView) because the form creates
    two model instances, not one — CreateView's instance-tracking is the
    wrong abstraction for that.
    """

    form_class = RegistrationForm
    template_name = 'arbiter/register.html'
    success_url = reverse_lazy('arbiter:attendance_list')

    def dispatch(self, request, *args, **kwargs):
        """Redirect already-signed-in users to the home page so they
        don't accidentally create a second account by revisiting
        /register/."""
        if request.user.is_authenticated:
            return redirect('arbiter:home')
        return super().dispatch(request, *args, **kwargs)

    @transaction.atomic
    def form_valid(self, form):
        """Create the User + Attendee atomically, then sign the new
        user in so they land on the dashboard rather than the login
        page. Atomicity matters: a half-created account (User without
        Attendee) would fail every subsequent AttendanceLog flow."""
        user = form.save()
        login(self.request, user)
        return super().form_valid(form)


class AttendeeUpdateView(_AttendeeRequiredMixin, UpdateView):
    """Edit the signed-in user's Attendee profile (role, industry,
    board_question, bio).

    The view resolves the target Attendee via _AttendeeRequiredMixin's
    get_active_attendee() rather than via URL pk, so the user never has
    to know their own Attendee id and can't accidentally land on
    someone else's profile. AttendeeForm gives board_question a larger
    textarea + scaffolded prompt because it's the field every AI
    recommendation reads from.
    """

    model = Attendee
    form_class = AttendeeForm
    template_name = 'arbiter/attendee_form.html'
    success_url = reverse_lazy('arbiter:attendance_list')

    def get_object(self, queryset=None):
        """Return the user's most recently created Attendee — the same
        record the AttendanceLog views treat as 'active'."""
        return self.get_active_attendee()


# ---------------------------------------------------------------------------
# Conference — read-only for attendees; staff-managed via admin
# ---------------------------------------------------------------------------

class ConferenceListView(ListView):
    """Browse all conferences in the catalog. Public — anyone can see the
    list, registration status is shown only when a user is signed in."""

    model = Conference
    template_name = 'arbiter/conference_list.html'
    context_object_name = 'conferences'

    def get_queryset(self):
        """Annotate each Conference with a session_count so the list
        template can render the count without issuing one COUNT query
        per row."""
        return Conference.objects.annotate(session_count=Count('sessions'))

    def get_context_data(self, **kwargs):
        """Add the set of conference ids the signed-in user is registered
        for, so the template can render a 'Registered' chip on the right
        rows. Empty list for anonymous users."""
        context = super().get_context_data(**kwargs)
        user = self.request.user
        if user.is_authenticated:
            context['user_attendee_conference_ids'] = list(
                user.attendees.values_list('conference_id', flat=True)
            )
        else:
            context['user_attendee_conference_ids'] = []
        return context


class ConferenceDetailView(DetailView):
    """Detail page for one Conference. Surfaces the agenda grouped by
    day, the conference's metadata, and (for users registered for this
    conference) quick CTAs into the logging surface."""

    model = Conference
    template_name = 'arbiter/conference_detail.html'
    context_object_name = 'conference'

    def get_context_data(self, **kwargs):
        """Add a pre-ordered sessions queryset and a boolean indicating
        whether the signed-in user has an Attendee row for this
        conference. The pre-ordered queryset is iterated by the
        regroup-by-day rendering in the template; binding it once in
        context (rather than calling conference.sessions.all() in the
        template) avoids a second query when the count and the list are
        both rendered."""
        context = super().get_context_data(**kwargs)
        # Order by (time_slot, topic_area) so the template can regroup by
        # time first, then within each time block sessions land in topic
        # alphabetical order. Concurrent sessions of the same category
        # visually cluster, which makes the "I have to choose between
        # these two Identity sessions" decision visible at a glance.
        context['sessions'] = self.object.sessions.all().order_by(
            'time_slot', 'topic_area'
        )
        user = self.request.user
        if user.is_authenticated:
            context['is_registered'] = user.attendees.filter(
                conference=self.object
            ).exists()
        else:
            context['is_registered'] = False
        return context


# ---------------------------------------------------------------------------
# Session — full CRUD; create/update/delete are staff-only
# ---------------------------------------------------------------------------

class SessionListView(ListView):
    """Browse sessions across every conference, with optional filtering by
    conference (?conference=<pk>) or topic_area (?topic=<area>). The two
    query params satisfy the assignment's "search/filter producing a
    meaningful report" requirement at a basic level; the deeper
    gap-analysis report layers on top of this surface."""

    model = Session
    template_name = 'arbiter/session_list.html'
    context_object_name = 'sessions'

    def get_queryset(self):
        """Apply conference and topic filters from the query string, and
        eager-load the conference FK so the list template can render the
        conference name on every row without N+1 queries."""
        queryset = (
            Session.objects
            .select_related('conference')
            .order_by('conference__name', 'time_slot', 'topic_area')
        )
        conference_id = self.request.GET.get('conference')
        if conference_id:
            queryset = queryset.filter(conference_id=conference_id)
        topic = self.request.GET.get('topic')
        if topic:
            queryset = queryset.filter(topic_area=topic)
        return queryset

    def get_context_data(self, **kwargs):
        """Provide the conference and topic_area dropdown options plus the
        currently-selected values so the filter bar can mark its current
        state correctly."""
        context = super().get_context_data(**kwargs)
        context['conferences'] = Conference.objects.order_by('-start_date')
        context['topics'] = list(
            Session.objects
            .order_by('topic_area')
            .values_list('topic_area', flat=True)
            .distinct()
        )
        context['selected_conference'] = self.request.GET.get('conference', '')
        context['selected_topic'] = self.request.GET.get('topic', '')
        return context


class SessionDetailView(DetailView):
    """Detail page for one Session. Surfaces the full session metadata
    plus, for users registered for this session's conference, an
    affordance to log attendance — pre-filling the session field on the
    AttendanceLog form via a query param so Catherine doesn't have to
    re-pick from a 69-row dropdown."""

    model = Session
    template_name = 'arbiter/session_detail.html'
    context_object_name = 'session'

    def get_queryset(self):
        """Eager-load the conference so the detail template can render
        the conference link without an extra query."""
        return Session.objects.select_related('conference')

    def get_context_data(self, **kwargs):
        """Add registration status and any existing AttendanceLog the
        signed-in user already wrote for this session, so the CTA can
        toggle between "Log this session" and "Edit your log"."""
        context = super().get_context_data(**kwargs)
        user = self.request.user
        if user.is_authenticated:
            context['is_registered'] = user.attendees.filter(
                conference=self.object.conference
            ).exists()
            context['existing_log'] = AttendanceLog.objects.filter(
                attendee__user=user,
                session=self.object,
            ).first()
        else:
            context['is_registered'] = False
            context['existing_log'] = None
        return context


class SessionCreateView(StaffRequiredMixin, CreateView):
    """Add a new session to a conference. Staff-only."""

    model = Session
    fields = [
        'conference', 'title', 'speaker', 'topic_area',
        'time_slot', 'description',
    ]
    template_name = 'arbiter/session_form.html'
    success_url = reverse_lazy('arbiter:session_list')


class SessionUpdateView(StaffRequiredMixin, UpdateView):
    """Edit an existing session. Staff-only."""

    model = Session
    fields = [
        'conference', 'title', 'speaker', 'topic_area',
        'time_slot', 'description',
    ]
    template_name = 'arbiter/session_form.html'
    success_url = reverse_lazy('arbiter:session_list')


class SessionDeleteView(StaffRequiredMixin, DeleteView):
    """Delete a session. Staff-only."""

    model = Session
    template_name = 'arbiter/session_confirm_delete.html'
    success_url = reverse_lazy('arbiter:session_list')


# ---------------------------------------------------------------------------
# AttendanceLog — full CRUD scoped to the signed-in attendee
# ---------------------------------------------------------------------------

class AttendanceLogListView(LoginRequiredMixin, ListView):
    """List the signed-in user's attendance logs across every Attendee
    registration they have, newest first. Scoping by request.user keeps
    one user from seeing another user's logs.

    Note: this view does not extend _AttendeeRequiredMixin because it is
    valid to reach this page with zero logs and zero Attendees; the
    template handles the empty state by pointing the user to register
    or to log their first session.
    """

    model = AttendanceLog
    template_name = 'arbiter/attendancelog_list.html'
    context_object_name = 'logs'

    def get_queryset(self):
        """Return only the AttendanceLogs owned by the signed-in user.

        select_related on session, session.conference, and attendee is a
        small but real win for the list-view template, which renders
        each row with the session title plus the conference name; without
        the prefetch each row would issue follow-up queries.
        """
        return (
            AttendanceLog.objects
            .filter(attendee__user=self.request.user)
            .select_related('session', 'session__conference', 'attendee')
            .order_by('-timestamp')
        )


class AttendanceLogCreateView(_AttendeeRequiredMixin, CreateView):
    """Log attendance at a session.

    The form (AttendanceLogForm) renders the casual prompt for
    tension_notes as the design centerpiece and tucks the
    contradiction_flagged + contradiction_notes fields behind an advanced
    disclosure. The view binds the new AttendanceLog to the user's active
    Attendee in form_valid; the user never picks an Attendee or
    Conference manually, only the session.
    """

    model = AttendanceLog
    form_class = AttendanceLogForm
    template_name = 'arbiter/attendancelog_form.html'
    success_url = reverse_lazy('arbiter:attendance_list')

    def get_form_kwargs(self):
        """Inject the active Attendee into form construction so the
        session field can be filtered to that attendee's conference."""
        kwargs = super().get_form_kwargs()
        kwargs['attendee'] = self.get_active_attendee()
        return kwargs

    def get_initial(self):
        """Pre-fill the session field when the create URL was reached
        with ?session=<pk>. Used by the "Log this session" CTA on
        SessionDetailView so Catherine doesn't have to re-pick from a
        long dropdown after clicking through from a session page."""
        initial = super().get_initial()
        session_id = self.request.GET.get('session')
        if session_id:
            try:
                initial['session'] = int(session_id)
            except (TypeError, ValueError):
                pass
        return initial

    def form_valid(self, form):
        """Bind the AttendanceLog to the active Attendee before saving.
        The attendee is not a form field; the view sets it from
        request.user so a user cannot log attendance on behalf of
        someone else by tampering with the form."""
        form.instance.attendee = self.get_active_attendee()
        return super().form_valid(form)


class AttendanceLogUpdateView(_AttendeeRequiredMixin, UpdateView):
    """Edit an existing AttendanceLog row. Used both for adding notes
    after the session ends and for fixing a misflagged entry. The
    queryset is scoped to logs owned by the signed-in user so one user
    cannot edit another user's logs by guessing the URL pk."""

    model = AttendanceLog
    form_class = AttendanceLogForm
    template_name = 'arbiter/attendancelog_form.html'
    success_url = reverse_lazy('arbiter:attendance_list')

    def get_queryset(self):
        """Restrict editable logs to those owned by the signed-in user."""
        return AttendanceLog.objects.filter(attendee__user=self.request.user)

    def get_form_kwargs(self):
        """Inject the active Attendee into form construction so the
        session field can be filtered to that attendee's conference."""
        kwargs = super().get_form_kwargs()
        kwargs['attendee'] = self.get_active_attendee()
        return kwargs


class AttendanceLogDeleteView(_AttendeeRequiredMixin, DeleteView):
    """Confirm-and-delete view for an AttendanceLog. Scoped by ownership
    so a user cannot delete another user's logs by URL guessing."""

    model = AttendanceLog
    template_name = 'arbiter/attendancelog_confirm_delete.html'
    success_url = reverse_lazy('arbiter:attendance_list')

    def get_queryset(self):
        """Restrict deletable logs to those owned by the signed-in user."""
        return AttendanceLog.objects.filter(attendee__user=self.request.user)


# ---------------------------------------------------------------------------
# VendorVisit — full CRUD scoped to the signed-in attendee
# ---------------------------------------------------------------------------

class VendorVisitListView(LoginRequiredMixin, ListView):
    """List the signed-in user's vendor visits, newest first. Same
    ownership-scoping pattern as AttendanceLogListView. Does not extend
    _AttendeeRequiredMixin because reaching the list with zero visits
    and zero Attendees is a valid empty state."""

    model = VendorVisit
    template_name = 'arbiter/vendorvisit_list.html'
    context_object_name = 'visits'

    def get_queryset(self):
        """Return only the VendorVisits owned by the signed-in user."""
        return (
            VendorVisit.objects
            .filter(attendee__user=self.request.user)
            .select_related('attendee', 'attendee__conference')
            .order_by('-timestamp')
        )


class VendorVisitCreateView(_AttendeeRequiredMixin, CreateView):
    """Log a vendor visit. The form (VendorVisitForm) is optimized for
    quick mobile entry: vendor_name, category, notes, tension_notes are
    surfaced by default; the contradiction_flagged + contradiction_notes
    pair sits behind an advanced disclosure. The view binds the new
    VendorVisit to the user's active Attendee in form_valid."""

    model = VendorVisit
    form_class = VendorVisitForm
    template_name = 'arbiter/vendorvisit_form.html'
    success_url = reverse_lazy('arbiter:vendor_list')

    def form_valid(self, form):
        """Bind the VendorVisit to the active Attendee before saving so
        a user cannot log a vendor visit on someone else's behalf by
        tampering with the form."""
        form.instance.attendee = self.get_active_attendee()
        return super().form_valid(form)


class VendorVisitUpdateView(_AttendeeRequiredMixin, UpdateView):
    """Edit an existing VendorVisit row. Used both for refining notes
    after the visit and fixing a misflagged entry. Queryset is scoped
    to visits owned by the signed-in user."""

    model = VendorVisit
    form_class = VendorVisitForm
    template_name = 'arbiter/vendorvisit_form.html'
    success_url = reverse_lazy('arbiter:vendor_list')

    def get_queryset(self):
        """Restrict editable visits to those owned by the signed-in user."""
        return VendorVisit.objects.filter(attendee__user=self.request.user)


class VendorVisitDeleteView(_AttendeeRequiredMixin, DeleteView):
    """Confirm-and-delete view for a VendorVisit. Ownership-scoped
    queryset so URL guessing returns 404 instead of letting one user
    delete another's visits."""

    model = VendorVisit
    template_name = 'arbiter/vendorvisit_confirm_delete.html'
    success_url = reverse_lazy('arbiter:vendor_list')

    def get_queryset(self):
        """Restrict deletable visits to those owned by the signed-in user."""
        return VendorVisit.objects.filter(attendee__user=self.request.user)


# ---------------------------------------------------------------------------
# AI endpoints — function-based; expect POST
# ---------------------------------------------------------------------------

def _resolve_active_attendee(request):
    """Return the most recently created Attendee for the signed-in user
    or None. Used by the AI function-based views since they cannot use
    the _AttendeeRequiredMixin pattern (which is class-based)."""
    return request.user.attendees.order_by('-created_at').first()


@require_POST
@login_required
def session_plan(request):
    """Before-phase AI call. Produces a prioritized session shortlist
    grounded in the signed-in attendee's board_question. Persists a
    Synthesis row with phase='plan' and redirects to its detail page.

    Args:
        request: Django HttpRequest. Must be POST and authenticated.

    Returns:
        HttpResponseRedirect to /arbiter/synthesis/<pk>/. If the user
        has no Attendee row, redirects to /register/ instead. If the AI
        call raises, surfaces a Django messages error and redirects
        back to the dashboard.
    """
    attendee = _resolve_active_attendee(request)
    if attendee is None:
        return redirect('arbiter:register')
    try:
        synthesis = ai_services.generate_session_plan(attendee)
    except Exception:
        logger.exception("session_plan AI call failed")
        messages.error(
            request,
            "Arbiter could not reach the AI service. Try again in a "
            "minute, or contact support if it keeps failing.",
        )
        return redirect('arbiter:dashboard')
    return redirect('arbiter:synthesis_detail', pk=synthesis.pk)


@require_POST
@login_required
def dynamic_replan(request):
    """During-phase AI call. Reads what the attendee has logged so far
    plus their vendor visits, returns replan suggestions and a
    preliminary board recommendation. Persists a Synthesis row with
    phase='preliminary' and redirects to its detail page.

    Args:
        request: Django HttpRequest. Must be POST and authenticated.

    Returns:
        HttpResponseRedirect to the new Synthesis detail page, or to
        register / dashboard on the no-attendee / AI-error paths.
    """
    attendee = _resolve_active_attendee(request)
    if attendee is None:
        return redirect('arbiter:register')
    try:
        synthesis = ai_services.generate_dynamic_replan(attendee)
    except Exception:
        logger.exception("dynamic_replan AI call failed")
        messages.error(
            request,
            "Arbiter could not reach the AI service. Try again in a "
            "minute, or contact support if it keeps failing.",
        )
        return redirect('arbiter:dashboard')
    return redirect('arbiter:synthesis_detail', pk=synthesis.pk)


@require_POST
@login_required
def final_board_rec(request):
    """After-phase AI call. Reads everything the attendee has captured
    (sessions, vendor visits, tension notes, manual contradiction
    flags) and produces the final board-ready synthesis. Persists a
    Synthesis row with phase='final' and redirects to its detail page.

    Args:
        request: Django HttpRequest. Must be POST and authenticated.

    Returns:
        HttpResponseRedirect to the new Synthesis detail page, or to
        register / dashboard on the no-attendee / AI-error paths.
    """
    attendee = _resolve_active_attendee(request)
    if attendee is None:
        return redirect('arbiter:register')
    try:
        synthesis = ai_services.generate_final_board_rec(attendee)
    except Exception:
        logger.exception("final_board_rec AI call failed")
        messages.error(
            request,
            "Arbiter could not reach the AI service. Try again in a "
            "minute, or contact support if it keeps failing.",
        )
        return redirect('arbiter:dashboard')
    return redirect('arbiter:synthesis_detail', pk=synthesis.pk)


# ---------------------------------------------------------------------------
# Synthesis — view and edit persisted AI outputs
# ---------------------------------------------------------------------------

class SynthesisListView(LoginRequiredMixin, ListView):
    """List every Synthesis the signed-in user has generated, newest
    first. Surfaces the evolution of their recommendations across the
    conference — a plan from the morning, a replan from the afternoon,
    a final synthesis after the keynote — so the attendee can revisit
    any version, compare across phases, or restore a prior framing
    they edited away.

    Queryset is ownership-scoped via the attendee FK so a user cannot
    see another user's synthesis history by URL guessing."""

    model = Synthesis
    template_name = 'arbiter/synthesis_list.html'
    context_object_name = 'syntheses'

    def get_queryset(self):
        """Restrict visible Synthesis rows to those owned by the
        signed-in user, newest first. Eager-loads the attendee +
        conference so the list template renders the conference name on
        every row without N+1 queries."""
        return (
            Synthesis.objects
            .filter(attendee__user=self.request.user)
            .select_related('attendee', 'attendee__conference')
            .order_by('-created_at')
        )


class SynthesisDetailView(LoginRequiredMixin, DetailView):
    """Render a persisted Synthesis row in the document register.

    Two render paths:

    1. If the user has saved an edited_text, the template renders that
       text in serif body type (linebreaks-preserved). Citations
       become plain-text mentions ("your Opening Keynote log") rather
       than clickable links — once Catherine edits, she's taking
       ownership of the prose and may rephrase the citations herself.

    2. If edited_text is empty, the structured AI content is rendered
       with each priority / contradiction citing the AttendanceLog or
       VendorVisit it was drawn from. The view enriches `content`
       in-place with resolved object lookups so the template can render
       <a href="{% url 'arbiter:attendance_update' log.pk %}">link</a>
       instead of "log #N".

    Queryset is ownership-scoped via the attendee FK so a user cannot
    view another user's synthesis by URL guessing.
    """

    model = Synthesis
    template_name = 'arbiter/synthesis_detail.html'
    context_object_name = 'synthesis'

    def get_queryset(self):
        """Restrict visible Synthesis rows to those owned by the
        signed-in user."""
        return Synthesis.objects.filter(attendee__user=self.request.user)

    def get_context_data(self, **kwargs):
        """Resolve supporting_log_ids / supporting_vendor_ids /
        session_id references in the AI's structured content into
        actual model objects so the template can render clickable
        citations. Mutates a shallow copy of synthesis.content; never
        writes the resolved objects back to the database."""
        context = super().get_context_data(**kwargs)
        synthesis = self.object
        attendee = synthesis.attendee
        content = synthesis.content or {}

        # Owner-scoped lookups. If the AI hallucinates an id that
        # doesn't belong to this attendee, it silently drops out
        # (None lookup).
        log_lookup = {
            log.id: log
            for log in AttendanceLog.objects
                .filter(attendee=attendee)
                .select_related('session', 'session__conference')
        }
        vendor_lookup = {
            v.id: v
            for v in VendorVisit.objects.filter(attendee=attendee)
        }
        session_lookup = {
            s.id: s
            for s in Session.objects.filter(conference=attendee.conference)
        }

        # Walk the structured content and attach resolved objects.
        # Items with both supporting_log_ids and supporting_vendor_ids
        # get supporting_logs / supporting_vendors lists for the
        # template; recommended_sessions / replan_suggestions get a
        # `session` attribute resolved from session_id.
        for section_key in ('priorities', 'preliminary_priorities', 'contradictions'):
            for item in content.get(section_key, []) or []:
                item['supporting_logs'] = [
                    log_lookup[i] for i in (item.get('supporting_log_ids') or [])
                    if i in log_lookup
                ]
                item['supporting_vendors'] = [
                    vendor_lookup[i] for i in (item.get('supporting_vendor_ids') or [])
                    if i in vendor_lookup
                ]
        for r in content.get('recommended_sessions', []) or []:
            r['session'] = session_lookup.get(r.get('session_id'))
        for s in content.get('replan_suggestions', []) or []:
            s['session'] = session_lookup.get(s.get('session_id'))

        context['enriched_content'] = content
        return context


class SynthesisDeleteView(LoginRequiredMixin, DeleteView):
    """Confirm-and-delete view for a Synthesis. Lets the user clean up
    their recommendation history — bad AI outputs, accidental
    re-clicks, parse-error rows, or simply syntheses they no longer
    want around.

    Safe to delete: Synthesis only owns a cites M2M (which gets
    unlinked). The AttendanceLog and VendorVisit rows it referenced
    are unaffected — Synthesis depends on them, not the other way
    round.

    Queryset is ownership-scoped same as the other Synthesis views;
    URL-pk-guessing returns 404."""

    model = Synthesis
    template_name = 'arbiter/synthesis_confirm_delete.html'
    success_url = reverse_lazy('arbiter:synthesis_list')

    def get_queryset(self):
        """Restrict deletable Synthesis rows to those owned by the
        signed-in user."""
        return Synthesis.objects.filter(attendee__user=self.request.user)


class SynthesisUpdateView(LoginRequiredMixin, UpdateView):
    """Edit a Synthesis row's edited_text field — the human-readable
    plain-text version of the AI's draft, pre-populated from the
    structured content the first time the user opens the form. Once
    saved, the detail page renders edited_text instead of the
    structured content (citations become plain-text mentions).

    The original `content` field is never overwritten so the AI's
    first draft remains auditable. Queryset is ownership-scoped same
    as SynthesisDetailView."""

    model = Synthesis
    form_class = SynthesisEditForm
    template_name = 'arbiter/synthesis_form.html'

    def get_queryset(self):
        """Restrict editable Synthesis rows to those owned by the
        signed-in user."""
        return Synthesis.objects.filter(attendee__user=self.request.user)

    def get_initial(self):
        """Pre-populate edited_text with a rendering of the structured
        content if the field is currently empty. This way Catherine
        opens the edit form and sees the full synthesis as readable
        prose ready to edit, rather than an empty textarea or a JSON
        blob."""
        initial = super().get_initial()
        if not self.object.edited_text:
            initial['edited_text'] = _synthesis_to_text(self.object)
        return initial

    def get_success_url(self):
        """Return the detail URL for the just-saved Synthesis so the
        user lands back on the document view of their edits."""
        return reverse('arbiter:synthesis_detail', kwargs={'pk': self.object.pk})


def _synthesis_to_text(synthesis):
    """Convert a Synthesis's structured AI content into plain text with
    citations resolved to readable references. Used to seed the
    edited_text field on first edit so Catherine sees prose, not JSON.

    Args:
        synthesis: a Synthesis instance with a structured content dict
            returned by the AI service layer.

    Returns:
        Plain text with section headings (uppercase, blank-line
        separated), numbered priority lists, and citation mentions
        like '(Drawn from your Opening Keynote log and your Okta
        visit.)'. If the content has parse_error, returns the raw
        AI text instead.
    """
    content = synthesis.content or {}
    if content.get('parse_error'):
        return content.get('raw', '')

    attendee = synthesis.attendee
    log_lookup = {
        log.id: log
        for log in AttendanceLog.objects
            .filter(attendee=attendee)
            .select_related('session')
    }
    vendor_lookup = {
        v.id: v for v in VendorVisit.objects.filter(attendee=attendee)
    }
    session_lookup = {
        s.id: s for s in Session.objects.filter(conference=attendee.conference)
    }

    def cite(item):
        parts = []
        for log_id in item.get('supporting_log_ids') or []:
            log = log_lookup.get(log_id)
            if log:
                title = log.session.title.strip()
                parts.append(f'your "{title}" log')
        for vendor_id in item.get('supporting_vendor_ids') or []:
            v = vendor_lookup.get(vendor_id)
            if v:
                parts.append(f'your visit to {v.vendor_name}')
        if not parts:
            return ''
        return f"(Drawn from {', '.join(parts)}.)"

    lines = []

    if content.get('diagnosis'):
        lines.append('WHAT YOU ENCOUNTERED')
        lines.append('')
        lines.append(content['diagnosis'].strip())
        lines.append('')
        lines.append('')

    if content.get('contradictions'):
        lines.append('TENSIONS WORTH RESOLVING')
        lines.append('')
        for c in content['contradictions']:
            between = (c.get('between') or '').strip()
            if between:
                lines.append(between)
                lines.append('')
            resolution = (c.get('resolution') or '').strip()
            if resolution:
                lines.append(resolution)
            citation = cite(c)
            if citation:
                lines.append('')
                lines.append(citation)
            lines.append('')
            lines.append('---')
            lines.append('')
        lines.append('')

    if content.get('priorities'):
        lines.append('PRIORITIES FOR YOUR BOARD')
        lines.append('')
        for p in content['priorities']:
            rank = p.get('rank', '?')
            title = (p.get('title') or '').strip()
            lines.append(f"{rank}. {title}")
            lines.append('')
            rationale = (p.get('rationale') or '').strip()
            if rationale:
                lines.append(rationale)
            citation = cite(p)
            if citation:
                lines.append('')
                lines.append(citation)
            lines.append('')
        lines.append('')

    if content.get('preliminary_priorities'):
        lines.append('PRELIMINARY PRIORITIES')
        lines.append('')
        for p in content['preliminary_priorities']:
            rank = p.get('rank', '?')
            title = (p.get('title') or '').strip()
            lines.append(f"{rank}. {title}")
            lines.append('')
            rationale = (p.get('rationale') or '').strip()
            if rationale:
                lines.append(rationale)
            citation = cite(p)
            if citation:
                lines.append('')
                lines.append(citation)
            lines.append('')
        lines.append('')

    if content.get('recommended_sessions'):
        lines.append('RECOMMENDED SESSIONS')
        lines.append('')
        for r in content['recommended_sessions']:
            session = session_lookup.get(r.get('session_id'))
            if session is None:
                continue
            lines.append(f"- {session.title}")
            rationale = (r.get('rationale') or '').strip()
            if rationale:
                lines.append(f"  {rationale}")
            lines.append('')
        lines.append('')

    if content.get('replan_suggestions'):
        lines.append('ADJUSTMENTS WORTH CONSIDERING')
        lines.append('')
        for s in content['replan_suggestions']:
            session = session_lookup.get(s.get('session_id'))
            action = (s.get('action') or '').capitalize()
            rationale = (s.get('rationale') or '').strip()
            if session and action:
                lines.append(f"{action} {session.title}: {rationale}")
            elif rationale:
                lines.append(rationale)
            lines.append('')
        lines.append('')

    if content.get('talking_points'):
        lines.append('MONDAY MORNING TALKING POINTS')
        lines.append('')
        for t in content['talking_points']:
            lines.append(f"- {t}")
        lines.append('')
        lines.append('')

    if content.get('warnings'):
        lines.append('NOTE')
        lines.append('')
        lines.append(content['warnings'].strip())
        lines.append('')

    return '\n'.join(lines).strip()


# ---------------------------------------------------------------------------
# Gap analysis report
# ---------------------------------------------------------------------------

@login_required
def gap_analysis(request):
    """Produce a planned-vs-attended report for the signed-in attendee,
    broken down by topic_area, with text search across session titles
    and log notes. Satisfies the assignment's "search/filter producing a
    meaningful report" requirement (more than simply linking to records
    by their foreign key).

    Filters supported via query params:
    - topic: filter logs to one topic_area
    - q: text search across session title, notes, tension_notes,
      contradiction_notes (case-insensitive substring)

    The report aggregates each topic_area into three counts:
    planned-and-attended, planned-but-skipped, and unplanned-drop-in.
    Topics with zero matching logs are omitted.

    Args:
        request: Django HttpRequest. Must be authenticated.

    Returns:
        Rendered gap_analysis.html, or a redirect to register if the
        user has no Attendee row.
    """
    attendee = _resolve_active_attendee(request)
    if attendee is None:
        return redirect('arbiter:register')

    logs = (
        AttendanceLog.objects
        .filter(attendee=attendee)
        .select_related('session', 'session__conference')
    )

    topic_filter = request.GET.get('topic', '').strip()
    if topic_filter:
        logs = logs.filter(session__topic_area=topic_filter)

    search_query = request.GET.get('q', '').strip()
    if search_query:
        logs = logs.filter(
            Q(session__title__icontains=search_query)
            | Q(notes__icontains=search_query)
            | Q(tension_notes__icontains=search_query)
            | Q(contradiction_notes__icontains=search_query)
        )

    # Aggregate logs into per-topic-area buckets with the three
    # truth-table counts. OrderedDict so iteration order is stable for
    # the template (we sort by total at the end anyway, but ordered
    # construction makes the pre-sort traversal deterministic).
    buckets: 'OrderedDict[str, dict]' = OrderedDict()
    for log in logs:
        topic = log.session.topic_area
        bucket = buckets.setdefault(topic, {
            'topic': topic,
            'planned_attended': 0,
            'planned_skipped': 0,
            'unplanned_attended': 0,
            'logs': [],
        })
        if log.planned and log.attended:
            bucket['planned_attended'] += 1
        elif log.planned and not log.attended:
            bucket['planned_skipped'] += 1
        elif not log.planned and log.attended:
            bucket['unplanned_attended'] += 1
        bucket['logs'].append(log)

    breakdown = []
    for bucket in buckets.values():
        total = (
            bucket['planned_attended']
            + bucket['planned_skipped']
            + bucket['unplanned_attended']
        )
        bucket['total'] = total
        breakdown.append(bucket)
    breakdown.sort(key=lambda b: -b['total'])

    all_topics = list(
        Session.objects
        .filter(conference=attendee.conference)
        .order_by('topic_area')
        .values_list('topic_area', flat=True)
        .distinct()
    )

    return render(request, 'arbiter/gap_analysis.html', {
        'attendee': attendee,
        'breakdown': breakdown,
        'all_topics': all_topics,
        'topic_filter': topic_filter,
        'search_query': search_query,
        'total_logs': sum(b['total'] for b in breakdown),
    })
