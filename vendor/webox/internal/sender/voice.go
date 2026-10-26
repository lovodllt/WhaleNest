package sender

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"math"
	"os"
	"os/exec"
	"strconv"
	"strings"
	"time"
)

type VoiceError struct {
	Err        error
	BeforeSend bool
}

func (err *VoiceError) Error() string { return err.Err.Error() }
func (err *VoiceError) Unwrap() error { return err.Err }

func (service *Service) SendVoice(ctx context.Context, target, sharedPath string) (float64, error) {
	before := func(err error) (float64, error) { return 0, &VoiceError{Err: err, BeforeSend: true} }
	if target == "" || len(target) > 200 {
		return before(errors.New("recipient is empty or too long"))
	}
	if service.pending != nil {
		return before(errors.New("a native quoted reply is reserved"))
	}
	if service.media == nil {
		return before(errors.New("shared media store is unavailable"))
	}
	path, _, err := service.media.ResolveFile(target, sharedPath)
	if err != nil {
		return before(err)
	}
	seconds, err := inspectVoiceWAV(ctx, path)
	if err != nil {
		return before(err)
	}
	if err := inspectVoiceBus(ctx); err != nil {
		return before(err)
	}
	recipient, err := service.wechat.ResolveRecipient(target)
	if err != nil {
		return before(err)
	}
	positions, err := service.wechat.RoomMessagePositions(recipient.Username)
	if err != nil {
		return before(err)
	}
	script, err := nativeVoiceScript(base64.StdEncoding.EncodeToString([]byte(recipient.SearchTerm)), path, seconds)
	if err != nil {
		return before(err)
	}
	output, err := voiceCommand(ctx, "timeout", "80s", "bash", "-lc", script).CombinedOutput()
	if err != nil {
		return 0, &VoiceError{Err: fmt.Errorf("native voice failed: %w: %s", err, strings.TrimSpace(string(output))), BeforeSend: !strings.Contains(string(output), "VOICE_SEND_ATTEMPTED") && !strings.Contains(string(output), "VOICE_STATE_UNKNOWN")}
	}
	for range 20 {
		items, err := service.wechat.OutgoingItemsAfter(positions, recipient.Username)
		if err != nil {
			return 0, &VoiceError{Err: err, BeforeSend: false}
		}
		for _, item := range items {
			if item.Kind != "voice" {
				continue
			}
			_, millis, ok := strings.Cut(item.Value, "\x00")
			duration, err := strconv.Atoi(millis)
			if ok && err == nil && math.Abs(float64(duration)/1000-seconds) <= 2 {
				return float64(duration) / 1000, nil
			}
		}
		select {
		case <-ctx.Done():
			return 0, &VoiceError{Err: ctx.Err(), BeforeSend: false}
		case <-time.After(500 * time.Millisecond):
		}
	}
	return 0, &VoiceError{Err: errors.New("voice send was not verified in the intended conversation; no automatic resend"), BeforeSend: false}
}

func inspectVoiceWAV(ctx context.Context, path string) (float64, error) {
	output, err := exec.CommandContext(ctx, "ffprobe", "-v", "error", "-show_entries", "format=format_name,duration:stream=codec_name,channels", "-of", "json", path).Output()
	if err != nil {
		return 0, fmt.Errorf("inspect voice WAV: %w", err)
	}
	var probe struct {
		Format struct {
			Name     string `json:"format_name"`
			Duration string `json:"duration"`
		} `json:"format"`
		Streams []struct {
			Codec    string `json:"codec_name"`
			Channels int    `json:"channels"`
		} `json:"streams"`
	}
	if err := json.Unmarshal(output, &probe); err != nil {
		return 0, err
	}
	seconds, err := strconv.ParseFloat(probe.Format.Duration, 64)
	if err != nil || math.IsNaN(seconds) || math.IsInf(seconds, 0) || seconds < 1 || seconds > 55 {
		return 0, errors.New("voice WAV must last between 1 and 55 seconds")
	}
	if probe.Format.Name != "wav" || len(probe.Streams) != 1 || probe.Streams[0].Codec != "pcm_s16le" || probe.Streams[0].Channels < 1 || probe.Streams[0].Channels > 2 {
		return 0, errors.New("voice input must be a mono or stereo PCM16 WAV")
	}
	return seconds, nil
}

func voiceCommand(ctx context.Context, name string, args ...string) *exec.Cmd {
	command := exec.CommandContext(ctx, name, args...)
	command.Env = append(os.Environ(), "PULSE_SERVER=unix:/webox/runtime/pulse/native")
	return command
}

