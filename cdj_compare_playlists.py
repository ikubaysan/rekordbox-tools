#!/usr/bin/env python
# cdj_compare_playlists.py
# ------------------------
# Compare two Rekordbox playlists (Base vs Candidate) and print:
#  • song counts for both
#  • which tracks match in both
#  • hot-cue counts for each matched track
#  • if hot-cue COUNT matches, also compare hot-cue TIMESTAMPS with ±tol
#  • which are missing or extra
#  • TrackNo alignment suggestions
# New:
#  • --apply-hotcues: clone base HOT cues into candidate on mismatches
#  • --only-differences: hide the per-track OK details, show just diffs
#  • Clear, sectioned diff report with summaries

import argparse, os, re, sys, unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, List, Tuple
from collections import defaultdict

from RekordboxPlaylistAnalyzer import RekordboxPlaylistAnalyzer
from pyrekordbox.db6.tables import DjmdCue  # for cloning/creating cues

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
        # Only HOT cues (exclude memory cues)
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
    content_id: int
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
        content_id=int(getattr(c, "ID")),
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

# --- DB write helpers (clone-based) -----------------------------------------

def _delete_existing_hot_cues(db, content_id: int) -> int:
    """Delete all NON-memory cues for a given content. Returns the number deleted."""
    deleted = 0
    q = db.get_cue(ContentID=str(content_id))
    for cue in q.all():
        if getattr(cue, "is_memory_cue", False) is True:
            continue
        db.delete(cue)
        deleted += 1
    db.flush()
    return deleted

def _clone_hot_cues_from_base_to_cand(db, base_content_id: int, cand_content_id: int) -> Tuple[int,int]:
    """
    Clone all HOT cues from base_content_id to cand_content_id.
    Returns (deleted_count, created_count) for the candidate.
    """
    deleted = _delete_existing_hot_cues(db, cand_content_id)
    created = 0
    cue_columns = [col for col in DjmdCue.columns() if col not in ("ID", "ContentID")]  # real DB cols
    base_q = db.get_cue(ContentID=str(base_content_id))
    for base_cue in base_q.all():
        if getattr(base_cue, "is_memory_cue", False) is True:
            continue
        kwargs = {}
        for col in cue_columns:
            try:
                kwargs[col] = base_cue[col]
            except Exception:
                pass
        new_id = db.generate_unused_id(DjmdCue, is_28_bit=True)
        new_cue = DjmdCue.create(ID=int(new_id), ContentID=str(cand_content_id), **kwargs)
        db.add(new_cue)
        created += 1
    return deleted, created

