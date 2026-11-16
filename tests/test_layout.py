"""Layout, app registry and dashboard: users see only the apps their roles allow."""
import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ImproperlyConfigured

from core import registry
from core.accounts.models import CompanyRole, Role
from core.masters.models import Company, Vendor
from core.registry import AppEntry, apps_for_user, register

User = get_user_model()
PASSWORD = "a-long-password-123"


@pytest.fixture
def acme():
    return Company.objects.create(name="Acme", code="ACME")


@pytest.fixture
def travel_app():
    """A pretend "travel" app, removed again after the test."""
    entry = AppEntry(code="travel", name="Travel", icon="no-such-icon", url_name="core:home", order=20)
    register(entry)
    yield entry
    registry._entries.pop("travel", None)


def make_user(email, companies, apps=(), **extra):
    user = User.objects.create_user(email=email, password=PASSWORD, first_name="Ravi", **extra)
    role = Role.objects.create(name=f"role-{email}", allowed_apps=list(apps))
    for company in companies:
        CompanyRole.objects.create(user=user, company=company, role=role)
    return user


def sidebar(content):
    """Only the sidebar part of the page."""
    html = content.decode()
    return html[html.index('id="app-menu"') :]


@pytest.mark.django_db
def test_sidebar_shows_only_allowed_apps(client, acme, travel_app):
    client.force_login(make_user("ravi@example.com", [acme], apps=["masters"]))

    menu = sidebar(client.get("/").content)

    assert "Masters" in menu
    assert "Travel" not in menu


@pytest.mark.django_db
def test_superuser_sees_every_app(travel_app):
    boss = User.objects.create_superuser(email="boss@example.com", password=PASSWORD)

    assert [entry.code for entry in apps_for_user(boss)] == ["masters", "travel"]


@pytest.mark.django_db
def test_user_without_roles_sees_no_apps_and_a_hint(client, acme, travel_app):
    client.force_login(make_user("new@example.com", [acme]))

    response = client.get("/")

    assert apps_for_user(response.wsgi_request.user) == []
    assert b"Ask your admin to give you a role" in response.content


@pytest.mark.django_db
def test_apps_come_in_order(acme, travel_app):
    user = make_user("ravi@example.com", [acme], apps=["travel", "masters"])

    assert [entry.code for entry in apps_for_user(user)] == ["masters", "travel"]


@pytest.mark.django_db
def test_dashboard_widget_counts_only_own_company_rows(client, acme):
    globex = Company.objects.create(name="Globex", code="GLOBEX")
    Vendor.objects.create(company=acme, name="Steel Co")
    Vendor.objects.create(company=globex, name="Secret Vendor")
    Vendor.objects.create(company=globex, name="Another Secret")
    client.force_login(make_user("ravi@example.com", [acme], apps=["masters"]))

    cards = client.get("/").context["cards"]

    counts = {item["title"]: item["count"] for item in cards[0]["data"]["counts"]}
    assert counts["Vendors"] == 1
    assert counts["Companies"] == 1


@pytest.mark.django_db
def test_broken_widget_shows_a_note_not_an_error_page(client, acme):
    def broken(user):
        raise RuntimeError("database is down")

    register(AppEntry(code="travel", name="Travel", icon="apps", url_name="core:home",
                      widget_template="masters/widget.html", widget_data=broken))
    try:
        client.force_login(make_user("ravi@example.com", [acme], apps=["travel"]))
        response = client.get("/")
    finally:
        registry._entries.pop("travel", None)

    assert response.status_code == 200
    assert b"This summary could not be loaded" in response.content


def test_same_app_code_cannot_be_registered_twice(travel_app):
    with pytest.raises(ImproperlyConfigured):
        register(AppEntry(code="travel", name="Other travel", icon="apps", url_name="core:home"))


@pytest.mark.django_db
def test_masters_link_is_highlighted_on_masters_pages(client, acme):
    client.force_login(make_user("ravi@example.com", [acme], apps=["masters"]))

    menu = sidebar(client.get("/masters/vendors/").content)

    assert 'href="/masters/companies/" class="menu-active"' in menu


@pytest.mark.django_db
def test_admin_link_only_for_staff(client, acme):
    client.force_login(make_user("ravi@example.com", [acme], apps=["masters"]))
    assert b'href="/admin/"' not in client.get("/").content

    client.force_login(make_user("staff@example.com", [acme], apps=["masters"], is_staff=True))
    assert b'href="/admin/"' in client.get("/").content
