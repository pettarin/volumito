# Library Usage

This document describes how to use `volumito` as a Python library.
For the command-line tool, see [CLI_USAGE.md](CLI_USAGE.md).


## Contents

- [Quick Start](#quick-start)


## Quick Start

```python
from volumito import (
    Album,
    Artist,
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
# (positions start at zero, see Units And Conventions below)
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


# get stories and album credits
# (requires a Premium subscription on the Volumio host;
# entities are given by free text, or by MusicBrainz ID with is_mbid=True)
client.get_story(artist=Artist("Miles Davis"))
client.get_story(album=Album("Kind of Blue"), artist=Artist("Miles Davis"))
client.get_story(album=Album("83d91898-7763-47d7-b03b-b92132375c47", is_mbid=True))
client.get_album_credits(Artist("Miles Davis"), Album("Kind of Blue"))
```

