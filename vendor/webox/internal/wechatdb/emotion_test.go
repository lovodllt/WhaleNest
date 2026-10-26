package wechatdb

import (
 "testing"
 "github.com/netcat-ai/webox/wecom"
)

func TestEmotionKeepsDownloadMetadataAndDecodesXML(t *testing.T) {
 var message wecom.Message
 normalizeMessage(&message,47,`sender:
<msg><emoji md5 = "0123456789abcdef0123456789abcdef" cdnurl="https://emoji.qpic.cn/test?a=1&amp;b=2" thumburl="https://mmbiz.qpic.cn/thumb" /></msg>`,true)
 if message.Emotion==nil || message.Emotion.MD5Sum!="0123456789abcdef0123456789abcdef" || message.Emotion.CDNURL!="https://emoji.qpic.cn/test?a=1&b=2" {
  t.Fatalf("emotion metadata missing: %#v",message.Emotion)
 }
}
