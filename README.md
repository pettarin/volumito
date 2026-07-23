# volumito

Python client library and CLI tool for Volumio.


## Overview

`volumito` is a Python library and a CLI tool
that allows querying and controlling a
[Volumio](https://volumio.com/)
host.


## Features

- Clean Python API to query and control a Volumio host
- Type-safe implementation with type hints
- Comprehensive test coverage (100%)
- An extensive and configurable CLI tool


## Requirements

- Python 3.13 or later
- A package/virtual environment manager tool
- A running Volumio host


## Installation

**IMPORTANT**: the examples in the documentation use `micromamba`
               to manage virtual environments; feel free to replace it
               with your favorite tool (`conda`, `uv`, etc.)

### From PyPI

Create a virtual environment (only the first time),
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
volumito, version 0.0.13
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
volumito, version 0.0.13
```


## Usage

### CLI Usage

Some examples of the commands made available
by the CLI tool ``volumito`` in the virtual enviroment
where it is installed:

```bash
$ # print help/usage messages; it works globally and on commands and subcommands
$ volumito --help
$ volumito playback --help

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
        "album": "Sirtaki",
        "artist": "Mango",
        "duration": "00:06:58",
        "position": 1,
        "title": "Nella mia città"
    },
    {
        "album": "Sirtaki",
        "artist": "Mango",
        "duration": "00:04:34",
        "position": 2,
        "title": "I giochi del vento sul lago salato"
    },
    {
        "album": "Sirtaki",
        "artist": "Mango",
        "duration": "00:05:18",
        "position": 3,
        "title": "Terra bianca"
    },
    ...
    {
        "album": "Disincanto",
        "artist": "Mango",
        "duration": "00:03:37",
        "position": 25,
        "title": "Gli angeli non volano"
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

The document
[docs/LIBRARY_USAGE.md](docs/LIBRARY_USAGE.md)
contains the API reference of the Python library `volumito`.


## Releases And Changelog

The list of releases and their changes is contained
in the
[docs/CHANGELOG](docs/CHANGELOG.md)
document.


## Development

Consult the
[docs/DEVELOPMENT.md](docs/DEVELOPMENT.md)
document to learn how to set up a development environment,
run the tests, browse the project structure, and contribute.


## License

This project is licensed under
the GNU General Public License v3.0 or later (GPLv3+).

See the [LICENSE](LICENSE) file for details.


## Authors

- Alberto Pettarin ([Web](https://www.albertopettarin.it))


## Legal Disclaimers

Volumio and the Volumio logo are registered trademarks of Volumio SRL,
a company registered in Italy (VAT ID: IT07009020483).

Please refer to the [Volumio Terms Of Service](https://volumio.com/terms-of-service/).

This project and its authors are not affiliated
nor endorsed by Volumio SRL.
