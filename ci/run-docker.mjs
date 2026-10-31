import { spawn,execFileSync } from 'node:child_process';
import { mkdir,readFile,writeFile } from 'node:fs/promises';
import { createWriteStream } from 'node:fs';
import { createHash,randomBytes } from 'node:crypto';
import { resolve } from 'node:path';
import assert from 'node:assert/strict';
import { settings,request,validationSummary } from '../runtime/validate-kestra.mjs';

const root=resolve(import.meta.dirname,'..');
const work=resolve(root,'.local/docker-ci');
// Fail before downloads or services when the host has no Docker daemon.
execFileSync('docker',['info'],{stdio:'ignore'});
await mkdir(work,{recursive:true});
for(const folder of ['home','tmp','plugins','artifacts'])await mkdir(resolve(work,folder),{recursive:true});
const jar=resolve(work,'kestra-2.0.7.jar');
const response=await fetch('https://github.com/kestra-io/kestra/releases/download/v2.0.7/kestra-2.0.7',{signal:AbortSignal.timeout(180000)});
assert.equal(response.ok,true);
const jarBytes=Buffer.from(await response.arrayBuffer());
assert.equal(createHash('sha256').update(jarBytes).digest('hex'),'a70c858d4d8aabe9532c92ea5c5c6982b77312286b846adc47e6c7eb969326b3');
await writeFile(jar,jarBytes);
const env={...process.env,KESTRA_PLUGINS_PATH:resolve(work,'plugins')};
const javaArgs=['-Xmx1g',`-Duser.home=${resolve(work,'home')}`,`-Djava.io.tmpdir=${resolve(work,'tmp')}`,'-jar',jar];
execFileSync('java',[...javaArgs,'plugins','install','io.kestra.plugin:plugin-script-python:1.18.4'],{cwd:work,env,stdio:'inherit',timeout:180000});
const password=randomBytes(24).toString('hex')+'aA1!';
await writeFile(resolve(work,'config.yaml'),`micronaut:\n  server:\n    host: 127.0.0.1\n    port: 18080\nkestra:\n  grpc:\n    basic-auth:\n      enabled: true\n      username: ci-worker\n      password: ${password}\n  anonymous-usage-report:\n    enabled: false\n  plugins:\n    auto-install:\n      enabled: false\n  server:\n    basic-auth:\n      enabled: true\n      username: audit-ci@example.invalid\n      password: ${password}\n    worker:\n      threads: 4\n`);
const log=createWriteStream(resolve(work,'engine.log'));
let engine,mock;
const config=settings({KESTRA_URL:'http://127.0.0.1:18080',KESTRA_USERNAME:'audit-ci@example.invalid',KESTRA_PASSWORD:password});
try{
 engine=spawn('java',[...javaArgs,'server','local','--config',resolve(work,'config.yaml')],{cwd:work,env,stdio:['ignore','pipe','pipe']});
 engine.stdout.pipe(log,{end:false});engine.stderr.pipe(log,{end:false});
 const source=await readFile(resolve(work,'flow.yaml'),'utf8');
 let validation;
 for(let i=0;i<90;i++){
  if(engine.exitCode!==null)throw Error('Kestra exited before readiness; inspect private engine log.');
  try{validation=validationSummary(await request(config,'/flows/validate',{method:'POST',headers:{'Content-Type':'application/x-yaml'},body:source}));break;}
  catch{await new Promise(r=>setTimeout(r,2000));}
 }
 assert.equal(validation?.valid,true,'Docker test flow must validate.');
 await request(config,'/flows',{method:'POST',headers:{'Content-Type':'application/x-yaml'},body:source});
 await mkdir(resolve(root,'runtime/private'),{recursive:true});
 mock=spawn(process.execPath,['runtime/mock-appwrite.mjs'],{cwd:root,stdio:'inherit'});
 const scenarios=[['clean','clean-ready','clean','SUCCESS'],['later-arrival','missing-then-received','clean','SUCCESS'],['inconsistent','clean-ready','inconsistent','FAILED'],['incomplete','clean-ready','incomplete','FAILED']];
 const results=[];
 for(const [name,fixture,mode,expected] of scenarios){
  await writeFile(resolve(root,'runtime/private/mock-scenario.json'),JSON.stringify({fixture,mode}));
  const created=await request(config,'/executions/company.labrelay.docker/appwrite-custody-audit',{method:'POST',body:new FormData()});
  const id=(created.execution??created).id;
  let execution;
  for(let i=0;i<150;i++){
   execution=await request(config,`/executions/${id}`);
   if(['SUCCESS','FAILED','WARNING','KILLED','CANCELLED'].includes(execution.state?.current))break;
   await new Promise(r=>setTimeout(r,2000));
  }
  assert.equal(execution.state?.current,expected,`Unexpected state for ${name}; inspect engine log.`);
  let audit;
  for(const filename of ['audit.json','audit.csv']){
   const evaluated=await request(config,`/executions/${id}/actions/eval`,{method:'POST',headers:{'Content-Type':'text/plain'},body:`{{ outputs.build_report.outputFiles['${filename}'] }}`});
   assert.ok(evaluated.result.startsWith('kestra:'));
   const file=await fetch(config.base+`/executions/${id}/file?path=${encodeURIComponent(evaluated.result)}`,{headers:{...config.headers,Accept:'application/octet-stream'},redirect:'error'});
   assert.equal(file.ok,true);const text=await file.text();
   await writeFile(resolve(work,'artifacts',`${name}.${filename}`),text);
   if(filename==='audit.json')audit=JSON.parse(text);
  }
  const status=mode==='incomplete'?'inconclusive':mode==='inconsistent'?'findings':'clean';
  assert.equal(audit.status,status);
  if(name==='later-arrival')assert.equal(audit.resolvedMissing,1);
  results.push({name,executionId:id,state:execution.state.current,status,artifactsInspected:true});
  console.log(JSON.stringify(results.at(-1)));
 }
 const transport=JSON.parse(await readFile(resolve(root,'runtime/private/mock-observations.json'),'utf8'));
 assert.equal(transport.activeSessions,0);assert.equal(transport.logins,transport.logouts);
 const attestation=JSON.parse(await readFile(resolve(work,'source-attestation.json'),'utf8'));
 await mkdir(resolve(root,'reports'),{recursive:true});
 await writeFile(resolve(root,'reports/docker-ci.json'),JSON.stringify({at:new Date().toISOString(),engine:'2.0.7',pythonPlugin:'1.18.4',runner:'Docker on Linux, host network for loopback harness',validation,attestation,results,transport,passed:true},null,2));
}finally{
 if(mock)mock.kill('SIGTERM');if(engine)engine.kill('SIGTERM');log.end();
}
