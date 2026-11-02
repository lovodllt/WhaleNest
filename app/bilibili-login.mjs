import {readFile, writeFile, rm} from 'node:fs/promises';

process.umask(0o077);
const root=new URL('../data/bilibili/provider/',import.meta.url);
const pending=new URL('qr-pending.json',root);
const action=process.argv[2];

try {
  const login=await import(new URL('node_modules/dsh-bilibili/lib/login.js',root));
  if(action==='start') {
    const result=await login.startQrLogin();
    if(!result.qr_image_path) throw new Error('QR image unavailable');
    await writeFile(pending,JSON.stringify({qrcode_key:result.qrcode_key,created_at:new Date().toISOString()}),{mode:0o600});
    console.log(JSON.stringify({status:'waiting_scan',qr_image_path:result.qr_image_path}));
  } else if(action==='poll') {
    const {qrcode_key}=JSON.parse(await readFile(pending,'utf8'));
    const result=await login.pollQrLogin(qrcode_key);
    console.log(JSON.stringify({status:result.status,code:result.code,saved:result.saved===true}));
    if(['success','expired'].includes(result.status)) {
      await rm(pending,{force:true});
      await rm(new URL('node_modules/dsh-bilibili/.qr-login.png',root),{force:true});
    }
  } else if(action==='status') {
    const stored=await login.loadStoredSessdata();
    console.log(JSON.stringify({credential_present:!!stored}));
  } else {
    console.error('Usage: node deploy/bilibili-login.mjs start|poll|status');
    process.exitCode=2;
  }
} catch(error) {
  console.error(JSON.stringify({status:'error',error_type:error.name}));
  process.exitCode=1;
}
