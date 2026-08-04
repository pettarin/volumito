"""Tests for the push notification listener.

:copyright: Copyright (C) 2025-2026 Alberto Pettarin
:license: GNU General Public License v3.0 (see the LICENSE file for details)
"""

import socket
from collections.abc import Iterator

import pytest
import requests
from pytest_mock import MockerFixture

from volumito.clients import (
    NotificationListener,
    VolumioConnectionError,
    VolumioHostConfiguration,
    receiver_url,
)

ENDPOINT = "/volumionotifications"
"""Path the listeners under test serve."""

STATE_NOTIFICATION = {
    "item": "state",
    "data": {"status": "play", "title": "Caterina", "artist": "Francesco De Gregori"},
}
"""A notification of the shape a Volumio host pushes."""


@pytest.fixture
def listener() -> Iterator[NotificationListener]:
    """Serve on a system-assigned port of the loopback interface."""
    with NotificationListener(port=0, endpoint=ENDPOINT, bind_address="127.0.0.1") as serving:
        yield serving


def _url(listening: NotificationListener, path: str = ENDPOINT) -> str:
    """Return the URL of a path served by a listener."""
    return f"http://127.0.0.1:{listening.port}{path}"


class TestNotificationListener:
    """Test cases for the NotificationListener class."""

    def test_receives_a_notification(self, listener: NotificationListener):
        """A posted notification is answered with 200 and yielded as a model."""
        response = requests.post(_url(listener), json=STATE_NOTIFICATION, timeout=5)

        received = list(listener.listen(count=1))

        assert response.status_code == 200
        assert response.text == ""
        assert len(received) == 1
        assert received[0].item == "state"
        assert received[0].data == STATE_NOTIFICATION["data"]
        # The posted payload stays available on the model
        assert received[0].raw == STATE_NOTIFICATION

    def test_receives_several_notifications_in_order(self, listener: NotificationListener):
        """The notifications are yielded in arrival order, up to the requested count."""
        for index in range(3):
            requests.post(_url(listener), json={"item": f"item{index}"}, timeout=5)

        received = list(listener.listen(count=2))

        assert [notification.item for notification in received] == ["item0", "item1"]

    def test_iterating_yields_the_notifications(self, listener: NotificationListener):
        """The listener itself is an iterator over the notifications."""
        requests.post(_url(listener), json=STATE_NOTIFICATION, timeout=5)

        notification = next(iter(listener))

        assert notification.item == "state"

    def test_another_path_is_not_found(self, listener: NotificationListener):
        """A notification posted to another path is refused and not delivered."""
        response = requests.post(_url(listener, "/elsewhere"), json=STATE_NOTIFICATION, timeout=5)

        assert response.status_code == 404
        assert list(listener.listen(idle_timeout=0.2)) == []

    def test_reading_the_endpoint_is_not_allowed(self, listener: NotificationListener):
        """The endpoint refuses a GET."""
        response = requests.get(_url(listener), timeout=5)

        assert response.status_code == 405

    def test_a_body_that_is_not_json(self, listener: NotificationListener):
        """A body that is not JSON is refused and not delivered."""
        response = requests.post(_url(listener), data="not json", timeout=5)

        assert response.status_code == 400
        assert list(listener.listen(idle_timeout=0.2)) == []

    def test_a_body_that_is_not_an_object(self, listener: NotificationListener):
        """A JSON body that is not an object is refused and not delivered."""
        response = requests.post(_url(listener), json=["state"], timeout=5)

        assert response.status_code == 400
        assert list(listener.listen(idle_timeout=0.2)) == []

    def test_an_empty_body(self, listener: NotificationListener):
        """A request without a body is refused and not delivered."""
        response = requests.post(_url(listener), timeout=5)

        assert response.status_code == 400
        assert list(listener.listen(idle_timeout=0.2)) == []

    def test_idle_timeout_returns(self, listener: NotificationListener):
        """Listening returns when no notification arrives within the idle timeout."""
        assert list(listener.listen(idle_timeout=0.2)) == []
        assert listener.idle_timed_out

    def test_timeout_returns(self, listener: NotificationListener):
        """Listening returns when the total timeout expires, which is not an idle timeout."""
        assert list(listener.listen(timeout=0.2)) == []
        assert not listener.idle_timed_out

    def test_an_expired_timeout_returns_at_once(self, listener: NotificationListener):
        """A timeout that is already over returns without waiting for anything."""
        requests.post(_url(listener), json=STATE_NOTIFICATION, timeout=5)

        assert list(listener.listen(timeout=0)) == []
        assert not listener.idle_timed_out

    def test_the_shorter_of_the_two_timeouts_applies(self, listener: NotificationListener):
        """With both timeouts given, the one expiring first ends the listening."""
        assert list(listener.listen(timeout=0.2, idle_timeout=5.0)) == []
        assert not listener.idle_timed_out

        assert list(listener.listen(timeout=5.0, idle_timeout=0.2)) == []
        assert listener.idle_timed_out

    def test_a_reached_count_is_not_a_timeout(self, listener: NotificationListener):
        """Reaching the count clears the idle timeout of an earlier listening."""
        assert list(listener.listen(idle_timeout=0.2)) == []
        assert listener.idle_timed_out

        requests.post(_url(listener), json=STATE_NOTIFICATION, timeout=5)

        assert len(list(listener.listen(count=1, idle_timeout=5.0))) == 1
        assert not listener.idle_timed_out

    def test_listening_before_serving(self):
        """Listening on a listener that is not serving is a programming error."""
        with pytest.raises(RuntimeError) as exc_info:
            list(NotificationListener(port=0).listen())

        assert "not serving" in str(exc_info.value)

    def test_the_port_before_and_after_starting(self):
        """The port is the requested one before starting, and the bound one after."""
        listening = NotificationListener(port=0, bind_address="127.0.0.1")

        assert listening.port == 0

        listening.start()
        try:
            assert listening.port > 0
        finally:
            listening.stop()

    def test_starting_twice_keeps_the_same_server(self, listener: NotificationListener):
        """Starting an already serving listener does nothing."""
        port = listener.port

        listener.start()

        assert listener.port == port

    def test_stopping_twice(self, listener: NotificationListener):
        """Stopping an already stopped listener does nothing."""
        listener.stop()

        listener.stop()

        assert listener.port == 0

    def test_the_port_is_released_on_exit(self):
        """Leaving the context frees the port for another listener."""
        with NotificationListener(port=0, endpoint=ENDPOINT, bind_address="127.0.0.1") as first:
            port = first.port

        with NotificationListener(
            port=port, endpoint=ENDPOINT, bind_address="127.0.0.1"
        ) as second:
            assert second.port == port

    def test_a_busy_port(self, listener: NotificationListener):
        """Binding a port already in use raises, leaving the caller to report it."""
        with pytest.raises(OSError):  # noqa: PT011
            NotificationListener(
                port=listener.port, endpoint=ENDPOINT, bind_address="127.0.0.1"
            ).start()


