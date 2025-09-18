#!/usr/bin/env python
# ---------------------------------------------------------------------------
# Convert all tracks from a Rekordbox playlist to MP3 320kbps.
#
# Usage:
#   python convert_playlist_to_mp3_320.py --playlist "My Playlist"
#   python convert_playlist_to_mp3_320.py --playlist "My Playlist" -n 25
#
# Output:
#   Creates a folder "<playlist>_mp3_320" next to this script.
#   Each output file is named "<original_stem>_mp3_320.mp3".
# ---------------------------------------------------------------------------

import argparse
import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional, Iterable, Tuple

from RekordboxPlaylistAnalyzer import RekordboxPlaylistAnalyzer

AUDIO_EXTS = {
    ".mp3", ".wav", ".aiff", ".aif", ".flac", ".m4a", ".alac", ".aac", ".ogg", ".wma"
}

def ensure_ffmpeg() -> str:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError(
            "ffmpeg not found in PATH. Install ffmpeg and/or add it to PATH."
        )
    return ffmpeg

def _is_audio_path(p: str) -> bool:
    try:
        ext = Path(p).suffix.lower()
    except Exception:
        return False
    return ext in AUDIO_EXTS

def _join_if_all(*parts: Optional[str]) -> Optional[str]:
    parts_ok = [p for p in parts if isinstance(p, str) and p.strip()]
    if len(parts_ok) != len(parts):
        return None
    return os.path.normpath(os.path.join(*parts_ok))

def _candidate_strings_from_obj(obj) -> Iterable[Tuple[str, str]]:
    preferred_attrs = [
        "FilePath", "FileFullPath", "FileLPath", "Location", "OrigFilePath",
        "AbsolutePath", "Path", "FullPath", "URL"
    ]
    seen = set()
    for name in preferred_attrs:
        if hasattr(obj, name):
            val = getattr(obj, name)
            if isinstance(val, str) and (os.sep in val or _is_audio_path(val)):
                seen.add(name)
                yield name, val
    for name in dir(obj):
        if name in seen or name.startswith("_"):
            continue
        try:
            val = getattr(obj, name)
        except Exception:
            continue
        if isinstance(val, str) and (os.sep in val or _is_audio_path(val)):
            yield name, val

def guess_content_file_path(content) -> Optional[str]:
    best_nonexistent: Optional[str] = None

    def _normalize(val: str) -> str:
        v = val
        if v.lower().startswith("file:///"):
            v = v[8:]  # keep leading slash; fix Windows /C:/... below
            if os.name == "nt" and v.startswith("/") and len(v) > 3 and v[2] == ":":
                v = v[1:]
        return os.path.normpath(v)

    for _, val in _candidate_strings_from_obj(content):
        path = _normalize(val)
        if _is_audio_path(path):
            if os.path.isfile(path):
                return path
            if best_nonexistent is None:
                best_nonexistent = path

    dir_like_names = ["Dir", "Directory", "Folder", "FileDir", "DirPath"]
    file_like_names = ["FileName", "Filename", "Name", "TitleFile"]
    dir_val = next((getattr(content, n) for n in dir_like_names if hasattr(content, n)), None)
    file_val = next((getattr(content, n) for n in file_like_names if hasattr(content, n)), None)
    joined = _join_if_all(dir_val, file_val)
    if joined and _is_audio_path(joined):
        if os.path.isfile(joined):
            return os.path.normpath(joined)
        if best_nonexistent is None:
            best_nonexistent = os.path.normpath(joined)

    child = getattr(content, "File", None)
    if child is not None:
        for _, val in _candidate_strings_from_obj(child):
            path = _normalize(val)
            if _is_audio_path(path):
                if os.path.isfile(path):
                    return path
                if best_nonexistent is None:
                    best_nonexistent = path

        dir_val = next((getattr(child, n) for n in dir_like_names if hasattr(child, n)), None)
        file_val = next((getattr(child, n) for n in file_like_names if hasattr(child, n)), None)
        joined = _join_if_all(dir_val, file_val)
        if joined and _is_audio_path(joined):
            if os.path.isfile(joined):
                return os.path.normpath(joined)
            if best_nonexistent is None:
                best_nonexistent = os.path.normpath(joined)

    return best_nonexistent

def unique_with_counter(base_path: Path) -> Path:
    """
    If base_path exists, append (2), (3), ... before suffix.
    """
    if not base_path.exists():
        return base_path
    stem, suffix = base_path.stem, base_path.suffix
    i = 2
    while True:
        candidate = base_path.with_name(f"{stem} ({i}){suffix}")
        if not candidate.exists():
            return candidate
        i += 1

def convert_to_mp3_320(ffmpeg: str, src: Path, dst: Path) -> int:
    """
    Convert src to MP3 320kbps CBR at dst.
    Returns ffmpeg returncode (0 on success).
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg,
        "-hide_banner", "-nostdin",
        "-loglevel", "error",     # only show errors (keeps output small/clean)
        "-y",
        "-i", str(src),
        "-vn",
        "-c:a", "libmp3lame",
        "-b:a", "320k",
        "-map_metadata", "0",
        "-id3v2_version", "3",
        str(dst),
    ]
    # On Windows, ffmpeg may emit non-cp1252 bytes; force UTF-8 and replace if needed
    creationflags = 0
    if os.name == "nt":
        # Prevents stray console windows when running from an IDE
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    proc = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=creationflags,
    )
    if proc.returncode != 0:
        print(f"[ffmpeg error] converting '{src}':\n{proc.stdout}")
    return proc.returncode


def main():
    parser = argparse.ArgumentParser(description="Convert Rekordbox playlist tracks to MP3 320kbps.")
    parser.add_argument("--playlist", required=True, help="Rekordbox playlist name")
    parser.add_argument("-n", "--max-songs", type=int, metavar="N",
                        help="Only process the first N tracks (by TrackNo)")
    args = parser.parse_args()

    ffmpeg = ensure_ffmpeg()

    analyzer = RekordboxPlaylistAnalyzer()
    try:
        songs = analyzer.get_playlist_songs_by_trackno(args.playlist)
    except ValueError as e:
        print(e)
        return

    if args.max_songs and args.max_songs > 0:
        songs = songs[:args.max_songs]

    # Output directory in the same folder as this script
    script_dir = Path(__file__).resolve().parent
    out_dir = script_dir / f"{args.playlist}_mp3_320"
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"Output folder: {out_dir}")

    converted = 0
    skipped = 0
    failures = 0

    for song in songs:
        content = song.Content
        src_path_str = guess_content_file_path(content)
        title = getattr(content, "Title", "(unknown title)")
        if not src_path_str or not os.path.isfile(src_path_str):
            print(f"[skip] Track #{song.TrackNo}: '{title}' – source path not found or missing on disk.")
            skipped += 1
            continue

        src = Path(src_path_str)
        # Destination filename: <stem>_mp3_320.mp3
        dst_name = f"{src.stem}_mp3_320.mp3"
        dst = out_dir / dst_name
        dst = unique_with_counter(dst)  # avoid collisions

        print(f"[convert] Track #{song.TrackNo}: '{title}'")
        print(f"    src: {src}")
        print(f"    dst: {dst}")

        rc = convert_to_mp3_320(ffmpeg, src, dst)
        if rc == 0:
            converted += 1
        else:
            failures += 1

    print("\n=== Summary ===")
    print(f"Converted: {converted}")
    print(f"Skipped (no source): {skipped}")
    print(f"Failures: {failures}")
    print(f"Output: {out_dir}")

if __name__ == "__main__":
    main()
