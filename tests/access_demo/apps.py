from django.apps import AppConfig


class AccessDemoConfig(AppConfig):
    """Test-only app: a tiny model to prove the access layer works. Never installed outside tests."""

    name = "tests.access_demo"
    label = "access_demo"
