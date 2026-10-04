import os, sys, collections
root0 = sys.argv[1]; outp = sys.argv[2]
n=0; sz=0; ptr=[]
for root,ds,fs in os.walk(os.path.join(root0,'submissions')):
    for f in fs:
        p=os.path.join(root,f)
        s=os.path.getsize(p)
        if s<1024:
            with open(p,'rb') as h:
                if h.read(40).startswith(b'version https://git-lfs'):
                    rel=os.path.relpath(p,root0).replace(os.sep,'/')
                    ptr.append(rel)
                    for l in open(p,encoding='utf-8'):
                        if l.startswith('size '): sz+=int(l.split()[1])
        n+=1
print('files',n,'lfs_pointers',len(ptr),'lfs_GB',round(sz/1e9,3))
open(outp,'w').write('\n'.join(ptr))
print(collections.Counter(os.path.basename(p) if not p.endswith('.jsonl') else '*.jsonl' for p in ptr).most_common(8))
