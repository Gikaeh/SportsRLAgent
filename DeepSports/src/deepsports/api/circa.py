"""Circa screenshot upload + today's state (docs/API.md, "Circa"). Never opens DuckDB.

The server binds 0.0.0.0, so the upload is strictly bounded: whole request <= MAX_REQUEST_BYTES
(checked while streaming), images by magic bytes only, 10 MB each, 30 per local day, server-chosen
file names. Responses never contain stakes (there are none here)."""

import contextlib

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, JSONResponse

from deepsports.api.circa_page import PAGE
from deepsports.circa import reader, storage, upload_code
from deepsports.circa.multipart import MultipartError, file_parts

MAX_REQUEST_BYTES = 60 * 1024 * 1024  # a handful of full-size screenshots per request
# POST only from this Mac: cloudflared forwards the BetDesk tunnel from localhost. LAN devices are
# refused. Tests patch this set.
ALLOWED_HOSTS = {"127.0.0.1", "::1"}
MAX_CONCURRENT = 2  # uploads being read/saved at once; more get 503
_active = 0  # only touched on the event loop


_limiter = upload_code.FailureLimiter()


def _client_host(request: Request) -> str | None:
    return request.client.host if request.client else None


def _origin_ok(request: Request) -> bool:
    """No Origin header (BetDesk's Worker sends none) or the server's own origin (the /circa page).
    A cross-site browser POST carries a foreign Origin."""
    origin = request.headers.get("origin")
    if origin is None:
        return True
    own = f"{request.url.scheme}://{request.headers.get('host', '')}"
    return origin.rstrip("/").lower() == own.lower()


# Host names a browser on this Mac uses for the server itself. A page whose own name was rebound
# to 127.0.0.1 (DNS rebinding) sends Origin == Host with its own name, so with an Origin the
# loopback path also needs one of these hosts.
LOCAL_HOSTNAMES = {"localhost", "127.0.0.1", "[::1]"}


def _local_host(request: Request) -> bool:
    host = request.headers.get("host", "").lower()
    if host.startswith("["):
        return host.split("]", 1)[0] + "]" in LOCAL_HOSTNAMES
    return host.rsplit(":", 1)[0] in LOCAL_HOSTNAMES


def upload_allowed(request: Request) -> bool:
    """The BetDesk tunnel path: a loopback client (cloudflared). With no Origin (the Worker sends
    none) that is enough; a browser on this Mac (Origin set) must also use a local host name."""
    if _client_host(request) not in ALLOWED_HOSTS or not _origin_ok(request):
        return False
    return request.headers.get("origin") is None or _local_host(request)


def check_upload(request: Request) -> JSONResponse | None:
    """None if the upload may go ahead, else the 403/429 response. Loopback (BetDesk tunnel) as
    before; a LAN client needs the X-Circa-Upload-Code header (the /circa page on home Wi-Fi). A
    custom header forces a CORS preflight, which our GET-only CORS refuses, so other websites
    can't send it. The code is never logged or echoed."""
    if upload_allowed(request):
        return None
    ip = _client_host(request) or "?"
    if _limiter.limited(ip):
        return _error(429, "too_many_attempts", "too many wrong upload codes; try again later")
    given = request.headers.get(upload_code.HEADER)
    if given and _origin_ok(request) and upload_code.matches(given):
        return None
    if given:
        _limiter.fail(ip)
    return _error(403, "forbidden", "a valid upload code is needed from this network")


def _error(status: int, code: str, detail: str) -> JSONResponse:
    return JSONResponse({"error": code, "detail": detail}, status_code=status)


STATUS_BY_CODE = {
    "file_too_large": 413,
    "unsupported_type": 415,
    "empty_file": 400,
    "daily_limit": 429,
}


def add_routes(app: FastAPI) -> None:
    @app.post("/api/circa/screenshots")
    async def upload(request: Request):
        global _active
        refused = await run_in_threadpool(check_upload, request)  # reads the code file
        if refused is not None:
            return refused
        if _active >= MAX_CONCURRENT:
            return _error(503, "busy", "another upload is in progress; try again")
        _active += 1
        try:
            return await _upload(request)
        finally:
            _active -= 1

    async def _upload(request: Request):
        declared = request.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > MAX_REQUEST_BYTES:
            return _error(413, "request_too_large", "request over 60 MB")
        body = bytearray()
        async for chunk in request.stream():
            body += chunk
            if len(body) > MAX_REQUEST_BYTES:
                return _error(413, "request_too_large", "request over 60 MB")
        try:
            images = file_parts(bytes(body), request.headers.get("content-type"), field="file")
        except MultipartError as e:
            return _error(400, "bad_request", str(e))
        if not images:
            return _error(400, "no_file", "send one or more images in form field 'file'")
        day = storage.today()
        try:
            saved = await run_in_threadpool(storage.save_images, images, day)
            count = len(await run_in_threadpool(storage.list_day, day))
        except storage.RejectedImage as e:
            return _error(STATUS_BY_CODE.get(e.code, 400), e.code, e.detail)
        except OSError:  # drive not mounted / not permitted
            return _error(503, "storage_unavailable", "screenshot storage unavailable")
        return {"date": day.isoformat(), "saved": saved, "today_count": count}

    @app.get("/circa", include_in_schema=False)
    def page():
        # make sure the code file exists, so `circa code` can show it (LAN uploads get 403 until
        # it can be created)
        with contextlib.suppress(OSError):
            upload_code.get_code()
        return HTMLResponse(PAGE, headers={"Cache-Control": "no-store"})

    @app.get("/api/circa/screenshots/today")
    def today():
        try:
            return reader.status()
        except OSError:
            return _error(503, "storage_unavailable", "screenshot storage unavailable")
