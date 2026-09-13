// Exercise the pure sorting function without launching or inspecting a browser.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const source = fs.readFileSync('src/deepseek_survey/web_assets/app.js', 'utf8');
const context = vm.createContext({state:{sort:'newest'}});
vm.runInContext(source.slice(source.indexOf('function sortPapers('),source.indexOf('function sortControl(')), context);
const papers = [
  {paper_id:'P01',published:'2023-03-01'},
  {paper_id:'P02',published:null},
  {paper_id:'P03',published:'2025-02-01'},
  {paper_id:'P04',published:'bad date'},
  {paper_id:'P05',published:'2025-01-01'}
];
assert.deepEqual(Array.from(context.sortPapers(papers).map(p=>p.paper_id)), ['P03','P05','P01','P02','P04']);
assert.deepEqual(Array.from(context.sortPapers(papers,'oldest').map(p=>p.paper_id)), ['P01','P05','P03','P02','P04']);
assert.deepEqual(papers.map(p=>p.paper_id), ['P01','P02','P03','P04','P05']);
console.log('Publication date sorting: passed, unknown dates last, citation IDs unchanged.');
