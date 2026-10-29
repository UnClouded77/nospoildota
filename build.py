#!/usr/bin/env python3
"""NoSpoilDota static site builder. Usage: python3 build.py  -> writes ./site/
Data: OpenDota /proMatches (finished maps) + Liquipedia MatchTicker via the parse API
(upcoming/live + tiers, CC-BY-SA 3.0; ONE request per build with an identifying UA, cached 1h)."""
import base64,json, re, time, html, os, urllib.request, urllib.parse, datetime as dt, hashlib, unicodedata
from collections import defaultdict
ROOT=os.path.dirname(os.path.abspath(__file__)); OUT=os.path.join(ROOT,'site'); CACHE=os.path.join(ROOT,'cache')
UA="NoSpoilDota/0.2 (https://nospoildota.com/; https://github.com/UnClouded77/nospoildota; non-commercial)"
SITE="https://nospoildota.com/"
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
    if not raw or raw.lower() in('tbd','none') or len(raw)<2 or not any(c.isalnum() for c in raw): return 'tbd'  # junk names like '.'
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
        rn,dn=[('TBD' if team_key(x)=='tbd' else x) for x in ((m.get('radiant_name') or '').strip(),(m.get('dire_name') or '').strip())]
        s=ser.setdefault(k,{"teams":sorted([rn,dn],key=str.lower),"league":m.get('league_name') or 'Unknown',"leagueid":m['leagueid'],
            "start":m['start_time'],"maps":[],"bo":{0:1,1:3,2:5,3:2}.get(m.get('series_type'),1)})
        s["start"]=min(s["start"],m['start_time'])
        rw=m.get('radiant_win'); w=(rn if rw else dn) if rw is not None else None
        s["maps"].append({"id":m['match_id'],"t":m['start_time'],"w":None if w=='TBD' else w})  # winner only emitted encoded, revealed per map on click
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
            stg=re.search(r'match-info-tournament-name"><a href="/dota2/[^"#]*#([^"]+)"',blk)
            rid=re.search(r'Match:ID_([A-Za-z0-9]+)_R(\d+)-M(\d+)',blk)
            if not ts or not tn: continue
            teams=[(html.unescape(re.sub(r'\s*\((page does not exist|stack)\)','',re.sub(r'\s*\(page does not exist\)','',a))) or b).strip() or 'TBD' for a,b in names][:2]
            while len(teams)<2: teams.append('TBD')
            streams=sorted(set(re.findall(r'href="/dota2/Special:Stream/([a-z]+)/([^"]+)"',blk)))
            t=int(ts.group(1)); key=(t,tuple(team_key(x) for x in teams),tour_key(tn.group(1)))
            if key in seen: continue
            seen.add(key)
            res.append({"teams":teams,"league":html.unescape(tn.group(1)),"lp":tl.group(1) if tl else None,"start":t,
                        "bo":int(bo.group(1)) if bo else 1,"tier":int(tier),"streams":streams,
                        "stage":urllib.parse.unquote(stg.group(1)).replace('_',' ') if stg else '',"rnd":int(rid.group(2)) if rid else None,
                        "mid":rid.group(0) if rid else None})
    return res

