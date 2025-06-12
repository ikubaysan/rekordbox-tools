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
from pyrekordbox.db6.tables import DjmdPlaylist
from typing import Dict, Tuple

class RekordboxPlaylistAnalyzer:
    def __init__(self):
        self.db = Rekordbox6Database()
        self.playlists: Dict[str, DjmdPlaylist] = {
            pl.Name: pl for pl in self.db.get_playlist()
        }

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

    def detect_current_song(
        self,
        playlist: str,
        previous_counts: Dict[int, int]
    ) -> Tuple[object, Dict[int, int]]:
        """
        Compare current DJPlayCount vs. previous_counts,
        return (current_song, new_counts_map).
        If none incremented, returns the first track.
        """
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

        return (current if current else songs[0], new_counts)

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
