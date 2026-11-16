"""Shared access layer. Every app asks these questions here, never writes its own checks.

- Which companies may this user see?      services.allowed_companies(user)
- Which rows may this user see?           MyModel.objects.for_user(user)
- May this user open this app?            AppAccessRequiredMixin on the view
"""
