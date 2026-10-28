package wechatdb

import (
	"encoding/binary"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
)

// A WCDB raw-key literal has a 32-byte repeating mask. Its public salt
// covers all 32 mask positions; opening the database still verifies the key.
func unmaskKey(blob []byte, salt string) string {
	if len(blob) != 99 || len(salt) != 32 {
		return ""
	}
	var pad [32]byte
	for i := range salt {
		pad[(66+i)%32] = blob[66+i] ^ salt[i]
	}
	var plain [99]byte
	for i, value := range blob {
		plain[i] = value ^ pad[i%32]
	}
	if (plain[0] != 'x' && plain[0] != 'X') || plain[1] != '\'' || plain[98] != '\'' || !isHexBytes(plain[2:98]) {
		return ""
	}
	return strings.ToLower(string(plain[2:66]))
}

func scanMaskedKeys(dbDir string, pids []int, salts map[string]string) ([]keyEntry, int) {
	missing := make(map[string]string)
	for salt, name := range salts {
		missing[salt] = name
	}
	var entries []keyEntry
	candidates := 0
	for _, pid := range pids {
		if len(missing) == 0 {
			break
		}
		regions, err := parseMaps(pid)
		if err != nil {
			continue
		}
		memory, err := os.Open(fmt.Sprintf("/proc/%d/mem", pid))
		if err != nil {
			continue
		}
		found, count := scanMaskedRegions(memory, regions, dbDir, missing)
		_ = memory.Close()
		entries = append(entries, found...)
		candidates += count
	}
	return entries, candidates
}

func scanMaskedRegions(memory io.ReaderAt, regions [][2]int64, dbDir string, missing map[string]string) ([]keyEntry, int) {
	var entries []keyEntry
	candidates := 0
	seen := make(map[int64]bool)
	buffer := make([]byte, chunkSize)
	for _, region := range regions {
		for address := region[0]; address < region[1] && len(missing) > 0; address += chunkSize - 16 {
			size := min(int64(len(buffer)), region[1]-address)
			n, _ := memory.ReadAt(buffer[:size], address)
			// Linux x86_64 WCDB buffers have an aligned pointer/length pair.
			for offset := 0; offset+16 <= n; offset += 8 {
				length := binary.LittleEndian.Uint64(buffer[offset+8 : offset+16])
				if length != 99 && length != 100 {
					continue
				}
				pointer := int64(binary.LittleEndian.Uint64(buffer[offset : offset+8]))
				if seen[pointer] {
					continue
				}
				readable := false
				for _, target := range regions {
					if target[0] <= pointer && pointer <= target[1]-99 {
						readable = true
						break
					}
				}
				if !readable {
					continue
				}
				seen[pointer] = true
				var blob [99]byte
				if count, _ := memory.ReadAt(blob[:], pointer); count != len(blob) {
					continue
				}
				candidates++
				for salt, name := range missing {
					key := unmaskKey(blob[:], salt)
					if key == "" {
						continue
					}
					db, err := openSQLCipher(filepath.Join(dbDir, filepath.FromSlash(name)), key)
					if err != nil {
						continue
					}
					_ = db.Close()
					entries = append(entries, keyEntry{dbName: name, key: key})
					delete(missing, salt)
				}
			}
		}
	}
	return entries, candidates
}
