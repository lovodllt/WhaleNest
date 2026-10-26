#!/usr/bin/env bash
set -euo pipefail

export WEBOX_ROOT="${WEBOX_ROOT:-/webox}"
export DISPLAY="${DISPLAY:-:1}"
export WEBOX_STATE_DIR="${WEBOX_STATE_DIR:-${WEBOX_ROOT}/state}"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-${WEBOX_ROOT}/runtime}"
export WEBOX_XVFB_FBDIR="${WEBOX_XVFB_FBDIR:-${XDG_RUNTIME_DIR}/xvfb}"
export WEBOX_HOME="${WEBOX_HOME:-${WEBOX_STATE_DIR}/home}"
export WEBOX_WX_HOME="${WEBOX_WX_HOME:-${WEBOX_HOME}}"
export HOME="$WEBOX_HOME"
export WECHAT_BIN="${WECHAT_BIN:-${WEBOX_ROOT}/wechat/opt/wechat/wechat}"
export WEBOX_WEAGENT_STATE_DIR="${WEBOX_WEAGENT_STATE_DIR:-${WEBOX_STATE_DIR}/weagent}"

target_uid="${WEBOX_UID:-1000}"
if [ "$(id -u webox)" != "$target_uid" ]; then usermod -o -u "$target_uid" webox; fi

mkdir -p "$WEBOX_ROOT" "$WEBOX_STATE_DIR" "$XDG_RUNTIME_DIR" "$WEBOX_XVFB_FBDIR" "$HOME"
ownership_marker="${WEBOX_STATE_DIR}/.webox-owned-v1"
if [ "$(cat "$ownership_marker" 2>/dev/null || true)" != "$(id -u webox)" ]; then
  chown -R webox:webox "$WEBOX_STATE_DIR" "$XDG_RUNTIME_DIR"
  gosu webox sh -c 'id -u > "$1"' sh "$ownership_marker"
else
  chown webox:webox "$WEBOX_STATE_DIR" "$XDG_RUNTIME_DIR" "$WEBOX_XVFB_FBDIR" "$HOME"
fi
chmod 700 "$XDG_RUNTIME_DIR"

"${WEBOX_ROOT}/weagent/bin/webox-identity.sh"

critical_pids=()
critical_names=()

register_critical() {
  critical_names+=("$1")
  critical_pids+=("$2")
}

stop_children() {
  trap - TERM INT EXIT
  for pid in "${critical_pids[@]}"; do
    kill "$pid" 2>/dev/null || true
  done
  wait 2>/dev/null || true
}

terminate() {
  echo "[entrypoint] stopping"
  stop_children
  exit 143
}

wait_critical() {
  trap terminate TERM INT
  trap stop_children EXIT
  while true; do
    set +e
    wait -n
    local status=$?
    set -e
    for i in "${!critical_pids[@]}"; do
      local pid="${critical_pids[$i]}"
      if ! kill -0 "$pid" 2>/dev/null; then
        echo "[entrypoint] critical process exited: ${critical_names[$i]} pid=$pid status=$status" >&2
        stop_children
        exit "$status"
      fi
    done
  done
}

start_display() {
  local display_id="${DISPLAY#:}" lock_pid
  if [ -f "/tmp/.X${display_id}-lock" ]; then
    lock_pid="$(tr -d '[:space:]' < "/tmp/.X${display_id}-lock")"
    if ! kill -0 "$lock_pid" 2>/dev/null; then
      rm -f "/tmp/.X${display_id}-lock" "/tmp/.X11-unix/X${display_id}"
    fi
  fi
  # Match WeChat's UID so the X server can attach its MIT-SHM buffers.
  gosu webox Xvfb "$DISPLAY" -screen 0 "${WEBOX_SCREEN:-1280x800x24}" -fbdir "$WEBOX_XVFB_FBDIR" -nolisten tcp &
  register_critical xvfb "$!"
  sleep 1

  gosu webox openbox &
  register_critical openbox "$!"

  gosu webox x11vnc \
    -display "$DISPLAY" \
    -forever \
    -shared \
    -nopw \
    -noshm -noxdamage \
    -listen 127.0.0.1 \
    -rfbport 5900 &
  register_critical x11vnc "$!"

  websockify --web=/usr/share/novnc 0.0.0.0:6080 127.0.0.1:5900 &
  register_critical novnc "$!"

  local xsettings="${WEBOX_STATE_DIR}/xsettingsd.conf"
  cat > "$xsettings" <<'EOF'
Xft/Antialias 1
Xft/Hinting 1
Xft/HintStyle "hintslight"
Xft/RGBA "rgb"
Xft/DPI 98304
Gtk/FontName "WenQuanYi Micro Hei 10"
EOF
  chown webox:webox "$xsettings"
  gosu webox xsettingsd --config="$xsettings" &
}

start_agent() {
  local agent="${WEBOX_ROOT}/weagent/bin/weagent"
  echo "[entrypoint] starting agent: $agent"
  gosu webox "$agent" &
  register_critical weagent "$!"
}

start_wechat() {
  if [ ! -x "$WECHAT_BIN" ]; then
    echo "[entrypoint] bundled wechat binary is missing: $WECHAT_BIN" >&2
    exit 1
  fi
  # Crashpad reports are telemetry and must not grow the persistent account volume.
  local crashinfo="${XDG_RUNTIME_DIR}/crashinfo"
  gosu webox mkdir -p "$HOME/.xwechat" "$crashinfo"
  rm -rf "$HOME/.xwechat/crashinfo"
  gosu webox ln -s "$crashinfo" "$HOME/.xwechat/crashinfo"
  echo "[entrypoint] starting wechat"
  gosu webox dbus-run-session -- "$WECHAT_BIN" &
  register_critical wechat "$!"
}

start_display
export PULSE_SERVER="unix:${XDG_RUNTIME_DIR}/pulse/native"
gosu webox mkdir -p "${XDG_RUNTIME_DIR}/pulse"
rm -f "${XDG_RUNTIME_DIR}/pulse/pid" "${XDG_RUNTIME_DIR}/pulse/native"
gosu webox pulseaudio --daemonize=yes --exit-idle-time=-1 --log-target="file:${XDG_RUNTIME_DIR}/pulse.log"
gosu webox pactl load-module module-null-sink sink_name=voice_bus sink_properties=device.description=VoiceBus
gosu webox pactl load-module module-remap-source master=voice_bus.monitor source_name=dafeiyu_mic source_properties=device.description=DafeiyuMic
gosu webox pactl set-default-sink voice_bus
gosu webox pactl set-default-source dafeiyu_mic
unset QT_QUICK_BACKEND
export QSG_RENDER_LOOP=basic
export QT_XCB_GL_INTEGRATION=xcb_egl
export QT_LINUX_ACCESSIBILITY_ALWAYS_ON=1
export WEBOX_SKIP_POSTLOGIN_ESCAPE=1
gosu webox mkdir -p "$WEBOX_WEAGENT_STATE_DIR"
for helper in native-reply ui_accessible.py ui_locator.py ui_template.py ui_quote_reply.py ui_voice_text.py ui_ready.py native-media; do
  gosu webox cp "${WEBOX_ROOT}/weagent/bin/$helper" "${WEBOX_WEAGENT_STATE_DIR}/$helper"
done
if [ ! -f "${WEBOX_WEAGENT_STATE_DIR}/ui_layout.json" ]; then
  gosu webox cp "${WEBOX_ROOT}/weagent/bin/ui_layout.json" "${WEBOX_WEAGENT_STATE_DIR}/ui_layout.json"
fi
start_agent
start_wechat
wait_critical
