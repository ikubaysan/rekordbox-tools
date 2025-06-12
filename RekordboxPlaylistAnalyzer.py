# rekordbox_analyzer.py

from pyrekordbox import Rekordbox6Database
from pyrekordbox.db6.tables import DjmdPlaylist, DjmdCue
from typing import List, Dict, Optional


class RekordboxPlaylistAnalyzer:
    def __init__(self):
        self.db = Rekordbox6Database()
        self.playlists: Dict[str, DjmdPlaylist] = {
            playlist.Name: playlist for playlist in self.db.get_playlist()
        }

    def format_duration(self, ms: int) -> str:
        minutes = ms // 60000
        seconds = (ms % 60000) // 1000
        return f"{minutes}m {seconds}s"

    @staticmethod
    def rekordbox_bpm_to_bpm(rekordbox_bpm: int) -> float:
        return rekordbox_bpm / 100 if rekordbox_bpm else 0.0

    def get_playlist(self, name: str) -> Optional[DjmdPlaylist]:
        return self.playlists.get(name)

    def analyze_playlist(self, playlist_name: str) -> str:
        playlist = self.get_playlist(playlist_name)
        if playlist is None:
            return f"Playlist '{playlist_name}' not found."

        output = [f"Playlist '{playlist_name}' found with {len(playlist.Songs)} songs.\n"]

        total_duration_ms = 0
        skipped_count = 0
        song_lines = []

        all_songs = sorted(playlist.Songs, key=lambda song: song.TrackNo)

        for song in all_songs:
            content = song.Content
            hot_cues: List[DjmdCue] = [cue for cue in content.Cues if not cue.is_memory_cue]

            if len(hot_cues) < 4:
                song_lines.append(f"Skipping '{content.Title}': only {len(hot_cues)} hot cues.")
                skipped_count += 1
                continue

            hot_cues.sort(key=lambda c: c.InMsec)
            distances_ms = [
                hot_cues[i + 1].InMsec - hot_cues[i].InMsec
                for i in range(len(hot_cues) - 1)
            ]

            if len(distances_ms) < 2:
                song_lines.append(f"Skipping '{content.Title}': not enough distances.")
                skipped_count += 1
                continue

            distances_ms.sort(reverse=True)
            max_duration = distances_ms[0] + distances_ms[1]
            total_duration_ms += max_duration

            song_lines.append(
                f"#{song.TrackNo} - '{content.Title}': {max_duration} ms "
                f"({self.format_duration(max_duration)}). "
                f"Play Count: {content.DJPlayCount}, "
                f"BPM: {self.rekordbox_bpm_to_bpm(content.BPM)}, "
                f"Key: {content.Key.ScaleName}"
            )

        total_duration_str = self.format_duration(total_duration_ms)
        output.append("=== Song Durations ===")
        output.extend(song_lines)
        output.append(f"\n=== Total Set Duration ===")
        output.append(f"{total_duration_ms} ms ({total_duration_str})")
        output.append(f"{len(song_lines)} songs processed, {skipped_count} skipped.")

        return "\n".join(output)

    def get_playlist_songs_by_trackno(self, playlist_name: str):
        # Retrieve songs sorted by TrackNo ascending in the specified playlist
        playlist = self.get_playlist(playlist_name)
        if playlist is None:
            raise ValueError(f"Playlist '{playlist_name}' not found.")
        return sorted(playlist.Songs, key=lambda song: song.TrackNo)
