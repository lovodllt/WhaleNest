package sender

import (
	"context"
	"os/exec"
	"strings"
	"testing"
	"time"

	"github.com/netcat-ai/webox/internal/wechatdb"
)

func TestNativeReplyReservationRejectsOtherConversationBeforeUI(t *testing.T) {
	s := &Service{pending: &pendingReply{room: "a@chatroom", reference: "123", token: "secret", expires: time.Now().Add(time.Minute)}}
	_, err := s.Send(context.Background(), "b@chatroom", []Item{{Kind: "text", Text: "wrong room"}})
	if err == nil || !strings.Contains(err.Error(), "reserved") {
		t.Fatalf("reservation ignored: %v", err)
	}
	_, err = s.Send(context.Background(), "a@chatroom", []Item{{Kind: "reply", Text: "reply", ReferenceID: "123", ContextToken: "wrong"}})
	if err == nil || !strings.Contains(err.Error(), "reserved") {
		t.Fatalf("token ignored: %v", err)
	}
	if containsItems([]wechatdb.OutgoingItem{{Kind: "reply", Value: "456\x00reply"}}, []preparedItem{{Kind: "reply", ReferenceID: "123", Text: "reply"}}) {
		t.Fatal("a quote to another parent must not satisfy verification")
	}
}

func TestNativeLocateScriptParsesBeforeItCanReachUI(t *testing.T) {
	cmd := exec.Command("bash", "-n")
	cmd.Stdin = strings.NewReader(nativeLocateScript("群备注", "这条消息"))
	if out, err := cmd.CombinedOutput(); err != nil {
		t.Fatalf("invalid native script: %v: %s", err, out)
	}
}

func TestNativeVoiceScriptParsesBeforeItCanReachUI(t *testing.T) {
	t.Setenv("WEBOX_FAST_UI", "1")
	script, err := nativeVoiceScript("d2Vib3gudGVzdA==", "/tmp/voice's sample.wav", 3.5)
	if err != nil {
		t.Fatal(err)
	}
	cmd := exec.Command("bash", "-n")
	cmd.Stdin = strings.NewReader(script)
	if out, err := cmd.CombinedOutput(); err != nil {
		t.Fatalf("invalid voice script: %v: %s", err, out)
	}
}

func TestShellQuoteSingle(t *testing.T) {
	if got := shellQuoteSingle("a'b"); got != `'a'"'"'b'` {
		t.Fatalf("unexpected quote: %s", got)
	}
}

func TestOpenChatUsesFirstSearchResultWithoutCoordinateFocus(t *testing.T) {
	script := openChatScript("query")
	if !strings.Contains(script, "set_clip 'query'; paste_clip; sleep 1.8") ||
		!strings.Contains(script, "key --clearmodifiers Return; sleep 1.5") {
		t.Fatalf("unexpected script: %s", script)
	}
	for _, forbidden := range []string{"Down", "getwindowgeometry", "mousemove", "click"} {
		if strings.Contains(script, forbidden) {
			t.Fatalf("script contains %q", forbidden)
		}
	}
}

func TestSendReturnsToContacts(t *testing.T) {
	script := sendItemsScript("target", []preparedItem{{Kind: "text", Text: "message"}})
	if strings.LastIndex(script, "key --clearmodifiers Return") >= strings.LastIndex(script, "key --clearmodifiers ctrl+2") {
		t.Fatal("send does not return to contacts")
	}
}

func TestSendItemsSendsEveryItemSeparately(t *testing.T) {
	script := sendItemsScript("target", []preparedItem{
		{Kind: "text", Text: "message"},
		{Kind: "image", Path: "/tmp/image.png", ContentType: "image/png"},
		{Kind: "file", Path: "/tmp/report.pdf", Filename: "report.pdf"},
	})
	for _, required := range []string{
		"set_clip 'bWVzc2FnZQ=='",
		"xclip -selection clipboard -target 'image/png' -loops 5 -i '/tmp/image.png'",
		"xclip -selection clipboard -target text/uri-list -loops 5 -i",
		"paste_clip", "key --clearmodifiers Return", "key --clearmodifiers ctrl+2",
	} {
		if !strings.Contains(script, required) {
			t.Fatalf("script does not contain %q: %s", required, script)
		}
	}
	if strings.Count(script, "xdotool key --clearmodifiers Return") != 4 {
		t.Fatalf("expected one search selection and one send per item: %s", script)
	}
	if strings.Count(script, "xdotool key --clearmodifiers Return; sleep 0.2") != 3 {
		t.Fatalf("each item was not submitted separately: %s", script)
	}
	if strings.Count(script, "xdotool key --clearmodifiers ctrl+2") != 1 {
		t.Fatalf("expected one return to contacts: %s", script)
	}
	for _, forbidden := range []string{"ctrl+l", "file_x", "send_x", "getwindowgeometry", "mousemove", "click"} {
		if strings.Contains(script, forbidden) {
			t.Fatalf("script contains media-specific coordinate action %q", forbidden)
		}
	}
}

