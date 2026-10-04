"""List a public S3 prefix over anonymous HTTPS (ListObjectsV2). Read-only, metadata only.
Usage: s3list.py <bucket> <prefix> [max_pages] [delimiter]"""
import sys, urllib.request, urllib.parse, xml.etree.ElementTree as ET

bucket, prefix = sys.argv[1], sys.argv[2]
max_pages = int(sys.argv[3]) if len(sys.argv) > 3 else 1
delim = sys.argv[4] if len(sys.argv) > 4 else None
ns = {"s3": "http://s3.amazonaws.com/doc/2006-03-01/"}
token, n, total, pages = None, 0, 0, 0
keys = []
prefixes = []
while pages < max_pages:
    q = {"list-type": "2", "prefix": prefix, "max-keys": "1000"}
    if delim:
        q["delimiter"] = delim
    if token:
        q["continuation-token"] = token
    url = f"https://{bucket}.s3.amazonaws.com/?" + urllib.parse.urlencode(q)
    x = ET.fromstring(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "b5a-audit"}), timeout=60).read())
    for c in x.findall("s3:Contents", ns):
        k = c.find("s3:Key", ns).text
        s = int(c.find("s3:Size", ns).text)
        keys.append((k, s))
        n += 1
        total += s
    for p in x.findall("s3:CommonPrefixes", ns):
        prefixes.append(p.find("s3:Prefix", ns).text)
    pages += 1
    t = x.find("s3:IsTruncated", ns).text
    if t != "true":
        break
    token = x.find("s3:NextContinuationToken", ns).text
print(f"objects={n} bytes={total} ({total/1e9:.3f} GB) pages={pages} truncated_more={t}")
for p in prefixes[:200]:
    print("PREFIX", p)
for k, s in keys[:8]:
    print(f"  {s:>12d} {k}")
