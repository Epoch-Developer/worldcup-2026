#!/usr/bin/env python3
"""
Kelly Family World Cup 2026 tracker — static build script.

Runs on a schedule (GitHub Actions) with NO AI and NO Claude dependency.
  1. Loads the append-only ledger from data/ledger.json
  2. Fetches the fixture+score feed (primary, with fallback)
  3. Banks any match whose score the feed reports as final
     (optionally cross-checked against a second feed for agreement)
  4. Rebuilds the 48-team standings and writes index.html

Run modes:
  python build.py               # full: fetch + merge + render
  python build.py --render-only # rebuild index.html from the existing ledger (no network)

Pure standard library. No pip installs required.
"""

import json, os, sys, urllib.request, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
LEDGER_PATH = os.path.join(HERE, "data", "ledger.json")
INDEX_PATH = os.path.join(HERE, "index.html")

PRIMARY_FEED = "https://raw.githubusercontent.com/upbound-web/worldcup-live.json/master/2026/worldcup.json"
FALLBACK_FEED = "https://raw.githubusercontent.com/openfootball/worldcup.json/master/2026/worldcup.json"

# If True, a primary-feed score is only banked when a second feed that also
# carries that match agrees on the exact scoreline. Matches the original
# "two independent sources must agree" rule, using two feeds instead of AI.
# Matches the second feed does NOT carry are still banked from the primary feed.
CROSS_CHECK = True

# Feed team name -> owner's canonical team name
NAME_MAP = {
    "Czechia": "Czech Republic",
    "Côte d'Ivoire": "Ivory Coast", "Cote d'Ivoire": "Ivory Coast",
    "Curacao": "Curaçao",
    "Congo DR": "DR Congo", "Democratic Republic of Congo": "DR Congo", "Congo": "DR Congo",
    "Bosnia-Herzegovina": "Bosnia and Herzegovina", "Bosnia & Herzegovina": "Bosnia and Herzegovina",
    "Korea Republic": "South Korea", "Republic of Korea": "South Korea",
    "Cape Verde Islands": "Cape Verde", "Cape Verde Is.": "Cape Verde",
    "USA": "United States",
    "Türkiye": "Turkey", "Turkiye": "Turkey",
}
def mapname(n): return NAME_MAP.get(n, n)

OWNERS = {
    "John":     ["England","Portugal","Japan","Morocco","Switzerland","Austria","Sweden","Ghana","Czech Republic","Jordan","Iraq","Haiti"],
    "Muireann": ["Spain","Netherlands","Colombia","Ecuador","Senegal","Turkey","Egypt","South Korea","Bosnia and Herzegovina","Saudi Arabia","DR Congo","Cape Verde"],
    "Ava":      ["Argentina","Brazil","Norway","Croatia","Mexico","Canada","Ivory Coast","Scotland","Iran","Tunisia","New Zealand","Curaçao"],
    "Conor":    ["France","Germany","Belgium","United States","Uruguay","Paraguay","Algeria","Australia","Uzbekistan","South Africa","Qatar","Panama"],
}
OWNER_ORDER = ["John","Muireann","Ava","Conor"]
TEAMS = {t for ts in OWNERS.values() for t in ts}
OWNER_OF = {t: o for o, ts in OWNERS.items() for t in ts}


def now_dublin():
    try:
        from zoneinfo import ZoneInfo
        return datetime.datetime.now(ZoneInfo("Europe/Dublin"))
    except Exception:
        # World Cup 2026 runs entirely in Irish Summer Time (UTC+1)
        return datetime.datetime.utcnow() + datetime.timedelta(hours=1)


def fetch_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "worldcup-tracker"})
    with urllib.request.urlopen(req, timeout=30) as r:
        text = r.read().decode("utf-8")
    i = text.find("{")
    return json.loads(text[i:] if i > 0 else text)


def canon(date, home, away):
    return "%s|%s|%s" % (date, home, away)


