package wechatdb

import (
 "database/sql"
 "github.com/netcat-ai/webox/wecom"
)

func (store *Store) Emotions() ([]wecom.Emotion,error) {
 db,found,err:=store.database("emoticon/emoticon.db")
 if err!=nil || !found { return nil,err }
 rows,err:=db.Query("SELECT md5,cdn_url,thumb_url,encrypt_url FROM kNonStoreEmoticonTable LIMIT 100")
 if err!=nil { return nil,err }
 defer rows.Close()
 result:=make([]wecom.Emotion,0)
 for rows.Next() {
  var md5,cdn,thumb,encrypted sql.NullString
  if err:=rows.Scan(&md5,&cdn,&thumb,&encrypted);err!=nil {return nil,err}
  result=append(result,wecom.Emotion{MD5Sum:md5.String,CDNURL:cdn.String,ThumbURL:thumb.String,EncryptURL:encrypted.String})
 }
 return result,rows.Err()
}
