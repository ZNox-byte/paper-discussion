"use strict";
const codexUI = { status:null, busy:false, error:'', model:localStorage.getItem('review-model')||'gpt-6-astra', effort:'high', loginURL:'', checking:false, request:null };
function renderCodexPanel() {
  const c=codexUI, s=c.status, models=s?.models||[], selected=models.find(m=>m.id===c.model);
  const current=research.jobs.find(j=>j.id===research.active), reviewing=current?.kind==='review';
  const eligible=state.route==='review' && state.run?.papers.some(p=>p.status==='validated');
  return `<section class="panel codex-panel" id="codex-panel"><div class="section-title"><div><span class="eyebrow">CODEX SUBSCRIPTION</span><h2>订阅终审</h2></div><span class="tag ${s?.authenticated?'':'amber'}">${s?.authenticated?'已登录':s?.login_pending?'等待登录':'未连接订阅'}</span></div>
    <p>使用具有 Codex 权限的 ChatGPT 账号，不需要 OpenAI API Key。${s?.plan?`当前套餐：${esc(s.plan)}。`:''}审阅会消耗 Codex 套餐额度。</p>
    <div class="codex-actions"><button class="button secondary" data-codex="connect" ${c.busy?'disabled':''}>${c.busy?'正在连接…':s?.connected?'刷新连接与模型':'检查 Codex 连接'}</button>${!s?.authenticated?`<button class="button" data-codex="login" ${c.busy?'disabled':''}>登录订阅账号</button>`:''}</div>
    ${c.loginURL&&!s?.authenticated?`<p><a class="text-link" href="${safeUrl(c.loginURL)}" target="_blank" rel="noopener noreferrer">继续浏览器登录 ${icon('external')}</a></p>`:''}
    <p class="field-help">首次在本应用中登录。登录缓存保存在项目目录内，关闭 VS Code 后仍可使用。</p>
    ${s?.authenticated?`<div class="form-grid"><label>终审模型<select id="codex-model" ${research.active?'disabled':''}>${!selected?`<option value="${esc(c.model)}">${esc(c.model)} · 当前列表未提供</option>`:''}${models.map(m=>`<option value="${esc(m.id)}" ${m.id===c.model?'selected':''}>${esc(m.name)}</option>`).join('')}</select></label><label>推理强度<select id="codex-effort" ${!selected||research.active?'disabled':''}>${(selected?.efforts||[]).map(e=>`<option value="${esc(e)}" ${e===c.effort?'selected':''}>${esc({low:'低',medium:'中',high:'高',xhigh:'更高',max:'最高',ultra:'极高'}[e]||e)}</option>`).join('')}</select></label></div>${!selected?'<p class="warning-text">当前登录的模型列表没有提供所选模型。可手动选择列表中的模型；应用不会自动替换 Astra。</p>':''}`:''}
    ${state.route==='review'?`<button class="button full" data-codex="review" ${!s?.authenticated||!selected||!eligible||research.active||c.busy?'disabled':''}>${icon('check')}使用所选 Codex 模型进行终审</button><p class="field-help">将本轮研究需求、阅读卡片及引文上下文发送给 Codex。生成新的审阅记录；原结果保留。证据不足时返回补读清单。</p>`:`<p class="field-help">阅读完成后，在“审阅与问题”中点击启动终审。其他厂商 Flash 的调用仍使用其各自配置和额度。</p>`}
    ${reviewing?`<div class="codex-progress" role="status"><b>${esc(jobLabels[current.status]||current.status)}</b><p>${esc(current.message)}</p><button class="text-button" data-job-open="${current.id}">打开审阅记录</button><button class="text-button warning-text" data-job-stop="${current.id}" ${current.status==='stopping'?'disabled':''}>停止审阅</button></div>`:''}
    ${c.error?`<p class="form-error" role="alert">${esc(c.error)}</p>`:''}
  </section>`;
}
function updateCodexPanel() {
  const element=$('#codex-panel'); if(element)element.outerHTML=renderCodexPanel();
}
function acceptCodexStatus(status) {
  codexUI.status=status;
  const model=status.models?.find(m=>m.id===codexUI.model);
  if(model&&!model.efforts.includes(codexUI.effort))codexUI.effort=model.default_effort;
  if(status.authenticated)codexUI.loginURL='';
  codexUI.error=status.error||'';
}
document.addEventListener('change',event=>{
  if(event.target.id==='codex-model'){
    codexUI.model=event.target.value;localStorage.setItem('review-model',codexUI.model);
    acceptCodexStatus(codexUI.status);updateCodexPanel();
  }
  if(event.target.id==='codex-effort')codexUI.effort=event.target.value;
});
document.addEventListener('click',async event=>{
  const button=event.target.closest('[data-codex]');if(!button||button.disabled||codexUI.busy)return;
  const action=button.dataset.codex;
  // Reserve a tab while handling the user's click to avoid popup blocking after await.
  const loginTab=action==='login'?window.open('about:blank','_blank'):null;
  if(loginTab)loginTab.opener=null;
  codexUI.busy=true;codexUI.error='';updateCodexPanel();
  try {
    if(action==='connect')acceptCodexStatus(await postJob('/api/codex/connect',{}));
    if(action==='login'){
      const response=await postJob('/api/codex/login',{});
      codexUI.loginURL=response.auth_url;
      if(loginTab)loginTab.location.href=response.auth_url;
      acceptCodexStatus(await api('/api/codex/status'));
    }
    if(action==='review'){
      const body={source_run:state.run.id,model:codexUI.model,effort:codexUI.effort};
      const signature=JSON.stringify(body);
      if(codexUI.request?.signature!==signature)codexUI.request={signature,id:crypto.randomUUID()};
      const job=await postJob('/api/jobs/review',{...body,request_id:codexUI.request.id});
      codexUI.request=null;research.active=job.id;
      await updateJobs();state.index=await api('/api/runs');state.route='review';await loadRun(job.id);
      notify('已启动订阅终审，结果将显示在新的研究记录中。');
    }
  }catch(error){if(loginTab)loginTab.close();codexUI.error=error.message;}
  finally{codexUI.busy=false;updateCodexPanel();}
});
setInterval(async()=>{
  if(codexUI.checking||codexUI.busy)return;
  codexUI.checking=true;
  try {
    if(codexUI.status?.login_pending){acceptCodexStatus(await api('/api/codex/status'));updateCodexPanel();}
    if(state.route==='review'){
      const previous=research.active;
      await updateJobs();
      if(previous&&!research.active&&state.run?.id===previous)await loadRun(previous);
      updateCodexPanel();
    }
  }catch(error){codexUI.error=error.message;updateCodexPanel();}
  finally{codexUI.checking=false;}
},3000);
api('/api/codex/status').then(status=>{acceptCodexStatus(status);updateCodexPanel();}).catch(()=>{});
