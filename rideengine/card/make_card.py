"""Share card generator (prototype).

Usage:  python -m rideengine.card.make_card card_config.json
Writes a self-contained Design Component (.dc.html) artboard: silver/graphite 9:16 card,
animated route draw + progress dots on map and elevation, open-arc dials, optional
vertical power strip. Prepare inputs with `python -m rideengine card` (see cli.py).

Config keys: pts, out, title, dist_km, towns [[name, lat, lon, km, "left"|"right"]],
marks [[label, lat, lon, side]], map_aria, ele_lo, ele_hi, ele_aria, ele_mid, meta_l,
meta_r, h1a, h1b, dials [[label, lo, hi, value, max_or_null, big, unit, sub, empty]],
power (optional path to a power-bins JSON).

Prototype code: written for speed of iteration, not structure. Rewrite in the app.
"""
import json,math
import sys
CFG=json.load(open(sys.argv[1]))
P=json.load(open(CFG['pts']))
GK=CFG['dist_km']/(P[-1]['d']/1000)  # scale GPS km to device km
BG='#111214';SIL='#ECEEF0';S2='#A9AEB3';S3='#6A6F75';LN='#2A2D31'
F="font-family:'Archivo',system-ui,sans-serif";M="font-family:'JetBrains Mono',ui-monospace,monospace"
CYC='9s';TRAVEL=0.55
lat0=sum(p['lat'] for p in P)/len(P)
xs=[p['lon']*math.cos(math.radians(lat0)) for p in P];ys=[-p['lat'] for p in P]
mnx,mny=min(xs),min(ys);sc0=1000/max(max(xs)-mnx,max(ys)-mny)
W0=(max(xs)-mnx)*sc0;H0=(max(ys)-mny)*sc0
def proj(lat,lon): return ((lon*math.cos(math.radians(lat0))-mnx)*sc0,(-lat-mny)*sc0)
R=[];nxt=0
for p,x,y in zip(P,xs,ys):
    if p['d']>=nxt: R.append(((x-mnx)*sc0,(y-mny)*sc0,p['d']/1000*GK));nxt+=120
E=[];nxt=0
for p in P:
    if p['d']>=nxt and p['ele'] is not None: E.append((p['d']/1000*GK,p['ele']));nxt+=200
# map
mw,mh=540,470
PW=json.load(open(CFG['power'])) if CFG.get('power') else None
mwe=468 if PW else mw
s=min((mh-30)/H0,(mwe-200)/W0); ox=(mwe-W0*s)/2; oy=(mh-H0*s)/2
f=lambda x,y:(round(ox+x*s,1),round(oy+y*s,1))
rd=' '.join(('M' if i==0 else 'L')+'%s %s'%f(x,y) for i,(x,y,k) in enumerate(R))
grid=''.join(f'<line x1="0" y1="{y}" x2="{mw}" y2="{y}" stroke="{LN}" stroke-width="1"></line>' for y in range(25,mh,70))+''.join(f'<line x1="{x}" y1="0" x2="{x}" y2="{mh}" stroke="{LN}" stroke-width="1"></line>' for x in range(20,mw,70))
towns=[tuple(t) for t in CFG['towns']]
tsvg='';thtml=''
for n,la,lo,km,side in towns:
    x,y=f(*proj(la,lo))
    tsvg+=f'<circle cx="{x}" cy="{y}" r="3.5" fill="{BG}" stroke="{S2}" stroke-width="1.5"></circle>'
    lab=n.upper()
    if side=='left':
        thtml+=f'<div style="position:absolute;right:{round(mw-x+9,1)}px;top:{round(y-7,1)}px;font-size:13px;letter-spacing:0.08em;color:{S2};{M};white-space:nowrap">{lab}</div>'
    else:
        thtml+=f'<div style="position:absolute;left:{round(x+9,1)}px;top:{round(y-7,1)}px;font-size:13px;letter-spacing:0.08em;color:{S2};{M};white-space:nowrap">{lab}</div>'
for lab,la,lo,side in CFG.get('marks',[]):
    x,y=f(*proj(la,lo))
    tsvg+=f'<circle cx="{x}" cy="{y}" r="7" fill="none" stroke="{SIL}" stroke-width="1.5"></circle><circle cx="{x}" cy="{y}" r="2.5" fill="{SIL}"></circle>'
    pos=f'left:{round(x+12,1)}px' if side=='right' else f'right:{round(mw-x+12,1)}px'
    thtml+=f'<div style="position:absolute;{pos};top:{round(y-8,1)}px;font-size:13px;letter-spacing:0.06em;color:{SIL};{M};font-weight:700;white-space:nowrap;background:{BG};padding:1px 4px">{lab}</div>'
