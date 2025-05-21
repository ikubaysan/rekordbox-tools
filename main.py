from pyrekordbox import Rekordbox6Database
from pyrekordbox.db6.tables import DjmdPlaylist, DjmdCue
from typing import List, Dict, Optional
import argparse
import sys

def format_duration(ms: int) -> str:
    minutes = ms // 60000
    seconds = (ms % 60000) // 1000
    return f"{minutes}m {seconds}s"

def main():
    # Parse playlist name from command-line argument
    parser = argparse.ArgumentParser(description="Get songs and cue timings from a Rekordbox playlist.")
    parser.add_argument("playlist_name", help="Name of the Rekordbox playlist to read.")
    args = parser.parse_args()

    db = Rekordbox6Database()
    playlist_query = db.get_playlist()

    playlists: Dict[str, DjmdPlaylist] = {p.Name: p for p in playlist_query}
    selected_playlist = playlists.get(args.playlist_name)

    if selected_playlist is None:
        print(f"Playlist '{args.playlist_name}' not found.")
        sys.exit(1)

    print(f"Playlist '{args.playlist_name}' found with {len(selected_playlist.Songs)} songs.\n")

    total_duration_ms = 0
    skipped_song_count = 0
    report_lines = []

    for song in selected_playlist.Songs:
        content = song.Content
        # Get hot cues (non-memory cues)
        hot_cues: List[DjmdCue] = [cue for cue in content.Cues if not cue.is_memory_cue]

        if len(hot_cues) < 4:
            report_lines.append(f"Skipping '{content.Title}': only {len(hot_cues)} hot cues.")
            skipped_song_count += 1
            continue

        # Sort cues by InMsec just in case they're unordered
        hot_cues.sort(key=lambda c: c.InMsec)

        # Calculate distances between each pair of contiguous cues
        distances_ms = []
        for i in range(len(hot_cues) - 1):
            distance = hot_cues[i + 1].InMsec - hot_cues[i].InMsec
            distances_ms.append(distance)

        # Find the max distance
        max_distance_ms = max(distances_ms)

        total_duration_ms += max_distance_ms

        duration_str = format_duration(max_distance_ms)

        report_lines.append(f"'{content.Title}': {max_distance_ms} ms ({duration_str})")

    total_duration_str = format_duration(total_duration_ms)

    # Print report
    print("=== Song Durations ===")
    for line in report_lines:
        print(line)

    print("\n=== Total Set Duration ===")
    print(f"{total_duration_ms} ms ({total_duration_str})")

    print(f"{len(report_lines)} songs processed, {skipped_song_count} skipped.")

if __name__ == "__main__":
    main()
