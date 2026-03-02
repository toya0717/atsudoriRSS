"""
BanG Dream! Our Notes - 公式ニュース RSS 自動生成スクリプト
======================================================
対象URL: https://bang-dream-on.bushimo.jp/news/
出力形式: RSS 2.0 (news_feed.xml)
"""

import sys
import logging
from datetime import datetime
from typing import Optional

import requests
from bs4 import BeautifulSoup
from feedgen.feed import FeedGenerator
import pytz

# ─────────────────────────────────────────────
# ログ設定
# ─────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# 設定定数
# HTMLの構造が変わった場合は、このブロックのみ修正する
# ─────────────────────────────────────────────

TARGET_URL = "https://bang-dream-on.bushimo.jp/news/"
BASE_URL   = "https://bang-dream-on.bushimo.jp"

# ニュース一覧のコンテナ要素（CSSセレクタ）
NEWS_LIST_SELECTOR = "ul.c-news-archive__list"   # ← 変更時はここを修正

# 個々のニュース記事要素（コンテナ内のセレクタ）
NEWS_ITEM_SELECTOR = "li.c-news-archive__item"   # ← 変更時はここを修正

# 各フィールドのセレクタ（記事要素内の相対パス）
TITLE_SELECTOR = "p.c-news-archive__title"       # ← 変更時はここを修正
LINK_SELECTOR  = "a.c-news-archive__anchor"      # href属性を取得
DATE_SELECTOR  = "p.c-news-archive__date"        # ← 変更時はここを修正

# 公開日の文字列フォーマット（strptime 書式）
DATE_FORMAT = "%Y.%m.%d"             # ← 変更時はここを修正

# RSS フィードのメタ情報
FEED_TITLE       = "BanG Dream! Our Notes Official News"
FEED_LINK        = "https://bang-dream-on.bushimo.jp/news/"
FEED_DESCRIPTION = "BanG Dream! Our Notes 公式サイトの最新ニュース"
FEED_LANGUAGE    = "ja"

# 出力ファイル名（None にすると標準出力へ）
OUTPUT_FILE: Optional[str] = "news_feed.xml"

# HTTPリクエスト設定
REQUEST_TIMEOUT = 15  # 秒
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; BangDreamRSSBot/1.0; "
        "+https://bang-dream-on.bushimo.jp/)"
    )
}

# タイムゾーン
JST = pytz.timezone("Asia/Tokyo")


# ─────────────────────────────────────────────
# メイン処理
# ─────────────────────────────────────────────