# ---------- presentation ----------
CSS=""":root{--bg:#0f1115;--card:#181b22;--mut:#9aa3b5;--fg:#e8ebf1;--acc:#e0533d;--bd:#2a2f3a;--live:#e5302f}
*{box-sizing:border-box}html{-webkit-text-size-adjust:100%}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
a{color:#ff9a82;text-decoration:none}a:hover{text-decoration:underline}:focus-visible{outline:2px solid #ffb199;outline-offset:2px}
.skip{position:absolute;left:-9999px}.skip:focus{left:8px;top:8px;background:#000;padding:6px;z-index:9}
header{border-bottom:1px solid var(--bd);padding:10px 16px;display:grid;grid-template-columns:auto minmax(0,1fr) auto;grid-template-areas:'logo nav lang';gap:6px 18px;align-items:center;width:100%;max-width:100%;position:sticky;top:0;background:#0f1115f2;z-index:5}
header .logo{font-weight:800;font-size:19px;color:var(--fg)}header .logo span{color:var(--acc)}nav{display:flex;flex-wrap:wrap;gap:4px 14px}nav a{color:var(--mut)}nav a[aria-current]{color:var(--fg)}
main{max-width:920px;margin:0 auto;padding:14px 16px}h1{font-size:23px;margin:.3em 0}h2{font-size:18px;margin:1.4em 0 .4em;color:#d5dae6}
h3{font-size:13px;margin:1.1em 0 .3em;color:var(--mut);text-transform:uppercase;letter-spacing:.04em}h3 a{color:inherit}
.tier{font-size:10px;border:1px solid var(--bd);border-radius:4px;padding:0 4px;margin-left:6px;color:var(--mut);vertical-align:1px;letter-spacing:0}
.m{background:var(--card);border:1px solid var(--bd);border-radius:10px;padding:9px 12px;margin:6px 0;display:grid;grid-template-columns:150px 1fr auto;gap:4px 12px;align-items:center}
.m.is-live{border-color:#8a2b2b;background:#1e1618}
.when{font-size:13px;color:var(--mut)}.when .rel{display:block;color:var(--fg);font-weight:600;font-variant-numeric:tabular-nums}.when.near .rel{color:#ffb199}.orig{color:var(--mut);font-weight:400;font-size:.85em}@media(max-width:640px){.m .teams .orig,.m .tag .orig{display:none}}.m.tl{display:block;position:relative}.m.tl:hover{border-color:#3a414f}.tla::after{content:'';position:absolute;inset:0;border-radius:10px}.cals{white-space:nowrap;position:relative;z-index:1}.tlh{display:flex;flex-wrap:wrap;justify-content:space-between;align-items:baseline;gap:2px 10px}a.cal,a.calf{color:var(--mut);font-size:12.5px;position:relative;z-index:1;white-space:nowrap}a.calf{margin-left:6px;font-size:11.5px;opacity:.8}a.cal:hover,a.calf:hover{color:var(--fg)}.wres.shown{gap:5px;border-color:#3a414f;cursor:default;white-space:nowrap}.wres .wn{color:#7dd3a0}.wres .ls{color:#f19a9a}.when .rel.cd::after{content:' ·';color:var(--mut);font-weight:400}
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
.teamlist{display:grid;grid-template-columns:repeat(auto-fill,minmax(270px,1fr));gap:0 18px;padding:0;margin:10px 0;list-style:none}.teamlist li{display:flex;align-items:center;gap:6px;padding:4px 0;border-bottom:1px solid var(--bd);min-width:0}.teamlist li a{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.teamlist li .tag{margin-left:auto;white-space:nowrap;font-size:12px}.teamlist li .star{margin:0}.tq{width:100%;max-width:420px;padding:8px 10px;border-radius:8px;border:1px solid var(--bd);background:#0f1115;color:var(--fg);font:inherit;margin-top:6px}
footer{color:var(--mut);font-size:12px;text-align:center;padding:24px 16px;border-top:1px solid var(--bd);margin-top:30px}
.star{font:inherit;background:none;border:1px solid transparent;color:var(--mut);cursor:pointer;min-width:36px;min-height:36px;padding:0 6px;margin:-6px 0 -6px -6px;font-size:19px;line-height:1;border-radius:8px;vertical-align:middle}
.star:hover{color:#ffc94d;border-color:var(--bd)}.star[aria-pressed=true]{color:#ffc94d}.star.big{font-size:15px;border-color:var(--bd);padding:6px 12px;margin:0 0 0 8px;display:inline-flex;gap:6px;align-items:center}.star.big[aria-pressed=true]{background:#3a2f10;border-color:#ffc94d}
.m.fav{border-color:#ffc94d;background:linear-gradient(90deg,#2a2412,var(--card) 60%);box-shadow:inset 4px 0 0 #ffc94d}.m.fav .when .rel::before{content:"★ ";color:#ffc94d}li.fav a{color:#ffc94d}
.vs+.star{margin-left:0}
.badge.soon{background:#2d6cdf}.badge.soon::before{content:"◷ "}.m.is-soon{border-color:#2d4f8a}
#ls:not(:has(.m)){display:none}h3.day{color:var(--fg);border-bottom:1px solid var(--bd);padding-bottom:3px}
.watch{display:flex;flex-wrap:wrap;gap:6px;margin:8px 0}.rp a{margin-right:8px}
@media(max-width:640px){.star{min-width:44px;min-height:44px}.m{grid-template-columns:1fr}.m .when{display:flex;gap:8px;align-items:baseline;flex-wrap:wrap}.m .when .rel{display:inline}.m .acts .btn{flex:1 1 auto;justify-content:center}.acts{justify-content:flex-start}main{padding:10px 12px}}"""
CSS+="\nheader .logo{grid-area:logo}header nav{grid-area:nav;min-width:0}.lang{grid-area:lang;justify-self:end;font-size:13px;color:var(--mut);border:1px solid var(--bd);border-radius:14px;padding:2px 10px;white-space:nowrap}.lang a{color:var(--mut);padding:2px}@media(max-width:640px){header{grid-template-columns:minmax(0,1fr) auto;grid-template-areas:'logo lang' 'nav nav'}}.lang a[aria-current]{color:var(--fg);font-weight:700}#eshint{margin:6px 0}#eshint[hidden]{display:none}"
JS=r"""(()=>{const HL=document.documentElement.lang,LG=HL==='es'?'es':HL==='pt-BR'?'pt':'en',LOC={es:'es',pt:'pt-BR',en:[]}[LG],T={pt:{W:'V',L:'D',cin:'em %s',started:'Começou',live:'Ao vivo',inm:'em %s min',inh:'em %s h',today:'hoje ',tom:'amanhã',ind:'em %s dias',soon:'começando em breve',agom:'há %s min',agoh:'há %s h',yest:'ontem',agod:'há %s dias',LIVE:'AO VIVO',SOON:'EM BREVE',ch:'Canal ao vivo',wl:'Assistir ao vivo',rv:'Mostrar replays',won:'%s venceu',na:'Resultado indisponível',hd:'Ocultar replays',cf:'Mostrar os links de replay? A quantidade de links revela quantos jogos foram disputados.',cp:'copiado',fol:'Seguir',unf:'Deixar de seguir',fing:'Seguindo',tz:'horário local'},es:{W:'V',L:'D',cin:'en %s',started:'Empezó',live:'En vivo',inm:'en %s min',inh:'en %s h',today:'hoy ',tom:'mañana',ind:'en %s días',soon:'por comenzar',agom:'hace %s min',agoh:'hace %s h',yest:'ayer',agod:'hace %s días',LIVE:'EN VIVO',SOON:'PRONTO',ch:'Canal en vivo',wl:'Ver en vivo',rv:'Mostrar repeticiones',won:'Ganó %s',na:'Resultado no disponible',hd:'Ocultar repeticiones',cf:'¿Mostrar los enlaces de repetición? La cantidad de enlaces revela cuántos juegos se jugaron.',cp:'copiado',fol:'Seguir',unf:'Dejar de seguir',fing:'Siguiendo',tz:'hora local'},
en:{W:'W',L:'L',cin:'in %s',started:'Started',live:'Live now',inm:'in %s min',inh:'in %sh',today:'today ',tom:'tomorrow',ind:'in %s days',soon:'starting soon',agom:'%s min ago',agoh:'%sh ago',yest:'yesterday',agod:'%s days ago',LIVE:'LIVE',SOON:'SOON',ch:'Live channel',wl:'Watch live',rv:'Reveal replays',won:'%s won',na:'Result not available',hd:'Hide replays',cf:'Show replay links? The number of links shows how many games were played.',cp:'copied',fol:'Follow',unf:'Unfollow',fing:'Following',tz:'local time'}}[LG],
f=(k,n)=>T[k].replace('%s',n);
const now=Date.now()/1000,fmt=new Intl.DateTimeFormat(LOC, {weekday:'short',month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'}),
tf=new Intl.DateTimeFormat(LOC, {hour:'2-digit',minute:'2-digit'}),day=d=>{const x=new Date(d);x.setHours(0,0,0,0);return x.getTime()};
function rel(ts,kind){const d=ts-now,a=Math.abs(d),dd=Math.round((day(ts*1000)-day(Date.now()))/864e5),t=tf.format(new Date(ts*1000));
 if(kind==='live')return T.live;
 if(d>0){if(a<3600)return f('inm',Math.max(1,Math.round(a/60)));if(a<6*3600)return f('inh',Math.round(a/3600));if(dd===0)return T.today.trim();if(dd===1)return T.tom;return f('ind',dd)}
 if(kind==='up')return T.soon;if(a<3600)return f('agom',Math.round(a/60));if(a<86400)return f('agoh',Math.round(a/3600));if(dd===-1)return T.yest;return f('agod',Math.round(a/86400))}
document.querySelectorAll('[data-ts]').forEach(e=>{const ts=+e.dataset.ts,full=fmt.format(new Date(ts*1000)),r=rel(ts,e.dataset.kind);
 e.textContent='';if(r){const s=document.createElement('span');s.className='rel';s.textContent=r;e.append(s,' ')}e.append(full);e.title=full});
const nl=(navigator.language||'').toLowerCase();[['eshint','es'],['pthint','pt']].forEach(([id,p])=>{const h=document.getElementById(id);if(h&&nl.startsWith(p))h.hidden=false});
const ls=document.getElementById('ls-list');
const CDS=[...document.querySelectorAll('.m[data-bo]')].map(c=>{const w=c.querySelector('[data-ts]');return{c,w,ts:+w.dataset.ts,bo:+c.dataset.bo||1,lv:c.dataset.live==='1',st:'',r0:(w.querySelector('.rel')||{}).textContent}});
function badge(o,kind){const t=o.c.querySelector('.teams');let bd=t.querySelector('.badge');if(!bd){bd=document.createElement('span');t.append(bd)}
 bd.className='badge'+(kind==='soon'?' soon':'');bd.textContent=kind==='live'?T.LIVE:T.SOON;o.c.classList.remove('is-live','is-soon');o.c.classList.add('is-'+kind)}
function cdtxt(d){const H=Math.floor(d/3600),M=Math.floor(d%3600/60),S=Math.floor(d%60);return H?H+'h '+M+'m':String(M).padStart(2,'0')+':'+String(S).padStart(2,'0')}
function tick(){const n=Date.now()/1000;CDS.forEach(o=>{const d=o.ts-n,end=o.ts+o.bo*4500+(o.lv?7200:0),r=o.w.querySelector('.rel');
 const st=d>0?(d<=3600?'soon':'up'):n<end?'live':'started';
 if(st!==o.st){o.st=st;if(st==='soon')badge(o,'soon');
  if(st==='live'){badge(o,'live');o.w.dataset.kind='live';o.c.querySelectorAll('.strm').forEach(sw=>{sw.classList.remove('ghost');sw.textContent=sw.textContent.replace(T.ch,T.wl)});if(ls&&!ls.contains(o.c))ls.append(o.c)}
  if(st==='started'){o.c.classList.remove('is-live','is-soon');const b=o.c.querySelector('.badge');if(b)b.remove()}}
 if(!r)return;o.w.classList.toggle('near',d>0&&d<900);
 const cd=st!=='live'&&st!=='started'&&d<43200;r.classList.toggle('cd',cd);r.textContent=st==='live'?T.live:st==='started'?T.started:cd?cdtxt(d):o.r0})}
let TK=null;const run=()=>{clearInterval(TK);TK=null;if(!document.hidden&&CDS.length){tick();TK=setInterval(tick,1000)}};
document.addEventListener('visibilitychange',run);run();
document.querySelectorAll('.byday').forEach(box=>{let last='';[...box.children].forEach(c=>{const w=c.querySelector('[data-ts]');if(!w)return;
 const k=new Date(+w.dataset.ts*1000).toDateString();if(k!==last){last=k;const h=document.createElement('h3');h.className='day';
 h.textContent=new Intl.DateTimeFormat(LOC, {weekday:'long',month:'long',day:'numeric'}).format(new Date(+w.dataset.ts*1000));box.insertBefore(h,c)}})});
const tz=document.getElementById('tzname');if(tz)tz.textContent=Intl.DateTimeFormat().resolvedOptions().timeZone||T.tz;
document.addEventListener('click',ev=>{const b=ev.target.closest('.reveal');if(b){const r=document.getElementById(b.dataset.for);
 if(!r.hidden){r.hidden=true;b.textContent=T.rv;b.setAttribute('aria-expanded','false')}else if(confirm(T.cf)){r.hidden=false;b.textContent=T.hd;b.setAttribute('aria-expanded','true')}return}
 const st=ev.target.closest('.steams');if(st){const dec=x=>new TextDecoder().decode(Uint8Array.from(atob(x),y=>y.charCodeAt(0))),c=st.closest('.m');
 try{c.querySelector('.tn').innerHTML=dec(st.dataset.h);c.dataset.teams=dec(st.dataset.k);c.dataset.search+=' '+dec(st.dataset.q)}catch(_){}st.remove();paint();return}
 const w=ev.target.closest('.wres');if(w){if(w.dataset.done)return;w.dataset.done=1;let n='';try{n=new TextDecoder().decode(Uint8Array.from(atob(w.dataset.w),x=>x.charCodeAt(0)))}catch(_){}
 let lo='';try{lo=new TextDecoder().decode(Uint8Array.from(atob(w.dataset.l||''),x=>x.charCodeAt(0)))}catch(_){}
 if(n&&lo){w.textContent='';const a=document.createElement('span'),z=document.createElement('span');a.className='wn';a.textContent=n+' '+T.W;z.className='ls';z.textContent=T.L+' '+lo;w.append(a,' · ',z);w.setAttribute('aria-label',T.won.replace('%s',n))}else w.textContent=n?T.won.replace('%s',n):T.na;w.classList.add('shown');return}
 const c=ev.target.closest('.copy');if(c&&navigator.clipboard){navigator.clipboard.writeText(c.dataset.copy);c.textContent=T.cp}});
const FK='nsd-follow';let fol=new Set();try{fol=new Set(JSON.parse(localStorage.getItem(FK)||'[]'))}catch(_){}
function paint(){document.querySelectorAll('[data-follow]').forEach(b=>{const on=fol.has(b.dataset.follow),n=b.dataset.n;
 b.setAttribute('aria-pressed',on);b.setAttribute('aria-label',(on?T.unf:T.fol)+' '+n);b.title=b.getAttribute('aria-label');b.firstChild.textContent=on?'★':'☆';const l=b.querySelector('.lbl');if(l)l.textContent=on?T.fing:T.fol});
 document.querySelectorAll('[data-teams]').forEach(c=>c.classList.toggle('fav',c.dataset.teams.split(' ').some(t=>fol.has(t))));document.dispatchEvent(new Event('nsd-follow'))}
document.addEventListener('click',ev=>{const b=ev.target.closest('[data-follow]');if(!b)return;ev.preventDefault();const k=b.dataset.follow;fol.has(k)?fol.delete(k):fol.add(k);
 try{localStorage.setItem(FK,JSON.stringify([...fol]))}catch(_){}paint()});paint();
const TL=document.getElementById('teamlist');if(TL){const lis=[...TL.children],tq=document.getElementById('tq');lis.forEach((l,i)=>l.dataset.i=i);
 const ord=()=>lis.slice().sort((a,b)=>((a.classList.contains('fav')?0:1e6)+ +a.dataset.i)-((b.classList.contains('fav')?0:1e6)+ +b.dataset.i)).forEach(l=>TL.append(l));
 tq.addEventListener('input',()=>{const v=tq.value.trim().toLowerCase();lis.forEach(l=>l.classList.toggle('hide',!!v&&!l.dataset.search.includes(v)))});document.addEventListener('nsd-follow',ord);ord()}
const F=document.getElementById('filters');if(!F)return;
const mine=F.querySelector('#mine'),ff=F.querySelector('#ffirst');try{mine.checked=localStorage.getItem('nsd-mine')==='1';ff.checked=localStorage.getItem('nsd-ffirst')==='1'}catch(_){}
document.querySelectorAll('.m,details.tbd,.grp').forEach((el,i)=>el.dataset.i=i);
function order(){document.querySelectorAll('.sect').forEach(sc=>{const sortk=el=>(ff.checked&&(el.classList.contains('fav')||el.querySelector('.fav'))?0:1e6)+(+el.dataset.i);
 const gs=[...sc.querySelectorAll(':scope>.grp')];gs.sort((a,b)=>sortk(a)-sortk(b)).forEach(g=>sc.insertBefore(g,sc.querySelector(':scope>.empty')));
 sc.querySelectorAll('.grp').forEach(g=>{const cs=[...g.querySelectorAll(':scope>.m')];const tb=g.querySelector(':scope>details');cs.sort((a,b)=>sortk(a)-sortk(b)).forEach(c=>g.insertBefore(c,tb))})})}
const items=[...document.querySelectorAll('[data-tier]')],q=F.querySelector('input[type=search]');let saved=null;try{saved=localStorage.getItem('nsd-tier')}catch(_){}
const sv=saved&&F.querySelector(`input[value="${saved}"]`);if(sv)sv.checked=true;
function apply(){const tv=F.querySelector('input[name=tier]:checked').value,max=tv==='all'?9:+tv,s=q.value.trim().toLowerCase();try{localStorage.setItem('nsd-tier',tv)}catch(_){}
 try{localStorage.setItem('nsd-mine',mine.checked?'1':'0');localStorage.setItem('nsd-ffirst',ff.checked?'1':'0')}catch(_){}order();
 items.forEach(el=>{const ok=(mine.checked?el.classList.contains('fav'):+el.dataset.tier<=max)&&(!s||el.dataset.search.includes(s));el.classList.toggle('hide',!ok)});
 document.querySelectorAll('.grp').forEach(g=>g.classList.toggle('hide',!g.querySelector('[data-tier]:not(.hide)')));document.querySelectorAll('h3.day').forEach(h=>{let n=h.nextElementSibling,v=false;while(n&&!n.matches('h3.day')){if(!n.classList.contains('hide'))v=true;n=n.nextElementSibling}h.classList.toggle('hide',!v)});
 document.querySelectorAll('.sect').forEach(sc=>{const any=sc.querySelector('[data-tier]:not(.hide)'),em=sc.querySelector('.empty');if(em)em.style.display=any?'none':'block'})}
F.addEventListener('change',apply);document.addEventListener('nsd-follow',()=>{if(mine.checked||ff.checked)apply()});q.addEventListener('input',apply);apply()})();"""

