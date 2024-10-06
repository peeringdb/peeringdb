from django.conf import settings
from django.core.cache import caches
from django.utils.log import AdminEmailHandler


class ThrottledAdminEmailHandler(AdminEmailHandler):
    """
    Throttled admin email handler
    """

    CACHE_KEY = "THROTTLE_ERROR_EMAILS"

    @property
    def cache(self):
        """
        returns the specific cache handler set up for this purpose
        """
        return caches["error_emails"]

    def increment_counter(self):
        try:
            self.cache.incr(self.CACHE_KEY)
        except ValueError:
            self.cache.set(self.CACHE_KEY, 1, settings.ERROR_EMAILS_PERIOD)
        return self.cache.get(self.CACHE_KEY)

    def emit(self, record):
        try:
            counter = self.increment_counter()
        except Exception:
            pass
        else:
            if counter > settings.ERROR_EMAILS_LIMIT:
                return
        super().emit(record)
