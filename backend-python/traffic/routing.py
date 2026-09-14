"""Boundary constrained horizontal paths. Weather columns cannot be overflown."""
import heapq
import math
from shapely.geometry import LineString, Point
from shapely.prepared import prep


def route(start,end,allowed,obstacles=None):
    start,end=tuple(start),tuple(end)
    prepared=prep(allowed)
    blocked=prep(obstacles) if obstacles is not None else None
    def valid(a,b):
        segment=LineString([a,b])
        return prepared.covers(segment) and (blocked is None or not blocked.intersects(segment))
    if not allowed.covers(Point(start)) or not allowed.covers(Point(end)): return None
    if obstacles is not None and (obstacles.covers(Point(start)) or obstacles.covers(Point(end))): return None
    if valid(start,end): return [list(start),list(end)]
    distance=math.dist(start,end)
    # Route-local grid; bounded work and progressively wider detours.
    step=max(800,min(6000,distance/25))
    margin=max(12000,min(70000,distance*.4))
    minx=min(start[0],end[0])-margin; miny=min(start[1],end[1])-margin
    nx=math.ceil((abs(start[0]-end[0])+2*margin)/step)
    ny=math.ceil((abs(start[1]-end[1])+2*margin)/step)
    def xy(node): return (minx+node[0]*step,miny+node[1]*step)
    source=(round((start[0]-minx)/step),round((start[1]-miny)/step))
    queue=[]; costs={}; previous={}
    for dx in range(-2,3):
        for dy in range(-2,3):
            n=(source[0]+dx,source[1]+dy)
            if valid(start,xy(n)):
                costs[n]=math.dist(start,xy(n)); previous[n]=None
                heapq.heappush(queue,(costs[n]+math.dist(xy(n),end),costs[n],n))
    checks=0
    while queue and checks<12000:
        _,cost,n=heapq.heappop(queue)
        if cost>costs[n]+1e-8: continue
        checks+=1; p=xy(n)
        if math.dist(p,end)<step*3 and valid(p,end):
            path=[list(end)]
            while n is not None:
                path.append(list(xy(n))); n=previous[n]
            path.append(list(start)); path.reverse()
            simplified=[path[0]]; i=0
            while i<len(path)-1:
                j=len(path)-1
                while j>i+1 and not valid(path[i],path[j]): j-=1
                simplified.append(path[j]); i=j
            return simplified
        for dx,dy in ((1,0),(-1,0),(0,1),(0,-1),(1,1),(1,-1),(-1,1),(-1,-1)):
            nxt=(n[0]+dx,n[1]+dy)
            if not (0<=nxt[0]<=nx and 0<=nxt[1]<=ny): continue
            new=cost+step*math.hypot(dx,dy)
            if new>=costs.get(nxt,float('inf')): continue
            if not valid(p,xy(nxt)): continue
            costs[nxt]=new; previous[nxt]=n
            heapq.heappush(queue,(new+math.dist(xy(nxt),end),new,nxt))
    return None