# ---------- UI strings (en / es-419) ----------
STR={
'en':dict(locale='en_US',cal='Add to calendar',cal_t='Subscribe in your calendar app; updates automatically, no results',po_r='Playoff match · round {r}',po='Playoff match',showteams='Show teams',later='Later-round matches',later_note='Hidden: listing them would reveal how this team did. Each stays behind <b>Show teams</b>.',later_none='none right now',matches='Matches',tournaments='Tournaments',teams='Teams',about='About',skip='Skip to content',main_nav='Main',
 foot='Match data: <a href="https://www.opendota.com">OpenDota</a> · Schedule, tiers &amp; streams: <a href="https://liquipedia.net/dota2/">Liquipedia</a> (<a href="https://creativecommons.org/licenses/by-sa/3.0/">CC-BY-SA 3.0</a>) · Not affiliated with Valve · Times in your timezone (<span id=tzname>local</span>) · <a href="{p}newsletter.html">Newsletter</a>',
 desc='Spoiler-free Dota 2 pro match calendar and replay finder: schedules, live badges and official streams with no scores.',
 ch='Live channel',wl='Watch live',ch_title='Official live channel',follow='Follow',tier_title='Liquipedia tier {n}',
 replay='Replay {i}: match ID',copy='copy',client='Watch in the Dota 2 client: Watch → Replays → search the match ID (kept about two weeks). Stats sites such as OpenDota show the result.',
 reveal='Reveal replays',showres='Show result',tbd1='+ {n} later-round slot, teams TBD',tbdn='+ {n} later-round slots, teams TBD',
 sub_summary='Optional: a weekly spoiler-free “what to watch” email',subscribe='Subscribe',email='Email',email_ph='you@example.com',
 lg_tier='Tier',t1='Tier 1',t12='Tier 1–2',t13='Tier 1–3',all='All',lg_fol='Followed teams',mine='★ My teams',ffirst='Followed first',
 q_label='Filter by team or tournament',q_ph='Search team or tournament…',filt_help='Tap ☆ next to a team to follow it (saved on this device only). Tiers from Liquipedia. Leagues it doesn’t list only appear under “All”.',
 h1_home='Spoiler-free Dota 2 pro match schedule',ls='Live &amp; starting soon',ls_empty='Nothing live or starting within the hour for this filter.',
 note='<b>Spoiler-free:</b> no winners, scores or game counts, only the best-of. Replay links stay hidden until you press <b>Reveal replays</b>.',
 upc='Upcoming · next 7 days',upc_empty='No upcoming matches for this filter.',rec='Recently finished',rec_empty='No finished series for this filter. Try “All”.',
 home_title='Dota 2 pro match schedule – spoiler-free | NoSpoilDota',home_desc='Spoiler-free Dota 2 pro match calendar: live and upcoming series, official streams and replay IDs, with no scores or winners.',
 tier_h='Tier {n}',no_stream='No official stream channel known yet.',add_cal='📅 Add to calendar (.ics)',lp_res='(shows results) · times in your timezone',
 lu='Live &amp; upcoming',none_sched='None scheduled.',fin='Finished',none_yet='None yet.',
 t_title='{n} schedule – spoiler-free | NoSpoilDota',t_desc='{n} Dota 2 schedule by day with official streams and replay IDs. Spoiler-free: no scores, winners or game counts.',
 tl_counts='{u} upcoming · {d} finished',tours_title='Dota 2 tournaments – spoiler-free schedules | NoSpoilDota',tours_desc='Current Dota 2 pro tournaments with spoiler-free schedules and calendar feeds.',
 team_cal='📅 Add {n}’s matches to your calendar (.ics)',team_sf='spoiler-free: no results or standings.',team_up_empty='Nothing on Liquipedia’s ticker right now.',
 recs='Recent series',recs_empty='No recent series in OpenDota’s feed.',team_title='{n} Dota 2 schedule – spoiler-free | NoSpoilDota',
 team_desc='Upcoming and recent {n} Dota 2 matches with official streams and a calendar feed. Spoiler-free: no results.',
 teams_counts='{u} upcoming · {d} recent',teams_intro='Follow your teams to pin their matches and get a calendar feed.',teams_up='{u} upcoming',teams_up1='1 upcoming',tq='Search teams…',
 teams_title='Dota 2 pro teams – spoiler-free schedules | NoSpoilDota',teams_desc='Follow Dota 2 pro teams: spoiler-free match schedules and calendar feeds for every team.',
 about_title='About NoSpoilDota – spoiler-free Dota 2 calendar',about_desc='How NoSpoilDota keeps Dota 2 schedules spoiler-free, and where the data comes from (OpenDota, Liquipedia CC-BY-SA).',
 about_body="""<h1>About NoSpoilDota</h1><p>A spoiler-free calendar of professional Dota 2 matches. Find the VOD without seeing who won first.</p>
<h2>How it stays spoiler-free</h2><ul><li>Lists show only teams, tournament, start time and best-of. Winners, scores and the number of games played are never shown; each series shows only its best-of. Replay match IDs stay behind <b>Reveal replays</b>.</li>
<li>Watch links go only to official Twitch/YouTube/Kick channels listed by Liquipedia. No search pages, whose titles and thumbnails spoil.</li>
<li>A series being played right now gets a LIVE badge and appears under <b>Live &amp; starting soon</b>, then moves to <b>Recently finished</b> afterwards.</li></ul>
<h2>Data &amp; attribution</h2><ul><li>Finished matches: <a href="https://www.opendota.com">OpenDota</a> public API (<code>/api/proMatches</code>).</li>
<li>Upcoming schedule, tiers and stream channels: <a href="https://liquipedia.net/dota2/Liquipedia:Matches">Liquipedia Dota 2</a>, licensed <a href="https://creativecommons.org/licenses/by-sa/3.0/">CC-BY-SA 3.0</a>. A couple of API requests per build (cached, at most hourly) with an identifying User-Agent, per Liquipedia’s API terms.</li>
<li>Calendar (.ics) feeds are on every tournament and team page.</li></ul><p>Dota 2 is a trademark of Valve Corporation. Not affiliated with Valve, OpenDota or Liquipedia.</p>
<p class=tag>Last built: {built} UTC</p>""",
 nl_title='Spoiler-free Dota 2 newsletter | NoSpoilDota',nl_desc='A free weekly spoiler-free email of Dota 2 series worth watching.',
 nl_body='<h1>What to watch: weekly spoiler-free email</h1><p>A free weekly email with the Dota 2 series worth watching and where to find the VODs. No winners, no scores, no spoilers, ever.</p>',
 nl_foot="Free, one email a week, unsubscribe anytime. Powered by <a href='https://buttondown.com'>Buttondown</a>.",
 hint=''),
'es':dict(locale='es_419',cal='Añadir al calendario',cal_t='Suscríbete en tu app de calendario; se actualiza sola, sin resultados',po_r='Partido de playoffs · ronda {r}',po='Partido de playoffs',showteams='Mostrar equipos',later='Partidos de rondas posteriores',later_note='Ocultos: mostrarlos revelaría cómo le fue a este equipo. Cada uno queda detrás de <b>Mostrar equipos</b>.',later_none='ninguno por ahora',matches='Partidas',tournaments='Torneos',teams='Equipos',about='Acerca de',skip='Saltar al contenido',main_nav='Principal',
 foot='Datos de partidas: <a href="https://www.opendota.com">OpenDota</a> · Calendario, tiers y streams: <a href="https://liquipedia.net/dota2/">Liquipedia</a> (<a href="https://creativecommons.org/licenses/by-sa/3.0/">CC-BY-SA 3.0</a>) · Sin afiliación con Valve · Horarios en tu zona horaria (<span id=tzname>local</span>) · <a href="{p}newsletter.html">Boletín</a>',
 desc='Calendario de partidas profesionales de Dota 2 sin spoilers y buscador de repeticiones: horarios, avisos en vivo y streams oficiales, sin marcadores.',
 ch='Canal en vivo',wl='Ver en vivo',ch_title='Canal oficial en vivo',follow='Seguir',tier_title='Tier {n} de Liquipedia',
 replay='Repetición {i}: ID de partida',copy='copiar',client='Míralo en el cliente de Dota 2: Ver → Repeticiones → busca el ID de partida (se guardan unas dos semanas). Los sitios de estadísticas como OpenDota muestran el resultado.',
 reveal='Mostrar repeticiones',showres='Mostrar resultado',tbd1='+ {n} cupo de rondas posteriores, equipos por definir',tbdn='+ {n} cupos de rondas posteriores, equipos por definir',
 sub_summary='Opcional: un correo semanal sin spoilers de “qué ver”',subscribe='Suscribirme',email='Correo',email_ph='tu@ejemplo.com',
 lg_tier='Tier',t1='Tier 1',t12='Tier 1–2',t13='Tier 1–3',all='Todos',lg_fol='Equipos seguidos',mine='★ Mis equipos',ffirst='Seguidos primero',
 q_label='Filtrar por equipo o torneo',q_ph='Buscar equipo o torneo…',filt_help='Toca ☆ junto a un equipo para seguirlo (se guarda solo en este dispositivo). Tiers de Liquipedia. Las ligas que no aparecen ahí solo se muestran en “Todos”.',
 h1_home='Calendario de partidas profesionales de Dota 2 sin spoilers',ls='En vivo y por comenzar',ls_empty='No hay nada en vivo ni por comenzar en la próxima hora con este filtro.',
 note='<b>Sin spoilers:</b> sin ganadores, marcadores ni cantidad de juegos; solo el formato (Bo3, Bo5…). Los enlaces de repetición quedan ocultos hasta que tocas <b>Mostrar repeticiones</b>.',
 upc='Próximas · siguientes 7 días',upc_empty='No hay partidas próximas con este filtro.',rec='Terminadas recientemente',rec_empty='No hay series terminadas con este filtro. Prueba con “Todos”.',
 home_title='Calendario de Dota 2 pro – sin spoilers | NoSpoilDota',home_desc='Calendario de partidas profesionales de Dota 2 sin spoilers: series en vivo y próximas, streams oficiales e IDs de repeticiones, sin marcadores ni ganadores.',
 tier_h='Tier {n}',no_stream='Todavía no se conoce un canal oficial de transmisión.',add_cal='📅 Agregar al calendario (.ics)',lp_res='(muestra resultados) · horarios en tu zona horaria',
 lu='En vivo y próximas',none_sched='Nada programado.',fin='Terminadas',none_yet='Ninguna todavía.',
 t_title='Calendario de {n} – sin spoilers | NoSpoilDota',t_desc='Calendario de {n} de Dota 2 por día, con streams oficiales e IDs de repeticiones. Sin spoilers: sin marcadores, ganadores ni cantidad de juegos.',
 tl_counts='{u} próximas · {d} terminadas',tours_title='Torneos de Dota 2 – calendarios sin spoilers | NoSpoilDota',tours_desc='Torneos profesionales de Dota 2 en curso, con calendarios sin spoilers y feeds de calendario.',
 team_cal='📅 Agrega las partidas de {n} a tu calendario (.ics)',team_sf='sin spoilers: sin resultados ni posiciones.',team_up_empty='Por ahora no hay nada en el ticker de Liquipedia.',
 recs='Series recientes',recs_empty='No hay series recientes en el feed de OpenDota.',team_title='Calendario de {n} en Dota 2 – sin spoilers | NoSpoilDota',
 team_desc='Partidas próximas y recientes de {n} en Dota 2, con streams oficiales y feed de calendario. Sin spoilers: sin resultados.',
 teams_counts='{u} próximas · {d} recientes',teams_intro='Sigue a tus equipos para fijar sus partidas y tener un feed de calendario.',teams_up='{u} próximas',teams_up1='1 próxima',tq='Buscar equipos…',
 teams_title='Equipos pro de Dota 2 – calendarios sin spoilers | NoSpoilDota',teams_desc='Sigue a equipos profesionales de Dota 2: calendarios de partidas sin spoilers y feeds de calendario para cada equipo.',
 about_title='Acerca de NoSpoilDota – calendario de Dota 2 sin spoilers',about_desc='Cómo NoSpoilDota mantiene los calendarios de Dota 2 sin spoilers y de dónde vienen los datos (OpenDota, Liquipedia CC-BY-SA).',
 about_body="""<h1>Acerca de NoSpoilDota</h1><p>Un calendario sin spoilers de partidas profesionales de Dota 2. Encuentra el VOD sin enterarte antes de quién ganó.</p>
<h2>Cómo se mantiene sin spoilers</h2><ul><li>Las listas muestran solo los equipos, el torneo, la hora de inicio y el formato. Nunca mostramos ganadores, marcadores ni cuántos juegos se jugaron; cada serie muestra solo su formato (Bo3, Bo5…). Los IDs de repetición quedan detrás de <b>Mostrar repeticiones</b>.</li>
<li>Los enlaces para ver van solo a canales oficiales de Twitch/YouTube/Kick que lista Liquipedia. Nada de páginas de búsqueda, cuyos títulos y miniaturas hacen spoiler.</li>
<li>Una serie que se está jugando ahora lleva la etiqueta EN VIVO y aparece en <b>En vivo y por comenzar</b>; después pasa a <b>Terminadas recientemente</b>.</li></ul>
<h2>Datos y atribución</h2><ul><li>Partidas terminadas: API pública de <a href="https://www.opendota.com">OpenDota</a> (<code>/api/proMatches</code>).</li>
<li>Calendario de próximas partidas, tiers y canales: <a href="https://liquipedia.net/dota2/Liquipedia:Matches">Liquipedia Dota 2</a>, con licencia <a href="https://creativecommons.org/licenses/by-sa/3.0/">CC-BY-SA 3.0</a>. Un par de solicitudes a la API por compilación (en caché, como máximo cada hora) con un User-Agent identificable, según los términos de la API de Liquipedia.</li>
<li>Hay feeds de calendario (.ics) en cada página de torneo y de equipo.</li></ul><p>Dota 2 es una marca registrada de Valve Corporation. Sin afiliación con Valve, OpenDota ni Liquipedia.</p>
<p class=tag>Última actualización: {built} UTC</p>""",
 nl_title='Boletín de Dota 2 sin spoilers | NoSpoilDota',nl_desc='Un correo semanal gratuito y sin spoilers con las series de Dota 2 que vale la pena ver.',
 nl_body='<h1>Qué ver: correo semanal sin spoilers</h1><p>Un correo semanal gratuito con las series de Dota 2 que vale la pena ver y dónde encontrar los VODs. Sin ganadores, sin marcadores, nunca spoilers.</p>',
 nl_foot="Gratis, un correo por semana, cancela cuando quieras. Funciona con <a href='https://buttondown.com'>Buttondown</a>.",
 hint=''),
'pt':dict(locale='pt_BR',cal='Adicionar ao calendário',cal_t='Assine no seu app de calendário; atualiza sozinho, sem resultados',po_r='Partida dos playoffs · rodada {r}',po='Partida dos playoffs',showteams='Mostrar times',later='Partidas de rodadas seguintes',later_note='Ocultas: mostrá-las revelaria como este time se saiu. Cada uma fica atrás de <b>Mostrar times</b>.',later_none='nenhuma no momento',matches='Partidas',tournaments='Torneios',teams='Times',about='Sobre',skip='Pular para o conteúdo',main_nav='Principal',
 foot='Dados das partidas: <a href="https://www.opendota.com">OpenDota</a> · Agenda, tiers e transmissões: <a href="https://liquipedia.net/dota2/">Liquipedia</a> (<a href="https://creativecommons.org/licenses/by-sa/3.0/">CC-BY-SA 3.0</a>) · Sem vínculo com a Valve · Horários no seu fuso (<span id=tzname>local</span>) · <a href="{p}newsletter.html">Newsletter</a>',
 desc='Agenda de partidas profissionais de Dota 2 sem spoilers e buscador de replays: horários, avisos ao vivo e transmissões oficiais, sem placares.',
 ch='Canal ao vivo',wl='Assistir ao vivo',ch_title='Canal oficial ao vivo',follow='Seguir',tier_title='Tier {n} da Liquipedia',
 replay='Replay {i}: ID da partida',copy='copiar',client='Assista no cliente do Dota 2: Assistir → Replays → busque o ID da partida (ficam disponíveis por cerca de duas semanas). Sites de estatísticas como o OpenDota mostram o resultado.',
 reveal='Mostrar replays',showres='Mostrar resultado',tbd1='+ {n} vaga de rodadas seguintes, times a definir',tbdn='+ {n} vagas de rodadas seguintes, times a definir',
 sub_summary='Opcional: um e-mail semanal sem spoilers com “o que assistir”',subscribe='Inscrever-se',email='E-mail',email_ph='voce@exemplo.com',
 lg_tier='Tier',t1='Tier 1',t12='Tier 1–2',t13='Tier 1–3',all='Todos',lg_fol='Times seguidos',mine='★ Meus times',ffirst='Seguidos primeiro',
 q_label='Filtrar por time ou torneio',q_ph='Buscar time ou torneio…',filt_help='Toque em ☆ ao lado de um time para segui-lo (fica salvo só neste aparelho). Tiers da Liquipedia. Ligas que não aparecem lá só são mostradas em “Todos”.',
 h1_home='Agenda de partidas profissionais de Dota 2 sem spoilers',ls='Ao vivo e começando em breve',ls_empty='Nada ao vivo nem começando na próxima hora com este filtro.',
 note='<b>Sem spoilers:</b> sem vencedores, placares nem quantidade de jogos; só o formato (Bo3, Bo5…). Os links de replay ficam ocultos até você tocar em <b>Mostrar replays</b>.',
 upc='Próximas · próximos 7 dias',upc_empty='Nenhuma partida próxima com este filtro.',rec='Encerradas recentemente',rec_empty='Nenhuma série encerrada com este filtro. Tente “Todos”.',
 home_title='Agenda de Dota 2 pro – sem spoilers | NoSpoilDota',home_desc='Agenda de partidas profissionais de Dota 2 sem spoilers: séries ao vivo e próximas, transmissões oficiais e IDs de replay, sem placares nem vencedores.',
 tier_h='Tier {n}',no_stream='Ainda não há um canal oficial de transmissão conhecido.',add_cal='📅 Adicionar à agenda (.ics)',lp_res='(mostra resultados) · horários no seu fuso',
 lu='Ao vivo e próximas',none_sched='Nada agendado.',fin='Encerradas',none_yet='Nenhuma ainda.',
 t_title='Agenda do {n} – sem spoilers | NoSpoilDota',t_desc='Agenda do {n} de Dota 2 por dia, com transmissões oficiais e IDs de replay. Sem spoilers: sem placares, vencedores nem quantidade de jogos.',
 tl_counts='{u} próximas · {d} encerradas',tours_title='Torneios de Dota 2 – agendas sem spoilers | NoSpoilDota',tours_desc='Torneios profissionais de Dota 2 em andamento, com agendas sem spoilers e feeds de calendário.',
 team_cal='📅 Adicione as partidas de {n} à sua agenda (.ics)',team_sf='sem spoilers: sem resultados nem classificação.',team_up_empty='Nada no ticker da Liquipedia no momento.',
 recs='Séries recentes',recs_empty='Nenhuma série recente no feed do OpenDota.',team_title='Agenda de {n} no Dota 2 – sem spoilers | NoSpoilDota',
 team_desc='Partidas próximas e recentes de {n} no Dota 2, com transmissões oficiais e feed de calendário. Sem spoilers: sem resultados.',
 teams_counts='{u} próximas · {d} recentes',teams_intro='Siga seus times para fixar as partidas deles e ter um feed de calendário.',teams_up='{u} próximas',teams_up1='1 próxima',tq='Buscar times…',
 teams_title='Times pro de Dota 2 – agendas sem spoilers | NoSpoilDota',teams_desc='Siga times profissionais de Dota 2: agendas de partidas sem spoilers e feeds de calendário para cada time.',
 about_title='Sobre o NoSpoilDota – agenda de Dota 2 sem spoilers',about_desc='Como o NoSpoilDota mantém as agendas de Dota 2 sem spoilers e de onde vêm os dados (OpenDota, Liquipedia CC-BY-SA).',
 about_body="""<h1>Sobre o NoSpoilDota</h1><p>Uma agenda sem spoilers de partidas profissionais de Dota 2. Encontre o VOD sem descobrir antes quem venceu.</p>
<h2>Como tudo fica sem spoilers</h2><ul><li>As listas mostram só os times, o torneio, o horário de início e o formato. Nunca mostramos vencedores, placares nem quantos jogos foram disputados; cada série mostra só o formato (Bo3, Bo5…). Os IDs de replay ficam atrás de <b>Mostrar replays</b>.</li>
<li>Os links para assistir levam só a canais oficiais da Twitch/YouTube/Kick listados pela Liquipedia. Nada de páginas de busca, cujos títulos e miniaturas dão spoiler.</li>
<li>Uma série sendo jogada agora ganha o selo AO VIVO e aparece em <b>Ao vivo e começando em breve</b>; depois passa para <b>Encerradas recentemente</b>.</li></ul>
<h2>Dados e atribuição</h2><ul><li>Partidas encerradas: API pública do <a href="https://www.opendota.com">OpenDota</a> (<code>/api/proMatches</code>).</li>
<li>Agenda das próximas partidas, tiers e canais: <a href="https://liquipedia.net/dota2/Liquipedia:Matches">Liquipedia Dota 2</a>, sob a licença <a href="https://creativecommons.org/licenses/by-sa/3.0/">CC-BY-SA 3.0</a>. Algumas poucas requisições à API por build (em cache, no máximo de hora em hora) com um User-Agent identificável, conforme os termos da API da Liquipedia.</li>
<li>Há feeds de calendário (.ics) em cada página de torneio e de time.</li></ul><p>Dota 2 é uma marca registrada da Valve Corporation. Sem vínculo com a Valve, o OpenDota ou a Liquipedia.</p>
<p class=tag>Última atualização: {built} UTC</p>""",
 nl_title='Newsletter de Dota 2 sem spoilers | NoSpoilDota',nl_desc='Um e-mail semanal gratuito e sem spoilers com as séries de Dota 2 que valem a pena assistir.',
 nl_body='<h1>O que assistir: e-mail semanal sem spoilers</h1><p>Um e-mail semanal gratuito com as séries de Dota 2 que valem a pena e onde encontrar os VODs. Sem vencedores, sem placares, nunca spoilers.</p>',
 nl_foot="Grátis, um e-mail por semana, cancele quando quiser. Feito com <a href='https://buttondown.com'>Buttondown</a>.",
 hint='')}
