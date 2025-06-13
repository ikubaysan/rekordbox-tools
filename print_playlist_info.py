# print_playlist_info.py
# Usage:
#   python print_playlist_info.py --playlist "My Playlist Name"
#   ^-- Replace "My Playlist Name" with the actual Rekordbox playlist name.
#       You can specify arguments in any order when using --flags.

import argparse
from RekordboxPlaylistAnalyzer import RekordboxPlaylistAnalyzer


def main():
    parser = argparse.ArgumentParser(description="Print Rekordbox playlist info.")
    parser.add_argument("--playlist", required=True, help="Name of the Rekordbox playlist to analyze")
    args = parser.parse_args()

    analyzer = RekordboxPlaylistAnalyzer()
    print(analyzer.analyze_playlist(args.playlist))

if __name__ == "__main__":
    main()