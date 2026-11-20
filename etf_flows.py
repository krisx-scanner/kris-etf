#!/usr/bin/env python3
"""Fetch Farside US spot Bitcoin ETF daily flows and write etf.json for Kris Terminal.
Runs on the Kris Terminal box and in GitHub Actions (krisx-scanner/kris-etf). On fetch/parse failure, leave the previous etf.json alone.
"""
import json, os, re, sys, time, urllib.request
from datetime import datetime, timezone
from html import unescape

SITE = os.environ.get('ETF_DIR') or os.path.dirname(os.path.abspath(__file__))
OUT = f'{SITE}/etf.json'
URL = 'https://farside.co.uk/bitcoin-etf-flow-all-data/'
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) '
      'Chrome/131.0.0.0 Safari/537.36')
DATE_RE = re.compile(r'^(\d{1,2}) (Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) (\d{4})$')
SKIP_LABELS = {'date', 'total', 'average', 'max', 'min'}
MONTHS = {m: i for i, m in enumerate(
    ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'], 1)}


def parse_num(s):
    s = unescape(s or '').strip()
    if s in ('', '-', '—', '–'):
        return None
    neg = False
    if s.startswith('(') and s.endswith(')'):
        neg, s = True, s[1:-1].strip()
    s = s.replace(',', '').replace('$', '').replace('\xa0', '').strip()
    if s in ('', '-', '—', '–'):
        return None
    try:
        v = float(s)
    except ValueError:
        return None
    return -v if neg else v


def cells(row_html):
    out = []
    for c in re.findall(r'<t[hd][^>]*>(.*?)</t[hd]>', row_html, re.S | re.I):
        t = re.sub(r'<[^>]+>', '', c)
        t = unescape(t)
        t = re.sub(r'\s+', ' ', t).strip()
        out.append(t)
    return out


def is_pending(funds, total):
    vals = list(funds.values())
    if not vals:
        return True
    if all(v is None for v in vals) and (total is None or total == 0.0):
        return True
    # Farside fills IBIT last; a row without IBIT is a partial day, not final
    return funds.get('IBIT') is None


def fetch():
    req = urllib.request.Request(URL, headers={'User-Agent': UA, 'Accept': 'text/html'})
    with urllib.request.urlopen(req, timeout=30) as r:
        html = r.read().decode('utf-8', 'replace')
    m = re.search(r'<table class="etf">(.*?)</table>', html, re.S | re.I)
    if not m:
        raise RuntimeError('Farside ETF table not found')
    rows = re.findall(r'<tr[^>]*>(.*?)</tr>', m.group(1), re.S | re.I)
    header, data = None, []
    for row in rows:
        cs = cells(row)
        if not cs:
            continue
        first = cs[0]
        if first.strip().lower() in SKIP_LABELS:
            if header is None and first.strip().lower() == 'date' and len(cs) >= 3:
                header = cs
            continue
        if not DATE_RE.match(first) or header is None or len(cs) < 2:
            continue
        funds, total = {}, None
        for i, name in enumerate(header[1:], 1):
            val = parse_num(cs[i]) if i < len(cs) else None
            if name.strip().lower() == 'total':
                total = val
            else:
                funds[name] = val
        if total is None and cs:
            total = parse_num(cs[-1])
        data.append({'date': first, 'total': total, 'funds': funds, 'pending': is_pending(funds, total)})
    if not data:
        raise RuntimeError('no dated ETF rows parsed')
    return data


def build(rows):
    completed = [r for r in rows if not r['pending']]
    if not completed:
        raise RuntimeError('no completed ETF days')
    pending_today = bool(rows) and rows[-1]['pending']
    latest = completed[-1]
    funds = {k: (0.0 if v is None else v) for k, v in latest['funds'].items() if v is not None}
    # streak over all completed history, from the latest day backward
    last = latest['total'] if latest['total'] is not None else 0.0
    if last == 0:
        streak = {'direction': 'in', 'days': 0}
    else:
        direction = 'in' if last > 0 else 'out'
        days = 0
        for r in reversed(completed):
            t = r['total'] if r['total'] is not None else 0.0
            if t == 0 or (t > 0) != (direction == 'in'):
                break
            days += 1
        streak = {'direction': direction, 'days': days}
    recent = [{'date': r['date'], 'total': r['total'] if r['total'] is not None else 0.0}
              for r in completed[-7:]]
    return {
        'updated': int(time.time()),
        'source': 'Farside',
        'latest': {'date': latest['date'], 'total': latest['total'] if latest['total'] is not None else 0.0, 'funds': funds},
        'pending_today': pending_today,
        'recent': recent,
        'streak': streak,
    }


def main():
    try:
        data = build(fetch())
        if not data.get('latest'):
            raise RuntimeError('missing latest')
        tmp = OUT + '.tmp'
        with open(tmp, 'w') as f:
            json.dump(data, f, separators=(',', ':'))
        os.replace(tmp, OUT)
        latest, streak = data['latest'], data['streak']
        print(datetime.now().strftime('%Y-%m-%d %H:%M'),
              f"ETF {latest['date']} total={latest['total']} IBIT={latest['funds'].get('IBIT')} "
              f"{streak['days']}d {streak['direction']} pending={data['pending_today']}",
              flush=True)
    except Exception as e:
        print(datetime.now().strftime('%Y-%m-%d %H:%M'), 'ETF FAILED:', repr(e), flush=True)
        sys.exit(1)


if __name__ == '__main__':
    main()
