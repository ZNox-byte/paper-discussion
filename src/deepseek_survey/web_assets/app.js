"use strict";
const $ = (s, root = document) => root.querySelector(s);
const state = { index: null, run: null, route: 'results', tab: 'read', version: '', query: '', category: '', source: '', scope: 'current', compare: new Set(), drawer: null, cumulative: null };
const icons = {
  book: '<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20M6.5 3H20v19H6.5A2.5 2.5 0 0 1 4 19.5v-14A2.5 2.5 0 0 1 6.5 3Z"/>',
  grid: '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
  check: '<path d="m9 12 2 2 4-4M12 3l8 3v6c0 5-8 9-8 9s-8-4-8-9V6z"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  search: '<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/>',
  arrow: '<path d="M5 12h14m-5-5 5 5-5 5"/>',
  external: '<path d="M14 3h7v7m0-7L10 14M10 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-5"/>',
  close: '<path d="m6 6 12 12M6 18 18 6"/>',
  refresh: '<path d="M20 7v5h-5M4 17v-5h5M6 7a7 7 0 0 1 12-2l2 7M4 12l2 7a7 7 0 0 0 12-2"/>',
  download: '<path d="M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5"/>',
  file: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8zM14 2v6h6M8 13h8M8 17h5"/>',
  layers: '<path d="m12 3 10 5-10 5L2 8zM2 12l10 5 10-5M2 16l10 5 10-5"/>',
  compare: '<path d="M9 3H3v18h6M15 3h6v18h-6M8 12h8m-3-3 3 3-3 3"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7h.01"/>',
  chevron: '<path d="m9 5 7 7-7 7"/>',
  menu: '<path d="M4 6h16M4 12h16M4 18h16"/>'
};
const icon = name => `<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.65" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${icons[name] || icons.file}</svg>`;
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const num = value => Number.isFinite(value) ? value.toLocaleString('zh-CN') : '未记录';
const safeUrl = value => /^https?:\/\//i.test(value || '') ? esc(value) : '#';
const date = value => { if (!value) return '时间未记录'; const d = new Date(value); return Number.isNaN(d.getTime()) ? '时间未记录' : d.toLocaleDateString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit' }); };
const runDate = id => /^\d{8}T/.test(id) ? `${id.slice(0, 4)}.${id.slice(4, 6)}.${id.slice(6, 8)} · ${id.slice(9, 11)}:${id.slice(11, 13)} UTC` : id;
const reviewLabels = { approved: '已批准', legacy_completed: '历史已审阅', stale: '批准已失效', needs_revision: '待修订', insufficient_evidence: '证据待补充', awaiting_review: '等待终审', unreviewed: '尚未终审' };
const runLabels = { completed: '已完成', failed: '运行未完成', running: '记录为进行中', interrupted: '已中断', discovered: '候选材料', awaiting_review: '等待终审', awaiting_codex_review: '等待终审', needs_revision: '待修订', insufficient_evidence: '证据待补充' };
const categoryColors = ['#317d83', '#526c9c', '#ae8050', '#697754', '#856499', '#a86f74', '#5b8c86', '#9b9256'];
const notify = text => { $('#toast').textContent = text; $('#toast').classList.add('visible'); clearTimeout(window.toastTimer); window.toastTimer = setTimeout(() => $('#toast').classList.remove('visible'), 3300); };

function inline(text, runId = state.run?.id || '') {
  const input = String(text ?? '');
  const pattern = /`([^`]+)`|\*\*([^*]+)\*\*|\*([^*]+)\*|\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)|\[(P\d+)\]/g;
  let html = '', position = 0;
  for (const match of input.matchAll(pattern)) {
    html += esc(input.slice(position, match.index));
    if (match[1]) html += `<code>${esc(match[1])}</code>`;
    else if (match[2]) html += `<strong>${esc(match[2])}</strong>`;
    else if (match[3]) html += `<em>${esc(match[3])}</em>`;
    else if (match[4]) html += `<a href="${safeUrl(match[5])}" target="_blank" rel="noopener noreferrer">${esc(match[4])}</a>`;
    else html += `<button class="citation" data-paper="${match[6]}" data-run="${esc(runId)}" title="查看论文 ${match[6]}">${match[6]}</button>`;
    position = match.index + match[0].length;
  }
  return html + esc(input.slice(position));
}

function markdown(text, { title = false, prefix = 'section' } = {}) {
  const lines = (text || '').replace(/\r/g, '').split('\n');
  let html = '', paragraph = [], list = false, code = false, buffer = [], heading = 0;
  const toc = [];
  const flush = () => { if (paragraph.length) html += `<p>${inline(paragraph.join(' '))}</p>`; paragraph = []; if (list) { html += '</ul>'; list = false; } };
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (/^```/.test(line)) { flush(); if (code) { html += `<pre><code>${esc(buffer.join('\n'))}</code></pre>`; buffer = []; } code = !code; continue; }
    if (code) { buffer.push(line); continue; }
    const h = /^(#{1,6})\s+(.+)$/.exec(line);
    if (h) { flush(); if (h[1].length === 1 && !title) continue; const id = `${prefix}-${heading++}`; const level = Math.min(h[1].length, 5); html += `<h${level} id="${id}">${inline(h[2])}</h${level}>`; if (level === 2) toc.push({ id, text: h[2] }); continue; }
    if (line.startsWith('|') && /^\|[\s:|\-]+\|?\s*$/.test(lines[i + 1] || '')) {
      flush(); const cells = row => row.trim().replace(/^\||\|$/g, '').split('|').map(s => s.trim());
      html += `<div class="table-scroll"><table><thead><tr>${cells(line).map(c => `<th>${inline(c)}</th>`).join('')}</tr></thead><tbody>`; i++;
      while ((lines[i + 1] || '').startsWith('|')) { i++; html += `<tr>${cells(lines[i]).map(c => `<td>${inline(c)}</td>`).join('')}</tr>`; } html += '</tbody></table></div>'; continue;
    }
    if (/^>\s?/.test(line)) { flush(); html += `<blockquote>${inline(line.replace(/^>\s?/, ''))}</blockquote>`; continue; }
    if (/^\s*[-*]\s+/.test(line) || /^\d+\.\s/.test(line)) {
      if (paragraph.length) { html += `<p>${inline(paragraph.join(' '))}</p>`; paragraph = []; }
      if (!list) { html += '<ul>'; list = true; } html += `<li>${inline(line.replace(/^\s*(?:[-*]|\d+\.)\s+/, ''))}</li>`; continue;
    }
    if (!line.trim()) flush(); else paragraph.push(line);
  }
  flush(); if (buffer.length) html += `<pre>${esc(buffer.join('\n'))}</pre>`;
  return { html, toc };
}

