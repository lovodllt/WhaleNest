ARG GO_BUILDER_IMAGE=golang:1.26-bookworm
ARG DEBIAN_RUNTIME_IMAGE=debian:bookworm-slim

FROM ${GO_BUILDER_IMAGE} AS build
ARG GOPROXY=https://proxy.golang.org,direct
ENV GOPROXY=${GOPROXY}
WORKDIR /src
COPY go.mod go.sum ./
RUN --mount=type=cache,target=/go/pkg/mod go mod download
COPY cmd ./cmd
COPY internal ./internal
COPY wecom ./wecom
RUN --mount=type=cache,target=/go/pkg/mod \
    --mount=type=cache,target=/root/.cache/go-build \
    mkdir -p /out && \
    CGO_ENABLED=1 go build -trimpath -ldflags="-s -w -extldflags=-s" -o /out/weagent ./cmd/weagent && \
    CGO_ENABLED=1 go build -trimpath -ldflags="-s -w -extldflags=-s" -o /out/native-media ./cmd/native-media && \
    CGO_ENABLED=1 go build -trimpath -ldflags="-s -w -extldflags=-s" -o /out/native-reply ./cmd/native-reply

FROM ${DEBIAN_RUNTIME_IMAGE} AS debian-base
ARG APT_DEBIAN_MIRROR=
ARG APT_DEBIAN_SECURITY_MIRROR=
RUN set -eux; \
    if [ -n "$APT_DEBIAN_MIRROR" ] && [ -f /etc/apt/sources.list.d/debian.sources ]; then \
      sed -i "s|http://deb.debian.org/debian\([[:space:]]\|$\)|$APT_DEBIAN_MIRROR\1|g" /etc/apt/sources.list.d/debian.sources; \
    fi; \
    if [ -n "$APT_DEBIAN_SECURITY_MIRROR" ] && [ -f /etc/apt/sources.list.d/debian.sources ]; then \
      sed -i "s|http://deb.debian.org/debian-security|$APT_DEBIAN_SECURITY_MIRROR|g; s|http://security.debian.org/debian-security|$APT_DEBIAN_SECURITY_MIRROR|g" /etc/apt/sources.list.d/debian.sources; \
    fi

FROM debian-base AS novnc-assets
RUN apt-get update && \
    apt-get install -y --no-install-recommends novnc && \
    mkdir -p /out && cp -a /usr/share/novnc/. /out/

FROM debian-base AS runtime-base
ENV DEBIAN_FRONTEND=noninteractive \
    LANG=zh_CN.UTF-8 \
    LC_ALL=zh_CN.UTF-8 \
    LIBGL_ALWAYS_SOFTWARE=1 \
    LD_LIBRARY_PATH=/webox/weagent/lib

RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
      ca-certificates dbus dpkg ffmpeg gosu libcap2-bin locales \
      openbox tini websockify x11vnc xclip xdotool xsettingsd xvfb \
      fonts-wqy-microhei fonts-noto-color-emoji \
      python3 python3-dbus python3-opencv at-spi2-core wmctrl pulseaudio pulseaudio-utils libasound2-plugins tesseract-ocr tesseract-ocr-chi-sim tesseract-ocr-eng \
      libatomic1 libnss3 libgbm1 libasound2 libpulse0 libxss1 libxdamage1 libxkbcommon-x11-0 \
      libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-render-util0 libxcb-xkb1 libxcb-cursor0 \
      libgtk-3-0 libatk1.0-0 libatk-bridge2.0-0 libatspi2.0-0 libcups2 \
      libxcomposite1 libxrandr2 libxfixes3 libxtst6 libxshmfence1 libdrm2; \
    sed -i 's/# zh_CN.UTF-8 UTF-8/zh_CN.UTF-8 UTF-8/' /etc/locale.gen; \
    locale-gen; \
    useradd -M -d /webox/state/home -u 1000 -s /bin/bash webox; \
    mkdir -p /webox/wechat /webox/weagent/bin /webox/state /webox/runtime; \
    chown -R webox:webox /webox; \
    apt-get clean; \
    rm -rf \
      /var/lib/apt/lists/* \
      /usr/share/man/* \
      /usr/share/locale/*

COPY --from=novnc-assets /out/ /usr/share/novnc/

FROM runtime-base AS runtime-wechat

RUN --mount=type=bind,source=docker/wechat,target=/tmp/wechat,ro \
    set -eux; \
    arch="$(dpkg --print-architecture)"; \
    case "$arch" in \
      amd64) deb="/tmp/wechat/WeChatLinux_x86_64.deb" ;; \
      arm64) deb="/tmp/wechat/WeChatLinux_arm64.deb" ;; \
      *) echo "unsupported architecture for bundled WeChat: $arch" >&2; exit 1 ;; \
    esac; \
    if [ ! -f "$deb" ]; then \
      echo "missing bundled WeChat package: $deb" >&2; \
      echo "put WeChatLinux_x86_64.deb or WeChatLinux_arm64.deb under docker/wechat before building" >&2; \
      exit 1; \
    fi; \
    dpkg-deb -x "$deb" /webox/wechat; \
    dpkg-deb -f "$deb" Version > /webox/wechat/.webox-version; \
    test -x /webox/wechat/opt/wechat/wechat

FROM runtime-wechat AS runtime

COPY --from=build /out/weagent /webox/weagent/bin/weagent
COPY --from=build /out/native-reply /webox/weagent/bin/native-reply
COPY --chmod=644 docker/helpers/ /webox/weagent/bin/
COPY --from=build /out/native-media /webox/weagent/bin/native-media
COPY docker/scripts/webox-identity.sh docker/scripts/entrypoint.sh /webox/weagent/bin/

RUN find /webox/weagent/bin -type d -exec chmod 755 {} + && \
    chmod 755 /webox/weagent/bin/weagent /webox/weagent/bin/*.sh && \
    setcap cap_sys_ptrace=ep /webox/weagent/bin/weagent

ENV WEBOX_ALL_CHATS=1 WEBOX_DETACHED_CHAT=1 WEBOX_FAST_UI=1 WEBOX_SKIP_POSTLOGIN_ESCAPE=1
COPY LICENSE THIRD_PARTY_NOTICES.md /usr/share/doc/dafeiyu-webox/
COPY LICENSES/ /usr/share/doc/dafeiyu-webox/LICENSES/
VOLUME ["/webox/state"]
EXPOSE 8080 6080

ENTRYPOINT ["/usr/bin/tini", "--", "/webox/weagent/bin/entrypoint.sh"]
