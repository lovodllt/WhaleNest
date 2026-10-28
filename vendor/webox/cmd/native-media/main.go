package main

import (
	"crypto/sha256"
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
	var request struct {
		wecom.Message
		Action   string `json:"action"`
		Username string `json:"username"`
	}
	if err := json.NewDecoder(os.Stdin).Decode(&request); err != nil {
		return err
	}
	message := request.Message
	if request.Action != "" && request.Action != "contact_avatar" {
		return errors.New("unsupported media action")
	}
	if request.Action == "contact_avatar" && (request.Username == "" || len(request.Username) > 200) {
		return errors.New("a contact username is required")
	}
	if request.Action == "" && (message.Image == nil || message.RoomID == "" || message.Sequence <= 0 || message.MsgTime <= 0 || message.MsgID == "") {
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
	if request.Action == "contact_avatar" {
		url, err := store.ContactAvatarURL(request.Username)
		if err != nil {
			return err
		}
		return json.NewEncoder(os.Stdout).Encode(map[string]any{"ret": 0, "username": request.Username, "account": fmt.Sprintf("%x", sha256.Sum256([]byte(key.DBDir))), "avatar_url": url})
	}
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
