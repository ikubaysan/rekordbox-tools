from pyrekordbox import Rekordbox6Database
from pyrekordbox.db6.tables import DjmdPlaylist, DjmdCue
from typing import List, Dict, Optional
import argparse
import sys


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

    def rekordbox_bpm_to_bpm(self, rekordbox_bpm: int) -> float:
        return rekordbox_bpm / 100 if rekordbox_bpm else 0.0

    def get_playlist(self, name: str) -> Optional[DjmdPlaylist]:
        return self.playlists.get(name)

    def analyze_song(self, song) -> Optional[str]:
        content = song.Content
        hot_cues: List[DjmdCue] = [cue for cue in content.Cues if not cue.is_memory_cue]

        if len(hot_cues) < 4:
            return f"Skipping '{content.Title}': only {len(hot_cues)} hot cues."

        hot_cues.sort(key=lambda c: c.InMsec)
        distances_ms = [
            hot_cues[i + 1].InMsec - hot_cues[i].InMsec
            for i in range(len(hot_cues) - 1)
        ]

        if len(distances_ms) < 2:
            return f"Skipping '{content.Title}': not enough distances calculated."

        distances_ms.sort(reverse=True)
        max_distance_ms = distances_ms[0] + distances_ms[1]
        duration_str = self.format_duration(max_distance_ms)

        line = (
            f"#{song.TrackNo} - '{content.Title}': {max_distance_ms} ms "
            f"({duration_str}). Play Count: {content.DJPlayCount}, "
            f"BPM: {self.rekordbox_bpm_to_bpm(content.BPM)}, Key: {content.Key.ScaleName}"
        )

        return line, max_distance_ms

    def print_playlist_info(self, playlist_name: str):
        selected_playlist = self.get_playlist(playlist_name)

        if selected_playlist is None:
            print(f"Playlist '{playlist_name}' not found.")
            sys.exit(1)

        print(f"Playlist '{playlist_name}' found with {len(selected_playlist.Songs)} songs.\n")

        total_duration_ms = 0
        skipped_song_count = 0
        report_lines = []

        all_songs = selected_playlist.Songs
        all_songs.sort(key=lambda song: song.TrackNo)

        for song in all_songs:
            result = self.analyze_song(song)
            if isinstance(result, str):  # Skipped with reason
                report_lines.append(result)
                skipped_song_count += 1
            else:
                line, song_duration = result
                report_lines.append(line)
                total_duration_ms += song_duration

        total_duration_str = self.format_duration(total_duration_ms)

        print("=== Song Durations ===")
        for line in report_lines:
            print(line)

        print("\n=== Total Set Duration ===")
        print(f"{total_duration_ms} ms ({total_duration_str})")

        print(f"{len(report_lines)} songs processed, {skipped_song_count} skipped.")


def main():
    parser = argparse.ArgumentParser(description="Get songs and cue timings from a Rekordbox playlist.")
    parser.add_argument("playlist_name", help="Name of the Rekordbox playlist to read.")
    args = parser.parse_args()

    analyzer = RekordboxPlaylistAnalyzer()
    analyzer.print_playlist_info(args.playlist_name)


if __name__ == "__main__":
    main()
