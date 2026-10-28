#!/usr/bin/env python3
"""NoSpoilDota static site builder. Usage: python3 build.py  -> writes ./site/
Data: OpenDota /proMatches (finished maps) + Liquipedia MatchTicker via the parse API
(upcoming/live + tiers, CC-BY-SA 3.0; ONE request per build with an identifying UA, cached 1h)."""
import json, re, time, html, os, urllib.request, urllib.parse, datetime as dt, hashlib, unicodedata
from collections import defaultdict
ROOT=os.path.dirname(os.path.abspath(__file__)); OUT=os.path.join(ROOT,'site'); CACHE=os.path.join(ROOT,'cache')
UA="NoSpoilDota/0.2 (https://unclouded77.github.io/nospoildota/; https://github.com/UnClouded77/nospoildota; non-commercial)"
SITE="https://unclouded77.github.io/nospoildota/"
os.makedirs(OUT,exist_ok=True); os.makedirs(CACHE,exist_ok=True)
e=html.escape
def get(url,name,ttl=3600,data=None):
    p=os.path.join(CACHE,name)
    if os.path.exists(p) and time.time()-os.path.getmtime(p)<ttl: return json.load(open(p))
    req=urllib.request.Request(url,data=data,headers={"User-Agent":UA,"Accept-Encoding":"gzip"})
    with urllib.request.urlopen(req,timeout=30) as r:
        b=r.read()
        if r.headers.get("Content-Encoding")=="gzip":
            import gzip; b=gzip.decompress(b)
    d=json.loads(b); json.dump(d,open(p,'w')); return d
def slug(s):
    a=re.sub(r'[^a-z0-9]+','-',s.lower()).strip('-')[:60]
    return a if len(a)>=4 and not a[0].isdigit() else (a+'-' if a else 't-')+hashlib.md5(s.encode()).hexdigest()[:6]

# ---------- name normalization (OpenDota <-> Liquipedia) ----------
def _fold(s):
    s=unicodedata.normalize('NFKD',s or '').encode('ascii','ignore').decode().lower()
    return re.sub(r'[^a-z0-9 ]+',' ',s)
TEAM_STOP={'team','gaming','esports','esport','gg','club','the'}
TEAM_ALIAS={'tspirit':'spirit','bb':'betboom','pari':'parivision','vp':'virtuspro','gl':'gamerlegion','nigma':'nigmagalaxy',
            'z10':'zerotenacity','db':'direborn','tundraesports':'tundra','liquid':'liquid'}
def team_key(n):
    raw=(n or '').strip()
    if not raw or raw.lower() in('tbd','none'): return 'tbd'
    f=_fold(raw).strip()
    if not f: return 'u'+hashlib.md5(raw.encode()).hexdigest()[:8]  # non-latin names
    toks=[t for t in f.split() if t not in TEAM_STOP] or f.split()
    k=''.join(toks); return TEAM_ALIAS.get(k,k)
def tour_name(name):  # merge "X - Playoffs" / "X - October 24" stages, drop "by Sponsor"
    n=re.split(r'\s+-\s+',(name or 'Unknown').strip())[0].strip(); n=re.sub(r'(?i)\s+by\s+.*$','',n).strip()
    return n.upper() if n.lower()=='pari universe' else n
def tour_key(name):
    n=tour_name(name).lower()
    if 'сбер' in n or 'sber' in n: return 'sber'
    f=_fold(n)
    f=re.sub(r'\b(19|20)\d\d\b|\bseason\b|\bs\d+\b|\b[ivx]+\b|\b\d+\b|\bclosed qualifiers?\b|\bseries\b',' ',f)
    f=' '.join(f.split()); f={'epl world southeast asia':'epl world sea'}.get(f,f)
    return f or n

# ---------- data ----------
def fetch_recent():
    out=[]; last=None
    for i in range(3):  # 3 pages x 100 maps
        u="https://api.opendota.com/api/proMatches"+(f"?less_than_match_id={last}" if last else "")
        try: d=get(u,f"pro{i}.json")
        except Exception as x: print("OpenDota failed:",x); break
        if not d: break
        out+=d; last=d[-1]['match_id']; time.sleep(1.1)
    ser={}
    for m in out:
        k=m.get('series_id') or m['match_id']
        rn,dn=(m.get('radiant_name') or 'TBD').strip(),(m.get('dire_name') or 'TBD').strip()
        s=ser.setdefault(k,{"teams":sorted([rn,dn],key=str.lower),"league":m.get('league_name') or 'Unknown',"leagueid":m['leagueid'],
            "start":m['start_time'],"maps":[],"bo":{0:1,1:3,2:5,3:2}.get(m.get('series_type'),1)})
        s["start"]=min(s["start"],m['start_time'])
        s["maps"].append({"id":m['match_id'],"t":m['start_time'],"win":(rn if m['radiant_win'] else dn),
                          "score":f"{m['radiant_score']}–{m['dire_score']}","dur":f"{(m.get('duration') or 0)//60}m"})
    return out,list(ser.values())
