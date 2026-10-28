#!/usr/bin/env python3
"""NoSpoilDota static site builder. Usage: python3 build.py  -> writes ./site/
Data: OpenDota (recent pro matches) + Liquipedia (upcoming, CC-BY-SA 3.0, 1 req per run, cached 1h)."""
import json, re, time, html, os, urllib.request, urllib.parse, datetime as dt, hashlib
from collections import defaultdict
ROOT=os.path.dirname(os.path.abspath(__file__)); OUT=os.path.join(ROOT,'site'); CACHE=os.path.join(ROOT,'cache')
UA="NoSpoilDota/0.1 (https://unclouded77.github.io/nospoildota/; https://github.com/UnClouded77/nospoildota; non-commercial)"
os.makedirs(OUT,exist_ok=True); os.makedirs(CACHE,exist_ok=True)
def get(url,name,ttl=3600,headers={}):
    p=os.path.join(CACHE,name)
    if os.path.exists(p) and time.time()-os.path.getmtime(p)<ttl: return json.load(open(p))
    req=urllib.request.Request(url,headers={"User-Agent":UA,"Accept-Encoding":"gzip",**headers})
    with urllib.request.urlopen(req,timeout=30) as r:
        b=r.read()
        if r.headers.get("Content-Encoding")=="gzip":
            import gzip; b=gzip.decompress(b)
    d=json.loads(b); json.dump(d,open(p,'w')); return d
def slug(s):
    a=re.sub(r'[^a-z0-9]+','-',s.lower()).strip('-')[:60]
    return a if len(a)>=4 and not a[0].isdigit() else (a+'-' if a else 't-')+hashlib.md5(s.encode()).hexdigest()[:6]
def norm_t(name):  # merge "X - Playoffs" stages into one tournament
    n=re.split(r'\s+-\s+',name)[0].strip(); n=re.sub(r'(?i)\s+by\s+.*$','',n); return n.upper() if n.lower()=='pari universe' else n
def fetch_recent():
    out=[]; last=None
    for i in range(3):  # 3 pages x 100 = ~300 maps
        u="https://api.opendota.com/api/proMatches"+(f"?less_than_match_id={last}" if last else "")
        d=get(u,f"pro{i}.json"); 
        if not d: break
        out+=d; last=d[-1]['match_id']; time.sleep(1.1)
    # group maps into series; keep ONLY non-spoiler fields
    ser={}
    for m in out:
        k=m.get('series_id') or m['match_id']
        s=ser.setdefault(k,{"teams":sorted([m.get('radiant_name') or 'TBD',m.get('dire_name') or 'TBD']),"league":m.get('league_name') or 'Unknown',
            "leagueid":m['leagueid'],"start":m['start_time'],"maps":[],"bo":{0:1,1:3,2:5,3:2}.get(m.get('series_type'),1)})
        s["start"]=min(s["start"],m['start_time'])
        s["maps"].append({"id":m['match_id'],"t":m['start_time'],"win":(m['radiant_name'] if m['radiant_win'] else m['dire_name']) or '?',
                          "score":f"{m['radiant_score']}–{m['dire_score']}","dur":f"{m['duration']//60}m"})
    return out,list(ser.values())
def fetch_upcoming():
    try:
        d=get("https://liquipedia.net/dota2/api.php?action=parse&page=Liquipedia:Matches&format=json&prop=text","lp.json",ttl=3600)
        h=d['parse']['text']['*']
    except Exception as e:
        print("Liquipedia failed:",e); return []
    h=h.split('data-toggle-area-content="2"')[0]  # upcoming section only
    res=[]; seen=set()
    for blk in h.split('<div class="match-info">')[1:]:
        ts=re.search(r'data-timestamp="(\d+)"',blk)
        names=re.findall(r'<span class="name"[^>]*>(?:<a [^>]*title="([^"]+)"[^>]*>)?([^<]*)',blk)
        tn=re.search(r'match-info-tournament-name"><a [^>]*><span>([^<]+)',blk)
        bo=re.search(r'\(Bo(\d)\)',blk)
        if not ts or not tn: continue
        teams=[html.unescape(re.sub(r' \(page does not exist\)','',a) or b) for a,b in names][:2] or ['TBD','TBD']
        while len(teams)<2: teams.append('TBD')
        t=int(ts.group(1))
        key=(t,tuple(teams))
        if key in seen: continue
        seen.add(key)
        live = t < time.time()
        res.append({"teams":teams,"league":html.unescape(tn.group(1)),"start":t,"bo":int(bo.group(1)) if bo else 1,"live":live})
    return res
