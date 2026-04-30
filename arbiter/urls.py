# Author: Ian Sun | isun@bu.edu
# Description: URL routing for the arbiter app. Maps every page Catherine
# can reach to its view class or function. Mounted under /arbiter/ by the
# project-level cs412/urls.py, so paths declared here are reached at
# /arbiter/<pattern>. Auth views (login, logout) are wired here as well so
# that all of Arbiter's URL surface lives in one app's URLconf.

from django.contrib.auth import views as auth_views
from django.urls import path, reverse_lazy

from arbiter import views


# Namespace every URL name under "arbiter:" so reverse() and {% url %} calls
# stay unambiguous if the project ever grows additional apps that also have
# a "home" or "login" route.
app_name = 'arbiter'


urlpatterns = [
    # Home — landing page for anonymous visitors; redirects authenticated
    # users to their dashboard at /arbiter/dashboard/.
    path('', views.HomeView.as_view(), name='home'),

    # Dashboard — authenticated workspace. Single anchor view that
    # surfaces the board_question, recent activity, and "what's next"
    # CTAs into the primary workflows.
    path(
        'dashboard/',
        views.DashboardView.as_view(),
        name='dashboard',
    ),

    # Registration: creates a User + an Attendee in one flow per the
    # registration design (option b — signup is conference-scoped, additional
    # conferences require a separate post-login action).
    path('register/', views.AttendeeCreateView.as_view(), name='register'),

    # Authentication. Django's stock LoginView and LogoutView are sufficient;
    # only the template path and the post-logout redirect target need to be
    # customized. The login template lives in arbiter/templates/arbiter/
    # rather than the default registration/ namespace so all Arbiter
    # templates sit together under one namespace.
    path(
        'accounts/login/',
        auth_views.LoginView.as_view(template_name='arbiter/login.html'),
        name='login',
    ),
    path(
        'accounts/logout/',
        auth_views.LogoutView.as_view(next_page=reverse_lazy('arbiter:home')),
        name='logout',
    ),

    # Attendee profile: edit role, industry, board_question, bio. There is no
    # AttendeeDeleteView in v1 — deleting an attendee is an account-level
    # action handled via the admin or a future "delete my account" flow.
    path(
        'profile/',
        views.AttendeeUpdateView.as_view(),
        name='attendee_update',
    ),

    # Conference: read-only for attendees. Create / update / delete happen
    # in the Django admin (Conference is staff-managed metadata).
    path(
        'conferences/',
        views.ConferenceListView.as_view(),
        name='conference_list',
    ),
    path(
        'conferences/<int:pk>/',
        views.ConferenceDetailView.as_view(),
        name='conference_detail',
    ),

    # Session: full CRUD. Create / update / delete are staff-only and
    # enforced inside the view classes via UserPassesTestMixin so an
    # authenticated attendee cannot inject fake sessions into the agenda.
    path(
        'sessions/',
        views.SessionListView.as_view(),
        name='session_list',
    ),
    path(
        'sessions/<int:pk>/',
        views.SessionDetailView.as_view(),
        name='session_detail',
    ),
    path(
        'sessions/new/',
        views.SessionCreateView.as_view(),
        name='session_create',
    ),
    path(
        'sessions/<int:pk>/edit/',
        views.SessionUpdateView.as_view(),
        name='session_update',
    ),
    path(
        'sessions/<int:pk>/delete/',
        views.SessionDeleteView.as_view(),
        name='session_delete',
    ),

    # AttendanceLog: full CRUD scoped to the signed-in attendee. The view
    # classes filter querysets by request.user.attendees so one attendee
    # cannot see or edit another attendee's logs.
    path(
        'attendance/',
        views.AttendanceLogListView.as_view(),
        name='attendance_list',
    ),
    path(
        'attendance/log/',
        views.AttendanceLogCreateView.as_view(),
        name='attendance_create',
    ),
    path(
        'attendance/<int:pk>/edit/',
        views.AttendanceLogUpdateView.as_view(),
        name='attendance_update',
    ),
    path(
        'attendance/<int:pk>/delete/',
        views.AttendanceLogDeleteView.as_view(),
        name='attendance_delete',
    ),

    # VendorVisit: full CRUD scoped to the signed-in attendee. Mirrors
    # the AttendanceLog surface; vendor visits feed the AI synthesis
    # alongside session attendance.
    path(
        'vendors/',
        views.VendorVisitListView.as_view(),
        name='vendor_list',
    ),
    path(
        'vendors/log/',
        views.VendorVisitCreateView.as_view(),
        name='vendor_create',
    ),
    path(
        'vendors/<int:pk>/edit/',
        views.VendorVisitUpdateView.as_view(),
        name='vendor_update',
    ),
    path(
        'vendors/<int:pk>/delete/',
        views.VendorVisitDeleteView.as_view(),
        name='vendor_delete',
    ),

    # AI endpoints. Function-based because each one assembles a request-
    # specific OpenRouter call and persists a Synthesis row — generic CBVs
    # would not save more than they cost. Expect POST; require_POST is
    # enforced inside each view.
    path('ai/plan/', views.session_plan, name='ai_session_plan'),
    path('ai/replan/', views.dynamic_replan, name='ai_dynamic_replan'),
    path('ai/synthesize/', views.final_board_rec, name='ai_final_board_rec'),

    # Synthesis: list every persisted recommendation chronologically;
    # view a single one in the document register; edit its plain-text
    # version. The export endpoint on detail reads edited_text when
    # populated and falls back to content, structurally enforcing the
    # review-before-present workflow.
    path(
        'synthesis/',
        views.SynthesisListView.as_view(),
        name='synthesis_list',
    ),
    path(
        'synthesis/<int:pk>/',
        views.SynthesisDetailView.as_view(),
        name='synthesis_detail',
    ),
    path(
        'synthesis/<int:pk>/edit/',
        views.SynthesisUpdateView.as_view(),
        name='synthesis_update',
    ),
    path(
        'synthesis/<int:pk>/delete/',
        views.SynthesisDeleteView.as_view(),
        name='synthesis_delete',
    ),

    # Gap analysis report: planned-vs-attended diff for the signed-in
    # attendee. Function-based because the output is a derived report
    # rather than a single model record.
    path('gap/', views.gap_analysis, name='gap_analysis'),
]
