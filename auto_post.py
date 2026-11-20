#!/usr/bin/env python3
"""
Automated SSC CGL 3-Question Mini Mock Carousel Publisher (@ssc1.daily)
-----------------------------------------------------------------------
Picks the next 3 unposted PYQs from `pyqs.json`, renders a 4-slide 1080x1350
bilingual carousel (Slides 1-3: Questions, Slide 4: Answer Key + X/3 Scorecard),
and auto-publishes it to Instagram via Meta's Content Publishing API.
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

IG_API_BASE = (
    "https://graph.instagram.com/v21.0"
    if os.environ.get("IG_ACCESS_TOKEN", "").startswith("IG")
    else "https://graph.facebook.com/v21.0"
)


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
    return webdriver.Chrome(options=options)


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


def build_mock_caption(batch: list[dict]) -> str:
    handle = batch[0].get("brand_handle", "@ssc1.daily")
    topics = " • ".join(q.get("highlight_phrase", "Static GK") for q in batch)
    return (
        f"SSC CGL Daily 3-Question Mini Mock ({topics}) — Can you score 3/3? 🔥👇\n\n"
        f"Solve Q1, Q2, and Q3 honestly, then swipe to Slide 4 for the verified Answer Key & NCERT notes!\n\n"
        f"💬 Comment your score: 3/3 🔥 | 2/3 ⚡ | 1/3 📖\n"
        f"✈️ Send this to your SSC study buddy and challenge them to beat your score!\n"
        f"🔖 Save for 1-minute revision • Follow {handle} for daily PYQ mocks.\n\n"
        f"#SSCCGL2026 #SSCMiniMock #SSCStaticGK #SSCPYQ"
    )


def render_next_mini_mock() -> None:
    pyqs = json.loads(PYQS_PATH.read_text(encoding="utf-8"))
    unposted = [q for q in pyqs if not q.get("posted", False)]
    if len(unposted) < 3:
        print(
            f"Need at least 3 unposted PYQs for a Mini Mock (found {len(unposted)}). Add more to pyqs.json!"
        )
        sys.exit(0)

    batch = unposted[:3]
    template = Template(TEMPLATE_PATH.read_text(encoding="utf-8"))
    mock_id = f"mock_{batch[0]['id']}"
    handle = batch[0].get("brand_handle", "@ssc1.daily")

    ctas = [
        "Q1 of 3  •  Swipe for Q2 →",
        "Q2 of 3  •  Swipe for Q3 →",
        "Last Question!  Swipe for Score & Answers →",
    ]

    slide_rels: list[str] = []
    driver = create_driver()
    try:
        # Slides 1, 2, 3: Questions
        for idx, quiz in enumerate(batch):
            slide_html = template.render(
                slide_type="question",
                badge_text=f"MINI MOCK • {quiz['exam_tag']}",
                page_label=f"Q{idx + 1} / 3",
                repeat_tag=quiz.get("repeat_tag", ""),
                difficulty=quiz.get("difficulty", ""),
                question_html=format_question_html(
                    quiz["question"], quiz.get("highlight_phrase")
                ),
                question_hi=quiz.get("question_hi", ""),
                options=quiz["options"],
                cta_text=ctas[idx],
                brand_handle=handle,
            )
            out_path = PUBLISHED_DIR / f"{mock_id}_slide{idx + 1}.jpg"
            render_html_to_jpeg(driver, slide_html, out_path)
            slide_rels.append(f"published/{out_path.name}")

        # Slide 4: Answer Key + Scorecard
        mock_answers = []
        for quiz in batch:
            first_note = (quiz.get("revision_notes") or [{}])[0]
            mock_answers.append(
                {
                    "correct_answer": quiz["correct_answer"],
                    "note_label": first_note.get("label", "Key Fact"),
                    "note_detail": first_note.get("detail", ""),
                    "verified_source": quiz.get(
                        "verified_source", "Official SSC Answer Key & NCERT"
                    ),
                }
            )

        slide4_html = template.render(
            slide_type="scorecard",
            badge_text="SSC CGL MINI MOCK • RESULTS",
            page_label="4 / 4",
            mock_answers=mock_answers,
            cta_text="Comment your score (X/3) & send to a buddy ✈️",
            brand_handle=handle,
        )
        out_path4 = PUBLISHED_DIR / f"{mock_id}_slide4.jpg"
        render_html_to_jpeg(driver, slide4_html, out_path4)
        slide_rels.append(f"published/{out_path4.name}")
    finally:
        driver.quit()

    PENDING_PATH.write_text(
        json.dumps(
            {
                "mock_id": mock_id,
                "question_ids": [q["id"] for q in batch],
                "slides": slide_rels,
                "caption": build_mock_caption(batch),
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print(f"Rendered 4-slide Mini Mock: {mock_id} ({len(slide_rels)} slides)")


def ig_post(endpoint: str, payload: dict) -> dict:
    resp = requests.post(f"{IG_API_BASE}/{endpoint}", data=payload, timeout=30)
    data = resp.json()
    if resp.status_code >= 400 or "error" in data:
        raise RuntimeError(f"Instagram API error on {endpoint}: {data}")
    return data


def publish_pending() -> None:
    if not PENDING_PATH.exists():
        print("No pending Mini Mock found (.pending_post.json missing). Skipping.")
        return

    token = os.environ.get("IG_ACCESS_TOKEN", "").strip()
    ig_user_id = os.environ.get("IG_USER_ID", "me").strip() or "me"
    repo = os.environ.get("GITHUB_REPOSITORY", "").strip()
    branch = os.environ.get("GITHUB_REF_NAME", "main").strip() or "main"

    if not token or not repo:
        raise RuntimeError("Missing IG_ACCESS_TOKEN or GITHUB_REPOSITORY.")

    pending = json.loads(PENDING_PATH.read_text(encoding="utf-8"))
    raw_base = f"https://raw.githubusercontent.com/{repo}/{branch}"

    child_ids = []
    for rel in pending["slides"]:
        img_url = f"{raw_base}/{rel}"
        print(f"Uploading carousel slide: {img_url}")
        cid = ig_post(
            f"{ig_user_id}/media",
            {"image_url": img_url, "is_carousel_item": "true", "access_token": token},
        )["id"]
        child_ids.append(cid)

    time.sleep(6)

    parent_id = ig_post(
        f"{ig_user_id}/media",
        {
            "media_type": "CAROUSEL",
            "children": ",".join(child_ids),
            "caption": pending["caption"],
            "access_token": token,
        },
    )["id"]

    time.sleep(6)

    published = ig_post(
        f"{ig_user_id}/media_publish",
        {"creation_id": parent_id, "access_token": token},
    )
    print(f"Published 4-slide Mini Mock! Media ID: {published['id']}")

    pyqs = json.loads(PYQS_PATH.read_text(encoding="utf-8"))
    posted_set = set(pending["question_ids"])
    for q in pyqs:
        if q["id"] in posted_set:
            q["posted"] = True
            q["ig_media_id"] = published["id"]
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
        render_next_mini_mock()
    elif args.publish_only:
        publish_pending()
    else:
        render_next_mini_mock()
        publish_pending()


if __name__ == "__main__":
    main()