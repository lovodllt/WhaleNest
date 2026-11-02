import {pathToFileURL} from 'node:url';
const {defineTool}=await import(pathToFileURL(process.env.DAFEIYU_TOOLS_MODULE).href);
export const name='whalenest-bilibili-tools';
export const inject=['tools'];
export function apply(ctx) {
  const resource={type:'string',required:true,description:'工具返回的真实BV号、bilibili:BV号或规范视频链接'};
  const definitions=[
    ['bilibili_search','按题材或关键词搜索B站。只返回真实标题、UP主、时长、简介和链接，search_metadata_only不代表看过，可换词或翻页。',{
      keyword:{type:'string',required:true,description:'1–120字公开检索词'},page:{type:'integer',description:'1–10页，默认1'},max_results:{type:'integer',description:'1–8条，默认5'}}],
    ['bilibili_read','一次读取首P全部可用字幕。不读取画面、声音、普通评论或弹幕；无字幕和超长失败须如实说明。', {resource_id:resource}],
    ['bilibili_remember','读字幕后留下唯一短摘要，不学习为性格。摘要和感受各最多180字，感受可空。',{
      resource_id:resource,summary:{type:'string',required:true,description:'最多180字'},feedback:{type:'string',required:true,description:'最多180字，可空'}}],
    ['bilibili_share','读完字幕后自行决定是否分享。wechat限当前聊天且recipient_uid填空；bilibili_dm只选读取工具返回名单中的UID。只准备入队，不能声称已发送。',{
      resource_id:resource,channel:{type:'string',required:true,enum:['wechat','bilibili_dm']},
      recipient_uid:{type:'string',required:true},text:{type:'string',required:true,description:'短感受，最多三句，每句最多25字，不含链接、控制标签或私人聊天背景'}}],
  ];
  for(const [name,description,parameters] of definitions) ctx.tools.register(defineTool({
    name,description,parameters,timeoutMs:35000,
    output:{schema:{type:'object',additionalProperties:true},render:(_args,value)=>[{type:'text',text:JSON.stringify(value)}]},
    async execute(args,exec) {
      if(!exec.agent) throw new Error('缺少当前会话身份');
      const response=await fetch(process.env.DAFEIYU_ACTION_URL,{
        method:'POST',headers:{'Content-Type':'application/json',Authorization:`Bearer ${process.env.DAFEIYU_ACTION_TOKEN}`},
        body:JSON.stringify({session:String(exec.agent.id),action:name,args}),signal:exec.signal});
      const result=await response.json();
      if(!response.ok || !result.ok) throw new Error(result.error||'B站操作失败');
      return result.result;
    },
  }));
}
