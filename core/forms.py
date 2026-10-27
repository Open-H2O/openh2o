# SPDX-License-Identifier: AGPL-3.0-or-later
"""Forms for user profiles and site configuration."""
from decimal import Decimal, InvalidOperation

from allauth.account.models import EmailAddress
from django import forms
from django.contrib.auth.password_validation import validate_password
from django.core.validators import EmailValidator

from core.account_forms import BLANK_AGAIN, BLANK_NEW, MISMATCH
from core.constants import RECOVERY_HORIZON_CHOICES
from core.history import CHANGE_NOTE_HELP, NOTE_MAX_LENGTH
from core.models import SiteConfig, User

# Replaces Django's "Enter a
# valid email address." on every form where an administrator types an address.
INCOMPLETE_EMAIL_VALIDATOR = EmailValidator(
    message="%(value)s is not a complete email address."
)


class ProfileForm(forms.ModelForm):
    """Edit the user's own contact details.

    Deliberately excludes email and password. The email address is the sign-in
    name and only an administrator changes it, on the Users page
    (:class:`UserEmailForm`); the password has its
    own page, linked from the profile.
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


# The three roles, in the order the Users screen offers them. An
# administrator is `agency_admin`; a viewer is `read_only`; an operator is
# neither. They are exclusive: User.clean() refuses a viewer who is also an
# administrator.
ROLE_ADMINISTRATOR = "administrator"
ROLE_OPERATOR = "operator"
ROLE_VIEWER = "viewer"
# A host administrator is is_staff. Offered on the Users page
# only to a reader who is one, so it is not in ROLE_CHOICES (Add user keeps three).
ROLE_HOST_ADMINISTRATOR = "host_administrator"
ROLE_CHOICES = [
    (ROLE_ADMINISTRATOR, "Administrator"),
    (ROLE_OPERATOR, "Operator"),
    (ROLE_VIEWER, "Viewer"),
]
# The help line under the role choice.
ROLE_HELP = (
    "Viewers read every record and change none. Operators also add, change "
    "and remove records. Administrators also manage users, set up the site, "
    "change the site's settings and finalize or reopen a water year."
)


HOST_ADMINISTRATOR_CHOICE = (ROLE_HOST_ADMINISTRATOR, "Host administrator")


def role_of(user):
    """The role value for ``user``: ROLE_CHOICES, or ``host_administrator``."""
    if user.is_staff:
        return ROLE_HOST_ADMINISTRATOR
    if user.agency_admin:
        return ROLE_ADMINISTRATOR
    if user.read_only:
        return ROLE_VIEWER
    return ROLE_OPERATOR


def apply_role(user, role):
    """Set ``user``'s role flags for ``role``; returns the fields changed."""
    if role == ROLE_HOST_ADMINISTRATOR:
        user.is_staff = True
        user.is_superuser = True
        user.agency_admin = False
        user.read_only = False
    else:
        # Any other role on a host administrator takes the host rank away.
        user.is_staff = False
        user.is_superuser = False
        user.agency_admin = role == ROLE_ADMINISTRATOR
        user.read_only = role == ROLE_VIEWER
    return ["is_staff", "is_superuser", "agency_admin", "read_only"]


