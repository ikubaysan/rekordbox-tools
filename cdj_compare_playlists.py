#!/usr/bin/env python
# cdj_compare_playlists.py
# ------------------------
# Compare two Rekordbox playlists (Base vs Candidate) and print:
#  • song counts for both
#  • which tracks match in both
#  • hot-cue counts for each matched track
#  • if hot-cue COUNT matches, also compare hot-cue TIMESTAMPS with ±1s tolerance
#  • which are missing or extra
#  • if NO tracks are missing: check per-track TrackNo alignment and
#    suggest the candidate TrackNo that should match the base

import argparse, os, re, sys, unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, List, Tuple
from collections import defaultdict

from RekordboxPlaylistAnalyzer import RekordboxPlaylistAnalyzer

_SUFFIX_TITLE_RE = re.compile(r"\s*\((?:320\s*mp3|AIFF|Transcoded)\)\s*$", re.IGNORECASE)
_NON_ALNUM_RE = re.compile(r"[^0-9a-z]+", re.IGNORECASE)

# --- Normalization helpers ---------------------------------------------------

def _norm(s: Optional[str]) -> str:
    if not s: return ""
    s = unicodedata.normalize("NFKD", s).encode("ascii","ignore").decode("ascii").lower()
    s = _NON_ALNUM_RE.sub(" ", s)
    return " ".join(s.split())

def _strip_transcode_suffix_from_title(t: str) -> str:
    return _SUFFIX_TITLE_RE.sub("", (t or "")).strip()

def _strip_file_suffixes(stem: str) -> str:
    return re.sub(r"(_mp3_320|_aiff)$","",stem,flags=re.IGNORECASE)

_POSSIBLE_PATH_FIELDS_ORDERED = [
    "FilePath","FileFullPath","FileLPath","Location","OrigFilePath","AbsolutePath","Path","FullPath","URL"
]

def _normalize_urlish_path(p: str) -> str:
    v = (p or "").replace("\\","/")
    if v.lower().startswith("file:///"):
        v = v[8:]
        if os.name=="nt" and len(v)>3 and v[0]=="/" and v[2]==":":
            v=v[1:]
    return os.path.normpath(v)

def _guess_content_path(c):
    for n in _POSSIBLE_PATH_FIELDS_ORDERED:
        if hasattr(c,n):
            v = getattr(c,n)
            if isinstance(v,str) and ("/" in v or "\\" in v):
                return Path(_normalize_urlish_path(v))
    child = getattr(c,"File",None)
    if child:
        for n in dir(child):
            if n.startswith("_"): continue
            try: v = getattr(child,n)
            except: continue
            if isinstance(v,str) and ("/" in v or "\\" in v):
                return Path(_normalize_urlish_path(v))
    return None

def _artist_text(c) -> str:
    s = getattr(c,"ArtistName",None)
    if isinstance(s,str) and s.strip(): return s
    art_obj = getattr(c,"Artist",None)
    for attr in ("Name","ArtistName"):
        if art_obj and hasattr(art_obj,attr):
            v = getattr(art_obj,attr)
            if isinstance(v,str) and v.strip(): return v
    artists_list = getattr(c,"Artists",None)
    if isinstance(artists_list,(list,tuple)):
        names=[]
        for a in artists_list:
            for attr in ("Name","ArtistName"):
                if hasattr(a,attr):
                    v = getattr(a,attr)
                    if isinstance(v,str) and v.strip():
                        names.append(v); break
            else:
                if isinstance(a,str) and a.strip(): names.append(a)
        if names: return " & ".join(names)
    s2 = getattr(c,"Artist",None)
    return s2 if isinstance(s2,str) and s2.strip() else ""

def _title_text(c) -> str:
    return _strip_transcode_suffix_from_title(getattr(c,"Title","") or "")

# --- Hot-cue helpers ---------------------------------------------------------

def _hot_cue_positions_ms(c) -> List[int]:
    cues = getattr(c, "Cues", None)
    if not isinstance(cues, (list, tuple)):
        return []
    out = []
    for cue in cues:
        if getattr(cue, "is_memory_cue", None) is True:
            continue
        ms = getattr(cue, "InMsec", None)
        if isinstance(ms, int):
            out.append(ms)
    out.sort()
    return out

def _match_hot_cue_positions(base_ms: List[int], cand_ms: List[int], tol_ms: int):
    used = [False] * len(cand_ms)
    matched_pairs = []
    unmatched_base = []
    for b in base_ms:
        found_j = None
        best_abs_diff = None
        for j, cm in enumerate(cand_ms):
            if used[j]:
                continue
            diff = abs(cm - b)
            if diff <= tol_ms and (best_abs_diff is None or diff < best_abs_diff):
                best_abs_diff = diff
                found_j = j
        if found_j is None:
            unmatched_base.append(b)
        else:
            used[found_j] = True
            matched_pairs.append((b, cand_ms[found_j]))
    unmatched_cand = [cand_ms[j] for j, u in enumerate(used) if not u]
    return matched_pairs, unmatched_base, unmatched_cand

def _fmt_ms(ms: int) -> str:
    s = ms // 1000
    m = s // 60
    s = s % 60
    return f"{m}:{s:02d} ({ms}ms)"

# --- Core record -------------------------------------------------------------

