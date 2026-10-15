# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'navigation.ui'
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
    QPushButton, QScrollArea, QSizePolicy, QSpacerItem,
    QVBoxLayout, QWidget)

class Ui_NavigationPanel(object):
    def setupUi(self, navigationPanel):
        if not navigationPanel.objectName():
            navigationPanel.setObjectName(u"navigationPanel")
        navigationPanel.setMinimumSize(QSize(200, 0))
        navigationPanel.setMaximumSize(QSize(200, 16777215))
        self.navigationLayout = QVBoxLayout(navigationPanel)
        self.navigationLayout.setSpacing(8)
        self.navigationLayout.setObjectName(u"navigationLayout")
        self.navigationLayout.setContentsMargins(18, 4, 18, 12)
        self.navScroll = QScrollArea(navigationPanel)
        self.navScroll.setObjectName(u"navScroll")
        self.navScroll.setFrameShape(QFrame.NoFrame)
        self.navScroll.setWidgetResizable(True)
        self.navScrollContent = QWidget()
        self.navScrollContent.setObjectName(u"navScrollContent")
        self.navMenuLayout = QVBoxLayout(self.navScrollContent)
        self.navMenuLayout.setSpacing(3)
        self.navMenuLayout.setObjectName(u"navMenuLayout")
        self.navMenuLayout.setContentsMargins(0, 4, 0, 0)
        self.navNavigationSectionLabel = QLabel(self.navScrollContent)
        self.navNavigationSectionLabel.setObjectName(u"navNavigationSectionLabel")

        self.navMenuLayout.addWidget(self.navNavigationSectionLabel)

        self.navHomeButton = QPushButton(self.navScrollContent)
        self.navHomeButton.setObjectName(u"navHomeButton")
        self.navHomeButton.setCheckable(True)

        self.navMenuLayout.addWidget(self.navHomeButton)

        self.navCategoryRankButton = QPushButton(self.navScrollContent)
        self.navCategoryRankButton.setObjectName(u"navCategoryRankButton")
        self.navCategoryRankButton.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

        self.navMenuLayout.addWidget(self.navCategoryRankButton)

        self.navWeeklyButton = QPushButton(self.navScrollContent)
        self.navWeeklyButton.setObjectName(u"navWeeklyButton")
        self.navWeeklyButton.setCheckable(True)
        self.navWeeklyButton.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

        self.navMenuLayout.addWidget(self.navWeeklyButton)

        self.navDownloadButton = QPushButton(self.navScrollContent)
        self.navDownloadButton.setObjectName(u"navDownloadButton")
        self.navDownloadButton.setCheckable(True)

        self.navMenuLayout.addWidget(self.navDownloadButton)

        self.navDivider = QFrame(self.navScrollContent)
        self.navDivider.setObjectName(u"navDivider")
        self.navDivider.setFrameShape(QFrame.HLine)
        self.navDivider.setFrameShadow(QFrame.Sunken)

        self.navMenuLayout.addWidget(self.navDivider)

        self.navUserSectionLabel = QLabel(self.navScrollContent)
        self.navUserSectionLabel.setObjectName(u"navUserSectionLabel")

        self.navMenuLayout.addWidget(self.navUserSectionLabel)

        self.navFavoriteButton = QPushButton(self.navScrollContent)
        self.navFavoriteButton.setObjectName(u"navFavoriteButton")
        self.navFavoriteButton.setCheckable(True)

        self.navMenuLayout.addWidget(self.navFavoriteButton)

        self.navCommentButton = QPushButton(self.navScrollContent)
        self.navCommentButton.setObjectName(u"navCommentButton")
        self.navCommentButton.setCheckable(True)

        self.navMenuLayout.addWidget(self.navCommentButton)

        self.navRemoteHistoryButton = QPushButton(self.navScrollContent)
        self.navRemoteHistoryButton.setObjectName(u"navRemoteHistoryButton")
        self.navRemoteHistoryButton.setCheckable(True)

        self.navMenuLayout.addWidget(self.navRemoteHistoryButton)

        self.navLocalFavoriteButton = QPushButton(self.navScrollContent)
        self.navLocalFavoriteButton.setObjectName(u"navLocalFavoriteButton")
        self.navLocalFavoriteButton.setCheckable(True)

        self.navMenuLayout.addWidget(self.navLocalFavoriteButton)

        self.navHistoryButton = QPushButton(self.navScrollContent)
        self.navHistoryButton.setObjectName(u"navHistoryButton")
        self.navHistoryButton.setCheckable(True)

        self.navMenuLayout.addWidget(self.navHistoryButton)

        self.navSupportDivider = QFrame(self.navScrollContent)
        self.navSupportDivider.setObjectName(u"navSupportDivider")
        self.navSupportDivider.setFrameShape(QFrame.HLine)
        self.navSupportDivider.setFrameShadow(QFrame.Sunken)

        self.navMenuLayout.addWidget(self.navSupportDivider)

        self.navSupportSectionLabel = QLabel(self.navScrollContent)
        self.navSupportSectionLabel.setObjectName(u"navSupportSectionLabel")

        self.navMenuLayout.addWidget(self.navSupportSectionLabel)

        self.navAboutButton = QPushButton(self.navScrollContent)
        self.navAboutButton.setObjectName(u"navAboutButton")
        self.navAboutButton.setCheckable(True)

        self.navMenuLayout.addWidget(self.navAboutButton)

        self.navSettingsButton = QPushButton(self.navScrollContent)
        self.navSettingsButton.setObjectName(u"navSettingsButton")
        self.navSettingsButton.setCheckable(True)

        self.navMenuLayout.addWidget(self.navSettingsButton)

        self.navMenuSpacer = QSpacerItem(0, 0, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)

        self.navMenuLayout.addItem(self.navMenuSpacer)

        self.navScroll.setWidget(self.navScrollContent)

        self.navigationLayout.addWidget(self.navScroll)

        self.headerAccountMenu = QFrame(navigationPanel)
        self.headerAccountMenu.setObjectName(u"headerAccountMenu")
        self.headerAccountMenu.setMinimumSize(QSize(0, 44))
        self.headerAccountMenu.setMaximumSize(QSize(16777215, 44))
        self.headerAccountMenu.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.headerAccountMenu.setFrameShape(QFrame.Shape.NoFrame)
        self.headerAccountMenuLayout = QHBoxLayout(self.headerAccountMenu)
        self.headerAccountMenuLayout.setSpacing(5)
        self.headerAccountMenuLayout.setObjectName(u"headerAccountMenuLayout")
        self.headerAccountMenuLayout.setContentsMargins(8, 7, 8, 7)
        self.profileAvatarButton = QPushButton(self.headerAccountMenu)
        self.profileAvatarButton.setObjectName(u"profileAvatarButton")
        self.profileAvatarButton.setMinimumSize(QSize(30, 30))
        self.profileAvatarButton.setMaximumSize(QSize(30, 30))
        self.profileAvatarButton.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

        self.headerAccountMenuLayout.addWidget(self.profileAvatarButton)

        self.headerUserLabel = QLabel(self.headerAccountMenu)
        self.headerUserLabel.setObjectName(u"headerUserLabel")
        self.headerUserLabel.setMinimumSize(QSize(0, 22))
        self.headerUserLabel.setAlignment(Qt.AlignmentFlag.AlignVCenter|Qt.AlignmentFlag.AlignLeft)

        self.headerAccountMenuLayout.addWidget(self.headerUserLabel)

        self.headerAccountArrowButton = QPushButton(self.headerAccountMenu)
        self.headerAccountArrowButton.setObjectName(u"headerAccountArrowButton")
        self.headerAccountArrowButton.setMinimumSize(QSize(24, 24))
        self.headerAccountArrowButton.setMaximumSize(QSize(24, 24))
        self.headerAccountArrowButton.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

        self.headerAccountMenuLayout.addWidget(self.headerAccountArrowButton)

        self.headerAccountSpacer = QSpacerItem(0, 0, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.headerAccountMenuLayout.addItem(self.headerAccountSpacer)


        self.navigationLayout.addWidget(self.headerAccountMenu)

        self.connectionCard = QFrame(navigationPanel)
        self.connectionCard.setObjectName(u"connectionCard")
        self.connectionLayout = QVBoxLayout(self.connectionCard)
        self.connectionLayout.setSpacing(1)
        self.connectionLayout.setObjectName(u"connectionLayout")
        self.connectionLayout.setContentsMargins(10, 7, 10, 7)
        self.connectionTitleRow = QHBoxLayout()
        self.connectionTitleRow.setObjectName(u"connectionTitleRow")
        self.connectionDot = QLabel(self.connectionCard)
        self.connectionDot.setObjectName(u"connectionDot")

        self.connectionTitleRow.addWidget(self.connectionDot)

        self.connectionTitle = QLabel(self.connectionCard)
        self.connectionTitle.setObjectName(u"connectionTitle")

        self.connectionTitleRow.addWidget(self.connectionTitle)

        self.connectionTitleSpacer = QSpacerItem(0, 0, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.connectionTitleRow.addItem(self.connectionTitleSpacer)


        self.connectionLayout.addLayout(self.connectionTitleRow)

        self.connectionSub = QLabel(self.connectionCard)
        self.connectionSub.setObjectName(u"connectionSub")

        self.connectionLayout.addWidget(self.connectionSub)


        self.navigationLayout.addWidget(self.connectionCard)


        self.retranslateUi(navigationPanel)

        QMetaObject.connectSlotsByName(navigationPanel)
    # setupUi

    def retranslateUi(self, navigationPanel):
        self.navNavigationSectionLabel.setText(QCoreApplication.translate("NavigationPanel", u"\u5bfc\u822a", None))
        self.navHomeButton.setText(QCoreApplication.translate("NavigationPanel", u"\u9996\u9875", None))
        self.navCategoryRankButton.setText(QCoreApplication.translate("NavigationPanel", u"\u5206\u7c7b\u4e0e\u6392\u884c", None))
        self.navWeeklyButton.setText(QCoreApplication.translate("NavigationPanel", u"\u6bcf\u5468\u5fc5\u770b", None))
        self.navDownloadButton.setText(QCoreApplication.translate("NavigationPanel", u"\u4e0b\u8f7d\u7ba1\u7406", None))
        self.navUserSectionLabel.setText(QCoreApplication.translate("NavigationPanel", u"\u7528\u6237", None))
        self.navFavoriteButton.setText(QCoreApplication.translate("NavigationPanel", u"\u6211\u7684\u6536\u85cf", None))
        self.navCommentButton.setText(QCoreApplication.translate("NavigationPanel", u"\u6211\u7684\u8bc4\u8bba", None))
        self.navRemoteHistoryButton.setText(QCoreApplication.translate("NavigationPanel", u"\u89c2\u770b\u8bb0\u5f55", None))
        self.navLocalFavoriteButton.setText(QCoreApplication.translate("NavigationPanel", u"\u672c\u5730\u6536\u85cf", None))
        self.navHistoryButton.setText(QCoreApplication.translate("NavigationPanel", u"\u672c\u5730\u8bb0\u5f55", None))
        self.navSupportSectionLabel.setText(QCoreApplication.translate("NavigationPanel", u"\u652f\u6301", None))
        self.navAboutButton.setText(QCoreApplication.translate("NavigationPanel", u"\u5e2e\u52a9", None))
        self.navSettingsButton.setText(QCoreApplication.translate("NavigationPanel", u"\u8bbe\u7f6e", None))
        self.profileAvatarButton.setText(QCoreApplication.translate("NavigationPanel", u"U", None))
        self.headerUserLabel.setText(QCoreApplication.translate("NavigationPanel", u"\u6e38\u5ba2", None))
        self.headerAccountArrowButton.setText(QCoreApplication.translate("NavigationPanel", u"\u2304", None))
        self.connectionDot.setText(QCoreApplication.translate("NavigationPanel", u"\u25cf", None))
        self.connectionTitle.setText("")
        self.connectionSub.setText(QCoreApplication.translate("NavigationPanel", u"\u5df2\u8f7d\u5165 0/0 \u6761\u6f2b\u753b\u6570\u636e", None))
        pass
    # retranslateUi

