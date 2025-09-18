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
#   Artwork and common metadata are copied from the source.
# ---------------------------------------------------------------------------

import argparse
import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional, Iterable, Tuple, Dict, Any

from RekordboxPlaylistAnalyzer import RekordboxPlaylistAnalyzer

# --- Artwork/metadata helpers (mutagen) ---
from mutagen import File as MutagenFile
from mutagen.id3 import (
    ID3, APIC, TIT2, TALB, TPE1, TPE2, TCON, TYER, TRCK, TPOS, COMM, TCOM,
    ID3NoHeaderError, PIC
)
from mutagen.flac import FLAC
from mutagen.mp4 import MP4, MP4Cover
from mutagen.aiff import AIFF
import time

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

# ------------------ Artwork extraction ------------------

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

# ------------------ Common metadata extraction ------------------

def _get_text(v: Any) -> Optional[str]:
    if v is None:
        return None
    if isinstance(v, (list, tuple)):
        if not v:
            return None
        v = v[0]
    try:
        s = str(v).strip()
        return s or None
    except Exception:
        return None

def _read_common_tags(src: Path) -> Dict[str, Optional[str]]:
    """
    Return a dict of common tags from the source file:
      album, artist, albumartist, date(year), track, track_total, disc, disc_total, genre, comment, composer
    """
    info = {
        "album": None,
        "artist": None,
        "albumartist": None,
        "date": None,           # 'YYYY' preferred
        "track": None,          # e.g. "5" or "5/12"
        "disc": None,           # e.g. "1" or "1/2"
        "genre": None,
        "comment": None,
        "composer": None,
    }

    audio = MutagenFile(src, easy=False)
    if audio is None:
        return info

    # MP3/ID3
    if isinstance(audio.tags, ID3):
        tags = audio.tags
        info["album"] = _get_text(tags.get("TALB"))
        info["artist"] = _get_text(tags.get("TPE1"))
        info["albumartist"] = _get_text(tags.get("TPE2"))  # often used as album artist
        # Year: in v2.3 it's TYER
        year = _get_text(tags.get("TYER"))
        info["date"] = year
        info["genre"] = _get_text(tags.get("TCON"))
        # Track and disc numbers
        trck = _get_text(tags.get("TRCK"))
        tpos = _get_text(tags.get("TPOS"))
        info["track"] = trck
        info["disc"] = tpos
        # Comment (take the first COMM)
        comms = tags.getall("COMM")
        if comms:
            info["comment"] = _get_text(comms[0].text if hasattr(comms[0], "text") else None)
        info["composer"] = _get_text(tags.get("TCOM"))
        return info

    # MP4/M4A
    if isinstance(audio, MP4):
        tags = audio.tags or {}
        info["album"] = _get_text(tags.get("\xa9alb"))
        info["artist"] = _get_text(tags.get("\xa9ART"))
        info["albumartist"] = _get_text(tags.get("aART"))
        # Prefer YYYY from ©day
        day = _get_text(tags.get("\xa9day"))
        if day and len(day) >= 4 and day[:4].isdigit():
            info["date"] = day[:4]
        # Track/disc are tuples like [(num, total)]
        trkn = tags.get("trkn")
        if trkn and isinstance(trkn, list) and trkn[0]:
            n, total = trkn[0][0], trkn[0][1]
            if n:
                info["track"] = f"{n}/{total}" if total else f"{n}"
        disk = tags.get("disk")
        if disk and isinstance(disk, list) and disk[0]:
            n, total = disk[0][0], disk[0][1]
            if n:
                info["disc"] = f"{n}/{total}" if total else f"{n}"
        info["genre"] = _get_text(tags.get("\xa9gen"))
        info["comment"] = _get_text(tags.get("\xa9cmt"))
        info["composer"] = _get_text(tags.get("\xa9wrt"))
        return info

    # FLAC/Vorbis
    if isinstance(audio, FLAC):
        tags = audio.tags or {}
        def g(key): return _get_text(tags.get(key))
        info["album"] = g("album")
        info["artist"] = g("artist")
        info["albumartist"] = g("albumartist")
        date = g("date") or g("year")
        if date and len(date) >= 4 and date[:4].isdigit():
            info["date"] = date[:4]
        # Track/disc
        tn = g("tracknumber")
        tt = g("tracktotal") or g("totaltracks")
        if tn:
            info["track"] = f"{tn}/{tt}" if tt else tn
        dn = g("discnumber")
        dt = g("disctotal") or g("totaldiscs")
        if dn:
            info["disc"] = f"{dn}/{dt}" if dt else dn
        info["genre"] = g("genre")
        info["comment"] = g("comment")
        info["composer"] = g("composer")
        return info

    # Fallback for others via Easy tags if possible
    easy = MutagenFile(src, easy=True)
    if easy and easy.tags:
        et = easy.tags
        def eg(k): return _get_text(et.get(k))
        info["album"] = eg("album")
        info["artist"] = eg("artist")
        info["albumartist"] = eg("albumartist")
        date = eg("date") or eg("year")
        if date and len(date) >= 4 and date[:4].isdigit():
            info["date"] = date[:4]
        tn = eg("tracknumber")
        tt = eg("tracktotal")
        if tn:
            info["track"] = f"{tn}/{tt}" if tt else tn
        dn = eg("discnumber")
        dt = eg("disctotal")
        if dn:
            info["disc"] = f"{dn}/{dt}" if dt else dn
        info["genre"] = eg("genre")
        info["comment"] = eg("comment")
        info["composer"] = eg("composer")
    return info

