"""Convert the warehouse Layout.xlsx (one sheet per floor, walls drawn as cell borders,
room names as cell text or text boxes) into warehouse-layout.json (schema v1).

Usage: python layout_to_json.py Layout.xlsx warehouse-layout.json
Needs: openpyxl. See warehouse-map-spec.md for the output schema.
DEFAULT_BINS below is SAMPLE data: replace with the real bin-prefix -> room assignments.
"""
import openpyxl, re, json, sys, zipfile
from collections import deque
src,dst=sys.argv[1],sys.argv[2]
wb=openpyxl.load_workbook(src); z=zipfile.ZipFile(src)
EMU=9525; CW=183173/EMU; RH=20.0
floors=[]
for idx,ws in enumerate(wb.worksheets,1):
    # bounds from borders
    R=C=0
    cells={}
    for row in ws.iter_rows():
        for c in row:
            b=c.border
            if any(s and s.style for s in (b.top,b.bottom,b.left,b.right)) or c.value is not None:
                R=max(R,c.row);C=max(C,c.column)
    R+=2;C+=2
    xs=[0];ys=[0]
    for c in range(1,C+1):
        d=ws.column_dimensions.get(openpyxl.utils.get_column_letter(c))
        xs.append(xs[-1]+(d.width/2.82421875*CW if d and d.customWidth and d.width else CW))
    for r in range(1,R+1):
        d=ws.row_dimensions.get(r); ys.append(ys[-1]+((d.height*4/3) if d and d.height else RH))
    mid={}
    for m in ws.merged_cells.ranges:
        for r in range(m.min_row,m.max_row+1):
            for c in range(m.min_col,m.max_col+1): mid[(r,c)]=str(m)
    same=lambda a,b: a in mid and mid.get(a)==mid.get(b)
    H=set();V=set()  # H:(r,c) wall below cell r col c ; V:(c,r) wall right of col c at row r
    for row in ws.iter_rows(min_row=1,max_row=R,max_col=C):
        for c in row:
            b=c.border;r,k=c.row,c.column
            if b.top and b.top.style and not same((r,k),(r-1,k)): H.add((r-1,k))
            if b.bottom and b.bottom.style and not same((r,k),(r+1,k)): H.add((r,k))
            if b.left and b.left.style and not same((r,k),(r,k-1)): V.add((k-1,r))
            if b.right and b.right.style and not same((r,k),(r,k+1)): V.add((k,r))
    # labels
    labels=[]
    merged={(m.min_row,m.min_col):m for m in ws.merged_cells.ranges}
    def cellAt(px,py):
        c=next(i for i in range(1,C+1) if xs[i]>px); r=next(i for i in range(1,R+1) if ys[i]>py); return r,c
    for row in ws.iter_rows():
        for c in row:
            if c.value is None or str(c.value).strip().upper()=='X': continue
            m=merged.get((c.row,c.column))
            r0,c0,r1,c1=(m.min_row,m.min_col,m.max_row,m.max_col) if m else (c.row,c.column,c.row,c.column)
            labels.append((str(c.value).strip(),(xs[c0-1]+xs[c1])/2,(ys[r0-1]+ys[r1])/2,(r0,c0,r1,c1) if m else None))
    pin=None
    rels=z.read(f'xl/worksheets/_rels/sheet{idx}.xml.rels').decode()
    dm=re.search(r'drawings/(drawing\d+\.xml)',rels)
    if dm:
        s=z.read('xl/drawings/'+dm.group(1)).decode()
        for a in re.findall(r'<xdr:twoCellAnchor.*?</xdr:twoCellAnchor>',s,re.S):
            def pos(t):
                g=re.search(rf'<xdr:{t}><xdr:col>(\d+)</xdr:col><xdr:colOff>(-?\d+)</xdr:colOff><xdr:row>(\d+)</xdr:row><xdr:rowOff>(-?\d+)</xdr:rowOff>',a)
                c,co,r,ro=map(int,g.groups()); return xs[c]+co/EMU, ys[r]+ro/EMU
            (x0,y0),(x1,y1)=pos('from'),pos('to')
            if '<xdr:pic' in a: pin=((x0+x1)/2,(y0+y1)/2); continue
            t=' '.join(x.strip() for x in re.findall(r'<a:t>(.*?)</a:t>',a)).strip()
            if t: labels.append((t,(x0+x1)/2,(y0+y1)/2,None))
    # rooms by ray cast
    rooms=[]
    for t,cx,cy,mr in labels:
        rc,cc=cellAt(cx,cy)
        l=cc
        while l>1 and (l-1,rc) not in V: l-=1
        rt=cc
        while rt<C and (rt,rc) not in V: rt+=1
        tp=rc
        while tp>1 and (tp-1,cc) not in H: tp-=1
        bt=rc
        while bt<R and (bt,cc) not in H: bt+=1
        if mr: tp,l,bt,rt=mr
        low=t.lower()
        kind='lift' if low=='lift' else 'stairs' if low.startswith('tangga') else 'wc' if 'mandi' in low else 'rack' if low.startswith('rak') else 'room'
        rooms.append(dict(name=t,kind=kind,r0=tp,c0=l,r1=bt,c1=rt,lx=round(cx,1),ly=round(cy,1),rc=rc,cc=cc))
    # flood fill unlabeled regions
    seen={};comps=[]
    for r in range(1,R+1):
        for c in range(1,C+1):
            if (r,c) in seen: continue
            q=deque([(r,c)]);seen[(r,c)]=len(comps);cs=[]
            while q:
                a,b=q.popleft();cs.append((a,b))
                for na,nb,blk in ((a,b+1,(b,a) in V),(a,b-1,(b-1,a) in V),(a+1,b,(a,b) in H),(a-1,b,(a-1,b) in H)):
                    if 1<=na<=R and 1<=nb<=C and not blk and (na,nb) not in seen:
                        seen[(na,nb)]=len(comps);q.append((na,nb))
            comps.append(cs)
    centers={(rm['rc'],rm['cc']) for rm in rooms}
    for rm in rooms:
        cs=comps[seen[(rm['rc'],rm['cc'])]]
        rect=(rm['r1']-rm['r0']+1)*(rm['c1']-rm['c0']+1)
        closed=not any(a in (1,R) or b in (1,C) for a,b in cs)
        others=sum(1 for x in centers if x in set(cs))
        if closed and others==1 and len(cs)<=rect*2.5: rm['cells']=sorted(cs)
        else: rm['cells']=[(r,c) for r in range(rm['r0'],rm['r1']+1) for c in range(rm['c0'],rm['c1']+1)]
    covered=set()
    for rm in rooms: covered.update(rm['cells'])
    areas=[]
    for cs in comps:
        if any(a in (1,R) or b in (1,C) for a,b in cs): continue  # outside
        n=len(cs); cov=sum(1 for x in cs if x in covered)
        if cov>n*0.3: continue
        if n<3: continue
        areas.append(cs)
    print(ws.title,'rooms:',[(x['name'],len(x['cells'])) for x in rooms],'R',R,'C',C,'areas',sorted(len(a) for a in areas),'pin',pin)
    def rle(cs):
        out=[];
        for r,c in sorted(cs):
            if out and out[-1][0]==r and out[-1][2]==c-1: out[-1][2]=c
            else: out.append([r,c,c])
        return out
    for rm in rooms:
        rm['cells']=rle(rm['cells'])
        for k in ('r0','c0','r1','c1','rc','cc'): rm.pop(k)
    floors.append(dict(name=ws.title,R=R,C=C,xs=[round(v,2) for v in xs],ys=[round(v,2) for v in ys],
        H=[list(x) for x in sorted(H)],V=[list(x) for x in sorted(V)],rooms=rooms,areas=[rle(a) for a in areas],pin=[round(pin[0],1),round(pin[1],1)] if pin else None))
