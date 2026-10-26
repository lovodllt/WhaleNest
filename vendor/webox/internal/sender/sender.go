package sender

import (
	"context"
	"crypto/rand"
	"encoding/base64"
	"encoding/hex"
	"errors"
	"fmt"
	"net/url"
	"os"
	"os/exec"
	"regexp"
	"strings"
	"time"

	"github.com/netcat-ai/webox/internal/sharedmedia"
	"github.com/netcat-ai/webox/internal/wechat"
	"github.com/netcat-ai/webox/internal/wechatdb"
)

const maxTextLength = 5000

type Service struct {
	wechat  *wechat.State
	media   *sharedmedia.Store
	pending *pendingReply
}

type Receipt struct {
	ClientMessageID string
}

type Item struct {
	Kind         string
	Text         string
	Mention      string
	SharedPath   string
	ReferenceID  string
	ContextToken string
}

type preparedItem struct {
	Kind        string
	Text        string
	Mention     string
	Path        string
	ContentType string
	Filename    string
	ReferenceID string
}

func New(state *wechat.State, media *sharedmedia.Store) *Service {
	return &Service{wechat: state, media: media}
}

func (service *Service) Send(ctx context.Context, target string, items []Item) (Receipt, error) {
	if target == "" || len(target) > 200 {
		return Receipt{}, errors.New("recipient is empty or too long")
	}
	if len(items) == 0 {
		return Receipt{}, errors.New("message items are empty")
	}
	if service.pending != nil && time.Now().After(service.pending.expires) {
		if err := service.CancelReply(ctx, service.pending.token); err != nil {
			return Receipt{}, err
		}
	}
	if service.pending != nil {
		if items[0].Kind != "reply" || target != service.pending.room || items[0].ContextToken != service.pending.token || items[0].ReferenceID != service.pending.reference {
			return Receipt{}, errors.New("a native quoted reply is reserved")
		}
	} else if items[0].Kind == "reply" {
		return Receipt{}, errors.New("prepare the native quoted reply first")
	}
	prepared, err := service.prepareItems(target, items)
	if err != nil {
		return Receipt{}, err
	}
	recipient, err := service.wechat.ResolveRecipient(target)
	if err != nil {
		return Receipt{}, err
	}
	positions, err := service.wechat.RoomMessagePositions(recipient.Username)
	if err != nil {
		return Receipt{}, err
	}
	receipt := Receipt{ClientMessageID: randomID()}
	if os.Getenv("WEBOX_UI_SEND_DRY_RUN") == "1" {
		return receipt, nil
	}
	search := base64.StdEncoding.EncodeToString([]byte(recipient.SearchTerm))
	script := sendItemsScript(search, prepared)
	if prepared[0].Mention != "" {
		anchor, err := service.nativeAnchor(target, prepared[0].ReferenceID, prepared[0].Mention)
		if err != nil {
			return Receipt{}, err
		}
		locate := nativeLocateScript(recipient.SearchTerm, anchor.Text.Content)
		locate += `; xdotool mousemove --window "$win" 310 "$((bubble_y-16))" click 3; sleep 0.2; xdotool key --clearmodifiers Up Down Return; sleep 0.3`
		script = strings.Replace(script, openChatScript(search), locate, 1)
	}
	if service.pending != nil {
		script = sendPreparedReplyScript(service.pending.window, prepared)
		token := service.pending.token
		defer func() {
			if service.pending != nil {
				service.CancelReply(context.WithoutCancel(ctx), token)
			}
		}()
	}
	if err := runUIScript(ctx, "80s", script, "send message"); err != nil {
		return Receipt{}, err
	}
	service.pending = nil
	for range 20 {
		found, err := service.verifyItems(positions, recipient.Username, prepared)
		if err != nil {
			return Receipt{}, fmt.Errorf("verify sent message in WeChat db: %w", err)
		}
		if found {
			return receipt, nil
		}
		select {
		case <-ctx.Done():
			return Receipt{}, ctx.Err()
		case <-time.After(500 * time.Millisecond):
		}
	}
	return Receipt{}, errors.New("send verification failed: not every item was found in WeChat db")
}

