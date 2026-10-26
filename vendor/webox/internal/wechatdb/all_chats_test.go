package wechatdb

import (
 "database/sql"
 "testing"
)

func TestAllChatsIncludesUnmarkedContactsButRejectsAmbiguousSearch(t *testing.T) {
 t.Setenv("WEBOX_ALL_CHATS", "1")
 db, err := sql.Open("sqlite3", ":memory:")
 if err != nil { t.Fatal(err) }
 defer db.Close()
 mustExec(t, db, "CREATE TABLE contact(username TEXT,nick_name TEXT,remark TEXT,alias TEXT,delete_flag INTEGER)")
 mustExec(t, db, "INSERT INTO contact VALUES ('human','Alice','','alice-id',0),('group@chatroom','测试群','','',0),('gh_service','公告','','',0)")
 names, err := loadEnabledRooms(db)
 if err != nil || len(names)!=2 { t.Fatalf("rooms=%v err=%v",names,err) }
 contacts, err := contactsByRemarkFromDB(db, "")
 if err != nil || len(contacts)!=3 { t.Fatalf("contacts=%v err=%v",contacts,err) }
 store:=&Store{dbs:map[string]*sql.DB{"contact/contact.db":db}}
 t.Setenv("WEBOX_LEGACY_INPUT_FOCUS", "1")
 if _,err=store.ResolveRecipient("group@chatroom", "bot"); err==nil { t.Fatal("unmarked legacy group accepted") }
 mustExec(t, db, "UPDATE contact SET remark='webox.group.example' WHERE username='group@chatroom'")
 if recipient,err:=store.ResolveRecipient("group@chatroom", "bot"); err!=nil || recipient.SearchTerm!="webox.group.example" { t.Fatalf("marked group=%v err=%v",recipient,err) }
 recipient, err := store.ResolveRecipient("human", "bot")
 if err != nil || recipient.SearchTerm!="Alice" { t.Fatalf("recipient=%v err=%v",recipient,err) }
 mustExec(t, db, "INSERT INTO contact VALUES ('other','Alice','','',0)")
 if _,err=store.ResolveRecipient("human", "bot"); err==nil { t.Fatal("ambiguous name accepted") }
}
