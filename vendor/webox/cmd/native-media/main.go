package main

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"time"

	"github.com/netcat-ai/webox/internal/sharedmedia"
	"github.com/netcat-ai/webox/internal/wechatdb"
	"github.com/netcat-ai/webox/wecom"
)

func main() {
	if err := run(); err != nil {
		fmt.Fprintln(os.Stderr, "native-media:", err)
		os.Exit(1)
	}
}

func run() error {
	var message wecom.Message
	if err := json.NewDecoder(os.Stdin).Decode(&message); err != nil {
		return err
	}
	if message.Image == nil || message.RoomID == "" || message.Sequence <= 0 || message.MsgTime <= 0 || message.MsgID == "" {
		return errors.New("image message, roomid, msgid, localid and msgtime required")
	}
	raw, err := os.ReadFile("/webox/state/weagent/wechat.key")
	if err != nil {
		return err
	}
	var key struct {
		DBDir string            `json:"dbDir"`
		Keys  map[string]string `json:"keys"`
	}
	if err := json.Unmarshal(raw, &key); err != nil {
		return err
	}
	store, err := wechatdb.Open(key.DBDir, key.Keys)
	if err != nil {
		return err
	}
	defer store.Close()
	image, err := store.ReadImage(message.RoomID, message.Sequence, time.UnixMilli(message.MsgTime).Unix(), message.Image.MD5Sum)
	if err != nil {
		return err
	}
	if image == nil {
		return json.NewEncoder(os.Stdout).Encode(map[string]any{"ret": 0, "sdkfileid": ""})
	}
	sharedDir := os.Getenv("WEBOX_SHARED_DIR")
	if sharedDir == "" {
		sharedDir = "/webox/state/shared"
	}
	media, err := sharedmedia.New(sharedDir)
	if err != nil {
		return err
	}
	path, err := media.WriteInbox(message.RoomID, message.MsgID, image.Data, image.ContentType)
	if err != nil {
		return err
	}
	return json.NewEncoder(os.Stdout).Encode(map[string]any{"ret": 0, "sdkfileid": path})
}
