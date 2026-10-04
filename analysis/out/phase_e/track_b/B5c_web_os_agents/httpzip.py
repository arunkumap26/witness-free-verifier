import urllib.request, io, zipfile, sys, json
class HTTPFile(io.RawIOBase):
    def __init__(self, url):
        self.url=url; self.pos=0; self.nbytes=0; self.nreq=0
        req=urllib.request.Request(url, method='HEAD', headers={'User-Agent':'research-audit'})
        r=urllib.request.urlopen(req, timeout=60)
        self.final=r.geturl(); self.size=int(r.headers['Content-Length'])
    def seekable(self): return True
    def readable(self): return True
    def tell(self): return self.pos
    def seek(self, off, whence=0):
        if whence==0: self.pos=off
        elif whence==1: self.pos+=off
        else: self.pos=self.size+off
        return self.pos
    def read(self, n=-1):
        if n is None or n<0: n=self.size-self.pos
        if n==0 or self.pos>=self.size: return b''
        end=min(self.pos+n, self.size)-1
        req=urllib.request.Request(self.final, headers={'User-Agent':'research-audit','Range':f'bytes={self.pos}-{end}'})
        for attempt in range(4):
            try:
                data=urllib.request.urlopen(req, timeout=120).read(); break
            except Exception as e:
                if attempt==3: raise
        self.pos+=len(data); self.nbytes+=len(data); self.nreq+=1
        return data
    def readinto(self, b):
        d=self.read(len(b)); b[:len(d)]=d; return len(d)
def open_zip(url):
    f=HTTPFile(url)
    z=zipfile.ZipFile(io.BufferedReader(f, buffer_size=1<<16))
    return f,z
if __name__=='__main__':
    url=sys.argv[1]
    f,z=open_zip(url)
    names=z.infolist()
    print('size',f.size,'members',len(names),'bytes_read',f.nbytes,'reqs',f.nreq)
    import collections
    ext=collections.Counter(n.filename.rsplit('.',1)[-1] if '.' in n.filename.rsplit('/',1)[-1] else '(none)' for n in names)
    print(ext.most_common(20))
    for n in names[:60]: print(n.filename, n.file_size, n.date_time)