CSS=""":root{--bg:#0f1115;--card:#181b22;--mut:#8a93a6;--fg:#e8ebf1;--acc:#e0533d;--bd:#262a33}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
a{color:#ff8a70;text-decoration:none}a:hover{text-decoration:underline}
header{border-bottom:1px solid var(--bd);padding:14px 18px;display:flex;gap:18px;align-items:center;flex-wrap:wrap;position:sticky;top:0;background:#0f1115ee;backdrop-filter:blur(6px)}
header .logo{font-weight:800;font-size:19px;color:var(--fg)}header .logo span{color:var(--acc)}nav a{color:var(--mut);margin-right:14px}
main{max-width:920px;margin:0 auto;padding:18px}h1{font-size:24px;margin:.4em 0}h2{font-size:18px;margin:1.6em 0 .5em;color:#cfd5e2}
h3{font-size:15px;margin:1.2em 0 .4em;color:var(--mut);text-transform:uppercase;letter-spacing:.04em}
.m{background:var(--card);border:1px solid var(--bd);border-radius:10px;padding:10px 14px;margin:8px 0;display:grid;grid-template-columns:110px 1fr auto;gap:10px;align-items:center}
.m .when{color:var(--mut);font-size:13px}.m .teams{font-weight:600}.m .vs{color:var(--mut);font-weight:400;margin:0 6px}
.m .acts{display:flex;gap:8px;flex-wrap:wrap;justify-content:flex-end}.btn{font-size:12px;padding:5px 9px;border-radius:6px;border:1px solid var(--bd);background:#20242d;color:var(--fg);cursor:pointer}
.btn:hover{border-color:var(--acc);text-decoration:none}.res{grid-column:1/-1;display:none;font-size:13px;color:#ffd27a;border-top:1px dashed var(--bd);padding-top:6px}
.live{color:#ff5c5c;font-weight:700;font-size:11px;margin-left:6px}.tag{color:var(--mut);font-size:12px}
.note{background:#1a1f2a;border-left:3px solid var(--acc);padding:10px 14px;border-radius:6px;color:#c9cfdb;font-size:14px}
form input{padding:10px;border-radius:6px;border:1px solid var(--bd);background:#11141a;color:var(--fg);width:min(320px,100%)}form button{padding:10px 16px;border:0;border-radius:6px;background:var(--acc);color:#fff;font-weight:600;cursor:pointer}
footer{color:var(--mut);font-size:12px;text-align:center;padding:30px 18px;border-top:1px solid var(--bd);margin-top:40px}
@media(max-width:600px){.m{grid-template-columns:1fr}.m .acts{justify-content:flex-start}}"""
JS="""document.querySelectorAll('[data-ts]').forEach(e=>{const d=new Date(+e.dataset.ts*1000);e.textContent=d.toLocaleString([], {weekday:'short',month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'})});
document.addEventListener('click',e=>{const b=e.target.closest('.reveal');if(!b)return;const r=document.getElementById(b.dataset.for);
if(r.style.display==='block'){r.style.display='none';b.textContent='Reveal result'}else if(confirm('Show the result? This is a spoiler.')){r.style.display='block';b.textContent='Hide result'}});"""
def page(title,body,depth=0):
    p="../"*depth
    return f"""<!doctype html><html lang=en><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1"><title>{html.escape(title)} · NoSpoilDota</title>
<meta name=description content="Spoiler-free Dota 2 pro match calendar and replay finder."><link rel=stylesheet href="{p}style.css"></head><body>
<header><a class=logo href="{p}index.html">NoSpoil<span>Dota</span></a><nav><a href="{p}index.html">Matches</a><a href="{p}tournaments.html">Tournaments</a><a href="{p}newsletter.html">Newsletter</a><a href="{p}about.html">About</a></nav></header>
<main>{body}</main><footer>Match data: <a href="https://www.opendota.com">OpenDota</a> · Schedule: <a href="https://liquipedia.net/dota2/">Liquipedia</a> (CC-BY-SA 3.0) · Not affiliated with Valve. Times shown in your local timezone.</footer><script src="{p}app.js"></script></body></html>"""
def yt(league,teams):
    q=f"{norm_t(league)} {teams[0]} vs {teams[1]} full game"
    return "https://www.youtube.com/results?search_query="+urllib.parse.quote_plus(q)
def card(s,tlink,upcoming=False):
    e=html.escape; a,b=s['teams']; uid="r"+hashlib.md5(f"{s['start']}{a}{b}".encode()).hexdigest()[:8]
    head=f"<div class=when data-ts={s['start']}></div><div><div class=teams>{e(a)}<span class=vs>vs</span>{e(b)}{'<span class=live>LIVE</span>' if s.get('live') else ''}</div><div class=tag><a href='{tlink}'>{e(norm_t(s['league']))}</a> · Bo{s['bo']}</div></div>"
    if upcoming: return f"<div class=m>{head}<div class=acts></div></div>"
    # result is hidden behind a click; stored in a data block rendered hidden
    maps="<br>".join(f"Game {i+1}: {e(m['win'])} won ({m['score']} kills, {m['dur']}) · <a href='https://www.opendota.com/matches/{m['id']}'>OpenDota</a>" for i,m in enumerate(sorted(s['maps'],key=lambda m:m['t'])))
    return f"<div class=m>{head}<div class=acts><a class=btn href='{yt(s['league'],s['teams'])}' target=_blank rel=noopener>▶ Find VOD</a><button class='btn reveal' data-for={uid}>Reveal result</button></div><div class=res id={uid}>{maps}</div></div>"
