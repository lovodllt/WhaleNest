package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"path/filepath"

	"github.com/netcat-ai/webox/internal/wechatdb"
)

type keyFile struct {
	WXID  string            `json:"wxid"`
	DBDir string            `json:"dbDir"`
	Keys  map[string]string `json:"keys"`
}

func main() {
	if err := run(); err != nil {
		fmt.Fprintf(os.Stderr, "diagnostic: %v\n", err)
		os.Exit(1)
	}
}

func run() error {
	refresh := flag.Bool("refresh", false, "validate fresh database keys from WeChat memory")
	source := flag.String("source", "/diagnostic/source-messages.json", "source message locations")
	output := flag.String("output", "/diagnostic/refreshed-wechat.key", "new key file; never the live key file")
	imageDir := flag.String("images", "/diagnostic/recovered", "directory for verified image output")
	flag.Parse()
	var key keyFile
	if *refresh {
		init, err := wechatdb.InitFromMemory()
		if err != nil {
			return err
		}
		key = keyFile{WXID: init.WXID, DBDir: init.DBDir, Keys: init.Keys}
	} else {
		raw, err := os.ReadFile("/webox/state/weagent/wechat.key")
		if err != nil {
			return err
		}
		if err := json.Unmarshal(raw, &key); err != nil {
			return err
		}
	}
	store, err := wechatdb.Open(key.DBDir, key.Keys)
	if err != nil {
		return err
	}
	defer store.Close()
	var messages []struct {
		Room  string `json:"roomid"`
		Local int64  `json:"localid"`
		Time  int64  `json:"msgtime"`
		Image struct {
			MD5 string `json:"md5sum"`
		} `json:"image"`
	}
	raw, err := os.ReadFile(*source)
	if err != nil {
		return err
	}
	if err := json.Unmarshal(raw, &messages); err != nil {
		return err
	}
	var recovered []*wechatdb.MediaFile
	for _, message := range messages {
		media, err := store.ReadImage(message.Room, message.Local, message.Time/1000, message.Image.MD5)
		if err != nil {
			return fmt.Errorf("local_id=%d: %w", message.Local, err)
		}
		if media == nil {
			return fmt.Errorf("local_id=%d: no image", message.Local)
		}
		recovered = append(recovered, media)
		fmt.Printf("local_id=%d: ok type=%s bytes=%d\n", message.Local, media.ContentType, len(media.Data))
	}
	if *refresh {
		if len(recovered) != 2 {
			return fmt.Errorf("expected two verified images, got %d", len(recovered))
		}
		if filepath.Clean(*output) == "/webox/state/weagent/wechat.key" {
			return fmt.Errorf("refusing to replace live key file")
		}
		if err := os.MkdirAll(*imageDir, 0700); err != nil {
			return err
		}
		for _, media := range recovered {
			if err := os.WriteFile(filepath.Join(*imageDir, media.Filename), media.Data, 0600); err != nil {
				return err
			}
		}
		raw, err := json.Marshal(key)
		if err != nil {
			return err
		}
		file, err := os.OpenFile(*output, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0600)
		if err != nil {
			return err
		}
		_, writeErr := file.Write(raw)
		closeErr := file.Close()
		if writeErr != nil {
			return writeErr
		}
		if closeErr != nil {
			return closeErr
		}
		fmt.Printf("saved validated key material and %d images\n", len(recovered))
	}
	return nil
}
