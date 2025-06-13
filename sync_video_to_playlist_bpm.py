# sync_video_to_playlist_bpm.py
# -----------------------------
# Loop an MP4 video and sync its playback speed to your Rekordbox playlist’s BPM.
#
# Usage:
#   python sync_video_to_playlist_bpm.py --playlist "My Playlist Name" --video "C:/path/to/video.mp4" [--average-bpm] [--interval 30] [--jump-interval X]
#
# Options:
#   --playlist        Required. Rekordbox playlist name to monitor.
#   --video           Required. Path to the MP4 video file to loop.
#   --average-bpm     Optional. Use the playlist’s average BPM instead of the first track.
#   --interval        Optional. Seconds between BPM checks (default: 30).
#   --max-playback-rate Optional. Enables dynamic rate scaling between 1.0x and this rate.
#   --jump-interval   Optional. If set, jumps to a random video position every X seconds.

import argparse
import random
import time
from datetime import datetime
import os

from RekordboxPlaylistAnalyzer import RekordboxPlaylistAnalyzer
vlc = RekordboxPlaylistAnalyzer.load_vlc_module()


def jump_to_random_position(player, length_s: float):
    if length_s > 0:
        new_pos = random.uniform(0, length_s)
        player.set_time(int(new_pos * 1000))
        print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] Jumping to {new_pos:.1f}s of {length_s:.1f}s")


def main():
    parser = argparse.ArgumentParser(
        description="Loop a video and sync its playback speed to Rekordbox BPM."
    )
    parser.add_argument("--playlist", required=True, help="Rekordbox playlist name")
    parser.add_argument("--video", required=True, help="Path to the MP4 video file")
    parser.add_argument("--average-bpm", action="store_true", help="Use average BPM of playlist instead of first track")
    parser.add_argument("--interval", type=int, default=30, help="Seconds between BPM checks (default: 30)")
    parser.add_argument("--max-playback-rate", type=float, default=None, help="If set, use dynamic playback rate")
    parser.add_argument("--jump-interval", type=int, default=None, help="If set, skip to a random part of the video every X seconds")

    args = parser.parse_args()

    # Print config at start
    print("\n--- Script Configuration ---")
    for key, value in vars(args).items():
        print(f"{key}: {value}")
    print("----------------------------\n")

    analyzer = RekordboxPlaylistAnalyzer()
    base_bpm = analyzer.get_base_bpm(args.playlist, average=args.average_bpm)
    mode = "average" if args.average_bpm else "first track"
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] Base BPM ({mode}): {base_bpm:.2f}")

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

    jump_to_random_position(player, length_s)

    # Initialize play-count tracking
    prev_counts = analyzer.init_play_counts(args.playlist)
    last_known_song = None
    last_jump_time = time.time()

    # Main loop
    while True:
        time.sleep(args.interval)

        now = time.time()
        if args.jump_interval and (now - last_jump_time >= args.jump_interval):
            jump_to_random_position(player, length_s)
            last_jump_time = now

        current, prev_counts = analyzer.detect_current_song(args.playlist, prev_counts, last_known_song)
        last_known_song = current

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