LP_TEXT="".join(f'<div id="nsd-tier-{t}">{{{{#invoke:Lua|invoke|module=MatchTicker/Custom|fn=mainPage|dev=false|type=upcoming|limit=60|filterbuttons-liquipediatier={t}}}}}</div>' for t in (1,2,3,4))
def fetch_upcoming():
    """ONE Liquipedia parse request that renders the match ticker once per tier, so each match carries its tier."""
    try:
        data=urllib.parse.urlencode({"action":"parse","format":"json","prop":"text","contentmodel":"wikitext","disablelimitreport":1,"text":LP_TEXT}).encode()
        h=get("https://liquipedia.net/dota2/api.php","lp_tiers.json",ttl=3600,data=data)['parse']['text']['*']
    except Exception as x:
        print("Liquipedia failed:",x); return []
    res=[]; seen=set()
    parts=re.split(r'<div id="nsd-tier-(\d)">',h)
    for tier,chunk in zip(parts[1::2],parts[2::2]):
        for blk in chunk.split('<div class="match-info">')[1:]:
            ts=re.search(r'data-timestamp="(\d+)"',blk)
            names=re.findall(r'<span class="name"[^>]*>(?:<a [^>]*title="([^"]+)"[^>]*>)?([^<]*)',blk)
            tn=re.search(r'match-info-tournament-name"><a [^>]*><span>([^<]+)',blk)
            tl=re.search(r'match-info-tournament-name"><a href="(/dota2/[^"#]+)',blk)
            bo=re.search(r'\(Bo(\d)\)',blk)
            if not ts or not tn: continue
            teams=[(html.unescape(re.sub(r'\s*\((page does not exist|stack)\)','',re.sub(r'\s*\(page does not exist\)','',a))) or b).strip() or 'TBD' for a,b in names][:2]
            while len(teams)<2: teams.append('TBD')
            streams=sorted(set(re.findall(r'href="/dota2/Special:Stream/([a-z]+)/([^"]+)"',blk)))
            t=int(ts.group(1)); key=(t,tuple(team_key(x) for x in teams),tour_key(tn.group(1)))
            if key in seen: continue
            seen.add(key)
            res.append({"teams":teams,"league":html.unescape(tn.group(1)),"lp":tl.group(1) if tl else None,"start":t,
                        "bo":int(bo.group(1)) if bo else 1,"tier":int(tier),"streams":streams})
    return res