# ------------------ ID3 writing helpers ------------------

def _apply_common_id3_frames(id3_obj: ID3, common: Dict[str, Optional[str]], title: Optional[str], cover: Optional[Tuple[bytes, str]]):
    # Title
    if title:
        id3_obj.setall("TIT2", [TIT2(encoding=3, text=title)])

    # Common text frames
    if common.get("album"):
        id3_obj.setall("TALB", [TALB(encoding=3, text=common["album"])])
    if common.get("artist"):
        id3_obj.setall("TPE1", [TPE1(encoding=3, text=common["artist"])])
    if common.get("albumartist"):
        id3_obj.setall("TPE2", [TPE2(encoding=3, text=common["albumartist"])])
    if common.get("genre"):
        id3_obj.setall("TCON", [TCON(encoding=3, text=common["genre"])])
    if common.get("composer"):
        id3_obj.setall("TCOM", [TCOM(encoding=3, text=common["composer"])])

    # Year (ID3v2.3: TYER)
    if common.get("date"):
        id3_obj.setall("TYER", [TYER(encoding=3, text=common["date"])])

    # Track / Disc numbers (text like "5/12")
    if common.get("track"):
        id3_obj.setall("TRCK", [TRCK(encoding=3, text=common["track"])])
    if common.get("disc"):
        id3_obj.setall("TPOS", [TPOS(encoding=3, text=common["disc"])])

    # Comment (use lang 'eng', desc empty)
    if common.get("comment"):
        id3_obj.setall("COMM", [COMM(encoding=3, lang="eng", desc="", text=common["comment"])])

    # Cover art
    if cover:
        img_bytes, mime = cover
        id3_obj.setall("APIC", [APIC(encoding=3, mime=mime, type=3, desc="Cover", data=img_bytes)])

def _embed_all_mp3(dst_path: Path, title: Optional[str], cover: Optional[Tuple[bytes, str]], common: Dict[str, Optional[str]]) -> None:
    try:
        tags = ID3(dst_path)
    except ID3NoHeaderError:
        tags = ID3()
    _apply_common_id3_frames(tags, common, title, cover)
    tags.save(dst_path, v2_version=3)

def _embed_all_aiff(dst_path: Path, title: Optional[str], cover: Optional[Tuple[bytes, str]], common: Dict[str, Optional[str]]) -> None:
    aiff = AIFF(dst_path)
    if aiff.tags is None:
        aiff.add_tags()  # create an empty ID3 chunk
    id3 = aiff.tags
    _apply_common_id3_frames(id3, common, title, cover)
    aiff.save(v2_version=3)

# ------------------ ffmpeg converters ------------------

def convert_to_mp3_320(ffmpeg: str, src: Path, dst: Path, title_for_tag: Optional[str]) -> int:
    """
    Convert src to MP3 320kbps CBR at dst.
    We let ffmpeg copy container-level metadata, then enforce ID3 via mutagen.
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
    We do NOT try to write ID3 in ffmpeg; mutagen will write a proper ID3 chunk.
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
        "-map_metadata", "0",    # harmless; AIFF ID3 will be handled by mutagen
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

        # Convert
        if args.format == "aiff":
            rc = convert_to_aiff_pcm_24bit(ffmpeg, src, dst, transcoded_title)
        else:
            rc = convert_to_mp3_320(ffmpeg, src, dst, transcoded_title)

        if rc == 0:
            # After conversion, embed artwork + full tag set for reliability
            cover = _get_cover_from_src(src)
            common = _read_common_tags(src)
            try:
                if args.format == "aiff":
                    _embed_all_aiff(dst, transcoded_title, cover, common)
                else:
                    _embed_all_mp3(dst, transcoded_title, cover, common)
            except Exception as e:
                print(f"[warn] Could not embed tags on '{dst.name}': {e}")
            converted += 1
        else:
            failures += 1

        # Maintain file creation order for easy drag/drop sorting
        time.sleep(2)

    print("\n=== Summary ===")
    print(f"Converted: {converted}")
    print(f"Skipped (no source): {skipped}")
    print(f"Failures: {failures}")
    print(f"Output: {out_dir}")

if __name__ == "__main__":
    main()
