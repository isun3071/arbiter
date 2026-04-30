# Author: Ian Sun | isun@bu.edu
# Description: Registers Arbiter's data models with the Django admin site so
# course staff and the developer can create, inspect, and edit records
# through the built-in admin UI. Adds ModelAdmin classes that surface the
# fields most useful for at-a-glance review (list displays, filters, and
# search) rather than relying on the default one-row-per-object listing.

from django.contrib import admin

from arbiter.models import (
    Conference, Attendee, Session, AttendanceLog, VendorVisit, Synthesis,
)


@admin.register(Conference)
class ConferenceAdmin(admin.ModelAdmin):
    """Admin view for Conference. Surfaces name, dates, and location in the
    list view so multiple conferences can be scanned at a glance."""

    list_display = ("name", "location", "start_date", "end_date")
    search_fields = ("name", "location")
    ordering = ("-start_date",)


@admin.register(Attendee)
class AttendeeAdmin(admin.ModelAdmin):
    """Admin view for Attendee. Lists the user, the conference they are
    registered for, and the role/industry context used by the AI layer."""

    list_display = ("user", "conference", "role", "industry", "created_at")
    list_filter = ("conference", "industry")
    search_fields = ("user__username", "role", "industry", "board_question")
    autocomplete_fields = ("user", "conference")


@admin.register(Session)
class SessionAdmin(admin.ModelAdmin):
    """Admin view for Session. Orders by start time and exposes topic_area
    as a filter so the SecureWorld agenda can be browsed by track."""

    list_display = ("title", "conference", "topic_area", "time_slot", "speaker")
    list_filter = ("conference", "topic_area")
    search_fields = ("title", "speaker", "description", "topic_area")
    ordering = ("time_slot",)


@admin.register(AttendanceLog)
class AttendanceLogAdmin(admin.ModelAdmin):
    """Admin view for AttendanceLog. Exposes the planned/attended flags and
    the contradiction flag as list filters so gap analysis data can be
    reviewed without opening each row individually."""

    list_display = (
        "attendee", "session", "planned", "attended",
        "contradiction_flagged", "timestamp",
    )
    list_filter = ("planned", "attended", "contradiction_flagged")
    search_fields = (
        "attendee__user__username", "session__title", "notes",
        "contradiction_notes",
    )
    autocomplete_fields = ("attendee", "session")


@admin.register(VendorVisit)
class VendorVisitAdmin(admin.ModelAdmin):
    """Admin view for VendorVisit. Surfaces vendor_name + category in
    the list with the contradiction flag as a filter so vendor-driven
    tension can be reviewed alongside session-driven tension."""

    list_display = (
        "attendee", "vendor_name", "category",
        "contradiction_flagged", "timestamp",
    )
    list_filter = ("category", "contradiction_flagged")
    search_fields = (
        "attendee__user__username", "vendor_name", "category",
        "notes", "tension_notes", "contradiction_notes",
    )
    autocomplete_fields = ("attendee",)


@admin.register(Synthesis)
class SynthesisAdmin(admin.ModelAdmin):
    """Admin view for Synthesis. Surfaces phase and model_used as filters so
    the timeline of AI outputs for a given attendee can be reviewed quickly,
    and uses filter_horizontal for the cites M2M so the admin can see which
    AttendanceLogs each synthesis was derived from."""

    list_display = ("attendee", "phase", "model_used", "created_at")
    list_filter = ("phase", "model_used")
    search_fields = (
        "attendee__user__username", "attendee__conference__name",
    )
    autocomplete_fields = ("attendee",)
    filter_horizontal = ("cites",)
    readonly_fields = ("created_at",)
    ordering = ("-created_at",)
