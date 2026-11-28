// SPDX-License-Identifier: Apache-2.0

// Shared rigs keep a saved agent recognizable in the workshop, lounge and crew.
const avatarColors={green:0x76b900,cyan:0x55bfff,amber:0xf4b34f,coral:0xff8873,violet:0xb49aff,ice:0xcbddea};
const characterPalettes=Object.fromEntries(Object.entries(/* AVATAR_PALETTES */).map(([id,p])=>[id,Object.fromEntries(['base','light','dark','accent'].map(key=>[key,Number(p[key].replace('#','0x'))]))]));
const avatarDefaults=[{body:'classic',color:'green',accessory:'antenna'},{body:'round',color:'cyan',accessory:'headset'},{body:'rover',color:'amber',accessory:'cap'},{body:'round',color:'coral',accessory:'antenna'},{body:'classic',color:'violet',accessory:'glasses'},{body:'claw',color:'ice',accessory:'headset'},{body:'classic',color:'cyan',accessory:'glasses'},{body:'round',color:'violet',accessory:'cap'},{body:'rover',color:'cyan',accessory:'glasses'},{body:'classic',color:'green',accessory:'headset'}];
const robotShape=new THREE.Shape();robotShape.moveTo(-.29,-.2);robotShape.lineTo(.29,-.2);robotShape.lineTo(.29,.2);robotShape.lineTo(-.29,.2);robotShape.closePath();
const robotHeadGeometry=new THREE.ExtrudeGeometry(robotShape,{depth:.38,bevelEnabled:true,bevelThickness:.07,bevelSize:.065,bevelSegments:2,steps:1});robotHeadGeometry.translate(0,0,-.19);
const robotSphereGeometry=new THREE.SphereGeometry(1,24,16),robotLensGeometry=new THREE.TorusGeometry(.1,.019,6,20);
// Shared rounded toy parts avoid sharp slabs without adding per-frame work.
const toyShape=new THREE.Shape();toyShape.moveTo(-.4,-.4);toyShape.lineTo(.4,-.4);toyShape.lineTo(.4,.4);toyShape.lineTo(-.4,.4);toyShape.closePath();
const toyBoxGeometry=new THREE.ExtrudeGeometry(toyShape,{depth:.8,bevelEnabled:true,bevelThickness:.1,bevelSize:.1,bevelSegments:3,steps:1});toyBoxGeometry.translate(0,0,-.4);
// These parts live as long as the scene, across preview and character replacements.
const sharedGeometries=new Set([boxGeometry,robotHeadGeometry,robotSphereGeometry,robotLensGeometry,toyBoxGeometry]);
function toyBox(parent,x,y,z,w,h,d,tint,glow=false){const mesh=new THREE.Mesh(toyBoxGeometry,mat(tint,glow));mesh.position.set(x,y,z);mesh.scale.set(w,h,d);mesh.castShadow=true;mesh.receiveShadow=true;parent.add(mesh);return mesh;}
function characterCurve(parent,points,radius,tint){const curve=new THREE.CatmullRomCurve3(points.map(p=>new THREE.Vector3(...p)));const mesh=new THREE.Mesh(new THREE.TubeGeometry(curve,12,radius,6,false),mat(tint));parent.add(mesh);return mesh;}
function createCharacter(avatar=avatarDefaults[0]){
  const appearance={...avatarDefaults[0],...avatar},palette=characterPalettes[appearance.color],color=palette?.accent??avatarColors[appearance.color]??avatarColors.green;
  const group=new THREE.Group(),body=new THREE.Group();group.add(body);
  if(appearance.body==='fox')appearance.body='claw';
  if(appearance.body==='operative')return createOperative(appearance,color,group,body,palette);
  if(appearance.body==='claw')return createClaw(appearance,color,group,body,palette);
  if(['fox-companion','bunny','panda'].includes(appearance.body))return createAnimal(appearance,color,group,body,palette);
  if(['cat','crab'].includes(appearance.body))return createCompanion(appearance,color,group,body,palette);
  const arms=[],legs=[];
  const round=appearance.body==='round';
  if(round){const torso=new THREE.Mesh(robotSphereGeometry,mat(palette?.light??0xcad4df));torso.position.y=.55;torso.scale.set(.24,.25,.19);torso.castShadow=true;body.add(torso);}
  else toyBox(body,0,.55,0,appearance.body==='rover'?.55:.4,.38,.3,palette?.light??0xcad4df);
  let head;
  if(appearance.body==='round'){
    head=new THREE.Mesh(robotSphereGeometry,mat(palette?.base??0xe6edf5));head.scale.set(.41,.34,.32);
  }else{head=new THREE.Mesh(robotHeadGeometry,mat(palette?.base??0xe6edf5));if(appearance.body==='rover')head.scale.set(1.18,.78,1.02);}
  head.position.y=.99;head.castShadow=true;body.add(head);
  let face;
  if(round){face=new THREE.Mesh(robotSphereGeometry,mat(0x111c29));face.scale.set(.285,.15,.055);face.position.set(0,.99,.29);body.add(face);}
  else face=toyBox(body,0,.99,.26,appearance.body==='rover'?.61:.49,.25,.03,0x111c29);
  const eyeZ=round?.349:face.position.z+.026;
  for(const side of [-1,1]){
    const eye=new THREE.Mesh(robotSphereGeometry,mat(color,true));eye.position.set(side*.115,1.015,eyeZ);eye.scale.set(.030,.044,.012);body.add(eye);
    const arm=new THREE.Group();arm.position.set(side*(appearance.body==='rover'?.38:.29),.7,0);toyBox(arm,0,-.15,0,.13,.28,.15,palette?.base??0xabbccc);body.add(arm);arms.push(arm);
    const leg=new THREE.Group();leg.position.set(side*.12,.34,0);body.add(leg);legs.push(leg);
    if(appearance.body!=='rover'){toyBox(leg,0,-.12,0,.15,.24,.16,palette?.light??0x788c9f);toyBox(leg,0,-.25,.045,.19,.10,.25,palette?.dark??0x283b50);}
    else{box(body,side*.28,.17,0,.2,.22,.57,0x172330);for(const z of [-.18,.18]){const wheel=cylinder(body,side*.39,.17,z,.12,.05,0x526777,12);wheel.rotation.z=Math.PI/2;}box(body,side*.4,.28,0,.02,.04,.4,color);}
  }
  characterCurve(body,[[-.045,.951,eyeZ],[0,.938,eyeZ+.004],[.045,.951,eyeZ]],.007,color);
  toyBox(body,0,.54,round?.19:.171,.20,.075,.025,color,true);
  equipCharacter(body,face,appearance,color,arms);
  return {group,body,arms,legs,appearance,color};
}

