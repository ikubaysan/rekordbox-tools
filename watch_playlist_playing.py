# watch_playlist_playing.py
# -------------------------
# Monitor a Rekordbox playlist and print the currently playing song.
#
# Usage:
#   python watch_playlist_playing.py --playlist "My Playlist Name" [--interval 30]
#
# Options:
#   --playlist   Required. Name of the Rekordbox playlist to monitor.
#   --interval   Optional. Seconds between checks (default: 30).
#
# Example:
#   python watch_playlist_playing.py \
#       --playlist "Deep House Essentials" \
#       --interval 15

import argparse
import time
from RekordboxPlaylistAnalyzer import RekordboxPlaylistAnalyzer

def main():
    parser = argparse.ArgumentParser(
        description="Monitor Rekordbox playlist for currently playing song."
    )
    parser.add_argument(
        "--playlist", required=True,
        help="Name of the Rekordbox playlist to monitor"
    )
    parser.add_argument(
        "--interval", type=int, default=30,
        help="Seconds between checks (default: 30)"
    )
    args = parser.parse_args()

    analyzer = RekordboxPlaylistAnalyzer()
    try:
        prev_counts = analyzer.init_play_counts(args.playlist)
    except ValueError as e:
        print(e)
        return

    last_known_song = None
    print(f"Monitoring '{args.playlist}' every {args.interval}s…")

    while True:
        current, prev_counts = analyzer.detect_current_song(
            args.playlist, prev_counts, last_known_song
        )
        last_known_song = current

        bpm = analyzer.rekordbox_bpm_to_bpm(current.Content.BPM)
        print(
            f"→ Now playing: "
            f"#{current.TrackNo} – {current.Content.Title} "
            f"({bpm:.2f} BPM)"
        )
        time.sleep(args.interval)

if __name__ == "__main__":
    main()