LANGS=('en','es','pt'); HLANG={'en':'en','es':'es','pt':'pt-BR'}; PFX={'en':'','es':'es/','pt':'pt/'}
HINTS={'es':'¿Prefieres español? <a href="{u}">Ver esta página en español →</a>','pt':'Prefere português? <a href="{u}">Ver esta página em português →</a>'}
LG='en'; L=STR['en']; RP=''; LROOT=SITE
CJK=re.compile(r'[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af\uf900-\ufaff]')
try: NAMES={k:v for k,v in json.load(open(os.path.join(ROOT,'data','name_translations.json'),encoding='utf-8')).items() if not k.startswith('_')}
except FileNotFoundError: NAMES={}
MISSING=set()
def tr(n):
    """Display name in the page language for CJK names (data/name_translations.json); others unchanged."""
    m=NAMES.get(n)
    if m: return m.get(LG) or m.get('en') or n
    if n and CJK.search(n): MISSING.add(n)
    return n
def hn(n):
    t=tr(n); return e(t)+(f"<span class=orig lang=zh> · {e(n)}</span>" if t!=n else "")
def both(n): return (n+' '+tr(n)).lower() if tr(n)!=n else n.lower()
def set_lang(lg):
    global LG,L,RP,LROOT
    LG=lg; L=STR[lg]; RP='' if lg=='en' else '../'; LROOT=SITE+PFX[lg]