func (service *Service) prepareItems(target string, items []Item) ([]preparedItem, error) {
	if len(items) == 0 {
		return nil, errors.New("message items are empty")
	}
	prepared := make([]preparedItem, 0, len(items))
	for _, item := range items {
		switch item.Kind {
		case "reply":
			if strings.TrimSpace(item.Text) == "" || len(item.Text) > maxTextLength || item.ReferenceID == "" {
				return nil, errors.New("reply title and parent msgid are required")
			}
			prepared = append(prepared, preparedItem{Kind: "reply", Text: item.Text, ReferenceID: item.ReferenceID})
		case "text":
			if strings.TrimSpace(item.Text) == "" || len(item.Text) > maxTextLength {
				return nil, errors.New("text is empty or too long")
			}
			if item.Mention != "" && ((item.Mention != os.Getenv("WEBOX_MENTION_OWNER") && item.ReferenceID == "") || !strings.HasSuffix(target, "@chatroom") || len(prepared) != 0) {
				return nil, errors.New("native mention requires the owner or a sender-matched message reference in the first group text item")
			}
			prepared = append(prepared, preparedItem{Kind: "text", Text: item.Text, Mention: item.Mention, ReferenceID: item.ReferenceID})
		case "image":
			if service.media == nil {
				return nil, errors.New("shared media store is unavailable")
			}
			path, contentType, err := service.media.ResolveImage(target, item.SharedPath)
			if err != nil {
				return nil, err
			}
			prepared = append(prepared, preparedItem{Kind: "image", Path: path, ContentType: contentType})
		case "file":
			if service.media == nil {
				return nil, errors.New("shared media store is unavailable")
			}
			path, filename, err := service.media.ResolveFile(target, item.SharedPath)
			if err != nil {
				return nil, err
			}
			prepared = append(prepared, preparedItem{Kind: "file", Path: path, Filename: filename})
		default:
			return nil, fmt.Errorf("unsupported message item kind %q", item.Kind)
		}
	}
	return prepared, nil
}

func (service *Service) verifyItems(positions wechatdb.RoomMessagePositions, username string, items []preparedItem) (bool, error) {
	sent, err := service.wechat.OutgoingItemsAfter(positions, username)
	if err != nil {
		return false, err
	}
	return containsItems(sent, items), nil
}

func containsItems(sent []wechatdb.OutgoingItem, expected []preparedItem) bool {
	counts := make(map[wechatdb.OutgoingItem]int, len(sent))
	for _, item := range sent {
		counts[item]++
	}
	for _, item := range expected {
		key := wechatdb.OutgoingItem{Kind: item.Kind}
		if item.Kind == "reply" {
			key.Value = item.ReferenceID + "\x00" + item.Text
		} else if item.Kind == "text" {
			key.Value = item.Text
		} else if item.Kind == "file" {
			key.Value = item.Filename
		}
		if item.Mention != "" {
			key = wechatdb.OutgoingItem{Kind: "mention"}
			for candidate, count := range counts {
				target, text, _ := strings.Cut(candidate.Value, "\x00")
				if count > 0 && candidate.Kind == "mention" && target == item.Mention && strings.HasPrefix(text, "@") && strings.HasSuffix(text, item.Text) {
					key = candidate
					break
				}
			}
		}
		if counts[key] == 0 {
			return false
		}
		counts[key]--
	}
	return true
}

