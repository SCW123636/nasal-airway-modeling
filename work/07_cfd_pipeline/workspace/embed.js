'use strict';
(() => {
  if(window.nasalToolPresentationApplied)return;
  window.nasalToolPresentationApplied=true;
  const routes = {'/progress/index.html':'overview','/viewer/index.html':'geometry','/landmark-review/':'review','/landmark-review/index.html':'review','/landmark-review/feedback_review/index.html':'feedback','/solver_reference/phantom_validation/validation.json':'validation'};
  const uploaded = location.pathname.match(/^\/case-assets\/(u_[0-9a-f]{16})\/(?:versions\/v_[0-9a-f]{16}\/)?review\/index\.html$/);
  const manifest = new URLSearchParams(location.search).get('manifest');
  const manifestCase = manifest?.match(/^\/case-assets\/(u_[0-9a-f]{16})\/(?:versions\/v_[0-9a-f]{16}\/)?viewer\.json$/);
  const step = uploaded ? 'review' : routes[location.pathname];
  if (!step || !/^https?:$/.test(location.protocol)) return;
  const embedded = new URLSearchParams(location.search).get('embedded') === '1' && window.parent !== window;
  if (!embedded) {
    const query = new URLSearchParams();
    const caseId = uploaded?.[1] || manifestCase?.[1];
    if (caseId) query.set('case', caseId);
    if (step === 'geometry' && manifest !== null) {query.set('manifest', manifest); if (!caseId) query.set('case', 'existing');}
    location.replace('/workspace/index.html' + (query.size ? '?' + query.toString() : '') + '#' + step); return;
  }
  document.documentElement.dataset.workflow = step;
  const stylesheet = document.createElement('link'); stylesheet.rel = 'stylesheet'; stylesheet.href = '/workspace/embedded.css'; document.head.append(stylesheet);
  // Shared presentation for generated tools. Moving their DOM nodes preserves
  // all listeners, source data, review identities and immutable artifact hashes.
  function disclosure(label, nodes, before=null) {
    nodes = nodes.filter(Boolean); if (!nodes.length) return null;
    const details=document.createElement('details');details.className='tool-details';
    const summary=document.createElement('summary');summary.textContent=label;details.append(summary);
    const parent=nodes[0].parentNode;parent.insertBefore(details,before || nodes[0]);nodes.forEach(node=>details.append(node));return details;
  }
  if (step==='overview') {
    const wrap=document.querySelector('.wrap');
    if(wrap) [...wrap.querySelectorAll(':scope > .card')].forEach(card=>{
      const title=card.querySelector('h2');if(!title)return;
      const details=document.createElement('details'),summary=document.createElement('summary');summary.textContent=title.textContent;title.remove();
      details.append(summary);[...card.childNodes].forEach(node=>details.append(node));card.append(details);
    });
  }
  if (step==='review') {
    const top=document.querySelector('.top');
    if(top){
      const help=disclosure('读图说明与保存方式',[top.querySelector('.notice'),top.querySelector('.review-context')]);
      if(help)help.classList.add('review-help');
    }
    document.querySelector('#reviewer')?.setAttribute('placeholder','填写复核人');
    const revise=()=>{
      document.documentElement.classList.toggle('single-case',document.querySelectorAll('#case-list .case-button').length===1);
      document.querySelectorAll('#cards .card').forEach(card=>{
        if(card.dataset.compact)return;card.dataset.compact='true';
        const evidence=card.querySelector('.details');
        if(evidence){const coord=card.querySelector('.coord');if(coord)evidence.insertBefore(coord,evidence.querySelector('pre'));
          card.querySelectorAll(':scope > .normal').forEach(node=>evidence.insertBefore(node,evidence.querySelector('pre')));
          evidence.querySelector('summary').textContent='坐标、粗精对照与候选依据';}
      });
    };
    revise();new MutationObserver(revise).observe(document.querySelector('#cards'),{childList:true});
  }
  if(step==='geometry'){
    const aside=document.querySelector('main aside');
    if(aside){
      const fields=aside.querySelector('#field-status')?.closest('.card');if(fields){const title=fields.querySelector('h2');if(title){const panel=disclosure('流场图层可用性',[fields]);panel.classList.add('card');title.remove();fields.classList.remove('card');}}
      const feedback=aside.querySelector('.feedback-card');if(feedback){const title=feedback.querySelector('h2');const panel=disclosure('外部意见核对',[feedback]);panel.classList.add('card');title?.remove();feedback.classList.remove('card');}
    }
  }
  if(step==='feedback'){
    const main=document.querySelector('main'),selection=document.querySelector('#selection');
    if(main && selection){
      const version=document.createElement('p');version.className='feedback-version';version.textContent='正在核对意见对照版本…';main.insertBefore(version,selection);
      (async()=>{
        try{
          const audit=JSON.parse(document.querySelector('#audit-data').textContent);
          const checks=await Promise.all(Object.entries(audit.original_proposal_sha256).map(async([id,expected])=>{
            const response=await fetch('/landmark-review/'+encodeURIComponent(id)+'/landmarks.json');if(!response.ok)throw Error('无法读取候选');
            const hash=await crypto.subtle.digest('SHA-256',await response.arrayBuffer());
            return [...new Uint8Array(hash)].map(n=>n.toString(16).padStart(2,'0')).join('')===expected;
          }));
          version.textContent=checks.every(Boolean)?'意见对照与当前候选版本一致':'本页为旧版意见对照；当前候选已更新，正式判断请进入切片审核。';
        }catch{version.textContent='意见对照版本未能核验，请结合当前切片审核。';}
      })();
      const panels=[...main.querySelectorAll(':scope > .panel')];
      const context=disclosure('意见记录与来源',[main.querySelector(':scope > .notice'),main.querySelector('.stats'),panels[0]],selection);
      context?.classList.add('panel');
      main.insertBefore(selection,context);
      disclosure('本轮意见采纳范围',[panels[2]])?.classList.add('panel');
      const measures=selection.querySelector('.measurements');
      if(measures)disclosure('局部测量数值与解释',[measures,measures.nextElementSibling]);
      const sweep=selection.querySelector('#sweep-button');
      if(sweep){const scroll=sweep.nextElementSibling?.nextElementSibling;
        if(scroll?.classList.contains('scroll'))disclosure('位移测量表与解释',[scroll,scroll.nextElementSibling]);}
      selection.querySelectorAll(':scope > p:not([id])').forEach(node=>node.classList.add('secondary-description'));
    }
  }
  document.addEventListener('click', event => {
    const link = event.target.closest('a[href]');
    if (!link || link.hasAttribute('download')) return;
    const url = new URL(link.href,location.href);
    if (url.origin !== location.origin || !routes[url.pathname]) return;
    event.preventDefault();
    window.parent.postMessage({type:'nasal-workspace-navigate',step:routes[url.pathname],...(url.pathname === '/viewer/index.html' && url.searchParams.has('manifest') ? {manifest:url.searchParams.get('manifest')} : {})},location.origin);
  });
  window.addEventListener('message', event => {
    if (event.source === window.parent && event.origin === location.origin && event.data?.type === 'nasal-workspace-visible') window.dispatchEvent(new Event('resize'));
  });
})();
