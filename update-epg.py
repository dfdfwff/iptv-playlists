#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Rebuild the local XMLTV file used by the playlists that sit next to this script.

Data sources
  1) https://live.fanmingming.com/e.xml  -> ~6 days of HISTORY (needs the system proxy)
  2) https://epg.pw/xmltv/epg_CN.xml     -> today + next 7 days
  3) epg.pw per-day API                  -> history for channels source (1) lacks
  4) the existing output file            -> older days are carried over (up to KEEP_DAYS)

Everything is parsed as a STREAM (xml.etree.ElementTree.iterparse) and written line by
line, so peak memory stays around a hundred megabytes instead of gigabytes.
"""

import csv
import datetime as dt
import html
import os
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from xml.etree import ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
FEED_URL = "https://live.fanmingming.com/e.xml"
BULK_URL = "https://epg.pw/xmltv/epg_CN.xml"
API_URL = "https://epg.pw/api/epg.xml?lang=zh-hans&date={date}&channel_id={cid}"

KEEP_DAYS = 14      # how long old days are carried over
API_DAYS = 6        # how far back the per-day API is asked for the remaining channels


def log(msg):
    print(msg, flush=True)


def peak_mb():
    try:
        import ctypes
        from ctypes import wintypes

        class PMC(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        p = PMC()
        p.cb = ctypes.sizeof(PMC)
        ctypes.windll.psapi.GetProcessMemoryInfo(
            ctypes.windll.kernel32.GetCurrentProcess(), ctypes.byref(p), p.cb)
        return p.PeakWorkingSetSize / 1048576.0
    except Exception:
        return -1.0


def system_proxy():
    try:
        import winreg
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                           r"Software\Microsoft\Windows\CurrentVersion\Internet Settings")
        enabled = winreg.QueryValueEx(k, "ProxyEnable")[0]
        server = winreg.QueryValueEx(k, "ProxyServer")[0]
        if enabled and server:
            return "http://" + server
    except Exception:
        pass
    return None


def fetch(url, path, proxy=None, timeout=180, retries=2):
    handlers = [urllib.request.ProxyHandler({"http": proxy, "https": proxy} if proxy else {})]
    op = urllib.request.build_opener(*handlers)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    last = None
    for attempt in range(retries + 1):
        try:
            with op.open(req, timeout=timeout) as r, open(path, "wb") as f:
                while True:
                    chunk = r.read(262144)
                    if not chunk:
                        break
                    f.write(chunk)
            size = os.path.getsize(path)
            if size > 0:
                return size
            last = Exception("empty response")
        except Exception as e:
            last = e
            time.sleep(2)
    raise last


def read_channels(playlists):
    channels, seen = [], set()
    for pl in playlists:
        with open(pl, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line.startswith("#EXTINF"):
                    continue
                m = __import__("re").search(r'tvg-id="([^"]+)"', line)
                if not m:
                    continue
                cid = m.group(1)
                if cid in seen:
                    continue
                seen.add(cid)
                name = line.rsplit(",", 1)[-1].strip()
                lm = __import__("re").search(r'tvg-logo="([^"]*)"', line)
                channels.append({"id": cid, "name": name, "logo": lm.group(1) if lm else ""})
    return channels


def iter_programmes(path):
    """Yield (channel, start, stop, inner_xml) - streamed, so large files are fine."""
    for _, el in ET.iterparse(path, events=("end",)):
        if el.tag != "programme":
            continue
        inner = "".join(ET.tostring(c, encoding="unicode") for c in el)
        yield el.get("channel"), el.get("start"), el.get("stop"), inner
        el.clear()


def main():
    t0 = time.time()
    playlists = [os.path.join(HERE, f) for f in os.listdir(HERE)
                 if f.lower().endswith(".m3u") and "EPG" not in f]
    if not playlists:
        log("no .m3u playlist found next to this script")
        return 1

    existing = [os.path.join(HERE, f) for f in os.listdir(HERE) if f.endswith("-EPG.xml")]
    out_file = existing[0] if existing else os.path.join(
        HERE, os.path.splitext(os.path.basename(playlists[0]))[0] + "-EPG.xml")
    cache = os.path.join(HERE, "_epg_cache")
    os.makedirs(cache, exist_ok=True)

    log("playlists: " + ", ".join(os.path.basename(p) for p in playlists))
    log("output   : " + os.path.basename(out_file))

    channels = read_channels(playlists)
    wanted = {c["id"] for c in channels}
    log("channels : %d" % len(channels))

    # ---- name -> history-feed channel id
    name_to_feed, feed_to_ours = {}, {}
    map_file = os.path.join(HERE, "epg-history-map.csv")
    if os.path.exists(map_file):
        with open(map_file, encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                if row.get("name") and row.get("fmmlid"):
                    name_to_feed[row["name"].strip()] = row["fmmlid"].strip()
    for c in channels:
        fid = name_to_feed.get(c["name"]) or name_to_feed.get(c["name"].rstrip("_"))
        if fid:
            feed_to_ours.setdefault(fid, []).append(c["id"])

    done = {}          # (cid, start) -> xml  (everything we keep)
    covered = set()    # (cid, date) already supplied by a history source
    today = dt.date.today()
    today_s = today.strftime("%Y%m%d")

    # ---- 1) today + future
    bulk = os.path.join(cache, "epg_cn.xml")
    log("downloading current-week EPG ...")
    bulk_ok = False
    try:
        log("  %d bytes" % fetch(BULK_URL, bulk, timeout=300))
        bulk_ok = True
    except Exception as e:
        log("  failed (%s) - will reuse today/future from the previous file" % e)
    n = 0
    if bulk_ok:
        try:
            for ch, st, sp, inner in iter_programmes(bulk):
                if ch not in wanted:
                    continue
                done[(ch, st)] = (ch, st, sp, inner)
                n += 1
        except Exception as e:
            log("  parse stopped early: %s" % e)
    log("  today+future: %d programmes" % n)

    # ---- 2) history feed (fanmingming)
    proxy = system_proxy()
    log("history feed (proxy=%s) ..." % (proxy or "none"))
    feed = os.path.join(cache, "history.xml")
    ok = False
    try:
        size = fetch(FEED_URL, feed, proxy=proxy)
        log("  %d bytes" % size)
        ok = size > 100000
    except Exception as e:
        log("  failed: %s" % e)
    n = 0
    if ok:
        try:
            for ch, st, sp, inner in iter_programmes(feed):
                ours = feed_to_ours.get(ch)
                if not ours:
                    continue
                date = st[:8]
                if date >= today_s:
                    continue
                for oid in ours:
                    if (oid, st) not in done:
                        done[(oid, st)] = (oid, st, sp, inner)
                        n += 1
                    covered.add((oid, date))
        except Exception as e:
            log("  parse stopped early: %s" % e)
    log("  history feed: +%d programmes" % n)

    # ---- 3) per-day API for whatever the feed does not cover
    todo = []
    for d in range(1, API_DAYS + 1):
        day = (today - dt.timedelta(days=d)).strftime("%Y%m%d")
        for c in channels:
            if (c["id"], day) not in covered:
                todo.append((c["id"], day))
    log("per-day API: %d requests ..." % len(todo))

    def grab(item):
        cid, day = item
        p = os.path.join(cache, "%s_%s.xml" % (cid, day))
        try:
            fetch(API_URL.format(date=day, cid=cid), p, timeout=30)
            return p, day
        except Exception:
            return None, day

    n = 0
    with ThreadPoolExecutor(max_workers=8) as pool:
        for path, day in pool.map(grab, todo):
            if not path or not os.path.exists(path):
                continue
            try:
                for ch, st, sp, inner in iter_programmes(path):
                    if not st.startswith(day):
                        continue
                    if (ch, st) not in done:
                        done[(ch, st)] = (ch, st, sp, inner)
                        n += 1
            except Exception:
                pass
    log("  per-day API: +%d programmes" % n)

    # ---- 4) carry over older days from the previous output
    cut = (today - dt.timedelta(days=KEEP_DAYS)).strftime("%Y%m%d")
    n = 0
    if os.path.exists(out_file):
        try:
            for ch, st, sp, inner in iter_programmes(out_file):
                if ch not in wanted or st[:8] < cut:
                    continue
                if (ch, st[:8]) in covered:
                    continue
                if (ch, st) not in done:
                    done[(ch, st)] = (ch, st, sp, inner)
                    n += 1
        except Exception as e:
            log("  parse stopped early: %s" % e)
    log("carry over: +%d programmes" % n)

    # ---- 5) write
    log("writing ...")
    with open(out_file, "w", encoding="utf-8", newline="\n") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        f.write('<tv generator-info-name="SrcBox local EPG (merged)">\n')
        for c in channels:
            icon = '<icon src="%s"/>' % html.escape(c["logo"], quote=True) if c["logo"] else ""
            f.write('  <channel id="%s"><display-name lang="zh">%s</display-name>%s</channel>\n'
                    % (html.escape(c["id"], quote=True), html.escape(c["name"]), icon))
        for k in sorted(done):
            cid, st, sp, inner = done[k]
            f.write('  <programme channel="%s" start="%s" stop="%s">%s</programme>\n'
                    % (html.escape(cid, quote=True), html.escape(st, quote=True),
                       html.escape(sp, quote=True), inner))
        f.write("</tv>\n")

    days = sorted({k[1][:8] for k in done})
    log("")
    log("done. programmes=%d  channels=%d  days=%d" % (len(done), len(channels), len(days)))
    log("date range: %s .. %s" % (days[0], days[-1]))
    log("output    : %s" % out_file)
    log("elapsed   : %.1fs   peak memory: %.0f MB" % (time.time() - t0, peak_mb()))
    try:
        import shutil
        shutil.rmtree(cache, ignore_errors=True)
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
