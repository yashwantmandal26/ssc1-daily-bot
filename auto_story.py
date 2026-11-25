#!/usr/bin/env python3
"""
Automated Daily Instagram Story Publisher (@ssc1.daily) - v2 (Approval Gate Ready)
----------------------------------------------------------------------------------
Designed for 2-job GitHub Actions approval flow:
  Job 1 (`--render-only`):
    1. Checks Google News RSS for fresh (<48h) SSC exam/aspirant updates.
    2. If fresh unseen SSC news exists -> renders "SSC EXAM ALERT" 9:16 Story.
    3. Otherwise -> picks the next unposted item from `stories.json`
       (dry sarcasm, non-generic raw student quotes, 10-sec SSC memory tricks).
    4. Marks the chosen item as consumed immediately so if you REJECT today's
       Story in GitHub Mobile, tomorrow automatically shows a DIFFERENT Story!
    5. Writes `image_rel` and `headline` to `$GITHUB_OUTPUT` & preview to `$GITHUB_STEP_SUMMARY`.
  Job 2 (`--publish-image <rel>`, protected by GitHub Environment `story-approval`):
    - Only runs after you tap "Approve" on your phone!
    - Publishes the exact previewed Story via Meta Graph API (`media_type=STORIES`).
"""

import argparse
import base64
import datetime
import email.utils
import json
import os
import sys
import tempfile
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

import requests
from jinja2 import Template
from PIL import Image
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By

ROOT_DIR = Path(__file__).resolve().parent
TEMPLATE_PATH = ROOT_DIR / "story_template.html"
STORIES_PATH = ROOT_DIR / "stories.json"
NEWS_CACHE_PATH = ROOT_DIR / "posted_news.json"
PUBLISHED_DIR = ROOT_DIR / "published"

IG_API_BASE = (
    "https://graph.instagram.com/v21.0"
    if os.environ.get("IG_ACCESS_TOKEN", "").startswith("IG")
    else "https://graph.facebook.com/v21.0"
)

RSS_QUERY = urllib.parse.quote(
    '("SSC CGL" OR "SSC CHSL" OR "SSC MTS" OR "ssc.gov.in") (notice OR exam OR admit card OR result OR calendar OR vacancy) when:2d'
)
GOOGLE_NEWS_RSS = f"https://news.google.com/rss/search?q={RSS_QUERY}&hl=en-IN&gl=IN&ceid=IN:en"

ALLOWED_NEWS_KEYWORDS = {
    "ssc", "cgl", "chsl", "mts", "gd", "cpo", "stenographer", "ssc.gov.in",
    "admit card", "answer key", "result", "notification", "vacancy", "calendar", "tier",
}


def get_ist_now() -> datetime.datetime:
    return datetime.datetime.now(
        datetime.timezone(datetime.timedelta(hours=5, minutes=30))
    )


