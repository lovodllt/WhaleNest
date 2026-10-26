import {createRequire} from 'node:module';
import {pathToFileURL} from 'node:url';
import {join} from 'node:path';
import {mkdirSync,existsSync,readFileSync,writeFileSync,renameSync} from 'node:fs';
import {createHash} from 'node:crypto';

const require=createRequire(join(process.env.DSH_HOME||join(process.env.HOME,'.dsh'),'profiles/dafeiyu-runtime/package.json'));
const {createRuntimeMemorySource}=await import(pathToFileURL(require.resolve('dsh-mnemon-source-runtime')));
let raw='';
for await (const chunk of process.stdin) raw+=chunk;
const request=JSON.parse(raw);
const result={_revisions:{},_usage:{}};
const delimiterBytes=Buffer.byteLength('\n§\n');
const entryKey=e=>createHash('sha256').update(e.target+'\0'+e.content).digest('hex').slice(0,24);
function save(path,data){const temp=path+'.tmp';writeFileSync(temp,JSON.stringify(data),{mode:0o600});renameSync(temp,path)}
for (const item of request.scopes) {
  if (!/^[a-f0-9]{64}$/.test(item.person) || !/^[a-f0-9]{64}$/.test(item.room)) throw Error('Invalid memory scope');
  const directory=join(request.root,item.person,item.room);
  mkdirSync(directory,{recursive:true,mode:0o700});
  const source=createRuntimeMemorySource({dataDir:directory,userLimitBytes:32768,memoryLimitBytes:8192});
  const runtime=source.create({sourceInstanceKey:'source:webox-person',configuration:{}});
  const archivePath=join(directory,'archive.json'),policyPath=join(directory,'entry-policy.json');
  let archive=existsSync(archivePath)?JSON.parse(readFileSync(archivePath,'utf8')):[];
  let policies=existsSync(policyPath)?JSON.parse(readFileSync(policyPath,'utf8')):{};
  let snapshot=(await runtime.manage({mode:'read',operation:'snapshot',input:{}})).value;
  const revision=()=>createHash('sha256').update(snapshot.revision+JSON.stringify(archive)+JSON.stringify(policies)).digest('hex');
  if(item.expected_revision && item.expected_revision!==revision())throw Error('Memory changed; refresh before editing');
  const changes=[...(item.changes??[])];
  if(item.maintain){
    const now=request.now??Date.now(),cutoff=now-(request.impression_days??90)*86400000;
    for(const entry of snapshot.entries){
      if((entry.target==='memory'&&entry.importance!=='critical'&&Date.parse(entry.updated_at)<cutoff)||Date.parse(policies[entryKey(entry)]?.expires_at??'')<=now)
        changes.unshift({kind:entry.target==='user'?'fact':'impression',action:'remove',old:entry.content});
    }
    archive=archive.filter(entry=>!((entry.target==='memory'&&entry.importance!=='critical'&&Date.parse(entry.updated_at)<cutoff)||Date.parse(policies[entryKey(entry)]?.expires_at??'')<=now));
  }
  for (const change of changes) {
    const target=change.kind==='fact'?'user':'memory';
    const active=snapshot.entries.find(e=>e.target===target&&e.content===(change.action==='add'?change.text:change.old));
    if(change.action==='add' && (active||archive.some(e=>e.target===target&&e.content===change.text)))continue;
    if(change.action!=='add'){
      archive=archive.filter(e=>e.target!==target||e.content!==change.old);
      delete policies[entryKey({target,content:change.old})];
    }
    if(change.action==='remove'&&!active)continue;
    const mutation={action:change.action==='replace'&&!active?'add':change.action,target,content:change.text,
      oldText:change.old,importance:change.pinned===undefined&&active?active.importance:change.pinned?'critical':target==='user'?'normal':'low'};
    const plan=(await runtime.manage({mode:'read',operation:'maintenance-plan',input:mutation})).value;
    if(plan.requiresMaintenance){
      const budget=plan.limit-Buffer.byteLength(plan.pending?.content??'','utf8')-delimiterBytes;
      const kept=[];let used=0;
      const entries=[...plan.entries].sort((a,b)=>(b.importance==='critical')-(a.importance==='critical')||b.updated_at.localeCompare(a.updated_at));
      for(const entry of entries){
        const size=Buffer.byteLength(entry.content,'utf8')+(kept.length?delimiterBytes:0);
        if(used+size<=budget){kept.push(entry);used+=size}
        else if(entry.importance==='critical')throw Error('Pinned memories fill the capacity; review them before adding more');
        else if(!archive.some(e=>entryKey(e)===entryKey(entry)))archive.push(entry);
      }
      save(archivePath,archive);
      await runtime.manage({mode:'write',operation:'compact-and-mutate',confirmed:true,input:{
        revision:plan.revision,mutation,compacted:kept,maxBytes:Math.max(0,budget)}});
    }else await runtime.manage({mode:'write',operation:'mutate',confirmed:true,input:mutation});
    snapshot=(await runtime.manage({mode:'read',operation:'snapshot',input:{}})).value;
    if(change.action!=='remove')policies[entryKey({target,content:change.text})]={...(change.expires_at?{expires_at:change.expires_at}:{})};
  }
  save(archivePath,archive);save(policyPath,policies);
  const active=new Set(snapshot.entries.map(entryKey));
  result[item.key]=[...snapshot.entries,...archive.filter(e=>!active.has(entryKey(e))).map(e=>({...e,archived:true}))]
    .map(e=>({id:entryKey(e),kind:e.target==='user'?'fact':'impression',text:e.content,updated:e.updated_at,
      pinned:e.importance==='critical',archived:!!e.archived,...policies[entryKey(e)]}));
  result._revisions[item.key]=revision();
  result._usage[item.key]=snapshot.targets;
}
process.stdout.write(JSON.stringify(result));
