#!/usr/bin/env python3
"""
Automated SSC CGL 2-Slide Instagram Carousel Publisher (@ssc1.daily)
--------------------------------------------------------------------
Designed to run 100% free in GitHub Actions (zero third-party image hosts).

Workflow inside GitHub Actions:
  1. `python3 auto_post.py --render-only`
     -> Picks the next unposted PYQ from `pyqs.json`
     -> Renders Slide 1 & Slide 2 (1080x1350 JPEGs) into `published/`
     -> Saves pending job metadata to `.pending_post.json`
  2. GitHub Actions commits & pushes `published/` so raw GitHub HTTPS URLs are live.
  3. `python3 auto_post.py --publish-only`
     -> Publishes the 2-slide carousel via Meta's Instagram Content Publishing API
     -> Marks the question `"posted": true` in `pyqs.json`
"""

import argparse
import base64
import html
import json
import os
import sys
import tempfile
import time
from pathlib import Path

import requests
from jinja2 import Template
from PIL import Image
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By

ROOT_DIR = Path(__file__).resolve().parent
TEMPLATE_PATH = ROOT_DIR / "slide_template.html"
PYQS_PATH = ROOT_DIR / "pyqs.json"
PUBLISHED_DIR = ROOT_DIR / "published"
PENDING_PATH = ROOT_DIR / ".pending_post.json"

IG_API_BASE = "https://graph.instagram.com/v21.0"


def format_question_html(question: str, highlight_phrase: str | None) -> str:
    escaped_q = html.escape(question)
    if highlight_phrase:
        escaped_hl = html.escape(highlight_phrase)
        if escaped_hl in escaped_q:
            return escaped_q.replace(
                escaped_hl,
                f'<span class="highlight-orange">{escaped_hl}</span>',
                1,
            )
    return escaped_q


def create_driver(width: int = 1080, height: int = 1500) -> webdriver.Chrome:
    os.environ.setdefault("DBUS_SESSION_BUS_ADDRESS", "/dev/null")
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--hide-scrollbars")
    options.add_argument(f"--window-size={width},{height}")
    options.add_argument("--force-device-scale-factor=1")
    driver = webdriver.Chrome(options=options)
    driver.set_window_size(width, height)
    return driver


def render_html_to_jpeg(
    driver: webdriver.Chrome,
    html_content: str,
    output_jpeg: Path,
    width: int = 1080,
    height: int = 1350,
    quality: int = 95,
) -> None:
    output_jpeg.parent.mkdir(parents=True, exist_ok=True)
    b64_html = base64.b64encode(html_content.encode("utf-8")).decode("ascii")
    driver.get(f"data:text/html;charset=utf-8;base64,{b64_html}")

    with tempfile.TemporaryDirectory(prefix="ig_render_") as tmpdir:
        png_file = Path(tmpdir) / "slide.png"
        canvas_el = driver.find_element(By.CSS_SELECTOR, ".canvas")
        canvas_el.screenshot(str(png_file))
        with Image.open(png_file) as img:
            rgb_img = img.convert("RGB")
            if rgb_img.size != (width, height):
                rgb_img = rgb_img.resize((width, height), Image.Resampling.LANCZOS)
            rgb_img.save(output_jpeg, format="JPEG", quality=quality, optimize=True)


def build_caption(quiz: dict) -> str:
    handle = quiz.get("brand_handle", "@ssc1.daily")
    exam_tag = quiz["exam_tag"]
    return (
        f"Can you solve this {exam_tag} question without looking at Slide 2? 👇\n\n"
        f"Drop A, B, C, or D in the comments first—then swipe to verify your answer "
        f"and grab the 1-minute NCERT revision flashcard!\n\n"
        f"Save this post for quick pre-exam revision and follow {handle} for 1 verified PYQ every day. ⚡\n\n"
        f"#SSCCGL #SSCCGL2026 #SSCStaticGK #SSCPYQ #NCERTNotes #GovtJobsIndia #SSCCHSL #SSCMTS"
    )


