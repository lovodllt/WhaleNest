import {loadStoredSessdata} from '../data/bilibili/provider/node_modules/dsh-bilibili/lib/login.js';
import {BilibiliOfficialProvider, mapSearchData} from '../data/bilibili/provider/node_modules/dsh-plugin-bilibili/lib/provider.js';

process.umask(0o077);
const signal = AbortSignal.timeout(25000);
const clean = value => String(value ?? '').replace(/<[^>]*>/g,'').replace(/&amp;/g,'&').replace(/&lt;/g,'<').replace(/&gt;/g,'>').replace(/&quot;/g,'"').replace(/&#39;/g,"'").trim();
function duration(value) {
  if(typeof value==='string' && value.includes(':')) return Math.round(value.split(':').reduce((v,p)=>v*60+Number(p),0)*1000);
  return Math.round(Number(value || 0)*1000);
}
const failure = code => ({access:[-101].includes(code)?'login_required':[-352,-412,412,429].includes(code)?'rate_limited':'unavailable',provider_code:code});

async function main(input) {
  const stored = await loadStoredSessdata();
  const headers = {'User-Agent':'Mozilla/5.0','Referer':'https://www.bilibili.com/'};
  if(stored?.sessdata) headers.Cookie='SESSDATA='+stored.sessdata;
  const provider=new BilibiliOfficialProvider({cookie:headers.Cookie,requestTimeoutMs:10000});
  async function get(path,params={}) {
    const url = new URL('https://api.bilibili.com'+path);
    for(const [key,value] of Object.entries(params)) url.searchParams.set(key,String(value));
    const response = await fetch(url,{headers,signal});
    if(!response.ok) return {code:response.status};
    return await response.json();
  }
  const operation = input.operation;
  if(operation==='status') {
    if(!stored?.sessdata) return {access:'login_required',credential_present:false,authenticated:false};
    const data = await get('/x/web-interface/nav');
    return {access:data.code===0 && data.data?.isLogin===true?'available':'login_required',credential_present:true,authenticated:data.code===0 && data.data?.isLogin===true};
  }
  const page = input.page ?? 1;
  if(!Number.isInteger(page) || page<1 || page>10) throw new Error('InvalidPage');
  if(operation==='feed' || operation==='search') {
    const query = String(input.query ?? '').trim();
    if(operation==='search' && (!query || query.length>120)) throw new Error('InvalidQuery');
    if(operation==='search') {
      const {wbiSign}=await import('../data/bilibili/provider/node_modules/dsh-plugin-bilibili/lib/wbi.js');
      await provider.ensureAnonymousCookies(signal);
      const keys=await provider.resolveWbiKeys(signal);
      const params=wbiSign({search_type:'video',keyword:query,page,page_size:8,web_location:1430654},keys.imgKey,keys.subKey);
      const raw=await provider.requestJson('/x/web-interface/wbi/search/type',params,signal);
      const data=mapSearchData(raw,page,8);
      return {access:'available',items:data.items.slice(0,8).map(v=>({resource_id:'bilibili:'+v.bvid,url:'https://www.bilibili.com/zh-Hans/video/'+v.bvid,
        title:clean(v.title),uploader:clean(v.author),duration_ms:duration(v.duration),description:clean(v.description).slice(0,1000)}))};
    }
    const data = await get('/x/web-interface/popular',{pn:page,ps:8});
    if(data.code!==0) return failure(data.code);
    const items = (data.data?.list ?? data.data?.result ?? []).filter(v=>/^BV[0-9A-Za-z]{10}$/.test(v.bvid)).slice(0,8).map(v=>({
      resource_id:'bilibili:'+v.bvid,url:'https://www.bilibili.com/zh-Hans/video/'+v.bvid,title:clean(v.title),
      uploader:clean(v.author ?? v.owner?.name),duration_ms:duration(v.duration),description:clean(v.description ?? v.desc).slice(0,1000)}));
    return {access:'available',items};
  }
  if(operation!=='open' || !/^bilibili:BV[0-9A-Za-z]{10}$/.test(input.resource_id ?? '')) throw new Error('InvalidResource');
  const bvid=input.resource_id.slice('bilibili:'.length);
  const detail=await provider.video({bvid},signal);
  const length=duration(detail.pages[0]?.duration ?? detail.duration);
  let transcript=null,subtitleAccess='available';
  try {transcript=await provider.subtitles({bvid},signal);} catch(error) {
    if(!['BILIBILI_SUBTITLES_UNAVAILABLE','BILIBILI_LOGIN_REQUIRED'].includes(error.code)) throw error;
    subtitleAccess=error.code==='BILIBILI_LOGIN_REQUIRED'?'login_required':'unavailable';
  }
  const subtitles=(transcript?.cues ?? []).map(v=>({start_ms:duration(v.from),end_ms:duration(v.to),text:clean(v.content)}))
    .filter(v=>v.text && Number.isFinite(v.start_ms) && Number.isFinite(v.end_ms) && v.start_ms>=0 && v.end_ms>v.start_ms)
    .sort((a,b)=>a.end_ms-b.end_ms);
  return {access:'available',resource:{resource_id:input.resource_id,url:'https://www.bilibili.com/zh-Hans/video/'+bvid,
    title:clean(detail.title),uploader:clean(detail.author),duration_ms:length,
    description:clean(detail.description).slice(0,2000),subtitles,subtitle_language:transcript?.language,
    subtitle_access:subtitles.length?'available':subtitleAccess==='available'?'unavailable':subtitleAccess,
    evidence:subtitles.length?'subtitle':'metadata_only',fetched_at_real_ms:Date.now(),part:1,parts:detail.pages.length}};
}
try {
  let source='';for await(const chunk of process.stdin) source+=chunk;
  console.log(JSON.stringify(await main(JSON.parse(source))));
} catch(error) {
  const http=Number(/HTTP (\d+)/.exec(error.message ?? '')?.[1] ?? 0);
  console.log(JSON.stringify({access:error.code==='BILIBILI_RISK_CONTROL' || [412,429].includes(http)?'rate_limited':error.code==='BILIBILI_LOGIN_REQUIRED'?'login_required':'unavailable',error_type:error.name,error_code:error.code,provider_code:error.bilibiliCode || http || undefined}));
}
