import proj4 from 'proj4'
const LOCAL='+proj=aeqd +lat_0=45 +lon_0=126 +datum=WGS84 +units=m'
export function lngLat(point){return proj4(LOCAL,'EPSG:4326',point.slice(0,2))}
export function geographicGeometry(geometry){
  function convert(value){return typeof value[0]==='number'?lngLat(value):value.map(convert)}
  return {...geometry,coordinates:convert(geometry.coordinates)}
}
export function localGeometry(geometry){
  function convert(value){return typeof value[0]==='number'?proj4('EPSG:4326',LOCAL,value):value.map(convert)}
  return {...geometry,coordinates:convert(geometry.coordinates)}
}
export function collection(features=[]){return {type:'FeatureCollection',features}}
export function feature(geometry,properties={}){return {type:'Feature',geometry,properties}}
export function geographicGeoJson(node){
  if(!node||typeof node!=='object')return node
  if(node.type==='FeatureCollection')return {...node,features:(node.features||[]).map(geographicGeoJson)}
  if(node.type==='Feature')return {...node,geometry:geographicGeoJson(node.geometry)}
  if(node.type==='GeometryCollection')return {...node,geometries:(node.geometries||[]).map(geographicGeoJson)}
  if(Array.isArray(node.coordinates))return geographicGeometry(node)
  return node
}