# --- Main --------------------------------------------------------------------

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--base",required=True)
    ap.add_argument("--candidate",required=True)
    ap.add_argument("--no-title-fallback",action="store_true")
    ap.add_argument("--hotcue-tolerance-ms", type=int, default=100)
    ap.add_argument("--apply-hotcues", action="store_true",
                    help="Overwrite mismatched candidate hot cues to match base (Rekordbox must be CLOSED for commit).")
    ap.add_argument("--only-differences", action="store_true",
                    help="Show only differences (omit per-track OK details).")
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

    hotcue_count_mismatches: List[Tuple[Rec,Rec]] = []
    hotcue_placement_mismatches: List[Tuple[Rec,Rec,List[int],List[int]]] = []

    tol = args.hotcue_tolerance_ms

    # Per-track details (optional)
    if not args.only_differences:
        print(f"✅ Matched in both ({len(matches)}):")
    for b,c in matches:
        counts_equal = (b.hot_cues == c.hot_cues)
        if not args.only_differences:
            marker = " " if counts_equal else " ⚠️"
            print(f"  ={marker} {b.label}")
            print(f"       • TrackNo: base #{b.track_no} | cand #{c.track_no}")
            print(f"       • Hot cues (count): base {b.hot_cues} | cand {c.hot_cues}")

        if not counts_equal:
            hotcue_count_mismatches.append((b,c))
            if not args.only_differences:
                print(f"       • Hot cues (placement): (skipped; counts differ)")
        else:
            pairs, unmatched_b, unmatched_c = _match_hot_cue_positions(b.hot_cue_ms, c.hot_cue_ms, tol_ms=tol)
            if unmatched_b or unmatched_c:
                hotcue_placement_mismatches.append((b, c, unmatched_b, unmatched_c))
                if not args.only_differences:
                    print(f"       • Hot cues (placement): ❌ mismatch within ±{tol}ms")
            else:
                if not args.only_differences:
                    print(f"       • Hot cues (placement): ✅ all matched within ±{tol}ms)")
    if not args.only_differences:
        print()

    # Track number alignment (computed regardless)
    misaligned = [(b,c) for (b,c) in matches if b.track_no != c.track_no]

    # ===== DIFF SUMMARY =====
    any_diffs = (missing or extra or hotcue_count_mismatches or hotcue_placement_mismatches or misaligned)
    print("=== Diff Summary ===")
    print(f"Missing in Candidate      : {len(missing)}")
    print(f"Additional in Candidate   : {len(extra)}")
    print(f"Hot-cue COUNT mismatches  : {len(hotcue_count_mismatches)}")
    print(f"Hot-cue PLACEMENT mismatches (±{tol}ms): {len(hotcue_placement_mismatches)}")
    print(f"TrackNo misaligned        : {len(misaligned)}")
    print()

    # ===== Detailed sections only for what differs =====
    if missing:
        print(f"❌ Missing in Candidate ({len(missing)}):")
        for m in missing:
            print(f"  - {m.label}")
        print()

    if extra:
        print(f"➕ Additional in Candidate ({len(extra)}):")
        for e in extra:
            print(f"  + {e.label}")
        print()

    if hotcue_count_mismatches:
        print(f"🎯 Hot-cue COUNT mismatches ({len(hotcue_count_mismatches)}):")
        for b,c in hotcue_count_mismatches:
            print(f"  - {b.label}: base {b.hot_cues} vs cand {c.hot_cues}")
        print()

    if hotcue_placement_mismatches:
        print(f"📍 Hot-cue PLACEMENT mismatches within ±{tol}ms ({len(hotcue_placement_mismatches)}):")
        for b,c,ub,uc in hotcue_placement_mismatches:
            print(f"  - {b.label}")
            if ub:
                print(f"      base unmatched: {', '.join(_fmt_ms(x) for x in ub)}")
            if uc:
                print(f"      cand unmatched: {', '.join(_fmt_ms(x) for x in uc)}")
        print()

    if not (missing or extra) and misaligned:
        print(f"🔢 TrackNo misalignment ({len(misaligned)}):")
        for b,c in misaligned:
            print(f"  - {b.label}: base #{b.track_no} | cand #{c.track_no}  → suggested: move candidate to #{b.track_no}")
        print()

    # --- Optional write-back of hot cues ------------------------------------
    if args.apply_hotcues:
        # Fix everything that’s wrong with hot cues (count OR placement)
        to_fix: List[Tuple[Rec, Rec, str]] = []
        for (b,c) in hotcue_count_mismatches:
            if b.hot_cues > 0:
                to_fix.append((b,c,"count"))
        for (b,c,_,_) in hotcue_placement_mismatches:
            if b.hot_cues > 0:
                to_fix.append((b,c,"placement"))

        if to_fix:
            print("\n=== Applying Hot-Cue Fixes (candidate ← base) ===")
            staged = 0
            for (b,c,reason) in to_fix:
                print(f"- {b.label}  [reason: {reason}]")
                print(f"    base hot cues: {', '.join(_fmt_ms(x) for x in b.hot_cue_ms) if b.hot_cue_ms else '(none)'}")
                print(f"    cand WAS     : {', '.join(_fmt_ms(x) for x in c.hot_cue_ms) if c.hot_cue_ms else '(none)'}")
                try:
                    deleted, created = _clone_hot_cues_from_base_to_cand(a.db, b.content_id, c.content_id)
                    staged += created
                    print(f"    staged fix   : deleted {deleted}; created {created} from base")
                except Exception as ex:
                    print(f"    ⚠️ Failed to stage hot-cue update for candidate content_id={c.content_id}: {ex}")

            if staged > 0:
                try:
                    a.db.commit(autoinc=True)
                    print("\n✅ Database commit successful. Hot cues updated in candidate tracks.")
                except RuntimeError as ex:
                    print("\n❌ Could not commit hot-cue changes.")
                    print(f"   Reason: {ex}")
                    print("   Hint: Close Rekordbox and rerun with --apply-hotcues.")
                except Exception as ex:
                    print("\n❌ Commit failed with unexpected error:")
                    print(f"   {ex}")
            else:
                print("\nNothing to commit (no changes were staged).")

    print()
    if not any_diffs:
        print("✅ All content matches")
        sys.exit(0)
    else:
        print("❌ Content differs")
        sys.exit(1)

if __name__=="__main__":
    main()
