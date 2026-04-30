# Author: Ian Sun | isun@bu.edu
# Description: Django management command that seeds the Arbiter database from
# the SecureWorld Boston 2026 agenda HTML. Reads an HTML path from the
# command line, parses it via arbiter.secureworldscraper.parse_sessions, and
# upserts one Conference plus one Session per parsed entry. Duplicate
# sessions (same conference, title, and time_slot) are skipped so the
# command is safe to re-run.

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from arbiter.models import Conference, Session
from arbiter.secureworldscraper import parse_sessions


# The agenda HTML does not carry the conference metadata in a machine-
# friendly form, so these constants supply the canonical values used when
# creating the Conference row. start_date and end_date are computed from the
# parsed sessions themselves, not hardcoded here.
CONFERENCE_NAME = "SecureWorld Boston 2026"
CONFERENCE_LOCATION = "Boston, MA"
CONFERENCE_DESCRIPTION = (
    "22nd annual SecureWorld cybersecurity conference: two days of sessions, "
    "networking, and vendor solutions for security leaders and practitioners."
)


class Command(BaseCommand):
    """Seed Conference and Session rows from a SecureWorld agenda HTML file.

    Usage: python manage.py load_secureworld <path-to-html>
    """

    help = (
        "Parse a SecureWorld agenda HTML file and create the corresponding "
        "Conference and Session rows in the Arbiter database."
    )

    def add_arguments(self, parser):
        """Register the command-line arguments for this command.

        Args:
            parser: the argparse.ArgumentParser instance that Django provides.
                Adds one required positional argument, the path to the HTML
                file to parse.
        """
        parser.add_argument(
            "html_path",
            type=str,
            help="Path to the SecureWorld agenda HTML file to parse.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        """Entry point for the command. Reads the HTML file, parses sessions,
        ensures the Conference exists, and creates one Session per parsed
        entry. Dedup key is (conference, title, time_slot): existing rows
        matching that key are left untouched. Wrapped in a single atomic
        transaction so a partial failure does not leave the database with
        half-loaded data.

        Args:
            args: unused positional arguments passed by Django.
            options: dict of parsed command-line arguments. Expects the key
                "html_path" to hold the HTML file path supplied by the user.

        Raises:
            CommandError: if the HTML file is missing or no sessions could be
                parsed from it.
        """
        path = Path(options["html_path"])
        if not path.exists():
            raise CommandError(f"HTML file not found: {path}")

        html = path.read_text(encoding="utf-8")
        parsed = parse_sessions(html)

        if not parsed:
            raise CommandError(
                "No sessions parsed from the HTML file. Double-check that "
                "the file is the SecureWorld agenda page and that the DOM "
                "still uses the expected .session-day / .session markup."
            )

        # The Conference's span is inferred from the sessions actually parsed
        # rather than from hardcoded dates, so this command keeps working if
        # the conference dates shift in a future HTML snapshot.
        start_date = min(session.time_slot.date() for session in parsed)
        end_date = max(session.time_slot.date() for session in parsed)

        conference, created = Conference.objects.get_or_create(
            name=CONFERENCE_NAME,
            defaults={
                "location": CONFERENCE_LOCATION,
                "start_date": start_date,
                "end_date": end_date,
                "description": CONFERENCE_DESCRIPTION,
            },
        )
        if created:
            self.stdout.write(self.style.SUCCESS(
                f"Created Conference: {conference}"
            ))
        else:
            self.stdout.write(f"Using existing Conference: {conference}")

        created_count = 0
        skipped_count = 0
        for parsed_session in parsed:
            _, was_created = Session.objects.get_or_create(
                conference=conference,
                title=parsed_session.title,
                time_slot=parsed_session.time_slot,
                defaults={
                    "speaker": parsed_session.speaker,
                    "topic_area": parsed_session.topic_area,
                    "description": parsed_session.description,
                },
            )
            if was_created:
                created_count += 1
            else:
                skipped_count += 1

        self.stdout.write(self.style.SUCCESS(
            f"Parsed {len(parsed)} sessions from {path.name}: "
            f"created {created_count}, skipped {skipped_count} duplicates."
        ))