DOW={'en':'Mon Tue Wed Thu Fri Sat Sun'.split(),'es':'lun mar mié jue vie sáb dom'.split(),'pt':'seg ter qua qui sex sáb dom'.split()}
MON={'en':'Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec'.split(),'es':'ene feb mar abr may jun jul ago sep oct nov dic'.split(),'pt':'jan fev mar abr mai jun jul ago set out nov dez'.split()}
def fdate(ts):
    """No-JS fallback date in the page language (UTC); app.js replaces it with local time."""
    d=dt.datetime.fromtimestamp(ts,dt.timezone.utc)
    return f"{DOW[LG][d.weekday()]}, {d.day} {MON[LG][d.month-1]}, {d:%H:%M} UTC" if LG!='en' else f"{DOW[LG][d.weekday()]}, {MON[LG][d.month-1]} {d.day}, {d:%H:%M} UTC"
def cal_link(rel,fb=True):
    """Subscribe via webcal:// (phones open the calendar app) plus a small https .ics fallback."""
    return (f"<span class=cals><a class=cal href='webcal://nospoildota.com/{rel}' title='{L['cal_t']}'><span aria-hidden=true>📅</span> {L['cal']}</a>"
            +(f"<a class=calf href='/{rel}' title='{L['cal_t']}' aria-label='{L['cal']} (.ics)'>.ics</a>" if fb else "")+"</span>")
ASSET_V=hashlib.md5((CSS+JS).encode()).hexdigest()[:10]
BD="nospoildota"
def signup(compact=True):
    f=f"""<form action="https://buttondown.com/api/emails/embed-subscribe/{BD}" method="post" target="popupwindow" onsubmit="window.open('https://buttondown.com/{BD}', 'popupwindow')"><label for=bd-email class=sr>{L['email']}</label><input type=email name="email" id=bd-email required placeholder="{L['email_ph']}"> <button type=submit>{L['subscribe']}</button></form>"""
    if compact: return f"<details class=signup><summary>{L['sub_summary']}</summary>{f}</details>"
    return f
