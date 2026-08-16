import asyncio
import json
import logging

from .exceptions import HttpError

logger = logging.getLogger(__name__)

# Retry configuration
RETRY_STATUS_CODES = {429, 500, 502, 503, 504}
MAX_RETRIES = 3
INITIAL_BACKOFF = 1.0  # seconds
# A rate limiter states how long to wait; guessing shorter guarantees the retry fails.
MAX_RETRY_AFTER = 60.0
RETRY_INFO_TYPE = "type.googleapis.com/google.rpc.RetryInfo"


def retry_after(headers, body):
    """The delay the server asked for, or None; capped so a bad value cannot hang."""
    stated = None
    try:
        raw = headers.get("Retry-After") if headers else None
        if raw:
            stated = float(str(raw).strip())
    except (ValueError, AttributeError):
        stated = None
    if stated is None:
        stated = _google_retry_info(body)
    if stated is None:
        return None
    return max(0.0, min(stated, MAX_RETRY_AFTER))


def _google_retry_info(body):
    """Google states the delay in a typed RetryInfo detail rather than a header."""
    payload = body
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            return None
    if isinstance(payload, list):
        payload = payload[0] if payload else None
    if not isinstance(payload, dict):
        return None
    for detail in (payload.get("error") or {}).get("details") or []:
        if isinstance(detail, dict) and detail.get("@type") == RETRY_INFO_TYPE:
            delay = str(detail.get("retryDelay") or "")
            if delay.endswith("s"):
                try:
                    return float(delay[:-1])
                except ValueError:
                    return None
    return None


class HttpClient:
    async def request(self, method, url, headers=None, body=None, signal=None):
        raise NotImplementedError


def is_pyodide():
    try:
        import pyodide_js  # noqa: F401

        return True
    except ImportError:
        return False


# parse response without relying on content type
async def parse_response(response):
    text = await response.text()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


# ----------------------------


def _js_headers(response):
    """A dict-like view of fetch's Headers, or None when it cannot be read."""
    try:
        return {"Retry-After": response.headers.get("Retry-After")}
    except Exception:
        return None


class BrowserHttpClient(HttpClient):
    def __init__(self):
        from js import fetch
        from pyodide.ffi import to_js

        self._fetch = fetch
        self._to_js = to_js

    async def request(self, method, url, headers=None, body=None, signal=None):
        headers = headers or {}
        options = {
            "method": method.upper(),
            "headers": headers,
            "cache": "no-store",
        }
        if body is not None:
            options["body"] = json.dumps(body)
            headers.setdefault("Content-Type", "application/json")
        # Handed to fetch so Stop drops the request in flight.
        if signal is not None:
            options["signal"] = signal

        last_error = None
        for attempt in range(MAX_RETRIES):
            response = await self._fetch(url, self._to_js(options))
            if response.ok:
                return await parse_response(response)

            status = response.status
            text = await response.text()

            if status not in RETRY_STATUS_CODES:
                # Don't retry client errors (except 429)
                raise HttpError(
                    f"HTTP {status}: {text}",
                    status_code=status,
                    details={"url": url, "method": method},
                )

            last_error = HttpError(
                f"HTTP {status}: {text}",
                status_code=status,
                details={"url": url, "method": method},
            )

            if attempt < MAX_RETRIES - 1:
                stated = retry_after(_js_headers(response), text)
                backoff = stated if stated is not None else INITIAL_BACKOFF * (2**attempt)
                logger.warning(f"HTTP {status}, retrying in {backoff}s " f"(attempt {attempt + 1}/{MAX_RETRIES})")
                await asyncio.sleep(backoff)

        raise last_error


# ----------------------------


class ServerHttpClient(HttpClient):
    def __init__(self):
        import aiohttp

        self._aiohttp = aiohttp

    async def request(self, method, url, headers=None, body=None, signal=None):
        # A browser AbortSignal has no meaning here; the loop's own checks still apply.
        del signal
        data = None
        if body is not None:
            data = json.dumps(body)
            headers = headers or {}
            headers.setdefault("Content-Type", "application/json")

        last_error = None
        last_headers = None
        for attempt in range(MAX_RETRIES):
            async with self._aiohttp.ClientSession() as session:
                async with session.request(
                    method=method.upper(),
                    url=url,
                    headers=headers,
                    data=data,
                ) as response:
                    if response.status < 400:
                        return await parse_response(response)

                    status = response.status
                    text = await response.text()
                    last_headers = dict(response.headers)

                    if status not in RETRY_STATUS_CODES:
                        # Don't retry client errors (except 429)
                        raise HttpError(
                            f"HTTP {status}: {text}",
                            status_code=status,
                            details={"url": url, "method": method},
                        )

                    last_error = HttpError(
                        f"HTTP {status}: {text}",
                        status_code=status,
                        details={"url": url, "method": method},
                    )

            if attempt < MAX_RETRIES - 1:
                stated = retry_after(last_headers, text)
                backoff = stated if stated is not None else INITIAL_BACKOFF * (2**attempt)
                logger.warning(f"HTTP {status}, retrying in {backoff}s " f"(attempt {attempt + 1}/{MAX_RETRIES})")
                await asyncio.sleep(backoff)

        raise last_error


# ----------------------------

http: HttpClient
if is_pyodide():
    http = BrowserHttpClient()
else:
    http = ServerHttpClient()


__all__ = ["http", "HttpClient"]
