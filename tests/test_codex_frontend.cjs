const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const path = require('node:path');
const context = vm.createContext({
  console, URL, Date, Map, Set, Intl, location:{hash:''},
  document:{addEventListener(){},querySelector(){return null;}},
  window:{}, localStorage:{getItem(){return null;},setItem(){}},
  setInterval(){}, setTimeout(){}, clearTimeout(){},
  fetch(){return new Promise(()=>{});}
});
for (const name of ['app.js','research.js','codex.js']) {
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../src/deepseek_survey/web_assets',name),'utf8'), context);
}
const run = code => vm.runInContext(code,context);
run(`research.settings={models:[],reviewer:'Codex 订阅'}; research.draft={question:'研究实验设置',date_from:'',date_to:'',target_papers:8,max_results:50,keywords:''};`);
assert.match(run('renderResearch()'),/id="codex-panel"/);
assert.match(run('renderCodexPanel()'),/不需要 OpenAI API Key/);
run(`state.route='review'; state.run={id:'run-1',papers:[{status:'validated'}]};`);
assert.match(run('renderCodexPanel()'),/data-codex="review" disabled/);
run(`acceptCodexStatus({authenticated:true,models:[{id:'available-model',name:'Available',efforts:['high'],default_effort:'high'}]});`);
assert.equal(run('codexUI.model'),'gpt-6-astra');
assert.match(run('renderCodexPanel()'),/不会自动替换 Astra/);
assert.match(run('renderCodexPanel()'),/data-codex="review" disabled/);
run(`acceptCodexStatus({authenticated:true,models:[{id:'gpt-6-astra',name:'Astra',efforts:['high'],default_effort:'high'}]});`);
assert.doesNotMatch(run('renderCodexPanel()'),/data-codex="review" disabled/);
run(`research.active='review-1';research.jobs=[{id:'review-1',kind:'review',status:'running',message:'核验中'}];`);
assert.match(run('renderCodexPanel()'),/data-codex="review" disabled/);
assert.match(run('renderCodexPanel()'),/停止审阅/);
run(`codexUI.error='<img src=x onerror=alert(1)>';`);
assert.doesNotMatch(run('renderCodexPanel()'),/<img src=x/);
console.log('Subscription UI: rendering, login/model gates, no silent fallback, cancellation and escaping passed.');
