# sync_video_to_playlist_bpm.py
# -----------------------------
# Loop an MP4 video and sync its playback speed to your Rekordbox playlist’s BPM.
#
# Usage:
#   python sync_video_to_playlist_bpm.py \
#       --playlist "My Playlist Name" \
#       --video "C:/path/to/video.mp4" \
#       [--average-bpm] [--interval 30]
#
# Options:
#   --playlist     Required. Rekordbox playlist name to monitor.
#   --video        Required. Path to the MP4 video file to loop.
#   --average-bpm  Optional flag. If set, use the playlist’s average BPM
#                  instead of the first track.
#   --interval     Optional. Seconds between BPM checks (default: 30).
#
# Example:
#   python sync_video_to_playlist_bpm.py \
#       --playlist "Deep House Essentials" \
#       --video "C:/Users/Me/Videos/ambient_loop.mp4" \
#       --average-bpm \
#       --interval 15

import argparse
import random
import time
from datetime import datetime
import vlc

from RekordboxPlaylistAnalyzer import RekordboxPlaylistAnalyzer

def main():
    parser = argparse.ArgumentParser(
        description="Loop a video and sync its playback speed to Rekordbox BPM."
    )
    parser.add_argument(
        "--playlist", required=True,
        help="Rekordbox playlist name"
    )
    parser.add_argument(
        "--video", required=True,
        help="Path to the MP4 video file"
    )
    parser.add_argument(
        "--average-bpm", action="store_true",
        help="Use average BPM of playlist instead of first track"
    )
    parser.add_argument(
        "--interval", type=int, default=30,
        help="Seconds between BPM checks (default: 30)"
    )
    args = parser.parse_args()

    analyzer = RekordboxPlaylistAnalyzer()

    # Determine base BPM
    base_bpm = analyzer.get_base_bpm(args.playlist, average=args.average_bpm)
    mode = "average" if args.average_bpm else "first track"
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] "
          f"Base BPM ({mode}): {base_bpm:.2f}")

    # Set up VLC player
    instance = vlc.Instance()
    player = instance.media_player_new()
    media = instance.media_new(str(args.video))
    player.set_media(media)
    player.play()

    # Give VLC some time to load the media
    time.sleep(0.5)
    length_ms = player.get_length()
    length_s = length_ms / 1000.0 if length_ms > 0 else 0.0

    # Seek to a random start point
    if length_s > 0:
        start = random.uniform(0, length_s)
        player.set_time(int(start * 1000))
        print(
            f"[{datetime.now():%Y-%m-%d %H:%M:%S}] "
            f"Starting video at {start:.1f}s of {length_s:.1f}s"
        )

    # Initialize play-count tracking
    prev_counts = analyzer.init_play_counts(args.playlist)

    # Main loop
    while True:
        time.sleep(args.interval)

        current, prev_counts = analyzer.detect_current_song(
            args.playlist, prev_counts
        )
        curr_bpm = analyzer.rekordbox_bpm_to_bpm(current.Content.BPM)
        mult = analyzer.get_bpm_multiplier(curr_bpm, base_bpm)
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        print(
            f"[{timestamp}] "
            f"Song #{current.TrackNo} – \"{current.Content.Title}\" | "
            f"{curr_bpm:.2f} BPM → rate {mult:.2f}x"
        )

        player.set_rate(mult)

if __name__ == "__main__":
    main()