async function api(url) { const response = await fetch(url); const data = await response.json(); if (!response.ok) throw new Error(data.error || '无法读取研究记录'); return data; }
let runRequest = 0;
async function loadRun(id) {
  const request = ++runRequest;
  try {
    $('#app').setAttribute('aria-busy', 'true');
    const run = await api(`/api/runs/${encodeURIComponent(id)}`);
    if (request !== runRequest) return false;
    state.run = run;
    state.version = state.run.reports.final ? 'final' : Object.keys(state.run.reports)[0] || '';
    state.query = ''; state.category = ''; state.source = ''; state.compare.clear(); state.cumulative = null; state.scope = 'current';
    closeOverlay(false); render(); return true;
  } catch (error) { if (request !== runRequest) return false; notify(error.message); if (!state.run) $('#app').innerHTML = `<div class="boot"><h1>暂时无法读取</h1><p>${esc(error.message)}</p><button data-action="refresh" class="button">重新读取</button></div>`; }
  finally { if (request === runRequest) $('#app').removeAttribute('aria-busy'); }
}
async function refresh() { try { state.index = await api('/api/runs'); if (!state.index.runs.length) { $('#app').innerHTML = '<div class="boot"><span class="brand-mark">P</span><h1>还没有研究记录</h1><p>在项目 runs 目录中生成或放入研究产物，再刷新页面。</p><button data-action="refresh" class="button">重新读取</button></div>'; return; } return await loadRun(state.index.runs.some(r => r.id === state.run?.id) ? state.run.id : state.index.default_run); } catch (error) { $('#app').innerHTML = `<div class="boot"><h1>连接暂时中断</h1><p>${esc(error.message)}</p><button data-action="refresh" class="button">重新连接</button></div>`; } }
function statusTag(status) { return `<span class="status ${status === 'approved' ? 'good' : ['stale', 'needs_revision', 'insufficient_evidence'].includes(status) ? 'warning' : 'neutral'}">${esc(reviewLabels[status] || runLabels[status] || status)}</span>`; }
function sourceLabel(p) { return p.source === 'abstract' ? (p.has_source ? '仅摘要 · 已保存' : '仅摘要') : p.has_source ? (p.sampled ? '全文已存 · 阅读有截断' : '原文已保存') : p.source === 'pdf' ? '历史 PDF · 无文本存档' : '来源未记录'; }

