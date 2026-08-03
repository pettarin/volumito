# volumito

Python client library and CLI tool for Volumio.


## Overview

`volumito` is a Python library and a CLI tool
that allows querying and controlling a
[Volumio](https://volumio.com/)
host.


## Features

- Clean Python API to query the state of a Volumio host and to control it
- Extensive and configurable CLI tool
- AI-generated, Human-reviewed code
- Type-safe implementation with type hints
- Comprehensive unit test coverage (100%)


## Requirements

- Python 3.13 or later
- A package/virtual environment manager tool (e.g., `micromamba`, `conda`, `uv`, etc.)
- A running Volumio host


## Installation

**IMPORTANT**: the examples in the documentation use `micromamba`
               to manage virtual environments; feel free to replace it
               with your favorite tool (`conda`, `uv`, etc.).

### From PyPI (Recommended)

`volumito` is published on PyPI by @pettarin as the same-name package
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

You should be able to run:

```bash
(volumito_env) $ volumito version
volumito, version 0.1.0
```

The next time you want to use `volumito`,
you will only need to activate the existing virtual environment:

```bash
$ micromamba activate volumito_env

(volumito_env) $ volumito version
volumito, version 0.1.0
```

To update `volumito`, use the `-U/--upgrade` option:

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

You should be able to run:

```bash
(volumito_env) $ volumito version
volumito, version 0.1.0
```


## Usage

### CLI Usage

Some examples of the commands made available
by the CLI tool `volumito` in the virtual enviroment
where it is installed:

```bash
$ # print help/usage messages; it works globally and on commands and subcommands
$ volumito --help
$ volumito playback --help

$ # create a configuration file (you might want to inspect/edit it later)
$ volumito configuration create -f ~/volumito.yaml
Created configuration file ~/volumito.yaml

$ # print information about the Volumio host
$ volumito system info
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

$ # print the playback status
$ volumito playback status
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

$ # print the list of tracks currently in the reproduction queue
$ volumito queue get
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
    {
        "album": "La Vie En Rouge",
        "artist": "Enrico Ruggeri",
        "duration": "00:04:07",
        "position": 3,
        "title": "La Vie En Rouge",
        "tracknumber": 1,
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

$ # print information about the current track,
$ # with a short format (a subset of all available fields)
$ volumito track info
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

$ # print information about the current track,
$ # with all the available fields
$ volumito track info --fields all
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

$ # control the playback on the Volumio host
$ volumito playback play
$ volumito playback pause
$ volumito playback stop
$ volumito playback previous
$ volumito playback next
$ volumito playback seek 00:01:02
$ volumito playback mute
$ volumito playback unmute
$ volumito playback volume 80

$ # print the list of all available playlists
$ volumito playlist list
[
    "another playlist",
    "my awesome playlist",
    "volumito test playlist"
]

$ # play the specified playlist, replacing the current queue
$ volumito playlist play "my awesome playlist"
Command 'playplaylist my awesome playlist' executed successfully
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

The document
[docs/CLI_USAGE.md](docs/CLI_USAGE.md)
describes all the commands, subcommands, and options
of the CLI tool `volumito`.

### Library Usage

A quick example:

```python
from volumito import (
    VolumioHostConfiguration,
    VolumioRESTAPIClient,
)

# replace with your Volumio host
host = VolumioHostConfiguration(host="volumio.local")
client = VolumioRESTAPIClient(host)


# retrieve and print the system information
print(client.system_info)
# {'id': 'REDACTED', 'host': 'http://192.168.1.122', 'name': 'volumio',
# 'type': 'device', 'serviceName': 'Volumio', 'state': {'status': 'play',
# 'volume': 39, 'mute': False, 'artist': 'Paolo Conte', 'track': 'Recitando',
# 'albumart': 'https://static.qobuz.com/images/covers/jc/sa/m0kxbt4a8sajc_600.jpg'},
# 'systemversion': '4.119', 'builddate': 'Tue Mar 24 17:20:52 UTC 2026',
# 'variant': 'volumio', 'hardware': 'pi', 'os': '12', 'isPremiumDevice': False,
# 'isVolumioProduct': False, 'hwUuid': 'REDACTED'}


# retrieve and print the current playing state
print(client.state)
# {'status': 'play', 'position': 5, 'title': 'Recitando', 'artist': 'Paolo Conte',
# 'album': "Paolo Conte Alla Scala - il Maestro è nell'anima",
# 'albumart': 'https://static.qobuz.com/images/covers/jc/sa/m0kxbt4a8sajc_600.jpg',
# 'uri': 'qobuz://song/264525074', 'trackType': 'qobuz', 'seek': 125029,
# 'duration': 229, 'samplerate': '44.1 kHz', 'bitdepth': '24 bit',
# 'channels': 2, 'bitrate': '1347 Kbps', 'random': False, 'repeat': False,
# 'repeatSingle': False, 'consume': True, 'volume': 49, 'dbVolume': None,
# 'mute': False, 'disableVolumeControl': False, 'stream': False,
# 'updatedb': False, 'volatile': False, 'service': 'qobuz'}

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

# print the current queue
queue = client.queue["queue"]
for index, item in enumerate(queue, 1):
    print(f"{index}. {item.get('title')} - {item.get('artist')}")
# 1. Aguaplano - Paolo Conte
# 2. Sotto Le Stelle Del Jazz - Paolo Conte
# 3. Come Di - Paolo Conte
# 4. Alle Prese Con Una Verde Milonga - Paolo Conte
# 5. Ratafià - Paolo Conte
# ...

# play the 4th track of the current queue
# (positions start at index zero)
client.play(3)

# read the seek position, then seek to 01:42 (both in seconds)
print(client.seek)
client.seek = 102

# play the previous/next track
client.previous()
client.next()


# list playlists and play one
playlist_name = "Jazz Classics"
if playlist_name in client.playlists:
    client.play_playlist(playlist_name)
else:
    print(f"No such playlist: '{playlist_name}'")
```

The document
[docs/LIBRARY_USAGE.md](docs/LIBRARY_USAGE.md)
contains the API reference of the Python library `volumito`.


## Releases And Changelog

The list of releases and their changes is contained
in the
[docs/CHANGELOG.md](docs/CHANGELOG.md)
document.


## Development

Consult the
[docs/DEVELOPMENT.md](docs/DEVELOPMENT.md)
document to learn how to set up a development environment,
run the tests, browse the project structure, and contribute.


## License

This project is licensed under
the GNU General Public License v3.0 or later (GPLv3+).

See the
[LICENSE](LICENSE)
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
