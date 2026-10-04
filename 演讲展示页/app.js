(() => {
  const sections = [...document.querySelectorAll('.story-screen')];
  const dots = [...document.querySelectorAll('.chapter-nav a')];
  const counter = document.querySelector('#chapter-counter');
  let current = 0, ticking = false;
  window.airwayPresentation = { index: 0, progress: 0, paused: matchMedia('(prefers-reduced-motion: reduce)').matches, focus: 'nostril' };
  document.body.classList.add('js-ready');
  const state = window.airwayPresentation;
  const go = (index) => sections[Math.max(0, Math.min(sections.length-1, index))].scrollIntoView({ behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' });
  function update() {
    const middle = innerHeight * .48;
    const visible = sections.filter(section => { const r = section.getBoundingClientRect(); return r.top < innerHeight*.85 && r.bottom > innerHeight*.12; });
    let index = 0;
    sections.forEach((section, i) => { if (section.getBoundingClientRect().top <= middle) index = i; section.classList.toggle('in-view', visible.includes(section)); });
    current = index;
    dots.forEach((dot, i) => { dot.classList.toggle('active', i===index); if(i===index)dot.setAttribute('aria-current','step');else dot.removeAttribute('aria-current'); });
    counter.textContent = `${String(index+1).padStart(2,'0')} / 06`;
    state.index = index;
    const rect = sections[index].getBoundingClientRect();
    state.progress = Math.max(0, Math.min(1, -rect.top / rect.height));
    state.footer = document.querySelector('footer').getBoundingClientRect().top < innerHeight * .6;
    document.querySelector('.top-progress i').style.transform = `scaleX(${Math.max(0, Math.min(1, scrollY / Math.max(1,document.documentElement.scrollHeight-innerHeight)))})`;
    document.querySelector('#visual-stage').classList.toggle('interactive', index===1);
    ticking=false;
  }
  addEventListener('scroll', () => { if(!ticking){ticking=true;requestAnimationFrame(update);} }, {passive:true});
  addEventListener('resize',update); update();
  document.querySelector('#previous').addEventListener('click',()=>go(current-1));
  document.querySelector('#next-chapter').addEventListener('click',()=>go(current+1));
  const motion = document.querySelector('#motion-toggle');
  function syncMotion(){document.body.classList.toggle('motion-paused',state.paused);motion.setAttribute('aria-pressed',String(state.paused));motion.setAttribute('aria-label',state.paused?'继续动效':'暂停动效');}
  motion.addEventListener('click',()=>{state.paused=!state.paused;syncMotion();});syncMotion();
  const presentationButton = document.querySelector('#present-toggle');
  const exitButton = document.querySelector('#exit-present');
  async function presentation(enabled) {
    document.body.classList.toggle('presenting',enabled);
    exitButton.hidden=!enabled;
    presentationButton.setAttribute('aria-pressed',String(enabled));
    if(enabled && !document.fullscreenElement){try{await document.documentElement.requestFullscreen();}catch{/* CSS presentation remains usable. */}}
    if(!enabled && document.fullscreenElement){try{await document.exitFullscreen();}catch{}}
  }
  presentationButton.addEventListener('click',()=>presentation(!document.body.classList.contains('presenting')));
  exitButton.addEventListener('click',()=>presentation(false));
  document.addEventListener('fullscreenchange',()=>{if(!document.fullscreenElement){document.body.classList.remove('presenting');exitButton.hidden=true;presentationButton.setAttribute('aria-pressed','false');}});
  document.addEventListener('keydown',(event)=>{
    if(event.ctrlKey||event.altKey||event.metaKey||document.querySelector('dialog[open]')||event.target.matches('input,textarea,select'))return;
    if(['ArrowDown','ArrowRight','PageDown'].includes(event.key)){event.preventDefault();go(current+1);}
    else if(['ArrowUp','ArrowLeft','PageUp'].includes(event.key)){event.preventDefault();go(current-1);}
    else if(event.key==='Home'){event.preventDefault();go(0);}
    else if(event.key==='End'){event.preventDefault();go(sections.length-1);}
    else if(event.key.toLowerCase()==='f'){event.preventDefault();presentation(!document.body.classList.contains('presenting'));}
    else if(event.key==='Escape')presentation(false);
  });
  const labels={nostril:'鼻孔入口候选',choana:'后鼻孔候选',outlet:'鼻咽出口候选'};
  document.querySelectorAll('[data-focus]').forEach(button=>button.addEventListener('click',()=>{
    state.focus=button.dataset.focus;
    document.querySelectorAll('[data-focus]').forEach(b=>b.classList.toggle('selected',b===button));
    document.querySelector('#landmark-title').textContent=labels[state.focus];
  }));
  const atlas = document.querySelector('#atlas-dialog');
  document.querySelector('#open-atlas').addEventListener('click',()=>atlas.showModal());
  atlas.querySelector('.dialog-close').addEventListener('click',()=>atlas.close());
  atlas.addEventListener('click',event=>{if(event.target===atlas){const r=atlas.getBoundingClientRect();if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom)atlas.close();}});
  const image=document.querySelector('#atlas-image');
  const sources={openstax:{src:'https://upload.wikimedia.org/wikipedia/commons/c/c2/731_Nasal_Cavity.jpg',alt:'OpenStax 鼻腔解剖图',credit:'OpenStax College · CC BY 3.0 · 原图未修改',link:'https://commons.wikimedia.org/wiki/File:731_Nasal_Cavity.jpg'},research:{src:'https://upload.wikimedia.org/wikipedia/commons/b/b3/Anatomy_of_the_human_nasal_cavity.png',alt:'鼻腔功能分区开放研究示意图',credit:'Stella Gänger & Katharina Schindowski · CC BY 4.0 · 原图未修改',link:'https://commons.wikimedia.org/wiki/File:Anatomy_of_the_human_nasal_cavity.png'}};
  image.addEventListener('error',()=>{document.querySelector('#atlas-error').hidden=false;});
  image.addEventListener('load',()=>{document.querySelector('#atlas-error').hidden=true;});
  document.querySelectorAll('[data-atlas]').forEach(button=>button.addEventListener('click',()=>{
    const data=sources[button.dataset.atlas]; image.src=data.src;image.alt=data.alt;
    const credit=document.querySelector('#atlas-credit');credit.replaceChildren(document.createTextNode(data.credit+' '));
    const a=document.createElement('a');a.href=data.link;a.target='_blank';a.rel='noopener';a.textContent='原图与许可 ↗';credit.append(a);
    document.querySelectorAll('[data-atlas]').forEach(b=>b.classList.toggle('selected',b===button));
  }));
  fetch('./assets/evidence.json').then(r=>{if(!r.ok)throw Error('Evidence unavailable');return r.json();}).then(data=>{
    const x=[90,315,540],y=v=>300-v*102;
    document.querySelector('.pressure-line').setAttribute('d',data.chart.map((c,i)=>`${i?'L':'M'}${x[i]} ${y(c.pressure_error_percent)}`).join(''));
    document.querySelector('.velocity-line').setAttribute('d',data.chart.map((c,i)=>`${i?'L':'M'}${x[i]} ${y(c.velocity_error_percent)}`).join(''));
    for(const [group,key] of [['pressure-points','pressure_error_percent'],['velocity-points','velocity_error_percent']])document.querySelectorAll('.'+group+' circle').forEach((circle,i)=>circle.setAttribute('cy',y(data.chart[i][key])));
  }).catch(()=>{/* Verified initial values stay visible. */});
})();