function render() {
  if (!state.run) return;
  const r = state.run, valid = r.papers.filter(p => p.result && Object.keys(p.result).length).length;
  const titles = [...new Set(state.index.runs.map(item => item.title))];
  const nav = [['results', 'book', '研究结果'], ['papers', 'grid', '论文库'], ['review', 'check', '审阅与问题'], ['runs', 'clock', '运行记录']];
  const sections = { results: '研究结果', papers: '论文库', review: '审阅与问题', runs: '运行记录' };
  $('#app').innerHTML = `<aside class="sidebar" aria-label="主导航"><a class="brand" href="#" data-action="home"><span class="brand-mark">P<span>·</span></span><span>Paper Atlas<small>论文研究工作台</small></span></a><div class="sidebar-label">工作空间</div><nav>${nav.map(([route, name, label]) => `<button data-route="${route}" class="nav-item ${state.route === route ? 'active' : ''}" ${state.route === route ? 'aria-current="page"' : ''}>${icon(name)}<span>${label}</span>${route === 'papers' ? `<span class="nav-count">${r.papers.length}</span>` : ''}</button>`).join('')}</nav><div class="sidebar-bottom"><span class="local-icon">${icon(layersIcon())}</span><div>本地研究库<small>只读浏览 · v0.1</small></div></div></aside>
  <div class="app-body"><header class="topbar"><div class="breadcrumb">工作空间 ${icon('chevron')} <span>${sections[state.route]}</span></div><div class="top-actions"><span class="sync-label">${new Date(r.read_at).toLocaleTimeString('zh-CN', {hour:'2-digit',minute:'2-digit'})} 更新</span><button class="icon-button" data-action="refresh" title="刷新本地记录" aria-label="刷新本地记录">${icon('refresh')}</button><span class="avatar" aria-label="本地工作空间">研</span></div></header>
  <main id="main" tabindex="-1"><div class="collection-bar"><span class="eyebrow">RESEARCH COLLECTION</span><div class="selectors">${titles.length > 1 ? `<select id="project-select" aria-label="研究主题">${titles.map(t => `<option ${t === r.title ? 'selected' : ''} value="${esc(t)}">${esc(t)}</option>`).join('')}</select>` : ''}<select id="run-select" aria-label="运行记录">${state.index.runs.filter(item => item.title === r.title).map(item => `<option value="${item.id}" ${item.id === r.id ? 'selected' : ''}>${item.round ? `第 ${item.round} 轮 · ` : ''}${runDate(item.id)}</option>`).join('')}</select></div></div>
  <section class="page-heading"><div><h1>${esc(r.title.replace(/论文综述$/, '').trim())}</h1><div class="heading-meta">${statusTag(r.review_state)}<span>${r.round ? `第 ${r.round} 轮研究` : r.papers.length ? '轮次未记录' : '候选资料'}<span class="meta-dot">·</span>${valid}${r.target ? ` / ${r.target}` : ''} 篇阅读结果</span><span class="meta-separator"></span><span>审阅者 ${esc(r.reviewer)}</span></div></div><button class="button secondary" data-action="export">${icon('download')} 导出结果</button></section>
  <div id="page-content">${state.route === 'results' ? renderResults() : state.route === 'papers' ? renderPapers() : state.route === 'review' ? renderReview() : renderRuns()}</div></main><footer>Paper Atlas<span>本地资料 · 依据原始研究记录呈现</span></footer></div>`;
  if (state.route === 'results' && state.tab === 'read') observeHeadings();
}
function layersIcon() { return 'layers'; }
function renderResults() {
  const r = state.run;
  const body = state.tab === 'read' ? renderReport() : renderMap();
  return `<div class="view-tabs" role="tablist" aria-label="研究结果视图"><button role="tab" aria-selected="${state.tab === 'read'}" class="${state.tab === 'read' ? 'active' : ''}" data-tab="read">${icon('file')}综述阅读</button><button role="tab" aria-selected="${state.tab === 'map'}" class="${state.tab === 'map' ? 'active' : ''}" data-tab="map">${icon('layers')}分类与脉络</button><span class="tab-note">${Object.keys(r.categories).length} 个研究方向</span></div>${body}`;
}
function renderReport() {
  const r = state.run;
  const report = r.reports[state.version];
  if (!report) return `<section class="empty-state">${icon('book')}<h2>${r.papers.length ? '阅读材料已经在这里' : '候选论文已就绪'}</h2><p>${r.papers.length ? `已获得 ${r.papers.filter(p => p.status === 'validated').length} 份阅读卡片，当前运行尚未生成综合报告。` : `这份记录包含 ${r.candidates.length} 篇候选论文，尚未开始逐篇阅读。`}</p><button class="button" data-route="papers">查看论文库 ${icon('arrow')}</button></section>`;
  const parsed = markdown(report.text);
  const versionNote = state.version !== 'final' ? '此版本为阶段产物，请结合审阅记录阅读。' : r.review_state === 'legacy_completed' ? '历史审阅记录已完成；此版本未包含新版文件一致性验证。' : r.review_state === 'approved' ? '正文与批准记录一致。点击文中论文编号可回查已有证据。' : '这份报告的批准状态尚未确认，请先查看审阅记录。';
  return `<div class="reader-top"><div class="reading-note">${icon('info')}<span>${versionNote}</span></div><select id="version-select" aria-label="报告版本">${Object.entries(r.reports).map(([key, value]) => `<option value="${key}" ${key === state.version ? 'selected' : ''}>${esc(value.label)}</option>`).join('')}</select></div><div class="reader-layout"><aside class="toc"><div class="small-heading">本篇目录</div>${parsed.toc.map((h, i) => `<a class="${i === 0 ? 'active' : ''}" href="#${h.id}">${esc(h.text)}</a>`).join('')}<div class="toc-end"><span>${num(r.papers.length)}</span> 篇论文<br>交叉阅读 · 追溯证据</div></aside><article class="report-paper"><div class="report-kicker"><span>RESEARCH REVIEW</span><span>${runDate(r.id).split(' · ')[0]}</span></div><div class="prose">${parsed.html}</div><div class="article-end">综述正文结束<span>逐篇阅读卡片可在论文库中查阅</span><button class="button secondary" data-route="papers">进入论文库 ${icon('arrow')}</button></div></article></div>`;
}
function observeHeadings() { window.tocObserver?.disconnect(); window.tocObserver = new IntersectionObserver(entries => { const entry = entries.find(item => item.isIntersecting); if (!entry) return; document.querySelectorAll('.toc a').forEach(a => a.classList.toggle('active', a.hash === '#' + entry.target.id)); }, { rootMargin: '-10% 0px -70% 0px' }); document.querySelectorAll('.prose h2').forEach(h => window.tocObserver.observe(h)); }
function renderMap() {
  const r = state.run, entries = Object.entries(r.categories).sort((a,b) => b[1]-a[1]);
  const max = Math.max(...entries.map(e => e[1]), 1);
  const groups = {};
  r.papers.forEach(p => { const year = p.published?.slice(0,4) || '年份未记录'; (groups[year] ||= []).push(p); });
  return `<div class="map-grid"><section class="panel category-panel"><div class="section-title"><div><span class="eyebrow">RESEARCH AREAS</span><h2>研究方向分布</h2></div><span class="subtle">${r.papers.filter(p => p.status === 'validated').length} 篇</span></div><p class="muted">${r.review_state === 'approved' ? '按终审确认的唯一主分类展示。' : r.review_state === 'legacy_completed' ? '按历史记录中的主分类展示。' : '当前为阅读阶段的暂定分类。'}</p><div class="category-bars">${entries.map(([c,n],i) => `<button class="category-bar" data-category-open="${esc(c)}"><span class="bar-title"><span>${esc(c)}</span><b>${n}</b></span><meter class="category-meter color-${i%8}" min="0" max="${max}" value="${n}" aria-label="${esc(c)} ${n} 篇">${n}</meter></button>`).join('')}</div></section><section class="panel timeline-panel"><div class="section-title"><div><span class="eyebrow">PUBLICATION TIMELINE</span><h2>论文发表时间轴</h2></div>${icon('clock')}</div><p class="muted">时间先后不代表技术继承。当前没有经终审确认的结构化关系图。</p><div class="timeline">${Object.entries(groups).sort(([a],[b])=>a.localeCompare(b)).map(([year,papers])=>`<div class="year-group"><div class="year-label">${esc(year)}<span>${papers.length} 篇</span></div><div class="year-papers">${papers.map(p=>`<button data-paper="${p.task_id}" class="timeline-paper"><span class="paper-id">${p.task_id}</span><span>${esc(p.title)}</span>${icon('chevron')}</button>`).join('')}</div></div>`).join('')}</div></section></div>`;
}

