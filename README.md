# volumito

Python client library and CLI tool for [Volumio](https://volumio.com/).


## Overview

`volumito` is a Python library and a CLI tool
that allows querying and controlling a
[Volumio](https://volumio.com/)
host.


## Features

- Clean Python API to query the state of a Volumio host and to control it
- Synchronous and asynchronous clients for the Volumio REST and WebSocket APIs
- Extensive and configurable CLI tool
- AI-generated, Human-reviewed code
- Type-safe implementation with type hints
- Comprehensive unit test coverage (100%)


## Requirements

- Python 3.13 or later
- A package/virtual environment manager tool (e.g., `micromamba`, `conda`, `uv`, etc.)
- A running Volumio host


## Installation

> [!NOTE]
> The examples in the documentation use `micromamba`
> to manage virtual environments; feel free to replace it
> with your favorite tool (`conda`, `uv`, etc.).

### From PyPI (Recommended)

`volumito` is published on PyPI as the same-name package
[volumito](https://pypi.org/project/volumito/)
, and this is the recommended way of installing it for most users.

Only the first time: create a virtual environment,
activate it, and install the latest release of `volumito`
available on PyPI with `pip`:

```bash
$ micromamba create -n volumito_env python=3.13
$ micromamba activate volumito_env

(volumito_env) $ pip install volumito
```

> [!NOTE]
> To use certain additional functionalities, not included by default,
> you will need to install `volumito` with `pip install volumito[<EXTRA>]`,
> where `<EXTRA>` is:
> - `async`: required by the asynchronous client `VolumioAsyncRESTAPIClient`
>   for the REST API of Volumio
>   (including when using the `volumito` CLI tool with
>   `--api-client asynchronous_rest`);
> - `scp`: required by the `volumito scp` and `volumito system execute`
>   (advanced and potentially dangerous) commands;
> - `websocket`: required by both the synchronous `VolumioWebSocketClient`
>   and asynchronous `VolumioAsyncWebSocketClient` clients
>   of the WebSocket API of Volumio
>   (including when using the `volumito` CLI tool with
>   `--api-client asynchronous_websocket` or
>   `--api-client synchronous_websocket`).

> [!TIP]
> The `all` extra installs all of them:
> `pip install volumito[all]`.

You should be able to run the `volumito` CLI tool,
automatically installed in the virtual environment:

```bash
(volumito_env) $ volumito version
volumito, version 0.4.0
```

The next time you want to use `volumito`,
you will only need to activate the existing virtual environment:

```bash
$ micromamba activate volumito_env

(volumito_env) $ volumito version
volumito, version 0.4.0
```

To update `volumito`, use the `-U / --upgrade` option:

```bash
$ micromamba activate volumito_env

(volumito_env) $ pip install volumito --upgrade
```


### From Source

Clone this repository and install from source
in a virtual environment:

```bash
$ git clone https://github.com/pettarin/volumito
$ cd volumito

$ micromamba create -n volumito_env python=3.13
$ micromamba activate volumito_env

(volumito_env) $ pip install -e .
(volumito_env) $ # or
(volumito_env) $ make install-e-this
```

> [!NOTE]
> To use certain additional functionalities, not included by default,
> you will need to install `volumito` with `pip install -e .[<EXTRA>]`
> or `make install-e-this-<EXTRA>`,
> where `<EXTRA>` is:
> - `async`: required by the asynchronous client `VolumioAsyncRESTAPIClient`
>   for the REST API of Volumio, and by the `volumito` CLI tool
>   when run with `--api-client asynchronous_rest`;
> - `scp`: required by the `volumito scp` and `volumito system execute`
>   (advanced and potentially dangerous) commands;
> - `websocket`: required by both the synchronous `VolumioWebSocketClient`
>   and asynchronous `VolumioAsyncWebSocketClient` clients
>   of the WebSocket API of Volumio, and by the `volumito` CLI tool
>   when run with `--api-client synchronous_websocket`
>   or `--api-client asynchronous_websocket`.

> [!TIP]
> The `all` extra installs all of them:
> `pip install -e .[all]` or `make install-e-this-all`.

You should be able to run the `volumito` CLI tool,
automatically installed in the virtual environment:

```bash
(volumito_env) $ volumito version
volumito, version 0.4.0
```


## Usage

### CLI Usage

The
[CLI Usage](https://github.com/pettarin/volumito/blob/main/docs/cli/INDEX.md)
guide describes all the commands, subcommands, and most of the options
of the CLI tool `volumito`.

Some examples of the commands made available
by the CLI tool `volumito` in the virtual enviroment
where it is installed:

> [!NOTE]
> For the sake of brevity, in the following examples:
> - the `(volumito_env) $` shell prompt is omitted;
> - some commands are shown without their output or with truncated output;
> - several commands and options are not illustrated.
> Consult the
> [CLI Usage](https://github.com/pettarin/volumito/blob/main/docs/cli/INDEX.md)
> for a comprehensive guide of the CLI tool `volumito`.

```bash
# print help/usage messages; it works globally and on commands and subcommands
volumito --help
volumito playback --help

# create a configuration file (you might want to inspect/edit it later)
volumito configuration create -o ~/volumito.yaml
[2026-08-13T13:52:30.130Z] [INFO] Created configuration file "/home/alberto/volumito.yaml"

# use the REST API or WebSocket asynchronous client,
# instead of the default "synchronous_rest" client
volumito --api-client asynchronous_rest playback status
volumito --api-client asynchronous_websocket playback status

# print information about the Volumio host
volumito system info
{
    "builddate": "Tue Mar 24 17:20:52 UTC 2026",
    "hardware": "pi",
    "host": "http://192.168.1.122",
    "hwUuid": "<REDACTED>",
    "id": "<REDACTED>",
    "isPremiumDevice": false,
    "isVolumioProduct": false,
    "name": "volumio",
    "os": "12",
    "serviceName": "Volumio",
    "state": {
        "albumart": "https://static.qobuz.com/images/covers/64/04/0639842660464_600.jpg",
        "artist": "Mango",
        "mute": false,
        "status": "play",
        "track": "Nella mia città",
        "volume": 20
    },
    "systemversion": "4.119",
    "type": "device",
    "variant": "volumio"
}

# print the playback status
volumito playback status
{
    "album": "Sirtaki",
    "artist": "Mango",
    "bitdepth": "16 bit",
    "channels": 2,
    "duration": "00:04:34",
    "mute": false,
    "position": 2,
    "samplerate": "44 KHz",
    "seek": "00:00:21.528",
    "status": "play",
    "title": "I giochi del vento sul lago salato",
    "trackType": "qobuz",
    "volume": 20
}

# print the list of tracks currently in the reproduction queue
volumito queue get
[
    {
        "album": "Polvere",
        "artist": "Enrico Ruggeri",
        "duration": "00:03:15",
        "position": 1,
        "title": "Va tutto bene",
        "tracknumber": 1,
        "volumeNumber": 1
    },
    {
        "album": "Polvere",
        "artist": "Enrico Ruggeri",
        "duration": "00:03:56",
        "position": 2,
        "title": "Fuoco sui giocattoli",
        "tracknumber": 2,
        "volumeNumber": 1
    },
    ...
    {
        "album": "La Vie En Rouge",
        "artist": "Enrico Ruggeri",
        "duration": "00:04:49",
        "position": 11,
        "title": "La Bandiera",
        "tracknumber": 3,
        "volumeNumber": 2
    }
]

# print information about the current track,
# with a short format (a subset of all available fields)
volumito track info
{
    "album": "Sirtaki",
    "artist": "Mango",
    "bitdepth": "16 bit",
    "channels": 2,
    "duration": "00:04:34",
    "position": 2,
    "samplerate": "44 KHz",
    "title": "I giochi del vento sul lago salato",
    "trackType": "qobuz"
}

# print information about the current track,
# with all the available fields
volumito track info --fields ALL
{
    "album": "Sirtaki",
    "albumart": "https://static.qobuz.com/images/covers/64/04/0639842660464_600.jpg",
    "artist": "Mango",
    "bitdepth": "16 bit",
    "channels": 2,
    "consume": false,
    "dbVolume": null,
    "disableVolumeControl": false,
    "duration": "00:04:34",
    "mute": false,
    "position": 2,
    "random": false,
    "repeat": false,
    "repeatSingle": false,
    "samplerate": "44 KHz",
    "seek": "00:01:53.135",
    "service": "qobuz",
    "status": "play",
    "stream": "qobuz",
    "title": "I giochi del vento sul lago salato",
    "trackType": "qobuz",
    "updatedb": false,
    "uri": "qobuz://song/2581513",
    "volatile": false,
    "volume": 20
}

# control the playback on the Volumio host
volumito playback play
volumito playback pause
volumito playback stop
volumito playback previous
volumito playback next
volumito playback seek 00:01:02
volumito playback mute
volumito playback unmute
volumito playback volume 80

# print the list of all available playlists
volumito playlist list
[
    "another playlist",
    "my awesome playlist",
    "volumito test playlist"
]

# play the specified playlist, replacing the current queue
volumito playlist play "my awesome playlist"
[2026-08-12T20:14:05.213Z] [INFO] Command 'playplaylist "my awesome playlist"' executed successfully
{
    "album": "Sirtaki",
    "artist": "Mango",
    "bitdepth": "16 bit",
    "channels": 2,
    "duration": "00:06:59",
    "mute": false,
    "position": 1,
    "samplerate": "44.1 kHz",
    "seek": "00:00:01.001",
    "status": "play",
    "title": "Nella mia città",
    "trackType": "qobuz",
    "volume": 30
}
```

### Library Usage

The
[Library Usage](https://github.com/pettarin/volumito/blob/main/docs/LIBRARY_USAGE.md)
document contains the API reference of the Python library `volumito`.

There are five major clients available for the APIs of Volumio:

- `VolumioAsyncRESTAPIClient`: asynchronous client for the REST API;
- `VolumioAsyncWebSocketClient`: asynchronous client for the WebSocket API;
- `VolumioMPDClient`: synchronous client for the MPD API;
- `VolumioRESTAPIClient`: synchronous client for the REST API;
- `VolumioWebSocketClient`: synchronous client for the WebSocket API.

The following is a short example
of the synchronous client for the REST API of Volumio:

```python
from volumito import (
    VolumioHostConfiguration,
    VolumioRESTAPIClient,
)

# replace with your Volumio host
host = VolumioHostConfiguration(host="volumio.local")
client = VolumioRESTAPIClient(host)


# retrieve the system information
info = client.system_info
print(info.name, info.system_version, info.is_premium_device)
# volumio 4.119 False


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

# play one, checking that it exists first
playlist_name = "Jazz Classics"
if playlist_name in client.playlists:
    client.play_playlist(playlist_name)
else:
    print(f"No such playlist: '{playlist_name}'")
```

The same API is available asynchronously,
provided the `async` extra is installed
(`pip install volumito[async]`):

```python
import asyncio

from volumito import (
    VolumioAsyncRESTAPIClient,
    VolumioHostConfiguration,
)

# replace with your Volumio host
host = VolumioHostConfiguration(host="volumio.local")


async def main():
    async with VolumioAsyncRESTAPIClient(host) as client:
        state = await client.get_state()
        print(state.title, "---", state.artist)
        # Recitando --- Paolo Conte

        await client.pause()
        await client.set_volume(50)

        # independent queries can travel together
        info, queue = await asyncio.gather(
            client.get_system_info(),
            client.get_queue(),
        )
        print(info.name, len(queue))
        # volumio 12


asyncio.run(main())
```

The same API is also available over Volumio's WebSocket API,
provided the `websocket` extra is installed
(`pip install volumito[websocket]`).
Its clients hold one open connection, and can listen to what the host pushes:

```python
from volumito import (
    VolumioHostConfiguration,
    VolumioWebSocketClient,
)

# replace with your Volumio host
host = VolumioHostConfiguration(host="volumio.local")

with VolumioWebSocketClient(host) as client:
    print(client.state.title, "---", client.state.artist)
    # Recitando --- Paolo Conte

    client.pause()
    client.volume = 50

    # react to what the host pushes, until the connection drops
    client.on("pushState", lambda state: print(state["status"], state["title"]))
    client.wait()
```

An asynchronous counterpart `VolumioAsyncWebSocketClient` is also available.

Beyond the members the REST clients also offer,
the WebSocket clients reach the functionalities that the REST API of Volumio does not
expose at all: editing the queue and the saved playlists, the favourites and the web
radios, the sleep timer and the alarms, the audio outputs, the library scans, the power
of the host, and its administration (plugins, network, shares, and preferences).
See the
[Library Usage](https://github.com/pettarin/volumito/blob/main/docs/LIBRARY_USAGE.md#beyond-the-rest-api)
document for the whole list.


## Releases And Changelog

The list of releases and their changes is contained
in the
[CHANGELOG](https://github.com/pettarin/volumito/blob/main/docs/CHANGELOG.md)
document.


## Development

Consult the
[DEVELOPMENT](https://github.com/pettarin/volumito/blob/main/docs/DEVELOPMENT.md)
document to learn how to set up a development environment,
run the tests, and browse the project structure.

The
[CONTRIBUTING](https://github.com/pettarin/volumito/blob/main/docs/CONTRIBUTING.md)
document explains how to report issues and propose changes.


## License

This project is licensed under
the GNU General Public License v3.0 or later (GPLv3+).

See the
[LICENSE](https://github.com/pettarin/volumito/blob/main/LICENSE)
file for details.


## Authors

- Alberto Pettarin ([Web](https://www.albertopettarin.it))


## Legal Disclaimers

Volumio and the Volumio logo are registered trademarks of Volumio SRL,
a company registered in Italy (VAT ID: IT07009020483).

Please refer to the
[Volumio Terms Of Service](https://volumio.com/terms-of-service/).

This project and its authors are not affiliated
nor endorsed by Volumio SRL.