ribbon=''
if PW:
    RW,RH,RT=56,330,34;SC=600
    sim_tag=f'<span style="color:{BG};background:{S2};padding:0 3px;font-size:10px;font-weight:700">SIM</span>' if PW.get('simulated',True) else ''
    b=PW['bins'];nb=len(b)
    pts=' '.join(f'L{round(RW-min(p,SC)/SC*RW,1)} {round(i/(nb-1)*RH,1)}' for i,p in enumerate(b))
    area=f'M{RW} 0 '+pts+f' L{RW} {RH} Z'
    ax=round(RW-PW['avg']/SC*RW,1)
    def row(k,v,strong=False):
        return f'<div style="display:flex;justify-content:flex-end;align-items:baseline;gap:5px;white-space:nowrap"><span style="color:{S3}">{k}</span><span style="color:{SIL if strong else S2};font-weight:{700 if strong else 500};letter-spacing:0.02em">{v}</span></div>'
    ribbon=f'''<div role="img" aria-label="{'Simulated power' if PW.get('simulated',True) else 'Power'} along the ride: average {PW['avg']} W, max {PW['max']} W" style="position:absolute;right:14px;top:0;width:{RW}px;display:flex;flex-direction:column;gap:6px;{M};font-size:12px;letter-spacing:0.06em">
<div style="display:flex;flex-direction:column;align-items:flex-end;gap:2px;height:28px;justify-content:flex-end"><span style="color:{SIL};font-weight:700">POWER</span>{sim_tag}</div>
<div style="position:relative;width:{RW}px;height:{RH}px;border-right:1px solid {S3}">
<svg width="{RW}" height="{RH}" viewBox="0 0 {RW} {RH}" aria-hidden="true" style="display:block;position:absolute;left:0;top:0">
<line x1="{round(RW-200/SC*RW,1)}" y1="0" x2="{round(RW-200/SC*RW,1)}" y2="{RH}" stroke="{LN}" stroke-width="1"></line>
<line x1="{round(RW-400/SC*RW,1)}" y1="0" x2="{round(RW-400/SC*RW,1)}" y2="{RH}" stroke="{LN}" stroke-width="1"></line>
<path d="{area}" fill="{SIL}" fill-opacity="0.75"></path>
<line x1="{ax}" y1="0" x2="{ax}" y2="{RH}" stroke="{BG}" stroke-width="1" stroke-dasharray="2 2"></line>
</svg>
<div class="pw-line" style="position:absolute;left:-6px;top:0;width:{RW+6}px;height:2px;background:{SIL};box-shadow:0 0 8px rgba(236,238,240,0.8)"></div>
</div>
<div style="display:flex;justify-content:space-between;color:{S3};font-size:10px"><span>600 W</span><span>0</span></div>
<div style="display:flex;flex-direction:column;align-items:flex-end;align-self:flex-end;width:max-content;gap:4px;font-size:12px">{row('AVG',str(PW['avg'])+' W',True)}{row('MAX',str(PW['max'])+' W')}</div>
</div>'''
    RHpx=RH
mapsvg=f'''<svg width="{mw}" height="{mh}" viewBox="0 0 {mw} {mh}" role="img" aria-label="{CFG['map_aria']}" style="display:block;position:absolute;left:0;top:0">
{grid}
<path d="{rd}" fill="none" stroke="{S3}" stroke-opacity="0.35" stroke-width="2" stroke-linejoin="round"></path>
<path class="r-draw" pathLength="1" d="{rd}" fill="none" stroke="{SIL}" stroke-width="3.5" stroke-linejoin="round" stroke-linecap="round"></path>
{tsvg}
</svg>'''
# elevation
ew,eh=476,64;mn,mx=CFG['ele_lo'],CFG['ele_hi'];top=6;bot=6
X=lambda km:round(km/CFG['dist_km']*ew,1);Y=lambda e:round(top+(mx-e)/(mx-mn)*(eh-top-bot),1)
el=' '.join(('M' if i==0 else 'L')+'%s %s'%(X(k),Y(e)) for i,(k,e) in enumerate(E))
area=el+' L%s %s L0 %s Z'%(X(E[-1][0]),eh,eh)
eticks=''.join(f'<line x1="{X(km)}" y1="0" x2="{X(km)}" y2="{eh}" stroke="{LN}" stroke-width="1" stroke-dasharray="2 3"></line>' for n,la,lo,km,side in towns if 0<km<CFG['dist_km']-0.5)
elevsvg=f'''<svg width="{ew}" height="{eh}" viewBox="0 0 {ew} {eh}" role="img" aria-label="{CFG['ele_aria']}" style="display:block;position:absolute;left:0;top:0">
{eticks}
<path d="{area}" fill="{SIL}" fill-opacity="0.14"></path>
<path d="{el}" fill="none" stroke="{S2}" stroke-width="1.5" stroke-linejoin="round"></path>
</svg>'''
_et=[(n,km) for n,la,lo,km,side in towns if 0<km<CFG['dist_km']-0.5]
etown=''.join(f'<span style="position:absolute;left:{X(km)}px;top:{0 if i%2==0 else 15}px;transform:translateX(-50%);font-size:11px;letter-spacing:0.04em;color:{S2};{M};white-space:nowrap">{n.upper()}</span>' for i,(n,km) in enumerate(_et))
# dials
D=96;c=D/2;A0,A1=-135,135
def pt(r,a):
    t=math.radians(a-90);return round(c+r*math.cos(t),2),round(c+r*math.sin(t),2)
