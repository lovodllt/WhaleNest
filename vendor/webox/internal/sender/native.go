package sender

import (
	"context"
	"encoding/base64"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"strconv"
	"strings"
	"time"
	"unicode/utf8"

	"github.com/netcat-ai/webox/wecom"
)

type pendingReply struct {
	token, room, reference, window string
	expires                        time.Time
}

func (service *Service) nativeAnchor(room, reference, actor string) (wecom.Message, error) {
	if os.Getenv("WEBOX_LEGACY_INPUT_FOCUS") != "1" {
		return wecom.Message{}, errors.New("native actions require the fixed legacy client")
	}
	now := time.Now()
	start := now.Add(-24 * time.Hour).UnixMilli()
	if reference != "" {
		start = 0
	}
	messages, err := service.wechat.RoomMessagesBySort(room, start, now.Add(time.Second).UnixMilli())
	if err != nil {
		return wecom.Message{}, err
	}
	for i := len(messages) - 1; i >= 0; i-- {
		m := messages[i]
		if m.Outgoing || m.Text == nil || m.MsgType != "text" || (reference != "" && m.MsgID != reference) || (actor != "" && m.From != actor) {
			continue
		}
		text := m.Text.Content
		if text == "" || strings.ContainsAny(text, "\r\n") || utf8.RuneCountInString(text) > 120 || (actor != "" && reference == "" && utf8.RuneCountInString(text) > 20) {
			continue
		}
		latest := true
		for _, newer := range messages[i+1:] {
			if newer.Text != nil && strings.Contains(newer.Text.Content, text) {
				latest = false
				break
			}
			if newer.Reply != nil && strings.Contains(newer.Reply.Title, text) {
				latest = false
				break
			}
		}
		if latest {
			return m, nil
		}
	}
	return wecom.Message{}, errors.New("no unambiguous searchable incoming text anchor")
}

func (service *Service) PrepareReply(ctx context.Context, room, reference string) (string, error) {
	if service.pending != nil && time.Now().After(service.pending.expires) {
		if err := service.CancelReply(ctx, service.pending.token); err != nil {
			return "", err
		}
	}
	if service.pending != nil {
		return "", errors.New("a native quoted reply is already reserved")
	}
	anchor, err := service.nativeAnchor(room, reference, "")
	if err != nil {
		return "", err
	}
	recipient, err := service.wechat.ResolveRecipient(room)
	if err != nil {
		return "", err
	}
	// Main window ID is recorded by the staging script; it is not a chat selector.
	script := visibleLocateScript(recipient.SearchTerm, anchor.Text.Content)
	if os.Getenv("WEBOX_DETACHED_CHAT") == "1" {
		parts := uiScriptPrelude()
		parts = append(parts, openChatScript(base64.StdEncoding.EncodeToString([]byte(recipient.SearchTerm))),
			`python3 /webox/state/weagent/ui_quote_reply.py prepare "$win" `+shellQuoteSingle(base64.StdEncoding.EncodeToString([]byte(anchor.Text.Content))))
		script = strings.Join(parts, "; ")
	} else {
		script += `; xdotool mousemove --window "$win" "$bubble_x" "$bubble_y" click 3; sleep 0.2; xdotool key --clearmodifiers Up Up Return; sleep 0.3`
	}
	script += `; printf '\nNATIVE_WINDOW:%s\n' "$win"`
	output, err := runNativeScript(ctx, script)
	if err != nil {
		return "", err
	}
	_, window, ok := strings.Cut(output, "NATIVE_WINDOW:")
	window = strings.TrimSpace(window)
	if _, err := strconv.ParseUint(window, 10, 64); !ok || err != nil {
		return "", errors.New("native quote window was not recorded")
	}
	token := randomID()
	service.pending = &pendingReply{token: token, room: room, reference: reference, window: window, expires: time.Now().Add(4 * time.Minute)}
	return token, nil
}