geo=json.loads(json.dumps(floors))  # tuples -> lists


# ---- emit schema v1 ----
DEFAULT_BINS={(1,"Rak"):["D-00"],(2,"201"):["A-01"],(2,"202"):["A-02"],(2,"208"):["B-03"],(3,"304"):["B-04"],(3,"301"):["C-01"]}
UP={1:"Tangga",2:"Tangga ke lt 3",3:"Tangga ke lt 4"}; DOWN={2:"Tangga dari Lt 1",3:"Tangga dari Lt 2",4:"Tangga"}
slug=lambda s:re.sub(r'[^a-z0-9]+','-',s.lower()).strip('-')
out={"version":1,"source":"Layout.xlsx","units":"px at 100% zoom (1 column ~ 19.2, 1 row = 20)","floors":[],"connectors":{"stairs":[],"lift":[]}}
ids={}
for i,g in enumerate(geo,1):
    rooms=[]
    for r in g["rooms"]:
        rid=f"L{i}-{slug(r['name'])}"; ids[(i,r['name'])]=rid
        rooms.append({"id":rid,"kind":r["kind"],"name":r["name"],"labelAt":[r["lx"],r["ly"]],"cells":r["cells"],"bins":DEFAULT_BINS.get((i,r["name"]),[])})
    for j,a in enumerate(g["areas"],1):
        rooms.append({"id":f"L{i}-area-{j}","kind":"area","name":None,"labelAt":None,"cells":a,"bins":[]})
    out["floors"].append({"index":i,"name":g["name"],"grid":{"colX":g["xs"],"rowY":g["ys"]},
        "walls":{"below":g["H"],"right":g["V"]},"youAreHere":g["pin"],"rooms":rooms})
for f,n in UP.items(): out["connectors"]["stairs"].append({"lower":ids[(f,n)],"upper":ids[(f+1,DOWN[f+1])]})
out["connectors"]["lift"]=[ids[(i,n)] for (i,n) in ids if n.lower()=="lift"]
json.dump(out,open(dst,"w"),separators=(",",":"))
print(json.dumps(out["connectors"]),[ [r["id"] for r in fl["rooms"] if r["kind"]!="area"] for fl in out["floors"]])
