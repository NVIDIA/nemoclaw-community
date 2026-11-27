// SPDX-License-Identifier: Apache-2.0

// Stable scenario IDs own saved work; this catalog only lays out their spaces.
// Equal entrances branch off a shared concourse. Add the next pair alongside.
const scenarioFloors=scenarioDefinitions.map((definition,index)=>{
  const x=26+Math.floor(index/2)*25,z=scenarioDefinitions.length===1?0:(index%2?11:-11),group=missionShell.clone(true);
  group.position.set(x,0,z);group.userData.scenario=definition.id;
  const materials=new Map(),titles=[];
  group.traverse(node=>{
    if(node.material){
      if(!materials.has(node.material))materials.set(node.material,node.material.clone());
      node.material=materials.get(node.material);
    }
    if(node.userData.scenarioFloor)node.material=mat(definition.floor);
    if(node.userData.scenarioAccent)node.material=mat(definition.accent,true);
    if(node.userData.scenarioTitle)titles.push(node);
  });
  titles.forEach(node=>node.removeFromParent());
  displayTitle(group,definition.title,-.6,4,-7.06,5.1,.48);
  for(const role of definition.residents){
    const rig=createCharacter(avatarDefaults[role]);rig.group.position.copy(originalHomes[role]);
    if(role===0)rig.group.scale.setScalar(1.12);
    group.add(rig.group);
  }
  scene.add(group);
  return {...definition,x,z,group,number:definition.number||('03-'+(index+1)),width:21.6,depth:15};
});
let activeScenario='',scenarioMoved=false,scenarioGallery=false,scenarioStatus=[],scenarioPending=false;
function setScenario(id){
  const destination=scenarioFloors.find(item=>item.id===id);
  if(!destination||activeScenario===id)return;
  if(activeScenario){clearMeeting();meetingId='';meetingFurniture.visible=false;}
  activeScenario=id;scenarioMoved=true;crewPresenceInitialized=false;exchangeTeamKey='';
  missionRoom.position.set(destination.x,0,destination.z);
  missionRoom.userData.scenario=id;
  missionFloor.material=mat(destination.floor);missionAccent.material=mat(destination.accent,true);
  const title=displayTitle(missionRoom,destination.title,-.6,4,-7.06,5.1,.48);
  missionTitle.material.map?.dispose();missionTitle.material.dispose();
  missionTitle.material=title.material;title.removeFromParent();title.geometry.dispose();
  Object.assign(studioRooms.mission,{x:destination.x,z:destination.z,title:destination.title});
  scenarioFloors.forEach(item=>item.group.visible=item.id!==id);
  scene.updateMatrixWorld(true);refreshNavigation();
}
function setScenarioStatus(rows,pending=false){
  scenarioStatus=rows;scenarioPending=pending;refreshScenarioLabels();
}
function scenarioPath(id){
  const item=scenarioFloors.find(s=>s.id===id),spine=item.x-12.2;
  const points=[[8,0],[13.8,0]];
  if(spine>14)points.push([spine,0]);
  if(item.z)points.push([spine,item.z]);
  points.push([item.x-10.6,item.z]);
  return points;
}
function campusBounds(scenariosOnly=false){
  const rooms=[...scenarioFloors];
  if(!scenariosOnly)rooms.push({x:0,z:0,width:18,depth:12.6},{x:0,z:18,width:12,depth:8.5});
  return {left:Math.min(...rooms.map(r=>r.x-r.width/2)),right:Math.max(...rooms.map(r=>r.x+r.width/2)),
    back:Math.min(...rooms.map(r=>r.z-r.depth/2)),front:Math.max(...rooms.map(r=>r.z+r.depth/2))+3};
}
function campusFrame(scenariosOnly=false){
  const bounds=campusBounds(scenariosOnly),center=new THREE.Vector3((bounds.left+bounds.right)/2,0,(bounds.back+bounds.front)/2);
  const a=.43,e=.64,right=new THREE.Vector3(Math.cos(a),0,-Math.sin(a));
  const up=new THREE.Vector3(-Math.sin(a)*Math.sin(e),Math.cos(e),-Math.cos(a)*Math.sin(e));
  let halfWidth=0,halfHeight=0;
  for(const x of [bounds.left,bounds.right])for(const z of [bounds.back,bounds.front])for(const y of [-.5,5.5]){
    const point=new THREE.Vector3(x,y,z).sub(center);
    halfWidth=Math.max(halfWidth,Math.abs(point.dot(right)));halfHeight=Math.max(halfHeight,Math.abs(point.dot(up)));
  }
  const aspect=viewport.clientWidth/Math.max(1,viewport.clientHeight);
  // Bring the whole studio closer on wide screens. Keep horizontal clearance on narrow ones.
  const heightFit=halfHeight/.79, widthFit=halfWidth/(aspect*.86);
  return {focus:center,height:Math.max(scenariosOnly?heightFit:heightFit/1.33,widthFit)};
}