@dataclass
class Rec:
    artist_norm: str
    title_norm: str
    fb_norm: Optional[str]
    label: str
    track_no: int
    hot_cues: int
    hot_cue_ms: List[int]

def _mk_rec(song) -> Rec:
    c = song.Content
    artist = _artist_text(c)
    title = _title_text(c)
    fb = None
    p = _guess_content_path(c)
    if p: fb = _norm(_strip_file_suffixes(p.stem))
    label = f"{artist} — {title}" if artist else title
    hot_ms = _hot_cue_positions_ms(c)
    return Rec(
        artist_norm=_norm(artist),
        title_norm=_norm(title),
        fb_norm=fb,
        label=label,
        track_no=int(getattr(song, "TrackNo", 0) or 0),
        hot_cues=len(hot_ms),
        hot_cue_ms=hot_ms,
    )

def _playlist_entries(analyzer: RekordboxPlaylistAnalyzer,name:str)->List[Rec]:
    return [_mk_rec(s) for s in analyzer.get_playlist_songs_by_trackno(name)]

# --- Matching logic ----------------------------------------------------------

def _index_many(values: List[int], key_fn):
    d=defaultdict(list)
    for i in values:
        k = key_fn(i)
        if k: d[k].append(i)
    return d

def _pop(buckets,k):
    arr=buckets.get(k)
    if arr: return arr.pop()

def _match(base:List[Rec],cand:List[Rec],title_fb=True) -> Tuple[List[Tuple[Rec,Rec]], List[Rec], List[Rec]]:
    nb,nc=len(base),len(cand)
    used_b=[False]*nb
    used_c=[False]*nc
    matches: List[Tuple[Rec,Rec]] = []

    def cand_idx(): return [i for i in range(nc) if not used_c[i]]

    b=_index_many(cand_idx(),lambda i:f"{cand[i].artist_norm}|{cand[i].title_norm}")
    for i in range(nb):
        if used_b[i]: continue
        j=_pop(b,f"{base[i].artist_norm}|{base[i].title_norm}")
        if j is not None: used_b[i]=used_c[j]=True; matches.append((base[i],cand[j]))

    b=_index_many(cand_idx(),lambda i:cand[i].fb_norm)
    for i in range(nb):
        if used_b[i] or not base[i].fb_norm: continue
        j=_pop(b,base[i].fb_norm)
        if j is not None: used_b[i]=used_c[j]=True; matches.append((base[i],cand[j]))

    if title_fb:
        b=_index_many(cand_idx(),lambda i:cand[i].title_norm)
        for i in range(nb):
            if used_b[i]: continue
            j=_pop(b,base[i].title_norm)
            if j is not None: used_b[i]=used_c[j]=True; matches.append((base[i],cand[j]))

    missing=[base[i] for i in range(nb) if not used_b[i]]
    extra=[cand[i] for i in range(nc) if not used_c[i]]
    return matches,missing,extra

# --- Main --------------------------------------------------------------------

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--base",required=True)
    ap.add_argument("--candidate",required=True)
    ap.add_argument("--no-title-fallback",action="store_true")
    ap.add_argument("--hotcue-tolerance-ms", type=int, default=100)
    args=ap.parse_args()

    a=RekordboxPlaylistAnalyzer()
    try:
        base=_playlist_entries(a,args.base)
        cand=_playlist_entries(a,args.candidate)
    except ValueError as e:
        print(e); sys.exit(2)

    matches,missing,extra=_match(base,cand,not args.no_title_fallback)

    print("\n=== Playlist Compare ===")
    print(f"Base     : {args.base} ({len(base)} tracks)")
    print(f"Candidate: {args.candidate} ({len(cand)} tracks)\n")

    hotcue_count_mismatches = []
    hotcue_placement_mismatches = []

    tol = args.hotcue_tolerance_ms

    print(f"✅ Matched in both ({len(matches)}):")
    for b,c in matches:
        counts_equal = (b.hot_cues == c.hot_cues)
        marker = " " if counts_equal else " ⚠️"
        print(f"  ={marker} {b.label}")
        print(f"       • TrackNo: base #{b.track_no} | cand #{c.track_no}")
        print(f"       • Hot cues (count): base {b.hot_cues} | cand {c.hot_cues}")

        if not counts_equal:
            hotcue_count_mismatches.append((b,c))
        else:
            pairs, unmatched_b, unmatched_c = _match_hot_cue_positions(b.hot_cue_ms, c.hot_cue_ms, tol_ms=tol)
            if unmatched_b or unmatched_c:
                hotcue_placement_mismatches.append((b, c, unmatched_b, unmatched_c))
                print(f"       • Hot cues (placement): ❌ mismatch within ±{tol}ms")
            else:
                print(f"       • Hot cues (placement): ✅ all matched within ±{tol}ms")
    print()

    if missing:
        print(f"❌ Missing in Candidate ({len(missing)})")
    if extra:
        print(f"➕ Additional in Candidate ({len(extra)})")

    misaligned = [(b,c) for (b,c) in matches if b.track_no != c.track_no]

    all_ok = (not missing and not extra and not hotcue_count_mismatches and not hotcue_placement_mismatches and not misaligned)
    print()
    if all_ok:
        print("✅ All content matches")
    else:
        print("❌ Content differs")

    sys.exit(0 if all_ok else 1)

if __name__=="__main__":
    main()