function equipCharacter(body,face,appearance,color,arms=[]){
  if(appearance.protection==='openshell'){
    const shield=new THREE.Group();shield.name='openshell-shield';shield.position.set(.12,.57,.48);shield.rotation.y=-.12;body.add(shield);
    const shape=new THREE.Shape();shape.moveTo(0,.40);shape.lineTo(.32,.25);shape.lineTo(.27,-.15);shape.quadraticCurveTo(.18,-.32,0,-.41);shape.quadraticCurveTo(-.18,-.32,-.27,-.15);shape.lineTo(-.32,.25);shape.closePath();
    const plate=new THREE.Mesh(new THREE.ExtrudeGeometry(shape,{depth:.045,bevelEnabled:true,bevelThickness:.012,bevelSize:.018,bevelSegments:1,steps:1}),mat(0x76b900));plate.castShadow=true;shield.add(plate);
    const rim=new THREE.LineLoop(new THREE.BufferGeometry().setFromPoints(shape.getPoints(24).map(p=>new THREE.Vector3(p.x,p.y,.065))),new THREE.LineBasicMaterial({color:0xc5ef91}));shield.add(rim);
    const shackle=new THREE.Mesh(new THREE.TorusGeometry(.085,.015,6,20,Math.PI),mat(0xf3ffe6));shackle.position.set(0,.09,.085);shield.add(shackle);
    for(const x of [-.085,.085])box(shield,x,.052,.085,.03,.075,.025,0xf3ffe6);
    box(shield,0,-.035,.085,.23,.17,.035,0xf3ffe6);box(shield,0,-.03,.109,.025,.06,.012,0x416b0b);
  }

  equipAccessory(body,face,appearance,color,arms);
}