func (service *Service) CancelReply(ctx context.Context, token string) error {
	if service.pending == nil {
		return nil
	}
	if token != service.pending.token {
		return errors.New("native quote reservation mismatch")
	}
	clear := `xdotool key --clearmodifiers Escape ctrl+a BackSpace`
	quoteLeft := 335
	if os.Getenv("WEBOX_DETACHED_CHAT") == "1" {
		clear = `xdotool key --clearmodifiers ctrl+a BackSpace`
	}
	script := uiScriptPrelude()
	script = append(script, `[ "$win" = `+shellQuoteSingle(service.pending.window)+` ] || exit 5`, `eval "$(xdotool getwindowgeometry --shell "$win")"; xdotool mousemove --window "$win" "$((WIDTH/2))" "$((HEIGHT-90))" click 1`, clear,
		// The quote preview sits outside the editor; deleting text does not close it.
		`for quote_x in $(seq `+strconv.Itoa(quoteLeft)+` 8 "$((WIDTH-35))"); do xdotool mousemove --window "$win" "$quote_x" "$((HEIGHT-64))" click 1; done`)
	if os.Getenv("WEBOX_DETACHED_CHAT") != "1" {
		script = append(script, `xdotool key --clearmodifiers ctrl+2`)
	} else {
		script = uiScriptPrelude()
		script = append(script, `python3 /webox/state/weagent/ui_quote_reply.py cancel `+shellQuoteSingle(service.pending.window))
	}
	if err := runUIScript(ctx, "10s", strings.Join(script, "; "), "cancel native quote"); err != nil {
		return err
	}
	service.pending = nil
	return nil
}

func sendPreparedReplyScript(window string, items []preparedItem) string {
	// Keep the selected native quote while the model is generating.
	script := sendItemsScript("", items)
	return strings.Replace(script, openChatScript(""), `[ "$win" = `+shellQuoteSingle(window)+` ] || exit 5`, 1)
}

func (service *Service) Pat(ctx context.Context, room, target string) (Receipt, error) {
	if service.pending != nil && time.Now().After(service.pending.expires) {
		if err := service.CancelReply(ctx, service.pending.token); err != nil {
			return Receipt{}, err
		}
	}
	if service.pending != nil {
		return Receipt{}, errors.New("a native quoted reply is reserved")
	}
	info, err := service.wechat.UserInfo()
	if err != nil {
		return Receipt{}, err
	}
	if target == info.AccountID {
		return Receipt{}, errors.New("self pat is not supported")
	}
	anchor, err := service.nativeAnchor(room, "", target)
	if err != nil {
		return Receipt{}, err
	}
	recipient, err := service.wechat.ResolveRecipient(room)
	if err != nil {
		return Receipt{}, err
	}
	positions, err := service.wechat.RoomMessagePositions(room)
	if err != nil {
		return Receipt{}, err
	}
	script := nativeLocateScript(recipient.SearchTerm, anchor.Text.Content)
	script += `; xdotool mousemove --window "$win" 310 "$((bubble_y-16))" click 3; sleep 0.2; xdotool key --clearmodifiers Up Return; sleep 0.3; xdotool key --clearmodifiers ctrl+2`
	if _, err = runNativeScript(ctx, script); err != nil {
		return Receipt{}, err
	}
	for range 20 {
		items, err := service.wechat.OutgoingItemsAfter(positions, room)
		if err != nil {
			return Receipt{}, err
		}
		for _, item := range items {
			if item.Kind == "pat" && item.Value == info.AccountID+"\x00"+target {
				return Receipt{ClientMessageID: randomID()}, nil
			}
		}
		select {
		case <-ctx.Done():
			return Receipt{}, ctx.Err()
		case <-time.After(500 * time.Millisecond):
		}
	}
	return Receipt{}, errors.New("native pat was not verified in the intended room")
}

