#!/usr/bin/env python
# ---------------------------------------------------------------------------
# Convert all tracks from a Rekordbox playlist to either:
#   - Uncompressed AIFF (24-bit, default), or
#   - MP3 320kbps CBR.
#
# Usage:
#   python convert_playlist_audio.py --playlist "My Playlist"
#   python convert_playlist_audio.py --playlist "My Playlist" --format mp3
#
# Output:
#   Creates "<playlist>_<fmt>" next to this script, where <fmt> is "aiff" or
#   "mp3_320". Filenames are "<original_stem>_<fmt>.<ext>".
#   Title tag is suffixed with " (AIFF)" or " (320 mp3)".
#   Artwork is copied from the source (MP3 ID3 APIC, M4A/MP4 covr, FLAC picture).
# ---------------------------------------------------------------------------

import argparse
import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional, Iterable, Tuple

from RekordboxPlaylistAnalyzer import RekordboxPlaylistAnalyzer

# --- Artwork/metadata helpers (mutagen) ---
from mutagen import File as MutagenFile
from mutagen.id3 import ID3, APIC, TIT2, ID3NoHeaderError, PIC
from mutagen.flac import FLAC
from mutagen.mp4 import MP4, MP4Cover
from mutagen.aiff import AIFF

AUDIO_EXTS = {
    ".mp3", ".wav", ".aiff", ".aif", ".flac", ".m4a", ".alac", ".aac", ".ogg", ".wma"
}

def ensure_ffmpeg() -> str:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg not found in PATH. Install ffmpeg and/or add it to PATH.")
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
            v = v[8:]
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
    """If base_path exists, append (2), (3), ... before suffix."""
    if not base_path.exists():
        return base_path
    stem, suffix = base_path.stem, base_path.suffix
    i = 2
    while True:
        candidate = base_path.with_name(f"{stem} ({i}){suffix}")
        if not candidate.exists():
            return candidate
        i += 1

# ------------------ Artwork extraction / embedding ------------------

def _get_cover_from_src(src_path: Path) -> Optional[Tuple[bytes, str]]:
    """
    Returns (image_bytes, mime) if artwork is found in src, else None.
    Handles MP3(ID3 APIC/PIC), MP4/M4A (covr), and FLAC pictures.
    """
    audio = MutagenFile(src_path)
    if audio is None:
        return None

    # MP3 (ID3)
    if hasattr(audio, "tags") and isinstance(audio.tags, ID3):
        # Prefer APIC (ID3v2.3/2.4), fallback to PIC (ID3v2.2)
        apics = audio.tags.getall("APIC")
        if apics:
            apic = apics[0]
            if getattr(apic, "data", None):
                mime = apic.mime or "image/jpeg"
                return bytes(apic.data), mime
        pics = audio.tags.getall("PIC")
        if pics:
            pic = pics[0]
            if getattr(pic, "data", None):
                # PIC may not have a canonical mime; assume JPEG if unspecified
                mime = getattr(pic, "mime", None) or "image/jpeg"
                return bytes(pic.data), mime

    # MP4/M4A
    if isinstance(audio, MP4):
        covr = audio.tags.get("covr")
        if covr:
            cov = covr[0]
            if isinstance(cov, MP4Cover):
                if cov.imageformat == MP4Cover.FORMAT_PNG:
                    return bytes(cov), "image/png"
                else:
                    return bytes(cov), "image/jpeg"

    # FLAC
    if isinstance(audio, FLAC) and audio.pictures:
        pic = audio.pictures[0]
        if getattr(pic, "data", None):
            mime = pic.mime or "image/jpeg"
            return bytes(pic.data), mime

    return None

def _embed_cover_and_title_mp3(dst_path: Path, title: Optional[str], cover: Optional[Tuple[bytes, str]]) -> None:
    """Ensure ID3v2.3 on MP3, write Title and APIC cover."""
    try:
        tags = ID3(dst_path)
    except ID3NoHeaderError:
        tags = ID3()

    if title:
        tags.setall("TIT2", [TIT2(encoding=3, text=title)])

    if cover:
        img_bytes, mime = cover
        tags.setall("APIC", [APIC(encoding=3, mime=mime, type=3, desc="Cover", data=img_bytes)])

    tags.save(dst_path, v2_version=3)