// Accessories use each character's head/chest anchors, rather than robot coordinates.
function equipAccessory(body,face,appearance,color,arms){
  const kind=appearance.body,id=appearance.accessory;
  if(!id||id==='none')return;
  const rig={
    classic:{top:1.27,eye:1.005,half:.34,neck:.78,chest:.62,back:.57},
    round:{top:1.27,eye:1.005,half:.4,neck:.78,chest:.62,back:.57},
    rover:{top:1.23,eye:1.005,half:.38,neck:.78,chest:.62,back:.57},
    operative:{top:1.41,eye:1.16,half:.27,neck:.85,chest:.69,back:.67},
    cat:{top:1.34,eye:1.07,half:.35,neck:.79,chest:.68,back:.58,flower:[.26,1.43,.10]},
    'fox-companion':{top:1.32,eye:1.15,half:.34,neck:.78,chest:.67,back:.59,flower:[.25,1.43,.08]},
    bunny:{top:1.32,eye:1.07,half:.33,neck:.77,chest:.66,back:.58,flower:[.2,1.4,.10]},
    panda:{top:1.35,eye:1.08,half:.36,neck:.79,chest:.67,back:.58},
    claw:{top:1.30,eye:1.28,half:.32,neck:.77,chest:.72,back:.65},
    crab:{top:.94,eye:1.11,half:.44,neck:.66,chest:.61,back:.63,flower:[.34,.85,.16]}
  }[kind]||{top:1.27,eye:1.005,half:.34,neck:.78,chest:.62,back:.57};
  const outfit=new THREE.Group();outfit.name='avatar-accessory-'+id;body.add(outfit);
  const palette=characterPalettes[appearance.color];
  // Keep hats/bags close to the coat; small fabric pieces can use its muted accent.
  const cream=palette?.light??0xf3ead7,ink=palette?.dark??0x233547;
  const fabric=palette?new THREE.Color(palette.accent).lerp(new THREE.Color(palette.dark),.2).getHex():color;
  color=palette?(['scarf','bowtie','flag'].includes(id)?kind==='fox-companion'?palette.dark:fabric:palette.base):color;
  if(id==='cap'&&palette&&kind!=='operative')color=palette.dark;
  const front=kind==='operative'?.18:kind==='crab'?.29:.29;
  const oval=(parent,x,y,z,sx,sy,sz,tint)=>{const mesh=new THREE.Mesh(robotSphereGeometry,mat(tint));mesh.position.set(x,y,z);mesh.scale.set(sx,sy,sz);mesh.castShadow=true;parent.add(mesh);return mesh;};
  if(id==='headset'){
    if(kind==='round'){
      const band=new THREE.Mesh(new THREE.TorusGeometry(.43,.028,8,24,Math.PI),mat(ink));band.scale.y=.8;band.position.set(0,rig.eye,-.035);outfit.add(band);
    }else{
      characterCurve(outfit,[[-rig.half-.025,rig.eye,-.035],[-rig.half-.02,rig.top-.035,-.035],[0,rig.top+.035,-.035],[rig.half+.02,rig.top-.035,-.035],[rig.half+.025,rig.eye,-.035]],.027,ink);
    }
    for(const side of [-1,1]){toyBox(outfit,side*(rig.half+.015),rig.eye,-.015,.075,.21,.20,ink);toyBox(outfit,side*(rig.half+.055),rig.eye,-.015,.065,.19,.18,color);}
    box(outfit,rig.half+.03,rig.eye-.13,.15,.04,.04,.25,ink);
  }else if(id==='glasses'){
    const glasses=new THREE.Group(),fox=kind==='fox-companion',panda=kind==='panda';
    glasses.position.set(0,rig.eye+(fox?.025:panda?.02:0),fox?.31:panda?.32:kind==='round'?.385:face.position.z+.055);
    if(fox||panda)glasses.rotation.x=fox?-.32:-.20;
    outfit.add(glasses);
    const frame=kind==='panda'&&palette?new THREE.Color(ink).lerp(new THREE.Color(palette.accent),.5).getHex():ink;
    for(const side of [-1,1]){const lens=new THREE.Mesh(robotLensGeometry,mat(frame));lens.position.set(side*.13,0,0);if(fox||panda)lens.scale.setScalar(fox?.8:.88);glasses.add(lens);}
    box(glasses,0,0,0,fox?.10:.065,.018,.018,frame);
  }else if(id==='cap'){
    const radius=kind==='round'?.375:rig.half+.015,depth=kind==='round'||kind==='crab'?.30:.27;
    const base=kind==='round'?1.15:kind==='operative'?1.27:kind==='classic'?1.26:rig.top-.035;
    const crown=new THREE.Mesh(new THREE.SphereGeometry(1,24,12,0,Math.PI*2,0,Math.PI/2),mat(color));
    crown.scale.set(radius,.22,depth);crown.position.set(0,base,-.02);crown.castShadow=true;outfit.add(crown);
    // A thin curved visor projects forward; it does not wrap around the head.
    const positions=[],indices=[],segments=24;
    for(let i=0;i<=segments;i++){
      const angle=-Math.PI/2+i*Math.PI/segments,x=Math.sin(angle),forward=Math.cos(angle);
      positions.push(x*radius*.83,.012,forward*depth*.8);
      positions.push(x*radius*.96,.005+.015*forward,forward*(depth+.12));
      if(i<segments){const n=i*2;indices.push(n,n+1,n+2,n+1,n+3,n+2);}
    }
    const visorGeometry=new THREE.BufferGeometry();visorGeometry.setAttribute('position',new THREE.Float32BufferAttribute(positions,3));visorGeometry.setIndex(indices);visorGeometry.computeVertexNormals();
    const visorMaterial=mat(color).clone();visorMaterial.side=THREE.DoubleSide;
    const visor=new THREE.Mesh(visorGeometry,visorMaterial);visor.position.set(0,base,-.02);visor.castShadow=true;outfit.add(visor);
    oval(outfit,0,base+.223,-.02,.027,.018,.027,color);
    oval(outfit,0,base+.085,depth*.91-.02,.032,.033,.010,cream).castShadow=false;
  }else if(id==='antenna'){
    cylinder(outfit,0,rig.top+.13,-.04,.023,.23,0x72859a,8);
    oval(outfit,0,rig.top+.27,-.04,.06,.06,.06,palette?.accent??color);
  }else if(id==='pirate'){
    const outline=new THREE.Shape();outline.moveTo(-.42,-.06);outline.quadraticCurveTo(-.49,.03,-.38,.12);outline.quadraticCurveTo(-.17,.05,-.15,.24);outline.quadraticCurveTo(0,.30,.15,.24);outline.quadraticCurveTo(.17,.05,.38,.12);outline.quadraticCurveTo(.49,.03,.42,-.06);outline.quadraticCurveTo(0,-.15,-.42,-.06);outline.closePath();
    const hat=new THREE.Mesh(new THREE.ExtrudeGeometry(outline,{depth:.08,bevelEnabled:true,bevelThickness:.012,bevelSize:.015,bevelSegments:1,steps:1}),mat(palette?.dark??0x101821));
    // Eyestalks remain in front of the hat on crustaceans.
    hat.position.set(0,rig.top,kind==='claw'||kind==='crab'?-.12:.05);hat.castShadow=true;outfit.add(hat);
    const rim=new THREE.LineLoop(new THREE.BufferGeometry().setFromPoints(outline.getPoints(24).map(p=>new THREE.Vector3(p.x,p.y,.095))),new THREE.LineBasicMaterial({color:cream}));hat.add(rim);
    oval(hat,0,.055,.10,.06,.065,.012,cream);
    for(const side of [-1,1]){oval(hat,side*.023,.06,.115,.012,.015,.008,ink);const bone=box(hat,0,-.055,.11,.21,.02,.015,cream);bone.rotation.z=side*.5;}
  }else if(id==='backpack'){
    toyBox(outfit,0,rig.back,-.34,.39,.39,.20,color);
    toyBox(outfit,0,rig.back-.055,-.455,.29,.15,.04,ink);
    const strapX=kind==='crab'?.35:['classic','rover','operative'].includes(kind)?.17:.21,strapZ=kind==='operative'?.18:kind==='classic'?.17:.22;
    for(const side of [-1,1])characterCurve(outfit,[[side*strapX,rig.back-.12,-.22],[side*strapX,rig.back+.21,-.18],[side*strapX,rig.back+.23,.04],[side*strapX,rig.back+.08,strapZ],[side*strapX,rig.back-.12,strapZ]],.018,palette?.dark??cream);
    characterCurve(outfit,[[-.065,rig.back+.19,-.32],[-.055,rig.back+.26,-.32],[.055,rig.back+.26,-.32],[.065,rig.back+.19,-.32]],.015,ink);
  }else if(id==='scarf'){
    const wrap=new THREE.Mesh(new THREE.TorusGeometry(.25,.065,8,24),mat(color));wrap.rotation.x=Math.PI/2;wrap.position.set(0,rig.neck,0);outfit.add(wrap);
    const end=toyBox(outfit,.11,rig.neck-.13,.28,.12,.30,.055,color);end.rotation.z=-.18;
    box(outfit,.13,rig.neck-.24,.315,.105,.035,.008,cream);
  }else if(id==='bowtie'){
    for(const side of [-1,1]){const wing=oval(outfit,side*.075,rig.chest+.05,front+.035,.085,.057,.032,color);wing.rotation.z=side*.20;}
    oval(outfit,0,rig.chest+.05,front+.055,.035,.037,.030,color);
  }else if(id==='flower'){
    const [x,y,z]=rig.flower||[.27,rig.top,.08];
    for(let i=0;i<5;i++){const a=i*Math.PI*2/5;oval(outfit,x+Math.cos(a)*.075,y+Math.sin(a)*.075,z,.055,.06,.023,palette?.light??0xffa5b7);}
    oval(outfit,x,y,z+.025,.044,.044,.025,palette?.accent??0xf6cb56);
  }else if(id==='flag'){
    cylinder(outfit,-.28,rig.back+.27,-.27,.018,.83,cream,8);
    const flag=new THREE.Shape();flag.moveTo(0,0);flag.lineTo(.31,-.07);flag.lineTo(0,-.18);flag.closePath();
    const mesh=new THREE.Mesh(new THREE.ShapeGeometry(flag),mat(color));mesh.material=mesh.material.clone();mesh.material.side=THREE.DoubleSide;mesh.position.set(-.28,rig.back+.66,-.27);outfit.add(mesh);
  }else if(id==='earpiece'){
    oval(outfit,.28,1.15,0,.045,.08,.065,ink);
    box(outfit,.29,1.02,.11,.022,.025,.22,ink);
    oval(outfit,.29,1.16,.065,.018,.025,.012,color);
  }else if(id==='watch'){
    const wrist=new THREE.Group();wrist.name='avatar-watch';(arms[1]||outfit).add(wrist);wrist.position.set(0,-.31,.07);
    box(wrist,0,0,0,.16,.08,.17,ink);box(wrist,0,0,.095,.09,.065,.02,color);
  }else if(id==='briefcase'){
    const caseGroup=new THREE.Group();caseGroup.name='avatar-briefcase';(arms[1]||outfit).add(caseGroup);caseGroup.position.set(.025,-.60,.055);
    box(caseGroup,0,0,0,.33,.24,.13,ink);box(caseGroup,0,.025,.074,.055,.035,.015,color);
    for(const side of [-1,1])box(caseGroup,side*.07,.16,0,.025,.09,.035,cream);
    box(caseGroup,0,.20,0,.16,.025,.035,cream);
  }else if(id==='carrot'||id==='bamboo'){
    const snack=new THREE.Group();snack.name='avatar-snack';(arms[1]||outfit).add(snack);snack.position.set(.025,-.23,.15);snack.rotation.z=-.25;
    if(id==='carrot'){
      const carrot=new THREE.Mesh(new THREE.ConeGeometry(.065,.27,12),mat(0xf59a3f));carrot.rotation.z=Math.PI;snack.add(carrot);
      for(const side of [-1,0,1]){const leaf=oval(snack,side*.03,.18,0,.023,.10,.025,0x70a948);leaf.rotation.z=-side*.35;}
    }else{
      cylinder(snack,0,.12,0,.035,.52,0x7faa54,10);
      for(const y of [-.1,.05,.2,.35])cylinder(snack,0,y,0,.043,.018,0xb7d485,10);
      for(const side of [-1,1]){const leaf=oval(snack,side*.075,.31,0,.10,.025,.035,0x65974c);leaf.rotation.z=side*.4;}
    }
  }
}

