"""WebSocket API client for Volumio.

The client wraps a Socket.IO connection to a Volumio host. A Volumio host acknowledges
nothing, so a read emits its event and waits for the ``push*`` event carrying the answer;
the reads are serialized, since two of them in flight at once could take each other's
answer. Everything the host pushes on its own -- a playback state on every change above
all -- reaches the handlers registered with :meth:`VolumioWebSocketClient.on`.

:copyright: Copyright (C) 2025-2026 Alberto Pettarin
:license: GNU General Public License v3.0 (see the LICENSE file for details)
"""

import logging
import threading
import uuid
from collections.abc import Callable
from types import ModuleType, TracebackType
from typing import Any, Self, cast

from volumito.clients.errors import VolumioWebSocketError
from volumito.clients.host_configuration import VolumioHostConfiguration
from volumito.clients.websocket.common import (
    EVENT_PINGER,
    RESPONSE_EVENTS,
    VolumioWebSocketCommon,
)


def _load_socketio() -> ModuleType:
    """Import the optional WebSocket dependency, when a connection is about to be opened.

    Returns:
        The socketio module

    Raises:
        VolumioWebSocketError: If the package is not installed
    """
    try:
        import socketio
    except ImportError as e:
        raise VolumioWebSocketError(
            "Reaching the Volumio host over WebSocket needs the python-socketio package: "
            "install it with 'pip install volumito[websocket]'"
        ) from e

    # python-socketio ships no type stubs, as paramiko does not either
    return cast(ModuleType, socketio)