function filteredPapers() {
  const list = state.scope === 'all' && state.cumulative ? state.cumulative : state.run.papers;
  const q = state.query.toLocaleLowerCase();
  return list.filter(p => (!state.category || p.category === state.category) && (!state.source || (state.source === 'saved' ? p.has_source : state.source === 'abstract' ? p.source === 'abstract' : p.status !== 'validated')) && (!q || [p.title, (p.authors||[]).join(' '), p.result.research_question, p.result.methodology, p.task_id].join(' ').toLocaleLowerCase().includes(q)));
}
function renderPapers() {
  const candidates = state.scope === 'candidates';
  const cats = [...new Set((state.cumulative && state.scope === 'all' ? state.cumulative : state.run.papers).map(p=>p.category))];
  return `<div class="library-toolbar"><div class="scope-tabs"><button data-scope="current" class="${state.scope==='current'?'active':''}">本轮论文 <span>${state.run.papers.length}</span></button><button data-scope="all" class="${state.scope==='all'?'active':''}">累计论文</button><button data-scope="candidates" class="${candidates?'active':''}">候选记录 <span>${state.run.candidates.length}</span></button></div><div class="filter-row"><label class="search-box">${icon('search')}<input id="paper-search" type="search" placeholder="搜索标题、作者、研究问题…" aria-label="搜索论文" value="${esc(state.query)}"></label><select id="category-filter" aria-label="分类筛选" ${candidates?'disabled':''}><option value="">全部分类</option>${cats.map(c=>`<option ${c===state.category?'selected':''}>${esc(c)}</option>`).join('')}</select><select id="source-filter" aria-label="状态筛选" ${candidates?'disabled':''}><option value="">全部状态</option><option value="saved" ${state.source==='saved'?'selected':''}>有原文存档</option><option value="abstract" ${state.source==='abstract'?'selected':''}>仅摘要</option><option value="failed" ${state.source==='failed'?'selected':''}>无有效阅读结果</option></select></div></div><div id="paper-results">${renderPaperRows()}</div><div id="compare-tray">${renderCompareTray()}</div>`;
}
function renderPaperRows() {
  if (state.scope === 'candidates') {
    const list = state.run.candidates.filter(p => !state.query || [p.title,p.abstract].join(' ').toLowerCase().includes(state.query.toLowerCase()));
    return `<div class="list-summary">${list.length} 篇候选论文<span>保留筛选记录，不将未入选解释为低质量</span></div><div class="paper-list">${list.map(p=>`<article class="candidate-row"><div><span class="tag">${({selected:'已入选',deferred:'待定',unselected:'未入选',unscreened:'尚未筛选'})[p.disposition]}</span><h3><a href="${safeUrl(p.url)}" target="_blank" rel="noopener noreferrer">${esc(p.title)} ${icon('external')}</a></h3><p class="muted">${p.rationale ? esc(p.rationale) : p.disposition==='unselected' ? '历史记录未提供逐篇排除理由。' : date(p.published)}</p><details><summary>查看摘要</summary><p>${esc(p.abstract || '摘要未记录')}</p></details></div></article>`).join('') || '<div class="empty-state"><h3>没有匹配的候选论文</h3></div>'}</div>`;
  }
  const papers = filteredPapers();
  return `<div class="list-summary">${papers.length} 篇论文<span>勾选 2–4 篇，按相同维度进行对照</span></div><div class="paper-list">${papers.map(p=>`<article class="paper-row"><label class="paper-check"><input type="checkbox" data-compare="${esc(p.key)}" aria-label="选择 ${esc(p.title)} 进行比较" ${state.compare.has(p.key)?'checked':''} ${p.status!=='validated'?'disabled':''}></label><span class="paper-id large">${esc(p.task_id)}</span><div class="paper-info"><div class="paper-tags"><span class="category-label">${esc(p.category)}</span><span>${p.published?.slice(0,4)||'年份未记录'}</span>${state.scope==='all'?`<span>${runDate(p.run_id)}</span>`:''}</div><button class="paper-title" data-paper="${p.task_id}" data-run="${p.run_id}">${esc(p.title)}</button><p>${esc(p.result.one_sentence_summary || '此论文尚无通过校验的阅读结果。')}</p><div class="paper-meta"><span>${icon('file')}${sourceLabel(p)}</span><span>${(p.result.evidence||[]).length} 条引文</span><span class="${p.status==='validated'?'validated-label':'warning-text'}">${p.status==='validated'?'阅读卡片已生成':'阅读未完成'}</span></div></div><button class="row-open icon-button" data-paper="${p.task_id}" data-run="${p.run_id}" aria-label="查看 ${esc(p.title)}">${icon('arrow')}</button></article>`).join('') || `<div class="empty-state">${icon('search')}<h3>没有匹配的论文</h3><p>试试其他关键词，或清除筛选条件。</p><button class="button secondary" data-action="clear-filters">清除筛选</button></div>`}</div>`;
}
function renderCompareTray() { return state.compare.size ? `<div class="compare-tray"><span>${icon('compare')} 已选 <b>${state.compare.size}</b> 篇论文</span><div><button class="text-button" data-action="clear-compare">清空</button><button class="button" data-action="compare" ${state.compare.size < 2 ? 'disabled':''}>并排比较 ${icon('arrow')}</button></div></div>` : ''; }
function renderReview() {
  const r = state.run, d = r.decision;
  const issues = [...(d.unresolved_issues||[]).map(v=>({title:typeof v==='string'?v:JSON.stringify(v), type:'待解决'})), ...(d.coverage_gaps||[]).map(v=>({title:typeof v==='string'?v:JSON.stringify(v),type:'覆盖缺口'})), ...(d.reread_requests||[]).map(v=>({title:v.question||'需要补读', detail:v.reason, task:v.task_id,type:'补读请求'}))];
  return `<div class="review-summary panel"><div class="review-symbol">${icon('check')}</div><div><span class="eyebrow">REVIEW STATUS</span><h2>${esc(reviewLabels[r.review_state]||'审阅状态未记录')}</h2><p>${r.review_state==='legacy_completed'?'已保存历史审阅意见。该轮没有新版的正文与证据包哈希验证。':r.review_state==='approved'?'批准决定、引用覆盖及正文和证据包的一致性检查通过。':r.approval_error || (r.review_mode==='external'?'当前采用外部审阅方式，等待审阅者返回综合结果或处理意见。':'依据审阅决定处理证据缺口，再进入最终定稿。')}</p></div><div class="review-owner"><span>本轮审阅者</span><strong>${esc(r.reviewer)}</strong><small>${r.review_mode==='external'?'外部审阅':'API 审阅'}</small></div></div><div class="review-grid"><section class="panel review-record"><div class="section-title"><h2>审阅记录</h2><span class="subtle">依据与修订决定</span></div><div class="prose compact">${r.review_record ? markdown(r.review_record, {prefix:'review'}).html : '<div class="empty-state"><h3>还没有审阅记录</h3><p>阅读结果已保留，可先在论文库中查看证据。</p></div>'}</div></section><aside class="review-aside"><section class="panel"><div class="section-title"><h2>待处理问题</h2><span class="count-pill">${issues.length}</span></div>${issues.map(issue=>`<div class="issue"><span class="tag amber">${issue.type}</span>${issue.task?`<button class="citation" data-paper="${esc(issue.task)}">${esc(issue.task)}</button>`:''}<p>${esc(issue.title)}</p>${issue.detail?`<small>${esc(issue.detail)}</small>`:''}</div>`).join('')||`<div class="quiet-empty">${icon('check')}<p>没有结构化的待处理问题</p><small>${r.review_state==='legacy_completed'?'历史细节请以左侧审阅记录为准。':'这不代表报告已经获得批准。'}</small></div>`}${issues.length?'<button class="button secondary full" data-action="copy-issues">复制问题清单</button>':''}</section><section class="note-card"><h3>阅读时留意</h3><p>引句匹配只说明文字存在于提供的原文中。实验条件、因果关系与结论仍需要审阅者判断。</p>${r.has_bundle?`<button class="text-link" data-action="export-bundle">导出审查材料 ${icon('arrow')}</button>`:''}</section></aside></div>`;
}
function renderRuns() {
  const r = state.run;
  return `<div class="runs-layout"><section class="panel"><div class="section-title"><div><span class="eyebrow">RESEARCH HISTORY</span><h2>研究运行记录</h2></div><span class="subtle">${state.index.runs.length} 条记录</span></div><div class="run-list">${state.index.runs.map(item=>`<button class="run-row ${item.id===r.id?'selected':''}" data-run-open="${item.id}"><span class="run-icon">${icon(item.has_final?'check':'clock')}</span><span class="run-info"><strong>${esc(item.title)}</strong><small>${runDate(item.id)}${item.round?` · 第 ${item.round} 轮`:''}</small></span><span class="run-numbers">${item.validated==null?'—':`${item.validated}${item.target?'/'+item.target:''}`}<small>有效阅读</small></span><span class="tag">${esc(runLabels[item.status]||item.status)}</span>${icon('chevron')}</button>`).join('')}</div></section><div class="runs-detail-grid"><section class="panel"><div class="section-title"><h2>已记录用量</h2><span class="subtle">${runDate(r.id).split(' · ')[0]}</span></div><p class="muted">${r.usage_complete?'包含预算结算记录；未知用量保留保守估算。':'历史调用记录可能不完整，下方数值不代表整轮总消耗。'}</p>${r.usage.length?`<div class="table-scroll"><table class="usage-table"><thead><tr><th>模型</th><th>已记录请求</th><th>已报告 token</th></tr></thead><tbody>${r.usage.map(u=>`<tr><td>${esc(u.model)}</td><td>${num(u.requests)}</td><td>${num(u.tokens)}${u.unknown?`<small>另 ${u.unknown} 条用量未知</small>`:''}</td></tr>`).join('')}</tbody></table></div>`:'<div class="quiet-empty"><p>该运行没有保存用量记录</p></div>'}${r.budget.max_total_tokens?`<div class="budget-line"><span>预算已计入 / token 上限</span><strong>${num(r.budget.charged_tokens)} / ${num(r.budget.max_total_tokens)}</strong></div>`:''}</section><section class="panel"><div class="section-title"><h2>阅读与来源</h2>${icon('file')}</div><div class="source-stat"><span>有有效阅读卡片</span><b>${r.papers.filter(p=>p.status==='validated').length}<small> / ${r.target || '—'}</small></b></div><div class="source-stat"><span>可回查本地全文</span><b>${r.papers.filter(p=>p.has_source&&p.source!=='abstract').length}</b></div><div class="source-stat"><span>失败任务记录</span><b>${r.failures.length}</b></div><p class="muted">此页面展示最近读取到的产物状态，不代表任务服务仍在运行。</p>${r.failures.length?`<details class="failures"><summary>查看 ${r.failures.length} 条失败记录</summary>${r.failures.map(f=>`<p>${esc(typeof f==='string'?f:JSON.stringify(f))}</p>`).join('')}</details>`:''}</section></div></div>`;
}