# ---------- presentation ----------
CSS=""":root{--bg:#0f1115;--card:#181b22;--mut:#9aa3b5;--fg:#e8ebf1;--acc:#e0533d;--bd:#2a2f3a;--live:#e5302f}
*{box-sizing:border-box}html{-webkit-text-size-adjust:100%}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
a{color:#ff9a82;text-decoration:none}a:hover{text-decoration:underline}:focus-visible{outline:2px solid #ffb199;outline-offset:2px}
.skip{position:absolute;left:-9999px}.skip:focus{left:8px;top:8px;background:#000;padding:6px;z-index:9}
header{border-bottom:1px solid var(--bd);padding:10px 16px;display:flex;gap:6px 18px;align-items:center;flex-wrap:wrap;position:sticky;top:0;background:#0f1115f2;z-index:5}
header .logo{font-weight:800;font-size:19px;color:var(--fg)}header .logo span{color:var(--acc)}nav{display:flex;flex-wrap:wrap;gap:4px 14px}nav a{color:var(--mut)}nav a[aria-current]{color:var(--fg)}
main{max-width:920px;margin:0 auto;padding:14px 16px}h1{font-size:23px;margin:.3em 0}h2{font-size:18px;margin:1.4em 0 .4em;color:#d5dae6}
h3{font-size:13px;margin:1.1em 0 .3em;color:var(--mut);text-transform:uppercase;letter-spacing:.04em}h3 a{color:inherit}
.tier{font-size:10px;border:1px solid var(--bd);border-radius:4px;padding:0 4px;margin-left:6px;color:var(--mut);vertical-align:1px;letter-spacing:0}
.m{background:var(--card);border:1px solid var(--bd);border-radius:10px;padding:9px 12px;margin:6px 0;display:grid;grid-template-columns:150px 1fr auto;gap:4px 12px;align-items:center}
.m.is-live{border-color:#8a2b2b;background:#1e1618}
.when{font-size:13px;color:var(--mut)}.when .rel{display:block;color:var(--fg);font-weight:600}
.teams{font-weight:600}.teams a{color:var(--fg)}.vs{color:var(--mut);font-weight:400;margin:0 6px}
.acts{display:flex;gap:6px;flex-wrap:wrap;justify-content:flex-end}
.btn{font:inherit;font-size:12.5px;padding:6px 10px;border-radius:6px;border:1px solid var(--bd);background:#222733;color:var(--fg);cursor:pointer;min-height:32px;display:inline-flex;align-items:center}
.btn:hover{border-color:var(--acc);text-decoration:none}.btn.ghost{background:none;color:var(--mut)}.btn.mini{min-height:0;padding:0 6px;font-size:11px}
.res{grid-column:1/-1;font-size:13px;color:#ffd27a;border-top:1px dashed var(--bd);padding-top:6px;margin-top:4px}.res[hidden]{display:none}.res code{color:#fff;background:#0007;padding:0 4px;border-radius:3px}
.badge{display:inline-block;background:var(--live);color:#fff;font-weight:800;font-size:11px;letter-spacing:.06em;border-radius:4px;padding:1px 6px;margin-left:8px;vertical-align:2px}
.badge::before{content:"● "}.tag{color:var(--mut);font-size:12.5px}
.note{background:#1a1f2a;border-left:3px solid var(--acc);padding:8px 12px;border-radius:6px;color:#c9cfdb;font-size:13.5px;margin:6px 0}
.filters{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:12px 0 4px;padding:10px;background:#141821;border:1px solid var(--bd);border-radius:10px}
.filters fieldset{border:0;margin:0;padding:0;display:flex;gap:4px;flex-wrap:wrap}.filters legend{position:absolute;left:-9999px}
.pill{cursor:pointer;position:relative}.pill input{position:absolute;opacity:0;width:1px;height:1px}.pill span{display:inline-block;padding:6px 11px;border-radius:16px;border:1px solid var(--bd);font-size:13px;color:var(--mut)}
.pill input:checked+span{background:var(--acc);border-color:var(--acc);color:#fff}.pill input:focus-visible+span{outline:2px solid #ffb199}
.filters input[type=search]{flex:1;min-width:170px;padding:8px 10px;border-radius:8px;border:1px solid var(--bd);background:#0f1115;color:var(--fg);font:inherit}
details.tbd{margin:6px 0;color:var(--mut);font-size:13px;border:1px dashed var(--bd);border-radius:10px;padding:6px 12px}details.tbd summary{cursor:pointer}details.tbd ul{margin:6px 0;padding-left:18px}
.empty{color:var(--mut);font-size:13px;font-style:italic}.hide{display:none!important}.sect:has([data-tier]:not(.hide)) .empty{display:none}
.sr{position:absolute;left:-9999px}
.signup{margin:2.5em 0 0;padding:10px 0;border-top:1px solid var(--bd);color:var(--mut);font-size:13px}.signup summary{cursor:pointer}.signup form{margin-top:8px}
form input[type=email]{padding:8px;border-radius:6px;border:1px solid var(--bd);background:#11141a;color:var(--fg);width:min(280px,100%)}form button{padding:8px 12px;border:1px solid var(--bd);border-radius:6px;background:#222733;color:var(--fg);cursor:pointer}
.teamlist{columns:3 180px;padding:0;list-style:none}.teamlist li{padding:2px 0;break-inside:avoid}
footer{color:var(--mut);font-size:12px;text-align:center;padding:24px 16px;border-top:1px solid var(--bd);margin-top:30px}
@media(max-width:640px){.m{grid-template-columns:1fr}.m .when{display:flex;gap:8px;align-items:baseline;flex-wrap:wrap}.m .when .rel{display:inline}.acts{justify-content:flex-start}main{padding:10px 12px}}"""
JS=r"""(()=>{const now=Date.now()/1000,fmt=new Intl.DateTimeFormat([], {weekday:'short',month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'}),
tf=new Intl.DateTimeFormat([], {hour:'2-digit',minute:'2-digit'}),day=d=>{const x=new Date(d);x.setHours(0,0,0,0);return x.getTime()};
function rel(ts,kind){const d=ts-now,a=Math.abs(d),dd=Math.round((day(ts*1000)-day(Date.now()))/864e5),t=tf.format(new Date(ts*1000));
 if(kind==='live')return'Live now';
 if(d>0){if(a<3600)return'in '+Math.max(1,Math.round(a/60))+' min';if(a<6*3600)return'in '+Math.round(a/3600)+'h';if(dd===0)return'today '+t;if(dd===1)return'starts tomorrow';return'in '+dd+' days'}
 if(kind==='up')return'starting soon';if(a<3600)return Math.round(a/60)+' min ago';if(a<86400)return Math.round(a/3600)+'h ago';if(dd===-1)return'yesterday';return Math.round(a/86400)+' days ago'}
document.querySelectorAll('[data-ts]').forEach(e=>{const ts=+e.dataset.ts,full=fmt.format(new Date(ts*1000)),r=rel(ts,e.dataset.kind);
 e.textContent='';if(r){const s=document.createElement('span');s.className='rel';s.textContent=r;e.append(s,' ')}e.append(full);e.title=full});
const tz=document.getElementById('tzname');if(tz)tz.textContent=Intl.DateTimeFormat().resolvedOptions().timeZone||'local time';
document.addEventListener('click',ev=>{const b=ev.target.closest('.reveal');if(b){const r=document.getElementById(b.dataset.for);
 if(!r.hidden){r.hidden=true;b.textContent='Reveal result';b.setAttribute('aria-expanded','false')}else if(confirm('Show the result? This is a spoiler.')){r.hidden=false;b.textContent='Hide result';b.setAttribute('aria-expanded','true')}return}
 const w=ev.target.closest('[data-warn]');if(w&&!confirm('Heads up: '+w.dataset.warn+' search results and thumbnails often show the score or winner. Open anyway?'))ev.preventDefault();
 const c=ev.target.closest('.copy');if(c&&navigator.clipboard){navigator.clipboard.writeText(c.dataset.copy);c.textContent='copied'}});
const F=document.getElementById('filters');if(!F)return;
const items=[...document.querySelectorAll('[data-tier]')],q=F.querySelector('input[type=search]');let saved=null;try{saved=localStorage.getItem('nsd-tier')}catch(_){}
const sv=saved&&F.querySelector(`input[value="${saved}"]`);if(sv)sv.checked=true;
function apply(){const tv=F.querySelector('input[name=tier]:checked').value,max=tv==='all'?9:+tv,s=q.value.trim().toLowerCase();try{localStorage.setItem('nsd-tier',tv)}catch(_){}
 items.forEach(el=>{const ok=(+el.dataset.tier<=max)&&(!s||el.dataset.search.includes(s));el.classList.toggle('hide',!ok)});
 document.querySelectorAll('.grp').forEach(g=>g.classList.toggle('hide',!g.querySelector('[data-tier]:not(.hide)')));
 document.querySelectorAll('.sect').forEach(sc=>{const any=sc.querySelector('[data-tier]:not(.hide)'),em=sc.querySelector('.empty');if(em)em.style.display=any?'none':'block'})}
F.addEventListener('change',apply);q.addEventListener('input',apply);apply()})();"""
BD="nospoildota"
def signup(compact=True):
    f=f"""<form action="https://buttondown.com/api/emails/embed-subscribe/{BD}" method="post" target="popupwindow" onsubmit="window.open('https://buttondown.com/{BD}', 'popupwindow')"><label for=bd-email class=sr>Email</label><input type=email name="email" id=bd-email required placeholder="you@example.com"> <button type=submit>Subscribe</button></form>"""
    if compact: return f"<details class=signup><summary>Optional: a weekly spoiler-free “what to watch” email</summary>{f}</details>"
    return f