def arc(r,a0,a1):
    x0,y0=pt(r,a0);x1,y1=pt(r,a1);return f'M{x0} {y0} A{r} {r} 0 {1 if a1-a0>180 else 0} 1 {x1} {y1}'
RO,RI=42,34;kf=''
def dial(idx,label,lo,hi,val,mxv,big,unit,sub,empty=False):
    global kf
    ang=lambda v:A0+(max(lo,min(hi,v))-lo)/(hi-lo)*(A1-A0)
    out=f'<path d="{arc(RO,A0,A1)}" fill="none" stroke="{LN}" stroke-width="6" stroke-linecap="round"></path>'
    if mxv is not None: out+=f'<path d="{arc(RI,A0,A1)}" fill="none" stroke="{LN}" stroke-width="3" stroke-linecap="round"></path>'
    d0=TRAVEL+0.02+idx*0.03
    p=lambda x:f'{x*100:.0f}%'
    if not empty:
        out+=f'<path class="a-v{idx}" pathLength="1" d="{arc(RO,A0,ang(val))}" fill="none" stroke="{SIL}" stroke-width="6" stroke-linecap="round"></path>'
        kf+=f'.a-v{idx}{{stroke-dasharray:1;stroke-dashoffset:0;animation:av{idx} {CYC} cubic-bezier(.3,.8,.3,1) infinite}}\n@keyframes av{idx}{{0%,{p(d0)}{{stroke-dashoffset:1}}{p(d0+0.14)},100%{{stroke-dashoffset:0}}}}\n'
        if mxv is not None:
            out+=f'<path class="a-m{idx}" pathLength="1" d="{arc(RI,A0,ang(mxv))}" fill="none" stroke="{S2}" stroke-width="3" stroke-linecap="round"></path>'
            kf+=f'.a-m{idx}{{stroke-dasharray:1;stroke-dashoffset:0;animation:am{idx} {CYC} cubic-bezier(.3,.8,.3,1) infinite}}\n@keyframes am{idx}{{0%,{p(d0+0.04)}{{stroke-dashoffset:1}}{p(d0+0.18)},100%{{stroke-dashoffset:0}}}}\n'
    x0,y0=pt(RO,A0);x1,y1=pt(RO,A1)
    ends='' if True else f'<text x="{x0-2}" y="{y0+14}" text-anchor="middle" font-size="8" fill="{S3}" style="{M}">{lo}</text><text x="{x1+2}" y="{y1+14}" text-anchor="middle" font-size="8" fill="{S3}" style="{M}">{hi}</text>' if not empty else ''
    vcol=S3 if empty else SIL
    aria=f'{label}: no data yet' if empty else f'{label}: {big} {unit.lower()}'+(f', {sub}' if mxv else '')
    return f'''<div style="display:flex;flex-direction:column;align-items:center;gap:4px">
<div style="position:relative;width:{D}px;height:{D}px">
<svg width="{D}" height="{D}" viewBox="0 0 {D} {D}" role="img" aria-label="{aria}" style="display:block;overflow:visible">{out}{ends}</svg>
<div style="position:absolute;left:0;right:0;top:{c-16}px;display:flex;flex-direction:column;align-items:center">
<span style="font-size:24px;font-weight:700;line-height:1;color:{vcol};{F};font-stretch:112%;font-variant-numeric:tabular-nums">{big}</span>
<span style="font-size:10.5px;letter-spacing:0.04em;color:{S2};{M};margin-top:3px">{unit}</span>
</div>
<div style="position:absolute;left:0;right:0;top:{D-16}px;text-align:center;font-size:11px;letter-spacing:0.06em;text-transform:uppercase;color:{S2};{M}">{label}</div>
</div>
<span style="font-size:11px;color:{S2};{M};white-space:nowrap">{sub}</span>
</div>'''
ds=''.join(dial(i+1,*d[:-1],empty=d[-1]) for i,d in enumerate(CFG['dials']))
def dot(pathd,size):
    return f'offset-path:path("{pathd}");offset-rotate:0deg;offset-anchor:50% 50%;width:{size}px;height:{size}px'
