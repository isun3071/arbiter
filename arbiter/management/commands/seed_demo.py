# Author: Ian Sun | isun@bu.edu
# Description: Django management command that seeds demo Conferences, Users,
# Attendees, and AttendanceLogs for the Arbiter CS412 checkpoint deliverable.
# Idempotent — re-running this command will not create duplicate rows.
# Requires that load_secureworld has already been run so that the SecureWorld
# Boston 2026 Conference and its Session rows exist.

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.db import transaction

from arbiter.models import (
    Attendee, AttendanceLog, Conference, Session, VendorVisit,
)


# Default password applied to every demo User at creation. The password is
# only set on first create — re-running the command does not stomp an
# existing user's password. sample_user.txt in the final Gradescope
# submission should point at one of these accounts plus this password.
DEMO_PASSWORD = "arbiter-demo-2026"


# Additional Conferences beyond SecureWorld Boston 2026 (which is seeded by
# load_secureworld). These are empty shells — no sessions attached — which
# is enough to satisfy the CS412 checkpoint's "3-5 records per model"
# requirement and to exercise ConferenceListView later.
DEMO_CONFERENCES = [
    {
        "name": "RSAC 2026",
        "location": "San Francisco, CA",
        "start_date": "2026-03-23",
        "end_date": "2026-03-26",
        "description": (
            "RSA Conference, the global cybersecurity industry's flagship "
            "event. Expect vendor-heavy floor, keynote-driven sessions, and "
            "widespread priority contradiction across tracks."
        ),
    },
    {
        "name": "Gartner Security & Risk Management Summit 2026",
        "location": "National Harbor, MD",
        "start_date": "2026-06-08",
        "end_date": "2026-06-10",
        "description": (
            "Gartner's annual event for security and risk management "
            "leaders. Heavy emphasis on analyst frameworks and named "
            "vendor quadrants."
        ),
    },
    {
        "name": "Black Hat USA 2026",
        "location": "Las Vegas, NV",
        "start_date": "2026-08-08",
        "end_date": "2026-08-13",
        "description": (
            "Technical cybersecurity conference focused on offensive "
            "research, zero-day disclosures, and hands-on tooling."
        ),
    },
]


# Four demo Attendees across different organizational contexts so the AI
# synthesis has recognizably different inputs per user. Each board_question
# is written the way a real board would frame the assignment: specific,
# time-bound, and tied to a live decision — not a generic "learn about
# cybersecurity" framing. All four are registered for SecureWorld Boston
# 2026 so that AttendanceLog rows can reference real seeded Sessions.
DEMO_ATTENDEES = [
    {
        "username": "catherine",
        "first_name": "Catherine",
        "last_name": "Liu",
        "email": "catherine@demo.arbiter.app",
        "conference_name": "SecureWorld Boston 2026",
        "role": "Security Manager",
        "industry": "Financial Services",
        "board_question": (
            "What should our security investment priority be for the next "
            "fiscal year given a flat budget? Present the top three "
            "priorities with rationale for the March 23 board meeting."
        ),
        "bio": (
            "Leads the security program at a regional bank of ~1,200 "
            "employees. Reports to the CRO."
        ),
        "non_session_time_budget": (
            "Planning ~3 hours on the expo floor Wednesday afternoon "
            "to talk to identity and EDR vendors specifically (per "
            "board priority). Tuesday networking dinner with the "
            "Boston ISACA chapter. Thursday morning fully on track "
            "for sessions."
        ),
    },
    {
        "username": "marcus",
        "first_name": "Marcus",
        "last_name": "Okafor",
        "email": "marcus@demo.arbiter.app",
        "conference_name": "SecureWorld Boston 2026",
        "role": "CISO",
        "industry": "Healthcare",
        "board_question": (
            "Should we accelerate our zero trust roadmap or focus on "
            "closing known identity gaps first? Recommendation needed for "
            "the Q2 executive committee review."
        ),
        "bio": (
            "CISO at a regional hospital network of five facilities, "
            "currently navigating an active Joint Commission review."
        ),
    },
    {
        "username": "priya",
        "first_name": "Priya",
        "last_name": "Raman",
        "email": "priya@demo.arbiter.app",
        "conference_name": "SecureWorld Boston 2026",
        "role": "VP of Security",
        "industry": "SaaS / Technology",
        "board_question": (
            "How do we credibly respond to customer security "
            "questionnaires asking about our AI governance posture, and "
            "what controls must be in place before the next renewal cycle?"
        ),
        "bio": None,
    },
    {
        "username": "david",
        "first_name": "David",
        "last_name": "Sorensen",
        "email": "david@demo.arbiter.app",
        "conference_name": "SecureWorld Boston 2026",
        "role": "IT Director",
        "industry": "Manufacturing",
        "board_question": (
            "What OT/IoT-specific controls should we invest in over the "
            "next 18 months given NIST SP 800-82 Rev 3 guidance and two "
            "recent incidents at peer manufacturers in our sector?"
        ),
        "bio": (
            "Solo IT/security leader at a mid-market manufacturer with "
            "three plant sites."
        ),
    },
]


