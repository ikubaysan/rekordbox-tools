# simple_video_player.py
# ----------------------
# Play an MP4 video at a fixed playback rate, optionally:
#   - jumping to a random position every X seconds
#   - oscillating hue back and forth every X seconds (OBS-style -180..180)
#
# Usage:
#   python simple_video_player.py --video "C:/path/to/video.mp4" --rate 1.25 \
#       --jump-interval 30 --hue-interval 5
#
# Disable hue oscillation:
#   python simple_video_player.py --video "..." --no-hue-oscillate
#
# Customize hue endpoints (OBS scale):
#   --hue-min -120 --hue-max 120

import argparse
import random
import time
from datetime import datetime
import vlc


def obs_to_vlc_hue(obs_deg: int) -> int:
    """Map OBS hue (-180..180) to VLC hue (0..360)."""
    return int((obs_deg + 360) % 360)


def set_vlc_hue(player: vlc.MediaPlayer, obs_deg: int):
    """Enable adjust filter (if not already) and set hue."""
    player.video_set_adjust_int(vlc.VideoAdjustOption.Enable, 1)
    player.video_set_adjust_int(vlc.VideoAdjustOption.Hue, obs_to_vlc_hue(obs_deg))


def jump_to_random_position(player, length_s: float):
    """Jump to a random position in the video."""
    if length_s > 0:
        new_pos = random.uniform(0, length_s)
        player.set_time(int(new_pos * 1000))
        print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] Jumping to {new_pos:.1f}s of {length_s:.1f}s")


def main():
    parser = argparse.ArgumentParser(description="Play a video at a fixed rate with optional effects.")
    parser.add_argument("--video", required=True, help="Path to the MP4 video file")
    parser.add_argument("--rate", type=float, default=1.0, help="Playback rate (default: 1.0)")
    parser.add_argument("--jump-interval", type=int, default=None,
                        help="If set, jump to a random part of the video every X seconds")

    # Hue oscillation controls (enabled by default)
    hue_group = parser.add_mutually_exclusive_group()
    hue_group.add_argument("--hue-oscillate", dest="hue_oscillate", action="store_true",
                           help="Enable hue oscillation (default)")
    hue_group.add_argument("--no-hue-oscillate", dest="hue_oscillate", action="store_false",
                           help="Disable hue oscillation")
    parser.set_defaults(hue_oscillate=True)

    parser.add_argument("--hue-interval", type=float, default=5.0,
                        help="Seconds between hue flips (default: 5.0)")
    parser.add_argument("--hue-min", type=int, default=-180,
                        help="Minimum hue (OBS scale, default: -180)")
    parser.add_argument("--hue-max", type=int, default=180,
                        help="Maximum hue (OBS scale, default: 180)")

    args = parser.parse_args()

    if args.rate <= 0:
        raise ValueError("Playback rate must be greater than 0.")
    if args.hue_min < -180 or args.hue_max > 180 or args.hue_min >= args.hue_max:
        raise ValueError("Hue bounds must satisfy -180 <= hue_min < hue_max <= 180.")

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
    length_s = length_ms / 1000.0 if length_ms and length_ms > 0 else 0.0

    # Apply playback rate
    player.set_rate(args.rate)
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] Playback rate set to {args.rate:.2f}x")

    # Initialize hue oscillation
    next_hue = args.hue_min
    direction = +1  # +1 means next flip goes to hue_max; -1 goes to hue_min
    if args.hue_oscillate:
        # Enable adjust and set initial hue
        set_vlc_hue(player, next_hue)
        print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] Hue set to {next_hue}° (OBS scale)")
    last_hue_flip = time.time()

    last_jump_time = time.time()

    # Main loop
    while True:
        time.sleep(0.1)
        now = time.time()

        # Random jump logic
        if args.jump_interval and (now - last_jump_time >= args.jump_interval):
            jump_to_random_position(player, length_s)
            last_jump_time = now

        # Hue oscillation logic
        if args.hue_oscillate and (now - last_hue_flip >= args.hue_interval):
            # Flip to the other endpoint
            if direction > 0:
                next_hue = args.hue_max
            else:
                next_hue = args.hue_min

            set_vlc_hue(player, next_hue)
            print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] Hue set to {next_hue}° (OBS scale)")
            direction *= -1
            last_hue_flip = now


if __name__ == "__main__":
    main()
