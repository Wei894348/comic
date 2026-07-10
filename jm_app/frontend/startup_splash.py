from __future__ import annotations

import sys
from pathlib import Path

from PyQt5.QtCore import QElapsedTimer, QEventLoop, QSize, QTimer, Qt
from PyQt5.QtGui import QColor, QMovie, QPixmap
from PyQt5.QtWidgets import QApplication, QGraphicsDropShadowEffect, QLabel, QVBoxLayout, QWidget


class StartupSplash(QWidget):
    def __init__(self) -> None:
        super().__init__(
            None,
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool,
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setStyleSheet("background: transparent;")
        self.setFixedSize(280, 230)
        self._movie: QMovie | None = None
        self._timer = QElapsedTimer()
        self._dot_count = 0
        self._text_timer = QTimer(self)
        self._text_timer.timeout.connect(self._tick_text)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.setAlignment(Qt.AlignCenter)

        self.pet_label = QLabel()
        self.pet_label.setAlignment(Qt.AlignCenter)
        self.pet_label.setFixedSize(160, 150)

        self.text_label = QLabel("正在启动中")
        self.text_label.setObjectName("startupSplashText")
        self.text_label.setAlignment(Qt.AlignCenter)
        self.text_label.setStyleSheet(
            """
            QLabel#startupSplashText {
                color: #ffffff;
                font-size: 24px;
                font-weight: 800;
                font-family: "Microsoft YaHei UI", "Segoe UI";
                padding-top: 2px;
            }
            """
        )
        self._add_shadow(self.text_label, QColor(25, 118, 210, 230), blur=18, y=2)

        self.hint_label = QLabel("请稍候")
        self.hint_label.setObjectName("startupSplashHint")
        self.hint_label.setAlignment(Qt.AlignCenter)
        self.hint_label.setStyleSheet(
            """
            QLabel#startupSplashHint {
                color: #e8f2ff;
                font-size: 14px;
                font-weight: 600;
                font-family: "Microsoft YaHei UI", "Segoe UI";
            }
            """
        )
        self._add_shadow(self.hint_label, QColor(15, 23, 42, 220), blur=12, y=1)

        layout.addWidget(self.pet_label, 0, Qt.AlignHCenter)
        layout.addWidget(self.text_label)
        layout.addWidget(self.hint_label)

        self._load_pet_image()

    def show_centered(self) -> None:
        desktop = QApplication.desktop()
        geometry = desktop.availableGeometry(desktop.primaryScreen())
        self.move(geometry.center() - self.rect().center())
        self.show()
        self.raise_()
        self._timer.start()
        self._text_timer.start(420)
        QApplication.processEvents()

    def finish(self, minimum_ms: int = 0) -> None:
        if minimum_ms > 0 and self._timer.isValid():
            remaining = minimum_ms - self._timer.elapsed()
            if remaining > 0:
                loop = QEventLoop(self)
                QTimer.singleShot(remaining, loop.quit)
                loop.exec_()
        self._text_timer.stop()
        if self._movie:
            self._movie.stop()
        self.close()
        QApplication.processEvents()

    def _tick_text(self) -> None:
        self._dot_count = (self._dot_count + 1) % 4
        self.text_label.setText("正在启动中" + "." * self._dot_count)

    @staticmethod
    def _add_shadow(label: QLabel, color: QColor, blur: int, y: int) -> None:
        shadow = QGraphicsDropShadowEffect(label)
        shadow.setColor(color)
        shadow.setBlurRadius(blur)
        shadow.setOffset(0, y)
        label.setGraphicsEffect(shadow)

    def _load_pet_image(self) -> None:
        path = self._pet_image_path()
        if path and path.suffix.lower() == ".gif":
            movie = QMovie(str(path))
            if movie.isValid():
                movie.setScaledSize(QSize(150, 140))
                self.pet_label.setMovie(movie)
                self._movie = movie
                movie.start()
                return

        if path:
            pixmap = QPixmap(str(path))
            if not pixmap.isNull():
                self.pet_label.setPixmap(
                    pixmap.scaled(
                        self.pet_label.size(),
                        Qt.KeepAspectRatio,
                        Qt.SmoothTransformation,
                    )
                )
                return

        self.pet_label.setText("JM")
        self.pet_label.setStyleSheet("color:#1976d2;font-size:42px;font-weight:800;")

    @staticmethod
    def _pet_image_path() -> Path | None:
        roots = []
        if hasattr(sys, "_MEIPASS"):
            roots.append(Path(getattr(sys, "_MEIPASS")))
        project_root = Path(__file__).resolve().parents[2]
        roots.extend([project_root, Path.cwd()])

        candidates: list[Path] = []
        for root in roots:
            candidates.extend(
                [
                    root / "assets" / "gifs" / "idle4.gif",
                    root / "assets" / "gifs" / "ameath.gif",
                    root / "desktop_pet" / "assets" / "gifs" / "idle4.gif",
                    root / "desktop_pet" / "assets" / "gifs" / "ameath.gif",
                    root / "assets" / "iconv2_256x256.jpg",
                ]
            )
        for candidate in candidates:
            if candidate.exists():
                return candidate
        return None
