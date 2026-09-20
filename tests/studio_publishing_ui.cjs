const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const nodes = new Map();
const context = vm.createContext({console, Date, Intl, Set,
  crypto: require('node:crypto').webcrypto,
  document: {querySelector: selector => {
    if (!nodes.has(selector)) nodes.set(selector, {innerHTML:'', showModal(){}});
    return nodes.get(selector);
  }}
});
// Render functions are tested without triggering network polling or UI events.
vm.runInContext(fs.readFileSync('static/studio.js','utf8').split("document.addEventListener('click'")[0], context);
vm.runInContext(`
state = {channels:[{id:'blues',name:'Bourbon With Blues',timezone:'UTC',upload_times:['09:00'],waveform_style:'circular'}],
  profiles:[], themes:{}, batches:[], content:[], jobs:[
    {job_id:'scheduled',title:'Scheduled song',channel_id:'blues',stage:'scheduled',metadata:{},youtube:{},publishing:{state:'scheduled',uploaded:true}},
    {job_id:'processing',title:'Processing song',channel_id:'blues',stage:'processing',metadata:{},youtube:{},publishing:{state:'processing',uploaded:true}},
    {job_id:'local',title:'Local song',channel_id:'blues',stage:'qc',metadata:{},youtube:{},publishing:{state:'not_uploaded',uploaded:false}}
  ]};
publishing();`, context);
let html = nodes.get('#main').innerHTML;
assert(html.includes('Local song')); // Status is visible even without a local video file.
assert(html.includes('yt-scheduled'));
assert(html.includes('yt-uploaded'));
assert(html.includes('Uploaded — processing'));
vm.runInContext("publishingFilter='processing'; publishing();", context);
html = nodes.get('#main').innerHTML;
assert(html.includes('Processing song'));
assert(!html.includes('Scheduled song'));
assert(!html.includes('Local song'));
vm.runInContext("active='blues'; contentDialog();", context);
assert(nodes.get('#editor-body').innerHTML.includes('GIF audio visualizer'));
assert(!nodes.get('#editor-body').innerHTML.includes('name="waveform_style"'));
assert(nodes.get('#editor-body').innerHTML.includes('name="visualizer_enabled"'));
assert(nodes.get('#editor-body').innerHTML.includes('Vintage Film'));
assert(nodes.get('#editor-body').innerHTML.includes('Sepia'));
vm.runInContext('videosDialog();', context);
assert(nodes.get('#editor-body').innerHTML.includes('id="videos-form"'));
assert(nodes.get('#editor-body').innerHTML.includes('How many videos?'));
assert(!nodes.get('#editor-body').innerHTML.includes('name="titles"'));
vm.runInContext("state.content=[{id:'new',job_id:'reserved',channel_id:'blues',title:'Preparing video 1',stage:'planned',duration_minutes:3}];publishingFilter='all';production();",context);
assert(nodes.get('#main').innerHTML.includes('Preparing video 1'));
console.log('Studio UI: badges, filtering, missing-file visibility, and style selection passed');
const clickHandlers = {};
const calls = [];
context.document.addEventListener = (event, handler) => { clickHandlers[event] = handler; };
context.location = {hash:''};
context.testApi = async (path, data) => {
  calls.push({path,data});
  if(path==='/deletion/preview') return {job_ids:['local'],files:[{path:'jobs/local/output/video.mp4'}],bytes:123,confirmation:'exact-token',message:'Generated files only'};
  if(path==='/deletion/confirm') return {deleted:['local']};
  if(path.endsWith('/qc')) return {status:'pass'};
  return {};
};
nodes.get('#editor').close = () => {};
vm.runInContext("api=testApi; refresh=async()=>{}; toast=()=>{};",context);
const source=fs.readFileSync('static/studio.js','utf8');
vm.runInContext(source.slice(source.indexOf("document.addEventListener('click'"),source.indexOf("document.addEventListener('submit'")),context);
(async()=>{
  async function click(action,id='local',op='metadata'){
    const button={dataset:{action,id,op},disabled:false};
    await clickHandlers.click({target:{closest:()=>button}});
    assert.equal(button.disabled,false);
  }
  await click('media-import');
  assert(nodes.get('#editor-body').innerHTML.includes('import-form'));
  await click('delete-job');
  assert(nodes.get('#editor-body').innerHTML.includes('jobs/local/output/video.mp4'));
  assert.equal(calls.at(-1).path,'/deletion/preview');
  await click('delete-confirm');
  assert.equal(calls.at(-1).data.confirmation,'exact-token');
  await click('delete-all');
  assert.equal(calls.at(-1).data.job_ids,'all');
  for(const [action,path] of [['job-qc','/jobs/local/qc'],['job-approve','/jobs/local/qc'],['job-regenerate','/jobs/local/retry-generation'],['job-retry','/jobs/local/retry/metadata'],['batch-retry','/batches/local/retry'],['job-publish','/publish']]){
    await click(action); assert.equal(calls.at(-1).path,path);
  }
  assert(!source.includes('thumbnail-form'));
  assert(!source.includes('Edit thumbnail'));
  console.log('Studio UI: import, exact deletion confirmation, clear all, QC, regenerate, retry, publish, and thumbnail handlers passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