def render_next_unposted() -> None:
    pyqs = json.loads(PYQS_PATH.read_text(encoding="utf-8"))
    next_quiz = next((q for q in pyqs if not q.get("posted", False)), None)
    if not next_quiz:
        print("All PYQs in pyqs.json have already been posted! Add more questions.")
        sys.exit(0)

    template = Template(TEMPLATE_PATH.read_text(encoding="utf-8"))
    qid = next_quiz["id"]
    handle = next_quiz.get("brand_handle", "@ssc1.daily")

    slide1_html = template.render(
        slide_type="question",
        slide_number="1",
        badge_text=next_quiz["exam_tag"],
        question_html=format_question_html(
            next_quiz["question"], next_quiz.get("highlight_phrase")
        ),
        options=next_quiz["options"],
        cta_text="Comment Your Answer  •  Swipe →",
        brand_handle=handle,
    )
    slide2_html = template.render(
        slide_type="answer",
        slide_number="2",
        badge_text="ANSWER & NCERT FLASHCARD",
        correct_answer=next_quiz["correct_answer"],
        revision_notes=next_quiz["revision_notes"],
        cta_text="Save for Revision  •  Follow for Daily PYQs",
        brand_handle=handle,
    )

    slide1_path = PUBLISHED_DIR / f"{qid}_slide1.jpg"
    slide2_path = PUBLISHED_DIR / f"{qid}_slide2.jpg"

    driver = create_driver()
    try:
        render_html_to_jpeg(driver, slide1_html, slide1_path)
        render_html_to_jpeg(driver, slide2_html, slide2_path)
    finally:
        driver.quit()

    PENDING_PATH.write_text(
        json.dumps(
            {
                "id": qid,
                "slide1_rel": f"published/{slide1_path.name}",
                "slide2_rel": f"published/{slide2_path.name}",
                "caption": build_caption(next_quiz),
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print(f"Rendered {slide1_path.name} & {slide2_path.name}")


def ig_post(endpoint: str, payload: dict) -> dict:
    resp = requests.post(f"{IG_API_BASE}/{endpoint}", data=payload, timeout=30)
    data = resp.json()
    if resp.status_code >= 400 or "error" in data:
        raise RuntimeError(f"Instagram API error on {endpoint}: {data}")
    return data


def publish_pending() -> None:
    if not PENDING_PATH.exists():
        print("No pending post found (.pending_post.json missing). Skipping publish.")
        return

    token = os.environ.get("IG_ACCESS_TOKEN", "").strip()
    ig_user_id = os.environ.get("IG_USER_ID", "me").strip() or "me"
    repo = os.environ.get("GITHUB_REPOSITORY", "").strip()
    branch = os.environ.get("GITHUB_REF_NAME", "main").strip() or "main"

    if not token or not repo:
        raise RuntimeError(
            "Missing IG_ACCESS_TOKEN or GITHUB_REPOSITORY environment variables."
        )

    pending = json.loads(PENDING_PATH.read_text(encoding="utf-8"))
    raw_base = f"https://raw.githubusercontent.com/{repo}/{branch}"
    img1_url = f"{raw_base}/{pending['slide1_rel']}"
    img2_url = f"{raw_base}/{pending['slide2_rel']}"

    print(f"Publishing carousel from:\n  1) {img1_url}\n  2) {img2_url}")

    # Step 1: Create child media containers for Slide 1 & Slide 2
    c1 = ig_post(
        f"{ig_user_id}/media",
        {
            "image_url": img1_url,
            "is_carousel_item": "true",
            "access_token": token,
        },
    )["id"]

    c2 = ig_post(
        f"{ig_user_id}/media",
        {
            "image_url": img2_url,
            "is_carousel_item": "true",
            "access_token": token,
        },
    )["id"]

    time.sleep(5)

    # Step 2: Create parent CAROUSEL container
    parent_id = ig_post(
        f"{ig_user_id}/media",
        {
            "media_type": "CAROUSEL",
            "children": f"{c1},{c2}",
            "caption": pending["caption"],
            "access_token": token,
        },
    )["id"]

    time.sleep(5)

    # Step 3: Publish carousel
    published = ig_post(
        f"{ig_user_id}/media_publish",
        {
            "creation_id": parent_id,
            "access_token": token,
        },
    )
    print(f"Published successfully! Media ID: {published['id']}")

    # Step 4: Mark as posted in pyqs.json & remove .pending_post.json
    pyqs = json.loads(PYQS_PATH.read_text(encoding="utf-8"))
    for q in pyqs:
        if q["id"] == pending["id"]:
            q["posted"] = True
            q["ig_media_id"] = published["id"]
            break
    PYQS_PATH.write_text(
        json.dumps(pyqs, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    PENDING_PATH.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--render-only", action="store_true")
    parser.add_argument("--publish-only", action="store_true")
    args = parser.parse_args()

    if args.render_only:
        render_next_unposted()
    elif args.publish_only:
        publish_pending()
    else:
        render_next_unposted()
        publish_pending()


if __name__ == "__main__":
    main()