func sendItemsScript(searchBase64 string, items []preparedItem) string {
	script := uiScriptPrelude()
	script = append(script, openChatScript(searchBase64))
	for _, item := range items {
		switch {
		case item.Kind == "text" || item.Kind == "reply":
			script = append(script,
				"set_clip "+shellQuoteSingle(base64.StdEncoding.EncodeToString([]byte(item.Text))),
				"paste_clip",
				"sleep 0.2",
			)
		case item.Kind == "image" && item.ContentType != "image/gif":
			script = append(script,
				"cleanup_clip",
				"xclip -selection clipboard -target "+shellQuoteSingle(item.ContentType)+" -loops 5 -i "+shellQuoteSingle(item.Path)+" >/dev/null 2>&1 & clip_pid=$!",
				"sleep 0.25",
				"paste_clip",
				"sleep 1",
			)
		case item.Kind == "file", item.Kind == "image" && item.ContentType == "image/gif":
			fileURL := (&url.URL{Scheme: "file", Path: item.Path}).String() + "\r\n"
			script = append(script,
				"cleanup_clip",
				"printf '%s' "+shellQuoteSingle(base64.StdEncoding.EncodeToString([]byte(fileURL)))+" | base64 -d | xclip -selection clipboard -target text/uri-list -loops 5 -i >/dev/null 2>&1 & clip_pid=$!",
				"sleep 0.25",
				"paste_clip",
				"sleep 1",
			)
		}
		script = append(script,
			"xdotool key --clearmodifiers Return",
			"sleep 0.2",
		)
	}
	if os.Getenv("WEBOX_FAST_UI") != "1" {
		script = append(script, "xdotool key --clearmodifiers ctrl+2", "sleep 0.2")
	}
	return strings.Join(script, "; ")
}

func uiScriptPrelude() []string {
	windowSearch := `win="$(xdotool search --onlyvisible --class 'wechat' 2>/dev/null | tail -n1 || true)"`
	if os.Getenv("WEBOX_FAST_UI") == "1" {
		windowSearch = `win=""; for candidate in $(xdotool search --onlyvisible --class 'wechat' 2>/dev/null); do ` +
			`eval "$(xdotool getwindowgeometry --shell "$candidate")"; ` +
			`if [ "$WIDTH" -ge 700 ] && [ "$HEIGHT" -ge 500 ]; then win="$candidate"; break; fi; done`
	}
	if os.Getenv("WEBOX_DETACHED_CHAT") == "1" {
		windowSearch = `win=""; active="$(xdotool getactivewindow 2>/dev/null || true)"; active_name="$(xdotool getwindowname "$active" 2>/dev/null || true)"; ` +
			`if [[ "$active_name" =~ ^webox\. ]]; then win="$active"; else ` + windowSearch + `; fi`
	}
	return []string{
		"set -e",
		`display="${DISPLAY:-}"`,
		`if [ -z "$display" ]; then for x in /tmp/.X11-unix/X*; do [ -e "$x" ] || continue; display=":${x##*X}"; break; done; fi`,
		`export DISPLAY="${display:-:1}"`,
		`command -v xclip >/dev/null 2>&1 || { echo "xclip not installed" >&2; exit 127; }`,
		`command -v xdotool >/dev/null 2>&1 || { echo "xdotool not installed" >&2; exit 127; }`,
		`clip_pid=""`,
		`cleanup_clip() { if [ -n "${clip_pid:-}" ]; then kill "$clip_pid" 2>/dev/null || true; wait "$clip_pid" 2>/dev/null || true; clip_pid=""; fi; }`,
		`set_clip() { cleanup_clip; printf '%s' "$1" | base64 -d | xclip -selection clipboard -target UTF8_STRING -loops 5 -i >/dev/null 2>&1 & clip_pid=$!; sleep 0.25; }`,
		`paste_clip() { xdotool key --clearmodifiers ctrl+v; for i in $(seq 1 30); do if ! kill -0 "$clip_pid" 2>/dev/null; then wait "$clip_pid" 2>/dev/null || true; clip_pid=""; sleep 0.1; return 0; fi; sleep 0.1; done; echo "wechat did not read clipboard" >&2; return 3; }`,
		`trap cleanup_clip EXIT`,
		windowSearch,
		`[ -n "$win" ] || { active="$(xdotool getactivewindow 2>/dev/null || true)"; active_name=""; if [ -n "$active" ]; then active_name="$(xdotool getwindowname "$active" 2>/dev/null || true)"; case "$active_name" in *微信*|*WeChat*) win="$active";; esac; fi; }`,
		`[ -n "$win" ] || win="$(xdotool search --onlyvisible --name '微信' 2>/dev/null | tail -n1 || true)"`,
		`[ -n "$win" ] || win="$(xdotool search --onlyvisible --name 'WeChat' 2>/dev/null | tail -n1 || true)"`,
		`[ -n "$win" ] || { echo "visible WeChat window not found" >&2; exit 2; }`,
		`xdotool windowactivate "$win"`,
		`if [ "${WEBOX_DETACHED_CHAT:-}" = "1" ]; then python3 /webox/state/weagent/ui_quote_reply.py cleanup; fi`,
		`if [ "${WEBOX_FAST_UI:-}" = "1" ]; then wmctrl -ir "$win" -b remove,maximized_vert,maximized_horz; sleep 0.1; xdotool windowsize --sync "$win" 980 710; fi`,
		"sleep 0.2",
	}
}

