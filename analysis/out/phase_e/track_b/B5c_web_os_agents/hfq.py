import urllib.request, json, sys, urllib.parse
def get(url):
    req=urllib.request.Request(url, headers={'User-Agent':'research-audit'})
    return json.load(urllib.request.urlopen(req, timeout=60))
if sys.argv[1]=='search':
    for q in sys.argv[2:]:
        print('==',q)
        try:
            for d in get('https://huggingface.co/api/datasets?search='+urllib.parse.quote(q)+'&limit=60'):
                print(' ',d['id'], 'gated=',d.get('gated'), 'dl=',d.get('downloads'), d.get('lastModified','')[:10])
        except Exception as e: print('ERR',e)
elif sys.argv[1]=='info':
    for rid in sys.argv[2:]:
        print('==',rid)
        try:
            d=get('https://huggingface.co/api/datasets/'+rid+'?blobs=true')
            cd=d.get('cardData') or {}
            print(' sha',d.get('sha'),'gated',d.get('gated'),'private',d.get('private'),'lastModified',d.get('lastModified'))
            print(' license', cd.get('license'), cd.get('license_name'), 'tags', [t for t in d.get('tags',[]) if t.startswith('license')])
            sib=d.get('siblings',[])
            tot=sum((s.get('size') or 0) for s in sib)
            print(' nfiles',len(sib),'total_bytes',tot, round(tot/1e9,3),'GB')
            for s in sib[:int(sys.argv[-1]) if sys.argv[-1].isdigit() else 40]:
                print('   ',s['rfilename'], s.get('size'))
        except Exception as e: print('ERR',e)