# Vendor visits Catherine logged during expo floor time. Designed to
# carry real signal for the synthesis: the Okta and CrowdStrike pitches
# both contradict the Opening Keynote's "audit your existing tooling
# before buying anything new" framing, and the Lacework visit is more
# measured, included as the un-flagged baseline so the demo doesn't
# read as "every booth is a contradiction."
DEMO_VENDOR_VISITS = [
    {
        "attendee_username": "catherine",
        "vendor_name": "Okta",
        "category": "Identity Provider",
        "notes": (
            "Pitched Workforce Identity Cloud as a unified platform "
            "replacing point solutions for SSO, MFA, and lifecycle "
            "management. Demo'd identity threat protection module; "
            "claimed 80% reduction in identity-based attacks per "
            "their internal benchmarks. Pricing deferred to "
            "follow-up."
        ),
        "tension_notes": (
            "Identity-first vendor messaging conflicts with the "
            "opening keynote's fundamentals-first framing. They want "
            "me to consolidate around identity; the keynote argued "
            "I should audit my existing stack first."
        ),
        "contradiction_flagged": False,
        "contradiction_notes": "",
    },
    {
        "attendee_username": "catherine",
        "vendor_name": "CrowdStrike",
        "category": "EDR",
        "notes": (
            "Falcon platform consolidation pitch: replace your SIEM, "
            "your XDR, your identity threat protection tools, all "
            "under one console. Lead with their identity attack data. "
            "Every benchmark was vs. legacy antivirus, not modern XDR "
            "competitors."
        ),
        "tension_notes": (
            "Their consolidation pitch ignores the very vendor sprawl "
            "the keynote was about. They're selling more sprawl while "
            "claiming to solve it."
        ),
        "contradiction_flagged": True,
        "contradiction_notes": (
            "CrowdStrike claims their platform reduces tool sprawl, "
            "but they're the platform you'd be adding. The keynote's "
            "argument was to audit existing tooling for overlap "
            "before buying anything new. CrowdStrike directly "
            "contradicts that prescription."
        ),
    },
    {
        "attendee_username": "catherine",
        "vendor_name": "Lacework",
        "category": "Cloud Security",
        "notes": (
            "CNAPP pitch: runtime defense, posture management, SBOM "
            "scanning. Differentiator was their polygraph approach "
            "(behavioral baselining). Didn't have answers when I "
            "asked about cost predictability for our scale."
        ),
        "tension_notes": (
            "More analytical than the other booths but still couldn't "
            "give a straight answer on TCO."
        ),
        "contradiction_flagged": False,
        "contradiction_notes": "",
    },
]


