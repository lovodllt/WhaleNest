package wechatdb

import (
	"database/sql"
	"testing"
)

func TestContactAvatarUsesStableIDAndPrefersThumbnail(t *testing.T) {
	db, err := sql.Open("sqlite3", ":memory:")
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	mustExec(t, db, "CREATE TABLE contact(username TEXT,nick_name TEXT,small_head_url TEXT,big_head_url TEXT,delete_flag INTEGER)")
	mustExec(t, db, "INSERT INTO contact VALUES ('one','same name','small-one','big-one',0),('two','same name','','big-two',0),('deleted','same name','old','old',1)")
	store := &Store{dbs: map[string]*sql.DB{"contact/contact.db": db}}
	if value, err := store.ContactAvatarURL("one"); err != nil || value != "small-one" {
		t.Fatalf("thumbnail=%q err=%v", value, err)
	}
	if value, err := store.ContactAvatarURL("two"); err != nil || value != "big-two" {
		t.Fatalf("fallback=%q err=%v", value, err)
	}
	if _, err := store.ContactAvatarURL("same name"); err == nil {
		t.Fatal("nickname was treated as an account ID")
	}
	if _, err := store.ContactAvatarURL("deleted"); err == nil {
		t.Fatal("deleted contact was used")
	}
}
