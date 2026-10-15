# SPDX-License-Identifier: AGPL-3.0-or-later
"""Forms for user profiles and site configuration."""
from decimal import Decimal, InvalidOperation

from allauth.account.models import EmailAddress
from django import forms
from django.contrib.auth.password_validation import validate_password

from core.constants import RECOVERY_HORIZON_CHOICES
from core.history import CHANGE_NOTE_HELP, NOTE_MAX_LENGTH
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


# The three roles, in the order the Users screen offers them (147-02). An
# administrator is `agency_admin`; a viewer is `read_only`; an operator is
# neither. They are exclusive: User.clean() refuses a viewer who is also an
# administrator.
ROLE_ADMINISTRATOR = "administrator"
ROLE_OPERATOR = "operator"
ROLE_VIEWER = "viewer"
ROLE_CHOICES = [
    (ROLE_ADMINISTRATOR, "Administrator"),
    (ROLE_OPERATOR, "Operator"),
    (ROLE_VIEWER, "Viewer (read only)"),
]
ROLE_HELP = (
    "Administrators also manage users and the agency's settings. Operators "
    "enter and view data. Viewers read every page and change nothing."
)


def role_of(user):
    """The role value for ``user``, one of ROLE_CHOICES."""
    if user.agency_admin or user.is_staff:
        return ROLE_ADMINISTRATOR
    if user.read_only:
        return ROLE_VIEWER
    return ROLE_OPERATOR


def apply_role(user, role):
    """Set ``user``'s role flags for ``role``; returns the fields changed."""
    user.agency_admin = role == ROLE_ADMINISTRATOR
    user.read_only = role == ROLE_VIEWER
    return ["agency_admin", "read_only"]