func openChatScript(queryBase64 string) string {
	query, _ := base64.StdEncoding.DecodeString(queryBase64)
	if os.Getenv("WEBOX_DETACHED_CHAT") == "1" {
		return detachedChatScript(string(query), queryBase64)
	}
	if os.Getenv("WEBOX_FAST_UI") == "1" && regexp.MustCompile(`^webox\.[A-Za-z0-9_.-]{1,42}$`).Match(query) {
		return fmt.Sprintf(`if [ "${WEBOX_SKIP_POSTLOGIN_ESCAPE:-}" != "1" ]; then xdotool key --clearmodifiers Escape; fi; eval "$(xdotool getwindowgeometry --shell "$win")"; `+
			`[ "$WIDTH" -eq 980 ] && [ "$HEIGHT" -eq 710 ] || exit 4; `+
			`if python3 /webox/state/weagent/ui_ready.py "$win" %s header 0; then printf 'UI_ROUTE:reuse\n'; else `+
			`xdotool key --clearmodifiers ctrl+f; sleep 0.1; xdotool key --clearmodifiers ctrl+a BackSpace; `+
			`set_clip %s; paste_clip; `+
			`python3 /webox/state/weagent/ui_ready.py "$win" %s search 3 || { echo 'search target not ready' >&2; exit 4; }; `+
			`xdotool key --clearmodifiers Return; `+
			`python3 /webox/state/weagent/ui_ready.py "$win" %s header 3 || { echo 'chat target not ready' >&2; exit 4; }; `+
			`printf 'UI_ROUTE:search\n'; fi; `+
			`xdotool mousemove --window "$win" "$((WIDTH/2))" "$((HEIGHT-90))" click 1`,
			shellQuoteSingle(string(query)), shellQuoteSingle(queryBase64), shellQuoteSingle(string(query)), shellQuoteSingle(string(query)))
	}
	script := fmt.Sprintf(
		`main_win="$(xdotool search --onlyvisible --class 'wechat' 2>/dev/null | tail -n1 || true)"; `+
			`if [ -n "$main_win" ]; then win="$main_win"; xdotool windowactivate "$win"; xdotool windowraise "$win" 2>/dev/null || true; sleep 0.2; fi; `+
			`if [ "${WEBOX_SKIP_POSTLOGIN_ESCAPE:-}" != "1" ]; then xdotool key --clearmodifiers Escape; fi; sleep 0.1; `+
			`xdotool key --clearmodifiers ctrl+f; sleep 0.3; `+
			`xdotool key --clearmodifiers ctrl+a BackSpace; sleep 0.2; `+
			`set_clip %s; paste_clip; sleep 1.8; `+
			`xdotool key --clearmodifiers Return; sleep 1.5`,
		shellQuoteSingle(queryBase64),
	)
	// WeChat Linux 4.1.1.8 opens search results without focusing its editor.
	// Keep this fallback opt-in for the isolated, fixed-layout legacy client.
	if os.Getenv("WEBOX_LEGACY_INPUT_FOCUS") == "1" {
		script += `; eval "$(xdotool getwindowgeometry --shell "$win")"; ` +
			`[ "$WIDTH" -ge 700 ] && [ "$HEIGHT" -ge 500 ] || exit 4; ` +
			`xdotool mousemove --window "$win" "$((WIDTH / 2))" "$((HEIGHT - 90))" click 1; sleep 0.2`
	}
	return script
}

