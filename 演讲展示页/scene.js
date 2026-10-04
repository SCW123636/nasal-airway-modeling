import * as THREE from 'three';
import {OrbitControls} from './assets/vendor/OrbitControls.js';

const canvas=document.querySelector('#scene-canvas');
const note=document.querySelector('#render-note');
const mobile=()=>innerWidth<=700;
const reduced=matchMedia('(prefers-reduced-motion: reduce)').matches;
try {
  const renderer=new THREE.WebGLRenderer({canvas,alpha:true,antialias:true,powerPreference:'high-performance'});
  renderer.setPixelRatio(Math.min(devicePixelRatio,mobile()?1.5:1.8));
  renderer.setClearColor(0x061415,0);
  const scene=new THREE.Scene();
  const camera=new THREE.PerspectiveCamera(32,innerWidth/innerHeight,.05,50);
  camera.position.set(0,0,6.1);
  const group=new THREE.Group();scene.add(group);
  const light=new THREE.HemisphereLight(0x91f1ce,0x102b21,2);scene.add(light);
  const key=new THREE.DirectionalLight(0xa4f7d5,3);key.position.set(1,3,4);scene.add(key);
  const side=new THREE.DirectionalLight(0xfaac83,1.2);side.position.set(-3,-1,2);scene.add(side);
  const controls=new OrbitControls(camera,canvas);controls.enabled=false;controls.enableDamping=true;controls.enablePan=false;controls.enableZoom=false;controls.rotateSpeed=.38;
  controls.minPolarAngle=Math.PI*.30;controls.maxPolarAngle=Math.PI*.68;
  let manual=0;controls.addEventListener('start',()=>{manual=performance.now()+5500;});
  const resize=()=>{renderer.setSize(innerWidth,innerHeight,false);camera.aspect=innerWidth/innerHeight;camera.fov=mobile()?39:32;camera.updateProjectionMatrix();};addEventListener('resize',resize);resize();
  const [meta,positionData,indexData]=await Promise.all([
    fetch('./assets/model.json').then(r=>{if(!r.ok)throw Error('model metadata');return r.json();}),
    fetch('./assets/airway-positions.bin').then(r=>{if(!r.ok)throw Error('model vertices');return r.arrayBuffer();}),
    fetch('./assets/airway-indices.bin').then(r=>{if(!r.ok)throw Error('model indices');return r.arrayBuffer();})
  ]);
  if(meta.cfd_ready!==false||meta.display_geometry_only!==true)throw Error('Expected display-only candidate');
  const positions=new Float32Array(positionData),indices=new Uint32Array(indexData);
  const geometry=new THREE.BufferGeometry();geometry.setAttribute('position',new THREE.BufferAttribute(positions,3));geometry.setIndex(new THREE.BufferAttribute(indices,1));geometry.computeVertexNormals();
  const surfaceMat=new THREE.MeshStandardMaterial({color:0x438a73,emissive:0x163b2d,emissiveIntensity:.3,transparent:true,opacity:.19,roughness:.64,metalness:.08,side:THREE.DoubleSide,depthWrite:false});
  const surface=new THREE.Mesh(geometry,surfaceMat);group.add(surface);
  const step=mobile()?5:3, cloud=[];
  for(let i=0;i<positions.length;i+=step*3)cloud.push(positions[i],positions[i+1],positions[i+2]);
  const pointGeo=new THREE.BufferGeometry();pointGeo.setAttribute('position',new THREE.Float32BufferAttribute(cloud,3));
  const pointMat=new THREE.ShaderMaterial({transparent:true,depthWrite:false,blending:THREE.AdditiveBlending,
    uniforms:{uTime:{value:0},uOpacity:{value:.8},uScan:{value:-2},uScatter:{value:0},uSize:{value:mobile()?2.2:1.9},uMode:{value:0}},
    vertexShader:`uniform float uTime;uniform float uScan;uniform float uScatter;uniform float uSize;varying float vBand;varying float vDepth;void main(){vec3 p=position;float wave=sin(uTime*.6+position.z*2.0)*.003;p+=normalize(position+.1)*wave;vec3 n=normalize(vec3(sin(position.x*23.0+position.z*11.0),cos(position.z*17.0+position.y*7.0),sin(position.y*19.0)));p+=n*uScatter*.4;vBand=exp(-pow((position.y-uScan)*14.0,2.0));vec4 mv=modelViewMatrix*vec4(p,1.0);vDepth=clamp((-mv.z-3.5)/5.0,0.0,1.0);gl_Position=projectionMatrix*mv;gl_PointSize=uSize*(5.0/max(2.0,-mv.z))*(1.0+vBand*.8);}`,
    fragmentShader:`uniform float uOpacity;varying float vBand;varying float vDepth;void main(){float r=length(gl_PointCoord-.5);if(r>.5)discard;float alpha=(1.0-smoothstep(.03,.5,r))*uOpacity*(.78-vDepth*.4);vec3 color=mix(vec3(.29,.88,.67),vec3(1.0,.74,.48),vBand);gl_FragColor=vec4(color,alpha);}`});
  const points=new THREE.Points(pointGeo,pointMat);group.add(points);
  const edges=[];
  for(let i=0;i<indices.length;i+=mobile()?93:51){const a=indices[i]*3,b=indices[i+1]*3,c=indices[i+2]*3;for(const [p,q] of [[a,b],[b,c]])edges.push(positions[p],positions[p+1],positions[p+2],positions[q],positions[q+1],positions[q+2]);}
  const edgeGeo=new THREE.BufferGeometry();edgeGeo.setAttribute('position',new THREE.Float32BufferAttribute(edges,3));
  const wire=new THREE.LineSegments(edgeGeo,new THREE.LineBasicMaterial({color:0x73ba91,transparent:true,opacity:.09,depthWrite:false}));group.add(wire);
  const orbitGroup=new THREE.Group();group.add(orbitGroup);
  const makeRing=(radius,angle,opacity)=>{
    const pts=[];for(let i=0;i<=180;i++){const a=i/180*Math.PI*2;pts.push(new THREE.Vector3(Math.cos(a)*radius,Math.sin(a)*radius*.58,0));}
    const ring=new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts),new THREE.LineBasicMaterial({color:0x75d0a2,transparent:true,opacity,depthWrite:false}));ring.rotation.set(angle,-.2,.2);orbitGroup.add(ring);return ring;
  };
  const ringA=makeRing(1.79,.5,.14),ringB=makeRing(1.94,1.7,.06);
  const ticks=[];for(let i=0;i<64;i++){const a=i/64*Math.PI*2,r=1.81;const ext=i%8===0?.055:.018;ticks.push(Math.cos(a)*r,Math.sin(a)*r*.58,0,Math.cos(a)*(r+ext),Math.sin(a)*(r+ext)*.58,0);}
  const ruler=new THREE.LineSegments(new THREE.BufferGeometry().setAttribute('position',new THREE.Float32BufferAttribute(ticks,3)),new THREE.LineBasicMaterial({color:0x66a681,transparent:true,opacity:.23}));ruler.rotation.copy(ringA.rotation);orbitGroup.add(ruler);
  const planeGeo=new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(-.85,0,-1.53),new THREE.Vector3(.85,0,-1.53),new THREE.Vector3(.85,0,1.53),new THREE.Vector3(-.85,0,1.53),new THREE.Vector3(-.85,0,-1.53)]);
  const scanPlane=new THREE.Line(planeGeo,new THREE.LineBasicMaterial({color:0xffc198,transparent:true,opacity:0,depthWrite:false}));group.add(scanPlane);
  const markerGroup=new THREE.Group();group.add(markerGroup);
  const markers=meta.landmarks.map(lm=>{const marker=new THREE.Mesh(new THREE.SphereGeometry(.023,12,8),new THREE.MeshBasicMaterial({color:0xffbd83,transparent:true,opacity:0,depthTest:false}));marker.position.fromArray(lm.position);marker.userData=lm;markerGroup.add(marker);return marker;});
  const searchFrame=new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.BoxGeometry(1.28,1.25,2.83)),new THREE.LineBasicMaterial({color:0x53886e,transparent:true,opacity:0}));group.add(searchFrame);
  const axisPts=[0,0,0,1.15,0,0,0,0,0,0,1,0,0,0,0,0,0,1.5];
  const axis=new THREE.LineSegments(new THREE.BufferGeometry().setAttribute('position',new THREE.Float32BufferAttribute(axisPts,3)),new THREE.LineBasicMaterial({color:0xc9b995,transparent:true,opacity:0}));group.add(axis);
  const dust=[];for(let i=0;i<(mobile()?180:360);i++)dust.push((Math.random()-.5)*10,(Math.random()-.5)*6,(Math.random()-.5)*4-1);
  const dustObj=new THREE.Points(new THREE.BufferGeometry().setAttribute('position',new THREE.Float32BufferAttribute(dust,3)),new THREE.PointsMaterial({size:.009,color:0x74b196,transparent:true,opacity:.36,sizeAttenuation:true,depthWrite:false}));scene.add(dustObj);
  const flowGroup=new THREE.Group();group.add(flowGroup);
  const paths=[];
  for(let i=0;i<22;i++){
    const side=i%2?1:-1,offset=(i%11)/10;
    const curve=new THREE.CatmullRomCurve3([
      new THREE.Vector3(side*(.26+offset*.1),-.57+offset*.14,1.72),
      new THREE.Vector3(side*(.28+offset*.18),-.18+offset*.12,.78),
      new THREE.Vector3(side*(.19+offset*.14),.17+offset*.1,-.03),
      new THREE.Vector3(side*(.14+offset*.09),-.01+offset*.1,-.90),
      new THREE.Vector3(.09+offset*.09,-.44+offset*.11,-1.55)]);
    paths.push(curve);
    const line=new THREE.Line(new THREE.BufferGeometry().setFromPoints(curve.getPoints(65)),new THREE.LineBasicMaterial({color:i%3===0?0xedb68c:0x64caa3,transparent:true,opacity:.05,depthWrite:false,blending:THREE.AdditiveBlending}));flowGroup.add(line);
  }
  const tracerCount=mobile()?260:480;
  const tracerPos=new Float32Array(tracerCount*3);const tracerColors=new Float32Array(tracerCount*3);
  for(let i=0;i<tracerCount;i++){const c=new THREE.Color(i%3?0x9ee5bc:0xffbc85);c.toArray(tracerColors,i*3);}
  const tracerGeo=new THREE.BufferGeometry();tracerGeo.setAttribute('position',new THREE.BufferAttribute(tracerPos,3));tracerGeo.setAttribute('color',new THREE.BufferAttribute(tracerColors,3));
  const tracerMat=new THREE.PointsMaterial({size:.016,vertexColors:true,transparent:true,opacity:0,blending:THREE.AdditiveBlending,depthWrite:false});
  const tracers=new THREE.Points(tracerGeo,tracerMat);group.add(tracers);
  const modes=[
    {surface:.14,point:.86,wire:.055,flow:.22,scan:0,marker:0,frame:0,angle:-.82,tilt:.15},
    {surface:.31,point:.44,wire:.06,flow:0,scan:0,marker:1,frame:0,angle:.22,tilt:.15},
    {surface:.1,point:.83,wire:.11,flow:0,scan:1,marker:0,frame:.16,angle:-.75,tilt:.1},
    {surface:.08,point:.59,wire:.2,flow:0,scan:0,marker:1,frame:.42,angle:.36,tilt:.16},
    {surface:.06,point:.23,wire:.02,flow:0,scan:0,marker:0,frame:0,angle:-1,tilt:.12},
    {surface:.1,point:.61,wire:.06,flow:.8,scan:0,marker:0,frame:0,angle:-.73,tilt:.14}
  ];
  let last=performance.now(),time=0,prevIndex=-1,wasEnabled=false;
  const ease=(a,b,t)=>a+(b-a)*t;
  document.body.classList.add('scene-ready');note.textContent='';
  window.airwayScene={renderer,camera,group,points,tracers,meta};
  function render(now){
    requestAnimationFrame(render);
    if(document.hidden){last=now;return;}
    const dt=Math.min(.05,(now-last)/1000);last=now;
    const state=window.airwayPresentation||{index:0,paused:reduced,focus:'nostril'};
    if(!state.paused)time+=dt;
    const index=state.index,target=modes[index]||modes[0],blend=1-Math.exp(-dt*3.3);
    if(index!==prevIndex){manual=0;prevIndex=index;}
    if(controls.enabled!== (index===1)){controls.enabled=index===1;if(!controls.enabled){camera.position.set(0,0,6.1);camera.lookAt(0,0,0);controls.target.set(0,0,0);}}
    const mx=mobile()?0:1.22,my=mobile()?-1.14:0;
    group.position.x=ease(group.position.x,mx,blend);group.position.y=ease(group.position.y,my,blend);
    group.scale.setScalar(ease(group.scale.x,mobile()?.91:1,blend));
    if(manual<now){group.rotation.y=ease(group.rotation.y,target.angle+Math.sin(time*.16)*.08,blend);group.rotation.x=ease(group.rotation.x,target.tilt,blend);group.rotation.z=ease(group.rotation.z,-.13,blend);}
    const dim=state.footer?.4:1;
    surfaceMat.opacity=ease(surfaceMat.opacity,target.surface*dim,blend);
    pointMat.uniforms.uOpacity.value=ease(pointMat.uniforms.uOpacity.value,target.point*dim,blend);
    wire.material.opacity=ease(wire.material.opacity,target.wire*dim,blend);
    tracerMat.opacity=ease(tracerMat.opacity,target.flow,blend);
    scanPlane.material.opacity=ease(scanPlane.material.opacity,target.scan*.5,blend);
    searchFrame.material.opacity=ease(searchFrame.material.opacity,target.frame,blend);
    axis.material.opacity=ease(axis.material.opacity,index===3?.45:0,blend);
    const scanY=Math.sin(time*.8)*.67;scanPlane.position.y=scanY;
    pointMat.uniforms.uTime.value=time;pointMat.uniforms.uScan.value=index===2?scanY:-2;
    orbitGroup.rotation.z=Math.sin(time*.12)*.12;dustObj.rotation.y=time*.01;
    markers.forEach((marker,i)=>{const key=marker.userData.key;const match=state.focus==='nostril'?key.startsWith('nostril'):state.focus==='choana'?key.startsWith('posterior'):key==='nasopharynx_outlet';const opacity=target.marker*(index===3?.8:(match?1:.16));marker.material.opacity=ease(marker.material.opacity,opacity,blend);marker.scale.setScalar((match?1.35:1)*(1+Math.sin(time*2.2+i)*.12));});
    for(let i=0;i<tracerCount;i++){const p=paths[i%paths.length].getPoint((i/tracerCount+time*.09*(.75+(i%7)*.065))%1);tracerPos[i*3]=p.x;tracerPos[i*3+1]=p.y;tracerPos[i*3+2]=p.z;}
    tracerGeo.attributes.position.needsUpdate=true;
    flowGroup.children.forEach(line=>line.material.opacity=tracerMat.opacity*.11);
    controls.update();renderer.render(scene,camera);
  }
  requestAnimationFrame(render);
}catch(error){
  note.textContent='此设备暂未启用三维显示；章节内容与验证数据仍可查看。';
  document.querySelector('#scene-canvas').hidden=true;
  console.error('Presentation scene:',error.message);
}