def fetch_html(url: str) -> str:
    """対象URLのHTMLを取得して返す。"""
    logger.info(f"HTMLを取得中: {url}")
    try:
        response = requests.get(url, headers=REQUEST_HEADERS, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        response.encoding = response.apparent_encoding
        logger.info(f"取得成功 (ステータス: {response.status_code})")
        return response.text
    except requests.exceptions.Timeout:
        logger.error(f"タイムアウト: {url}")
        raise
    except requests.exceptions.HTTPError as e:
        logger.error(f"HTTPエラー: {e.response.status_code} - {url}")
        raise
    except requests.exceptions.RequestException as e:
        logger.error(f"リクエストエラー: {e}")
        raise


def parse_date(date_str: str) -> Optional[datetime]:
    """
    'YYYY.MM.DD' 形式の文字列を JST 09:00:00 の datetime に変換する。
    解析失敗時は None を返す。
    """
    date_str = date_str.strip()
    try:
        dt = datetime.strptime(date_str, DATE_FORMAT)
        return JST.localize(dt.replace(hour=9, minute=0, second=0))
    except ValueError:
        logger.warning(f"日付の解析に失敗しました: '{date_str}' (期待フォーマット: {DATE_FORMAT})")
        return None


def extract_news_items(html: str) -> list[dict]:
    """
    HTMLを解析してニュース記事リストを返す。
    各要素は {'title': str, 'link': str, 'date': datetime | None} の辞書。
    """
    soup = BeautifulSoup(html, "html.parser")
    news_container = soup.select_one(NEWS_LIST_SELECTOR)

    if not news_container:
        # コンテナが見つからない場合、セレクタの警告を出して空リストを返す
        logger.warning(
            f"ニュースリストのコンテナが見つかりません。"
            f"セレクタを確認してください: '{NEWS_LIST_SELECTOR}'"
        )
        # フォールバック: <body> 全体を対象に直近の <li> を探す
        logger.info("フォールバック: ページ全体から記事の検出を試みます...")
        news_container = soup.body

    items = news_container.select(NEWS_ITEM_SELECTOR) if news_container else []
    logger.info(f"{len(items)} 件の記事要素を検出しました")

    results = []
    for item in items:
        # タイトル取得
        title_tag = item.select_one(TITLE_SELECTOR)
        title = title_tag.get_text(strip=True) if title_tag else None

        # リンク取得（相対URLは絶対URLに変換）
        link_tag = item.select_one(LINK_SELECTOR)
        raw_link = link_tag.get("href", "").strip() if link_tag else ""
        if raw_link.startswith("http"):
            link = raw_link
        elif raw_link.startswith("/"):
            link = BASE_URL + raw_link
        else:
            link = TARGET_URL  # リンク不明時はトップURLを使用

        # 公開日取得
        date_tag = item.select_one(DATE_SELECTOR)
        if date_tag:
            # <time datetime="..."> 属性を優先して取得
            raw_date = date_tag.get("datetime") or date_tag.get_text(strip=True)
        else:
            raw_date = None

        pub_date = parse_date(raw_date) if raw_date else None

        if not title:
            logger.debug("タイトルが空の要素をスキップしました")
            continue

        results.append({"title": title, "link": link, "date": pub_date})
        logger.debug(f"  記事: {title} | {link} | {pub_date}")

    return results


def build_rss_feed(items: list[dict]) -> FeedGenerator:
    """ニュース記事リストから FeedGenerator オブジェクトを構築して返す。"""
    fg = FeedGenerator()
    fg.title(FEED_TITLE)
    fg.link(href=FEED_LINK, rel="alternate")
    fg.description(FEED_DESCRIPTION)
    fg.language(FEED_LANGUAGE)
    fg.lastBuildDate(datetime.now(tz=JST))

    for item in items:
        fe = fg.add_entry()
        fe.title(item["title"])
        fe.link(href=item["link"])
        fe.id(item["link"])  # GUID としてリンクを使用
        if item["date"]:
            fe.pubDate(item["date"])

    logger.info(f"RSSフィードを構築しました ({len(items)} 件)")
    return fg


def output_feed(fg: FeedGenerator) -> None:
    """フィードを OUTPUT_FILE またはstdoutへ出力する。"""
    if OUTPUT_FILE:
        fg.rss_file(OUTPUT_FILE, pretty=True)
        logger.info(f"RSSフィードを書き出しました: {OUTPUT_FILE}")
    else:
        rss_str = fg.rss_str(pretty=True)
        sys.stdout.buffer.write(rss_str)
        logger.info("RSSフィードを標準出力へ出力しました")


def main() -> None:
    logger.info("=== BanG Dream! Our Notes RSS 生成スクリプト 開始 ===")
    try:
        html = fetch_html(TARGET_URL)
        items = extract_news_items(html)

        if not items:
            logger.warning(
                "記事が1件も取得できませんでした。"
                "サイトのHTML構造が変更された可能性があります。"
                "スクリプト冒頭のセレクタ定数を確認してください。"
            )

        fg = build_rss_feed(items)
        output_feed(fg)

    except requests.exceptions.RequestException:
        logger.critical("ネットワークエラーによりスクリプトを終了します")
        sys.exit(1)
    except Exception as e:
        logger.critical(f"予期しないエラーが発生しました: {e}", exc_info=True)
        sys.exit(1)

    logger.info("=== 処理完了 ===")


if __name__ == "__main__":
    main()
