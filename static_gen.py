"""One-off generator for static/ (favicons + og.png). Run manually; outputs are committed."""
from PIL import Image,ImageDraw,ImageFont
F="/usr/share/fonts/truetype/sand-box/google/Inter/Inter-VariableFont_opsz,wght.ttf"
BG,CARD,FG,ACC,MUT,BD=(15,17,21),(24,27,34),(232,235,241),(224,83,61),(154,163,181),(42,47,58)
def font(sz,w='ExtraBold'):
    f=ImageFont.truetype(F,sz)
    try: f.set_variation_by_name(w)
    except Exception: pass
    return f
def icon(n):
    S=n*4; im=Image.new('RGBA',(S,S),(0,0,0,0)); d=ImageDraw.Draw(im)
    d.rounded_rectangle((0,0,S-1,S-1),radius=int(S*.22),fill=BG+(255,))
    f=font(int(S*.56)); t1,t2="N","S"
    w1=d.textlength(t1,font=f); w2=d.textlength(t2,font=f); x=(S-w1-w2)/2; y=S/2
    d.text((x,y),t1,font=f,fill=FG,anchor='lm'); d.text((x+w1,y),t2,font=f,fill=ACC,anchor='lm')
    return im.resize((n,n),Image.LANCZOS)
icon(180).convert('RGB').save('static/apple-touch-icon.png')
icon(512).save('static/icon-512.png'); icon(192).save('static/icon-192.png')
icon(64).save('static/favicon.ico',sizes=[(16,16),(32,32),(48,48),(64,64)])
open('static/icon.svg','w').write('''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect width="64" height="64" rx="14" fill="#0f1115"/><text x="32" y="33" dominant-baseline="central" text-anchor="middle" font-family="Inter,system-ui,-apple-system,Segoe UI,Roboto,sans-serif" font-weight="800" font-size="36" letter-spacing="-1"><tspan fill="#e8ebf1">N</tspan><tspan fill="#e0533d">S</tspan></text></svg>
''')
open('static/site.webmanifest','w').write('{"name":"NoSpoilDota","short_name":"NoSpoilDota","icons":[{"src":"/icon-192.png","sizes":"192x192","type":"image/png"},{"src":"/icon-512.png","sizes":"512x512","type":"image/png"}],"theme_color":"#0f1115","background_color":"#0f1115","display":"standalone","start_url":"/"}\n')
W,H=1200,630; im=Image.new('RGB',(W,H),BG); d=ImageDraw.Draw(im)
d.rectangle((0,0,W,10),fill=ACC)
ic=icon(120); im.paste(ic,(90,150),ic); d.rounded_rectangle((90,150,209,269),radius=26,outline=BD,width=2)
f=font(96); x=90; y=330
d.text((x,y),"NoSpoil",font=f,fill=FG,anchor='ls'); d.text((x+d.textlength("NoSpoil",font=f),y),"Dota",font=f,fill=ACC,anchor='ls')
d.text((x,y+70),"Pro Dota 2 schedule & replays, spoiler-free",font=font(44,'SemiBold'),fill=FG,anchor='ls')
d.rounded_rectangle((x,y+120,x+560,y+180),radius=12,fill=CARD,outline=BD,width=2)
d.text((x+24,y+150),"No scores · no winners · no game counts",font=font(26,'Medium'),fill=MUT,anchor='lm')
d.text((W-90,H-50),"nospoildota.com",font=font(28,'SemiBold'),fill=MUT,anchor='rs')
im.save('static/og.png',optimize=True)
