"use strict";
const research = { settings: null, draft: null, jobs: [], active: null, selected: null, candidates: [], error: '', submitting: false, polling: false, pendingRequest: null };
const jobLabels = { queued:'等待开始', running:'正在执行', stopping:'正在停止', completed:'已完成', failed:'任务失败', interrupted:'已中断', awaiting_review:'等待外部终审', needs_revision:'待修订', insufficient_evidence:'证据待补充' };
const activeJob = job => job && ['queued','running','stopping'].includes(job.status);
const jobById = id => research.jobs.find(j => j.id === id);
const modelOptions = selected => (research.settings?.models||[]).map(m=>`<option value="${esc(m.alias)}" ${m.alias===selected?'selected':''}>${esc(m.provider)} / ${esc(m.model)}${m.available?'':' · 密钥未设置'}</option>`).join('');
function todayUTC() { return new Date().toISOString().slice(0,10); }

function renderResearch() {
  if (!research.draft) return '<section class="panel"><p>正在读取研究设置…</p></section>';
  const d = research.draft, settings = research.settings, models = settings.models || [];
  const model = models.find(m=>m.alias===d.flash_model);
  return `<div class="research-layout"><form id="research-form" class="panel research-form">
    <label class="field-label" for="research-question">我的研究需求 <span>必填</span></label>
    <textarea id="research-question" name="question" required minlength="8" maxlength="6000" rows="6" placeholder="例如：查询近一年大模型推理加速的研究。我更想看实验数据：在什么模型、数据集和硬件上，比哪些基线快多少？重点比较吞吐量、首 token 延迟和显存占用，标出原文依据。">${esc(d.question)}</textarea>
    <p class="field-help">可以写你想了解算法原理、实验数据，或两者之间的关系。也可以直接指定算法名称、指标和使用场景。</p>
    <div class="form-grid"><label>开始日期<input type="date" name="date_from" value="${esc(d.date_from)}" max="${todayUTC()}"></label><label>结束日期<input type="date" name="date_to" value="${esc(d.date_to)}" max="${todayUTC()}"></label></div>
    <p class="field-help">按 arXiv 首次提交日期筛选；留空表示不限制该端日期。</p>
    <div class="form-grid model-grid"><label>下层 Flash 模型<select name="flash_model" required>${models.length?modelOptions(d.flash_model):'<option value="">暂无已配置的 Flash 模型</option>'}</select></label><label>计划阅读篇数<input type="number" name="target_papers" min="1" max="32" required value="${d.target_papers}"></label></div>
    <div id="model-availability">${modelNote(model)}</div>
    <details class="search-advanced" ${d.keywords?'open':''}><summary>手动检索词与数量设置（可选）</summary><label>英文关键词或 arXiv 检索式<textarea name="keywords" rows="3" maxlength="2000" placeholder='每行一个主题，最多 6 行，例如：\nspeculative decoding\nall:"LLM serving" AND all:scheduling'>${esc(d.keywords)}</textarea></label><p class="field-help">留空时由所选 Flash 根据上面的完整需求生成检索式。填写后直接检索，不调用模型生成检索式；你的研究需求仍会传给后续阅读。</p><label>每条检索式最多取回<input type="number" name="max_results" min="10" max="100" required value="${d.max_results}"></label></details>
    <div id="research-error" role="alert">${research.error?`<p class="form-error">${esc(research.error)}</p>`:''}</div>
    <div class="research-submit"><button type="submit" class="button" ${research.submitting||research.active||!models.length?'disabled':''}>${icon('search')}${research.submitting?'正在提交…':'按需求检索文献'}</button><span>先看候选论文，再决定是否开始阅读</span></div>
  </form><aside class="research-guide">${typeof renderCodexPanel === "function" ? renderCodexPanel() : ""}<section class="panel"><h2>这次任务会怎样进行</h2><ol class="research-steps"><li><b>按你的话检索</b><p>生成英文检索式，查询 arXiv 并去重。检索式会发送给 arXiv。</p></li><li><b>查看候选与选择模型</b><p>按时间浏览论文摘要，调整要读的篇数和 Flash 模型。</p></li><li><b>围绕原需求阅读</b><p>筛选、逐篇阅读和上层审阅都会收到你填写的完整要求。</p></li></ol><div class="review-configuration"><span>上层审阅者</span><strong>${esc(settings.reviewer||'未配置')}</strong><p>${'阅读完成后，在“审阅与问题”中点击 Codex 订阅终审。'}</p></div></section><div class="inline-note">检索覆盖 arXiv，结果受日期、关键词与取回数量限制。“最新发表”不等于“实验效果最好”。</div></aside></div>
  <section id="research-jobs">${renderResearchJobs()}</section><section id="research-candidates">${renderResearchCandidates()}</section>`;
}
function modelNote(model) {
  if (!model) return '<p class="field-help warning-text">在项目 config.toml 中配置 Flash 模型后，刷新即可选择。</p>';
  return `<p class="field-help ${model.available?'':'warning-text'}">${model.available?'检索式生成与后续筛选、阅读使用此 Flash。使用该供应商的独立额度，Codex 订阅不包含此 Flash 用量。':`所选模型的 ${esc(model.key_env)} 尚未设置。可先填写手动检索词查询；自然语言检索和阅读需在设置密钥后重启本地服务。`}</p><p class="field-help">菜单只列出项目中已配置的 Flash 模型；不会将下层任务自动升级为 Pro。</p>`;
}
function renderResearchJobs() {
  if (!research.jobs.length) return '';
  return `<div class="section-title research-section-title"><h2>查询与阅读任务</h2><span class="subtle">每 3 秒更新任务状态</span></div><div class="job-list">${research.jobs.map(j=>`<article class="job-card ${research.selected===j.id?'selected':''}"><div class="job-header"><span class="tag">${j.kind==='review'?'Codex 订阅终审':j.kind==='search'?'文献检索':'Flash 阅读'}</span><span class="status ${j.status==='failed'?'warning':'neutral'}">${esc(jobLabels[j.status]||j.status)}</span><span class="job-date">${date(j.created_at)}</span></div><h3>${esc(j.request.title||j.request.question.split('\n')[0])}</h3><p class="job-message">${esc(j.message)}</p><div class="job-counts">${j.candidate_count} 篇候选${j.kind==='read'?` · ${j.read_count} / ${j.request.target_papers} 份阅读结果`:''}<span>${esc(j.request.flash_model)}</span></div><div class="job-actions">${j.kind==='search'&&j.status==='completed'?`<button class="button secondary" data-search-results="${j.id}">查看候选论文</button>`:''}<button class="text-button" data-job-open="${j.id}">${j.kind!=='search'?'打开研究结果':'打开记录'}</button>${activeJob(j)?`<button class="text-button warning-text" data-job-stop="${j.id}" ${j.status==='stopping'?'disabled':''}>停止任务</button>`:''}</div><details class="job-details"><summary>本次需求、检索式与过程</summary><p class="saved-question">${esc(j.request.question)}</p>${(j.queries||[]).map(q=>`<code>${esc(q)}</code>`).join('')}<pre>${esc((j.logs||[]).join('\n'))}</pre></details></article>`).join('')}</div>`;
}
function renderResearchCandidates() {
  const job = jobById(research.selected);
  if (!job || job.kind!=='search') return '';
  const papers = sortPapers(research.candidates);
  return `<div class="section-title research-section-title"><div><h2>候选论文 · ${papers.length} 篇</h2><p class="muted">此次检索取回的论文，按首次发表时间排序。</p></div>${sortControl('research-sort')}</div><div class="search-reading-bar"><div><label>本次阅读使用<select id="result-model">${modelOptions(research.draft.flash_model)}</select></label><label>阅读篇数<input id="result-count" type="number" min="1" max="${Math.min(32,papers.length)||1}" value="${Math.min(research.draft.target_papers,papers.length)||1}"></label></div><button class="button" data-start-reading="${job.id}" ${research.active||research.submitting||!papers.length?'disabled':''}>${icon('book')}开始 Flash 阅读</button><p>读取这次检索保存的原始研究需求；从这些候选中筛选指定篇数。会调用所选模型并产生用量。</p></div>${papers.length?`<div class="paper-list">${papers.map(p=>`<article class="candidate-row"><div class="paper-tags"><span class="tag">待筛选</span><span>首次发表 ${date(p.published)}</span></div><h3><a href="${safeUrl(p.url)}" target="_blank" rel="noopener noreferrer">${esc(p.title)} ${icon('external')}</a></h3><p class="field-help">${esc((p.authors||[]).slice(0,6).join(' · '))}</p><details><summary>查看摘要</summary><p>${esc(p.abstract||'摘要未记录')}</p></details></article>`).join('')}</div>`:'<div class="empty-state"><h3>这个范围内没有找到论文</h3><p>可扩大日期范围，补充英文关键词，或把需求中的领域与算法名称写得更明确。</p></div>'}`;
}
function captureResearchForm(form) {
  const data = Object.fromEntries(new FormData(form));
  research.draft = {...research.draft,...data,target_papers:Number(data.target_papers),max_results:Number(data.max_results)};
}
async function postJob(url, body) {
  return api(url,{method:'POST',headers:{'Content-Type':'application/json','X-Research-Token':research.settings.csrf_token},body:JSON.stringify(body)});
}
function submissionBody(body) {
  const signature=JSON.stringify(body);
  if(research.pendingRequest?.signature!==signature)research.pendingRequest={signature,id:crypto.randomUUID()};
  return {...body,request_id:research.pendingRequest.id};
}
async function refreshResearchSettings() {
  research.settings=await api('/api/settings');
  if(research.draft&&!research.settings.models.some(m=>m.alias===research.draft.flash_model))research.draft.flash_model=research.settings.default_model||research.settings.models[0]?.alias||'';
}
function showResearchError(message) {
  research.error=message;
  if ($('#research-error')) $('#research-error').innerHTML=`<p class="form-error">${esc(message)}</p>`;
  notify(message);
}
async function loadSearchResults(id, scroll = true) {
  const data = await api(`/api/runs/${id}`);
  research.selected=id; research.candidates=data.candidates;
  if ($('#research-candidates')) {
    $('#research-candidates').innerHTML=renderResearchCandidates();
    if(scroll) $('#research-candidates').scrollIntoView({behavior:'smooth',block:'start'});
  }
}
async function updateJobs() {
  if(research.polling)return;
  research.polling=true;
  try {
    const data=await api('/api/jobs');
    const oldActive=research.active, changed=JSON.stringify(data.jobs)!==JSON.stringify(research.jobs);
    research.jobs=data.jobs;research.active=data.active_id;
    if(state.route==='research') {
      if(changed&&$('#research-jobs'))$('#research-jobs').innerHTML=renderResearchJobs();
      const submit=$('#research-form button[type=submit]');if(submit)submit.disabled=!!research.active||research.submitting||!research.settings.models.length;
      if(oldActive&&!research.active) {
        const finished=jobById(oldActive);
        if(finished?.kind==='search'&&finished.status==='completed')await loadSearchResults(finished.id,false);
        else if($('#research-candidates'))$('#research-candidates').innerHTML=renderResearchCandidates();
      }
    }
  } catch(error) { if(research.active)notify('任务状态暂时无法更新；不会自动重新提交任务。'); }
  finally {research.polling=false;}
}
document.addEventListener('submit', async event=>{
  if(event.target.id!=='research-form')return;
  event.preventDefault();if(research.submitting||research.active)return;
  captureResearchForm(event.target);research.error='';research.submitting=true;
  const button=event.target.querySelector('button[type=submit]');button.disabled=true;
  try {
    const d=research.draft;
    const job=await postJob('/api/jobs/search',submissionBody({...d,date_from:d.date_from||null,date_to:d.date_to||null}));
    research.pendingRequest=null;
    research.active=job.id;research.selected=null;research.candidates=[];
    await updateJobs();research.submitting=false;render();
  } catch(error){showResearchError(error.message);await updateJobs();}
  finally {research.submitting=false;if(button.isConnected)button.disabled=!!research.active;}
});
document.addEventListener('input',event=>{
  const form=event.target.closest('#research-form');if(form)captureResearchForm(form);
});
document.addEventListener('change',event=>{
  const form=event.target.closest('#research-form');
  if(form){captureResearchForm(form);if(event.target.name==='flash_model')$('#model-availability').innerHTML=modelNote(research.settings.models.find(m=>m.alias===event.target.value));}
  if(event.target.id==='research-sort'){state.sort=event.target.value;$('#research-candidates').innerHTML=renderResearchCandidates();}
  if(event.target.id==='result-model'){research.draft.flash_model=event.target.value;const select=$('#research-form [name=flash_model]');if(select){select.value=event.target.value;$('#model-availability').innerHTML=modelNote(research.settings.models.find(m=>m.alias===event.target.value));}}
  if(event.target.id==='result-count')research.draft.target_papers=Number(event.target.value);
});
document.addEventListener('click',async event=>{
  const button=event.target.closest('button');if(!button||button.disabled)return;
  if(!button.dataset.searchResults&&!button.dataset.jobOpen&&!button.dataset.jobStop&&!button.dataset.startReading)return;
  try {
    if(button.dataset.searchResults)await loadSearchResults(button.dataset.searchResults);
    if(button.dataset.jobOpen){const job=jobById(button.dataset.jobOpen);state.index=await api('/api/runs');state.route=job?.kind==='review'?'review':job?.kind==='search'?'papers':'results';await loadRun(button.dataset.jobOpen);if(job?.kind==='search'){state.scope='candidates';render();}}
    if(button.dataset.jobStop){button.disabled=true;await postJob(`/api/jobs/${button.dataset.jobStop}/cancel`,{});await updateJobs();}
    if(button.dataset.startReading){
      if(research.submitting||research.active)return;
      const count=$('#result-count');if(!count.reportValidity())return;
      const body=submissionBody({source_run:button.dataset.startReading,flash_model:$('#result-model').value,target_papers:Number(count.value)});
      research.submitting=true;button.disabled=true;
      try{const job=await postJob('/api/jobs/read',body);research.pendingRequest=null;research.active=job.id;await updateJobs();notify('Flash 阅读任务已开始，可在此查看进度。');}
      finally{research.submitting=false;}
    }
  }catch(error){showResearchError(error.message);await updateJobs();}
  finally {if(button.isConnected&&!button.dataset.jobStop)button.disabled=!!research.active&&!!button.dataset.startReading;}
});
async function initializeResearch() {
  if(location.hash==='#research')state.route='research';
  try {research.settings=await api('/api/settings');}
  catch(error){research.settings={models:[],error:'本地服务需要重启以启用文献查询。'};}
  research.error=research.settings.error||'';
  research.draft={question:'',title:'',keywords:'',date_from:'',date_to:todayUTC(),flash_model:research.settings.default_model||research.settings.models[0]?.alias||'',target_papers:8,max_results:50};
  await updateJobs();await refresh();
  if(research.jobs[0]?.kind==='search'&&research.jobs[0].status==='completed')await loadSearchResults(research.jobs[0].id,false);
  setInterval(()=>{if(research.active||state.route==='research')updateJobs();},3000);
}
initializeResearch();
