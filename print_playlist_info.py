#!/usr/bin/env python
# ---------------------------------------------------------------------------
# Print Rekordbox playlist info.
#
# Usage examples
#   python print_playlist_info.py --playlist "My Playlist Name"
#   python print_playlist_info.py --playlist "My Playlist" --max-songs 25
#
# Flags
#   --playlist   (required)  Name of the Rekordbox playlist to analyze.
#   --max-songs, -n          Only process the first N tracks (sorted by TrackNo).
# ---------------------------------------------------------------------------

import argparse
from RekordboxPlaylistAnalyzer import RekordboxPlaylistAnalyzer


def main() -> None:
    parser = argparse.ArgumentParser(description="Print Rekordbox playlist info.")
    parser.add_argument(
        "--playlist",
        required=True,
        help="Name of the Rekordbox playlist to analyze",
    )
    parser.add_argument(
        "--max-songs",
        "-n",
        type=int,
        metavar="N",
        help="Only analyze the first N songs (sorted by track number)",
    )
    args = parser.parse_args()

    analyzer = RekordboxPlaylistAnalyzer()
    print(analyzer.analyze_playlist(args.playlist, max_songs=args.max_songs))


if __name__ == "__main__":
    main()