def build():
    raw,recent=fetch_recent(); up=fetch_upcoming()
    tours=defaultdict(lambda:{"up":[],"done":[]})
    for s in up: tours[norm_t(s['league'])]["up"].append(s)
    for s in recent: tours[norm_t(s['league'])]["done"].append(s)
    tl=lambda n,d=0:("../"*d)+f"t/{slug(n)}.html"
    def grouped(items,key,upc,depth=0):
        g=defaultdict(list)
        for s in items: g[norm_t(s['league'])].append(s)
        order=sorted(g,key=lambda n:(min if upc else max)(x['start'] for x in g[n]),reverse=not upc)
        return "".join(f"<h3><a href='{tl(n,depth)}'>{html.escape(n)}</a></h3>"+"".join(card(s,tl(n,depth),upc) for s in sorted(g[n],key=lambda x:x['start'],reverse=not upc)) for n in order)
    now=time.time(); upn=[s for s in up if s['start']<now+7*86400]
    body=("<div class=note>Spoiler-free by default: no winners, scores, durations or kills. Use <b>Find VOD</b> to search for the replay, and <b>Reveal result</b> only if you want to know.</div>"
          f"<h2>Upcoming & live (next 7 days)</h2>{grouped(upn,0,True) or '<p class=tag>No upcoming matches found.</p>'}"
          f"<h2>Recently finished</h2>{grouped(sorted(recent,key=lambda s:-s['start'])[:60],0,False)}")
    open(f"{OUT}/index.html","w").write(page("Matches",body))
    os.makedirs(f"{OUT}/t",exist_ok=True)
    for n,v in tours.items():
        b=f"<h1>{html.escape(n)}</h1><p class=tag><a href='https://liquipedia.net/dota2/index.php?search={urllib.parse.quote_plus(n)}'>Tournament info on Liquipedia</a> (may contain spoilers)</p>"
        b+="<h2>Upcoming</h2>"+("".join(card(s,tl(n,1),True) for s in sorted(v['up'],key=lambda x:x['start'])) or "<p class=tag>None scheduled.</p>")
        b+="<h2>Finished</h2>"+("".join(card(s,tl(n,1)) for s in sorted(v['done'],key=lambda x:-x['start'])) or "<p class=tag>None yet.</p>")
        open(f"{OUT}/{tl(n)}","w").write(page(n,b,1))
    lst="".join(f"<div class=m><div class=tag>{len(v['up'])} upcoming</div><div class=teams><a href='{tl(n)}'>{html.escape(n)}</a></div><div class=tag>{len(v['done'])} finished</div></div>" for n,v in sorted(tours.items(),key=lambda kv:-max([x['start'] for x in kv[1]['up']+kv[1]['done']])))
    open(f"{OUT}/tournaments.html","w").write(page("Tournaments","<h1>Tournaments</h1>"+lst))
    open(f"{OUT}/about.html","w").write(page("About",f"""<h1>About NoSpoilDota</h1><p>NoSpoilDota is a spoiler-free calendar of professional Dota 2 matches. Watch the VOD without seeing who won first.</p>
<h2>Data & attribution</h2><ul><li>Finished matches: <a href="https://www.opendota.com">OpenDota</a> public API (<code>/api/proMatches</code>).</li>
<li>Upcoming schedule: <a href="https://liquipedia.net/dota2/Liquipedia:Matches">Liquipedia Dota 2</a>, licensed <a href="https://creativecommons.org/licenses/by-sa/3.0/">CC-BY-SA 3.0</a>. Fetched at most once per hour with an identifying User-Agent, per Liquipedia's API terms.</li>
<li>VOD links are YouTube searches; results/thumbnails there may contain spoilers.</li></ul><p>Dota 2 is a trademark of Valve Corporation. This site is not affiliated with Valve, OpenDota or Liquipedia.</p>
<p class=tag>Last built: {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC</p>"""))
    open(f"{OUT}/newsletter.html","w").write(page("Newsletter","""<h1>Weekly spoiler-free digest</h1><p>Get the week's biggest series and VOD links in your inbox. No results, ever.</p>
<form onsubmit="event.preventDefault();this.innerHTML='<p>Thanks! (Placeholder: signups are not stored yet.)</p>'"><input type=email required placeholder="you@example.com"> <button>Subscribe</button></form><p class=tag>Placeholder form: no backend connected.</p>"""))
    open(f"{OUT}/style.css","w").write(CSS); open(f"{OUT}/app.js","w").write(JS)
    stats={"opendota_maps":len(raw),"opendota_series":len(recent),"liquipedia_upcoming":len(up),"upcoming_7d":len(upn),"tournaments":len(tours)}
    json.dump(stats,open(f"{OUT}/stats.json","w")); print(stats)
if __name__=="__main__": build()
