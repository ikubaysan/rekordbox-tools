from pyrekordbox import Rekordbox6Database
from typing import List, Dict, Optional
from pyrekordbox.db6.tables import DjmdPlaylist


# Do something with `playlists` here
if __name__ == "__main__":

    db = Rekordbox6Database()
    playlist_query = db.get_playlist()

    playlists: Dict[str, DjmdPlaylist] = {}
    for p in playlist_query:
        playlists[p.Name] = p

    selected_playlist_name = ""
    selected_playlist = playlists.get(selected_playlist_name)

    if selected_playlist is None:
        print(f"Playlist '{selected_playlist_name}' not found.")
        quit(1)

    print(f"Playlist '{selected_playlist_name}' found.")

    song_contents = []

    for song in selected_playlist.Songs:
        content = song.Content
        song_contents.append(content)

        for cue in content.Cues:
            cue_comment: Optional[str] = cue.Comment


    pass
