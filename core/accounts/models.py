from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models
from simple_history import register
from simple_history.models import HistoricalRecords


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

    history = HistoricalRecords()

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


class CompanyRole(models.Model):
    """A user's role inside one company. Example: (Ravi, Acme, Manager) and (Ravi, Globex, Admin).

    A user sees a company only if they have at least one role in it.
    """

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="company_roles")
    company = models.ForeignKey("masters.Company", on_delete=models.CASCADE, related_name="user_roles")
    role = models.ForeignKey(Role, on_delete=models.PROTECT, related_name="company_roles")

    history = HistoricalRecords()

    class Meta:
        ordering = ["company", "role"]
        verbose_name = "company role"
        constraints = [
            models.UniqueConstraint(fields=["user", "company", "role"], name="unique_role_per_user_company")
        ]

    def __str__(self):
        return f"{self.company}: {self.role}"


# History of user changes. The password hash and last login are never stored.
register(User, excluded_fields=["password", "last_login"])