def page(title,body,depth=0,cur=None,path="",desc=None,ld=None,nolist=False):
    """depth = levels below the language root; RP climbs from /es/ back to the shared assets at the site root."""
    p="../"*depth; r=p+RP; can=LROOT+path
    if nolist: p=r='/'  # 404 is served at arbitrary depths: absolute links
    if LG=='en' and not nolist: PAGES.append(path)
    desc=desc or L['desc']
    ldj=f'<script type="application/ld+json">{json.dumps(ld,ensure_ascii=False).replace("</","<\\/")}</script>' if ld else ""
    NAV=[("index.html",L['matches']),("tournaments.html",L['tournaments']),("teams.html",L['teams']),("about.html",L['about'])]
    nav="".join(f"<a href='{p}{h}'{' aria-current=page' if h==cur else ''}>{t}</a>" for h,t in NAV)
    sw="<span class=lang>"+" | ".join(f"<a href='/{PFX[x]}{path}' hreflang={HLANG[x]} lang={HLANG[x]} data-lg={x}{' aria-current=true' if LG==x else ''}>{x.upper()}</a>" for x in LANGS)+"</span>"
    hint="".join(f"<p id={x}hint class=note lang={HLANG[x]} hidden>{HINTS[x].format(u='/'+PFX[x]+path).replace('<a ',f'<a data-lg={x} ')}</p>" for x in ('es','pt') if x!=LG and not (x=='es' and LG!='en'))
    alt="".join(f'<link rel=alternate hreflang={HLANG[x]} href="{SITE+PFX[x]+path}">' for x in LANGS)+f'<link rel=alternate hreflang=x-default href="{SITE+path}">'
    return f"""<!doctype html><html lang={HLANG[LG]}><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1"><title>{e(title)}</title>{LANG_JS.replace("@L",'404' if nolist else LG)}
<meta name=description content="{e(desc)}"><link rel=canonical href="{can}">{alt}<meta property=og:type content=website><meta property=og:site_name content=NoSpoilDota><meta property=og:locale content={L['locale']}><meta property=og:title content="{e(title)}"><meta property=og:description content="{e(desc)}"><meta property=og:url content="{can}"><meta name=twitter:card content=summary><meta name=color-scheme content=dark>{ldj}<link rel=stylesheet href="{r}style.css?v={ASSET_V}"></head><body>
<a class=skip href="#main">{L['skip']}</a><header><a class=logo href="{p}index.html">NoSpoil<span>Dota</span></a>{sw}<nav aria-label={L['main_nav']}>{nav}</nav></header>
<main id=main>{hint}{body}</main><footer>{L['foot'].format(p=p)}</footer><script src="{r}app.js?v={ASSET_V}" defer></script><script data-goatcounter="https://nospoildota.goatcounter.com/count" async src="https://gc.zgo.at/count.js"></script></body></html>"""
PAGES=[]
HANDLE={'twitch':r'[A-Za-z0-9_]{3,25}','kick':r'[A-Za-z0-9_-]{3,40}','youtube':r'@?[A-Za-z0-9_.-]{3,40}|channel/UC[A-Za-z0-9_-]{22}'}
def stream_url(pl,ch):
    """Direct LIVE channel URLs only (never /videos, VODs or search)."""
    if pl=='twitch': return f"https://www.twitch.tv/{ch.lower()}"
    if pl=='kick': return f"https://kick.com/{ch.lower()}"
    return f"https://www.youtube.com/{ch if ch.startswith('channel/') else '@'+ch.lstrip('@')}/live"
# Curated official channels (each URL checked with curl on 2026-10-28), matched against Liquipedia organizer / tournament name.
FALLBACK=[(('the international','valve','dota2ti'),[('twitch','dota2ti'),('youtube','channel/UCTQKT5QqO3h7y32G8VzuySQ')]),
  (('pgl',),[('twitch','pgl_dota2'),('youtube','PGL_Dota2'),('kick','pgldota2')]),
  (('dreamleague','esl'),[('twitch','esl_dota2'),('youtube','ESLDota2')]),
  (('blast',),[('twitch','blastdota'),('youtube','BLASTDota'),('kick','blastdota')]),
  (('fissure',),[('twitch','fissure_dota_en'),('youtube','fiss_dota2_en'),('kick','fissure_dota_en')]),
  (('pari',),[('youtube','PARIEsportsDOTA2')]),
  (('epicenter',),[('twitch','epicenter_en1')]),
  (('betboom',),[('youtube','BetBoomEsports')]),
  (('epl','european pro league'),[('kick','epldota_en1')]),
  (('esports pro circuit','epc'),[('twitch','epc_en')]),
  (('nexus',),[('twitch','nexusmedia_en')])]
def fetch_tour_streams(pages):
    """ONE batched Liquipedia query for the tournament pages' wikitext -> {page:(organizer,[(platform,handle)])}."""
    pages=sorted(set(pages))[:50]
    if not pages: return {}
    try:
        u="https://liquipedia.net/dota2/api.php?"+urllib.parse.urlencode({"action":"query","prop":"revisions","rvprop":"content","rvslots":"main","format":"json","redirects":1,"titles":"|".join(p.replace('_',' ') for p in pages)})
        d=get(u,"lp_streams.json",ttl=6*3600); time.sleep(2)
    except Exception as x: print("Liquipedia streams failed:",x); return {}
    q=d.get('query',{}); alias={x['to']:x['from'] for x in q.get('normalized',[])+q.get('redirects',[])}
    out={}
    for p in q.get('pages',{}).values():
        w=(p.get('revisions') or [{}])[0].get('slots',{}).get('main',{}).get('*','')
        org=' '.join(re.findall(r'\|organizer[0-9]*=([^|\n}]*)',w)[:3])
        st=[]
        for pl,n,v in re.findall(r'\|(twitch|youtube|kick)([0-9]*)=([^|\n}]*)',w):
            v=v.strip()
            if re.fullmatch(HANDLE[pl],v) and (pl,v.lower()) not in [(a,b.lower()) for a,b,_ in st]: st.append((pl,v,n in ('','1')))
        t=p['title']
        while t in alias: t=alias[t]
        out[t.replace(' ','_')]=(org,st)
    return out
def pick_streams(name,org,st):
    prim=[(a,b) for a,b,p in st if p]; sec=[(a,b) for a,b,p in st if not p]; st=prim
    hay=f"{name} {org}".lower()
    for keys,chans in FALLBACK:
        if any(re.search(r'\b'+re.escape(k)+r'\b',hay) for k in keys):
            for c in chans:
                if c[0] not in [x[0] for x in st]: st.append(c)
            break
    order={'twitch':0,'youtube':1,'kick':2}
    # main/official tier (Liquipedia slot 1 + curated organizer channels) always ahead of secondary channels, any platform
    return sorted(st,key=lambda c:order[c[0]])+[c for c in sec if c not in st]
PL={'twitch':'Twitch','youtube':'YouTube','kick':'Kick'}
def is_pt(ch): return bool(re.search(r'(^|[_.-])(pt|br|ptbr|pt_br|bra)([_.-]|\d*$)|brasil|brazil|ptbr',ch.lower()))
def is_es(ch): return bool(re.search(r'(^|[_.-])(es|esp|spa|spanish|latam|lat)([_.-]|\d*$)|espanol|español',ch.lower()))
def lang_streams(st):
    """Spanish pages: per platform, move a Spanish-language channel (e.g. nexusmedia_es) into that platform's first slot."""
    if LG=='en': return st
    mark=is_es if LG=='es' else is_pt
    st=list(st)
    for pl in PL:
        sp=[c for c in st if c[0]==pl and mark(c[1])]
        firsts=[i for i,c in enumerate(st) if c[0]==pl]
        if sp and firsts and st[firsts[0]]!=sp[0]:
            st.remove(sp[0]); st.insert(firsts[0],sp[0])
    return st
def watch_links(s,cls="btn",n=2,live=False,all_=False):
    """Official channels from Liquipedia's stream data only (no search pages, no titles/thumbnails that could spoil)."""
    st=lang_streams(s.get('streams',[]))
    if not all_:  # cards: one button per platform, max n
        seen=set(); st=[c for c in st if not (c[0] in seen or seen.add(c[0]))][:n]
        return "".join(f"<a class='{cls}' href='{stream_url(pl,ch)}' target=_blank rel='noopener nofollow' title='{L['ch_title']}: {e(ch)}'>▶ {L['wl'] if live else L['ch']} · {PL.get(pl,pl.title())}</a>" for pl,ch in st)
    return "".join(f"<a class='{cls}' href='{stream_url(pl,ch)}' target=_blank rel='noopener nofollow' title='{L['ch_title']}'>▶ {PL.get(pl,pl.title())} · {e(ch.split('/')[-1].lstrip('@'))}</a>" for pl,ch in st)
def star(k,n,big=False):
    lab=f"{L['follow']} {e(tr(n))}"
    return f"<button type=button class='star{' big' if big else ''}' data-follow={k} data-n=\"{e(tr(n))}\" aria-pressed=false aria-label='{lab}' title='{lab}'><span aria-hidden=true>☆</span>{'<span class=lbl>'+L['follow']+'</span>' if big else ''}</button>"
LANG_JS="""<script>(function(){var C='@L',K='nsd-lang',P={en:'/',es:'/es/',pt:'/pt/'},s=null;try{s=localStorage.getItem(K)}catch(e){}
document.addEventListener('click',function(v){var a=v.target.closest&&v.target.closest('a[data-lg]');if(a)try{localStorage.setItem(K,a.dataset.lg)}catch(e){}});
if(C==='404'||navigator.webdriver||/bot|crawl|spider/i.test(navigator.userAgent)||/[?&]lang=en(&|$)/.test(location.search))return;
var t=null;if(s&&P[s])t=s;else if(C==='en'&&!(document.referrer&&new URL(document.referrer).host===location.host)){var l=(navigator.languages||[navigator.language||'']);for(var i=0;i<l.length;i++){var x=(l[i]||'').toLowerCase();if(x.indexOf('es')===0){t='es';break}if(x.indexOf('pt')===0){t='pt';break}if(x.indexOf('en')===0)break}}
if(!t||t===C)return;var r=location.pathname.replace(/^\\/(es|pt)\\//,'/');location.replace(P[t]+r.slice(1)+location.search+location.hash)})()</script>"""
def card(s,d,ctx,TEAMS):
    a,b=s['teams']; uid="r"+hashlib.md5(f"{s['start']}{a}{b}{s['tname']}".encode()).hexdigest()[:8]
    live=s.get('live')
    tn=lambda x: hn(x) if team_key(x) not in TEAMS else star(team_key(x),TEAMS[team_key(x)])+f"<a href='{'../'*d}team/{slug(TEAMS[team_key(x)])}.html'>{hn(x)}</a>"
    tier=f"<span class=tier title='{L['tier_title'].format(n=s['tier'])}'>T{s['tier']}</span>" if s.get('tier') else ""
    real=f"{tn(a)}<span class=vs>vs</span>{tn(b)}"; hid=s.get('hid') and ctx=='up'
    b64=lambda x: base64.b64encode(x.encode()).decode()
    lab=e(L['po_r'].format(r=s['rnd']) if s.get('rnd') else L['po'])
    tt=(f"<span class=tn>TBD<span class=vs>vs</span>TBD <span class=tag>· {lab}</span></span> <button type=button class='btn ghost mini steams' data-h=\"{b64(real)}\" data-k=\"{b64(' '.join(sorted(s['pair']-{'tbd'})))}\" data-q=\"{b64(both(a)+' '+both(b))}\">{L['showteams']}</button>") if hid else f"<span class=tn>{real}</span>"
    head=(f"<div class=when data-ts={s['start']} data-kind={'up' if ctx=='up' else 'done'}>{fdate(s['start'])}</div><div><div class=teams>{tt}"
          f"</div><div class=tag><a href='{'../'*d}t/{slug(s['tname'])}.html'>{hn(s['tname'])}</a> · Bo{s['bo']}{tier}</div></div>")
    attrs=f"class=m{' data-bo='+str(s['bo'])+(' data-live=1' if live else '') if ctx=='up' else ''} data-tier={s.get('tier') or 9} data-teams=\"{'' if hid else ' '.join(sorted(s['pair']-{'tbd'}))}\" data-search=\"{e(both(s['tname']) if hid else both(a)+' '+both(b)+' '+both(s['tname']))}\""
    if ctx=='up':
        return f"<div {attrs}>{head}<div class=acts>{watch_links(s,'btn ghost strm',2)}</div></div>"
    maps="<br>".join(f"<span class=rp>{L['replay'].format(i=i+1)} <code>{m['id']}</code> <button class='btn ghost mini copy' data-copy={m['id']}>{L['copy']}</button> <button type=button class='btn ghost mini wres' data-w=\"{base64.b64encode(tr(TEAMS.get(team_key(m['w']),m['w'])).encode()).decode() if m.get('w') else ''}\" data-l=\"{base64.b64encode(tr(next((x for x in (a,b) if team_key(x)!=team_key(m['w'])),'')).encode()).decode() if m.get('w') else ''}\" aria-live=polite>{L['showres']}</button></span>"
                  for i,m in enumerate(sorted(s['maps'],key=lambda m:m['t'])))
    maps+=f"<br><span class=tag>{L['client']}</span>"
    return (f"<div {attrs}>{head}<div class=acts><button class='btn reveal' data-for={uid} aria-expanded=false aria-controls={uid}>{L['reveal']}</button></div>"
            f"<div class=res id={uid} hidden>{maps}</div></div>")
