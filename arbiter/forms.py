# Author: Ian Sun | isun@bu.edu
# Description: Form classes for the arbiter app. Each ModelForm here
# customizes label text, placeholder copy, help text, and widget
# attributes for the corresponding model so the user-facing prompts read
# like a thoughtful tool rather than a default Django form. Lives in its
# own module rather than inline on each view because several views share
# the same form (Create and Update on AttendanceLog both use
# AttendanceLogForm).

from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User

from arbiter.models import (
    Attendee, AttendanceLog, Conference, Session, Synthesis, VendorVisit,
)


class RegistrationForm(UserCreationForm):
    """Combined User + Attendee signup form. Per the registration design
    (option b), creating an account also creates the attendee's first
    Attendee row for a Conference selected at signup; additional
    conferences are a separate post-login action.

    Built on UserCreationForm so the username + password handling (with
    proper validators and confirmation) come for free. Email is added as
    a required field on top, and the Attendee fields (conference, role,
    industry, board_question, bio) are declared on this class so a
    single form covers the whole signup. The view wraps save() in an
    atomic transaction so a partial failure cannot leave a User without
    an Attendee.
    """

    email = forms.EmailField(
        required=True,
        help_text="We use this for account recovery only. Not shared.",
    )
    conference = forms.ModelChoiceField(
        queryset=Conference.objects.order_by('-start_date'),
        empty_label='Pick a conference',
        help_text=(
            "The conference you'll be attending. You can register for "
            "additional conferences later, after signing in."
        ),
    )
    role = forms.CharField(
        max_length=200,
        help_text='e.g. "Security Manager" or "VP of Security".',
    )
    industry = forms.CharField(
        max_length=200,
        help_text='e.g. "Financial Services" or "Healthcare".',
    )
    board_question = forms.CharField(
        widget=forms.Textarea(attrs={
            'rows': 4,
            'placeholder': (
                "e.g. \"What should our security investment priority be "
                "for the next fiscal year given a flat budget?\""
            ),
        }),
        help_text=(
            "The most important field on this page. Be specific. The "
            "clearer this question, the sharper your final board "
            "recommendation will be."
        ),
    )
    bio = forms.CharField(
        widget=forms.Textarea(attrs={'rows': 3}),
        required=False,
        help_text='Optional. Anything else worth knowing about your context.',
    )

    class Meta:
        model = User
        # Username is the only User model field rendered through Meta;
        # email is declared as a Form field above so it can be marked
        # required (the model's email field is optional by default).
        # Password fields are declared by UserCreationForm itself.
        fields = ('username',)

    def save(self, commit=True):
        """Create the User first, then the linked Attendee. Returns the
        User so callers (the view) can sign the new account in
        immediately after registration.

        Args:
            commit: when True, both User and Attendee are written to the
                database. When False, returns an unsaved User and skips
                Attendee creation entirely (the view must handle saving
                in that case, but no current caller does this).

        Returns:
            The newly created User instance.
        """
        user = super().save(commit=False)
        user.email = self.cleaned_data['email']
        if commit:
            user.save()
            Attendee.objects.create(
                user=user,
                conference=self.cleaned_data['conference'],
                role=self.cleaned_data['role'],
                industry=self.cleaned_data['industry'],
                board_question=self.cleaned_data['board_question'],
                bio=self.cleaned_data.get('bio') or '',
            )
        return user


class AttendeeForm(forms.ModelForm):
    """Form for editing an Attendee profile.

    board_question is the differentiator — every AI recommendation is
    grounded in it — so this form gives it a larger textarea and a
    framing prompt that asks the user to write their actual question,
    not just a topic. The other fields (role, industry, bio) are
    supporting context and stay at default sizing.
    """

    class Meta:
        model = Attendee
        fields = [
            'role', 'industry', 'board_question', 'bio',
            'non_session_time_budget',
        ]
        labels = {
            'role': 'Your role',
            'industry': 'Industry',
            'board_question': 'What did your board send you to answer?',
            'bio': 'Bio',
            'non_session_time_budget': 'Non-session time you have planned',
        }
        help_texts = {
            'role': 'e.g. "Security Manager" or "VP of Security".',
            'industry': 'e.g. "Financial Services" or "Healthcare".',
            'board_question': (
                "The most important field on this page. Be specific. "
                "The clearer this question, the sharper your final "
                "board recommendation will be."
            ),
            'bio': 'Optional. Anything else worth knowing about your context.',
            'non_session_time_budget': (
                "Optional. Free text. Tell Arbiter when you're not "
                "attending sessions, e.g. \"~3 hours on the expo "
                "floor Wednesday afternoon, networking dinner Tuesday\". "
                "The before-phase planner uses this to avoid "
                "recommending sessions during your reserved time."
            ),
        }
        widgets = {
            'board_question': forms.Textarea(attrs={
                'rows': 4,
                'placeholder': (
                    "e.g. \"What should our security investment priority "
                    "be for the next fiscal year given a flat budget?\""
                ),
            }),
            'bio': forms.Textarea(attrs={'rows': 3}),
            'non_session_time_budget': forms.Textarea(attrs={
                'rows': 3,
                'placeholder': (
                    "e.g. \"~3 hours on the expo floor Wednesday "
                    "afternoon, networking dinner Tuesday.\""
                ),
            }),
        }


