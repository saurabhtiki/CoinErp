"""Who can see what. Uses the test-only Note model in tests/access_demo."""
import pytest
from django.contrib.auth import get_user_model

from core.access import services
from core.accounts.models import Role
from core.masters.models import Company
from tests.access_demo.models import Note

User = get_user_model()
APP = "access_demo"


@pytest.fixture
def acme():
    return Company.objects.create(name="Acme", code="ACME")


@pytest.fixture
def globex():
    return Company.objects.create(name="Globex", code="GLOBEX")


def make_user(email, companies=(), own_records_only=False, apps=(APP,), **extra):
    user = User.objects.create_user(email=email, password="a-long-password-123", first_name="X", **extra)
    user.companies.set(companies)
    if apps:
        user.roles.add(Role.objects.create(name=f"role-{email}", allowed_apps=list(apps), own_records_only=own_records_only))
    return user


def note(company, title, created_by=None):
    return Note.objects.create(company=company, title=title, created_by=created_by)


# --- Company rule -----------------------------------------------------------------


@pytest.mark.django_db
def test_user_of_company_a_cannot_see_company_b_rows(acme, globex):
    ravi = make_user("ravi@example.com", [acme])
    note(acme, "acme note")
    note(globex, "globex note")

    titles = list(Note.objects.for_user(ravi).values_list("title", flat=True))

    assert titles == ["acme note"]


@pytest.mark.django_db
def test_user_with_two_companies_sees_both(acme, globex):
    ravi = make_user("ravi@example.com", [acme, globex])
    note(acme, "a")
    note(globex, "b")

    assert Note.objects.for_user(ravi).count() == 2


@pytest.mark.django_db
def test_user_with_no_company_sees_nothing(acme):
    ravi = make_user("ravi@example.com", [])
    note(acme, "a")

    assert Note.objects.for_user(ravi).count() == 0


@pytest.mark.django_db
def test_superuser_sees_all_companies(acme, globex):
    boss = User.objects.create_superuser(email="boss@example.com", password="a-long-password-123", first_name="B")
    note(acme, "a")
    note(globex, "b")

    assert Note.objects.for_user(boss).count() == 2
    assert set(services.allowed_companies(boss)) == {acme, globex}


@pytest.mark.django_db
def test_inactive_or_anonymous_user_sees_nothing(acme):
    from django.contrib.auth.models import AnonymousUser

    ravi = make_user("ravi@example.com", [acme], is_active=False)
    note(acme, "a")

    assert Note.objects.for_user(ravi).count() == 0
    assert Note.objects.for_user(AnonymousUser()).count() == 0


@pytest.mark.django_db
def test_external_user_sees_only_assigned_company(acme, globex):
    vendor = make_user("vendor@example.com", [globex], is_external=True)
    note(acme, "a")
    note(globex, "b")

    assert list(Note.objects.for_user(vendor).values_list("title", flat=True)) == ["b"]


@pytest.mark.django_db
def test_allowed_companies_lists_only_assigned(acme, globex):
    ravi = make_user("ravi@example.com", [acme])

    assert list(services.allowed_companies(ravi)) == [acme]


# --- Own records rule -------------------------------------------------------------


@pytest.mark.django_db
def test_own_records_user_sees_only_own_rows(acme):
    ravi = make_user("ravi@example.com", [acme], own_records_only=True)
    sita = make_user("sita@example.com", [acme])
    note(acme, "ravi's", created_by=ravi)
    note(acme, "sita's", created_by=sita)

    assert list(Note.objects.for_user(ravi).values_list("title", flat=True)) == ["ravi's"]
    assert Note.objects.for_user(sita).count() == 2


@pytest.mark.django_db
def test_own_records_still_limited_to_company(acme, globex):
    ravi = make_user("ravi@example.com", [acme], own_records_only=True)
    note(globex, "own but other company", created_by=ravi)

    assert Note.objects.for_user(ravi).count() == 0


@pytest.mark.django_db
def test_wider_role_for_same_app_wins_over_own_records_role(acme):
    ravi = make_user("ravi@example.com", [acme], own_records_only=True)
    ravi.roles.add(Role.objects.create(name="Manager", allowed_apps=[APP]))
    note(acme, "someone else's")

    assert Note.objects.for_user(ravi).count() == 1


@pytest.mark.django_db
def test_own_records_role_for_other_app_does_not_limit_this_app(acme):
    ravi = make_user("ravi@example.com", [acme])
    ravi.roles.add(Role.objects.create(name="Travel clerk", allowed_apps=["travel"], own_records_only=True))
    note(acme, "someone else's")

    assert Note.objects.for_user(ravi).count() == 1


# --- App rule (views) -------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.urls("tests.access_demo.urls")
def test_role_with_app_can_open_it(client, acme):
    client.force_login(make_user("ravi@example.com", [acme]))

    assert client.get("/notes/").status_code == 200


@pytest.mark.django_db
@pytest.mark.urls("tests.access_demo.urls")
def test_role_without_app_gets_403(client, acme):
    client.force_login(make_user("ravi@example.com", [acme], apps=["travel"]))

    assert client.get("/notes/").status_code == 403


@pytest.mark.django_db
@pytest.mark.urls("tests.access_demo.urls")
def test_user_without_any_role_gets_403(client, acme):
    client.force_login(make_user("ravi@example.com", [acme], apps=()))

    assert client.get("/notes/").status_code == 403


@pytest.mark.django_db
@pytest.mark.urls("tests.access_demo.urls")
def test_logged_out_user_goes_to_login(client):
    response = client.get("/notes/")

    assert response.status_code == 302
    assert response.url.startswith("/accounts/login/")


@pytest.mark.django_db
@pytest.mark.urls("tests.access_demo.urls")
def test_other_company_row_gives_404_not_403(client, acme, globex):
    client.force_login(make_user("ravi@example.com", [acme]))
    mine = note(acme, "mine")
    theirs = note(globex, "theirs")

    assert client.get(f"/notes/{mine.pk}/").status_code == 200
    assert client.get(f"/notes/{theirs.pk}/").status_code == 404


def test_view_without_app_code_fails_loudly(rf):
    from core.access.mixins import AppAccessRequiredMixin

    class BrokenView(AppAccessRequiredMixin):
        pass

    view = BrokenView()
    view.request = rf.get("/")
    view.request.user = type("U", (), {"is_authenticated": True, "is_active": True})()

    with pytest.raises(ValueError, match="must set app_code"):
        view.test_func()
