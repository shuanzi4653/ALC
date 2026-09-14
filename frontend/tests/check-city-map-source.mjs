// Opt-in online coverage check, separate from offline unit tests. One tile per city.
import {VectorTile} from '@mapbox/vector-tile'
import {PbfReader} from 'pbf'
import {writeFile,mkdir} from 'node:fs/promises'
const get=async url=>{const r=await fetch(url,{signal:AbortSignal.timeout(25000)});if(!r.ok)throw new Error(`HTTP ${r.status}`);return r}
const network=await (await get('http://127.0.0.1:8085/api/traffic/network')).json()
const metadata=await (await get('https://tiles.openfreemap.org/planet')).json()
const results=[]
for(const city of network.cities){
  const [lon,lat]=city.coordinate,z=14,x=Math.floor((lon+180)/360*2**z),y=Math.floor((1-Math.asinh(Math.tan(lat*Math.PI/180))/Math.PI)/2*2**z)
  try{
    const response=await get(metadata.tiles[0].replace('{z}',z).replace('{x}',x).replace('{y}',y))
    const bytes=new Uint8Array(await response.arrayBuffer()),tile=new VectorTile(new PbfReader(bytes))
    results.push({city:city.name,id:city.id,z,x,y,bytes:bytes.length,roads:tile.layers.transportation?.length||0,buildings:tile.layers.building?.length||0,status:'OK'})
  }catch(e){results.push({city:city.name,id:city.id,status:'ERROR',message:e.message})}
}
await mkdir('../docs/evaluation-v1.2',{recursive:true})
await writeFile('../docs/evaluation-v1.2/city-map-coverage.json',JSON.stringify({checkedAt:new Date().toISOString(),source:metadata.tiles[0],scope:'One z14 centre tile per city; counts are not city-wide building totals.',results},null,2))
console.log(JSON.stringify({cities:results.length,available:results.filter(r=>r.status==='OK').length,withBuildings:results.filter(r=>r.buildings>0).length,errors:results.filter(r=>r.status==='ERROR')}))
if(results.some(r=>r.status==='ERROR'))process.exitCode=1
