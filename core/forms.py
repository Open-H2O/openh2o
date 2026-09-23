# SPDX-License-Identifier: AGPL-3.0-or-later
"""Forms for user profiles and site configuration."""
from decimal import Decimal, InvalidOperation

from allauth.account.models import EmailAddress
from django import forms
from django.contrib.auth.password_validation import validate_password

from core.constants import RECOVERY_HORIZON_CHOICES
from core.models import SiteConfig, User


class ProfileForm(forms.ModelForm):
    """Edit the user's own contact details.

    Deliberately excludes email and password -- those are auth-sensitive and are
    managed through django-allauth's own pages (Email Management and Change
    Password), which keep allauth's EmailAddress table in sync. The profile page
    links to those rather than duplicating them here.
    """

    class Meta:
        model = User
        fields = ["first_name", "last_name", "phone", "title"]
        widgets = {
            "first_name": forms.TextInput(attrs={"class": "form-input"}),
            "last_name": forms.TextInput(attrs={"class": "form-input"}),
            "phone": forms.TextInput(
                attrs={"class": "form-input", "placeholder": "(555) 555-1234"}
            ),
            "title": forms.TextInput(
                attrs={"class": "form-input", "placeholder": "e.g. Water Resources Manager"}
            ),
        }
        labels = {
            "first_name": "First name",
            "last_name": "Last name",
            "phone": "Phone",
            "title": "Title",
        }