let previousFocus = null;
function showOverlay(html, kind = 'drawer') {
  previousFocus = document.activeElement;
  $('#overlay-root').innerHTML = `<div class="overlay" data-dismiss="true"><section class="${kind}" role="dialog" aria-modal="true" aria-labelledby="dialog-title" tabindex="-1">${html}</section></div>`;
  document.body.classList.add('overlay-open');
  $('.'+kind).focus();
}
function closeOverlay(restore = true) { $('#overlay-root').innerHTML = ''; document.body.classList.remove('overlay-open'); state.drawer = null; if (restore && previousFocus?.isConnected) previousFocus.focus(); }
async function openPaper(task, runId = state.run.id) {
  let p = (state.cumulative || []).find(p=>p.run_id===runId&&p.task_id===task) || state.run.papers.find(p=>p.run_id===runId&&p.task_id===task);
  if (!p) { notify('这份记录中没有该论文的阅读卡片。'); return; }
  state.drawer = p;
  const r = p.result, list = items => (items||[]).length ? `<ul>${items.map(s=>`<li>${inline(s,p.run_id)}</li>`).join('')}</ul>` : '<p class="muted">未记录</p>';
  showOverlay(`<div class="drawer-top"><span class="eyebrow">PAPER NOTES <span class="paper-id">${p.task_id}</span></span><button class="icon-button" data-action="close" aria-label="关闭论文详情">${icon('close')}</button></div><div class="drawer-body"><div class="paper-tags"><span class="tag">${esc(p.category)}</span><span>${date(p.published)}</span></div><h2 id="dialog-title">${esc(p.title)}</h2><p class="authors">${esc((p.authors||[]).join(' · '))}</p><div class="drawer-links">${p.url?`<a class="button secondary" href="${safeUrl(p.url)}" target="_blank" rel="noopener noreferrer">论文原文 ${icon('external')}</a>`:''}${p.pdf_url?`<a class="text-link" href="${safeUrl(p.pdf_url)}" target="_blank" rel="noopener noreferrer">PDF ${icon('external')}</a>`:''}</div><div class="paper-summary">${esc(r.one_sentence_summary||p.abstract||'尚无阅读结果')}</div><div class="detail-section"><h3>研究问题</h3><p>${inline(r.research_question||'未记录',p.run_id)}</p></div><div class="detail-section"><h3>方法与贡献</h3><p>${inline(r.methodology||'未记录',p.run_id)}</p>${list(r.main_contributions)}</div><div class="detail-section"><h3>实验设置</h3><p>${inline(r.experimental_setup||'未记录',p.run_id)}</p></div><div class="detail-section"><h3>关键发现</h3>${list(r.key_findings)}</div><div class="detail-section"><h3>局限与代价</h3>${list(r.limitations)}</div><div class="detail-section evidence-section"><div class="section-title"><h3>该论文的原文证据</h3><span class="count-pill">${(r.evidence||[]).length}</span></div><p class="muted">以下为阅读卡片保存的证据，不表示与报告每一句话都已逐条绑定。</p>${(r.evidence||[]).map((e,i)=>{const c=p.evidence_context[i];return `<div class="evidence-card"><div class="evidence-index">E${String(i+1).padStart(2,'0')}<span>${e.page?`论文 p. ${e.page}`:'页码未记录'}</span></div><h4>${esc(e.claim)}</h4><blockquote lang="en">${esc(e.quote)}</blockquote>${c?.context?`<details><summary>展开原文上下文</summary><p class="source-excerpt">${esc(c.context)}</p>${c.warning?`<p class="warning-text">${esc(c.warning)}</p>`:''}</details>`:''}</div>`;}).join('')||'<p class="muted">尚无已保存的引文。</p>'}${p.has_source?`<button class="button secondary full" data-action="source">${p.source==='abstract'?'查看已保存摘要':'查看已保存的提取文本'}</button>`:'<div class="inline-note">历史记录未保存原文上下文。可查看现有引句或打开论文原文。</div>'}<div id="source-view"></div></div><details class="provenance-details"><summary>来源与阅读记录</summary><p>${sourceLabel(p)}</p><p>阅读模型：${esc(p.producer.response_model||p.producer.model||'历史未记录')}</p><p>所属运行：${esc(runDate(p.run_id))}</p>${p.warnings.map(w=>`<p>${esc(w)}</p>`).join('')}${r.confidence!=null?`<p>模型自评：${esc(r.confidence)}（不是事实正确率）</p>`:''}</details></div>`);
  state.drawer = p;
}
function openCompare() {
  const collection = [...state.run.papers, ...(state.cumulative||[])];
  const papers = [...state.compare].map(key=>collection.find(p=>p.key===key)).filter(Boolean);
  if (papers.length<2) return;
  const rows = [['研究问题','research_question'],['核心机制','methodology'],['实验设置','experimental_setup'],['关键发现','key_findings'],['代价与局限','limitations']];
  showOverlay(`<div class="modal-heading"><div><span class="eyebrow">SIDE BY SIDE</span><h2 id="dialog-title">论文并排比较</h2></div><button class="icon-button" data-action="close" aria-label="关闭比较">${icon('close')}</button></div><p class="comparison-note">实验条件不同的结果不能直接排名。所有内容沿用各论文已保存的阅读卡片。</p><div class="comparison-scroll"><table class="comparison-table"><thead><tr><th>比较维度</th>${papers.map(p=>`<th><span class="paper-id">${p.task_id}</span><h3>${esc(p.title)}</h3><small>${esc(p.category)}</small></th>`).join('')}</tr></thead><tbody>${rows.map(([label,key])=>`<tr><th>${label}</th>${papers.map(p=>`<td>${Array.isArray(p.result[key])?`<ul>${p.result[key].map(s=>`<li>${inline(s,p.run_id)}</li>`).join('')}</ul>`:inline(p.result[key]||'未记录',p.run_id)}</td>`).join('')}</tr>`).join('')}<tr><th>证据</th>${papers.map(p=>`<td>${(p.result.evidence||[]).map(e=>`<blockquote>${esc(e.quote)}<small>${e.page?`p. ${e.page}`:'页码未记录'}</small></blockquote>`).join('')}</td>`).join('')}</tr></tbody></table></div>`, 'compare-modal');
}
function openExport() { const reports=Object.entries(state.run.reports); showOverlay(`<div class="modal-heading"><div><span class="eyebrow">EXPORT</span><h2 id="dialog-title">导出研究结果</h2></div><button class="icon-button" data-action="close" aria-label="关闭导出">${icon('close')}</button></div><p class="muted">下载本轮报告或审查材料。新版获批正文导出与当前展示一致，阅读卡片可单独导出。</p><div class="export-options">${reports.map(([key,value])=>`<a href="/api/download?run=${encodeURIComponent(state.run.id)}&kind=${key}" class="export-row" download>${icon('file')}<span>${esc(value.label)}<small>Markdown 文档</small></span>${icon('download')}</a>`).join('')}${state.run.has_bundle?`<a class="export-row" href="/api/download?run=${encodeURIComponent(state.run.id)}&kind=bundle" download>${icon('layers')}<span>审查材料<small>证据与阅读卡片 · JSON</small></span>${icon('download')}</a>`:reports.length?'':'<p class="muted">此运行尚未生成可导出的报告或审查包。</p>'}</div>`, 'small-modal'); }