def tbd_block(items):
    if not items: return ""
    li="".join(f"<li><span data-ts={s['start']} data-kind=up>{fdate(s['start'])}</span> · {' vs '.join(hn(t) for t in s['teams'])} · Bo{s['bo']}</li>" for s in sorted(items,key=lambda x:x['start']))
    t=min((s.get('tier') or 9) for s in items); n=len(items)
    return f"<details class=tbd data-tier={t} data-search=\"{e(both(items[0]['tname']))} tbd\"><summary>{(L['tbd1'] if n==1 else L['tbdn']).format(n=n)}</summary><ul>{li}</ul></details>"
def ics(name,items,url):
    f=lambda ts: dt.datetime.fromtimestamp(ts,dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    esc=lambda x: re.sub(r'([,;\\])',r'\\\1',x).replace('\n','\\n')
    stamp=f(time.time()); L=["BEGIN:VCALENDAR","VERSION:2.0","PRODID:-//NoSpoilDota//EN","CALSCALE:GREGORIAN","METHOD:PUBLISH",f"X-WR-CALNAME:{esc(tr(name))} (NoSpoilDota)","X-PUBLISHED-TTL:PT2H","REFRESH-INTERVAL;VALUE=DURATION:PT2H"]
    for s in sorted(items,key=lambda x:x['start']):
        uid=hashlib.md5((f"{s['tk']}|{s['mid']}" if s.get('mid') else f"{s['start']}|{s['tk']}|{'|'.join(sorted(map(team_key,s['teams'])))}").encode()).hexdigest()
        L+=["BEGIN:VEVENT",f"UID:{uid}@nospoildota",f"DTSTAMP:{stamp}",f"DTSTART:{f(s['start'])}",f"DURATION:PT{max(1,s['bo'])}H",
            "SUMMARY:"+esc((f"{STR['en']['po_r'].format(r=s['rnd']) if s.get('rnd') else STR['en']['po']} (Bo{s['bo']}) · {tr(s['tname'])}") if s.get('hid') and s['start']>time.time()-6*3600 else f"{tr(s['teams'][0])} vs {tr(s['teams'][1])} (Bo{s['bo']}) · {tr(s['tname'])}"),
            "DESCRIPTION:"+esc("Spoiler-free, no results. Watch links: "+url),f"URL:{url}","END:VEVENT"]
    L.append("END:VCALENDAR")
    def fold(x):  # RFC 5545: max 75 octets per line, never split a UTF-8 character
        out=[];cur=''
        for ch in x:
            if len((cur+ch).encode())>(75 if not out else 74): out.append(cur);cur=''
            cur+=ch
        return "\r\n ".join(out+[cur])
    return "\r\n".join(fold(x) for x in L)+"\r\n"

def iso(ts): return dt.datetime.fromtimestamp(ts,dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
def events_ld(items,url,limit=50):
    """schema.org SportsEvent list. Teams, time, tournament only - never winners, scores or game counts."""
    ev=[]
    for s in sorted(items,key=lambda x:x['start'])[:limit]:
        if s['pair']=={'tbd'} or s.get('hid'): continue
        ev.append({"@type":"SportsEvent","name":f"{tr(s['teams'][0])} vs {tr(s['teams'][1])} (Bo{s['bo']}) – {tr(s['tname'])}","sport":"Dota 2",
            "startDate":iso(s['start']),"eventAttendanceMode":"https://schema.org/OnlineEventAttendanceMode",
            "location":{"@type":"VirtualLocation","url":url},"url":url,"organizer":{"@type":"Organization","name":tr(s['tname'])},
            "competitor":[{"@type":"SportsTeam","name":tr(t)} for t in s['teams'] if t!='TBD'],
            "superEvent":{"@type":"SportsEvent","name":tr(s['tname']),"url":f"{LROOT}t/{slug(s['tname'])}.html"}})
        if s['start']>time.time(): ev[-1]["eventStatus"]="https://schema.org/EventScheduled"
    return {"@context":"https://schema.org","@graph":ev} if ev else None
def build():
    raw,recent=fetch_recent(); up=fetch_upcoming(); now=time.time()
    TN,TT,TL,TLF={},{},{},{}
    for s in up:
        k=tour_key(s['league']); TN.setdefault(k,tour_name(s['league'])); TT[k]=min(TT.get(k,9),s['tier']); 
        if s.get('lp'): TL.setdefault(k,s['lp'].split('/dota2/')[1].split('/')[0])
        if s.get('lp'): TLF.setdefault(k,urllib.parse.unquote(s['lp'].split('/dota2/')[1]))
    for s in recent: TN.setdefault(tour_key(s['league']),tour_name(s['league']))
    LS=fetch_tour_streams(TLF.values()); TS={}
    for k in TN:
        org,st=LS.get(TLF.get(k,''),('',[])); TS[k]=pick_streams(TN[k],org,st)
    TEAMN={}  # canonical team display names, Liquipedia's full names first
    for s in up+recent:
        for t in s['teams']: TEAMN.setdefault(team_key(t),t)
    for s in up+recent:
        k=tour_key(s['league']); s['tk']=k; s['tname']=TN[k]; s['tier']=TT.get(k) or s.get('tier')
        s['teams']=['TBD' if team_key(t)=='tbd' else TEAMN[team_key(t)] for t in s['teams']]; s['pair']=frozenset(map(team_key,s['teams']))
        s['streams']=TS.get(k,[])
    # One series = one place: a Liquipedia match with OpenDota maps already (same teams, start within 3h) is LIVE and hidden from "finished".
    used=set()
    for s in up:
        s['live']=s['start']<=now
        if s['pair']=={'tbd'}: continue
        for i,r in enumerate(recent):
            if r['pair']==s['pair'] and abs(r['start']-s['start'])<=3*3600:
                s['live']=True; used.add(i)
    # Bracket spoiler guard: a playoff match past round 1, with a still-TBD slot, or with a team that already played in this
    # tournament shows who advanced. Group-stage (round-robin day) matches carry no bracket round and stay visible.
    played=defaultdict(dict)
    for r in recent:
        for t in r['pair']-{'tbd'}: played[r['tk']][t]=min(played[r['tk']].get(t,9e18),r['start'])
    for s in up:
        br=s.get('rnd') is not None or bool(re.search(r'(?i)playoff|bracket|final|knockout|elimination|decider',s.get('stage','')))
        s['hid']=br and s['pair']!={'tbd'} and ((s.get('rnd') or 1)>1 or 'tbd' in s['pair'] or any(played[s['tk']].get(t,9e18)<s['start']-3600 for t in s['pair']-{'tbd'}))
    recent=[r for i,r in enumerate(recent) if i not in used]
    TEAMS={k:v for k,v in TEAMN.items() if k!='tbd'}
    upcoming=[s for s in up if s['start']<now+7*86400]; live=[s for s in upcoming if s['live']]; soon=upcoming
    tours=defaultdict(lambda:{"up":[],"done":[]})
    for s in up: tours[s['tk']]["up"].append(s)
    for s in recent: tours[s['tk']]["done"].append(s)
    tm=defaultdict(lambda:{"up":[],"done":[]})
    for s in up:
        for t in s['pair']-{'tbd'}:
            if not s['hid']: tm[t]["up"].append(s)
    for s in up:
        for t in s['pair']-{'tbd'}:
            if s['hid'] and t in tm: tm[t].setdefault("hid",[]).append(s)
    for s in recent:
        for t in s['pair']-{'tbd'}: tm[t]["done"].append(s)
    keep={"t":{slug(TN[k]) for k in tours},"team":{slug(TEAMS[k]) for k in tm}}
    def section(items,ctx,d=0,by_t=True,limit=None):
        items=sorted(items,key=lambda x:x['start'],reverse=(ctx=='done'))[:limit]
        if not by_t:
            return "<div class=byday>"+"".join(card(s,d,ctx,TEAMS) for s in items if s['pair']!={'tbd'})+"</div>"+tbd_block([s for s in items if s['pair']=={'tbd'}])
        g=defaultdict(list)
        for s in items: g[s['tk']].append(s)
        out=""
        for k in sorted(g,key=lambda k:(min(x['start'] for x in g[k]) if ctx!='done' else -max(x['start'] for x in g[k]))):
            tier=f"<span class=tier>T{TT[k]}</span>" if TT.get(k) else ""
            out+=(f"<div class=grp><h3><a href='{'../'*d}t/{slug(TN[k])}.html'>{hn(TN[k])}</a>{tier}</h3>"
                  +"".join(card(s,d,ctx,TEAMS) for s in g[k] if s['pair']!={'tbd'})+tbd_block([s for s in g[k] if s['pair']=={'tbd'}])+"</div>")
        return out
    sect=lambda h,inner,empty,idn: f"<section class=sect aria-labelledby={idn}><h2 id={idn}>{h}</h2>{inner}<p class=empty>{empty}</p></section>"
    has_top=any((s.get('tier') or 9)<=2 for s in upcoming)
    radio=lambda v,l,chk: f"<label class=pill><input type=radio name=tier value={v}{' checked' if chk else ''}><span>{l}</span></label>"
    for d_ in ("cal/t","cal/team"): os.makedirs(f"{OUT}/{d_}",exist_ok=True)
    for lg in LANGS:
        set_lang(lg); O=OUT+'/'+PFX[lg].rstrip('/') if PFX[lg] else OUT
        for d_ in ("t","team"): os.makedirs(f"{O}/{d_}",exist_ok=True)
        W=lambda rel,html_: open(f"{O}/{rel}","w").write(html_)
        filt=(f"<form id=filters class=filters role=search onsubmit='return false'><fieldset><legend>{L['lg_tier']}</legend>{radio(1,L['t1'],False)}{radio(2,L['t12'],has_top)}{radio(3,L['t13'],False)}{radio('all',L['all'],not has_top)}</fieldset><fieldset><legend>{L['lg_fol']}</legend><label class=pill><input type=checkbox id=mine><span>{L['mine']}</span></label><label class=pill><input type=checkbox id=ffirst><span>{L['ffirst']}</span></label></fieldset>"
              f"<label for=q class=sr>{L['q_label']}</label><input id=q type=search placeholder='{L['q_ph']}' autocomplete=off></form>"
              f"<p class=tag>{L['filt_help']}</p>")
        body=(f"<h1 class=sr>{L['h1_home']}</h1><section class=sect id=ls aria-labelledby=h-live><h2 id=h-live>{L['ls']}</h2><div id=ls-list></div><p class=empty>{L['ls_empty']}</p></section>"
              f"<p class=note>{L['note']}</p>"+filt
              +sect(L['upc'],section(soon,'up'),L['upc_empty'],"h-up")
              +sect(L['rec'],section(recent,'done',limit=80),L['rec_empty'],"h-done")+signup())
        W("index.html",page(L['home_title'],body,0,"index.html",path="",desc=L['home_desc'],ld=events_ld(upcoming,LROOT,30)))
        for k,v in tours.items():
            n=TN[k]; sl=slug(n); url=f"{LROOT}t/{sl}.html"
            lp=f"https://liquipedia.net/dota2/{TL[k]}" if k in TL else f"https://liquipedia.net/dota2/index.php?search={urllib.parse.quote_plus(n)}"
            strm=watch_links({"streams":TS.get(k,[])},"btn",99,True,True) or f"<span class=tag>{L['no_stream']}</span>"
            b=(f"<h1>{hn(n)}{' <span class=tier>'+L['tier_h'].format(n=TT[k])+'</span>' if TT.get(k) else ''}</h1><div class=watch>{strm}</div>"
               f"<p class=tag>{cal_link(f'cal/t/{sl}.ics')} · <a href='{lp}' rel=noopener>Liquipedia</a> {L['lp_res']}</p>"
               +sect(L['lu'],section(v['up'],'up',1,False),L['none_sched'],"h-up")+sect(L['fin'],section(v['done'],'done',1,False),L['none_yet'],"h-done"))
            W(f"t/{sl}.html",page(L['t_title'].format(n=tr(n)),b,1,path=f"t/{sl}.html",desc=L['t_desc'].format(n=tr(n)),ld=events_ld(v['up']+v['done'],url)))
            if lg=='en': open(f"{OUT}/cal/t/{sl}.ics","w",newline="").write(ics(n,[s for s in v['up']+v['done'] if s['pair']!={'tbd'}],url))
        act=lambda v:max(x['start'] for x in v['up']+v['done'])
        lst="".join(f"<div class='m tl'><div class=tag>{L['tl_counts'].format(u=len(v['up']),d=len(v['done']))}</div><div class=tlh><span class=teams><a class=tla href='t/{slug(TN[k])}.html'>{hn(TN[k])}</a>{f'<span class=tier>T{TT[k]}</span>' if TT.get(k) else ''}</span>{cal_link(f'cal/t/{slug(TN[k])}.ics',False)}</div></div>" for k,v in sorted(tours.items(),key=lambda kv:-act(kv[1])))
        W("tournaments.html",page(L['tours_title'],f"<h1>{L['tournaments']}</h1>"+lst,0,"tournaments.html",path="tournaments.html",desc=L['tours_desc']))
        for k,v in tm.items():
            n=TEAMS[k]; sl=slug(n); url=f"{LROOT}team/{sl}.html"
            b=(f"<h1>{hn(n)} {star(k,n,True)}</h1><p class=tag>{cal_link(f'cal/team/{sl}.ics')} · {L['team_sf']}</p>"
               +sect(L['lu'],section(v['up'],'up',1,False),L['team_up_empty'],"h-up")
               +f"<details class=tbd><summary>{L['later']}</summary><p class=tag>{L['later_note']}</p>{section(v['hid'],'up',1,False) if v.get('hid') else '<p class=empty>'+L['later_none']+'</p>'}</details>"
               +sect(L['recs'],section(v['done'],'done',1,False),L['recs_empty'],"h-done"))
            W(f"team/{sl}.html",page(L['team_title'].format(n=tr(n)),b,1,path=f"team/{sl}.html",desc=L['team_desc'].format(n=tr(n)),ld=events_ld(v['up']+v['done'],url)))
            if lg=='en': open(f"{OUT}/cal/team/{sl}.ics","w",newline="").write(ics(n,v['up']+v['done'],url))  # hidden later-round matches are not in v['up']
        tl="".join(f"<li data-teams={k} data-search=\"{e(both(TEAMS[k]))}\">{star(k,TEAMS[k])}<a href='team/{slug(TEAMS[k])}.html'>{hn(TEAMS[k])}</a>{'<span class=tag>'+(L['teams_up1'] if len(tm[k]['up'])==1 else L['teams_up'].format(u=len(tm[k]['up'])))+'</span>' if tm[k]['up'] else ''}</li>" for k in sorted(tm,key=lambda k:(not tm[k]['up'],TEAMS[k].lower())))
        W("teams.html",page(L['teams_title'],f"<h1>{L['teams']}</h1><p class=tag>{L['teams_intro']}</p><label for=tq class=sr>{L['tq']}</label><input id=tq class=tq type=search placeholder='{L['tq']}' autocomplete=off><ul class=teamlist id=teamlist>"+tl+"</ul>",0,"teams.html",path="teams.html",desc=L['teams_desc']))
        W("about.html",page(L['about_title'],L['about_body'].replace('{built}',f"{dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M}")+signup(),0,"about.html",path="about.html",desc=L['about_desc']))
        if lg=='en': W("404.html",page({'en':'Page not found | NoSpoilDota','es':'Página no encontrada | NoSpoilDota','pt':'Página não encontrada | NoSpoilDota'}[lg],
            {'en':"<h1>Page not found</h1><p><a href='/'>Go to the spoiler-free schedule →</a></p>",'es':"<h1>Página no encontrada</h1><p><a href='/es/'>Ir al calendario sin spoilers →</a></p>",'pt':"<h1>Página não encontrada</h1><p><a href='/pt/'>Ir para a agenda sem spoilers →</a></p>"}[lg],path="",nolist=True))
        W("newsletter.html",page(L['nl_title'],L['nl_body']+signup(False)+f"<p class=tag>{L['nl_foot']}</p>",path="newsletter.html",desc=L['nl_desc']))
        for d_ in ("t","team"):  # prune stale pages from earlier local builds
            for x in os.listdir(f"{O}/{d_}"):
                if x.rsplit('.',1)[0] not in keep[d_]: os.remove(f"{O}/{d_}/{x}")
    set_lang('en')
    for d_ in ("cal/t","cal/team"):
        for x in os.listdir(f"{OUT}/{d_}"):
            if x.rsplit('.',1)[0] not in keep[d_.split('/')[-1]]: os.remove(f"{OUT}/{d_}/{x}")
    open(f"{OUT}/style.css","w").write(CSS); open(f"{OUT}/app.js","w").write(JS)
    lm=dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%d')
    def urlent(loc,p): return (f"<url><loc>{e(loc)}</loc><lastmod>{lm}</lastmod>"+"".join(f"<xhtml:link rel=\"alternate\" hreflang=\"{HLANG[x]}\" href=\"{e(SITE+PFX[x]+p)}\"/>" for x in LANGS)
        +f"<xhtml:link rel=\"alternate\" hreflang=\"x-default\" href=\"{e(SITE+p)}\"/></url>")
    open(f"{OUT}/sitemap.xml","w").write('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:xhtml="http://www.w3.org/1999/xhtml">'
        +"".join(urlent(SITE+PFX[x]+p,p) for p in PAGES for x in LANGS)+"</urlset>\n")
    open(f"{OUT}/robots.txt","w").write(f"User-agent: *\nAllow: /\nSitemap: {SITE}sitemap.xml\n")
    open(f"{OUT}/CNAME","w").write("nospoildota.com\n")
    stats={"opendota_maps":len(raw),"opendota_series":len(recent),"liquipedia_upcoming":len(up),"live":len(live),"upcoming_7d":len(soon),
           "merged_live":len(used),"tournaments":len(tours),"teams":len(tm),"pages_per_lang":len(PAGES),"tiers":{t:sum(1 for s in up if s['tier']==t) for t in (1,2,3,4)}}
    json.dump(stats,open(f"{OUT}/stats.json","w")); print(stats)
    for n in sorted(MISSING): print(f"WARNING: CJK name without translation in data/name_translations.json: {n}")
if __name__=="__main__": build()
