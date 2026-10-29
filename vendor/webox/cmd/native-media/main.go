package main

import (
	"crypto/sha256"
	"encoding/json"
	"errors"
	"fmt"
	"io"
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

type mediaRequest struct {
	wecom.Message
	Action   string `json:"action"`
	Username string `json:"username"`
}

func readRequest(input io.Reader) (mediaRequest, error) {
	var request mediaRequest
	if err := json.NewDecoder(input).Decode(&request); err != nil {
		return request, err
	}
	if request.Action == wecom.ActionSend {
		request.Action = ""
	}
	if request.Action != "" && request.Action != "contact_avatar" {
		return request, errors.New("unsupported media action")
	}
	if request.Action == "contact_avatar" && (request.Username == "" || len(request.Username) > 200) {
		return request, errors.New("a contact username is required")
	}
	if request.Action == "" && (request.RoomID == "" || request.MsgID == "" || request.Image == nil && request.MsgType != wecom.MessageTypeImage) {
		return request, errors.New("image message, roomid and msgid required")
	}
	return request, nil
}

func run() error {
	request, err := readRequest(os.Stdin)
	if err != nil {
		return err
	}
	message := request.Message
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
	if message.Sequence <= 0 || message.MsgTime <= 0 {
		localID, created, err := store.ImageLocation(message.RoomID, message.MsgID)
		if err != nil {
			return err
		}
		message.Sequence, message.MsgTime = localID, created*1000
	}
	md5 := ""
	if message.Image != nil {
		md5 = message.Image.MD5Sum
	}
	image, err := store.ReadImage(message.RoomID, message.Sequence, time.UnixMilli(message.MsgTime).Unix(), md5)
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