class TestReceiverUrl:
    """Test cases for the receiver_url function."""

    def test_builds_the_url_from_the_local_address(self, mocker: MockerFixture):
        """The URL carries the local address reaching the host, the port, and the endpoint."""
        probe = mocker.patch("volumito.clients.listener.socket.socket")
        probe.return_value.__enter__.return_value.getsockname.return_value = ("192.168.1.50", 4242)

        url = receiver_url(
            VolumioHostConfiguration(host="volumio.local"), 8080, "/hook"
        )

        assert url == "http://192.168.1.50:8080/hook"
        probe.return_value.__enter__.return_value.connect.assert_called_once_with(
            ("volumio.local", 3000)
        )

    def test_the_defaults(self, mocker: MockerFixture):
        """The default port and endpoint are those of the listener."""
        probe = mocker.patch("volumito.clients.listener.socket.socket")
        probe.return_value.__enter__.return_value.getsockname.return_value = ("192.168.1.50", 4242)

        assert (
            receiver_url(VolumioHostConfiguration())
            == "http://192.168.1.50:3003/volumionotifications"
        )

    def test_an_unreachable_host(self, mocker: MockerFixture):
        """A host no local address routes to is reported as a connection error."""
        probe = mocker.patch("volumito.clients.listener.socket.socket")
        probe.return_value.__enter__.return_value.connect.side_effect = socket.gaierror(
            "Name or service not known"
        )

        with pytest.raises(VolumioConnectionError) as exc_info:
            receiver_url(VolumioHostConfiguration(host="volumio.local"))

        assert "Failed to find the local address" in str(exc_info.value)