class UserCreateForm(forms.ModelForm):
    """Add a new user from the in-app admin Users page (ISS-021, 41-02).

    Email delivery isn't configured on this single-tenant deploy (ISS-015), so an
    administrator sets the new user's initial password here rather than mailing
    an invite link -- the honest path given the deploy. On save we also mint a
    verified, primary allauth ``EmailAddress`` row the same way ``ensure_superuser``
    does, so the new account can sign in by email immediately. (allauth
    authenticates against ``EmailAddress``, not ``User.email``.)
    """

    password = forms.CharField(
        widget=forms.PasswordInput(
            attrs={"class": "form-input", "autocomplete": "new-password"}
        ),
        help_text=(
            "The user signs in with this. They can change it later under "
            "Sign-in & Security."
        ),
    )

    class Meta:
        model = User
        fields = ["email", "first_name", "last_name", "title", "agency_admin"]
        widgets = {
            "email": forms.EmailInput(
                attrs={"class": "form-input", "placeholder": "name@district.gov"}
            ),
            "first_name": forms.TextInput(attrs={"class": "form-input"}),
            "last_name": forms.TextInput(attrs={"class": "form-input"}),
            "title": forms.TextInput(
                attrs={"class": "form-input", "placeholder": "e.g. Water Resources Manager"}
            ),
            "agency_admin": forms.CheckboxInput(),
        }
        labels = {
            "email": "Email",
            "first_name": "First name",
            "last_name": "Last name",
            "title": "Title",
            "agency_admin": "Administrator",
        }
        help_texts = {
            "agency_admin": (
                "Administrators can manage users, the setup wizard, and "
                "methodology. Leave unchecked for an operator (data entry and "
                "viewing only)."
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # AbstractUser.email is blank=True at the model level; on this platform
        # email IS the login, so require it on the form.
        self.fields["email"].required = True

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("A user with that email already exists.")
        return email

    def clean_password(self):
        password = self.cleaned_data["password"]
        validate_password(password)
        return password

    def save(self, commit=True):
        user = super().save(commit=False)
        email = self.cleaned_data["email"]
        # Login is by email, but AbstractUser still carries a unique username --
        # keep them in lockstep (same convention as ensure_superuser).
        user.email = email
        user.username = email
        user.is_active = True
        user.set_password(self.cleaned_data["password"])
        if commit:
            user.save()
            EmailAddress.objects.update_or_create(
                email=email,
                defaults={"user": user, "verified": True, "primary": True},
            )
        return user


class DeliverySettingsForm(forms.Form):
    """Agency-wide delivery accounting policy, in plain language (Phase 55-03).

    Edits the two SiteConfig fields Plans 01-02 added:
    ``default_irrigation_efficiency`` and ``default_recovery_horizon``. Both are
    phrased as plain questions a non-coder analyst can answer once for the whole
    agency — no internal jargon. Efficiency is SHOWN as a whole-number percent
    (75) but STORED on the model as a Decimal fraction (0.750), so this form
    converts in both directions.

    SiteConfig is a singleton; the view loads the one row and passes it in as
    ``instance``. The form never creates a second row.

    **The efficiency field belongs to ``surface`` and disappears with it (90-02).**
    ``default_irrigation_efficiency`` has exactly one consumer —
    ``surface/services.py``, which apportions a delivery between what the crop
    consumed and what returned to the aquifer. On a deployment with no Surface
    module nothing reads the number, so offering the control invites an analyst
    to tune a knob connected to nothing. ``default_recovery_horizon`` is the
    opposite case and stays: ``accounting.services.resolve_recovery_horizon`` and
    ``rollover_allocations`` read it for any zone's unused allocation, surface or
    not.

    **``diversion_report_year_rule`` belongs to ``surface`` the same way
    (146-03 Task 3).** It is the 145-01 memo's crosswalk layer for a bulk
    diversion import a later plan adds; on a deployment with no Surface
    module there is no diversion file to read, so it is shown and saved
    under exactly the same ``shows_efficiency`` gate -- kept as its own name
    (``shows_diversion_settings``) so the template reads for what it shows,
    not why.

    **The USE-row question that used to sit beside it moved to the import
    screen (146-03 Task 6, Brent's 2026-09-22 checkpoint ruling).** It is a
    question about one uploaded file, asked here months before any file
    exists, of a reader with no reason yet to hold the vocabulary; it now
    renders on the import mapping step, and only when the uploaded file
    actually has USE rows in it. ``diversion_use_type_rule`` stays on
    ``SiteConfig`` as the remembered answer, written from the import screen,
    but this form no longer shows or saves it.
    """

    efficiency_percent = forms.IntegerField(
        min_value=1,
        max_value=100,
        label="Share of delivered water the crop consumes",
        # 90-02: said "soaks back into the aquifer as recharge", which named the
        # `recharge` module's noun on deployments that do not run it. The
        # sentence does not need the word — where the water goes is already
        # said — so the copy changed rather than `_FORBIDDEN_VOCABULARY`.
        help_text="Typical: 75%.",
        widget=forms.NumberInput(
            attrs={"class": "form-input", "style": "width: 6rem;", "step": "1"}
        ),
    )
    recovery_horizon = forms.ChoiceField(
        choices=RECOVERY_HORIZON_CHOICES,
        # 90-02: was "its full surface-water allotment", which described surface
        # water on a deployment that may have none — and the setting was never
        # surface-only in the first place. Rewritten module-neutrally rather than
        # guarded, because the sentence survives it (89-02's rule).
        label=(
            "When a district doesn't use its full allotment by the end of the "
            "water year:"
        ),
        widget=forms.RadioSelect,
    )
    # 146-03 Task 3: the 145-01 memo's crosswalk layer (J6, M2). Choices come
    # off SiteConfig itself so the two never drift out of step. (J3, the
    # USE-row rule, moved to the import screen in Task 6 -- see the class
    # docstring.)
    diversion_report_year_rule = forms.ChoiceField(
        choices=SiteConfig.DIVERSION_REPORT_YEAR_RULE_CHOICES,
        label="Which months does a reporting year cover?",
        help_text="Used when a file gives a year and a month but no date.",
        widget=forms.RadioSelect,
    )
    season_start_month = forms.IntegerField(
        required=False,
        min_value=1,
        max_value=12,
        label="If the report year above is a season, which month does it start?",
        help_text="1-12. Used only when the report year rule above is a season.",
        widget=forms.NumberInput(
            attrs={"class": "form-input", "style": "width: 6rem;", "step": "1", "min": "1", "max": "12"}
        ),
    )

    # 146-06 Task 1 (ISS-019): the one stored piece of the persistent
    # identifier scheme. Owned by `core`, so it is shown whatever modules run.
    identifier_host = forms.CharField(
        required=False,
        max_length=200,
        label="Where your record addresses are published",
        help_text="Each record here has a permanent address ending in "
        "/id/<kind>/<number>/, shown on its page. Leave this "
        "blank to use this site's own address. Set it before registering "
        "with Geoconnex (the Internet of Water's public index of water "
        "records) so the addresses never change.",
        widget=forms.TextInput(
            attrs={"class": "form-input", "placeholder": "water.example.org"}
        ),
    )

    def __init__(self, *args, instance=None, **kwargs):
        from core.modules import is_enabled

        self.instance = instance
        self.shows_efficiency = is_enabled("surface")
        # Same gate as efficiency (see the class docstring), named for what
        # it shows rather than for the reason both happen to share.
        self.shows_diversion_settings = self.shows_efficiency
        if instance is not None and "initial" not in kwargs:
            initial = {
                "recovery_horizon": instance.default_recovery_horizon,
                "identifier_host": instance.identifier_host,
            }
            if self.shows_efficiency:
                # 0.750 (fraction) -> 75 (percent), rounded to a whole number.
                initial["efficiency_percent"] = int(
                    (instance.default_irrigation_efficiency * 100).to_integral_value()
                )
            if self.shows_diversion_settings:
                initial["diversion_report_year_rule"] = instance.diversion_report_year_rule
                initial["season_start_month"] = instance.season_start_month
            kwargs["initial"] = initial
        super().__init__(*args, **kwargs)
        if not self.shows_efficiency:
            del self.fields["efficiency_percent"]
        if not self.shows_diversion_settings:
            del self.fields["diversion_report_year_rule"]
            del self.fields["season_start_month"]
        # Plain-language radio labels — these are what the manager reads, NOT the
        # model's choice labels. Option order matches RECOVERY_HORIZON_CHOICES.
        self.fields["recovery_horizon"].choices = [
            ("carry_forward", "Carry it forward as a credit toward next year"),
            ("same_water_year", "Let it expire (use-it-or-lose-it)"),
        ]
        if self.shows_diversion_settings:
            self.fields["diversion_report_year_rule"].choices = [
                ("water_year", "Water year: October to September"),
                ("calendar_year", "Calendar year: January to December"),
                ("season", "A single irrigation season each year"),
            ]

    def clean_identifier_host(self):
        from core.identifiers import normalize_host

        value = normalize_host(self.cleaned_data.get("identifier_host"))
        if any(ch.isspace() for ch in value):
            raise forms.ValidationError(
                "Enter a host name such as water.example.org, with no spaces."
            )
        return value

    def clean_efficiency_percent(self):
        percent = self.cleaned_data["efficiency_percent"]
        # Percent (75) -> Decimal fraction (0.750), the stored convention.
        try:
            return (Decimal(percent) / Decimal("100")).quantize(Decimal("0.001"))
        except InvalidOperation:
            raise forms.ValidationError("Enter a whole number between 1 and 100.")

    def save(self):
        """Write the shown fields back onto the singleton SiteConfig instance.

        ``update_fields`` is built from what the form actually rendered, so a
        deployment with no Surface module leaves ``default_irrigation_efficiency``
        (and the reporting-year setting) exactly as they were rather than
        writing a value nobody was offered.
        """
        config = self.instance
        updated = ["default_recovery_horizon", "identifier_host"]
        config.default_recovery_horizon = self.cleaned_data["recovery_horizon"]
        config.identifier_host = self.cleaned_data.get("identifier_host", "")
        if self.shows_efficiency:
            config.default_irrigation_efficiency = self.cleaned_data[
                "efficiency_percent"
            ]
            updated.append("default_irrigation_efficiency")
        if self.shows_diversion_settings:
            config.diversion_report_year_rule = self.cleaned_data["diversion_report_year_rule"]
            config.season_start_month = self.cleaned_data.get("season_start_month")
            updated.extend([
                "diversion_report_year_rule", "season_start_month",
            ])
        config.save(update_fields=updated)
        return config
