from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
ICONSET = ROOT / "build" / "4GDongleManager.iconset"
ICONSET.mkdir(parents=True, exist_ok=True)
SOURCE = ROOT / "assets" / "4g-dongle-icon.png"
if not SOURCE.exists():
    raise SystemExit("缺少 assets/4g-dongle-icon.png")


def render(size: int, path: Path):
    subprocess.run(
        ["sips", "-z", str(size), str(size), str(SOURCE), "--out", str(path)],
        check=True,
        stdout=subprocess.DEVNULL,
    )


for logical in (16, 32, 128, 256, 512):
    render(logical, ICONSET / f"icon_{logical}x{logical}.png")
    render(logical * 2, ICONSET / f"icon_{logical}x{logical}@2x.png")

subprocess.run(["iconutil", "-c", "icns", str(ICONSET), "-o", str(ROOT / "assets" / "4GDongleManager.icns")], check=True)
