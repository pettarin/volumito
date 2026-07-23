# Library Usage

This document describes how to use `volumito` as a Python library.
For the command-line tool, see [CLI_USAGE.md](CLI_USAGE.md).

**IMPORTANT**: this document needs to be reworked,
               it might contain wrong pieces of information.

## Contents

- [Quick Start](#quick-start)
- [VolumioHostConfiguration](#volumiohostconfiguration)
- [VolumioRESTAPIClient](#volumiorestapiclient)
- [VolumioMPDClient](#volumiompdclient)
- [Error Handling](#error-handling)
- [Units And Conventions](#units-and-conventions)
- [Examples](#examples)

## Quick Start

Everything meant for public use is exported from the top-level package:

```python
from volumito import (
    VolumioAPIError,
    VolumioConnectionError,
    VolumioError,
    VolumioHostConfiguration,
    VolumioMPDClient,
    VolumioRESTAPIClient,
)

host = VolumioHostConfiguration(host="volumio.local")
client = VolumioRESTAPIClient(host)

state = client.get_state()
print(state["title"], "-", state["artist"])
```

## VolumioHostConfiguration

A frozen dataclass bundling the connection parameters, passed to both clients:

```python
VolumioHostConfiguration(
    scheme="http",            # "http" or "https"
    host="volumio.local",     # hostname or IP address
    rest_api_port=3000,       # REST API port
    mpd_port=6600,            # MPD port (6599 on Volumio 3 and earlier)
)
```

All four fields have the defaults shown above, so `VolumioHostConfiguration()` already points at a
Volumio instance at its usual location. Being frozen, an instance is hashable and safe to share;
build a variant with `dataclasses.replace`.

It exposes one property:

```python
host = VolumioHostConfiguration(scheme="https", host="192.168.1.100", rest_api_port=8080)
host.rest_base_url        # "https://192.168.1.100:8080"
```

## VolumioRESTAPIClient

```python
VolumioRESTAPIClient(host_configuration, timeout=5.0)
```

`timeout` is the per-request timeout in seconds. The client holds no connection and no state, so a
single instance can serve any number of calls.

Every method performs one HTTP GET and raises `VolumioConnectionError` or `VolumioAPIError` on
failure (see [Error Handling](#error-handling)). Unless noted otherwise, each returns the parsed
JSON object of the response, as a `dict`.

### Player State And Queue

| Method | Returns |
|---|---|
| `get_state()` | The full player state: `status`, `title`, `artist`, `album`, `duration`, `seek`, `volume`, `mute`, `position`, and more |
| `get_queue()` | The playback queue, under the `"queue"` key |

### Playback Control

| Method | Effect |
|---|---|
| `toggle()` | Toggle between play and pause |
| `play(position=None)` | Start playback; with `position`, play that queue entry (**0-indexed**) |
| `pause()` | Pause playback |
| `stop()` | Stop playback |
| `next()` | Skip to the next track |
| `previous()` | Skip to the previous track |
| `seek(value)` | Seek to `value` seconds, or `"plus"`/`"minus"` to seek relatively |
| `volume(value)` | Set the volume to an integer 0-100, or one of `"mute"`, `"unmute"`, `"plus"`, `"minus"` |

The Volumio API accepts a `seek` position outside the track and a playlist name that does not
exist without reporting an error; the CLI guards against both, the library does not.

### Queue Management

| Method | Effect |
|---|---|
| `clear()` | Clear the playback queue |
| `repeat(value=None)` | Enable (`True`) or disable (`False`) the repeat mode; `None` toggles it |
| `randomize(value=None)` | Enable, disable, or toggle the random (shuffle) mode |

### Playlists

| Method | Returns / effect |
|---|---|
| `list_playlists()` | A **`list`** of the names of the saved playlists |
| `play_playlist(name)` | Start playback of the playlist named `name` (percent-encoded for you) |

### System, Library, And Multiroom

| Method | Returns |
|---|---|
| `ping()` | The response body as **`str`** (`"pong"` from a healthy instance) |
| `get_system_version()` | The system version information |
| `get_system_info()` | The system information |
| `collectionstats()` | The statistics of the music collection |
| `get_zones()` | The multiroom zones, under the `"zones"` key |

### Low-Level Escape Hatch

```python
client.send_command("random&value=true")
```

`send_command(cmd)` sends `cmd` to the commands endpoint verbatim and returns the parsed response.
Every playback and queue method above is a thin wrapper around it; use it directly for a command
the library does not cover yet. The argument is interpolated as given: percent-encode any value
that may contain a space or an `&`.

## VolumioMPDClient

The REST API does not expose the URI of the file being played; MPD does. This client wraps
[python-mpd2](https://pypi.org/project/python-mpd2/) for that purpose:

```python
VolumioMPDClient(host_configuration, timeout=5.0)
```

| Method | Effect |
|---|---|
| `connect()` | Open the connection; raises `VolumioConnectionError` on failure |
| `disconnect()` | Close it; safe to call more than once, never raises |
| `get_current_song()` | The current song as a `dict`, straight from MPD |
| `get_track_uri()` | The `file` value of the current song, as `str` |

`get_track_uri` rewrites `localhost` and `127.0.0.1` in the URI to the configured host, so the
result is reachable from the machine running the code — that is what makes the URI downloadable.

Both `get_current_song` and `get_track_uri` raise `VolumioConnectionError` when the client is not
connected or no track is playing.

The client is a context manager, which is the recommended way to use it:

```python
with VolumioMPDClient(host) as mpd_client:
    uri = mpd_client.get_track_uri()
```

## Error Handling

```
VolumioError                 # base class, catch this to catch everything
├── VolumioConnectionError   # the instance could not be reached
└── VolumioAPIError          # the instance answered, but not usefully
```

- `VolumioConnectionError` — connection refused, DNS failure, timeout, any other request failure,
  and every MPD-side failure (including "not connected" and "no track currently playing").
- `VolumioAPIError` — an HTTP error status, a body that is not valid JSON, or a payload of the
  wrong shape (an object where an array was expected, or the reverse).

```python
from volumito import VolumioAPIError, VolumioConnectionError, VolumioRESTAPIClient

try:
    state = client.get_state()
except VolumioConnectionError as e:
    print(f"cannot reach the instance: {e}")
except VolumioAPIError as e:
    print(f"the instance answered with an error: {e}")
```

## Units And Conventions

The library returns what the Volumio API returns, without the conversions the CLI applies for
display:

| Value | Unit / convention |
|---|---|
| `seek` in the state | **milliseconds** |
| `duration` in the state | **seconds** |
| `position` in the state | queue index, **starting at zero** |
| `seek(value)` argument | **seconds** |

## Examples

### Print What Is Playing

```python
from volumito import VolumioConnectionError, VolumioHostConfiguration, VolumioRESTAPIClient

client = VolumioRESTAPIClient(VolumioHostConfiguration(host="volumio.local"))

try:
    state = client.get_state()
except VolumioConnectionError as e:
    raise SystemExit(f"cannot reach the instance: {e}") from e

print(f"{state['status']}: {state['title']} - {state['artist']}")
print(f"at {state['seek'] / 1000:.0f} s of {state['duration']} s")
```

### Seek, Then Check The Result

```python
import time

client.seek(60)
time.sleep(1.0)                       # give the instance a moment to apply it
print(client.get_state()["seek"])     # milliseconds
```

### Play A Playlist If It Exists

```python
name = "Jazz Classics"

if name in client.list_playlists():
    client.play_playlist(name)
else:
    print(f"no such playlist: {name}")
```

### Download The Current Track

```python
import requests

from volumito import VolumioHostConfiguration, VolumioMPDClient

host = VolumioHostConfiguration(host="volumio.local")

with VolumioMPDClient(host) as mpd_client:
    uri = mpd_client.get_track_uri()

response = requests.get(uri, timeout=5.0, stream=True)
response.raise_for_status()
with open("track.flac", "wb") as f:
    for chunk in response.iter_content(chunk_size=8192):
        f.write(chunk)
```

### Walk The Queue

```python
queue = client.get_queue()["queue"]

for index, item in enumerate(queue):
    print(f"{index + 1}. {item.get('title')} - {item.get('artist')}")
```
