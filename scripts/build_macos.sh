#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ ! -x .venv/bin/python ]]; then
  /opt/homebrew/bin/python3.12 -m venv .venv
fi

.venv/bin/pip install -r requirements-dev.txt

if [[ ! -f assets/BaiwangConnect.icns ]]; then
  echo "缺少 assets/BaiwangConnect.icns；请先运行 scripts/make_icon.py 生成图标。" >&2
  exit 1
fi

LIBUSB="$(brew --prefix libusb)/lib/libusb-1.0.dylib"
if [[ ! -f "$LIBUSB" ]]; then
  echo "libusb 未安装，请先执行：brew install libusb" >&2
  exit 1
fi

.venv/bin/pyinstaller \
  --noconfirm \
  --clean \
  --windowed \
  --name "DJI 4G Dongle Manager" \
  --osx-bundle-identifier "com.goodday00.baiwang-connect" \
  --icon assets/BaiwangConnect.icns \
  --paths src \
  --add-binary "$LIBUSB:lib" \
  launcher.py

# Documents may be managed by Apple's File Provider, which adds Finder xattrs
# that codesign rejects. Sign in a clean temporary directory, archive there,
# then extract the verified bundle back into dist.
SIGN_DIR="$(mktemp -d /tmp/baiwang-connect-sign.XXXXXX)"
trap 'rm -rf "$SIGN_DIR"' EXIT
ditto --norsrc --noextattr "dist/DJI 4G Dongle Manager.app" "$SIGN_DIR/DJI 4G Dongle Manager.app"
xattr -rc "$SIGN_DIR/DJI 4G Dongle Manager.app"
codesign --force --deep --sign - "$SIGN_DIR/DJI 4G Dongle Manager.app"
codesign --verify --deep --strict "$SIGN_DIR/DJI 4G Dongle Manager.app"
rm -f "dist/DJI-4G-Dongle-Manager-macOS-arm64.zip"
(cd "$SIGN_DIR" && /usr/bin/zip -qry -X -y "$ROOT/dist/DJI-4G-Dongle-Manager-macOS-arm64.zip" "DJI 4G Dongle Manager.app")

echo "构建完成：$ROOT/dist/DJI 4G Dongle Manager.app"
echo "发布压缩包：$ROOT/dist/DJI-4G-Dongle-Manager-macOS-arm64.zip"
