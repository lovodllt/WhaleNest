let biliState=null,biliDraft=null,biliTimer=null;
const biliLabels={pending:'待处理',reading:'读字幕中',unreadable:'无可用字幕',reply_queued:'回复已排队',
  queued_wechat:'微信分享排队中',sending:'发送中',sent_provider:'B站已接受',sent_wechat:'微信已核验',
  uncertain:'结果未确认，不自动重发',failed:'未成功',skipped:'人物选择不回复',cancelled:'已取消',
  interrupted:'阅读被中断',expired:'已过期'};
function biliChanged(){biliDraft={enabled:$('#bili-enabled').checked,share_recipient_uids:$('#bili-uids').value};dirty=true}
async function openBilibili(restore=false){
  if(dirty&&!restore){toast('请先保存或放弃当前修改');return}
  clearTimeout(biliTimer);
  try{
    if(!restore||!biliState){biliState=await fetchState('/api/bilibili/state');biliDraft={enabled:biliState.config.enabled,share_recipient_uids:biliState.config.share_recipient_uids.join('\n')}}
    activePlugin='bilibili';
    const s=biliState,c=s.credentials;
    const rows=(items,send)=>items.length?items.map(x=>`<div class="dep-row"><div><p>${esc(send?x.operation:x.resource||'新@通知')}</p><small>${esc(new Date(x.created).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'}))}${send&&x.recipient?' · '+esc(x.recipient):''}</small></div><strong>${esc(biliLabels[x.status]||x.status)}${x.receipt?.receipt_id?'<br><small>回执 '+esc(x.receipt.receipt_id)+'</small>':''}</strong></div>`).join(''):'<p class="sub">暂无记录</p>';
    modal('B站互动 · WhaleNest','本项目独立配置，不读取或更改 Dworld 的账号、名单和后台',`
      <div id="bili-panel"><div class="note">${s.provider_installed?'提供方已安装':'先在终端运行 scripts/manage.py bilibili-plugins 安装锁定插件'}<br>账号：${esc(s.config.account_uid||'尚未验证绑定')} · ${c.read_ready?'已保存读取凭据':'未登录'} · ${c.write_ready?'具备写入所需字段':'缺少写入凭据'}<br>字段齐备不代表平台一定接受，实际发送以回执为准</div>
      <div class="setting-line"><div><strong>B站功能总开关</strong><small>搜索、字幕、新@处理与尚未发送的分享</small></div><label class="switch"><input id="bili-enabled" type="checkbox" ${biliDraft.enabled?'checked':''} onchange="biliChanged()"><span></span></label></div>
      <label class="field"><span>B站私信分享接收UID</span><textarea id="bili-uids" rows="5" oninput="biliChanged()" placeholder="每行一个数字UID；留空则不发站内私信">${esc(biliDraft.share_recipient_uids)}</textarea><small>由你维护；人物只能从名单中选。保存后发送前再次核对</small></label>
      <div class="section-head"><h3>扫码登录</h3>${btn('生成／刷新二维码',"biliLogin('start')",false,'',!s.provider_installed||offline||dirty)}</div><div id="bili-login-status" class="sub">扫码成功后会核实并绑定实际账号，凭据只留服务端</div><img id="bili-qr" hidden width="240" height="240" alt="B站登录二维码">
      <div class="section-head"><h3>近期通知</h3></div>${rows(s.notifications,false)}
      <div class="section-head"><h3>近期发送</h3></div>${rows(s.actions,true)}
      <div class="note" style="margin-top:18px">只处理启用后的新@，有可用字幕才交给人物判断是否回复原评论。阅读范围是首P字幕，没有画面或声音。未知发送结果不自动重发；已在传输中的消息不能撤回</div></div>`,
      btn('关闭','closePlugin()')+btn('刷新状态','openBilibili()',false,'',dirty)+btn('保存','saveBilibili()',true,'check',offline),'globe');
  }catch(e){toast(e.message)}
}
async function saveBilibili(){
  if(busy||offline||!biliState)return;
  biliChanged();
  const uids=biliDraft.share_recipient_uids.split(/[\s,，]+/).filter(Boolean);
  if(uids.some(v=>!/^[1-9][0-9]{0,19}$/.test(v))){toast('请填写数字UID，每行一个');return}
  busy=true;
  try{biliState=await fetchState('/api/bilibili/config',{revision:biliState.revision,enabled:biliDraft.enabled,share_recipient_uids:uids});dirty=false;busy=false;closeModal();toast('B站配置已保存');await refreshLive();await openBilibili()}catch(e){busy=false;toast(e.message)}
}
async function biliLogin(action){
  if(busy||offline||dirty||!$('#bili-panel')||document.hidden)return;
  clearTimeout(biliTimer);busy=true;
  try{
    const {login}=await fetchState('/api/bilibili/login/'+action,{});
    if(!$('#bili-panel'))return;
    const labels={waiting_scan:'等待扫码',waiting:'等待扫码',scanned:'请在B站确认',success:'登录成功，账号已绑定',expired:'二维码已过期，请刷新',error:'登录失败，请刷新'};
    $('#bili-login-status').textContent=labels[login.status]||login.status;
    if(login.qr_image_url){$('#bili-qr').src=login.qr_image_url+'?t='+Date.now();$('#bili-qr').hidden=false}
    if(login.status==='success'){
      busy=false;await openBilibili();return;
    }
    if(['waiting_scan','waiting','scanned'].includes(login.status))biliTimer=setTimeout(()=>biliLogin('poll'),2500);
  }catch(e){if($('#bili-login-status'))$('#bili-login-status').textContent=e.message}finally{busy=false}
}