NAV=[("index.html","Matches"),("tournaments.html","Tournaments"),("teams.html","Teams"),("about.html","About")]
def page(title,body,depth=0,cur=None):
    p="../"*depth
    nav="".join(f"<a href='{p}{h}'{' aria-current=page' if h==cur else ''}>{t}</a>" for h,t in NAV)
    return f"""<!doctype html><html lang=en><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1"><title>{e(title)} · NoSpoilDota</title>
<meta name=description content="Spoiler-free Dota 2 pro match calendar and replay finder."><meta name=color-scheme content=dark><link rel=stylesheet href="{p}style.css"></head><body>
<a class=skip href="#main">Skip to content</a><header><a class=logo href="{p}index.html">NoSpoil<span>Dota</span></a><nav aria-label=Main>{nav}</nav></header>
<main id=main>{body}</main><footer>Match data: <a href="https://www.opendota.com">OpenDota</a> · Schedule, tiers &amp; streams: <a href="https://liquipedia.net/dota2/">Liquipedia</a> (<a href="https://creativecommons.org/licenses/by-sa/3.0/">CC-BY-SA 3.0</a>) · Not affiliated with Valve · Times in your timezone (<span id=tzname>local</span>) · <a href="{p}newsletter.html">Newsletter</a></footer><script src="{p}app.js" defer></script></body></html>"""