// Original digital operative: dark suit and permanent sunglasses, with
// articulated pincers instead of human hands. The cat renderer remains below
// so previously saved cat agents continue to load.
function createOperative(appearance,color,group,body,palette){
  const arms=[],legs=[];
  function oval(parent,x,y,z,sx,sy,sz,tint){const mesh=new THREE.Mesh(robotSphereGeometry,mat(tint));mesh.position.set(x,y,z);mesh.scale.set(sx,sy,sz);mesh.castShadow=true;parent.add(mesh);return mesh;}
  toyBox(body,0,.67,0,.46,.55,.27,palette?.base??0x121820);
  box(body,0,.68,.151,.16,.43,.025,palette?.light??0xf1f3f4);
  const lapel=new THREE.Shape();lapel.moveTo(-.17,.2);lapel.lineTo(0,-.02);lapel.lineTo(.17,.2);lapel.lineTo(.11,-.18);lapel.lineTo(-.11,-.18);lapel.closePath();
  const jacket=new THREE.Mesh(new THREE.ExtrudeGeometry(lapel,{depth:.025,bevelEnabled:false}),mat(palette?.dark??0x080b0f));jacket.position.set(0,.72,.165);body.add(jacket);
  const tie=box(body,0,.70,.205,.045,.30,.025,0x050607);tie.rotation.z=0;
  oval(body,0,1.12,0,.27,.30,.24,0xd4ad92);
  const hair=new THREE.Mesh(new THREE.SphereGeometry(1,24,12,0,Math.PI*2,0,1.16),mat(0x171b1f));hair.scale.set(.278,.31,.248);hair.position.set(0,1.12,0);hair.castShadow=true;body.add(hair);
  for(const side of [-1,1]){oval(body,side*.258,1.11,0,.038,.06,.05,0xd4ad92);oval(body,side*.242,1.22,-.035,.025,.085,.105,0x171b1f);}
  // A single dark visor reads as sunglasses from every camera distance.
  for(const side of [-1,1])box(body,side*.115,1.16,.226,.205,.095,.035,0x06090c);
  box(body,0,1.16,.229,.055,.025,.038,0x06090c);
  characterCurve(body,[[-.055,1.038,.235],[0,1.025,.241],[.045,1.038,.235]],.006,0x795b4d);
  for(const side of [-1,1]){
    const arm=new THREE.Group();arm.position.set(side*.34,.78,0);body.add(arm);arms.push(arm);
    toyBox(arm,0,-.16,0,.14,.38,.17,palette?.base??0x11171e);
    const wrist=oval(arm,0,-.39,.035,.09,.10,.09,palette?.light??color);
    wrist.rotation.z=side*.18;
    for(const tip of [-1,1]){
      const claw=oval(arm,side*tip*.065,-.48,.07,.065,.15,.06,palette?.light??color);
      claw.rotation.z=side*tip*.48;
    }
    const leg=new THREE.Group();leg.position.set(side*.13,.39,0);body.add(leg);legs.push(leg);
    box(leg,0,-.17,0,.18,.34,.20,palette?.base??0x0d1218);
    toyBox(leg,0,-.36,.07,.20,.09,.31,palette?.dark??0x080b0f);
  }
  equipCharacter(body,{position:{z:.22}},{...appearance,accessory:appearance.accessory==='glasses'?'none':appearance.accessory},color,arms);
  return {group,body,arms,legs,appearance,color};
}