class UserCreateForm(forms.ModelForm):
    """Add a new user from the in-app admin Users page.

    A deployment may have no mail server (no ``EMAIL_HOST``), so an
    administrator sets the new user's initial password here rather than mailing
    an invite link -- the honest path given the deploy. On save we also mint a
    verified, primary allauth ``EmailAddress`` row the same way ``ensure_superuser``
    does, so the new account can sign in by email immediately. (allauth
    authenticates against ``EmailAddress``, not ``User.email``.)

    The role is one choice of three, stored on the two flags by
    :func:`apply_role`.
    """

    password = forms.CharField(
        widget=forms.PasswordInput(
            attrs={"class": "form-input", "autocomplete": "new-password"}
        ),
        error_messages={"required": "Enter the starting password."},
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
                attrs={"class": "form-input", "placeholder": "name@example.com"}
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
        self.fields["email"].error_messages["required"] = "Enter the email address."
        # The same validator on Add user.
        self.fields["email"].validators = [INCOMPLETE_EMAIL_VALIDATOR]

    def clean_email(self):
        # An address on file as any account's (a second address added under
        # Manage email included) is refused; otherwise the save's
        # update_or_create would move it onto this account.
        email = self.cleaned_data["email"].strip().lower()
        if (
            User.objects.filter(email__iexact=email).exists()
            or EmailAddress.objects.filter(email__iexact=email).exists()
        ):
            raise forms.ValidationError(
                f"The email address {email} already belongs to an account."
            )
        return email

    def clean_password(self):
        # Row 10: with no user passed, Django's check against the email and
        # names never ran. The fields above are cleaned before this one.
        password = self.cleaned_data["password"]
        validate_password(password, user=User(
            email=self.cleaned_data.get("email", ""),
            first_name=self.cleaned_data.get("first_name", ""),
            last_name=self.cleaned_data.get("last_name", ""),
        ))
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
        user.must_choose_password = True
        if commit:
            user.save()
            EmailAddress.objects.update_or_create(
                email=email,
                defaults={"user": user, "verified": True, "primary": True},
            )
        return user


class UserRoleForm(forms.Form):
    """The Users screen's per-row role control."""

    role = forms.ChoiceField(choices=ROLE_CHOICES + [HOST_ADMINISTRATOR_CHOICE])


class _TwoPasswordsForm(forms.Form):
    """Two password boxes that must match and pass Django's checks.

    The mismatch sentence and the refusals are the ones Change password and
    Add user already use (core/account_forms.py, core/password_validation.py).
    ``user`` is passed to the checks so the similarity check runs.
    """

    password1 = forms.CharField(
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
        error_messages={"required": BLANK_NEW},
    )
    password2 = forms.CharField(
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
        error_messages={"required": BLANK_AGAIN},
    )

    def __init__(self, *args, user, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned = super().clean()
        one, two = cleaned.get("password1"), cleaned.get("password2")
        if one and two and one != two:
            self.add_error("password2", MISMATCH)
        elif one and two:
            self.check_password(one)
        return cleaned

    def check_password(self, password):
        # The username copies the email, so Django would name the username,
        # which nobody here sees; check against what Add user checks.
        try:
            validate_password(password, user=User(
                email=self.user.email,
                first_name=self.user.first_name,
                last_name=self.user.last_name,
            ))
        except forms.ValidationError as error:
            self.add_error("password1", error)


class TemporaryPasswordForm(_TwoPasswordsForm):
    """An administrator sets another person's temporary password."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["password1"].label = "Temporary password"
        self.fields["password1"].error_messages["required"] = "Enter the temporary password."
        self.fields["password2"].label = "Confirm temporary password"
        self.fields["password2"].error_messages["required"] = "Enter the temporary password again."


SAME_AS_CURRENT = "The new password must be different from your current password."


class ChoosePasswordForm(_TwoPasswordsForm):
    """A person replaces the password an administrator set."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["password1"].label = "New password"
        self.fields["password2"].label = "Confirm new password"

    def check_password(self, password):
        if self.user.check_password(password):
            self.add_error("password1", SAME_AS_CURRENT)
            return
        super().check_password(password)


def email_on_file(email, exclude_user=None):
    """Whether ``email`` is any account's address, in either table.

    allauth signs a person in by any of their ``EmailAddress`` rows and falls
    back to ``User.email`` (and the username here mirrors the email), so an
    address counts as taken if any of the three holds it.
    """
    users = User.objects.filter(email__iexact=email) | User.objects.filter(
        username__iexact=email
    )
    rows = EmailAddress.objects.filter(email__iexact=email)
    if exclude_user is not None:
        users = users.exclude(pk=exclude_user.pk)
        rows = rows.exclude(user=exclude_user)
    return users.exists() or rows.exists()


class UserEmailForm(forms.Form):
    """An administrator changes another person's email address.

    Only an administrator changes an address, and a person has one address.
    The person's sign-in name changes with it,
    so the save rewrites ``User.email``, the username kept in step with it, and
    allauth's one ``EmailAddress`` row, which is what sign-in reads first.
    Any second row left from the removed email page goes, so the old address
    stops signing in.
    """

    email = forms.EmailField(
        label="New email address",
        widget=forms.EmailInput(
            attrs={"class": "form-input", "placeholder": "name@example.com"}
        ),
        error_messages={"required": "Enter the email address."},
    )

    def __init__(self, *args, target, **kwargs):
        self.target = target
        super().__init__(*args, **kwargs)
        self.fields["email"].validators = [INCOMPLETE_EMAIL_VALIDATOR]

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if email == (self.target.email or "").lower():
            raise forms.ValidationError(
                f"{email} is already this person's email address."
            )
        if email_on_file(email, exclude_user=self.target):
            raise forms.ValidationError(
                f"The email address {email} already belongs to an account."
            )
        return email

    def save(self):
        from django.db import transaction

        user = self.target
        email = self.cleaned_data["email"]
        with transaction.atomic():
            user.email = email
            user.username = email
            user.save(update_fields=["email", "username"])
            EmailAddress.objects.filter(user=user).delete()
            EmailAddress.objects.create(
                user=user, email=email, verified=True, primary=True
            )
        return user


class DeliverySettingsForm(forms.Form):
    """Agency-wide delivery accounting policy, in plain language.

    Edits SiteConfig's ``default_irrigation_efficiency`` and
    ``default_recovery_horizon``, plus the module-gated fields below. Both are
    phrased as plain questions a non-coder analyst can answer once for the whole
    agency — no internal jargon. Efficiency is SHOWN as a whole-number percent
    (75) but STORED on the model as a Decimal fraction (0.750), so this form
    converts in both directions.

    SiteConfig is a singleton; the view loads the one row and passes it in as
    ``instance``. The form never creates a second row.

    **The efficiency field belongs to ``parcels``.** It is a field's
    irrigation efficiency wherever no irrigation method is on file (``parcels.services.field_efficiency``),
    and a groundwater-only district has fields too, so it is
    shown whenever ``parcels`` runs. ``default_recovery_horizon`` stays for the
    same reason: ``accounting.services.resolve_recovery_horizon`` and
    ``rollover_allocations`` read it for any zone's unused allocation, surface or
    not.

    **There is no separate groundwater efficiency.** There is one irrigation
    efficiency per field, so ``run_calculations`` divides pumped groundwater by
    the same field efficiency the default above feeds.

    **The over-delivery treatment belongs to ``surface`` the same way.**
    ``over_delivery_treatment`` is read once per run by ``run_calculations``;
    only canal water can be over-delivered, so the field is shown and saved
    under the ``shows_surface_settings`` gate. It is ``required=False`` at the
    Django level so a caller that does not offer it (an old test, or a
    deployment with ``surface`` off) leaves the stored value exactly as it
    was. Two choices are offered; a site stored as "credited" by an older
    version is moved to "not credited" by migration.

    **The seepage choice belongs to ``surface`` the same way**, and the share
    left in the basin is shown when ``surface`` or ``recharge`` runs, because
    each of them credits water accounts with the volume less that share.

    **``diversion_report_year_rule`` belongs to ``surface`` the same way.**
    It sets how a YEAR and MONTH in the bulk diversion import file become a
    calendar month; on a deployment with no Surface
    module there is no diversion file to read, so it is shown and saved
    under exactly the same ``shows_surface_settings`` gate -- kept as its own name
    (``shows_diversion_settings``) so the template reads for what it shows,
    not why.

    **The USE-row question is asked on the import screen, not here.** It is a
    question about one uploaded file, and a reader of this page has no reason
    yet to hold the vocabulary; it renders on the import mapping step, and only when the uploaded file
    actually has USE rows in it. ``diversion_use_type_rule`` stays on
    ``SiteConfig`` as the remembered answer, written from the import screen,
    and this form does not show or save it.
    """

    efficiency_percent = forms.IntegerField(
        min_value=1,
        max_value=100,
        error_messages={
            "min_value": "Enter a percent from 1 to 100.",
            "max_value": "Enter a percent from 1 to 100.",
        },
        label="Default irrigation efficiency",
        # The sentence avoids the `recharge` module's noun, which a
        # deployment that does not run that module must not name.
        help_text="Typical: 75%. OpenH2O uses this efficiency for every field "
        "with no irrigation method on file.",
        widget=forms.NumberInput(
            attrs={"class": "form-input", "style": "width: 6rem;", "step": "1"}
        ),
    )
    # What happens to surface water in excess of ETAW. `required=False` at the Django level (see
    # the class docstring) -- a submission that omits it leaves the stored
    # treatment untouched, same convention as `identifier_host` blank meaning
    # "use the default". Plain-language radio labels are set in __init__,
    # like `recovery_horizon`'s.
    over_delivery_treatment = forms.ChoiceField(
        choices=SiteConfig.OVER_DELIVERY_TREATMENT_OFFERED,
        required=False,
        label="Surface water in excess of ETAW",
        widget=forms.RadioSelect,
    )
    # What happens to a canal's seepage. `surface` owns it, so it is shown and
    # saved under `shows_surface_settings`; required=False for the same reason
    # as the treatment above.
    canal_seepage_credit = forms.ChoiceField(
        choices=SiteConfig.CANAL_SEEPAGE_CREDIT_CHOICES,
        required=False,
        label="Canal seepage",
        widget=forms.RadioSelect,
    )
    # Shown/entered as a whole-number percent, stored as a Decimal fraction like
    # `efficiency_percent`. Read for the recharge credit (`recharge`) and the
    # seepage credit (`surface`), so the card shows when either module runs, and
    # its help text is built in __init__ to name only the modules that run.
    leave_behind_percent = forms.IntegerField(
        required=False,
        min_value=0,
        max_value=100,
        error_messages={
            "min_value": "Enter a percent from 0 to 100.",
            "max_value": "Enter a percent from 0 to 100.",
        },
        label="Share left in the basin",
        widget=forms.NumberInput(
            attrs={"class": "form-input", "style": "width: 6rem;", "step": "1"}
        ),
    )
    recovery_horizon = forms.ChoiceField(
        choices=RECOVERY_HORIZON_CHOICES,
        # Worded without "surface water": the setting applies on a deployment
        # that may have none.
        label=(
            "When a zone doesn't use its full allocation by the end of the "
            "water year:"
        ),
        widget=forms.RadioSelect,
    )
    # Choices come off SiteConfig itself so the two never drift out of step.
    # (The USE-row rule is asked on the import screen -- see the class
    # docstring.)
    diversion_report_year_rule = forms.ChoiceField(
        choices=SiteConfig.DIVERSION_REPORT_YEAR_RULE_CHOICES,
        label="Which months does a reporting year cover?",
        help_text="OpenH2O applies this rule to a diversion file that gives a year and a month but no date.",
        widget=forms.RadioSelect,
    )
    season_start_month = forms.IntegerField(
        required=False,
        min_value=1,
        max_value=12,
        error_messages={
            "min_value": "No month is numbered %(show_value)s.",
            "max_value": "No month is numbered %(show_value)s.",
        },
        label="If a reporting year is a single irrigation season, which month does the season start?",
        help_text="Enter a month number from 1 to 12.",
        widget=forms.NumberInput(
            attrs={"class": "form-input", "style": "width: 6rem;", "step": "1", "min": "1", "max": "12"}
        ),
    )

    # The one stored piece of the persistent
    # identifier scheme. Owned by `core`, so it is shown whatever modules run.
    identifier_host = forms.CharField(
        required=False,
        max_length=200,
        label="Where your record addresses are published",
        help_text="Each record's page shows its permanent address, which "
        "ends in /id/<kind>/<number>/. Leave this blank to use this "
        "site's own address. Set it before you register this site with "
        "Geoconnex, the Internet of Water's public index of water "
        "records, so that the addresses never change.",
        widget=forms.TextInput(
            attrs={"class": "form-input", "placeholder": "water.example.org"}
        ),
    )

    # Why the settings changed, saved with the change in the change history
    # (core/history.py). Optional here; not a SiteConfig field. The page shows
    # no box for it; a caller can still supply a note.
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
        # The default irrigation efficiency belongs to `parcels`,
        # which every deployment that reaches this page runs (the page is
        # `accounting`'s, and the two are an inseparable pair).
        self.shows_efficiency = is_enabled("parcels")
        # The cards only a canal district has: surface water in excess of
        # ETAW and the reporting-year rule. The efficiency card has its own gate,
        # `shows_efficiency`, above.
        self.shows_surface_settings = is_enabled("surface")
        # Same gate as the surface settings, named for what it shows.
        self.shows_diversion_settings = self.shows_surface_settings
        # The share left in the basin is read by the recharge credit and by the
        # seepage credit, so either module is a reason to show it.
        self.shows_leave_behind = is_enabled("recharge") or self.shows_surface_settings
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
                initial["canal_seepage_credit"] = instance.canal_seepage_credit
            if self.shows_leave_behind:
                initial["leave_behind_percent"] = int(
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
            del self.fields["canal_seepage_credit"]
        if not self.shows_leave_behind:
            del self.fields["leave_behind_percent"]
        else:
            self.fields["leave_behind_percent"].help_text = self._leave_behind_help()
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
            # The radio's label is the
            # choice, one line; what it does is the description the template
            # prints under it (`over_delivery_options`). No "recharge": this
            # page is served without that module.
            self.fields["over_delivery_treatment"].choices = [
                ("not_credited", "Not credited to anyone."),
                ("named_line", "Shown on the field's page as its own line."),
            ]
            self.fields["canal_seepage_credit"].choices = [
                ("none", "Credited to no one."),
                ("by_acre", "Shared by acre among the fields the canal serves, less the share left in the basin."),
                ("owner", "Credited to the canal's owner only, less the share left in the basin."),
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

        The Delivery Settings card prints each choice as a label line
        with what it does on a quieter line under it, so the three radios
        line up instead of wrapping to three different lengths. The
        descriptions live here, beside the labels, and not in the template,
        so the words that describe a choice sit with the choice. Empty when
        the field is not shown (no ``surface`` module).
        """
        if not self.shows_surface_settings:
            return []
        descriptions = {
            "not_credited": (
                "Nothing else happens to the amount. This is the default."
            ),
            "named_line": (
                "OpenH2O neither credits nor charges the amount. The field's "
                "water balance is the same under both choices."
            ),
        }
        return [
            (radio, descriptions[radio.data["value"]])
            for radio in self["over_delivery_treatment"]
        ]

    def _leave_behind_help(self):
        """The share's help text, naming only the credits this deployment has."""
        from core.modules import is_enabled

        sources = []
        if is_enabled("recharge"):
            sources.append("a recharge event's water")
        if self.shows_surface_settings:
            sources.append("canal seepage")
        return (
            f"Typical: 10%. When OpenH2O credits {' and '.join(sources)} to a "
            "water account, it leaves this share in the basin and credits the "
            "rest. A changed share applies to credits written after the change."
        )

    @property
    def canal_seepage_options(self):
        """``(radio, description)`` per seepage choice, in the choices' own order."""
        if not self.shows_surface_settings:
            return []
        descriptions = {
            "none": (
                "OpenH2O records the seepage in the basin's water budget and "
                "credits it to no water account. This is the default."
            ),
            "by_acre": (
                "Each served field's water account is credited its share of the "
                "seepage by acre. A field that is not in a water account is "
                "skipped, and its part is credited to no one."
            ),
            "owner": (
                "The water account named as owner on the canal's headgate is "
                "credited. A headgate with no owner named credits no one."
            ),
        }
        return [
            (radio, descriptions[radio.data["value"]])
            for radio in self["canal_seepage_credit"]
        ]

    def clean_identifier_host(self):
        from core.identifiers import normalize_host

        value = normalize_host(self.cleaned_data.get("identifier_host"))
        if any(ch.isspace() for ch in value):
            raise forms.ValidationError(
                "Enter a host name such as water.example.org, with no spaces."
            )
        return value

    def clean_leave_behind_percent(self):
        percent = self.cleaned_data.get("leave_behind_percent")
        if percent is None:
            return None
        return (Decimal(percent) / Decimal("100")).quantize(Decimal("0.001"))

    def clean_efficiency_percent(self):
        percent = self.cleaned_data["efficiency_percent"]
        # Percent (75) -> Decimal fraction (0.750), the stored convention.
        try:
            return (Decimal(percent) / Decimal("100")).quantize(Decimal("0.001"))
        except InvalidOperation:
            raise forms.ValidationError("Enter a whole number between 1 and 100.")

    def clean(self):
        cleaned = super().clean()
        if self.shows_diversion_settings:
            # A season with no starting month would fail every row of a
            # Water Use Reported file.
            if (
                cleaned.get("diversion_report_year_rule") == "season"
                and not cleaned.get("season_start_month")
                and "season_start_month" not in self.errors
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
            # A submission that omits the treatment (nobody was offered it,
            # e.g. a caller that does not send the field) leaves the stored
            # value exactly as it was.
            treatment = self.cleaned_data.get("over_delivery_treatment")
            if treatment:
                config.over_delivery_treatment = treatment
                updated.append("over_delivery_treatment")
            seepage = self.cleaned_data.get("canal_seepage_credit")
            if seepage:
                config.canal_seepage_credit = seepage
                updated.append("canal_seepage_credit")
        if self.shows_leave_behind:
            leave_behind = self.cleaned_data.get("leave_behind_percent")
            if leave_behind is not None:
                config.over_delivery_leave_behind = leave_behind
                updated.append("over_delivery_leave_behind")
        if self.shows_diversion_settings:
            config.diversion_report_year_rule = self.cleaned_data["diversion_report_year_rule"]
            config.season_start_month = self.cleaned_data.get("season_start_month")
            updated.extend([
                "diversion_report_year_rule", "season_start_month",
            ])
        config.save(update_fields=updated)
        return config