def extract_score(m):
    """Return (hg, ag, res) using owner orientation, or None if no final score."""
    sc = m.get("score") or {}
    ft = sc.get("ft")
    if not (isinstance(ft, list) and len(ft) == 2 and all(isinstance(x, int) for x in ft)):
        return None
    et = sc.get("et"); pk = sc.get("p")
    goals = et if (isinstance(et, list) and len(et) == 2 and all(isinstance(x, int) for x in et)) else ft
    hg, ag = goals[0], goals[1]
    if isinstance(pk, list) and len(pk) == 2 and pk[0] != pk[1]:
        res = "H" if pk[0] > pk[1] else "A"
    elif isinstance(et, list) and len(et) == 2 and et[0] != et[1]:
        res = "H" if et[0] > et[1] else "A"
    else:
        res = "H" if ft[0] > ft[1] else ("A" if ft[1] > ft[0] else "D")
    return hg, ag, res


def build_fallback_index(feed):
    """canonical key -> (hg, ag) from the second feed, for cross-checking."""
    idx = {}
    for m in feed.get("matches", []):
        t1, t2 = mapname(m.get("team1", "")), mapname(m.get("team2", ""))
        if t1 not in TEAMS or t2 not in TEAMS:
            continue
        s = extract_score(m)
        if s:
            idx[canon(m.get("date", ""), t1, t2)] = (s[0], s[1])
    return idx


def merge(ledger, feed, fallback_idx, today):
    existing_canon = set()
    existing_keys = set()
    for e in ledger:
        date = e["key"].split("|")[0]
        existing_canon.add(canon(date, e["home"], e["away"]))
        existing_keys.add(e["key"])

    merged = list(ledger)
    added, skipped = [], []
    for m in feed.get("matches", []):
        date = m.get("date", "")
        t1raw, t2raw = m.get("team1", ""), m.get("team2", "")
        t1, t2 = mapname(t1raw), mapname(t2raw)
        if not date or date > today:
            continue
        if t1 not in TEAMS or t2 not in TEAMS:   # skips knockout placeholders
            continue
        c = canon(date, t1, t2)
        key = "%s|%s|%s" % (date, t1raw, t2raw)
        if c in existing_canon or key in existing_keys:
            continue
        s = extract_score(m)
        if not s:
            continue
        hg, ag, res = s
        if CROSS_CHECK and c in fallback_idx and fallback_idx[c] != (hg, ag):
            skipped.append("%s %s-%s (feeds disagree)" % (c, hg, ag))
            continue
        entry = {"key": key, "home": t1, "away": t2, "hg": hg, "ag": ag, "res": res}
        merged.append(entry)
        existing_canon.add(c); existing_keys.add(key)
        added.append("%s %d-%d" % (c, hg, ag))
    return merged, added, skipped


def rebuild_standings(merged, label):
    stats = {t: {"name": t, "owner": OWNER_OF[t], "p": 0, "w": 0, "d": 0, "l": 0,
                 "gf": 0, "ga": 0, "pts": 0} for t in TEAMS}
    for e in merged:
        h, a = e["home"], e["away"]
        if h not in stats or a not in stats:
            continue
        H, A = stats[h], stats[a]
        H["p"] += 1; A["p"] += 1
        H["gf"] += e["hg"]; H["ga"] += e["ag"]
        A["gf"] += e["ag"]; A["ga"] += e["hg"]
        if e["res"] == "D":
            H["d"] += 1; A["d"] += 1; H["pts"] += 1; A["pts"] += 1
        elif e["res"] == "H":
            H["w"] += 1; H["pts"] += 3; A["l"] += 1
        else:
            A["w"] += 1; A["pts"] += 3; H["l"] += 1
    teams = [stats[t] for o in OWNER_ORDER for t in OWNERS[o]]
    return {"updated": label, "matches": len(merged), "inProgress": 0, "teams": teams}


def render(merged, standings):
    html = TEMPLATE
    html = html.replace("__BANKED_JSON__", json.dumps(merged, ensure_ascii=False))
    html = html.replace("__STANDINGS_JSON__", json.dumps(standings, ensure_ascii=False))
    with open(INDEX_PATH, "w", encoding="utf-8") as f:
        f.write(html)


