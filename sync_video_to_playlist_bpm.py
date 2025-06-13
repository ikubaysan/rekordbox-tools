# sync_video_to_playlist_bpm.py
# -----------------------------
# Loop an MP4 video and sync its playback speed to your Rekordbox playlist’s BPM.
#
# Usage:
#    python sync_video_to_playlist_bpm.py --playlist "My Playlist Name" --video "C:/path/to/video.mp4" [--average-bpm] [--interval 30]
#
# Options:
#   --playlist     Required. Rekordbox playlist name to monitor.
#   --video        Required. Path to the MP4 video file to loop.
#   --average-bpm  Optional flag. If set, use the playlist’s average BPM
#                  instead of the first track.
#   --interval     Optional. Seconds between BPM checks (default: 30).
#
# Example:
#   python sync_video_to_playlist_bpm.py --playlist "Deep House" --video "C:/Users/Me/Videos/ambient_loop.mp4" --average-bpm --interval 15

import argparse
import random
import time
from datetime import datetime

import os
from RekordboxPlaylistAnalyzer import RekordboxPlaylistAnalyzer
vlc = RekordboxPlaylistAnalyzer.load_vlc_module()

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
    parser.add_argument(
        "--max-playback-rate", type=float, default=None,
        help="If set, use dynamic playback rate - 1x on the lowest BPM, and this multiplier on the highest BPM"
    )
    args = parser.parse_args()

    analyzer = RekordboxPlaylistAnalyzer()

    # Determine base BPM
    base_bpm = analyzer.get_base_bpm(args.playlist, average=args.average_bpm)
    mode = "average" if args.average_bpm else "first track"
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] "
          f"Base BPM ({mode}): {base_bpm:.2f}")

    if args.max_playback_rate:
        bpms = [
            analyzer.rekordbox_bpm_to_bpm(s.Content.BPM)
            for s in analyzer.get_playlist_songs_by_trackno(args.playlist)
        ]
        min_bpm = min(bpms)
        max_bpm = max(bpms)
        print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] "
              f"Dynamic scaling enabled: Min BPM in this playlist is {min_bpm:.2f}, Max BPM is {max_bpm:.2f} BPM. "
              f"Rates to be used: 1.0–{args.max_playback_rate:.2f}x")
    else:
        min_bpm = base_bpm
        max_bpm = base_bpm
        print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] "
              f"Static scaling: 1.0x for {base_bpm:.2f} BPM, adjusting rate based on how many "
              f"X faster or slower the current song is compared to this base BPM.")

    # Set up VLC player
    instance = vlc.Instance('--vout=opengl')

    player = instance.media_player_new()
    media = instance.media_new(str(args.video))

    # Loop the video indefinitely
    media.add_option("input-repeat=999999")

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
    last_known_song = None

    # Main loop
    while True:
        time.sleep(args.interval)

        current, prev_counts = analyzer.detect_current_song(
            args.playlist, prev_counts, last_known_song
        )
        last_known_song = current  # Update memory of last song

        curr_bpm = analyzer.rekordbox_bpm_to_bpm(current.Content.BPM)
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if args.max_playback_rate:
            mult = 1.0 + ((curr_bpm - base_bpm) / (max_bpm - base_bpm)) * (args.max_playback_rate - 1.0)
        else:
            mult = analyzer.get_bpm_multiplier(curr_bpm, base_bpm)


        print(
            f"[{timestamp}] "
            f"Song #{current.TrackNo} – \"{current.Content.Title}\" | "
            f"Current BPM: {curr_bpm:.2f} | Base BPM based on {mode}: {base_bpm:.2f} | Playback rate: {mult:.2f}x | "
            f"Max playback rate: {round(args.max_playback_rate, 2) if args.max_playback_rate else 'N/A'}"
        )

        player.set_rate(mult)

if __name__ == "__main__":
    main()