document.addEventListener('click', async event => {
  const target = event.target.closest('button,a,[data-dismiss]'); if (!target) return;
  if (target.dataset.dismiss && event.target===target) { closeOverlay(); return; }
  if (target.dataset.paper) { event.preventDefault(); return openPaper(target.dataset.paper, target.dataset.run||state.run.id); }
  if (target.dataset.route) { state.route=target.dataset.route; state.compare.clear(); render(); window.scrollTo({top:0}); return; }
  if (target.dataset.tab) { state.tab=target.dataset.tab; render(); return; }
  if (target.dataset.runOpen) return loadRun(target.dataset.runOpen);
  if (target.dataset.categoryOpen) { state.category=target.dataset.categoryOpen; state.route='papers'; state.scope='current'; render(); return; }
  if (target.dataset.scope) {
    state.scope=target.dataset.scope; state.category='';state.source='';state.query='';state.compare.clear();
    if (state.scope==='all'&&!state.cumulative) {
      notify('正在整理同一研究主题下的论文…');
      const originRun=state.run.id;
      try { const runs=await Promise.all(state.index.runs.filter(r=>r.title===state.run.title).map(r=>api(`/api/runs/${r.id}`))); if(state.run.id!==originRun||state.scope!=='all')return; const unique=new Map(); runs.forEach(r=>r.papers.forEach(p=>{const key=p.paper_id||p.title; if(!unique.has(key)||(!Object.keys(unique.get(key).result).length&&Object.keys(p.result).length)) unique.set(key,p);}));state.cumulative=[...unique.values()]; } catch(error){notify(error.message);state.scope='current';}
    }
    render();return;
  }
  switch(target.dataset.action) {
    case 'home': event.preventDefault(); state.route='results'; render(); break;
    case 'refresh': if (await refresh()) notify('已重新读取本地研究记录'); break;
    case 'close': closeOverlay(); break;
    case 'export': openExport(); break;
    case 'export-bundle': window.location.href=`/api/download?run=${state.run.id}&kind=bundle`; break;
    case 'clear-filters': state.query='';state.category='';state.source='';render();break;
    case 'clear-compare': state.compare.clear(); $('#paper-results').innerHTML=renderPaperRows();$('#compare-tray').innerHTML=''; break;
    case 'compare': openCompare();break;
    case 'source': {
      if(!state.drawer)return; const p=state.drawer; target.disabled=true;
      try { const source=await api(`/api/runs/${p.run_id}/source/${p.task_id}`); if(state.drawer?.key!==p.key)return; $('#source-view').innerHTML=`<details open><summary>${p.source==='abstract'?'已保存摘要':'已保存的提取文本'}</summary><pre class="source-full">${esc(source.text||'未找到原文存档')}</pre></details>`; } catch(error){notify(error.message);} finally {target.disabled=false;} break;
    }
    case 'copy-issues': {
      const text=JSON.stringify(state.run.decision,null,2); try{await navigator.clipboard.writeText(text);notify('问题清单已复制');}catch{notify('浏览器未允许复制，请从审查材料中查看。');}break;
    }
  }
});
document.addEventListener('change', event => {
  const target=event.target;
  if(target.id==='run-select') return loadRun(target.value);
  if(target.id==='project-select') return loadRun(state.index.runs.find(r=>r.title===target.value&&r.has_final)?.id||state.index.runs.find(r=>r.title===target.value).id);
  if(target.id==='version-select'){state.version=target.value;render();return;}
  if(target.id==='category-filter'||target.id==='source-filter'){state[target.id==='category-filter'?'category':'source']=target.value;$('#paper-results').innerHTML=renderPaperRows();return;}
  if(target.dataset.compare){if(target.checked&&state.compare.size>=4){target.checked=false;notify('最多选择 4 篇论文进行比较');return;} target.checked?state.compare.add(target.dataset.compare):state.compare.delete(target.dataset.compare);$('#compare-tray').innerHTML=renderCompareTray();}
});
document.addEventListener('input', event=>{if(event.target.id==='paper-search'){state.query=event.target.value;$('#paper-results').innerHTML=renderPaperRows();}});
document.addEventListener('keydown', event=>{
  if(event.key==='Escape') closeOverlay();
  if(event.key==='Tab'&&$('.overlay')) {const items=[...$('.overlay').querySelectorAll('a[href],button:not(:disabled),input,select,summary,[tabindex="0"]')];if(!items.length)return;const first=items[0],last=items[items.length-1];if(event.shiftKey&&(document.activeElement===first||document.activeElement.matches('[role="dialog"]'))){event.preventDefault();last.focus();}else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first.focus();}}
});
refresh();