def main():
    render_only = "--render-only" in sys.argv
    now = now_dublin()
    label = now.strftime("%d %b %Y %H:%M")
    today = now.strftime("%Y-%m-%d")

    with open(LEDGER_PATH, encoding="utf-8") as f:
        ledger = json.load(f)

    if render_only:
        standings = rebuild_standings(ledger, label)
        render(ledger, standings)
        print("Rendered index.html from %d banked matches (no fetch)." % len(ledger))
        return

    try:
        feed = fetch_json(PRIMARY_FEED)
    except Exception as e:
        print("Primary feed failed (%s); trying fallback." % e)
        feed = fetch_json(FALLBACK_FEED)

    fallback_idx = {}
    if CROSS_CHECK:
        try:
            fallback_idx = build_fallback_index(fetch_json(FALLBACK_FEED))
        except Exception as e:
            print("Cross-check feed unavailable (%s); banking from primary only." % e)

    merged, added, skipped = merge(ledger, feed, fallback_idx, today)

    with open(LEDGER_PATH, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False)
    standings = rebuild_standings(merged, label)
    render(merged, standings)

    print("Banked total: %d (%d new this run)." % (len(merged), len(added)))
    for a in added:
        print("  + " + a)
    for s in skipped:
        print("  ! held: " + s)


TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Kelly Family World Cup 2026</title>
<style>
:root { color-scheme: light; }
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f8fafc; color: #0f172a; min-height: 100vh; }
.header { background: linear-gradient(135deg, #1e3a5f 0%, #0f172a 100%); padding: 22px 20px 18px; text-align: center; }
.header h1 { font-size: 1.55rem; font-weight: 800; color: #f1f5f9; }
.header p  { color: #94a3b8; font-size: 0.78rem; margin-top: 5px; }
.status-bar { display: flex; align-items: center; justify-content: center; gap: 8px; padding: 8px 16px; background: #1e293b; font-size: 0.75rem; color: #94a3b8; }
.dot { width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; }
.dot-green  { background: #22c55e; }
.dot-yellow { background: #f59e0b; }
.warn-bar { display: none; align-items: center; gap: 8px; background: #fefce8; border-bottom: 1px solid #fde047; padding: 8px 16px; font-size: 0.78rem; color: #713f12; }
.no-data { text-align: center; padding: 60px 20px; color: #64748b; }
.no-data p { margin-top: 12px; font-size: 0.95rem; }
.no-data small { font-size: 0.8rem; color: #94a3b8; }
.section { padding: 18px 16px 0; }
.section-title { font-size: 0.72rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em; color: #64748b; margin-bottom: 12px; }
.leaderboard { display: grid; grid-template-columns: repeat(2, 1fr); gap: 10px; }
@media (min-width: 640px) { .leaderboard { grid-template-columns: repeat(4, 1fr); } }
.player-card { background: #fff; border-radius: 12px; padding: 16px; border-top: 4px solid; box-shadow: 0 1px 4px rgba(0,0,0,0.06); }
.card-rank  { font-size: 1.4rem; }
.card-name  { font-size: 1rem; font-weight: 700; margin: 6px 0 2px; }
.card-pts   { font-size: 2.2rem; font-weight: 800; line-height: 1.1; }
.card-label { font-size: 0.65rem; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.1em; }
.card-stats { display: flex; gap: 14px; margin-top: 10px; padding-top: 10px; border-top: 1px solid #f1f5f9; }
.card-stat-val   { font-size: 1rem; font-weight: 600; }
.card-stat-label { font-size: 0.62rem; color: #94a3b8; text-transform: uppercase; }
.legend { display: flex; flex-wrap: wrap; gap: 14px; padding: 14px 16px 0; }
.legend-item { display: flex; align-items: center; gap: 5px; font-size: 0.78rem; font-weight: 500; color: #334155; }
.legend-pip  { width: 9px; height: 9px; border-radius: 50%; }
.table-wrap { overflow-x: auto; margin-top: 10px; padding-bottom: 20px; }
table { width: 100%; border-collapse: collapse; font-size: 0.82rem; min-width: 560px; }
thead th { background: #f1f5f9; padding: 9px 7px; font-size: 0.68rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.06em; color: #64748b; border-bottom: 2px solid #e2e8f0; white-space: nowrap; }
tbody tr { border-bottom: 1px solid #f1f5f9; }
tbody tr:hover { background: #f8fafc; }
td { padding: 8px 7px; }
.td-pos  { width: 28px; text-align: right; color: #94a3b8; font-size: 0.75rem; }
.td-team { text-align: left; padding-left: 10px !important; }
.td-num  { text-align: center; color: #475569; }
.td-pts  { text-align: center; font-weight: 700; }
.td-gd   { text-align: center; font-weight: 600; }
.team-name-text { font-weight: 500; color: #0f172a; }
.owner-tag { display: inline-block; font-size: 0.6rem; font-weight: 700; padding: 1px 5px; border-radius: 3px; margin-left: 5px; opacity: 0.9; }
.row-john     td:first-child { border-left: 3px solid #3b82f6; }
.row-muireann td:first-child { border-left: 3px solid #8b5cf6; }
.row-ava      td:first-child { border-left: 3px solid #ef4444; }
.row-conor    td:first-child { border-left: 3px solid #10b981; }
.gd-pos { color: #16a34a; }
.gd-neg { color: #dc2626; }
.gd-nil { color: #94a3b8; }
.footer { padding: 14px 16px; font-size: 0.72rem; color: #94a3b8; text-align: center; }
</style>
</head>
<body>
<div class="header">
  <h1>🏆 Kelly Family World Cup 2026</h1>
  <p>Live standings · Only completed matches counted · Canada / USA / Mexico</p>
</div>
<div class="status-bar" id="statusBar">
  <span class="dot dot-yellow"></span>
  <span id="statusText">Loading…</span>
</div>
<div class="warn-bar" id="warnBar">⚠️ Matches were in progress at last update — those scores are excluded.</div>
<div id="noData" class="no-data">
  <div style="font-size:2rem">⏳</div>
  <p>Standings will appear after the first scheduled refresh.</p>
  <small>Updates run at 6am · noon · 6pm · midnight (Irish time)</small>
</div>
<div id="mainContent" style="display:none">
  <div class="section">
    <div class="section-title">🏅 Family Leaderboard</div>
    <div class="leaderboard" id="leaderboard"></div>
  </div>
  <div class="legend">
    <div class="legend-item"><span class="legend-pip" style="background:#3b82f6"></span>John</div>
    <div class="legend-item"><span class="legend-pip" style="background:#8b5cf6"></span>Muireann</div>
    <div class="legend-item"><span class="legend-pip" style="background:#ef4444"></span>Ava</div>
    <div class="legend-item"><span class="legend-pip" style="background:#10b981"></span>Conor</div>
  </div>
  <div class="section" style="padding-top:16px">
    <div class="section-title">📊 Tournament Table — All 48 Teams</div>
    <div class="table-wrap">
      <table>
        <thead><tr>
          <th style="text-align:right">#</th>
          <th style="text-align:left;padding-left:10px">Team</th>
          <th>P</th><th>W</th><th>D</th><th>L</th><th>GF</th><th>GA</th><th>GD</th><th>Pts</th>
        </tr></thead>
        <tbody id="teamBody"></tbody>
      </table>
    </div>
  </div>
  <div class="footer">Standings rebuilt from a banked match ledger · confirmed results never dropped</div>
</div>
<script>
const BANKED_MATCHES = __BANKED_JSON__;
const STANDINGS = __STANDINGS_JSON__;
const STYLES = {
  John:     { color:'#3b82f6', cls:'row-john',     tagBg:'#dbeafe', tagFg:'#1d4ed8' },
  Muireann: { color:'#8b5cf6', cls:'row-muireann', tagBg:'#ede9fe', tagFg:'#5b21b6' },
  Ava:      { color:'#ef4444', cls:'row-ava',       tagBg:'#fee2e2', tagFg:'#991b1b' },
  Conor:    { color:'#10b981', cls:'row-conor',     tagBg:'#d1fae5', tagFg:'#065f46' }
};
const RANK_MEDALS = ['🥇','🥈','🥉','4️⃣'];
const ASSIGNMENTS = {
  John:     ['England','Portugal','Japan','Morocco','Switzerland','Austria','Sweden','Ghana','Czech Republic','Jordan','Iraq','Haiti'],
  Muireann: ['Spain','Netherlands','Colombia','Ecuador','Senegal','Turkey','Egypt','South Korea','Bosnia and Herzegovina','Saudi Arabia','DR Congo','Cape Verde'],
  Ava:      ['Argentina','Brazil','Norway','Croatia','Mexico','Canada','Ivory Coast','Scotland','Iran','Tunisia','New Zealand','Curaçao'],
  Conor:    ['France','Germany','Belgium','United States','Uruguay','Paraguay','Algeria','Australia','Uzbekistan','South Africa','Qatar','Panama']
};
function gdCell(v){ if(v>0) return '<span class="gd-pos">+'+v+'</span>'; if(v<0) return '<span class="gd-neg">'+v+'</span>'; return '<span class="gd-nil">0</span>'; }
function render(){
  if(!STANDINGS.updated || STANDINGS.teams.length===0) return;
  if(STANDINGS.inProgress>0){ document.getElementById('warnBar').style.display='flex'; }
  document.getElementById('statusBar').innerHTML =
    '<span class="dot dot-green"></span><span>Last updated: '+STANDINGS.updated+' · '+STANDINGS.matches+' completed match'+(STANDINGS.matches!==1?'es':'')+' counted</span>';
  const sorted = [...STANDINGS.teams].sort((a,b)=>{ const gdA=a.gf-a.ga, gdB=b.gf-b.ga; return b.pts-a.pts || gdB-gdA || b.gf-a.gf || a.name.localeCompare(b.name); });
  const players = {};
  for(const [name] of Object.entries(ASSIGNMENTS)) players[name]={name,pts:0,gd:0,gf:0,p:0};
  for(const t of sorted){ const ps=players[t.owner]; if(!ps) continue; ps.pts+=t.pts; ps.gd+=(t.gf-t.ga); ps.gf+=t.gf; ps.p+=t.p; }
  const lb = Object.values(players).sort((a,b)=> b.pts-a.pts || b.gd-a.gd || b.gf-a.gf);
  document.getElementById('leaderboard').innerHTML = lb.map((p,i)=>{
    const s=STYLES[p.name]; const gdStr = p.gd>=0?('+'+p.gd):(''+p.gd);
    return '<div class="player-card" style="border-top-color:'+s.color+'">'
      +'<div style="display:flex;justify-content:space-between;align-items:flex-start">'
      +'<span class="card-rank">'+RANK_MEDALS[i]+'</span>'
      +'<span style="font-size:0.68rem;color:#94a3b8">'+p.p+' games</span></div>'
      +'<div class="card-name" style="color:'+s.color+'">'+p.name+'</div>'
      +'<div class="card-pts">'+p.pts+'</div><div class="card-label">points</div>'
      +'<div class="card-stats"><div><div class="card-stat-val">'+gdStr+'</div><div class="card-stat-label">GD</div></div>'
      +'<div><div class="card-stat-val">'+p.gf+'</div><div class="card-stat-label">Goals</div></div></div></div>';
  }).join('');
  document.getElementById('teamBody').innerHTML = sorted.map((t,i)=>{
    const s=STYLES[t.owner]; const gd=t.gf-t.ga;
    return '<tr class="'+s.cls+'"><td class="td-pos">'+(i+1)+'</td>'
      +'<td class="td-team"><span class="team-name-text">'+t.name+'</span>'
      +'<span class="owner-tag" style="background:'+s.tagBg+';color:'+s.tagFg+'">'+t.owner+'</span></td>'
      +'<td class="td-num">'+t.p+'</td><td class="td-num">'+t.w+'</td><td class="td-num">'+t.d+'</td><td class="td-num">'+t.l+'</td>'
      +'<td class="td-num">'+t.gf+'</td><td class="td-num">'+t.ga+'</td><td class="td-gd">'+gdCell(gd)+'</td>'
      +'<td class="td-pts" style="color:'+s.color+'">'+t.pts+'</td></tr>';
  }).join('');
  document.getElementById('noData').style.display='none';
  document.getElementById('mainContent').style.display='block';
}
render();
</script>
</body>
</html>
"""

if __name__ == "__main__":
    main()