function createCompanion(appearance,color,group,body,palette){
  const arms=[],legs=[],crab=appearance.body==='crab';
  const fur=palette?.base??color,light=palette?.light??0xe6edf5,dark=palette?.dark??color;
  function oval(parent,x,y,z,sx,sy,sz,tint){const mesh=new THREE.Mesh(robotSphereGeometry,mat(tint));mesh.position.set(x,y,z);mesh.scale.set(sx,sy,sz);mesh.castShadow=true;parent.add(mesh);return mesh;}
  oval(body,0,crab?.61:.57,0,crab?.49:.27,crab?.27:.36,.26,fur);
  if(crab&&palette)oval(body,0,.50,.23,.34,.12,.055,light);
  if(!crab){
    oval(body,0,1.02,.01,.37,.31,.3,fur);
    oval(body,0,.56,.225,.16,.23,.055,light);
    for(const side of [-1,1]){
      const ear=new THREE.Mesh(new THREE.ConeGeometry(.14,.32,4),mat(fur));ear.position.set(side*.245,1.34,0);ear.rotation.z=-side*.17;body.add(ear);
      const inner=new THREE.Mesh(new THREE.ConeGeometry(.082,.22,4),mat(0xd9a6a0));inner.position.set(side*.245,1.36,.07);inner.rotation.z=-side*.17;body.add(inner);
      oval(body,side*.105,.94,.286,.13,.085,.085,light);
    }
    oval(body,0,.98,.36,.042,.033,.035,0x172330);
    for(const side of [-1,1]){
      characterCurve(body,[[0,.958,.355],[side*.035,.935,.354],[side*.064,.943,.345]],.0055,0x4a4140);
      for(const offset of [-1,1])characterCurve(body,[[side*.19,.956+offset*.013,.341],[side*.26,.96+offset*.025,.319],[side*.33,.965+offset*.036,.285]],.0045,dark);
    }
    const tail=new THREE.Group();tail.position.set(0,.42,-.19);body.add(tail);
    const plume=oval(tail,.18,.2,-.26,.07,.32,.11,fur);plume.rotation.z=-.5;
    oval(tail,.32,.46,-.26,.065,.12,.085,light);
  }
  const face={position:{z:.30}};
  for(const side of [-1,1]){
    if(crab){cylinder(body,side*.16,.96,.15,.035,.3,dark,10);oval(body,side*.16,1.1,.15,.09,.1,.08,0xe6edf5);}
    oval(body,side*(crab?.16:.135),crab?1.11:1.07,crab?.224:.296,.036,.052,.025,0x101b29);
    oval(body,side*(crab?.16:.135)-.008,crab?1.13:1.085,crab?.244:.318,.008,.011,.006,0xffffff).castShadow=false;
    const arm=new THREE.Group();arm.position.set(side*(crab?.43:.25),crab?.72:.72,0);body.add(arm);arms.push(arm);
    if(crab){
      oval(arm,side*.14,.07,.05,.2,.075,.08,fur);
      for(const tip of [-1,1]){const claw=oval(arm,side*.30,.18,.06+tip*.09,.12,.18,.06,dark);claw.rotation.z=-side*.4;}
      for(let i=0;i<3;i++){
        const limb=new THREE.Group();limb.position.set(side*.28,.50,(i-1)*.17);body.add(limb);legs.push(limb);
        characterCurve(limb,[[0,0,0],[side*.19,-.06,.015],[side*.29,-.25,.04],[side*.33,-.43,.07]],.043,dark);
        oval(limb,side*.33,-.43,.07,.072,.045,.075,dark);
      }
    }else{
      oval(arm,side*.02,-.13,.01,.085,.20,.09,fur);oval(arm,side*.02,-.29,.045,.09,.07,.10,light);
      const leg=new THREE.Group();leg.position.set(side*.14,.28,0);body.add(leg);legs.push(leg);oval(leg,0,-.12,.065,.115,.14,.16,dark);
    }
  }
  if(crab)characterCurve(body,[[-.075,.645,.266],[0,.621,.278],[.075,.645,.266]],.008,0x4d3430);
  equipCharacter(body,face,appearance,color,arms);
  return {group,body,arms,legs,appearance,color};
}

