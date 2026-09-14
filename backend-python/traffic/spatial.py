"""Continuous piecewise-linear 4D separation in metres and simulation minutes."""
import math

HORIZONTAL_M=250.0
VERTICAL_M=60.0


def position(points, minute):
    if minute<=points[0][3]: return points[0][:3]
    for a,b in zip(points,points[1:]):
        if minute<=b[3]:
            f=(minute-a[3])/(b[3]-a[3])
            return [a[k]+f*(b[k]-a[k]) for k in range(3)]
    return points[-1][:3]


def conflict(a,b,horizontal=HORIZONTAL_M,vertical=VERTICAL_M):
    """Solve the simultaneous horizontal quadratic and vertical interval exactly.

    Evaluates intervals, not sparse samples: brief crossings cannot slip between ticks.
    Endpoint touching of separation boundaries is conservatively treated as conflict.
    """
    for p,q in zip(a,a[1:]):
        for r,s in zip(b,b[1:]):
            lo=max(p[3],r[3]); hi=min(q[3],s[3])
            if hi<lo: continue
            va=[(q[k]-p[k])/(q[3]-p[3]) for k in range(3)]
            vb=[(s[k]-r[k])/(s[3]-r[3]) for k in range(3)]
            delta=[p[k]+va[k]*(lo-p[3])-r[k]-vb[k]*(lo-r[3]) for k in range(3)]
            velocity=[va[k]-vb[k] for k in range(3)]
            left,right=0.0,hi-lo
            if abs(velocity[2])<1e-10:
                if abs(delta[2])>vertical: continue
            else:
                z=sorted(((-vertical-delta[2])/velocity[2],(vertical-delta[2])/velocity[2]))
                left=max(left,z[0]); right=min(right,z[1])
            if left>right: continue
            vv=velocity[0]**2+velocity[1]**2
            t=left if vv<1e-10 else max(left,min(right,-(delta[0]*velocity[0]+delta[1]*velocity[1])/vv))
            if (delta[0]+velocity[0]*t)**2+(delta[1]+velocity[1]*t)**2<=horizontal**2:
                return True
    return False


def trajectory(path,departure,speed_kmh,altitude,raised=False,crossings=None):
    """Vertical takeoff/landing and finite-rate crossing ramps; endpoint heights are zero."""
    distances=[0.0]
    for a,b in zip(path,path[1:]): distances.append(distances[-1]+math.dist(a,b))
    total=distances[-1]
    marks=set(distances)
    ramps=[]
    if crossings:
        width=1800 if speed_kmh>100 else 550
        for centre in crossings:
            # Keep takeoff/landing ramps explicit and do not move either endpoint.
            half=min(width,centre*.8,(total-centre)*.8)
            if half>10:
                ramps.append((centre,half));marks.update((centre-half,centre-half*.25,centre+half*.25,centre+half))
    elif raised:
        marks.update(total*f for f in (.25,.4,.6,.75))
    result=[[path[0][0],path[0][1],0.0,departure]]
    t=departure+altitude/180.0  # 3 m/s takeoff, not instantaneous vertical jumps.
    result.append([path[0][0],path[0][1],altitude,t])
    for d in sorted(marks)[1:]:
        idx=next(i for i in range(1,len(distances)) if distances[i]>=d-1e-6)
        f=(d-distances[idx-1])/(distances[idx]-distances[idx-1])
        xy=[path[idx-1][k]+f*(path[idx][k]-path[idx-1][k]) for k in range(2)]
        if ramps:
            lift=100*max(max(0,min(1,(half-abs(d-centre))/(half*.75))) for centre,half in ramps)
        else:
            lift=0 if not raised else 100*max(0,min(1,(d/total-.25)/.15,(.75-d/total)/.15))
        prev=result[-1]; z=altitude+lift
        t+=max(math.dist(prev[:2],xy)/(speed_kmh*1000/60),abs(z-prev[2])/180.0)
        result.append([*xy,z,t])
    result.append([*path[-1],0.0,t+result[-1][2]/180.0])
    return result
