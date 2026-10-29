package main

import (
	"strings"
	"testing"
)

func TestMediaRequestAcceptsReceivedImagesAndKeepsAvatarOperation(t *testing.T) {
	for _, body := range []string{
		`{"action":"send","roomid":"group","msgid":"123","localid":7,"msgtime":1000,"msgtype":"image","image":{}}`,
		`{"roomid":"group","msgid":"123","msgtype":"image"}`,
		`{"action":"contact_avatar","username":"friend"}`,
	} {
		request, err := readRequest(strings.NewReader(body))
		if err != nil {
			t.Fatalf("valid media request rejected: %v", err)
		}
		if request.Action == "send" {
			t.Fatal("received message action was confused with a media operation")
		}
	}
	for _, body := range []string{`{"action":"other"}`, `{"action":"send","msgtype":"text"}`, `{"action":"contact_avatar"}`} {
		if _, err := readRequest(strings.NewReader(body)); err == nil {
			t.Fatal("invalid media request accepted")
		}
	}
}
