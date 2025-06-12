# watch_playlist_playing.py
# Usage:
#   python watch_playlist_playing.py --playlist "My Playlist Name" [--interval 30]
#
#   --playlist    : Required. Name of the Rekordbox playlist to monitor.
#   --interval    : Optional. Number of seconds between refreshes (default: 30).
#   You can specify arguments in any order when using --flags.

import argparse
import time
from RekordboxPlaylistAnalyzer import RekordboxPlaylistAnalyzer


def main():
    parser = argparse.ArgumentParser(description="Monitor Rekordbox playlist for currently playing song.")
    parser.add_argument("--playlist", required=True, help="Name of the Rekordbox playlist to monitor")
    parser.add_argument("--interval", type=int, default=30, help="Refresh interval in seconds (default: 30)")
    args = parser.parse_args()

    analyzer = RekordboxPlaylistAnalyzer()
    try:
        songs = analyzer.get_playlist_songs_by_trackno(args.playlist)
    except ValueError as e:
        print(e)
        return

    previous_counts = {song.Content.ID: song.Content.DJPlayCount for song in songs}
    current_song = songs[0]  # assume first song if unknown

    print(f"Monitoring '{args.playlist}'... (every {args.interval}s)")

    while True:

        analyzer = RekordboxPlaylistAnalyzer()  # refresh DB instance
        try:
            songs = analyzer.get_playlist_songs_by_trackno(args.playlist)
        except ValueError:
            print("Playlist disappeared or could not be refreshed.")
            continue

        for song in songs:
            prev_count = previous_counts.get(song.Content.ID, song.Content.DJPlayCount)
            if song.Content.DJPlayCount > prev_count:
                current_song = song
            previous_counts[song.Content.ID] = song.Content.DJPlayCount

        print(f"Currently playing: #{current_song.TrackNo} - {current_song.Content.Title} ({RekordboxPlaylistAnalyzer.rekordbox_bpm_to_bpm(current_song.Content.BPM)} BPM)")
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
