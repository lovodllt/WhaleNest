import { pathToFileURL } from 'node:url';

const { defineTool } = await import(pathToFileURL(process.env.DAFEIYU_TOOLS_MODULE).href);

export const name = 'daily-tools';
export const inject = ['tools'];

export function apply(ctx) {
  const url = process.env.DAFEIYU_ACTION_URL;
  const token = process.env.DAFEIYU_ACTION_TOKEN;
  ctx.tools.register(defineTool({
    name: 'daily_action',
    description: `处理当前主人私聊中明确提出的简单生活事务。args是以下JSON对象的字符串，不接收owner、session或其他聊天目标：
recent_images：查看本聊天近期图片和表情，args={}。
list_stickers：查看表情库，args={}。
collect_stickers：收藏表情，args={"items":[{"id":"真实16位素材ID","description":"客观画面、可读文字及适用时机，不超过300字"}]}。
remove_stickers：删除收藏，args={"ids":["真实素材ID"]}。
list_reminders：查看本私聊提醒，args={}。
create_reminder：准备本私聊提醒，args={"when":"明天09:00、10分钟后或每天21:00","text":"提醒内容"}。
cancel_reminder：取消提醒，args={"id":"真实T开头提醒ID"}。
search_public：检索公开资料，args={"query":"最少公开搜索词"}，不把私聊记录交给搜索。
set_preferences：修改主人明确要求的生活与互动开关，args={"values":{...}}；只支持voice_reply.enabled、voice_reply.spontaneous、defaults.auto_stickers、owner_proactive.enabled这四个布尔值，defaults.sticker_interval_seconds、owner_proactive.interval_minutes这两个整数，以及owner_proactive.hours时间数组如["09:00","23:00"]。
先查缺少的信息再操作，只使用当前聊天和真实回执中的素材、提醒ID，不编造ID。每轮最多六次工具调用、一次修改；未经主人明确要求不修改。修改动作返回prepared仅代表准备完成，后台会在本轮结束并检查最新消息后执行；此时不得说已完成、已收藏、已设定或已删除。图片、语音和群发仍按原有桥接能力的控制标签处理，与本轮修改操作互斥。本工具不处理工作任务。`,
    parameters: {
      action: {
        type: 'string',
        required: true,
        enum: ['recent_images', 'collect_stickers', 'list_stickers', 'remove_stickers',
          'list_reminders', 'create_reminder', 'cancel_reminder', 'search_public', 'set_preferences'],
      },
      args: {
        type: 'string',
        required: true,
        description: '该操作的JSON对象参数；无参数时使用{}。',
      },
    },
    output: {
      schema: { type: 'object', additionalProperties: true },
      render: (_args, value) => [{ type: 'text', text: JSON.stringify(value) }],
    },
    async execute({ action, args }, exec) {
      const parsed = JSON.parse(args);
      if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) {
        throw new Error('args必须是JSON对象字符串');
      }
      if (!exec.agent) throw new Error('缺少当前会话身份');
      const response = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({ session: String(exec.agent.id), action, args: parsed }),
        signal: exec.signal,
      });
      const receipt = await response.json();
      if (!response.ok || !receipt.ok) throw new Error(receipt.error || '操作失败');
      return receipt;
    },
  }));
}