class VolumioWebSocketClient(VolumioWebSocketCommon):
    """Client for interacting with Volumio's WebSocket API.

    The client owns the Socket.IO connection it emits through: use it as a context
    manager, so the connection is closed when the block is left.
    """

    def __init__(
        self,
        host_configuration: VolumioHostConfiguration,
        timeout: float = 5.0,
        logger: logging.Logger | None = None,
    ) -> None:
        """Initialize the WebSocket API client.

        Args:
            host_configuration: The host configuration (scheme, host, and ports)
            timeout: The number of seconds a read waits for its answer (default: 5.0)
            logger: The logger the client writes to; without one, the client logs
                under its own name in the ``volumito`` hierarchy
        """
        super().__init__(host_configuration, timeout, logger)
        self._log_debug(f"Initializing the {self._CLIENT_DESCRIPTION}...")
        self._client: Any = None
        self._connected = False
        self._handlers: dict[str, list[Callable[[Any], None]]] = {}
        self._arrived: dict[str, threading.Event] = {}
        self._registered: set[str] = set()
        self._request_lock = threading.Lock()
        self._slots: dict[str, object] = {}
        self._log_debug(f"Initializing the {self._CLIENT_DESCRIPTION}... done")

    def _deliver(self, event: str, payload: object) -> None:
        """Hand an event the host pushed to whoever is waiting for it.

        Args:
            event: The name of the event
            payload: What the event carried
        """
        self._log_debug(f'Received "{event}"')
        arrived = self._arrived.get(event)
        if arrived is not None:
            self._slots[event] = payload
            arrived.set()
        for handler in list(self._handlers.get(event, ())):
            try:
                handler(payload)
            except Exception:
                self._log_exception(f'A handler of "{event}" raised')

    def _emit(self, event: str, payload: object = None) -> None:
        """Send an event to the Volumio instance.

        Args:
            event: The name of the event to emit
            payload: What the event carries, when it carries anything

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        if not self._connected:
            self._fail_not_connected(f'emit "{event}"')
        self._log_debug(f'Emitting "{event}"...')
        try:
            if payload is None:
                self._client.emit(event)
            else:
                self._client.emit(event, payload)
        except Exception as e:
            self._fail_emit(event, e)
        self._log_debug(f'Emitting "{event}"... done')

    def _ensure_registered(self, event: str) -> None:
        """Make sure the connection hands an event over when the host pushes it.

        Args:
            event: The name of the event to listen for
        """
        if event in self._registered or self._client is None:
            return
        self._client.on(event, self._receiver(event))
        self._registered.add(event)

    def _receiver(self, event: str) -> Callable[..., None]:
        """Build the callback the connection calls when the host pushes an event.

        Args:
            event: The name of the event the callback listens for

        Returns:
            The callback handing the payload over to :meth:`_deliver`
        """

        def receive(payload: object = None) -> None:
            self._deliver(event, payload)

        return receive

    def _request(
        self,
        event: str,
        response_event: str | None = None,
        payload: object = None,
        timeout: float | None = None,
    ) -> object:
        """Emit an event and return the payload of the answer the host pushes back.

        The reads are serialized: ``search`` and ``browseLibrary`` are answered by the
        same event, so two reads in flight at once could take each other's answer.

        Args:
            event: The event to emit
            response_event: The event carrying the answer, looked up when not given
            payload: What the emitted event carries, when it carries anything
            timeout: The number of seconds to wait, the timeout of the client when
                not given

        Returns:
            What the answer carried

        Raises:
            ValueError: If no answer event is given for an event the host does not answer
            VolumioConnectionError: If not connected, if the event cannot be sent, or if
                the host does not answer in time
        """
        awaited = response_event if response_event is not None else self._response_event(event)
        waited = timeout if timeout is not None else self.timeout
        with self._request_lock:
            self._log_debug(f'Requesting "{event}", waiting for "{awaited}"...')
            # an answer event outside the map is listened for from its first read on
            self._ensure_registered(awaited)
            arrived = threading.Event()
            self._arrived[awaited] = arrived
            try:
                self._emit(event, payload)
                if not arrived.wait(waited):
                    self._fail_no_response(event, awaited, waited)
                answer = self._slots.pop(awaited, None)
            finally:
                self._arrived.pop(awaited, None)
            self._log_debug(f'Requesting "{event}", waiting for "{awaited}"... done')
            return answer

    def connect(self) -> None:
        """Open the connection to the Volumio WebSocket API.

        Connecting an already connected client does nothing.

        Raises:
            VolumioWebSocketError: If the python-socketio package is not installed
            VolumioConnectionError: If the connection cannot be opened
        """
        if self._connected:
            self._log_debug("Already connected to the Volumio WebSocket API")
            return
        sio: Any = _load_socketio()
        url = self.host_configuration.websocket_base_url
        self._log_debug(f'Connecting to the Volumio WebSocket API at "{url}"...')
        self._client = sio.Client(reconnection=False)
        self._registered = set()
        for event in set(RESPONSE_EVENTS.values()) | set(self._handlers):
            self._ensure_registered(event)
        try:
            self._client.connect(url)
        except Exception as e:
            self._client = None
            self._registered = set()
            self._fail_connection(e)
        self._connected = True
        self._log_debug(f'Connecting to the Volumio WebSocket API at "{url}"... done')

    def disconnect(self) -> None:
        """Close the connection to the Volumio WebSocket API.

        This method is safe to call multiple times and will not raise exceptions.
        """
        if self._connected:
            self._log_debug("Disconnecting from the Volumio WebSocket API...")
            try:
                self._client.disconnect()
            except Exception as e:
                self._log_warning(
                    f"Ignoring an error while disconnecting from the Volumio "
                    f"WebSocket API: {e}"
                )
            finally:
                self._client = None
                self._connected = False
                self._registered = set()
            self._log_debug("Disconnecting from the Volumio WebSocket API... done")

    def emit(self, event: str, payload: object = None) -> None:
        """Send an event to the Volumio instance, without waiting for anything.

        This is the way to reach the events the client exposes no member for: a Volumio
        host listens for far more of them than the REST API has endpoints.

        Args:
            event: The name of the event to emit
            payload: What the event carries, when it carries anything

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        self._emit(event, payload)

    def off(self, event: str, handler: Callable[[Any], None] | None = None) -> None:
        """Stop calling a handler, or every handler, when an event arrives.

        Args:
            event: The name of the event
            handler: The handler to remove; without one, every handler of the event
                is removed
        """
        if handler is None:
            self._handlers.pop(event, None)
            self._log_debug(f'Removed every handler of "{event}"')
            return
        handlers = self._handlers.get(event)
        if handlers is not None and handler in handlers:
            handlers.remove(handler)
            self._log_debug(f'Removed a handler of "{event}"')

    def on(self, event: str, handler: Callable[[Any], None]) -> None:
        """Call a handler with the payload of an event whenever the host pushes it.

        A Volumio host pushes some events on its own -- ``pushState`` on every change of
        the playback state, and a few more the moment the connection opens -- and pushes
        others as the answer to a read, in which case the handler is called too.

        Handlers can be registered before connecting. They run on the thread the
        connection reads on, and an exception one raises is logged and swallowed, so one
        failing handler does not stop the others.

        Args:
            event: The name of the event to listen for (e.g., ``"pushState"``)
            handler: The callable receiving the payload of the event
        """
        self._handlers.setdefault(event, []).append(handler)
        self._ensure_registered(event)
        self._log_debug(f'Added a handler of "{event}"')

    def ping(self) -> str:
        """Ping the Volumio instance to check that it is reachable.

        The host echoes back, unchanged, what the ping carried, so the answer is matched
        against what was sent rather than merely awaited.

        Returns:
            ``"pong"`` from a healthy Volumio instance

        Raises:
            VolumioConnectionError: If not connected, or if the host does not answer in
                time or does not echo the ping back
        """
        nonce = uuid.uuid4().hex
        echoed = self._request(EVENT_PINGER, payload={"nonce": nonce})
        if not isinstance(echoed, dict) or echoed.get("nonce") != nonce:
            self._log_warning(f"The Volumio API answered a ping with {echoed!r}")
            self._fail_no_response(EVENT_PINGER, self._response_event(EVENT_PINGER), self.timeout)
        return "pong"

    def request(
        self,
        event: str,
        response_event: str | None = None,
        payload: object = None,
        timeout: float | None = None,
    ) -> object:
        """Emit an event and return the payload of the answer the host pushes back.

        This is the way to read through the events the client exposes no member for.

        Args:
            event: The event to emit
            response_event: The event carrying the answer; needed for the events the
                client does not already know the answer of
            payload: What the emitted event carries, when it carries anything
            timeout: The number of seconds to wait, the timeout of the client when
                not given

        Returns:
            What the answer carried

        Raises:
            ValueError: If no answer event is given for an event the host does not answer
            VolumioConnectionError: If not connected, if the event cannot be sent, or if
                the host does not answer in time
        """
        return self._request(event, response_event, payload, timeout)

    def wait(self) -> None:
        """Block until the connection to the Volumio instance drops.

        Raises:
            VolumioConnectionError: If not connected
        """
        if not self._connected:
            self._fail_not_connected("wait for events")
        self._log_debug("Waiting for the connection to drop...")
        self._client.wait()
        self._log_debug("Waiting for the connection to drop... done")

    def __enter__(self) -> Self:
        """Context manager entry - connects to the Volumio WebSocket API.

        Returns:
            The VolumioWebSocketClient instance

        Raises:
            VolumioWebSocketError: If the python-socketio package is not installed
            VolumioConnectionError: If the connection cannot be opened
        """
        self.connect()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Context manager exit - disconnects from the Volumio WebSocket API.

        Args:
            exc_type: Exception type (if any)
            exc_val: Exception value (if any)
            exc_tb: Exception traceback (if any)
        """
        self.disconnect()