class AttendanceLogForm(forms.ModelForm):
    """Form for creating or editing an AttendanceLog row.

    The casual prompt for tension_notes is the design centerpiece.
    Catherine takes notes the way she normally would. The form does not
    ask her to articulate what contradicts what; that work belongs to the
    AI layer reading her notes after the fact. The advanced
    contradiction_flagged + contradiction_notes fields stay available as
    a power-user toggle for the rare case where she has a clear
    contradiction in mind.

    The form also scopes the session field to sessions of the attendee's
    conference so a user is not choosing from sessions at conferences
    they have not registered for. The attendee FK itself is excluded
    from the form fields; the view sets it from request.user inside
    form_valid().
    """

    class Meta:
        model = AttendanceLog
        fields = [
            'session', 'planned', 'attended',
            'notes', 'tension_notes',
            'contradiction_flagged', 'contradiction_notes',
        ]
        labels = {
            'session': 'Which session is this?',
            'planned': 'I planned to attend this session',
            'attended': 'I actually attended',
            'notes': 'Notes',
            'tension_notes': 'Did anything in this session feel different from something you heard earlier?',
            'contradiction_flagged': 'Flag a specific contradiction',
            'contradiction_notes': 'What specifically contradicts what?',
        }
        help_texts = {
            'notes': "What you heard. The way you'd take notes anywhere else.",
            'tension_notes': (
                "Optional. A casual sentence if something stuck out. "
                "No need to explain why or how."
            ),
            'contradiction_flagged': (
                "Only check this if you have already identified two "
                "specific things that contradict. Otherwise leave it "
                "alone. Arbiter surfaces contradictions for you from "
                "your notes."
            ),
        }
        widgets = {
            'notes': forms.Textarea(attrs={
                'rows': 6,
                'placeholder': "Whatever you would write in your notebook.",
            }),
            'tension_notes': forms.Textarea(attrs={
                'rows': 3,
                'placeholder': "A sentence or two if anything stuck out.",
            }),
            'contradiction_notes': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, attendee=None, **kwargs):
        """Constructor that scopes the session field to the attendee's
        conference, so a user can only log attendance at sessions of the
        conference they registered for.

        Args:
            attendee: the Attendee for whom this log is being created or
                edited. Required at form-init time so the session
                queryset can be filtered. Passed in by the view via
                get_form_kwargs(). When None (defensive default), the
                session queryset is left at its model default.
        """
        super().__init__(*args, **kwargs)
        if attendee is not None:
            self.fields['session'].queryset = (
                Session.objects
                .filter(conference=attendee.conference)
                .order_by('time_slot')
            )


class SynthesisEditForm(forms.ModelForm):
    """Form for editing a Synthesis's plain-text version. Single large
    textarea for edited_text. The view pre-populates it with a rendered
    text version of the AI's structured output, so Catherine sees
    readable prose rather than an empty textarea or a JSON blob."""

    class Meta:
        model = Synthesis
        fields = ['edited_text']
        labels = {'edited_text': 'Recommendation'}
        widgets = {
            'edited_text': forms.Textarea(attrs={
                'rows': 24,
                'class': 'synthesis-textarea',
            }),
        }


class VendorVisitForm(forms.ModelForm):
    """Form for creating or editing a VendorVisit row.

    Optimized for ~30-second mobile entry between sessions. Default
    state surfaces vendor_name, category, notes, and tension_notes.
    The contradiction_flagged + contradiction_notes pair tucks behind
    an advanced disclosure for the rare case where Catherine has a
    specific contradiction in mind. Same advisor-not-detector framing
    as AttendanceLogForm: she notes what the booth said and how it
    felt; the AI handles the analytical work.
    """

    class Meta:
        model = VendorVisit
        fields = [
            'vendor_name', 'category',
            'notes', 'tension_notes',
            'contradiction_flagged', 'contradiction_notes',
        ]
        labels = {
            'vendor_name': 'Vendor or company name',
            'category': 'Category',
            'notes': 'Notes',
            'tension_notes': (
                'Did anything they said feel different from something '
                'you heard earlier?'
            ),
            'contradiction_flagged': 'Flag a specific contradiction',
            'contradiction_notes': 'What specifically contradicts what?',
        }
        help_texts = {
            'vendor_name': 'e.g. "Okta" or "CrowdStrike".',
            'category': 'e.g. "Identity Provider" or "EDR".',
            'notes': "What the booth pitched. Quick capture is fine.",
            'tension_notes': (
                "Optional. A casual sentence if something stuck out. "
                "No need to explain why or how."
            ),
            'contradiction_flagged': (
                "Only check this if you have already identified two "
                "specific things that contradict. Otherwise leave it "
                "alone. Arbiter surfaces contradictions for you from "
                "your notes."
            ),
        }
        widgets = {
            'notes': forms.Textarea(attrs={
                'rows': 5,
                'placeholder': (
                    "What they pitched. Quick capture between "
                    "sessions is fine."
                ),
            }),
            'tension_notes': forms.Textarea(attrs={
                'rows': 3,
                'placeholder': "A sentence or two if anything stuck out.",
            }),
            'contradiction_notes': forms.Textarea(attrs={'rows': 3}),
        }