def fetch_fresh_ssc_news() -> dict | None:
    posted_links: set[str] = set()
    if NEWS_CACHE_PATH.exists():
        try:
            posted_links = set(json.loads(NEWS_CACHE_PATH.read_text(encoding="utf-8")))
        except Exception:
            posted_links = set()

    try:
        req = urllib.request.Request(
            GOOGLE_NEWS_RSS,
            headers={"User-Agent": "Mozilla/5.0 (compatible; SSC1DailyBot/1.0)"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            xml_bytes = resp.read()
        root = ET.fromstring(xml_bytes)
    except Exception as exc:
        print(f"RSS fetch skipped: {exc}")
        return None

    now_utc = datetime.datetime.now(datetime.timezone.utc)
    for item in root.findall(".//item")[:10]:
        raw_title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        pub_str = (item.findtext("pubDate") or "").strip()

        if not raw_title or not link or link in posted_links:
            continue

        if pub_str:
            try:
                pub_dt = email.utils.parsedate_to_datetime(pub_str)
                if (now_utc - pub_dt).total_seconds() > 48 * 3600:
                    continue
            except Exception:
                pass

        parts = raw_title.rsplit(" - ", 1)
        headline = parts[0].strip().replace("\u2014", "-")
        publisher = parts[1].strip() if len(parts) > 1 else "SSC News Desk"

        low = headline.lower()
        if not any(kw in low for kw in ALLOWED_NEWS_KEYWORDS):
            continue
        if len(headline) > 140:
            headline = headline[:137].rstrip() + "..."

        return {
            "id": f"news_{int(time.time())}",
            "is_news": True,
            "link": link,
            "theme_class": "theme-news",
            "category_badge": "SSC EXAM ALERT",
            "headline": headline,
            "body_text": "Check official ssc.gov.in for complete notice & dates.",
            "highlight_text": "Verify dates and PDF directly on ssc.gov.in before acting on any forwarded screenshot.",
            "source_text": f"Source: {publisher}",
        }

    return None


def create_driver() -> webdriver.Chrome:
    os.environ.setdefault("DBUS_SESSION_BUS_ADDRESS", "/dev/null")
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--hide-scrollbars")
    options.add_argument("--window-size=1080,2000")
    options.add_argument("--force-device-scale-factor=1")
    return webdriver.Chrome(options=options)


def render_story_jpg(html_content: str, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    driver = create_driver()
    try:
        b64_html = base64.b64encode(html_content.encode("utf-8")).decode("ascii")
        driver.get(f"data:text/html;charset=utf-8;base64,{b64_html}")
        with tempfile.TemporaryDirectory(prefix="ig_story_") as tmpdir:
            png_file = Path(tmpdir) / "story.png"
            driver.find_element(By.CSS_SELECTOR, ".canvas").screenshot(str(png_file))
            with Image.open(png_file) as img:
                rgb = img.convert("RGB")
                if rgb.size != (1080, 1920):
                    rgb = rgb.resize((1080, 1920), Image.Resampling.LANCZOS)
                rgb.save(output_path, format="JPEG", quality=95, optimize=True)
    finally:
        driver.quit()


def write_github_output(key: str, value: str) -> None:
    gh_out = os.environ.get("GITHUB_OUTPUT")
    if gh_out:
        safe_val = value.replace("\n", " ").strip()
        with open(gh_out, "a", encoding="utf-8") as f:
            f.write(f"{key}={safe_val}\n")


def render_next_story(mode: str, mark_consumed: bool = True) -> None:
    story_data = None
    bank = []

    if mode in ("auto", "news"):
        story_data = fetch_fresh_ssc_news()
        if story_data:
            print(f"Found fresh SSC news: {story_data['headline']}")

    if not story_data:
        if mode == "news":
            print("No fresh SSC news in last 48h; falling back to curated Story bank.")
        if not STORIES_PATH.exists():
            print("stories.json missing. Exiting.")
            sys.exit(0)
        bank = json.loads(STORIES_PATH.read_text(encoding="utf-8"))
        unposted = [s for s in bank if not s.get("posted", False)]
        if not unposted:
            for s in bank:
                s["posted"] = False
            unposted = bank
        item = unposted[0]
        kind = item.get("kind", "trick")
        theme_class = "theme-sarcasm" if kind == "sarcasm" else ""
        story_data = {
            "id": item["id"],
            "is_news": False,
            "theme_class": theme_class,
            "category_badge": item["category_badge"],
            "headline": item["headline"].replace("\u2014", "-"),
            "body_text": item.get("body_text", "").replace("\u2014", "-"),
            "highlight_text": item.get("highlight_text", "").replace("\u2014", "-"),
            "source_text": item.get("source_text", "").replace("\u2014", "-"),
        }

    ist_now = get_ist_now()
    date_label = ist_now.strftime("%d %b %Y")
    tpl = Template(TEMPLATE_PATH.read_text(encoding="utf-8"))
    html_str = tpl.render(date_label=date_label, **story_data)

    out_path = PUBLISHED_DIR / f"story_{story_data['id']}.jpg"
    render_story_jpg(html_str, out_path)
    image_rel = f"published/{out_path.name}"

    # Mark consumed immediately so rejecting today's Story automatically moves to a NEW one tomorrow!
    if mark_consumed:
        if story_data["is_news"] and story_data.get("link"):
            links = []
            if NEWS_CACHE_PATH.exists():
                try:
                    links = json.loads(NEWS_CACHE_PATH.read_text(encoding="utf-8"))
                except Exception:
                    links = []
            links.append(story_data["link"])
            NEWS_CACHE_PATH.write_text(json.dumps(links[-100:], indent=2) + "\n", encoding="utf-8")
        elif bank:
            for s in bank:
                if s["id"] == story_data["id"]:
                    s["posted"] = True
            STORIES_PATH.write_text(json.dumps(bank, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    write_github_output("image_rel", image_rel)
    write_github_output("story_id", story_data["id"])
    write_github_output("headline", story_data["headline"])
    print(f"Rendered Story: {image_rel} | Headline: {story_data['headline']}")


def ig_post(endpoint: str, payload: dict) -> dict:
    resp = requests.post(f"{IG_API_BASE}/{endpoint}", data=payload, timeout=30)
    data = resp.json()
    if resp.status_code >= 400 or "error" in data:
        raise RuntimeError(f"Instagram API error on {endpoint}: {data}")
    return data


def publish_story_image(image_rel: str) -> None:
    token = os.environ.get("IG_ACCESS_TOKEN", "").strip()
    ig_user_id = os.environ.get("IG_USER_ID", "me").strip() or "me"
    repo = os.environ.get("GITHUB_REPOSITORY", "").strip()
    branch = os.environ.get("GITHUB_REF_NAME", "main").strip() or "main"

    if not token or not repo:
        raise RuntimeError("Missing IG_ACCESS_TOKEN or GITHUB_REPOSITORY.")

    img_url = f"https://raw.githubusercontent.com/{repo}/{branch}/{image_rel}"
    print(f"Publishing approved Instagram Story from: {img_url}")

    container_id = ig_post(
        f"{ig_user_id}/media",
        {
            "media_type": "STORIES",
            "image_url": img_url,
            "access_token": token,
        },
    )["id"]
    time.sleep(6)
    published = ig_post(
        f"{ig_user_id}/media_publish",
        {"creation_id": container_id, "access_token": token},
    )
    print(f"Published Story! Media ID: {published['id']}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--render-only", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="Render without marking stories.json consumed")
    parser.add_argument("--publish-image", type=str, default="", help="Relative path to approved Story image")
    parser.add_argument("--mode", choices=["auto", "news", "curated"], default="auto")
    args = parser.parse_args()

    if args.publish_image:
        publish_story_image(args.publish_image)
    elif args.render_only or args.dry_run:
        render_next_story(args.mode, mark_consumed=not args.dry_run)
    else:
        render_next_story(args.mode, mark_consumed=True)


if __name__ == "__main__":
    main()
