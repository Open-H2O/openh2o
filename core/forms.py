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
    """

    efficiency_percent = forms.IntegerField(
        min_value=1,
        max_value=100,
        label="Share of delivered water the crop actually consumes",
        help_text="The rest soaks back into the aquifer as recharge. Typical: 75%.",
        widget=forms.NumberInput(
            attrs={"class": "form-input", "style": "width: 6rem;", "step": "1"}
        ),
    )
    recovery_horizon = forms.ChoiceField(
        choices=RECOVERY_HORIZON_CHOICES,
        label=(
            "When a district doesn't use its full surface-water allotment by the "
            "end of the water year:"
        ),
        widget=forms.RadioSelect,
    )

    def __init__(self, *args, instance=None, **kwargs):
        self.instance = instance
        if instance is not None and "initial" not in kwargs:
            kwargs["initial"] = {
                # 0.750 (fraction) -> 75 (percent), rounded to a whole number.
                "efficiency_percent": int(
                    (instance.default_irrigation_efficiency * 100).to_integral_value()
                ),
                "recovery_horizon": instance.default_recovery_horizon,
            }
        super().__init__(*args, **kwargs)
        # Plain-language radio labels — these are what the manager reads, NOT the
        # model's choice labels. Option order matches RECOVERY_HORIZON_CHOICES.
        self.fields["recovery_horizon"].choices = [
            ("carry_forward", "Carry it forward as a credit toward next year"),
            ("same_water_year", "Let it expire (use-it-or-lose-it)"),
        ]

    def clean_efficiency_percent(self):
        percent = self.cleaned_data["efficiency_percent"]
        # Percent (75) -> Decimal fraction (0.750), the stored convention.
        try:
            return (Decimal(percent) / Decimal("100")).quantize(Decimal("0.001"))
        except InvalidOperation:
            raise forms.ValidationError("Enter a whole number between 1 and 100.")

    def save(self):
        """Write the two fields back onto the singleton SiteConfig instance."""
        config = self.instance
        config.default_irrigation_efficiency = self.cleaned_data["efficiency_percent"]
        config.default_recovery_horizon = self.cleaned_data["recovery_horizon"]
        config.save(
            update_fields=[
                "default_irrigation_efficiency",
                "default_recovery_horizon",
            ]
        )
        return config
