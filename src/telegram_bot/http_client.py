"""Shared HTTP client utilities (httpx + tenacity).

Provides a small synchronous API that replaces the project's prior `requests`
usage, with retry/backoff behavior and per-thread connection pooling.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any, Mapping

import httpx
from tenacity import RetryCallState, RetryError, Retrying, retry_if_exception, stop_after_attempt, wait_exponential_jitter

from .project_logger import get_logger

_thread_local = threading.local()

DEFAULT_TIMEOUT = httpx.Timeout(30.0, connect=10.0)
DEFAULT_MAX_ATTEMPTS = 3


def _get_client() -> httpx.Client:
    client: httpx.Client | None = getattr(_thread_local, "client", None)
    if client is None or client.is_closed:
        client = httpx.Client(timeout=DEFAULT_TIMEOUT, follow_redirects=True)
        _thread_local.client = client
    return client


def _is_retryable_http_status(status_code: int) -> bool:
    return status_code == 429 or 500 <= status_code <= 599


def _should_retry(retry_state: RetryCallState) -> bool:
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    if isinstance(exc, (httpx.TimeoutException, httpx.TransportError)):
        return True
    
    
    return _is_retryable_http_status(retry_state.outcome.result().status_code) if retry_state.outcome else False


def _log_before_sleep(retry_state: RetryCallState) -> None:
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    if exc is None:
        return
    logger = get_logger()
    delay = getattr(retry_state.next_action, "sleep", None)
    attempt = retry_state.attempt_number
    logger.info(f"http retry: attempt={attempt} sleep={delay}s error={exc!r}")


def request(
    method: str,
    url: str,
    *,
    params: Mapping[str, Any] | None = None,
    headers: Mapping[str, str] | None = None,
    json: Any | None = None,
    data: Any | None = None,
    content: bytes | str | None = None,
    timeout: httpx.Timeout | float | None = None,
    follow_redirects: bool = True,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
) -> httpx.Response:
    def _do_request() -> httpx.Response:
        client = _get_client()
        resp = client.request(
            method=method,
            url=url,
            params=params,
            headers=headers,
            json=json,
            data=data,
            content=content,
            timeout=timeout,
            follow_redirects=follow_redirects,
        )
        return resp

    retrying = Retrying(
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential_jitter(initial=0.5, max=8.0),
        retry=_should_retry,
        reraise=True,
        before_sleep=_log_before_sleep,
    )
    return retrying(_do_request)


def get(
    url: str,
    *,
    params: Mapping[str, Any] | None = None,
    headers: Mapping[str, str] | None = None,
    timeout: httpx.Timeout | float | None = None,
    follow_redirects: bool = True,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
) -> httpx.Response:
    try:
        response = request(
            "GET",
            url,
            params=params,
            headers=headers,
            timeout=timeout,
            follow_redirects=follow_redirects,
            max_attempts=max_attempts,
        )
    except RetryError as e:
        logger = get_logger()
        logger.error(f"GET request to {url} failed after {max_attempts} attempts: {e}")
        return e.last_attempt.result()
    return response


def post(
    url: str,
    *,
    params: Mapping[str, Any] | None = None,
    headers: Mapping[str, str] | None = None,
    json: Any | None = None,
    data: Any | None = None,
    content: bytes | str | None = None,
    timeout: httpx.Timeout | float | None = None,
    follow_redirects: bool = True,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
) -> httpx.Response:
    try:
        response = request(
            "POST",
            url,
            params=params,
            headers=headers,
            json=json,
            data=data,
            content=content,
            timeout=timeout,
            follow_redirects=follow_redirects,
            max_attempts=max_attempts,
        )
    except RetryError as e:
        logger = get_logger()
        logger.error(f"POST request to {url} failed after {max_attempts} attempts: {e}")
        return e.last_attempt.result()
    return response


def download_file(
    url: str,
    file_path: str | os.PathLike[str],
    *,
    headers: Mapping[str, str] | None = None,
    timeout: httpx.Timeout | float | None = None,
    follow_redirects: bool = True,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
) -> Path:
    destination = Path(file_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_path = destination.with_suffix(destination.suffix + ".part")

    def _do_stream() -> Path:
        client = _get_client()
        try:
            with client.stream(
                "GET",
                url,
                headers=headers,
                timeout=timeout,
                follow_redirects=follow_redirects,
            ) as resp:
                resp.raise_for_status()
                with temp_path.open("wb") as f:
                    for chunk in resp.iter_bytes():
                        f.write(chunk)
            temp_path.replace(destination)
            return destination
        finally:
            try:
                if temp_path.exists():
                    temp_path.unlink()
            except Exception:
                pass

    retrying = Retrying(
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential_jitter(initial=0.5, max=8.0),
        retry=retry_if_exception(_should_retry),
        reraise=True,
        before_sleep=_log_before_sleep,
    )
    return retrying(_do_stream)
