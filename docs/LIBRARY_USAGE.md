# Library Usage

This document describes how to use `volumito` as a Python library.

> [!TIP]
> For the command-line tool `volumito`, see the
> [CLI Usage](https://github.com/pettarin/volumito/blob/main/docs/cli/INDEX.md)
> guide.

## Contents

- [Quick Start](#quick-start)
- [Async Client](#async-client)
- [WebSocket Client](#websocket-client)
- [Response Models](#response-models)
- [Reference](#reference)


## Quick Start

```python
from volumito import (
    Album,
    Artist,
    NotificationListener,
    VolumioHostConfiguration,
    VolumioRESTAPIClient,
    VolumioStoryError,
)

# replace with your Volumio host
host = VolumioHostConfiguration(host="volumio.local")
client = VolumioRESTAPIClient(host)


# retrieve the system information
info = client.system_info
print(info.name, info.system_version, info.is_premium_device)
# volumio 4.119 False
print(info.state.artist, "-", info.state.track)
# Mango - Nella mia città


# retrieve the current playing state
state = client.state
print(state.title, "---", state.artist, "---", state.album)
# Recitando --- Paolo Conte --- Paolo Conte Alla Scala - il Maestro è nell'anima
print(state.status, state.volume, state.seek, state.duration)
# play 49 125029 229
print(state.is_playing, state.is_paused, state.is_stopped)
# True False False

# the payload the Volumio host returned is always available
print(state.raw["trackType"], state.raw["samplerate"])
# qobuz 44.1 kHz

# pause/play/stop the current track (and check the playback status)
client.pause()
print(client.is_paused)
client.play()
print(client.is_playing)
client.stop()
print(client.is_stopped)

# read and control the volume
print(client.volume)
client.volume = 50
client.mute()
print(client.is_muted)
client.unmute()

# print the current queue (which is a sequence of its tracks)
for index, track in enumerate(client.queue, 1):
    print(f"{index}. {track.title} - {track.artist}")
# 1. Aguaplano - Paolo Conte
# 2. Sotto Le Stelle Del Jazz - Paolo Conte
# 3. Come Di - Paolo Conte
# 4. Alle Prese Con Una Verde Milonga - Paolo Conte
# 5. Ratafià - Paolo Conte
# ...

# play the 4th track of the current queue, by track or by position
# (positions start at index zero)
client.play(client.queue[3])
client.play(3)

# read the seek position, then seek to 01:42 (both in seconds)
print(client.seek)
client.seek = 102

# play the previous/next track
client.previous()
client.next()


# list the saved playlists (which are a sequence of their playlists)
for playlist in client.playlists:
    print(playlist.name)
# Jazz Classics
# Rock
# ...

# play one, by playlist or by name, checking that it exists first
playlist_name = "Jazz Classics"
if playlist_name in client.playlists:
    client.play_playlist(playlist_name)
else:
    print(f"No such playlist: '{playlist_name}'")


# list the URLs receiving the push notifications
# (which are a sequence of their notifications)
for notification in client.notifications:
    print(notification.url)
# http://192.168.1.100:3223/receiver1
# ...

# unregister the first URL (receiver1)
client.unregister_notification(client.notifications[0])

# register three new URLs
client.register_notification("http://192.168.1.100:3333/receiver2")
client.register_notification("http://192.168.1.100:3333/receiver3")
client.register_notification("http://192.168.1.100:3334/receiver4")

# register a new URL, and start listening on it
# (volumito_hostname is the machine running volumito)
url = "http://volumito_hostname:3003/volumionotifications"
client.register_notification(url)
try:
    with NotificationListener(port=3003, endpoint="/volumionotifications") as listener:
        for notification in listener.listen(count=3, idle_timeout=60):
            print(notification.item, notification.data)
    # state {'status': 'play', 'title': 'Caterina', ...}
    # queue [{'title': 'Caterina', ...}, ...]
finally:
    client.unregister_notification(url)


# search the sources of the host, and keep what is wanted
results = client.search("Paolo Conte")
for result_list in results.filtered(service="mpd"):
    print(result_list.title)
    for item in result_list:
        print(" ", item.kind, item.title, item.uri)
# Found 1 Artist 'paolo conte'
#   artist Paolo Conte artists://Paolo%20Conte
# ...


# browse the collection from a URI, the root without one
content = client.browse("music-library")
for item in content.items:
    print(item.title or item.name, item.uri)
# INTERNAL music-library/INTERNAL
# ...

# replace the queue with the content of a URI and play its second item,
# or add the content to the queue without touching playback
client.replace_queue_and_play(content.items[0].uri, index=1)
client.add_to_queue(content.items[0].uri)


# get stories and album credits
# (requires a Premium subscription on the Volumio host;
# entities are given by free text, or by MusicBrainz ID with is_mbid=True)
story = client.get_story(artist=Artist("Miles Davis"))
print(story.value)
client.get_story(album=Album("Kind of Blue"), artist=Artist("Miles Davis"))
client.get_story(album=Album("83d91898-7763-47d7-b03b-b92132375c47", is_mbid=True))
client.get_album_credits(Artist("Miles Davis"), Album("Kind of Blue"))

# a query the Volumio host cannot answer raises VolumioStoryError
try:
    client.get_story(artist=Artist("No Such Artist"))
except VolumioStoryError as e:
    print(f"Story error: {e}")
# Story error: not found
```


## Async Client

`VolumioAsyncRESTAPIClient` is the
[aiohttp](https://docs.aiohttp.org/)
counterpart of `VolumioRESTAPIClient`.

It needs `volumito` to be installed with the `async` extra:

```bash
pip install volumito[async]
```

> [!TIP]
> The `all` extra installs the `async` extra too.

The client owns the HTTP session it sends its requests through,
opening it on the first request:
use it as an async context manager,
so the session is closed when the block is left.

```python
import asyncio

from volumito import (
    Artist,
    VolumioAsyncRESTAPIClient,
    VolumioHostConfiguration,
)

# replace with your Volumio host
host = VolumioHostConfiguration(host="volumio.local")


async def main():
    async with VolumioAsyncRESTAPIClient(host) as client:
        # check that the host is reachable
        print(await client.ping())
        # pong

        # read what is playing, and control the playback
        state = await client.get_state()
        print(state.title, state.artist, state.status)
        # So What Miles Davis play
        await client.pause()
        await client.set_volume(50)

        # the queries that take arguments keep their names
        results = await client.search("miles davis")
        story = await client.get_story(artist=Artist("Miles Davis"))
        print(story.value)


asyncio.run(main())
```

Without an `async with` block, close the client yourself,
otherwise `aiohttp` reports an unclosed session
once the client is garbage collected:

```python
client = VolumioAsyncRESTAPIClient(host)
try:
    await client.get_state()
finally:
    await client.close()
```

Closing is idempotent and leaves the client usable:
a later request opens a fresh session.

### Differences Between Synchronous And Asynchronous Clients

The two clients expose the same members and return the same models.

However, since a property cannot be awaited,
the members the synchronous client exposes
as properties are coroutine methods here:
the nouns take a `get_` prefix,
the predicates keep their names,
and the assignable properties take a `set_` prefix.

| Synchronous                     | Asynchronous                               |
| ------------------------------- | ------------------------------------------ |
| `client.state`                  | `await client.get_state()`                 |
| `client.queue`                  | `await client.get_queue()`                 |
| `client.queue_status`           | `await client.get_queue_status()`          |
| `client.playlists`              | `await client.get_playlists()`             |
| `client.notifications`          | `await client.get_notifications()`         |
| `client.system_info`            | `await client.get_system_info()`           |
| `client.system_version`         | `await client.get_system_version()`        |
| `client.collection_statistics`  | `await client.get_collection_statistics()` |
| `client.zones`                  | `await client.get_zones()`                 |
| `client.volume`                 | `await client.get_volume()`                |
| `client.volume = 50`            | `await client.set_volume(50)`              |
| `client.seek`                   | `await client.get_seek()`                  |
| `client.seek = 102`             | `await client.set_seek(102)`               |
| `client.is_playing`             | `await client.is_playing()`                |
| `client.has_next`               | `await client.has_next()`                  |
| `client.browse(uri)`            | `await client.browse(uri)`                 |

> [!WARNING]
> Be careful with the `volume` and `seek` setters:
> for example, `client.volume = 50` on the async client
> silently replaces the method with the number instead of setting the volume.
> A type checker rejects the assignment, but a Python interpreter does not.
> You must use `await client.set_volume(50)` instead.

> [!WARNING]
> Unlike their synchronous counterparts,
> setters `set_*()` return the `CommandResponse` the Volumio host answered with.

### Running Queries Concurrently

The members reading two endpoints
(e.g., `get_queue_status`, `has_next`, `has_previous`)
await them one after the other,
so a failure surfaces as the same exception the synchronous client raises.

To let independent queries travel together,
gather them yourself:

```python
state, queue, info = await asyncio.gather(
    client.get_state(),
    client.get_queue(),
    client.get_system_info(),
)
```

A client whose requests all fail is reported the same way
as the synchronous one:
`VolumioConnectionError` for an unreachable or slow host,
`VolumioAPIError` for an answer the host refused or malformed.
`VolumioAsyncError` is raised instead when the
`aiohttp` package is not installed.


## WebSocket Client

`VolumioWebSocketClient` and `VolumioAsyncWebSocketClient` speak Volumio's
[WebSocket API](https://developers.volumio.com/api/websocket-api),
which the Volumio project considers its primary one.

They need `volumito` to be installed with the `websocket` extra:

```bash
pip install volumito[websocket]
```

> [!TIP]
> The `all` extra installs the `websocket` extra too.

Unlike the REST clients, which open a connection per request,
a WebSocket client holds one open connection:
use it as a context manager,
so the connection is closed when the block is left.

```python
from volumito import VolumioHostConfiguration, VolumioWebSocketClient

# replace with your Volumio host
host = VolumioHostConfiguration(host="volumio.local")

with VolumioWebSocketClient(host) as client:
    # check that the host is reachable
    print(client.ping())
    # pong

    # read what is playing, and control the playback
    print(client.state.title, client.state.artist, client.state.status)
    # So What Miles Davis play
    client.pause()
    client.volume = 50

    # the queries that take arguments keep their names
    results = client.search("miles davis")
    print(len(results.items))
    # 215
```

Without a `with` block, connect and disconnect yourself:

```python
client = VolumioWebSocketClient(host)
client.connect()
try:
    print(client.state.status)
finally:
    client.disconnect()
```

Disconnecting is idempotent and leaves the client usable:
connecting again opens a fresh connection.

### Listening To What The Host Pushes

This is what the WebSocket API offers that the REST API does not.
A Volumio host pushes an event whenever something changes --
`pushState` on every change of the playback state above all --
and `on` registers a handler for it:

```python
with VolumioWebSocketClient(host) as client:
    client.on("pushState", lambda state: print(state["status"], state["title"]))
    client.wait()  # block until the connection drops
```

`off(event, handler)` removes one handler,
`off(event)` removes them all.
Handlers may be registered before connecting.
On the asynchronous client a handler may also be a coroutine function.

> [!TIP]
> The REST API offers the same updates through `NotificationListener`,
> which runs a local HTTP server the host posts to.
> That needs a routable local address and an open inbound port;
> a WebSocket connection needs neither.

### Reaching The Rest Of The API

A Volumio host listens for far more events than the REST API has endpoints.
`emit` sends one without waiting,
and `request` sends one and returns the answer the host pushes back:

```python
with VolumioWebSocketClient(host) as client:
    client.emit("setSleep", {"enabled": True, "time": "23:30"})
    print(client.request("getSleep", "pushSleep"))
    # {'enabled': True, 'time': '23:30', ...}
```

The second argument of `request` names the event carrying the answer.
It can be left out for the events the client already knows the answer of
(`getState`, `getQueue`, `listPlaylist`, `browseLibrary`, `search`,
`getSystemInfo`, `getSystemVersion`, `getMyCollectionStats`,
`getMultiRoomDevices`, and `pinger`).

### Differences From The REST API Clients

The two families expose the same members and return the same models,
except where the WebSocket API cannot match the REST one:

> [!WARNING]
> **The commands return `None`.**
> A Volumio host answers `play`, `pause`, `volume` and the rest with nothing at all,
> so there is no `CommandResponse` to hand back.

> [!WARNING]
> **A read can be answered by a broadcast.**
> The host broadcasts `pushState` on every change of the playback state,
> so a `state` read may be answered by a broadcast it did not ask for --
> which carries the current state all the same.
> For the same reason the reads of one client are serialized:
> `search` and `browseLibrary` share their answer event,
> so two of them in flight at once could take each other's result.

Three members of the REST clients are absent, having no WebSocket equivalent:
`get_story` and `get_album_credits` (the metavolumio plugin is REST-only), and
`notifications` / `register_notification` / `unregister_notification`
(the HTTP push channel this client supersedes).

Two more behave differently:
`browse` takes no offset, since the WebSocket API answers the whole listing
(`BrowseResults.offset` skips into it), and
`seek_forward` / `seek_backward` read the current position first,
since the WebSocket API seeks to absolute positions only.

The asynchronous client follows the naming of `VolumioAsyncRESTAPIClient`:

```python
import asyncio

from volumito import VolumioAsyncWebSocketClient, VolumioHostConfiguration

host = VolumioHostConfiguration(host="volumio.local")


async def main():
    async with VolumioAsyncWebSocketClient(host) as client:
        print(await client.ping())
        state = await client.get_state()
        print(state.title, state.status)
        await client.set_volume(50)


asyncio.run(main())
```

`VolumioConnectionError` is raised for a host that cannot be reached, for an event
that cannot be sent, and for a read the host does not answer in time.
`VolumioWebSocketError` is raised instead when the
`python-socketio` package is not installed.


## Response Models

> [!WARNING]
> This section needs to be reviewed before version 1.0.0 is released.

Every query returns a model instead of a raw dictionary:

| Client member                                       | Model                               |
| --------------------------------------------------- | ----------------------------------- |
| `add_to_queue`, `replace_queue_and_play`            | `CommandResponse`                   |
| `browse`                                            | `BrowseResults`                     |
| `collection_statistics`                             | `CollectionStatistics`              |
| `get_album_credits`, `get_story`                    | `Story`                             |
| `notifications`                                     | `Notifications` (of `Notification`) |
| `NotificationListener.listen`                       | `PushNotification`                  |
| `pause`, `play`, `stop`, and the other commands     | `CommandResponse`                   |
| `ping`                                              | `str`                               |
| `playlists`                                         | `Playlists` (of `Playlist`)         |
| `queue`                                             | `Queue` (of `QueueTrack`)           |
| `register_notification`, `unregister_notification`  | `SuccessResponse`                   |
| `search`                                            | `SearchResults`                     |
| `state`                                             | `PlayerState`                       |
| `system_info`                                       | `SystemInfo`                        |
| `system_version`                                    | `SystemVersion`                     |
| `zones`                                             | `Zones` (of `Zone`)                 |

The WebSocket clients return the same models, with two differences: their commands
return `None` rather than a `CommandResponse`, since a Volumio host answers a command
with nothing at all, and `emit` and `request` hand back what the host pushed, untouched.

The models are [pydantic](https://docs.pydantic.dev/) models, so their fields are
typed and validated. A few things worth knowing:

- **The raw payload is always kept.** Every model has a `raw` attribute holding the
  JSON payload it was parsed from, including the keys the model does not describe:
  the response object for most models, the array of names for `Playlists` and of URLs
  for `Notifications` (and the name or the URL itself for each `Playlist` or
  `Notification`), and the whole response envelope for `Story`.
- **Field names are snake_case**, with the Volumio names as aliases: for example
  `state.track_type` for `trackType`, `track.volume_number` for `volumeNumber`, and
  `zone.is_self` for `isSelf`.
- **Every field is optional.** Volumio omits the fields that do not apply to what is
  playing (a web radio has no album, for instance), so a field that the host did not
  report is `None`.
- **An unexpected value never breaks a response.** A value that does not fit its
  field is ignored (the attribute stays `None`) instead of failing the whole
  response; that value is still readable in `raw`.
- `PlayerState` also offers the `is_playing`, `is_paused`, and `is_stopped` flags,
  computed from the state already fetched (unlike the client properties of the same
  name, which each perform a fresh request).
- **A queue track knows its position.** The Volumio API reports the queue as an array,
  so `Queue` gives each of its tracks the `position` it holds (starting from zero);
  `client.play(queue[3])` plays it. A `QueueTrack` parsed on its own has no position.
  Likewise, `client.play_playlist(playlist)` accepts one of the saved playlists.

Units follow the Volumio API: `PlayerState.seek` is in **milliseconds**, while
`duration` and the `seek` property of the client are in **seconds**.

The library logs under the standard `volumito` logger, which carries a
`logging.NullHandler` by default: attach your own handler
(`logging.getLogger("volumito").addHandler(...)`) to see its records. The clients also
accept a `logger` argument, for callers who manage their own.

The table above names the members of the synchronous client; the asynchronous client
returns the same models from the members named in
[Differences Between Synchronous And Asynchronous Clients](#differences-between-synchronous-and-asynchronous-clients).


## Reference

> [!WARNING]
> The Python reference documentation is not available at the moment;
> it will be published once version 1.0.0 is released.

The Python reference documentation is published
[here](https://www.albertopettarin.it/volumito/docs/).