func detachedChatScript(query, encoded string) string {
	return `expected=` + shellQuoteSingle(query) + `; [ -n "$expected" ] || exit 4; ` +
		`title_matches() { [[ "$1" = "$expected" ]] || [[ "$1" =~ ^"$expected"[[:space:]]*\([0-9]+\)$ ]] || python3 /webox/state/weagent/ui_accessible.py header "$2" "$expected" >/dev/null 2>&1; }; ` +
		`find_detached() { detached=""; for candidate in $(xdotool search --onlyvisible --class wechat 2>/dev/null); do ` +
		`title="$(xdotool getwindowname "$candidate" 2>/dev/null || true)"; if title_matches "$title" "$candidate"; then detached="$candidate"; break; fi; done; }; ` +
		`find_detached; if [ -z "$detached" ]; then main=""; ` +
		`for candidate in $(xdotool search --onlyvisible --class wechat 2>/dev/null); do title="$(xdotool getwindowname "$candidate" 2>/dev/null || true)"; case "$title" in 微信|WeChat) main="$candidate"; break;; esac; done; ` +
		`[ -n "$main" ] || { echo 'WeChat main window not found'; exit 4; }; win="$main"; xdotool windowactivate "$win"; ` +
		`wmctrl -ir "$win" -b remove,maximized_vert,maximized_horz; sleep 0.1; xdotool windowsize --sync "$win" 980 710; ` +
		`if ! python3 /webox/state/weagent/ui_accessible.py chat "$expected" >/dev/null 2>&1; then ` +
		`xdotool key --clearmodifiers ctrl+f; sleep 0.1; xdotool key --clearmodifiers ctrl+a BackSpace; set_clip ` + shellQuoteSingle(encoded) + `; paste_clip; xdotool key --clearmodifiers Return; ` +
		`for attempt in $(seq 1 10); do python3 /webox/state/weagent/ui_accessible.py chat "$expected" >/dev/null 2>&1 && break; sleep 0.1; done; fi; ` +
		`for attempt in $(seq 1 30); do find_detached; [ -n "$detached" ] && break; sleep 0.1; done; fi; ` +
		`[ -n "$detached" ] || { echo 'target detached chat not found'; exit 4; }; win="$detached"; ` +
		`xdotool windowactivate "$win"; wmctrl -ir "$win" -b remove,maximized_vert,maximized_horz; sleep 0.1; xdotool windowmove --sync "$win" 200 80; xdotool windowsize --sync "$win" 980 710; ` +
		`eval "$(xdotool getwindowgeometry --shell "$win")"; [ "$WIDTH" -eq 980 ] && [ "$HEIGHT" -eq 710 ] || exit 4; ` +
		`title_matches "$(xdotool getwindowname "$win")" "$win" || { echo 'detached chat title mismatch'; exit 4; }; ` +
		`python3 /webox/state/weagent/ui_locator.py --window "$win" --layout /webox/state/weagent/ui_layout.json click editor || exit 4; printf 'UI_ROUTE:detached\n'`
}

func runUIScript(ctx context.Context, timeout, script, action string) error {
	output, err := exec.CommandContext(ctx, "timeout", timeout, "bash", "-lc", script).CombinedOutput()
	if err == nil {
		if os.Getenv("WEBOX_FAST_UI") == "1" {
			fmt.Fprint(os.Stderr, string(output))
		}
		return nil
	}
	return fmt.Errorf("%s failed: %w: %s", action, err, strings.TrimSpace(string(output)))
}

func shellQuoteSingle(value string) string {
	return "'" + strings.ReplaceAll(value, "'", `'"'"'`) + "'"
}

func randomID() string {
	value := make([]byte, 16)
	if _, err := rand.Read(value); err != nil {
		return strconvFallbackID()
	}
	return hex.EncodeToString(value)
}

func strconvFallbackID() string {
	return fmt.Sprintf("%032x", time.Now().UnixNano())
}
