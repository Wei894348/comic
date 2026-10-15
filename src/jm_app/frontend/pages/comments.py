"""Personal comment center widgets, filtering, and card presentation."""

from __future__ import annotations

import copy
from typing import Dict, List, TYPE_CHECKING

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from ...backend.models import AlbumMeta

if TYPE_CHECKING:
    from ..ui import MainWindow


class CommentsPageMixin:
    """Render the account comment route without coupling it to the library form."""

    def setup_comments_page(self: "MainWindow", panel: QFrame) -> None:
        comments_tab = panel.findChild(QFrame, "commentsTab")
        if comments_tab is None:
            comments_tab = next(
                (self.library_tabs.widget(index) for index in range(self.library_tabs.count())
                 if self.library_tabs.widget(index).objectName() == "commentsTab"),
                None,
            )
        if comments_tab is None or not isinstance(comments_tab.layout(), QVBoxLayout):
            raise RuntimeError("Missing commentsTab layout")

        self.my_comments_header = self.load_ui_widget("my_comments.ui", QFrame, comments_tab)
        comments_layout = comments_tab.layout()
        comments_layout.insertWidget(0, self.my_comments_header)
        self.library_comment_toolbar_layout = self._find_child_layout(comments_layout, "commentsToolbar")
        self.library_comment_post_layout = self._find_child_layout(comments_layout, "commentPostRow")
        self.library_comment_pager_layout = self._build_comment_pager_host(
            comments_layout, comments_tab
        )

        def require(widget_type, name):
            widget = self.my_comments_header.findChild(widget_type, name)
            if widget is None:
                raise RuntimeError(f"my_comments.ui is missing {name}")
            return widget

        self.my_comments_search_edit = require(QLineEdit, "myCommentsSearchEdit")
        self.my_comments_sort_combo = require(QComboBox, "myCommentsSortCombo")
        self.my_comments_avatar_label = require(QLabel, "myCommentsAvatarLabel")
        self.my_comments_name_label = require(QLabel, "myCommentsNameLabel")
        self.my_comments_level_label = require(QLabel, "myCommentsLevelLabel")
        self.my_comments_bio_label = require(QLabel, "myCommentsBioLabel")
        self.my_comments_stat_labels = {
            "published": require(QLabel, "myCommentsPublishedValue"),
            "likes": require(QLabel, "myCommentsLikesValue"),
            "featured": require(QLabel, "myCommentsFeaturedValue"),
            "replies": require(QLabel, "myCommentsRepliesValue"),
        }
        self.my_comments_published_caption = require(
            QLabel, "myCommentsPublishedCaption"
        )
        stats_layout = self.my_comments_header.findChild(QHBoxLayout, "myCommentsStatsRow")
        if stats_layout is not None:
            for index in range(4):
                stats_layout.setStretch(index, 1)
        self.my_comments_filter_buttons = {
            "all": require(QPushButton, "myCommentsAllButton"),
            "published": require(QPushButton, "myCommentsPublishedButton"),
            "replied": require(QPushButton, "myCommentsRepliedButton"),
            "liked": require(QPushButton, "myCommentsLikedButton"),
        }
        self.my_comments_filter_group = QButtonGroup(self)
        self.my_comments_filter_group.setExclusive(True)
        for key, button in self.my_comments_filter_buttons.items():
            self.my_comments_filter_group.addButton(button)
            button.clicked.connect(lambda _checked=False, key=key: self.set_comment_filter(key))

        self.my_comments_search_edit.addAction(
            self.style().standardIcon(QStyle.SP_FileDialogContentsView),
            QLineEdit.ActionPosition.LeadingPosition,
        )
        self.my_comments_search_edit.textChanged.connect(self.apply_comment_view)
        self.my_comments_sort_combo.currentIndexChanged.connect(self.apply_comment_view)
        require(QPushButton, "myCommentsEditProfileButton").clicked.connect(self.open_profile_page)
        self.comment_filter_mode = "all"
        self.library_comment_items: List[Dict] = []
        self.library_comment_total = 0
        self.personal_comment_statistics = None
        self.personal_comment_statistics_uid = ""
        self.personal_comment_statistics_loading = False
        self.personal_comment_statistics_serial = 0
        self.update_comment_statistics([], 0)
        self.sync_comment_profile_header()

    @staticmethod
    def _find_child_layout(root_layout, object_name: str):
        for index in range(root_layout.count()):
            layout = root_layout.itemAt(index).layout()
            if layout is not None and layout.objectName() == object_name:
                return layout
        return None

    def _build_comment_pager_host(
        self: "MainWindow", comments_layout: QVBoxLayout, comments_tab: QWidget
    ) -> QHBoxLayout:
        """Move pager widgets, never the Designer-owned layout object itself."""
        pager = self._find_child_layout(comments_layout, "commentsPager")
        post = getattr(self, "library_comment_post_layout", None)
        if pager is None:
            raise RuntimeError("library.ui is missing commentsPager")
        host = QWidget(comments_tab)
        host.setObjectName("commentPagerHost")
        host_layout = QHBoxLayout(host)
        host_layout.setObjectName("commentPagerHostLayout")
        host_layout.setContentsMargins(0, 2, 0, 0)
        host_layout.setSpacing(8)
        host_layout.addStretch(1)
        host_layout.addWidget(self.library_comment_previous_btn)
        host_layout.addWidget(self.library_comment_page_label)
        host_layout.addWidget(self.library_comment_next_btn)
        host_layout.addStretch(1)
        post_index = next(
            (index for index in range(comments_layout.count())
             if comments_layout.itemAt(index).layout() is post),
            comments_layout.count(),
        )
        comments_layout.insertWidget(post_index, host)
        return host_layout

    @staticmethod
    def _set_layout_visible(layout, visible: bool) -> None:
        if layout is None:
            return
        for index in range(layout.count()):
            item = layout.itemAt(index)
            widget = item.widget()
            child_layout = item.layout()
            if widget is not None:
                widget.setVisible(visible)
            elif child_layout is not None:
                CommentsPageMixin._set_layout_visible(child_layout, visible)

    def set_comments_page_mode(self: "MainWindow", personal: bool) -> None:
        if not hasattr(self, "my_comments_header"):
            return
        self.my_comments_header.setVisible(personal)
        self._set_layout_visible(self.library_comment_toolbar_layout, not personal)
        self._set_layout_visible(self.library_comment_post_layout, not personal)
        self.library_comment_scroll.setProperty("personalComments", personal)
        self.library_comment_scroll.style().unpolish(self.library_comment_scroll)
        self.library_comment_scroll.style().polish(self.library_comment_scroll)
        if personal:
            self.sync_comment_profile_header()

    def set_comment_filter(self: "MainWindow", key: str) -> None:
        if key not in self.my_comments_filter_buttons:
            key = "all"
        if key == getattr(self, "comment_filter_mode", "all"):
            return
        self.comment_filter_mode = key
        self.my_comments_filter_buttons[key].setChecked(True)
        self.library_comment_page = 1
        self.refresh_library_comments()

    @staticmethod
    def _comment_number(value) -> int:
        try:
            return max(0, int(str(value or "0").replace(",", "")))
        except (TypeError, ValueError):
            return 0

    def comment_reply_count(self: "MainWindow", item: Dict) -> int:
        replies = item.get("replys") or item.get("replies") or item.get("children") or []
        if isinstance(replies, list):
            return len(replies)
        return self._comment_number(
            self._comment_field(item, ["reply_count", "replies_count", "reply_num"], "0")
        )

    def comment_like_count(self: "MainWindow", item: Dict) -> int:
        return self._comment_number(
            self._comment_field(item, ["likes", "like", "like_count", "praise"], "0")
        )

    def comment_is_reply(self: "MainWindow", item: Dict) -> bool:
        return bool(
            self._comment_field(
                item,
                ["reply_to", "reply_id", "parent_id", "parent_cid", "comment_parent_id"],
            )
        )

    def sync_comment_profile_header(self: "MainWindow") -> None:
        if not hasattr(self, "my_comments_header"):
            return
        data = self.profile_data or {}
        user = data.get("user") or {}
        username = self._profile_text(
            data.get("username") or user.get("username") or self.session_username,
            "游客",
        )
        level = self._profile_text(user.get("level") or data.get("level"), "-")
        bio = self._profile_text(
            user.get("description")
            or user.get("signature")
            or user.get("intro")
            or data.get("description")
            or data.get("signature"),
            "记录每一次阅读后的想法",
        )
        self.my_comments_name_label.setText(username)
        self.my_comments_name_label.setToolTip(username)
        self.my_comments_level_label.setText(f"LV {level}" if level != "-" else "LV -")
        self.my_comments_bio_label.setText(bio)
        self.my_comments_bio_label.setToolTip(bio)
        if self.profile_avatar_pixmap is not None:
            self.set_comment_avatar_on_label(self.my_comments_avatar_label, self.profile_avatar_pixmap)
        elif self.session_uid:
            photo = self._profile_text(
                user.get("photo")
                or user.get("avatar")
                or data.get("photo")
                or data.get("avatar"),
                "",
            )
            self.request_comment_avatar(
                photo, self.session_uid, self.my_comments_avatar_label, username
            )
        else:
            self._comment_avatar_placeholder(self.my_comments_avatar_label, username)

    def update_comment_statistics(self: "MainWindow", _comments: List[Dict], _total: int) -> None:
        values = getattr(self, "personal_comment_statistics", None)
        self.my_comments_published_caption.setText("发布评论")
        for key in ("published", "likes", "featured", "replies"):
            label = self.my_comments_stat_labels[key]
            label.setText("--" if values is None else str(max(0, int(values.get(key) or 0))))
            label.setToolTip("当前账号全部评论的统计")

    def invalidate_personal_comment_statistics(self: "MainWindow") -> None:
        self.personal_comment_statistics = None
        self.personal_comment_statistics_uid = ""
        self.personal_comment_statistics_loading = False
        self.personal_comment_statistics_serial = int(
            getattr(self, "personal_comment_statistics_serial", 0)
        ) + 1
        if hasattr(self, "my_comments_stat_labels"):
            self.update_comment_statistics([], 0)

    def render_comment_center(self: "MainWindow", comments: List[Dict], total: int) -> None:
        self.library_comment_items = [dict(item) for item in comments if isinstance(item, dict)]
        self.library_comment_total = max(0, int(total or 0))
        self.sync_comment_profile_header()
        if self.profile_avatar_pixmap is None:
            profile_item = next(
                (
                    item
                    for item in self.library_comment_items
                    if self._comment_field(
                        item, ["photo", "avatar", "avatar_url", "head", "head_url"]
                    )
                    or self._comment_field(item, ["UID", "uid", "user_id"])
                ),
                None,
            )
            if profile_item is not None:
                username = self._comment_field(
                    profile_item,
                    ["username", "user_name", "nickname", "name"],
                    self.my_comments_name_label.text() or "用户",
                )
                photo = self._comment_field(
                    profile_item, ["photo", "avatar", "avatar_url", "head", "head_url"]
                )
                user_id = self._comment_field(profile_item, ["UID", "uid", "user_id"])
                self.request_comment_avatar(
                    photo, user_id, self.my_comments_avatar_label, username
                )
        self.update_comment_statistics(self.library_comment_items, self.library_comment_total)
        self.apply_comment_view()

    def apply_comment_view(self: "MainWindow", *_args) -> None:
        if not hasattr(self, "library_comment_layout"):
            return
        comments = list(getattr(self, "library_comment_items", []))
        personal = not bool(getattr(self, "comment_context_album_id", ""))
        if personal and hasattr(self, "my_comments_search_edit"):
            query = self.my_comments_search_edit.text().strip().casefold()
            if query:
                comments = [
                    item for item in comments
                    if query in self.clean_comment_content(
                        self._comment_field(item, ["comment", "content", "text", "message"])
                    ).casefold()
                    or query in self._comment_field(
                        item, ["name", "album_name", "comic_name", "title"]
                    ).casefold()
                ]
            mode = getattr(self, "comment_filter_mode", "all")
            if mode == "replied":
                comments = [item for item in comments if self.comment_reply_count(item) > 0]
            elif mode == "liked":
                comments = [item for item in comments if self.comment_like_count(item) > 0]

            sort_key = self.my_comments_sort_combo.currentData() or "latest"
            if sort_key == "likes":
                comments.sort(key=self.comment_like_count, reverse=True)
            elif sort_key == "replies":
                comments.sort(key=self.comment_reply_count, reverse=True)

        if not personal:
            self.comment_avatar_targets.clear()
        self.library_comment_scroll.setUpdatesEnabled(False)
        try:
            self._clear_library_layout(self.library_comment_layout)
            if not comments:
                message = "没有符合条件的评论" if self.library_comment_items else "暂无评论"
                self.library_comment_layout.insertWidget(
                    max(0, self.library_comment_layout.count() - 1),
                    self.create_empty_state_label(message, 18),
                )
            else:
                page_size = max(1, len(self.library_comment_items))
                start_index = (max(1, int(self.library_comment_page)) - 1) * page_size + 1
                for offset, item in enumerate(comments):
                    self.library_comment_layout.insertWidget(
                        max(0, self.library_comment_layout.count() - 1),
                        self.build_comment_card(item, start_index + offset),
                    )
        finally:
            self.library_comment_scroll.setUpdatesEnabled(True)
            self.library_comment_scroll.viewport().update()
        QTimer.singleShot(0, lambda: self.library_comment_scroll.verticalScrollBar().setValue(0))

    def build_comment_card(self: "MainWindow", item: Dict, index: int) -> QFrame:
        card = self.load_ui_widget("comment_card.ui", QFrame)

        def label(name: str) -> QLabel:
            widget = card.findChild(QLabel, name)
            if widget is None:
                raise RuntimeError(f"comment_card.ui is missing {name}")
            return widget

        def button(name: str) -> QPushButton:
            widget = card.findChild(QPushButton, name)
            if widget is None:
                raise RuntimeError(f"comment_card.ui is missing {name}")
            return widget

        username = self._comment_field(item, ["username", "user_name", "nickname", "name"], "匿名用户")
        content = self.clean_comment_content(
            self._comment_field(item, ["comment", "content", "text", "message"])
        ) or "（无内容）"
        album_id = self._comment_field(item, ["AID", "aid", "album_id", "photo_id", "comic_id"])
        album_name = self._comment_field(item, ["name", "album_name", "comic_name", "title"])
        comment_id = self._comment_field(item, ["CID", "comment_id", "cid", "id"])
        user_id = self._comment_field(item, ["UID", "uid", "user_id"])
        created = self._comment_field(item, ["addtime", "created_at", "time", "created", "date"])
        level = self._comment_field(item, ["level", "lv", "user_level"])
        title = self._comment_field(item, ["title", "level_name", "role", "badge"])
        photo = self._comment_field(item, ["photo", "avatar", "avatar_url", "head", "head_url"])
        likes = self.comment_like_count(item)
        replies = item.get("replys") or item.get("replies") or item.get("children") or []
        reply_count = self.comment_reply_count(item)
        personal = not bool(getattr(self, "comment_context_album_id", "")) and bool(album_id)

        label("commentIndexLabel").setText(f"#{index}")
        label("commentNameLabel").setText(username)
        label("commentNameLabel").setToolTip(username)
        label("commentDateLabel").setText(created or "-")
        label("commentDateLabel").setToolTip(created)
        label("commentLevelLabel").setText(f"LV {level}" if level else "")
        label("commentTitleLabel").setText(title)
        label("commentIdLabel").setText(f"#{comment_id}" if comment_id else "")
        content_label = label("commentContentLabel")
        content_label.setTextFormat(Qt.PlainText)
        content_label.setText(content)
        content_label.setToolTip(content)
        label("commentLikeLabel").setText(f"♡ {likes}")

        album_button = button("commentAlbumButton")
        if album_id:
            album_button.setText(album_name or f"JM{album_id}")
            album_button.setToolTip(f"打开 JM{album_id}")
            album_button.clicked.connect(
                lambda _checked=False, album_id=album_id, album_name=album_name:
                self.open_comment_album_detail(album_id, album_name)
            )
        else:
            album_button.setVisible(False)

        reply_button = button("commentReplyButton")
        reply_button.setText(f"回复 ({reply_count})")
        reply_button.setEnabled(bool(comment_id))
        if comment_id:
            if isinstance(replies, list) and replies:
                reply_button.clicked.connect(
                    lambda _checked=False, replies=list(replies), comment_id=comment_id:
                    self.open_comment_replies(replies, comment_id)
                )
            else:
                reply_button.clicked.connect(
                    lambda _checked=False, comment_id=comment_id: self.prepare_comment_reply(comment_id)
                )

        avatar = label("commentAvatarLabel")
        cover = label("commentAlbumCoverLabel")
        preview = label("commentReplyPreviewLabel")
        cover.setVisible(personal)
        avatar.setVisible(not personal)
        label("commentIndexLabel").setVisible(not personal)
        for name in ("commentNameLabel", "commentLevelLabel", "commentTitleLabel", "commentIdLabel"):
            label(name).setVisible(not personal)

        preview_text = ""
        if personal and isinstance(replies, list) and replies:
            first_reply = replies[0] if isinstance(replies[0], dict) else {}
            reply_author = self._comment_field(first_reply, ["username", "user_name", "nickname", "name"])
            reply_content = self.clean_comment_content(
                self._comment_field(first_reply, ["comment", "content", "text", "message"])
            )
            if reply_content:
                preview_text = f"{reply_author + '：' if reply_author else ''}{reply_content}"
        preview.setText(preview_text)
        preview.setVisible(bool(preview_text))

        if personal:
            cover._persistent_cover = True
            cover.setText("加载中" if album_id else "暂无封面")
            if album_id:
                QTimer.singleShot(
                    35 + min(max(0, index - 1), 12) * 20,
                    lambda album_id=album_id, album_name=album_name, cover=cover:
                    self.request_comment_album_cover(album_id, album_name, cover),
                )
        else:
            self.request_comment_avatar(photo, user_id, avatar, username)
        card.setProperty("personalMode", personal)
        return card

    def open_comment_album_detail(
        self: "MainWindow", album_id: str, album_name: str = ""
    ) -> None:
        """Open a forum-linked album even when it was not loaded in a feed."""
        album_id = str(album_id or "").strip()
        if not album_id or album_id == "0":
            self.show_toast("该评论没有关联漫画")
            return
        if album_id not in self.albums:
            cached = self.detail_cache.get(album_id)
            self.albums[album_id] = copy.deepcopy(cached) if cached else AlbumMeta(
                album_id=album_id,
                title=str(album_name or f"JM{album_id}"),
                url=f"jm://album/{album_id}",
                cover_url=self.default_cover_url(album_id),
            )
        self.open_album_detail(album_id)

    def request_comment_album_cover(
        self: "MainWindow", album_id: str, album_name: str, cover: QLabel
    ) -> None:
        try:
            album = self.albums.get(album_id) or self.detail_cache.get(album_id)
            if album is None:
                album = AlbumMeta(
                    album_id=album_id,
                    title=album_name or f"JM{album_id}",
                    url="",
                    cover_url=self.default_cover_url(album_id),
                )
            else:
                album = copy.deepcopy(album)
            self.request_cover(album, cover)
        except RuntimeError:
            return
