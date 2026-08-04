"""Receiver of the push notifications of a Volumio host.

:copyright: Copyright (C) 2025-2026 Alberto Pettarin
:license: GNU General Public License v3.0 (see the LICENSE file for details)
"""

import json
import socket
import threading
import time
from collections.abc import Iterator
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from queue import Empty, Queue
from types import TracebackType
from typing import Self

from volumito.clients.errors import VolumioConnectionError
from volumito.clients.host_configuration import VolumioHostConfiguration
from volumito.clients.models import PushNotification

DEFAULT_BIND_ADDRESS = "0.0.0.0"
"""Address the listener binds to by default: any interface, since the host must reach it."""

DEFAULT_ENDPOINT = "/volumionotifications"
"""Path the listener serves by default."""

DEFAULT_PORT = 3003
"""Port the listener binds to by default."""

SHUTDOWN_POLL_INTERVAL = 0.05
"""Seconds between the checks the serving loop makes for a shutdown request."""


class _NotificationHandler(BaseHTTPRequestHandler):
    """Handler answering the notification requests of a Volumio host.

    The endpoint served and the queue the notifications are delivered to are attributes
    of the server instance, set by :class:`NotificationListener`. Only POST is served;
    a GET is refused with a 405, and the other methods with the 501 of the stdlib.
    """

    server: "_NotificationServer"

    def do_GET(self) -> None:  # noqa: N802
        """Refuse a read of the endpoint, which only accepts the pushed notifications."""
        self.send_error(HTTPStatus.METHOD_NOT_ALLOWED)

    def do_POST(self) -> None:  # noqa: N802
        """Deliver the posted notification, or reject the request."""
        if self.path != self.server.endpoint:
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length > 0 else b""

        try:
            payload = json.loads(body)
        except ValueError:
            self.send_error(HTTPStatus.BAD_REQUEST, "Expected a JSON body")
            return

        if not isinstance(payload, dict):
            self.send_error(HTTPStatus.BAD_REQUEST, "Expected a JSON object")
            return

        self.server.notifications.put(PushNotification.from_raw(payload))

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        """Silence the request log the stdlib writes to stderr."""

    def send_error(
        self,
        code: int,
        message: str | None = None,
        explain: str | None = None,
    ) -> None:
        """Answer an error without the stdlib HTML body, which no host reads."""
        self.send_response(code, message)
        self.send_header("Content-Length", "0")
        self.end_headers()


class _NotificationServer(ThreadingHTTPServer):
    """The threading HTTP server carrying the endpoint and the delivery queue."""

    daemon_threads = True

    def __init__(
        self,
        server_address: tuple[str, int],
        endpoint: str,
        notifications: "Queue[PushNotification]",
    ) -> None:
        """Initialize the server.

        Args:
            server_address: The (address, port) pair to bind to
            endpoint: The path the notifications are expected on
            notifications: The queue the received notifications are delivered to
        """
        self.endpoint = endpoint
        self.notifications = notifications
        super().__init__(server_address, _NotificationHandler)


class NotificationListener:
    """A local HTTP server receiving the push notifications of a Volumio host.

    The listener is a context manager serving its endpoint while the context is open,
    and yielding the notifications as they arrive::

        with NotificationListener(port=3003, endpoint="/volumionotifications") as listener:
            for notification in listener:
                print(notification.item, notification.data)

    The URL to register on the Volumio host, so that it pushes to this listener, is
    given by :func:`receiver_url`.
    """

    def __init__(
        self,
        port: int = DEFAULT_PORT,
        endpoint: str = DEFAULT_ENDPOINT,
        bind_address: str = DEFAULT_BIND_ADDRESS,
    ) -> None:
        """Initialize the listener, without binding anything yet.

        Args:
            port: The port to listen on, or 0 to let the system choose one
            endpoint: The path the notifications are expected on
            bind_address: The address to bind to (any interface by default)
        """
        self.bind_address = bind_address
        self.endpoint = endpoint
        self.notifications: Queue[PushNotification] = Queue()
        self._port = port
        self._server: _NotificationServer | None = None
        self._thread: threading.Thread | None = None

    def __enter__(self) -> Self:
        """Start serving, and return the listener."""
        self.start()
        return self

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Stop serving."""
        self.stop()

    def __iter__(self) -> Iterator[PushNotification]:
        """Iterate over the notifications as they arrive, until interrupted."""
        return self.listen()

    @property
    def port(self) -> int:
        """The port being listened on, resolved once the listener is started."""
        if self._server is None:
            return self._port
        return int(self._server.server_address[1])

    def listen(
        self,
        count: int | None = None,
        timeout: float | None = None,
        idle_timeout: float | None = None,
    ) -> Iterator[PushNotification]:
        """Yield the received notifications, until a limit is reached.

        Args:
            count: Number of notifications to yield before returning, or None for no limit
            timeout: Seconds to listen for in total, or None for no limit
            idle_timeout: Seconds to wait for each notification, or None for no limit

        Yields:
            Each notification received, in arrival order

        Raises:
            RuntimeError: If the listener is not serving
        """
        if self._server is None:
            raise RuntimeError("The notification listener is not serving")

        deadline = None if timeout is None else time.monotonic() + timeout
        yielded = 0

        while count is None or yielded < count:
            wait = idle_timeout
            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return
                wait = remaining if wait is None else min(wait, remaining)

            try:
                notification = self.notifications.get(timeout=wait)
            except Empty:
                return

            yield notification
            yielded += 1

    def start(self) -> None:
        """Bind the endpoint and start serving in the background.

        Raises:
            OSError: If the address and port cannot be bound
        """
        if self._server is not None:
            return
        self._server = _NotificationServer(
            (self.bind_address, self._port), self.endpoint, self.notifications
        )
        self._thread = threading.Thread(
            target=self._server.serve_forever, args=(SHUTDOWN_POLL_INTERVAL,), daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop serving and release the port."""
        if self._server is None:
            return
        self._server.shutdown()
        self._server.server_close()
        if self._thread is not None:
            self._thread.join()
        self._server = None
        self._thread = None


def receiver_url(
    host_configuration: VolumioHostConfiguration,
    port: int = DEFAULT_PORT,
    endpoint: str = DEFAULT_ENDPOINT,
) -> str:
    """Return the URL a Volumio host should push its notifications to.

    The local address is the one routing to the Volumio host: a datagram socket is
    connected to it, which selects the outgoing interface without sending anything,
    and the local end of that socket is read.

    Args:
        host_configuration: The host configuration of the Volumio instance
        port: The port the listener listens on
        endpoint: The path the listener serves

    Returns:
        The URL of the local listener, as reachable by the Volumio host

    Raises:
        VolumioConnectionError: If no local address routing to the host can be found
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect((host_configuration.host, host_configuration.rest_api_port))
            address = probe.getsockname()[0]
    except OSError as e:
        raise VolumioConnectionError(
            f"Failed to find the local address reaching the Volumio instance at "
            f"{host_configuration.host}: {e}"
        ) from e

    return f"http://{address}:{port}{endpoint}"
