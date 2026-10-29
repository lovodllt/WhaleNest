import asyncio
import json
from pathlib import Path
import edge_tts

async def main():
    voices=await edge_tts.list_voices()
    result=[{'voice':v['ShortName'],'label':v['FriendlyName']} for v in voices if v['Locale'].startswith('zh-')]
    path=Path(__file__).resolve().parents[1]/'data/tts/voices.json'
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('中文音色已更新：',len(result))

asyncio.run(main())
