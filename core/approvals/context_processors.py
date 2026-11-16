from django.utils.functional import SimpleLazyObject


def waiting_approvals(request):
    """`waiting_approvals`: how many records wait for this user's approval (sidebar badge)."""

    def count():
        if not request.user.is_authenticated:
            return 0
        from .services import waiting_for

        return waiting_for(request.user).count()

    return {"waiting_approvals": SimpleLazyObject(count)}