def stream_url(pl,ch): return f"https://liquipedia.net/dota2/Special:Stream/{pl}/{urllib.parse.quote(ch)}"
def watch_links(s):
    a,b=s['teams']; tn=s['tname']; st=s.get('streams',[]); out=[]
    for pl,ch in st[:2]:
        if pl=='twitch':
            out.append(f"<a class=btn href='https://www.twitch.tv/{urllib.parse.quote(ch.replace(' ','_').lower())}/videos?filter=archives&amp;sort=time' target=_blank rel=noopener title='Official broadcaster: past broadcasts ({e(ch)})'>▶ Official VODs (Twitch)</a>")
        else:
            lab={'kick':'Kick','youtube':'YouTube'}.get(pl,pl.title())
            out.append(f"<a class=btn href='{stream_url(pl,ch)}' target=_blank rel=noopener title='Official channel ({e(ch)}) via Liquipedia'>▶ Official {lab} channel</a>")
    q=urllib.parse.quote_plus(f"{tn} {a} vs {b}")
    out.append(f"<a class='btn ghost' href='https://www.youtube.com/results?search_query={q}' target=_blank rel=noopener data-warn=YouTube>YouTube search ⚠</a>")
    if not any(pl=='twitch' for pl,_ in st):
        out.append(f"<a class='btn ghost' href='https://www.twitch.tv/search?term={urllib.parse.quote(tn)}&amp;type=videos' target=_blank rel=noopener data-warn=Twitch>Twitch search ⚠</a>")
    return "".join(out)
def card(s,d,ctx,TEAMS):
    a,b=s['teams']; uid="r"+hashlib.md5(f"{s['start']}{a}{b}{s['tname']}".encode()).hexdigest()[:8]
    live=s.get('live'); kind='live' if live else ('up' if ctx=='up' else 'done')
    tn=lambda x: e(x) if team_key(x) not in TEAMS else f"<a href='{'../'*d}team/{slug(TEAMS[team_key(x)])}.html'>{e(x)}</a>"
    tier=f"<span class=tier title='Liquipedia tier {s['tier']}'>T{s['tier']}</span>" if s.get('tier') else ""
    head=(f"<div class=when data-ts={s['start']} data-kind={kind}></div><div><div class=teams>{tn(a)}<span class=vs>vs</span>{tn(b)}"
          f"{'<span class=badge>LIVE</span>' if live else ''}</div><div class=tag><a href='{'../'*d}t/{slug(s['tname'])}.html'>{e(s['tname'])}</a> · Bo{s['bo']}{tier}</div></div>")
    attrs=f"class='m{' is-live' if live else ''}' data-tier={s.get('tier') or 9} data-search=\"{e(f'{a} {b} {s[chr(116)+"name"]}'.lower())}\""
    if ctx=='up':
        acts=""
        if s.get('streams'): acts=f"<a class='btn{'' if live else ' ghost'}' href='{stream_url(*s['streams'][0])}' target=_blank rel=noopener>{'▶ Watch live' if live else 'Stream'}</a>"
        return f"<div {attrs}>{head}<div class=acts>{acts}</div></div>"
    maps="<br>".join(f"Game {i+1}: <b>{e(m['win'])}</b> won ({m['score']} kills, {m['dur']}) · match ID <code>{m['id']}</code> <button class='btn ghost mini copy' data-copy={m['id']}>copy</button> · <a href='https://www.opendota.com/matches/{m['id']}'>OpenDota</a> · <a href='https://www.dotabuff.com/matches/{m['id']}'>Dotabuff</a>"
                  for i,m in enumerate(sorted(s['maps'],key=lambda m:m['t'])))
    maps+="<br><span class=tag>In-game replay (DotaTV): Dota 2 → Watch → Replays → search the match ID (replays are kept for about two weeks).</span>"
    return (f"<div {attrs}>{head}<div class=acts>{watch_links(s)}<button class='btn reveal' data-for={uid} aria-expanded=false aria-controls={uid}>Reveal result</button></div>"
            f"<div class=res id={uid} hidden>{maps}</div></div>")