css=f'''body{{margin:0;background:{BG}}}
a{{color:{SIL}}}a:hover{{color:#FFFFFF}}
.r-draw{{stroke-dasharray:1;stroke-dashoffset:0;animation:draw {CYC} linear infinite}}
@keyframes draw{{0%{{stroke-dashoffset:1}}{TRAVEL*100:.0f}%,100%{{stroke-dashoffset:0}}}}
.dot-map{{position:absolute;left:0;top:0;{dot(rd,12)};border-radius:50%;background:{SIL};box-shadow:0 0 0 4px rgba(236,238,240,0.18),0 0 14px rgba(236,238,240,0.6);animation:go {CYC} linear infinite}}
.dot-el{{position:absolute;left:0;top:0;{dot(el,9)};border-radius:50%;background:{SIL};box-shadow:0 0 0 3px rgba(236,238,240,0.18);animation:go {CYC} linear infinite}}
@keyframes pw{{0%{{transform:translateY(0)}}{TRAVEL*100:.0f}%,100%{{transform:translateY({330 if PW else 0}px)}}}}
.pw-line{{animation:pw {CYC} linear infinite}}
@keyframes go{{0%{{offset-distance:0%}}{TRAVEL*100:.0f}%,100%{{offset-distance:100%}}}}
{kf}@media (prefers-reduced-motion: reduce){{.r-draw,.dot-map,.dot-el,.pw-line,[class^="a-"]{{animation:none!important}}.dot-map,.dot-el{{offset-distance:100%}}}}
'''
props={"$preview":{"width":540,"height":960}}
html=f'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{CFG['title']}</title>
<script src="./support.js"></script>
</head>
<body>
<x-dc>
<helmet>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo:wdth,wght@62..125,400..800&amp;family=JetBrains+Mono:wght@500;700&amp;display=swap">
<style>
{css}</style>
</helmet>
<div style="width:540px;height:960px;box-sizing:border-box;background:{BG};color:{SIL};display:flex;flex-direction:column;{F};overflow:hidden">
<header style="display:flex;flex-direction:column;gap:14px;padding:34px 32px 0">
<div style="display:flex;justify-content:space-between;font-size:13px;letter-spacing:0.1em;color:{S2};{M}"><span>{CFG['meta_l']}</span><span>{CFG['meta_r']}</span></div>
<h1 style="margin:0;font-size:46px;line-height:0.98;font-weight:800;font-stretch:118%;letter-spacing:-0.01em;color:{SIL};text-wrap:balance"><span style="color:{S3}">{CFG['h1a']}</span><br>{CFG['h1b']}</h1>
</header>
<div style="position:relative;width:{mw}px;height:{mh}px;margin-top:8px;flex:none">
{mapsvg}{thtml}{ribbon}
<div class="dot-map" aria-hidden="true"></div>
</div>
<div style="padding:0 32px;display:flex;flex-direction:column;gap:4px">
<div style="position:relative;height:28px">{etown}</div>
<div style="position:relative;width:{ew}px;height:{eh}px">
{elevsvg}
<div class="dot-el" aria-hidden="true"></div>
</div>
<div style="display:flex;justify-content:space-between;font-size:12px;letter-spacing:0.06em;color:{S2};{M}"><span>KM 0</span><span>{CFG['ele_mid']}</span><span>KM {CFG['dist_km']}</span></div>
</div>
<div style="display:grid;grid-template-columns:repeat(5,minmax(0,1fr));padding:22px 8px 0;justify-items:center">
{ds}
</div>
</div>
</x-dc>
<script type="text/x-dc" data-dc-script data-props='{json.dumps(props)}'>
class Component extends DCLogic {{
renderVals() {{
return {{}};
}}
}}
</script>
</body>
</html>
'''
open(CFG['out'],'w').write(html)
print(len(html))