func TestContainsItemsCountsDuplicates(t *testing.T) {
	expected := []preparedItem{
		{Kind: "image"},
		{Kind: "image"},
		{Kind: "file", Filename: "report.txt"},
		{Kind: "file", Filename: "report.txt"},
	}
	sent := []wechatdb.OutgoingItem{
		{Kind: "image"},
		{Kind: "file", Value: "report.txt"},
	}
	if containsItems(sent, expected) {
		t.Fatal("one outgoing item satisfied duplicate expected items")
	}
	sent = append(sent,
		wechatdb.OutgoingItem{Kind: "image"},
		wechatdb.OutgoingItem{Kind: "file", Value: "report.txt"},
	)
	if !containsItems(sent, expected) {
		t.Fatal("matching duplicate outgoing items were not found")
	}
}

func TestUIPreludeDoesNotDependOnWindowGeometry(t *testing.T) {
	script := strings.Join(uiScriptPrelude(), "; ")
	for _, forbidden := range []string{"getwindowgeometry", "mousemove", "click"} {
		if strings.Contains(script, forbidden) {
			t.Fatalf("script contains %q", forbidden)
		}
	}
}

func TestOwnerMentionRequiresWhitelistGroupAndNativeTargetProof(t *testing.T) {
	t.Setenv("WEBOX_MENTION_OWNER", "owner")
	service := &Service{}
	for _, testcase := range []struct{ room, target string }{{"room@chatroom", "stranger"}, {"owner", "owner"}} {
		if _, err := service.prepareItems(testcase.room, []Item{{Kind: "text", Text: "主人，来了", Mention: testcase.target}}); err == nil {
			t.Fatal("unapproved mention accepted")
		}
	}
	expected, err := service.prepareItems("room@chatroom", []Item{{Kind: "text", Text: "主人，来了", Mention: "owner"}})
	if err != nil {
		t.Fatal(err)
	}
	for _, actual := range []wechatdb.OutgoingItem{{Kind: "text", Value: "@owner_name 主人，来了"}, {Kind: "mention", Value: "stranger\x00@owner_name\u2005主人，来了"}, {Kind: "mention", Value: "owner\x00@owner_name\u2005别的消息"}} {
		if containsItems([]wechatdb.OutgoingItem{actual}, expected) {
			t.Fatal("incorrect native mention satisfied verification")
		}
	}
	if !containsItems([]wechatdb.OutgoingItem{{Kind: "mention", Value: "owner\x00@webox.owner\u2005主人，来了"}}, expected) {
		t.Fatal("verified owner mention was rejected")
	}
}

func TestTaskMentionRequiresGroupAndMessageReference(t *testing.T) {
	t.Setenv("WEBOX_MENTION_OWNER", "owner")
	service := &Service{}
	item := Item{Kind: "text", Text: "喝水啦", Mention: "requester", ReferenceID: "123"}
	prepared, err := service.prepareItems("room@chatroom", []Item{item})
	if err != nil || prepared[0].ReferenceID != "123" {
		t.Fatal("task reference was not retained", err)
	}
	if _, err := service.prepareItems("requester", []Item{item}); err == nil {
		t.Fatal("private mention accepted")
	}
}

func TestDetachedChatScriptsParseBeforeUI(t *testing.T) {
	t.Setenv("WEBOX_DETACHED_CHAT", "1")
	t.Setenv("WEBOX_FAST_UI", "1")
	voice, err := nativeVoiceScript("d2Vib3gub3duZXI=", "/tmp/sample.wav", 3.5)
	if err != nil {
		t.Fatal(err)
	}
	for _, script := range []string{voice, visibleLocateScript("webox.owner", "hello"), sendPreparedReplyScript("123", []preparedItem{{Kind: "text", Text: "hello"}})} {
		cmd := exec.Command("bash", "-n")
		cmd.Stdin = strings.NewReader(script)
		if out, err := cmd.CombinedOutput(); err != nil {
			t.Fatalf("invalid detached script: %v: %s", err, out)
		}
	}
}
