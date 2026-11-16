from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models


class Role(models.Model):
    """What a group of users may do. Example: "Finance clerk" may open ["finance"], own records only."""

    name = models.CharField(max_length=100, unique=True)
    allowed_apps = models.JSONField(
        default=list,
        blank=True,
        help_text='App codes this role may open, e.g. ["tasks", "travel"].',
    )
    own_records_only = models.BooleanField(
        default=False, help_text="Users see only records they created."
    )
    requires_2fa = models.BooleanField(
        default=False, help_text="Users must use an authenticator app code at login."
    )

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class UserManager(BaseUserManager):
    """Users log in with email. Email is stored lower-case so 'Ravi@X.com' and 'ravi@x.com' match."""

    use_in_migrations = True

    def _create_user(self, email, password, **extra_fields):
        if not email:
            raise ValueError("Email address is required.")
        user = self.model(email=self.normalize_email(email).lower(), **extra_fields)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields["is_staff"] = True
        extra_fields["is_superuser"] = True
        return self._create_user(email, password, **extra_fields)

    def get_by_natural_key(self, username):
        return self.get(email__iexact=username)


class User(AbstractUser):
    """One user table for staff and external users. Login is by email; there is no username."""

    username = None
    first_name = models.CharField(max_length=150)
    email = models.EmailField("email address", unique=True)
    is_external = models.BooleanField(
        default=False, help_text="Outside user (vendor, consultant). Never gets the admin site."
    )
    companies = models.ManyToManyField(
        "masters.Company", blank=True, related_name="users", help_text="Companies this user can see."
    )
    roles = models.ManyToManyField(Role, blank=True, related_name="users")

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["first_name"]

    objects = UserManager()

    class Meta:
        ordering = ["email"]

    def __str__(self):
        return self.get_full_name() or self.email

    def save(self, *args, **kwargs):
        self.email = self.email.lower()
        super().save(*args, **kwargs)
