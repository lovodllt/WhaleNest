package wechatdb

import (
	"bytes"
	"crypto/md5"
	"database/sql"
	"encoding/hex"
	"fmt"
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestPackedImageMD5UsesMessageLocalImageField(t *testing.T) {
	fixtures := []struct{ packed, want string }{
		{"080110021a22222065656236653430333532666462643566303865323263326338303364333464305800", "eeb6e40352fdbd5f08e22c2c803d34d0"},
		{"080110021a22222065303763646635313038303063313262306237353130373035663538333335335800", "e07cdf510800c12b0b7510705f583353"},
	}
	for _, fixture := range fixtures {
		packed, err := hex.DecodeString(fixture.packed)
		if err != nil {
			t.Fatal(err)
		}
		if got := packedImageMD5(packed); got != fixture.want {
			t.Fatalf("local image MD5=%q, want %q", got, fixture.want)
		}
	}
	if got := packedImageMD5(append([]byte{0x22, 0x20}, []byte(fixtures[0].want)...)); got != "" {
		t.Fatal("accepted an MD5 outside image field 3")
	}
}

func TestMessageImageMD5RequiresExactLocationAndImageType(t *testing.T) {
	db, err := sql.Open("sqlite3", ":memory:")
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	roomID := "private-user"
	table := fmt.Sprintf("Msg_%x", md5.Sum([]byte(roomID)))
	mustExec(t, db, fmt.Sprintf("CREATE TABLE [%s] (local_id INTEGER, create_time INTEGER, local_type INTEGER, packed_info_data BLOB)", table))
	imageMD5 := "eeb6e40352fdbd5f08e22c2c803d34d0"
	packed := append([]byte{0x1a, 0x22, 0x22, 0x20}, []byte(imageMD5)...)
	mustExec(t, db, fmt.Sprintf("INSERT INTO [%s] VALUES (306,1000,3,?),(307,1000,1,?)", table), packed, packed)
	store := &Store{dbDir: t.TempDir(), keys: map[string]string{"message/message_0.db": "fixture"}, dbs: map[string]*sql.DB{"message/message_0.db": db}}
	if got, err := messageImageMD5(store, roomID, 306, 1000); err != nil || got != imageMD5 {
		t.Fatalf("exact image=%q err=%v", got, err)
	}
	if got, err := messageImageMD5(store, roomID, 306, 1001); err != nil || got != "" {
		t.Fatalf("different timestamp image=%q err=%v", got, err)
	}
	if got, err := messageImageMD5(store, roomID, 307, 1000); err != nil || got != "" {
		t.Fatalf("non-image message=%q err=%v", got, err)
	}
	if _, err := store.ReadImage(roomID, 306, 1000, ""); err != nil {
		t.Fatalf("local image MD5 unnecessarily queried absent resource database: %v", err)
	}
}

func TestFindImageDatsPrefersHighQualityThenStandardThenThumbnail(t *testing.T) {
	attachRoot := t.TempDir()
	roomID := "room@chatroom"
	imageMD5 := "0123456789abcdef0123456789abcdef"
	imageDir := filepath.Join(attachRoot, fmt.Sprintf("%x", md5.Sum([]byte(roomID))), "2026-08", "Img")
	if err := os.MkdirAll(imageDir, 0o700); err != nil {
		t.Fatal(err)
	}
	paths := map[string]string{
		"standard":  filepath.Join(imageDir, imageMD5+".dat"),
		"high":      filepath.Join(imageDir, imageMD5+"_h.dat"),
		"thumbnail": filepath.Join(imageDir, imageMD5+"_t.dat"),
	}
	for _, path := range paths {
		if err := os.WriteFile(path, []byte("fixture"), 0o600); err != nil {
			t.Fatal(err)
		}
	}
	now := time.Now().Add(imageThumbnailWait)
	if got := findImageDatsAt(attachRoot, roomID, imageMD5, now); len(got) != 3 || got[0] != paths["high"] || got[1] != paths["standard"] || got[2] != paths["thumbnail"] {
		t.Fatalf("all variants selected %#v, want high then standard then thumbnail", got)
	}
	if err := os.Remove(paths["high"]); err != nil {
		t.Fatal(err)
	}
	if got := findImageDatsAt(attachRoot, roomID, imageMD5, now); len(got) != 2 || got[0] != paths["standard"] || got[1] != paths["thumbnail"] {
		t.Fatalf("fallback variants selected %#v, want standard then thumbnail", got)
	}
	if err := os.Remove(paths["standard"]); err != nil {
		t.Fatal(err)
	}
	if got := findImageDatsAt(attachRoot, roomID, imageMD5, now); len(got) != 1 || got[0] != paths["thumbnail"] {
		t.Fatalf("thumbnail fallback selected %#v, want %q", got, paths["thumbnail"])
	}
}

func TestFindImageDatsDefersThumbnailForThreeSeconds(t *testing.T) {
	attachRoot := t.TempDir()
	roomID := "room@chatroom"
	imageMD5 := "0123456789abcdef0123456789abcdef"
	imageDir := filepath.Join(attachRoot, fmt.Sprintf("%x", md5.Sum([]byte(roomID))), "2026-08", "Img")
	if err := os.MkdirAll(imageDir, 0o700); err != nil {
		t.Fatal(err)
	}
	thumbnail := filepath.Join(imageDir, imageMD5+"_t.dat")
	if err := os.WriteFile(thumbnail, []byte("fixture"), 0o600); err != nil {
		t.Fatal(err)
	}
	writtenAt := time.Unix(1786106120, 0)
	if err := os.Chtimes(thumbnail, writtenAt, writtenAt); err != nil {
		t.Fatal(err)
	}
	if got := findImageDatsAt(attachRoot, roomID, imageMD5, writtenAt.Add(imageThumbnailWait-time.Nanosecond)); len(got) != 0 {
		t.Fatalf("fresh thumbnail selected before wait elapsed: %#v", got)
	}
	standard := filepath.Join(imageDir, imageMD5+".dat")
	if err := os.WriteFile(standard, []byte("fixture"), 0o600); err != nil {
		t.Fatal(err)
	}
	if got := findImageDatsAt(attachRoot, roomID, imageMD5, writtenAt.Add(time.Second)); len(got) != 1 || got[0] != standard {
		t.Fatalf("standard image did not bypass thumbnail wait: %#v", got)
	}
	if err := os.Remove(standard); err != nil {
		t.Fatal(err)
	}
	if got := findImageDatsAt(attachRoot, roomID, imageMD5, writtenAt.Add(imageThumbnailWait)); len(got) != 1 || got[0] != thumbnail {
		t.Fatalf("thumbnail selected at deadline %#v, want %q", got, thumbnail)
	}
}

func TestConvertWXGFRejectsInvalidHeader(t *testing.T) {
	if _, err := convertWXGFToJPEG([]byte("not a wxgf image")); err == nil {
		t.Fatal("non-WXGF input was accepted")
	}
}

func TestConvertWXGFFixture(t *testing.T) {
	path := os.Getenv("WEBOX_WXGF_TEST_FILE")
	if path == "" {
		t.Skip("WEBOX_WXGF_TEST_FILE is not set")
	}
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	jpeg, err := convertWXGFToJPEG(data)
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.HasPrefix(jpeg, []byte{0xff, 0xd8, 0xff}) {
		t.Fatalf("decoded output is not JPEG: %x", jpeg[:min(len(jpeg), 16)])
	}
	t.Logf("decoded %d-byte WXGF into %d-byte JPEG", len(data), len(jpeg))
}
