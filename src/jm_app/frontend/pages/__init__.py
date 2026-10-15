"""Page-level controllers used by :class:`MainWindow`.

The application keeps Qt widget ownership in ``ui.py`` while each page owns
its own interaction and request orchestration here.  This mirrors the
``view/<page>`` layout used by JMComic-qt without breaking existing Designer
forms.
"""

from .appearance import AppearancePageMixin
from .detail import DetailPageMixin
from .download import DownloadPageMixin
from .comments import CommentsPageMixin
from .home import HomePageMixin
from .library_feed import LibraryFeedPageMixin
from .local_download import LocalDownloadPageMixin
from .local_favorite import LocalFavoritePageMixin
from .local_history import LocalHistoryPageMixin
from .navigation import NAVIGATION_PANEL_WIDTH, NavigationPageMixin
from .profile import ProfilePageMixin
from .settings import SettingsPageMixin
from .weekly import WeeklyPageMixin

__all__ = (
    "AppearancePageMixin",
    "DetailPageMixin",
    "DownloadPageMixin",
    "CommentsPageMixin",
    "HomePageMixin",
    "LibraryFeedPageMixin",
    "LocalDownloadPageMixin",
    "LocalFavoritePageMixin",
    "LocalHistoryPageMixin",
    "NAVIGATION_PANEL_WIDTH",
    "NavigationPageMixin",
    "ProfilePageMixin",
    "SettingsPageMixin",
    "WeeklyPageMixin",
)