def tbd_block(items):
    if not items: return ""
    li="".join(f"<li><span data-ts={s['start']} data-kind=up></span> · {e(' vs '.join(s['teams']))} · Bo{s['bo']}</li>" for s in sorted(items,key=lambda x:x['start']))
    t=min((s.get('tier') or 9) for s in items); n=len(items)
    return f"<details class=tbd data-tier={t} data-search=\"{e(items[0]['tname'].lower())} tbd\"><summary>+ {n} later-round slot{'s' if n>1 else ''}, teams TBD</summary><ul>{li}</ul></details>"
def ics(name,items,url):
    f=lambda ts: dt.datetime.fromtimestamp(ts,dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    esc=lambda x: re.sub(r'([,;\\])',r'\\\1',x).replace('\n','\\n')
    stamp=f(time.time()); L=["BEGIN:VCALENDAR","VERSION:2.0","PRODID:-//NoSpoilDota//EN","CALSCALE:GREGORIAN","METHOD:PUBLISH",f"X-WR-CALNAME:{esc(name)} (NoSpoilDota)","X-PUBLISHED-TTL:PT2H","REFRESH-INTERVAL;VALUE=DURATION:PT2H"]
    for s in sorted(items,key=lambda x:x['start']):
        uid=hashlib.md5(f"{s['start']}|{s['tk']}|{'|'.join(sorted(map(team_key,s['teams'])))}".encode()).hexdigest()
        L+=["BEGIN:VEVENT",f"UID:{uid}@nospoildota",f"DTSTAMP:{stamp}",f"DTSTART:{f(s['start'])}",f"DURATION:PT{max(1,s['bo'])}H",
            "SUMMARY:"+esc(f"{s['teams'][0]} vs {s['teams'][1]} (Bo{s['bo']}) · {s['tname']}"),
            "DESCRIPTION:"+esc("Spoiler-free, no results. Watch links: "+url),f"URL:{url}","END:VEVENT"]
    L.append("END:VCALENDAR")
    return "\r\n".join(x if len(x)<=74 else "\r\n ".join(x[i:i+70] for i in range(0,len(x),70)) for x in L)+"\r\n"

def build():
    raw,recent=fetch_recent(); up=fetch_upcoming(); now=time.time()
    TN,TT,TS,TL={},{},defaultdict(set),{}
    for s in up:
        k=tour_key(s['league']); TN.setdefault(k,tour_name(s['league'])); TT[k]=min(TT.get(k,9),s['tier']); TS[k]|=set(s['streams'])
        if s.get('lp'): TL.setdefault(k,s['lp'].split('/dota2/')[1].split('/')[0])
    for s in recent: TN.setdefault(tour_key(s['league']),tour_name(s['league']))
    TEAMN={}  # canonical team display names, Liquipedia's full names first
    for s in up+recent:
        for t in s['teams']: TEAMN.setdefault(team_key(t),t)
    for s in up+recent:
        k=tour_key(s['league']); s['tk']=k; s['tname']=TN[k]; s['tier']=TT.get(k) or s.get('tier')
        s['teams']=['TBD' if team_key(t)=='tbd' else TEAMN[team_key(t)] for t in s['teams']]; s['pair']=frozenset(map(team_key,s['teams']))
        s['streams']=sorted(TS.get(k,()))
    # One series = one place: a Liquipedia match with OpenDota maps already (same teams, start within 3h) is LIVE and hidden from "finished".
    used=set()
    for s in up:
        s['live']=s['start']<=now
        if s['pair']=={'tbd'}: continue
        for i,r in enumerate(recent):
            if r['pair']==s['pair'] and abs(r['start']-s['start'])<=3*3600:
                s['live']=True; used.add(i)
    recent=[r for i,r in enumerate(recent) if i not in used]
    TEAMS={k:v for k,v in TEAMN.items() if k!='tbd'}
    upcoming=[s for s in up if s['start']<now+7*86400]; live=[s for s in upcoming if s['live']]; soon=[s for s in upcoming if not s['live']]
    def section(items,ctx,d=0,by_t=True,limit=None):
        items=sorted(items,key=lambda x:x['start'],reverse=(ctx=='done'))[:limit]
        if not by_t:
            return "".join(card(s,d,ctx,TEAMS) for s in items if s['pair']!={'tbd'})+tbd_block([s for s in items if s['pair']=={'tbd'}])
        g=defaultdict(list)
        for s in items: g[s['tk']].append(s)
        out=""
        for k in sorted(g,key=lambda k:(min(x['start'] for x in g[k]) if ctx!='done' else -max(x['start'] for x in g[k]))):
            tier=f"<span class=tier>T{TT[k]}</span>" if TT.get(k) else ""
            out+=(f"<div class=grp><h3><a href='{'../'*d}t/{slug(TN[k])}.html'>{e(TN[k])}</a>{tier}</h3>"
                  +"".join(card(s,d,ctx,TEAMS) for s in g[k] if s['pair']!={'tbd'})+tbd_block([s for s in g[k] if s['pair']=={'tbd'}])+"</div>")
        return out
    sect=lambda h,inner,empty,idn: f"<section class=sect aria-labelledby={idn}><h2 id={idn}>{h}</h2>{inner}<p class=empty>{empty}</p></section>"
    has_top=any((s.get('tier') or 9)<=2 for s in upcoming)
    radio=lambda v,l,chk: f"<label class=pill><input type=radio name=tier value={v}{' checked' if chk else ''}><span>{l}</span></label>"
    filt=(f"<form id=filters class=filters role=search onsubmit='return false'><fieldset><legend>Tier</legend>{radio(1,'Tier 1',False)}{radio(2,'Tier 1–2',has_top)}{radio(3,'Tier 1–3',False)}{radio('all','All',not has_top)}</fieldset>"
          "<label for=q class=sr>Filter by team or tournament</label><input id=q type=search placeholder='Search team or tournament…' autocomplete=off></form>"
          "<p class=tag>Tiers from Liquipedia. Leagues it doesn’t list only appear under “All”.</p>")
    body=("<p class=note><b>Spoiler-free:</b> no winners, scores or game lengths. Results stay hidden until you press <b>Reveal result</b>.</p>"+filt
          +sect("Live now",section(live,'up'),"Nothing live right now for this filter.","h-live")
          +sect("Upcoming · next 7 days",section(soon,'up'),"No upcoming matches for this filter.","h-up")
          +sect("Recently finished",section(recent,'done',limit=80),"No finished series for this filter. Try “All”.","h-done")+signup())
    open(f"{OUT}/index.html","w").write(page("Matches",body,0,"index.html"))
    for d_ in ("t","team","cal/t","cal/team"): os.makedirs(f"{OUT}/{d_}",exist_ok=True)
    tours=defaultdict(lambda:{"up":[],"done":[]})
    for s in up: tours[s['tk']]["up"].append(s)
    for s in recent: tours[s['tk']]["done"].append(s)
    for k,v in tours.items():
        n=TN[k]; sl=slug(n); url=f"{SITE}t/{sl}.html"
        lp=f"https://liquipedia.net/dota2/{TL[k]}" if k in TL else f"https://liquipedia.net/dota2/index.php?search={urllib.parse.quote_plus(n)}"
        strm=" · ".join(f"<a href='{stream_url(pl,ch)}' target=_blank rel=noopener>{e(ch)} ({pl})</a>" for pl,ch in sorted(TS.get(k,()))) or "not listed"
        b=(f"<h1>{e(n)}{f' <span class=tier>Tier {TT[k]}</span>' if TT.get(k) else ''}</h1><p class=tag>Official streams: {strm}<br>"
           f"<a href='../cal/t/{sl}.ics'>📅 Add this tournament to your calendar (.ics)</a> · <a href='{lp}' rel=noopener>Liquipedia page</a> (shows results)</p>"
           +sect("Live &amp; upcoming",section(v['up'],'up',1,False),"None scheduled.","h-up")+sect("Finished",section(v['done'],'done',1,False),"None yet.","h-done"))
        open(f"{OUT}/t/{sl}.html","w").write(page(n,b,1))
        open(f"{OUT}/cal/t/{sl}.ics","w",newline="").write(ics(n,[s for s in v['up']+v['done'] if s['pair']!={'tbd'}],url))
    act=lambda v:max(x['start'] for x in v['up']+v['done'])
    lst="".join(f"<div class=m><div class=tag>{len(v['up'])} upcoming · {len(v['done'])} finished</div><div class=teams><a href='t/{slug(TN[k])}.html'>{e(TN[k])}</a>{f'<span class=tier>T{TT[k]}</span>' if TT.get(k) else ''}</div><div class=acts><a class='btn ghost' href='cal/t/{slug(TN[k])}.ics'>📅 .ics</a></div></div>" for k,v in sorted(tours.items(),key=lambda kv:-act(kv[1])))
    open(f"{OUT}/tournaments.html","w").write(page("Tournaments","<h1>Tournaments</h1>"+lst,0,"tournaments.html"))
    tm=defaultdict(lambda:{"up":[],"done":[]})
    for s in up:
        for t in s['pair']-{'tbd'}: tm[t]["up"].append(s)
    for s in recent:
        for t in s['pair']-{'tbd'}: tm[t]["done"].append(s)
    for k,v in tm.items():
        n=TEAMS[k]; sl=slug(n); url=f"{SITE}team/{sl}.html"
        b=(f"<h1>{e(n)}</h1><p class=tag><a href='../cal/team/{sl}.ics'>📅 Add {e(n)}’s matches to your calendar (.ics)</a> · spoiler-free: no results or standings.</p>"
           +sect("Live &amp; upcoming",section(v['up'],'up',1,False),"Nothing on Liquipedia’s ticker right now.","h-up")
           +sect("Recent series",section(v['done'],'done',1,False),"No recent series in OpenDota’s feed.","h-done"))
        open(f"{OUT}/team/{sl}.html","w").write(page(n,b,1))
        open(f"{OUT}/cal/team/{sl}.ics","w",newline="").write(ics(n,v['up']+v['done'],url))
    tl="".join(f"<li><a href='team/{slug(TEAMS[k])}.html'>{e(TEAMS[k])}</a> <span class=tag>{len(tm[k]['up'])} upcoming · {len(tm[k]['done'])} recent</span></li>" for k in sorted(tm,key=lambda k:TEAMS[k].lower()))
    open(f"{OUT}/teams.html","w").write(page("Teams","<h1>Teams</h1><p class=tag>Every team page has a spoiler-free schedule and a calendar feed.</p><ul class=teamlist>"+tl+"</ul>",0,"teams.html"))
    keep={"t":{slug(TN[k]) for k in tours},"team":{slug(TEAMS[k]) for k in tm}}
    for d_ in ("t","team","cal/t","cal/team"):  # prune stale pages from earlier local builds
        for x in os.listdir(f"{OUT}/{d_}"):
            if x.rsplit('.',1)[0] not in keep[d_.split('/')[-1]]: os.remove(f"{OUT}/{d_}/{x}")
    open(f"{OUT}/about.html","w").write(page("About",f"""<h1>About NoSpoilDota</h1><p>A spoiler-free calendar of professional Dota 2 matches. Find the VOD without seeing who won first.</p>
<h2>How it stays spoiler-free</h2><ul><li>Lists show only teams, tournament, start time and best-of. Winners, scores, kills and game lengths stay hidden until you press <b>Reveal result</b> and confirm.</li>
<li>Watch links point at the tournament’s official channel (Twitch past broadcasts where known). Search links are marked ⚠ and ask first, because thumbnails and titles there often spoil.</li>
<li>A series being played right now appears once, under <b>Live now</b>, and moves to <b>Recently finished</b> afterwards.</li></ul>
<h2>Data &amp; attribution</h2><ul><li>Finished matches: <a href="https://www.opendota.com">OpenDota</a> public API (<code>/api/proMatches</code>).</li>
<li>Upcoming schedule, tiers and stream channels: <a href="https://liquipedia.net/dota2/Liquipedia:Matches">Liquipedia Dota 2</a>, licensed <a href="https://creativecommons.org/licenses/by-sa/3.0/">CC-BY-SA 3.0</a>. One API request per build (at most hourly) with an identifying User-Agent, per Liquipedia’s API terms.</li>
<li>Calendar (.ics) feeds are on every tournament and team page.</li></ul><p>Dota 2 is a trademark of Valve Corporation. Not affiliated with Valve, OpenDota or Liquipedia.</p>
<p class=tag>Last built: {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC</p>""",0,"about.html"))
    open(f"{OUT}/newsletter.html","w").write(page("Newsletter","""<h1>What to watch: weekly spoiler-free email</h1><p>A free weekly email with the Dota 2 series worth watching and where to find the VODs. No winners, no scores, no spoilers, ever.</p>
"""+signup(False)+"<p class=tag>Free, one email a week, unsubscribe anytime. Powered by <a href='https://buttondown.com'>Buttondown</a>.</p>"))
    open(f"{OUT}/style.css","w").write(CSS); open(f"{OUT}/app.js","w").write(JS)
    stats={"opendota_maps":len(raw),"opendota_series":len(recent),"liquipedia_upcoming":len(up),"live":len(live),"upcoming_7d":len(soon),
           "merged_live":len(used),"tournaments":len(tours),"teams":len(tm),"tiers":{t:sum(1 for s in up if s['tier']==t) for t in (1,2,3,4)}}
    json.dump(stats,open(f"{OUT}/stats.json","w")); print(stats)
if __name__=="__main__": build()