class UserCreateForm(forms.ModelForm):
    """Add a new user from the in-app admin Users page (ISS-021, 41-02).

    Email delivery isn't configured on this single-tenant deploy (ISS-015), so an
    administrator sets the new user's initial password here rather than mailing
    an invite link -- the honest path given the deploy. On save we also mint a
    verified, primary allauth ``EmailAddress`` row the same way ``ensure_superuser``
    does, so the new account can sign in by email immediately. (allauth
    authenticates against ``EmailAddress``, not ``User.email``.)

    The role is one choice of three (147-02), stored on the two flags by
    :func:`apply_role`.
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
    role = forms.ChoiceField(
        choices=ROLE_CHOICES,
        initial=ROLE_OPERATOR,
        widget=forms.RadioSelect,
        label="Role",
        help_text=ROLE_HELP,
    )

    class Meta:
        model = User
        fields = ["email", "first_name", "last_name", "title"]
        widgets = {
            "email": forms.EmailInput(
                attrs={"class": "form-input", "placeholder": "name@district.gov"}
            ),
            "first_name": forms.TextInput(attrs={"class": "form-input"}),
            "last_name": forms.TextInput(attrs={"class": "form-input"}),
            "title": forms.TextInput(
                attrs={"class": "form-input", "placeholder": "e.g. Water Resources Manager"}
            ),
        }
        labels = {
            "email": "Email",
            "first_name": "First name",
            "last_name": "Last name",
            "title": "Title",
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
        apply_role(user, self.cleaned_data["role"])
        user.set_password(self.cleaned_data["password"])
        if commit:
            user.save()
            EmailAddress.objects.update_or_create(
                email=email,
                defaults={"user": user, "verified": True, "primary": True},
            )
        return user


class UserRoleForm(forms.Form):
    """The Users screen's per-row role control (147-02)."""

    role = forms.ChoiceField(choices=ROLE_CHOICES)


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

    **The efficiency field belongs to ``parcels`` (150.2-01).** From 90-02 it
    belonged to ``surface`` and disappeared with it, because its one consumer
    then apportioned canal deliveries. It is a field's irrigation efficiency
    wherever no irrigation method is on file (``parcels.services.field_efficiency``),
    and a groundwater-only district has fields too (Brent, 2026-10-11), so it is
    shown whenever ``parcels`` runs. ``default_recovery_horizon`` stays for the
    same reason: ``accounting.services.resolve_recovery_horizon`` and
    ``rollover_allocations`` read it for any zone's unused allocation, surface or
    not.

    **There is no separate groundwater efficiency (150.2-02).** From 148-02
    to 150.2-02 a flat ``groundwater_efficiency`` (80%) had its own card here;
    Brent ruled "one irrigation efficiency per field" (2026-10-11), so
    ``run_calculations`` divides pumped groundwater by the same field
    efficiency the default above feeds, and the setting is gone.

    **The over-delivery treatment belongs to ``surface`` the same way (148-04
    Task 1, Brent's Q1 ruling 2026-09-20).** ``over_delivery_treatment`` and
    ``over_delivery_leave_behind`` are read once per run by
    ``run_calculations`` (148-04 Task 2); only canal water can be
    over-delivered, so both fields are shown and saved under the
    ``shows_surface_settings`` gate. Both fields are ``required=False`` at the
    Django level so a caller that does not offer them (an old test, or a
    deployment with ``surface`` off) leaves the stored values exactly as
    they were rather than writing a value nobody was offered -- the same
    "leave it alone" outcome a module gate gives every other field
    here, reached a different way because this pair shares one card with a
    conditional second field (the percent only applies to "credited").

    **``diversion_report_year_rule`` belongs to ``surface`` the same way
    (146-03 Task 3).** It is the 145-01 memo's crosswalk layer for a bulk
    diversion import a later plan adds; on a deployment with no Surface
    module there is no diversion file to read, so it is shown and saved
    under exactly the same ``shows_surface_settings`` gate -- kept as its own name
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
        label="Default irrigation efficiency",
        # 90-02: said "soaks back into the aquifer as recharge", which named the
        # `recharge` module's noun on deployments that do not run it. The
        # sentence does not need the word — where the water goes is already
        # said — so the copy changed rather than `_FORBIDDEN_VOCABULARY`.
        # 150.2-02 (Brent, 2026-10-11 13:25 PDT: "approved").
        help_text="Typical: 75%. OpenH2O uses this efficiency for every field "
        "with no irrigation method on file.",
        widget=forms.NumberInput(
            attrs={"class": "form-input", "style": "width: 6rem;", "step": "1"}
        ),
    )
    # 148-04 Task 1: what happens to surface water in excess of ETAW
    # (150.1-02, Brent's term, 2026-10-11). `required=False` at the Django level (see
    # the class docstring) -- a submission that omits it leaves the stored
    # treatment untouched, same convention as `identifier_host` blank meaning
    # "use the default". Plain-language radio labels are set in __init__,
    # like `recovery_horizon`'s.
    over_delivery_treatment = forms.ChoiceField(
        choices=SiteConfig.OVER_DELIVERY_TREATMENT_CHOICES,
        required=False,
        label="Surface water in excess of ETAW",
        widget=forms.RadioSelect,
    )
    # Shown/entered as a whole-number percent, stored as a Decimal fraction --
    # the same convention as `efficiency_percent`. Required only when
    # "credited" is the chosen treatment (enforced in `clean()`); otherwise
    # the stored leave-behind share is left exactly as it was.
    over_delivery_leave_behind_percent = forms.IntegerField(
        required=False,
        min_value=0,
        max_value=100,
        label="Share left in the basin",
        # 148-04: the sentence about fields without a well is in the
        # template, behind the `wells` gate: a kept page may not name a
        # dropped module's noun (tests/droppability).
        help_text="Under the credited choice, OpenH2O leaves this share of the "
        "surface water in excess of ETAW in the basin, credited to no one, and "
        "credits the rest to the landowner. 10 percent unless an administrator "
        "changes it. A changed setting affects a past month only when that "
        "month is recalculated.",
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
            "When a zone doesn't use its full allocation by the end of the "
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

    # Phase 147: why the settings changed, saved with the change in the change
    # history (core/history.py). Optional here; not a SiteConfig field. 147-02
    # (Brent's checkpoint ruling) removed this field's box from the page; the
    # recording stays, so a caller (or a future one) can still supply a note.
    note = forms.CharField(
        required=False,
        max_length=NOTE_MAX_LENGTH,
        label="Note (why)",
        help_text=CHANGE_NOTE_HELP,
        widget=forms.TextInput(
            attrs={"class": "form-input", "maxlength": str(NOTE_MAX_LENGTH)}
        ),
    )

    def __init__(self, *args, instance=None, **kwargs):
        from core.modules import is_enabled

        self.instance = instance
        # 150.2-01: the default irrigation efficiency belongs to `parcels`,
        # which every deployment that reaches this page runs (the page is
        # `accounting`'s, and the two are an inseparable pair).
        self.shows_efficiency = is_enabled("parcels")
        # The cards only a canal district has: surface water in excess of
        # ETAW and the reporting-year rule. This was `shows_efficiency` until
        # 150.2-01 moved the efficiency off `surface`.
        self.shows_surface_settings = is_enabled("surface")
        # Same gate as the surface settings, named for what it shows.
        self.shows_diversion_settings = self.shows_surface_settings
        # Whether the deployment has wells: the credited choice's sentence
        # about a field with no well is said only where a field can have one.
        self.has_wells = is_enabled("wells")
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
            if self.shows_surface_settings:
                initial["over_delivery_treatment"] = instance.over_delivery_treatment
                initial["over_delivery_leave_behind_percent"] = int(
                    (instance.over_delivery_leave_behind * 100).to_integral_value()
                )
            if self.shows_diversion_settings:
                initial["diversion_report_year_rule"] = instance.diversion_report_year_rule
                initial["season_start_month"] = instance.season_start_month
            kwargs["initial"] = initial
        super().__init__(*args, **kwargs)
        if not self.shows_efficiency:
            del self.fields["efficiency_percent"]
        if not self.shows_surface_settings:
            del self.fields["over_delivery_treatment"]
            del self.fields["over_delivery_leave_behind_percent"]
        if not self.shows_diversion_settings:
            del self.fields["diversion_report_year_rule"]
            del self.fields["season_start_month"]
        # Plain-language radio labels — these are what the manager reads, NOT the
        # model's choice labels. Option order matches RECOVERY_HORIZON_CHOICES.
        self.fields["recovery_horizon"].choices = [
            ("carry_forward", "Carry it forward as a credit toward next year"),
            ("same_water_year", "Let it expire (use-it-or-lose-it)"),
        ]
        if self.shows_surface_settings:
            # The settled words (148-03, 2026-09-28): the radio's label is the
            # choice, one line; what it does is the description the template
            # prints under it (`over_delivery_options`). No "recharge": this
            # page is served without that module.
            self.fields["over_delivery_treatment"].choices = [
                ("not_credited", "Not credited to anyone."),
                ("credited", "Credited to the landowner, less a share left in the basin."),
                ("named_line", "Shown on the field's page as its own line."),
            ]
        if self.shows_diversion_settings:
            self.fields["diversion_report_year_rule"].choices = [
                ("water_year", "Water year: October to September"),
                ("calendar_year", "Calendar year: January to December"),
                ("season", "A single irrigation season each year"),
            ]

    @property
    def over_delivery_options(self):
        """``(radio, description)`` per choice, in the choices' own order.

        148-03: the Delivery Settings card prints each choice as a label line
        with what it does on a quieter line under it, so the three radios
        line up instead of wrapping to three different lengths. The
        descriptions live here, beside the labels, and not in the template,
        so the words that describe a choice sit with the choice. Empty when
        the field is not shown (no ``surface`` module).
        """
        if not self.shows_surface_settings:
            return []
        if self.has_wells:
            credited = (
                "The landowner's share is a credit on the field's ledger. "
                "A field with no well has its share go to the zone's shared "
                "account, because it has no well to pump it back."
            )
        else:
            credited = (
                "The landowner's share is a credit on the field's ledger. "
                "The share goes to the zone's shared account."
            )
        descriptions = {
            "not_credited": (
                "The amount is recorded with the month's figures and nothing "
                "else happens. This is the default."
            ),
            "credited": credited,
            "named_line": (
                "Not a credit and not charged. The field's water balance "
                "reads the same as under the other two choices."
            ),
        }
        return [
            (radio, descriptions[radio.data["value"]])
            for radio in self["over_delivery_treatment"]
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

    def clean_over_delivery_leave_behind_percent(self):
        percent = self.cleaned_data.get("over_delivery_leave_behind_percent")
        if percent is None:
            return None
        # Percent (90) -> Decimal fraction (0.900), the stored convention.
        try:
            return (Decimal(percent) / Decimal("100")).quantize(Decimal("0.001"))
        except InvalidOperation:
            raise forms.ValidationError("Enter a whole number between 0 and 100.")

    def clean(self):
        cleaned = super().clean()
        if self.shows_surface_settings:
            treatment = cleaned.get("over_delivery_treatment")
            leave_behind = cleaned.get("over_delivery_leave_behind_percent")
            if treatment == "credited" and leave_behind is None:
                self.add_error(
                    "over_delivery_leave_behind_percent",
                    "Enter the share left in the basin when crediting the "
                    "landowner.",
                )
        if self.shows_diversion_settings:
            # 150.1-02 screen 18 (Brent 18:01, message B row 9): a season with
            # no starting month failed every row of a Water Use Reported file.
            if (
                cleaned.get("diversion_report_year_rule") == "season"
                and not cleaned.get("season_start_month")
            ):
                self.add_error(
                    "season_start_month", "Enter the season's starting month."
                )
        return cleaned

    def save(self):
        """Write the shown fields back onto the singleton SiteConfig instance.

        ``update_fields`` is built from what the form actually rendered, so a
        deployment with no Surface module leaves the surface settings (and the
        reporting-year setting) exactly as they were rather than writing a
        value nobody was offered.
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
        if self.shows_surface_settings:
            # 148-04 Task 1: a submission that omits the treatment (nobody
            # was offered it, e.g. a caller built before this plan) leaves
            # both stored values exactly as they were. A submitted treatment
            # other than "credited" leaves the stored leave-behind share
            # untouched too -- it only means something when crediting.
            treatment = self.cleaned_data.get("over_delivery_treatment")
            if treatment:
                config.over_delivery_treatment = treatment
                updated.append("over_delivery_treatment")
                if treatment == "credited":
                    config.over_delivery_leave_behind = self.cleaned_data[
                        "over_delivery_leave_behind_percent"
                    ]
                    updated.append("over_delivery_leave_behind")
        if self.shows_diversion_settings:
            config.diversion_report_year_rule = self.cleaned_data["diversion_report_year_rule"]
            config.season_start_month = self.cleaned_data.get("season_start_month")
            updated.extend([
                "diversion_report_year_rule", "season_start_month",
            ])
        config.save(update_fields=updated)
        return config
