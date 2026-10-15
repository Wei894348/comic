# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'album_card.ui'
##
## Created by: Qt User Interface Compiler version 6.10.3
##
## WARNING! All changes made in this file will be lost when recompiling UI file!
################################################################################

from PySide6.QtCore import (QCoreApplication, QDate, QDateTime, QLocale,
    QMetaObject, QObject, QPoint, QRect,
    QSize, QTime, QUrl, Qt)
from PySide6.QtGui import (QBrush, QColor, QConicalGradient, QCursor,
    QFont, QFontDatabase, QGradient, QIcon,
    QImage, QKeySequence, QLinearGradient, QPainter,
    QPalette, QPixmap, QRadialGradient, QTransform)
from PySide6.QtWidgets import (QApplication, QFrame, QHBoxLayout, QLabel,
    QSizePolicy, QVBoxLayout, QWidget)

class Ui_AlbumCardForm(object):
    def setupUi(self, albumCard):
        if not albumCard.objectName():
            albumCard.setObjectName(u"albumCard")
        albumCard.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.albumCheckmark = QLabel(albumCard)
        self.albumCheckmark.setObjectName(u"albumCheckmark")
        self.albumCheckmark.setGeometry(QRect(12, 12, 24, 24))
        self.albumCheckmark.setMinimumSize(QSize(24, 24))
        self.albumCheckmark.setMaximumSize(QSize(24, 24))
        self.albumCheckmark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.albumMeta = QLabel(albumCard)
        self.albumMeta.setObjectName(u"albumMeta")
        self.albumMeta.setGeometry(QRect(30, 12, 180, 20))
        self.albumMeta.setAlignment(Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignVCenter)
        self.albumCardLayout = QVBoxLayout(albumCard)
        self.albumCardLayout.setSpacing(0)
        self.albumCardLayout.setObjectName(u"albumCardLayout")
        self.albumCardLayout.setContentsMargins(8, 8, 8, 8)
        self.albumCover = QLabel(albumCard)
        self.albumCover.setObjectName(u"albumCover")
        self.albumCover.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.albumCardLayout.addWidget(self.albumCover)

        self.albumTitle = QLabel(albumCard)
        self.albumTitle.setObjectName(u"albumTitle")
        self.albumTitle.setMinimumSize(QSize(0, 34))
        self.albumTitle.setMaximumSize(QSize(16777215, 34))
        self.albumTitle.setAlignment(Qt.AlignmentFlag.AlignLeading|Qt.AlignmentFlag.AlignLeft|Qt.AlignmentFlag.AlignTop)
        self.albumTitle.setWordWrap(True)

        self.albumCardLayout.addWidget(self.albumTitle)

        self.albumTagsLayout = QHBoxLayout()
        self.albumTagsLayout.setSpacing(4)
        self.albumTagsLayout.setObjectName(u"albumTagsLayout")
        self.albumTagsLayout.setContentsMargins(0, 0, 0, 0)

        self.albumCardLayout.addLayout(self.albumTagsLayout)


        self.retranslateUi(albumCard)

        QMetaObject.connectSlotsByName(albumCard)
    # setupUi

    def retranslateUi(self, albumCard):
        self.albumCheckmark.setText(QCoreApplication.translate("AlbumCardForm", u"\u2713", None))
        self.albumMeta.setText("")
        self.albumCover.setText("")
        self.albumTitle.setText("")
        pass
    # retranslateUi

