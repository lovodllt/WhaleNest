package wechatdb

import (
	"bytes"
	"database/sql"
	"encoding/binary"
	"encoding/hex"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestMaskedKeysRequireWorkingDatabaseKey(t *testing.T) {
	root := t.TempDir()
	path := filepath.Join(root, "session.db")
	key := strings.Repeat("12", 32)
	db, err := sql.Open("sqlite3", path+"?_pragma_key=x'"+key+"'&_pragma_cipher_page_size=4096")
	if err != nil {
		t.Fatal(err)
	}
	mustExec(t, db, "CREATE TABLE SessionTable (value INTEGER)")
	if err := db.Close(); err != nil {
		t.Fatal(err)
	}
	page, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	salt := hex.EncodeToString(page[:16])
	for _, valid := range []bool{false, true} {
		memory := make([]byte, chunkSize+4096)
		candidate := key
		if !valid {
			candidate = strings.Repeat("34", 32)
		}
		blob := []byte("x'" + candidate + salt + "'")
		for i := range blob {
			blob[i] ^= byte(71 + i%32)
		}
		copy(memory[512:], blob)
		// Put the descriptor across a chunk boundary, with a duplicate nearby.
		for _, offset := range []int{chunkSize - 8, chunkSize + 128} {
			binary.LittleEndian.PutUint64(memory[offset:], 512)
			binary.LittleEndian.PutUint64(memory[offset+8:], 100)
		}
		if len(searchKeyPatterns(memory)) != 0 {
			t.Fatal("fixture unexpectedly contains a plaintext key")
		}
		found, count := scanMaskedRegions(bytes.NewReader(memory), [][2]int64{{0, int64(len(memory))}}, root, map[string]string{salt: "session.db"})
		if count != 1 {
			t.Fatalf("candidate count=%d, expected one deduplicated buffer", count)
		}
		if valid {
			if len(found) != 1 || found[0].key != key || found[0].dbName != "session.db" {
				t.Fatal("verified masked database key was not recovered")
			}
		} else if len(found) != 0 {
			t.Fatal("syntactically valid but incorrect database key was accepted")
		}
	}
}
