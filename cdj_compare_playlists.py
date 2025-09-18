#!/usr/bin/env python
# cdj_compare_playlists.py
# --------------------
# Compare two Rekordbox playlists (Base vs Candidate) and print:
#  • song counts for both
#  • which tracks match in both
#  • which are missing or extra
#
# Matching order:
#  1) artist+title
#  2) fallback filename stem
#  3) title-only (unless --no-title-fallback)

import argparse, os, re, sys, unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, List
from collections import defaultdict

from RekordboxPlaylistAnalyzer import RekordboxPlaylistAnalyzer

_SUFFIX_TITLE_RE = re.compile(r"\s*\((?:320\s*mp3|AIFF|Transcoded)\)\s*$", re.IGNORECASE)
_NON_ALNUM_RE = re.compile(r"[^0-9a-z]+", re.IGNORECASE)

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

def _guess_content_path(c) -> Optional[Path]:
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

@dataclass
class Rec:
    artist_norm: str
    title_norm: str
    fb_norm: Optional[str]
    label: str

def _mk_rec(song) -> Rec:
    c = song.Content
    artist = _artist_text(c)
    title = _title_text(c)
    fb = None
    p = _guess_content_path(c)
    if p: fb = _norm(_strip_file_suffixes(p.stem))
    return Rec(_norm(artist),_norm(title),fb,f"{artist} — {title}" if artist else title)

def _playlist_entries(analyzer: RekordboxPlaylistAnalyzer,name:str)->List[Rec]:
    return [_mk_rec(s) for s in analyzer.get_playlist_songs_by_trackno(name)]

def _index_many(values: List[int], key_fn):
    d=defaultdict(list)
    for i in values:
        k = key_fn(i)
        if k: d[k].append(i)
    return d

def _pop(buckets,k):
    arr=buckets.get(k)
    if arr: return arr.pop()

def _match(base:List[Rec],cand:List[Rec],title_fb=True):
    nb,nc=len(base),len(cand)
    used_b=[False]*nb
    used_c=[False]*nc
    matches=[]
    def cand_idx(): return [i for i in range(nc) if not used_c[i]]

    # pass1: artist+title
    b=_index_many(cand_idx(),lambda i:f"{cand[i].artist_norm}|{cand[i].title_norm}")
    for i in range(nb):
        if used_b[i]: continue
        j=_pop(b,f"{base[i].artist_norm}|{base[i].title_norm}")
        if j is not None: used_b[i]=used_c[j]=True; matches.append((base[i],cand[j]))

    # pass2: filename stem
    b=_index_many(cand_idx(),lambda i:cand[i].fb_norm)
    for i in range(nb):
        if used_b[i] or not base[i].fb_norm: continue
        j=_pop(b,base[i].fb_norm)
        if j is not None: used_b[i]=used_c[j]=True; matches.append((base[i],cand[j]))

    # pass3: title only
    if title_fb:
        b=_index_many(cand_idx(),lambda i:cand[i].title_norm)
        for i in range(nb):
            if used_b[i]: continue
            j=_pop(b,base[i].title_norm)
            if j is not None: used_b[i]=used_c[j]=True; matches.append((base[i],cand[j]))

    missing=[base[i] for i in range(nb) if not used_b[i]]
    extra=[cand[i] for i in range(nc) if not used_c[i]]
    return matches,missing,extra

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--base",required=True)
    ap.add_argument("--candidate",required=True)
    ap.add_argument("--no-title-fallback",action="store_true")
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

    print(f"✅ Matched in both ({len(matches)}):")
    for b,c in matches:
        print(f"  = {b.label}")
    print()

    if missing:
        print(f"❌ Missing in Candidate ({len(missing)}):")
        for r in missing: print(f"  - {r.label}")
        print()

    if extra:
        print(f"➕ Additional in Candidate ({len(extra)}):")
        for r in extra: print(f"  + {r.label}")
        print()

    if not missing and not extra: sys.exit(0)
    sys.exit(1)

if __name__=="__main__":
    main()