def _embed_cover_and_title_aiff(dst_path: Path, title: Optional[str], cover: Optional[Tuple[bytes, str]]) -> None:
    """
    Use mutagen.aiff.AIFF to attach/create an ID3 chunk and write Title + APIC.
    This keeps the AIFF container's chunk sizes/ordering valid.
    """
    aiff = AIFF(dst_path)
    if aiff.tags is None:
        aiff.add_tags()  # creates an empty ID3 tag chunk

    id3 = aiff.tags
    if title:
        id3.setall("TIT2", [TIT2(encoding=3, text=title)])

    if cover:
        img_bytes, mime = cover
        id3.setall("APIC", [APIC(encoding=3, mime=mime, type=3, desc="Cover", data=img_bytes)])

    aiff.save(v2_version=3)

# ------------------ ffmpeg converters ------------------

def convert_to_mp3_320(ffmpeg: str, src: Path, dst: Path, title_for_tag: Optional[str]) -> int:
    """
    Convert src to MP3 320kbps CBR at dst.
    (We still write title via ffmpeg, and later enforce via mutagen as well.)
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg,
        "-hide_banner", "-nostdin",
        "-loglevel", "error",
        "-y",
        "-i", str(src),
        "-vn",
        "-c:a", "libmp3lame",
        "-b:a", "320k",
        "-map_metadata", "0",
        "-id3v2_version", "3",
    ]
    if title_for_tag:
        cmd += ["-metadata", f"title={title_for_tag}"]
    cmd += [str(dst)]

    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    proc = subprocess.run(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", creationflags=creationflags
    )
    if proc.returncode != 0:
        print(f"[ffmpeg error] converting '{src}':\n{proc.stdout}")
    return proc.returncode

def convert_to_aiff_pcm_24bit(ffmpeg: str, src: Path, dst: Path, title_for_tag: Optional[str]) -> int:
    """
    Convert src to uncompressed AIFF at 24-bit PCM (pcm_s24be) at dst.
    IMPORTANT: we do NOT ask ffmpeg to write ID3 here; mutagen will handle it.
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg,
        "-hide_banner", "-nostdin",
        "-loglevel", "error",
        "-y",
        "-i", str(src),
        "-vn",
        "-c:a", "pcm_s24be",     # always 24-bit big-endian
        "-map_metadata", "0",    # copy non-image source tags to the container (safe)
        # No -write_id3v2 here; mutagen writes the ID3 chunk cleanly afterwards.
    ]
    if title_for_tag:
        cmd += ["-metadata", f"title={title_for_tag}"]
    cmd += [str(dst)]

    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    proc = subprocess.run(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", creationflags=creationflags
    )
    if proc.returncode != 0:
        print(f"[ffmpeg error] converting '{src}':\n{proc.stdout}")
    return proc.returncode

# ------------------ Main ------------------

def main():
    parser = argparse.ArgumentParser(description="Convert Rekordbox playlist tracks to AIFF (24-bit) or MP3 320kbps.")
    parser.add_argument("--playlist", required=True, help="Rekordbox playlist name")
    parser.add_argument(
        "--format",
        choices=["aiff", "mp3"],
        default="aiff",
        help="Output audio format. 'aiff' (24-bit uncompressed) or 'mp3' (320kbps CBR). Default: aiff",
    )
    args = parser.parse_args()

    ffmpeg = ensure_ffmpeg()

    analyzer = RekordboxPlaylistAnalyzer()
    try:
        songs = analyzer.get_playlist_songs_by_trackno(args.playlist)
    except ValueError as e:
        print(e)
        return

    # Output directory in the same folder as this script
    script_dir = Path(__file__).resolve().parent
    fmt_suffix = "aiff" if args.format == "aiff" else "mp3_320"
    out_dir = script_dir / f"{args.playlist}_{fmt_suffix}"
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

        # Destination filename / extension and Title suffix
        if args.format == "aiff":
            dst_name = f"{src.stem}_aiff.aiff"
            transcoded_title = f"{title} (AIFF)"
        else:
            dst_name = f"{src.stem}_mp3_320.mp3"
            transcoded_title = f"{title} (320 mp3)"

        dst = unique_with_counter(out_dir / dst_name)

        print(f"[convert] Track #{song.TrackNo}: '{title}'")
        print(f"    src: {src}")
        print(f"    dst: {dst}")

        if args.format == "aiff":
            rc = convert_to_aiff_pcm_24bit(ffmpeg, src, dst, transcoded_title)
        else:
            rc = convert_to_mp3_320(ffmpeg, src, dst, transcoded_title)

        if rc == 0:
            # After conversion, embed artwork (and title again) for reliability
            cover = _get_cover_from_src(src)
            try:
                if args.format == "aiff":
                    _embed_cover_and_title_aiff(dst, transcoded_title, cover)
                else:
                    _embed_cover_and_title_mp3(dst, transcoded_title, cover)
            except Exception as e:
                print(f"[warn] Could not embed artwork on '{dst.name}': {e}")
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
