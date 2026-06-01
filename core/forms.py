# SPDX-License-Identifier: AGPL-3.0-or-later
from allauth.account.models import EmailAddress
from django import forms
from django.contrib.auth.password_validation import validate_password

from core.models import User


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
