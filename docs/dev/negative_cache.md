## Developer Documentation on Negative Caching in PeeringDB

### Overview

Negative caching provides a way to remember previously seen HTTP error codes (e.g., 401, 403, 429) and cache these responses. This minimizes the need to constantly re-evaluate requests that we expect will return the same error codes. This document provides developers with information about the negative caching system implemented in PeeringDB using Redis.

### Development Considerations

When working with the negative caching system, developers should be aware of the following:

1. **Testing Repeated Responses**: If you are writing tests or manually testing repeated requests that initially return HTTP error codes like 401, 403, or 429, remember that the response might be cached by the negative caching system. To get accurate and consistent test results:
   - You may need to manually clear the negative cache before retrying the request.
   - Do not assume that just because you received an error once, subsequent requests within the cache duration will re-evaluate permissions or rate limits.
   - When in doubt, turn `NEGATIVE_CACHE_ENABLED` off during initial implementation / testing

### Negative Cache Settings

Below are the default settings for the negative caching system. Each setting controls how long a specific error code is cached:

- **401 - Unauthorized**: Cached for 1 minute.
  ```python
  set_option("NEGATIVE_CACHE_EXPIRY_401", 60)
  ```

- **403 - Forbidden**: Cached for 10 seconds. This is typically due to permission check failures. It's essential to keep this cache duration short, espe ially since some permission checks on write requests (POST, PUT) might require checking the payload to determine the right permissions.
  ```python
  set_option("NEGATIVE_CACHE_EXPIRY_403", 10)
  ```

- **429 - Too Many Requests**: Cached for 10 seconds. This setting should remain low to avoid interference with the existing REST API rate limiting. If this cache is too long, it can obscure the accurate rate limit reset time that's already in place.
  ```python
  set_option("NEGATIVE_CACHE_EXPIRY_429", 10)
  ```

- **Inactive Users and Keys**: Cached for 1 hour. This helps in reducing checks for users or API keys that have been marked as inactive.
  ```python
  set_option("NEGATIVE_CACHE_EXPIRY_INACTIVE_AUTH", 3600)
  ```

- **Global Negative Cache Switch**: Controls whether negative caching is globally enabled or disabled.
  ```python
  set_option("NEGATIVE_CACHE_ENABLED", True)
  ```

### Adjusting Settings

When making changes to the settings above:

1. Ensure you understand the implications of the change.
2. Test any changes in a development or staging environment before applying to production to avoid unintended behaviors.
3. Monitor the application and Redis performance after changes, as caching can affect resource utilization.

### Clearing the cache manually

```python
from django.core.cache import cache
...
cache.clear()
```
