package wechatapi

import (
	"context"
	"net/http"

	"github.com/netcat-ai/webox/internal/sender"
)

type nativeSender interface {
	PrepareReply(context.Context, string, string) (string, error)
	CancelReply(context.Context, string) error
	Pat(context.Context, string, string) (sender.Receipt, error)
}

func (server *Server) interaction(response http.ResponseWriter, request *http.Request) {
	if !server.authenticate(response, request) {
		return
	}
	var body struct {
		Action  string `json:"action"`
		Room    string `json:"roomid"`
		Message string `json:"msgid"`
		Target  string `json:"target"`
		Token   string `json:"context_token"`
	}
	if err := decodeJSON(request, &body); err != nil {
		writeError(response, http.StatusBadRequest, err.Error())
		return
	}
	native, ok := server.sender.(nativeSender)
	if !ok {
		writeError(response, http.StatusNotImplemented, "native interactions unavailable")
		return
	}
	if body.Room == "" && body.Action != "cancel_reply" {
		writeError(response, http.StatusBadRequest, "roomid is required")
		return
	}
	server.sendMu.Lock()
	defer server.sendMu.Unlock()
	var err error
	var token string
	switch body.Action {
	case "prepare_reply":
		if body.Message == "" {
			writeError(response, http.StatusBadRequest, "msgid is required")
			return
		}
		token, err = native.PrepareReply(request.Context(), body.Room, body.Message)
	case "cancel_reply":
		err = native.CancelReply(request.Context(), body.Token)
	case "pat":
		if body.Target == "" {
			writeError(response, http.StatusBadRequest, "target is required")
			return
		}
		_, err = native.Pat(request.Context(), body.Room, body.Target)
	default:
		writeError(response, http.StatusBadRequest, "unsupported interaction")
		return
	}
	if err != nil {
		server.logger.Error("native interaction failed", "action", body.Action, "error", err)
		writeError(response, http.StatusConflict, err.Error())
		return
	}
	writeJSON(response, http.StatusOK, map[string]any{"ret": 0, "context_token": token})
}
