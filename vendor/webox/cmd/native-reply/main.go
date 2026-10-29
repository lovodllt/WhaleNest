package main

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"syscall"
	"time"

	"github.com/netcat-ai/webox/internal/config"
	"github.com/netcat-ai/webox/internal/sender"
	"github.com/netcat-ai/webox/internal/sharedmedia"
	"github.com/netcat-ai/webox/internal/wechat"
)

func main() {
	if err := run(); err != nil {
		failure := map[string]any{"error": err.Error()}
		if len(os.Args) > 1 && os.Args[1] == "--voice" {
			failure["before_send"] = true
			var voiceError *sender.VoiceError
			if errors.As(err, &voiceError) {
				failure["before_send"] = voiceError.BeforeSend
			}
		}
		json.NewEncoder(os.Stdout).Encode(failure)
		os.Exit(1)
	}
}

func run() error {
	if len(os.Args) != 3 {
		return fmt.Errorf("room and reference are required")
	}
	os.Setenv("WEBOX_SKIP_POSTLOGIN_ESCAPE", "1")
	configuration, err := config.Load()
	if err != nil {
		return err
	}
	lock, err := os.OpenFile(filepath.Join(configuration.StateDir, "ui-send.lock"), os.O_CREATE|os.O_RDWR, 0600)
	if err != nil {
		return err
	}
	defer lock.Close()
	if err := syscall.Flock(int(lock.Fd()), syscall.LOCK_EX); err != nil {
		return err
	}
	previous, _ := exec.Command("xdotool", "getactivewindow").Output()
	defer func() {
		if window := strings.TrimSpace(string(previous)); window != "" {
			ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
			defer cancel()
			_ = exec.CommandContext(ctx, "xdotool", "windowactivate", window).Run()
		}
	}()
	state := wechat.New(configuration.StateDir)
	ready, err := state.InitializeIfReady()
	if err != nil {
		return err
	}
	if ready != wechat.Ready {
		return fmt.Errorf("WeChat is not ready")
	}
	media, err := sharedmedia.New(configuration.SharedDir)
	if err != nil {
		return err
	}
	service := sender.New(state, media)
	ctx, cancel := context.WithTimeout(context.Background(), 4*time.Minute)
	defer cancel()
	if os.Args[1] == "--voice" {
		var request struct{ SharedPath string }
		if err := json.NewDecoder(os.Stdin).Decode(&request); err != nil {
			return err
		}
		seconds, err := service.SendVoice(ctx, os.Args[2], request.SharedPath)
		if err != nil {
			return err
		}
		if err := json.NewEncoder(os.Stdout).Encode(map[string]any{"ret": 0, "voice_seconds": seconds}); err != nil {
			return &sender.VoiceError{Err: err, BeforeSend: false}
		}
		return nil
	}
	if os.Args[1] == "--send" {
		var items []sender.Item
		if err := json.NewDecoder(os.Stdin).Decode(&items); err != nil {
			return err
		}
		if _, err := service.Send(ctx, os.Args[2], items); err != nil {
			return err
		}
		return json.NewEncoder(os.Stdout).Encode(map[string]int{"ret": 0})
	}
	token, err := service.PrepareReply(ctx, os.Args[1], os.Args[2])
	if err != nil {
		return err
	}
	defer service.CancelReply(context.Background(), token)
	json.NewEncoder(os.Stdout).Encode(map[string]string{"context_token": token})
	var command struct {
		Action string
		Text   string
		Items  []sender.Item
	}
	if err := json.NewDecoder(os.Stdin).Decode(&command); err != nil {
		return err
	}
	if command.Action == "cancel" {
		if err := service.CancelReply(ctx, token); err != nil {
			return err
		}
	} else if command.Action == "send" {
		items := command.Items
		if len(items) == 0 {
			items = []sender.Item{{Kind: "reply", Text: command.Text}}
		}
		items[0].ReferenceID = os.Args[2]
		items[0].ContextToken = token
		_, err = service.Send(ctx, os.Args[1], items)
		if err != nil {
			return err
		}
	} else {
		return fmt.Errorf("unknown action")
	}
	return json.NewEncoder(os.Stdout).Encode(map[string]int{"ret": 0})
}