func inspectVoiceBus(ctx context.Context) error {
	if _, err := os.Stat("/.dockerenv"); err != nil {
		return errors.New("native voice requires the isolated WeChat container")
	}
	if _, err := os.Stat("/dev/snd"); !errors.Is(err, os.ErrNotExist) {
		return errors.New("native voice refuses a container with host sound devices")
	}
	modules, err := voiceCommand(ctx, "pactl", "list", "short", "modules").Output()
	if err != nil {
		return fmt.Errorf("inspect container audio modules: %w", err)
	}
	var sinks, sources []struct {
		Name  string `json:"name"`
		Owner int    `json:"owner_module"`
	}
	for _, query := range []struct {
		Name  string
		Value any
	}{{"sinks", &sinks}, {"sources", &sources}} {
		output, err := voiceCommand(ctx, "pactl", "-f", "json", "list", query.Name).Output()
		if err != nil {
			return fmt.Errorf("inspect container audio %s: %w", query.Name, err)
		}
		if err := json.Unmarshal(output, query.Value); err != nil {
			return err
		}
	}
	if len(sinks) != 1 || sinks[0].Name != "voice_bus" {
		return errors.New("container audio must have only the silent voice_bus sink")
	}
	bus, mic := false, false
	for _, line := range strings.Split(strings.TrimRight(string(modules), "\r\n"), "\n") {
		module := strings.SplitN(line, "\t", 4)
		if len(module) < 3 {
			return errors.New("invalid PulseAudio short module entry")
		}
		index, err := strconv.Atoi(module[0])
		if err != nil {
			return err
		}
		if index == sinks[0].Owner && module[1] == "module-null-sink" {
			bus = true
		}
		if module[1] == "module-remap-source" && strings.Contains(" "+module[2]+" ", " master=voice_bus.monitor ") {
			for _, source := range sources {
				if source.Name == "dafeiyu_mic" && source.Owner == index {
					mic = true
				}
			}
		}
	}
	if !bus || !mic {
		return errors.New("silent voice_bus and its dafeiyu_mic remap were not verified")
	}
	return nil
}

func nativeVoiceScript(search, path string, seconds float64) (string, error) {
	if os.Getenv("WEBOX_FAST_UI") != "1" {
		return "", errors.New("native voice requires the verified fixed-size WeChat layout")
	}
	script := uiScriptPrelude()
	script = append(script, openChatScript(search),
		`eval "$(xdotool getwindowgeometry --shell "$win")"; [ "$WIDTH" -eq 980 ] && [ "$HEIGHT" -eq 710 ] || { echo 'unsupported recording layout'; exit 4; }`,
		`python3 - <<'PY'
import json, subprocess
streams = json.loads(subprocess.check_output(['pactl','-f','json','list','source-outputs']))
if any(s.get('properties',{}).get('application.process.binary') in ('wechat','WeChatAppEx') for s in streams):
    raise SystemExit('WeChat already has an active recording; refusing another')
PY`,
		`native_voice_active=0; native_voice_attempted=0; cleanup_voice() { status=$?; if [ "$native_voice_active" = 1 ] && [ "$native_voice_attempted" = 0 ]; then python3 /webox/state/weagent/ui_locator.py --window "$win" --layout /webox/state/weagent/ui_layout.json click voice_cancel || printf '\nVOICE_STATE_UNKNOWN\n'; fi; cleanup_clip; return "$status"; }; trap cleanup_voice EXIT`,
		`python3 /webox/state/weagent/ui_locator.py --window "$win" --layout /webox/state/weagent/ui_layout.json click voice_start || exit 4; native_voice_active=1`,
		"python3 - "+shellQuoteSingle(path)+" "+strconv.FormatFloat(seconds, 'f', 3, 64)+` <<'PY'
import json, subprocess, sys, time
for _ in range(30):
    streams = json.loads(subprocess.check_output(['pactl','-f','json','list','source-outputs']))
    active = [s for s in streams if s.get('properties',{}).get('application.process.binary') in ('wechat','WeChatAppEx')]
    if active:
        if len(active) != 1:
            raise SystemExit('ambiguous WeChat recording streams')
        subprocess.run(['pactl','move-source-output',str(active[0]['index']),'dafeiyu_mic'],check=True)
        time.sleep(.2)
        subprocess.run(['paplay','--device=voice_bus',sys.argv[1]],check=True,timeout=float(sys.argv[2])+5)
        time.sleep(.1)
        break
    time.sleep(.1)
else:
    raise SystemExit('WeChat recording stream did not appear; no audio injected')
PY`,
		`printf '\nVOICE_SEND_ATTEMPTED\n'; native_voice_attempted=1; python3 /webox/state/weagent/ui_locator.py --window "$win" --layout /webox/state/weagent/ui_layout.json click voice_send; native_voice_active=0; sleep 0.3`,
	)
	return strings.Join(script, "\n"), nil
}
