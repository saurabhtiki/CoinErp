from django.utils.functional import SimpleLazyObject

from .services import unread_count


def unread_notifications(request):
    """`unread_notifications`: text on the bell ("", "3" or "9+"). Counted only if a page shows the bell."""

    def badge():
        count = unread_count(request.user)
        return "" if not count else ("9+" if count > 9 else str(count))

    return {"unread_notifications": SimpleLazyObject(badge)}
