"""HTTPS-only device transport; never redirects bearer tokens to another endpoint."""

import json
import ssl
import urllib.error
import urllib.parse
import urllib.request

from .build_profile import ENGINEERING, OFFLINE_ORIGIN, current, require_network


class RetryableError(ConnectionError):
    def __init__(self, code, retry_after=0):
        super().__init__(code)
        self.retry_after = retry_after


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Api:
    def __init__(self, base, token):
        if current() == ENGINEERING and base.rstrip("/") != OFFLINE_ORIGIN:
            raise ValueError("ENGINEERING_OFFLINE_ORIGIN_REQUIRED")
        url = urllib.parse.urlsplit(base)
        if (
            url.scheme != "https"
            or not url.hostname
            or url.username
            or url.password
            or url.query
            or url.fragment
            or url.path not in ("", "/")
        ):
            raise ValueError("HTTPS origin required, without credentials/path/query")
        self.base, self.token = base.rstrip("/"), token
        # Standard certificate and hostname verification. No custom CA or verify=False option.
        self.opener = urllib.request.build_opener(NoRedirect())

    def allowed_path(self, path):
        return path in ("/api/v1/mt5/collector/control", "/api/v1/mt5/collector/batches")

    def call(self, path, payload=None):
        require_network()
        if not self.allowed_path(path):
            raise ValueError("Collector path not allowed")
        request = urllib.request.Request(  # noqa: S310 - validated HTTPS origin + fixed paths
            self.base + path,
            data=json.dumps(payload).encode() if payload is not None else None,
            headers={"Authorization": "Bearer " + self.token, "Content-Type": "application/json"},
            method="POST" if payload is not None else "GET",
        )
        try:
            with self.opener.open(request, timeout=30) as response:
                return json.loads(response.read(2_000_000))
        except urllib.error.HTTPError as exc:
            if exc.code != 429 and exc.code < 500:
                raise RuntimeError("SYNC_PAUSED_HTTP_" + str(exc.code)) from None
            # Do not log URLs, response bodies or credentials. Retry same durable payload.
            delay = exc.headers.get("Retry-After", "0") if exc.headers else "0"
            delay = min(int(delay), 86400) if delay.isdecimal() else 0
            raise RetryableError("RETRY_HTTP_" + str(exc.code), delay) from None
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, ssl.SSLError):
                raise RuntimeError("TLS_VALIDATION_FAILED") from None
            raise RetryableError("NETWORK_UNAVAILABLE") from None
        except ssl.SSLError:
            raise RuntimeError("TLS_VALIDATION_FAILED") from None
        except (TimeoutError, OSError):
            raise ConnectionError("NETWORK_OR_TLS_UNAVAILABLE") from None
