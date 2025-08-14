# RekordboxPlaylistAnalyzer.py
"""
RekordboxPlaylistAnalyzer
--------------------------

Encapsulates all of your Rekordbox DB logic:
  • Fetching & sorting playlist songs by track number
  • Seeding + detecting changes in DJPlayCount
  • Converting Rekordbox’s integer BPM → float BPM
  • Computing a “base” BPM (first track or average)
  • Computing a BPM multiplier

This is meant to be imported; you do not run this directly.
"""

from pyrekordbox import Rekordbox6Database
from pyrekordbox.db6.tables import DjmdPlaylist, DjmdCue
from typing import List, Dict, Optional
from typing import Dict, Tuple
import os
import importlib
import platform

class RekordboxPlaylistAnalyzer:
    def __init__(self):
        self.db = Rekordbox6Database()
        self.playlists: Dict[str, DjmdPlaylist] = {
            pl.Name: pl for pl in self.db.get_playlist()
        }

    @staticmethod
    def load_vlc_module():
        """
        Load python-vlc against the VLC install whose bitness matches our Python.
        Provides a clear error if bitness mismatch is likely.
        """
        import ctypes
        is_64_python = platform.architecture()[0] == "64bit"
        candidates = (
            [r"C:\Program Files\VideoLAN\VLC", r"C:\Program Files (x86)\VideoLAN\VLC"]
            if is_64_python
            else
            [r"C:\Program Files (x86)\VideoLAN\VLC", r"C:\Program Files\VideoLAN\VLC"]
        )

        latest_error = None
        for vlc_dir in candidates:
            if not os.path.isdir(vlc_dir):
                continue

            # Try to check the architecture of libvlc.dll using Windows API
            libvlc_path = os.path.join(vlc_dir, "libvlc.dll")
            if os.path.exists(libvlc_path):
                try:
                    # Read PE header to determine 32-bit or 64-bit
                    with open(libvlc_path, 'rb') as f:
                        f.seek(0x3C)
                        pe_offset = int.from_bytes(f.read(4), 'little')
                        f.seek(pe_offset + 4)
                        machine_type = int.from_bytes(f.read(2), 'little')
                        if is_64_python and machine_type != 0x8664:
                            raise RuntimeError(f"VLC at '{vlc_dir}' is 32-bit, but you're using 64-bit Python.")
                        if not is_64_python and machine_type != 0x14c:
                            raise RuntimeError(f"VLC at '{vlc_dir}' is 64-bit, but you're using 32-bit Python.")
                except Exception as e:
                    latest_error = e
                    continue

            # 1) register the install directory for DLL resolution
            handle = os.add_dll_directory(vlc_dir)
            os.environ["VLC_PLUGIN_PATH"] = os.path.join(vlc_dir, "plugins")
            orig_cwd = os.getcwd()
            os.chdir(vlc_dir)

            try:
                vlc = importlib.import_module("vlc")
                return vlc
            except OSError as e:
                latest_error = e
                handle.close()
            finally:
                os.chdir(orig_cwd)

        msg = (
                "Could not load libvlc from any of:\n  "
                + "\n  ".join(candidates)
        )
        if latest_error:
            msg += f"\nLatest error: {latest_error}"
        raise FileNotFoundError(msg)

    @staticmethod
    def rekordbox_bpm_to_bpm(rekordbox_bpm: int) -> float:
        """Convert Rekordbox’s integer BPM (e.g. 12900) to a float (129.00)."""
        return rekordbox_bpm / 100.0 if rekordbox_bpm else 0.0

    def get_playlist_songs_by_trackno(self, name: str):
        """
        Return songs sorted by TrackNo;
        raises ValueError if the named playlist doesn’t exist.
        """
        playlist = self.playlists.get(name)
        if playlist is None:
            raise ValueError(f"Playlist '{name}' not found.")
        return sorted(playlist.Songs, key=lambda s: s.TrackNo)

    def init_play_counts(self, playlist: str) -> Dict[int, int]:
        """
        Build initial map: Content.ID → DJPlayCount
        for seeding a monitoring loop.
        """
        songs = self.get_playlist_songs_by_trackno(playlist)
        return {song.Content.ID: song.Content.DJPlayCount for song in songs}

    def refresh(self):
        self.db = Rekordbox6Database()
        self.playlists = {
            pl.Name: pl for pl in self.db.get_playlist()
        }

    def detect_current_song(
            self,
            playlist: str,
            previous_counts: Dict[int, int],
            last_known_song: object = None
    ) -> Tuple[object, Dict[int, int]]:
        """
        Return (current_song, updated_counts).
        If a DJPlayCount incremented, use that song.
        If none changed:
          - Return last_known_song if available.
          - Else, return the first song in the playlist.
        """
        self.refresh()
        songs = self.get_playlist_songs_by_trackno(playlist)
        new_counts = {}
        current = None

        for song in songs:
            cid = song.Content.ID
            curr = song.Content.DJPlayCount
            prev = previous_counts.get(cid, curr)
            new_counts[cid] = curr
            if curr > prev:
                current = song

        if current:
            return current, new_counts
        elif last_known_song:
            return last_known_song, new_counts
        else:
            return songs[0], new_counts

    def get_base_bpm(self, playlist: str, average: bool=False) -> float:
        """
        Base BPM = first track’s BPM by default;
        if average=True, returns the mean BPM across all songs.
        """
        songs = self.get_playlist_songs_by_trackno(playlist)
        bpms = [self.rekordbox_bpm_to_bpm(s.Content.BPM) for s in songs]
        if not bpms:
            return 0.0
        return sum(bpms)/len(bpms) if average else bpms[0]

    @staticmethod
    def get_bpm_multiplier(current_bpm: float, base_bpm: float) -> float:
        """Return current_bpm / base_bpm, or 1.0 if base_bpm is zero."""
        return current_bpm / base_bpm if base_bpm else 1.0

    def format_duration(self, ms: int) -> str:
        minutes = ms // 60000
        seconds = (ms % 60000) // 1000
        return f"{minutes}m {seconds}s"

    def analyze_playlist(
            self,
            playlist_name: str,
            *,
            max_songs: Optional[int] = None,
    ) -> str:
        playlist = self.playlists.get(playlist_name)
        if playlist is None:
            return f"Playlist '{playlist_name}' not found."

        all_songs = sorted(playlist.Songs, key=lambda s: s.TrackNo)
        if max_songs is not None and max_songs > 0:
            all_songs = all_songs[:max_songs]

        output_lines = []
        output_lines.append(f"Playlist '{playlist_name}' contains {len(playlist.Songs)} songs.")
        output_lines.append(f"Analyzing first {len(all_songs)} songs...\n")

        total_duration_ms = 0
        total_adjusted_duration_ms = 0
        skipped = 0
        prev_bpm = None

        for song in all_songs:
            content = song.Content
            hot_cues: List[DjmdCue] = [cue for cue in content.Cues if not cue.is_memory_cue]

            if len(hot_cues) < 4:
                output_lines.append(f"Skipping '{content.Title}': only {len(hot_cues)} hot cues.")
                skipped += 1
                continue

            hot_cues.sort(key=lambda c: c.InMsec)
            distances = [
                hot_cues[i + 1].InMsec - hot_cues[i].InMsec
                for i in range(len(hot_cues) - 1)
            ]
            if len(distances) < 2:
                output_lines.append(f"Skipping '{content.Title}': not enough distances.")
                skipped += 1
                continue

            distances.sort(reverse=True)
            max_duration = distances[0] + distances[1]
            duration_str = self.format_duration(max_duration)

            current_bpm = self.rekordbox_bpm_to_bpm(content.BPM)
            bpm_info = f"BPM {current_bpm:.2f}"
            adjusted_duration = max_duration

            output_lines.append(
                f"#{song.TrackNo:03d} – '{content.Title}': {max_duration} ms ({duration_str}); "
                f"{bpm_info}, Key {content.Key.ScaleName}; Plays {content.DJPlayCount}"
            )

            if prev_bpm is not None:
                bpm_diff = current_bpm - prev_bpm
                tempo_shift = -bpm_diff / 2  # slow down or speed up by half the difference
                adjusted_bpm = current_bpm + tempo_shift
                ratio = current_bpm / adjusted_bpm if adjusted_bpm != 0 else 1
                adjusted_duration = int(max_duration * ratio)

                output_lines.append(
                    f"  * Adjusting tempo from {current_bpm:.2f} to {adjusted_bpm:.2f} BPM "
                    f"to meet halfway to previous BPM ({prev_bpm:.2f})"
                )
                output_lines.append(
                    f"  * Estimated adjusted playtime: {adjusted_duration} ms "
                    f"({self.format_duration(adjusted_duration)})"
                )
            else:
                output_lines.append("  ⮩ No previous BPM to compare for tempo adjustment.")

            prev_bpm = current_bpm
            total_duration_ms += max_duration
            total_adjusted_duration_ms += adjusted_duration

        output_lines.append("\n=== Total Set Duration ===")
        output_lines.append(f"Original: {total_duration_ms} ms ({self.format_duration(total_duration_ms)})")
        output_lines.append(f"Adjusted (half BPM diff per song): {total_adjusted_duration_ms} ms "
                            f"({self.format_duration(total_adjusted_duration_ms)})")
        output_lines.append(f"{len(output_lines) - 5} songs processed, {skipped} skipped.")

        return "\n".join(output_lines)