// Upright lobster silhouette: oversized open pincers, segmented tail, no feline ears.
function createClaw(appearance,color,group,body,palette){
  const arms=[],legs=[];
  const shell=palette?.base??color;
  function oval(parent,x,y,z,sx,sy,sz,tint=shell){const mesh=new THREE.Mesh(robotSphereGeometry,mat(tint));mesh.position.set(x,y,z);mesh.scale.set(sx,sy,sz);mesh.castShadow=true;parent.add(mesh);return mesh;}
  oval(body,0,.66,0,.28,.39,.25);
  oval(body,0,1.01,.025,.33,.28,.27);
  for(let i=0;i<4;i++){
    oval(body,0,.47-i*.07,-.18-i*.09,.23-i*.025,.095,.15);
    box(body,0,.48-i*.07,.215,.35-i*.04,.025,.02,palette?.light??0xe6edf5);
  }
  for(const side of [-1,1]){
    const fan=oval(body,side*.11,.18,-.57,.16,.055,.17);fan.rotation.y=side*.45;
    cylinder(body,side*.13,1.20,.17,.029,.15,shell,8);
    oval(body,side*.13,1.28,.20,.074,.085,.065,0xe6edf5);
    oval(body,side*.13,1.28,.258,.032,.043,.02,0x111c29);
    oval(body,side*.13-.008,1.295,.277,.008,.011,.005,0xffffff).castShadow=false;
    const arm=new THREE.Group();arm.position.set(side*.29,.67,0);body.add(arm);arms.push(arm);
    const forearm=oval(arm,side*.14,.015,.10,.19,.08,.09);forearm.rotation.z=side*.35;
    const outline=new THREE.Shape();outline.moveTo(-.10,0);outline.quadraticCurveTo(-.31,.23,-.18,.48);outline.lineTo(-.05,.31);outline.lineTo(0,.20);outline.lineTo(.055,.32);outline.lineTo(.18,.48);outline.quadraticCurveTo(.31,.23,.10,0);outline.closePath();
    const pincer=new THREE.Mesh(new THREE.ExtrudeGeometry(outline,{depth:.14,bevelEnabled:true,bevelThickness:.025,bevelSize:.025,bevelSegments:2,steps:1}),mat(palette?.dark??color));
    pincer.position.set(side*.26,.04,.12);pincer.rotation.z=-side*.22;pincer.castShadow=true;arm.add(pincer);
    for(let i=0;i<2;i++){const leg=new THREE.Group();leg.position.set(side*.19,.34,-i*.15);body.add(leg);legs.push(leg);const foot=box(leg,side*.09,-.15,.06,.12,.26,.12,palette?.dark??0x526777);foot.rotation.z=side*.22;}
  }
  characterCurve(body,[[-.06,.93,.288],[0,.912,.294],[.06,.93,.288]],.008,0x29313b);
  equipCharacter(body,{position:{z:.28}},appearance,color,arms);
  return {group,body,arms,legs,appearance,color};
}