# AttendanceLog fixtures span every meaningful (planned, attended)
# combination so the gap-analysis truth table is visible in the admin
# screenshots. Sessions are matched by case-insensitive substring on title
# to insulate the fixtures from the exact SecureWorld HTML snapshot. The
# substrings chosen use only ASCII characters so they match cleanly even
# after WordPress rewrites apostrophes to smart quotes.
DEMO_LOGS = [
    {
        "attendee_username": "catherine",
        "session_title_contains": "Opening Keynote",
        "planned": True,
        "attended": True,
        "notes": (
            "Strong framing. Speaker argued InfoSec professionals "
            "overcomplicate the job — we should be auditing our tooling "
            "for redundancy next quarter rather than chasing new "
            "categories."
        ),
        "contradiction_flagged": False,
        "contradiction_notes": "",
    },
    {
        "attendee_username": "catherine",
        "session_title_contains": "AI Advantage",
        "planned": True,
        "attended": True,
        "notes": (
            "Vendor pitch disguised as analysis. Some useful points on "
            "AI-driven alert triage, but ROI claims were unsupported and "
            "the legacy-security framing felt commercially motivated."
        ),
        "contradiction_flagged": True,
        "contradiction_notes": (
            "Directly contradicts the fundamentals-first framing from the "
            "opening keynote. Flagging for board-rec synthesis — need to "
            "arbitrate: audit existing tooling (keynote) vs. layer AI "
            "tooling on top (this session)."
        ),
    },
    {
        "attendee_username": "catherine",
        "session_title_contains": "Data Security",
        "planned": True,
        "attended": False,
        "notes": "",
        "contradiction_flagged": False,
        "contradiction_notes": "",
    },
    {
        "attendee_username": "catherine",
        "session_title_contains": "Your Help Desk Just Reset",
        "planned": False,
        "attended": True,
        "notes": (
            "Unplanned — walked in because the data security session I "
            "planned felt too product-pitch. This one was identity-focused "
            "on AI agent impersonation risk; much more relevant to the "
            "board question on prioritization."
        ),
        "contradiction_flagged": False,
        "contradiction_notes": "",
    },
    {
        "attendee_username": "marcus",
        "session_title_contains": "Shadow AI",
        "planned": True,
        "attended": True,
        "notes": (
            "Useful framing on AI governance blind spots. Aligns with the "
            "identity-before-AI thesis I'm building for the Q2 exec "
            "committee."
        ),
        "contradiction_flagged": False,
        "contradiction_notes": "",
    },
]