func nativeLocateScript(search, text string) string {
	b64 := func(s string) string { return shellQuoteSingle(base64.StdEncoding.EncodeToString([]byte(s))) }
	script := uiScriptPrelude()
	script = append(script, `history_win=""; trap 'status=$?; cleanup_clip; if [ "$status" -ne 0 ] && [ -n "$history_win" ] && [ "$history_win" != "$win" ]; then wmctrl -ic "$history_win" 2>/dev/null || true; fi' EXIT`, openChatScript(base64.StdEncoding.EncodeToString([]byte(search))),
		`xdotool key --clearmodifiers ctrl+a BackSpace`,
		`eval "$(xdotool getwindowgeometry --shell "$win")"; [ "$WIDTH" -eq 980 ] && [ "$HEIGHT" -eq 710 ] || { printf 'unsupported main layout: %sx%s' "$WIDTH" "$HEIGHT"; exit 6; }; main_height="$HEIGHT"`,
		`xdotool mousemove --window "$win" 473 "$((HEIGHT-126))" click 1; sleep 1.2`,
		`history_win="$(xdotool getactivewindow)"; [ "$history_win" != "$win" ] || { printf 'history did not open'; exit 6; }`,
		`case "$(xdotool getwindowname "$history_win")" in *聊天记录*) ;; *) printf 'unexpected history title'; exit 6 ;; esac`,
		`xdotool key --clearmodifiers ctrl+a BackSpace`,
		"set_clip "+b64(text)+`; paste_clip; xdotool key --clearmodifiers Return; sleep 1`,
		"expected="+b64(text),
		"set_clip "+b64("native-check-"+randomID()),
		`xdotool mousemove --window "$history_win" 100 175 click 3; sleep 0.2; xdotool key --clearmodifiers Up Down Down Return; sleep 0.2`,
		`actual="$(timeout 1s xclip -selection clipboard -target UTF8_STRING -o 2>/dev/null | base64 -w0 || true)"; [ "$actual" = "$expected" ] || { printf 'history text mismatch: %s vs %s encoded characters' "${#actual}" "${#expected}"; xdotool key Escape Escape; exit 7; }`,
		`xdotool mousemove --window "$history_win" 100 175 click 3; sleep 0.2; xdotool key --clearmodifiers Up Down Return; sleep 0.7`,
		`found=0; for bubble_y in "$((main_height/2-30))" "$((main_height-180))"; do :`,
		"set_clip "+b64("native-check-"+randomID()),
		`xdotool mousemove --window "$win" 350 "$bubble_y" click 3; sleep 0.2; xdotool key --clearmodifiers Up Down Return; sleep 0.2`,
		`actual="$(timeout 1s xclip -selection clipboard -target UTF8_STRING -o 2>/dev/null | base64 -w0 || true)"; if [ "$actual" = "$expected" ]; then found=1; break; fi; xdotool key Escape`,
		`done; [ "$found" = 1 ] || exit 8`,
	)
	return strings.Join(script, "; ")
}

func visibleLocateScript(search, text string) string {
	b64 := func(s string) string { return shellQuoteSingle(base64.StdEncoding.EncodeToString([]byte(s))) }
	bubbleX := 350
	clear := `xdotool key --clearmodifiers Escape ctrl+a BackSpace`
	dismiss := `xdotool key Escape`
	if os.Getenv("WEBOX_DETACHED_CHAT") == "1" {
		bubbleX = 70
		clear = `xdotool key --clearmodifiers ctrl+a BackSpace`
		dismiss = `xdotool mousemove --window "$win" "$((WIDTH/2))" "$((HEIGHT-90))" click 1`
	}
	script := uiScriptPrelude()
	script = append(script, openChatScript(base64.StdEncoding.EncodeToString([]byte(search))),
		clear,
		`eval "$(xdotool getwindowgeometry --shell "$win")"; [ "$WIDTH" -eq 980 ] && [ "$HEIGHT" -eq 710 ] || exit 6`,
		"bubble_x="+strconv.Itoa(bubbleX),
		"expected="+b64(text),
		"set_clip "+b64("native-check-"+randomID()),
		`found=0; for bubble_y in $(seq "$((HEIGHT-180))" -18 100); do :`,
		`xdotool mousemove --window "$win" "$bubble_x" "$bubble_y" click 3; sleep 0.08; xdotool key --clearmodifiers Up Down Return; sleep 0.08`,
		`actual="$(timeout 0.3s xclip -selection clipboard -target UTF8_STRING -o 2>/dev/null | base64 -w0 || true)"; if [ "$actual" = "$expected" ]; then found=1; break; fi; `+dismiss,
		`done; [ "$found" = 1 ] || { printf 'original message is not visible'; exit 8; }`,
	)
	return strings.Join(script, "; ")
}

func runNativeScript(ctx context.Context, script string) (string, error) {
	output, err := exec.CommandContext(ctx, "timeout", "10s", "bash", "-lc", script).CombinedOutput()
	if err != nil {
		return "", fmt.Errorf("native interaction failed: %w: %s", err, strings.TrimSpace(string(output)))
	}
	return string(output), nil
}
