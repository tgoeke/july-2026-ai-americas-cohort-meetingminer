"""Measure what the embedding threshold actually does on the real corpus."""
import psycopg, itertools, math
from meetingminer.config import load_config
from meetingminer import db
from meetingminer.adapters.embed import build_embedder

config = load_config()
emb = build_embedder(config)
with psycopg.connect(db.conninfo(config), connect_timeout=10) as conn:
    rows = conn.execute(
        "select t.id, t.name, m.meeting_id from topic t "
        "join topic_mention m on m.topic_id = t.id group by t.id, t.name, m.meeting_id"
    ).fetchall()
names, meeting_of = [], {}
for _id, name, mid in rows:
    if _id not in meeting_of:
        names.append((_id, name)); meeting_of[_id] = mid
print(f"{len(names)} topics; median name length "
      f"{sorted(len(n.split()) for _, n in names)[len(names)//2]} words")

vecs = emb.embed_documents([n for _, n in names])
def norm(v):
    m = math.sqrt(sum(x*x for x in v)) or 1.0
    return [x/m for x in v]
vecs = [norm(v) for v in vecs]

pairs = []
for (i, (ai, _)), (j, (bi, _)) in itertools.combinations(list(enumerate(names)), 2):
    s = sum(x*y for x, y in zip(vecs[i], vecs[j]))
    if s >= 0.60:
        pairs.append((s, ai, bi))
pairs.sort(reverse=True)

class DS:
    def __init__(s): s.p = {}
    def find(s, x):
        s.p.setdefault(x, x)
        while s.p[x] != x: s.p[x] = s.p[s.p[x]]; x = s.p[x]
        return x
    def union(s, a, b): s.p[s.find(a)] = s.find(b)

print(f"\n{'thresh':>7} {'links':>6} {'threads':>8} {'multi-meeting':>14} {'largest':>8}")
for t in (0.90, 0.88, 0.86, 0.84, 0.82, 0.80, 0.78, 0.76, 0.74, 0.72, 0.70):
    ds = DS()
    for _id, _ in names: ds.find(_id)
    n = 0
    for s, a, b in pairs:
        if s >= t: ds.union(a, b); n += 1
    cl = {}
    for _id, _ in names: cl.setdefault(ds.find(_id), []).append(_id)
    multi = sum(1 for v in cl.values() if len({meeting_of[x] for x in v}) >= 2)
    largest = max(len({meeting_of[x] for x in v}) for v in cl.values())
    print(f"{t:>7.2f} {n:>6} {len(cl):>8} {multi:>14} {largest:>8}")
