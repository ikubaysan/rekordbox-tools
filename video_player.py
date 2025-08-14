# simple_video_player.py
# ----------------------
# Play an MP4 video at a fixed playback rate, optionally jumping to a random position every X seconds.
#
# Usage:
#   python simple_video_player.py --video "C:/path/to/video.mp4" --rate 1.25 [--jump-interval 30]

import argparse
import random
import time
from datetime import datetime
import vlc


def jump_to_random_position(player, length_s: float):
    """Jump to a random position in the video."""
    if length_s > 0:
        new_pos = random.uniform(0, length_s)
        player.set_time(int(new_pos * 1000))
        print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] Jumping to {new_pos:.1f}s of {length_s:.1f}s")


def main():
    parser = argparse.ArgumentParser(description="Play a video at a fixed rate with optional random jumps.")
    parser.add_argument("--video", required=True, help="Path to the MP4 video file")
    parser.add_argument("--rate", type=float, default=1.0, help="Playback rate (default: 1.0)")
    parser.add_argument("--jump-interval", type=int, default=None,
                        help="If set, jump to a random part of the video every X seconds")
    args = parser.parse_args()

    if args.rate <= 0:
        raise ValueError("Playback rate must be greater than 0.")

    print("\n--- Script Configuration ---")
    for key, value in vars(args).items():
        print(f"{key}: {value}")
    print("----------------------------\n")

    # Set up VLC player
    instance = vlc.Instance('--vout=opengl')
    player = instance.media_player_new()
    media = instance.media_new(str(args.video))
    media.add_option("input-repeat=999999")  # Loop indefinitely
    player.set_media(media)
    player.play()

    # Give VLC time to start
    time.sleep(0.5)

    length_ms = player.get_length()
    length_s = length_ms / 1000.0 if length_ms > 0 else 0.0

    # Apply playback rate
    player.set_rate(args.rate)
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] Playback rate set to {args.rate:.2f}x")

    last_jump_time = time.time()

    # Main loop
    while True:
        time.sleep(0.5)
        now = time.time()

        if args.jump_interval and (now - last_jump_time >= args.jump_interval):
            jump_to_random_position(player, length_s)
            last_jump_time = now


if __name__ == "__main__":
    main()
