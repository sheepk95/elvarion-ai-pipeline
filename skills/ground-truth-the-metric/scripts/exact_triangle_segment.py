"""Non-coplanar triangle intersection segment length on parsed binary coordinates.
Exact predicates do not imply physical precision. Coplanar overlaps are unsupported;
tangencies/degenerate triangles are not a complete contact classifier.
No file/network/engine access. Run directly for five known-answer controls.
"""
import math,itertools
def sub(a,b):return tuple(x-y for x,y in zip(a,b))
def add(a,b):return tuple(x+y for x,y in zip(a,b))
def mul(a,s):return tuple(x*s for x in a)
def dot(a,b):return sum(x*y for x,y in zip(a,b))
def cross(a,b):return (a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0])
def norm(a):return math.sqrt(dot(a,a))
from fractions import Fraction as F
def edge_hit(p,q,tri):
 a,b,c=tri;direction=sub(q,p);e1=sub(b,a);e2=sub(c,a);h=cross(direction,e2);det=dot(e1,h)
 if det==0:return None
 s=sub(p,a);u=dot(s,h)/det;qv=cross(s,e1);v=dot(direction,qv)/det;t=dot(e2,qv)/det
 if min(u,v,t)<0 or u+v>1 or t>1:return None
 return add(p,mul(direction,t))
def segment(a,b):
 # Exact rational predicates on the parsed binary coordinates. No absolute
 # endpoint deduplication floor that would discard sub-nanometre segments.
 a=[tuple(F(x) for x in p) for p in a];b=[tuple(F(x) for x in p) for p in b];points=set()
 for source,target in [(a,b),(b,a)]:
  for i,j in [(0,1),(1,2),(2,0)]:
   p=edge_hit(source[i],source[j],target)
   if p is not None:points.add(p)
 lengths=[dot(sub(p,q),sub(p,q)) for p,q in itertools.combinations(points,2)]
 return math.sqrt(float(max(lengths,default=0)))

if __name__ == "__main__":
    base=[(0.,0,0),(1.,0,0),(0.,1,0)]
    assert abs(segment([(0.,0,-1),(1.,0,1),(0.,1,1)],base)-math.sqrt(.5))<1e-12
    assert segment([(0.,0,1),(1.,0,1),(0.,1,1)],base)==0
    assert segment([(3.,0,-1),(4.,0,1),(3.,1,1)],base)==0
    assert abs(segment([(-1.,.25,-1),(1.,.25,1),(1.,1.25,-1)],base)-.5590169943749474)<1e-12
    tiny=1e-9
    assert abs(segment([(0.,0,-tiny),(tiny,0,tiny),(0.,tiny,tiny)],[(0.,0,0),(tiny,0,0),(0.,tiny,0)])-tiny*math.sqrt(.5))<1e-21
    print("PASS 5 known-answer controls, including sub-nanometre scale; non-coplanar predicate only")
