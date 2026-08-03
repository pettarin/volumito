# Library Usage

This document describes how to use `volumito` as a Python library.
For the command-line tool, see [CLI_USAGE.md](CLI_USAGE.md).


## Contents

- [Quick Start](#quick-start)
- [Response Models](#response-models)
- [Reference](#reference)


## Quick Start

```python
from volumito import (
    Album,
    Artist,
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

# play the 4th track of the current queue
# (positions start at index zero)
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


## Response Models

Every query returns a model instead of a raw dictionary:

| Client member                                       | Model                       |
| --------------------------------------------------- | --------------------------- |
| `collection_statistics`                             | `CollectionStatistics`      |
| `get_album_credits`, `get_story`                    | `Story`                     |
| `pause`, `play`, `stop`, and the other commands     | `CommandResponse`           |
| `ping`                                              | `str`                       |
| `playlists`                                         | `Playlists` (of `Playlist`) |
| `queue`                                             | `Queue` (of `QueueTrack`)   |
| `state`                                             | `PlayerState`               |
| `system_info`                                       | `SystemInfo`                |
| `system_version`                                    | `SystemVersion`             |
| `zones`                                             | `Zones` (of `Zone`)         |

The models are [pydantic](https://docs.pydantic.dev/) models, so their fields are
typed and validated. A few things worth knowing:

- **The raw payload is always kept.** Every model has a `raw` attribute holding the
  JSON payload it was parsed from, including the keys the model does not describe:
  the response object for most models, the array of names for `Playlists` (and the
  name itself for each `Playlist`), and the whole response envelope for `Story`.
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

Units follow the Volumio API: `PlayerState.seek` is in **milliseconds**, while
`duration` and the `seek` property of the client are in **seconds**.


## Reference

TODO: add link to the Sphinx-generated documentation for the `volumito` Python library.
