from pathlib import Path
import subprocess

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPainter, QPixmap


ROOT = Path(__file__).resolve().parents[1]
ICONSET = ROOT / "build" / "BaiwangConnect.iconset"
ICONSET.mkdir(parents=True, exist_ok=True)
app = QGuiApplication([])


def render(size: int, path: Path):
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor("#176BFF"))
    painter.setPen(Qt.PenStyle.NoPen)
    margin = max(2, int(size * 0.06))
    painter.drawRoundedRect(margin, margin, size - margin * 2, size - margin * 2, size * 0.23, size * 0.23)
    painter.setPen(QColor("white"))
    painter.setFont(QFont("Helvetica Neue", int(size * 0.43), QFont.Weight.Bold))
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "B")
    painter.end()
    pixmap.save(str(path), "PNG")


for logical in (16, 32, 128, 256, 512):
    render(logical, ICONSET / f"icon_{logical}x{logical}.png")
    render(logical * 2, ICONSET / f"icon_{logical}x{logical}@2x.png")

subprocess.run(["iconutil", "-c", "icns", str(ICONSET), "-o", str(ROOT / "assets" / "BaiwangConnect.icns")], check=True)