// Soft animal silhouettes share the same walking/seated rig as the robots.
function createAnimal(appearance,color,group,body,palette){
  const arms=[],legs=[],fox=appearance.body==='fox-companion',bunny=appearance.body==='bunny';
  const fur=palette?.base??(fox?0xe38e48:bunny?0xe8e2db:0xe5ebec),dark=palette?.dark??0x293644,cream=palette?.light??0xf7eee0;
  function oval(parent,x,y,z,sx,sy,sz,tint){const mesh=new THREE.Mesh(robotSphereGeometry,mat(tint));mesh.position.set(x,y,z);mesh.scale.set(sx,sy,sz);mesh.castShadow=true;parent.add(mesh);return mesh;}
  oval(body,0,.57,0,.29,.36,.25,fur);
  oval(body,0,.56,.22,.19,.25,.055,cream);
  oval(body,0,1.05,0,.36,.30,.29,fur);
  for(const side of [-1,1]){
    if(fox){
      const ear=new THREE.Mesh(new THREE.ConeGeometry(.14,.34,4),mat(fur));ear.position.set(side*.25,1.35,-.025);ear.rotation.z=-side*.16;body.add(ear);
      const inside=new THREE.Mesh(new THREE.ConeGeometry(.077,.20,4),mat(dark));inside.position.set(side*.25,1.38,.055);inside.rotation.z=-side*.16;body.add(inside);
      oval(body,side*.13,.99,.24,.18,.12,.11,cream);
    }else if(bunny){
      const ear=oval(body,side*.15,1.43,-.025,.085,.27,.065,fur);ear.rotation.z=-side*.12;
      const inner=oval(body,side*.15,1.45,.025,.043,.19,.025,0xe6abb1);inner.rotation.z=-side*.12;
      oval(body,side*.09,.97,.265,.095,.07,.065,cream);
    }else{
      oval(body,side*.27,1.30,-.035,.12,.13,.085,dark);
      // Flatten the markings against the face so they read as fur, not goggles.
      const patch=oval(body,side*.14,1.08,.263,.102,.12,.023,dark);patch.rotation.z=-side*.22;
      oval(body,side*.075,.975,.278,.09,.066,.045,cream);
    }
    if(fox){
      // Keep the eyes above the cheek patches, following the rounded head
      // surface so the muzzle cannot clip them into uneven crescents.
      const eye=new THREE.Group(),x=side*.135,y=.10;
      const z=.29*Math.sqrt(1-(x/.36)**2-(y/.30)**2);
      eye.position.set(x,1.05+y,z);
      eye.quaternion.setFromUnitVectors(new THREE.Vector3(0,0,1),new THREE.Vector3(x/.36**2,y/.30**2,z/.29**2).normalize());
      body.add(eye);
      oval(eye,0,0,.006,.030,.039,.016,0x25313b).castShadow=false;
      oval(eye,-.007,.012,.020,.006,.008,.004,0xffffff).castShadow=false;
    }else{
      const eyeX=side*.135,eyeZ=bunny?.285:.296;
      if(!bunny)oval(body,eyeX,1.085,.291,.041,.049,.012,cream).castShadow=false;
      oval(body,eyeX,1.08,eyeZ,bunny?.031:.026,bunny?.046:.034,.016,0x25313b).castShadow=false;
      oval(body,eyeX-.007,1.092,eyeZ+.014,.007,.010,.004,0xffffff).castShadow=false;
    }
    const arm=new THREE.Group();arm.position.set(side*.28,.73,0);body.add(arm);arms.push(arm);
    oval(arm,side*.025,-.16,0,.09,.20,.095,fox||bunny?fur:dark);
    oval(arm,side*.025,-.31,.035,.095,.07,.10,fox?dark:bunny?cream:dark);
    const leg=new THREE.Group();leg.position.set(side*.14,.27,0);body.add(leg);legs.push(leg);
    oval(leg,0,-.12,.07,.12,.14,.17,fox||!bunny?dark:fur);
  }
  oval(body,0,.99,fox?.345:.305,.04,.029,.028,bunny?0xd98f9a:dark);
  if(!fox)for(const side of [-1,1])characterCurve(body,[[0,.97,.323],[side*.026,.948,.317],[side*.05,.955,.310]],.0055,bunny?0x9c7374:dark);
  if(fox){
    const tail=new THREE.Group();tail.position.set(.03,.35,-.22);tail.rotation.z=-.55;body.add(tail);
    const plume=oval(tail,.18,.18,-.23,.14,.37,.15,fur);plume.rotation.x=-.42;
    oval(tail,.18,.47,-.36,.125,.16,.125,cream);
  }else oval(body,0,.44,-.26,bunny?.13:.09,bunny?.13:.09,.13,fur);
  // A coordinated accent complements the fur and markings.
  cylinder(body,0,.80,0,.245,.045,color,20);
  oval(body,0,.75,.265,.048,.055,.018,color);
  equipCharacter(body,{position:{z:fox?.307:bunny?.285:.296}},appearance,color,arms);
  return {group,body,arms,legs,appearance,color};
}