class Command(BaseCommand):
    """Seed demo Conferences, Users, Attendees, and AttendanceLogs for the
    Arbiter CS412 checkpoint deliverable.

    Idempotent: re-running the command does not create duplicate rows and
    does not overwrite an existing user's password. Requires that
    load_secureworld has already been run first so that the SecureWorld
    Boston 2026 Conference and its Session rows exist.
    """

    help = (
        "Seed demo Conferences, Users, Attendees, and AttendanceLogs for "
        "the Arbiter checkpoint. Safe to re-run."
    )

    @transaction.atomic
    def handle(self, *args, **options):
        """Entry point. Seeds all demo rows inside a single transaction so
        that a partial failure does not leave the database in an
        inconsistent state.

        Args:
            args: unused positional arguments.
            options: unused keyword options.
        """
        self._seed_conferences()
        self._seed_attendees()
        self._seed_logs()
        self._seed_vendor_visits()
        self.stdout.write(self.style.SUCCESS("Demo seed complete."))

    def _seed_conferences(self):
        """Create each demo Conference shell beyond SecureWorld Boston 2026.
        Uses get_or_create on name so re-runs do not create duplicates."""
        for spec in DEMO_CONFERENCES:
            _, created = Conference.objects.get_or_create(
                name=spec["name"],
                defaults={
                    "location": spec["location"],
                    "start_date": spec["start_date"],
                    "end_date": spec["end_date"],
                    "description": spec["description"],
                },
            )
            verb = "Created" if created else "Skipped existing"
            self.stdout.write(f"{verb} Conference: {spec['name']}")

    def _seed_attendees(self):
        """Create demo Users and their Attendee registrations.

        Users are created with DEMO_PASSWORD on first create; existing users
        are left untouched so rerunning the command is safe. Attendees are
        keyed on (user, conference) matching the model's unique_together
        constraint. If the referenced conference has not yet been seeded
        (typically because load_secureworld has not been run), the attendee
        is skipped with a warning rather than aborting the whole command.
        """
        for spec in DEMO_ATTENDEES:
            user, user_created = User.objects.get_or_create(
                username=spec["username"],
                defaults={
                    "email": spec["email"],
                    "first_name": spec["first_name"],
                    "last_name": spec["last_name"],
                },
            )
            if user_created:
                user.set_password(DEMO_PASSWORD)
                user.save()
                self.stdout.write(f"Created User: {spec['username']}")
            else:
                self.stdout.write(f"Skipped existing User: {spec['username']}")

            try:
                conference = Conference.objects.get(name=spec["conference_name"])
            except Conference.DoesNotExist:
                self.stdout.write(self.style.WARNING(
                    f"Skipping Attendee {spec['username']} — conference "
                    f"'{spec['conference_name']}' does not exist. Run "
                    f"load_secureworld first."
                ))
                continue

            _, attendee_created = Attendee.objects.get_or_create(
                user=user,
                conference=conference,
                defaults={
                    "role": spec["role"],
                    "industry": spec["industry"],
                    "board_question": spec["board_question"],
                    "bio": spec["bio"],
                    "non_session_time_budget": spec.get(
                        "non_session_time_budget"
                    ),
                },
            )
            verb = "Created" if attendee_created else "Skipped existing"
            self.stdout.write(
                f"{verb} Attendee: {spec['username']} @ {spec['conference_name']}"
            )

    def _seed_logs(self):
        """Create demo AttendanceLog rows covering every meaningful
        (planned, attended) combination plus one contradiction flag.

        Sessions are resolved by case-insensitive substring match on title
        so the fixtures do not break when the underlying SecureWorld HTML
        snapshot changes. If either the attendee or the session cannot be
        resolved, the log is skipped with a warning so the rest of the seed
        still succeeds.
        """
        for spec in DEMO_LOGS:
            try:
                attendee = Attendee.objects.get(
                    user__username=spec["attendee_username"]
                )
            except Attendee.DoesNotExist:
                self.stdout.write(self.style.WARNING(
                    f"Skipping log — no Attendee found for user "
                    f"'{spec['attendee_username']}'."
                ))
                continue

            session = Session.objects.filter(
                conference=attendee.conference,
                title__icontains=spec["session_title_contains"],
            ).first()
            if session is None:
                self.stdout.write(self.style.WARNING(
                    f"Skipping log for {spec['attendee_username']} — no "
                    f"Session matching '{spec['session_title_contains']}'."
                ))
                continue

            _, created = AttendanceLog.objects.get_or_create(
                attendee=attendee,
                session=session,
                defaults={
                    "planned": spec["planned"],
                    "attended": spec["attended"],
                    "notes": spec["notes"],
                    "contradiction_flagged": spec["contradiction_flagged"],
                    "contradiction_notes": spec["contradiction_notes"],
                },
            )
            verb = "Created" if created else "Skipped existing"
            self.stdout.write(
                f"{verb} AttendanceLog: {spec['attendee_username']} -> "
                f"{session.title[:50]}"
            )

    def _seed_vendor_visits(self):
        """Create demo VendorVisit rows. Idempotent on (attendee,
        vendor_name): re-running the command does not duplicate entries
        for the same attendee + vendor pair, even though the model
        itself does not enforce that uniqueness (since at a real
        conference a vendor might pitch different things across days).
        """
        for spec in DEMO_VENDOR_VISITS:
            try:
                attendee = Attendee.objects.get(
                    user__username=spec["attendee_username"]
                )
            except Attendee.DoesNotExist:
                self.stdout.write(self.style.WARNING(
                    f"Skipping vendor visit — no Attendee for user "
                    f"'{spec['attendee_username']}'."
                ))
                continue

            _, created = VendorVisit.objects.get_or_create(
                attendee=attendee,
                vendor_name=spec["vendor_name"],
                defaults={
                    "category": spec["category"],
                    "notes": spec["notes"],
                    "tension_notes": spec["tension_notes"],
                    "contradiction_flagged": spec["contradiction_flagged"],
                    "contradiction_notes": spec["contradiction_notes"],
                },
            )
            verb = "Created" if created else "Skipped existing"
            self.stdout.write(
                f"{verb} VendorVisit: {spec['attendee_username']} -> "
                f"{spec['vendor_name']}"
            )
