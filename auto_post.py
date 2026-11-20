#!/usr/bin/env python3
"""
Automated SSC CGL Carousel + 7-Second Countdown Reel Publisher (@ssc1.daily)
----------------------------------------------------------------------------
Supports BOTH:
  1. 2-Slide Carousels (Question + Bilingual Hindi + Answer/NCERT Flashcard)
  2. 7-Second Countdown Quiz Reels (5s countdown timer + 2s Answer reveal MP4)

Designed for ₹0/month GitHub Actions execution (zero external image/video host).
"""

import argparse
import base64
import html
import json
import os
import subprocess
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
    driver = webdriver.Chrome(options=options)
    return driver


def render_html_to_image(
    driver: webdriver.Chrome,
    html_content: str,
    output_path: Path,
    width: int = 1080,
    height: int = 1350,
    quality: int = 95,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
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
            fmt = "PNG" if output_path.suffix.lower() == ".png" else "JPEG"
            save_kwargs = {"optimize": True}
            if fmt == "JPEG":
                save_kwargs["quality"] = quality
            rgb_img.save(output_path, format=fmt, **save_kwargs)


def build_seo_caption(quiz: dict) -> str:
    """2026 Instagram SEO-optimized caption (natural keywords, strong CTA, minimal hashtags)."""
    handle = quiz.get("brand_handle", "@ssc1.daily")
    exam_tag = quiz["exam_tag"]
    topic = quiz.get("highlight_phrase") or "Static GK"
    source = quiz.get("verified_source", "Official SSC Answer Key & NCERT")
    is_reel = quiz.get("post_type", "carousel") == "reel"

    action_line = (
        "Pause before the 5-second timer ends and comment A, B, C, or D! ⏱️👇"
        if is_reel
        else "Comment A, B, C, or D first—then swipe to Slide 2 for the answer & 1-minute NCERT notes! 👇"
    )

    return (
        f"{exam_tag} Official PYQ on {topic} — can you crack it in 5 seconds?\n\n"
        f"{action_line}\n\n"
        f"✈️ Send this to your SSC study partner to test their prep!\n"
        f"🔖 Save for quick exam revision • Verified: {source}\n"
        f"Follow {handle} for 1 verified SSC CGL Static GK PYQ every morning.\n\n"
        f"#SSCCGL2026 #SSCPYQ #SSCStaticGK #NCERTNotes"
    )


def render_carousel_assets(driver: webdriver.Chrome, template: Template, quiz: dict) -> dict:
    qid = quiz["id"]
    handle = quiz.get("brand_handle", "@ssc1.daily")

    slide1_html = template.render(
        slide_type="question",
        page_label="1 / 2",
        badge_text=quiz["exam_tag"],
        repeat_tag=quiz.get("repeat_tag", ""),
        difficulty=quiz.get("difficulty", ""),
        question_html=format_question_html(quiz["question"], quiz.get("highlight_phrase")),
        question_hi=quiz.get("question_hi", ""),
        options=quiz["options"],
        cta_text="Comment A / B / C / D  •  Swipe →",
        brand_handle=handle,
    )
    slide2_html = template.render(
        slide_type="answer",
        page_label="2 / 2",
        badge_text="ANSWER & NCERT FLASHCARD",
        correct_answer=quiz["correct_answer"],
        revision_notes=quiz["revision_notes"],
        verified_source=quiz.get("verified_source", ""),
        cta_text="Send to your SSC buddy ✈️  •  Save for Revision",
        brand_handle=handle,
    )

    s1 = PUBLISHED_DIR / f"{qid}_slide1.jpg"
    s2 = PUBLISHED_DIR / f"{qid}_slide2.jpg"
    render_html_to_image(driver, slide1_html, s1)
    render_html_to_image(driver, slide2_html, s2)

    return {
        "id": qid,
        "post_type": "carousel",
        "slide1_rel": f"published/{s1.name}",
        "slide2_rel": f"published/{s2.name}",
        "caption": build_seo_caption(quiz),
    }


def render_reel_assets(driver: webdriver.Chrome, template: Template, quiz: dict) -> dict:
    """Build a 7-second 1080x1350 H.264 MP4 countdown quiz Reel using ffmpeg."""
    qid = quiz["id"]
    handle = quiz.get("brand_handle", "@ssc1.daily")
    video_path = PUBLISHED_DIR / f"{qid}_reel.mp4"
    PUBLISHED_DIR.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="ig_reel_") as tmpdir:
        tmp = Path(tmpdir)
        concat_lines = []

        # 5 countdown frames (1 second each: 5s -> 1s)
        for idx, sec in enumerate([5, 4, 3, 2, 1]):
            pct = int((sec / 5) * 100)
            frame_html = template.render(
                slide_type="reel_question",
                page_label="5s QUIZ",
                badge_text=quiz["exam_tag"],
                repeat_tag=quiz.get("repeat_tag", ""),
                difficulty=quiz.get("difficulty", ""),
                question_html=format_question_html(
                    quiz["question"], quiz.get("highlight_phrase")
                ),
                question_hi=quiz.get("question_hi", ""),
                options=quiz["options"],
                seconds_left=sec,
                progress_pct=pct,
                brand_handle=handle,
            )
            frame_png = tmp / f"frame_{idx}.png"
            render_html_to_image(driver, frame_html, frame_png)
            concat_lines.append(f"file '{frame_png}'\nduration 1\n")

        # 2.5-second answer reveal frame
        ans_html = template.render(
            slide_type="answer",
            page_label="ANSWER",
            badge_text="ANSWER & NCERT FLASHCARD",
            correct_answer=quiz["correct_answer"],
            revision_notes=quiz["revision_notes"],
            verified_source=quiz.get("verified_source", ""),
            cta_text="Send to your SSC buddy ✈️  •  Save to Revise",
            brand_handle=handle,
        )
        ans_png = tmp / "frame_answer.png"
        render_html_to_image(driver, ans_html, ans_png)
        concat_lines.append(f"file '{ans_png}'\nduration 2.5\n")
        concat_lines.append(f"file '{ans_png}'\n")  # ffmpeg concat demuxer requirement

        concat_file = tmp / "frames.txt"
        concat_file.write_text("".join(concat_lines), encoding="utf-8")

        # Encode silent stereo AAC + H.264 yuv420p (100% Instagram Reels compliant)
        cmd = [
            "ffmpeg",
            "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", str(concat_file),
            "-f", "lavfi",
            "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
            "-c:v", "libx264",
            "-r", "30",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-shortest",
            "-movflags", "+faststart",
            str(video_path),
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if res.returncode != 0 or not video_path.exists():
            raise RuntimeError(f"ffmpeg failed: {res.stderr}")

    return {
        "id": qid,
        "post_type": "reel",
        "video_rel": f"published/{video_path.name}",
        "caption": build_seo_caption(quiz),
    }


def render_next_unposted(force_id: str | None = None) -> None:
    pyqs = json.loads(PYQS_PATH.read_text(encoding="utf-8"))
    if force_id:
        next_quiz = next((q for q in pyqs if q["id"] == force_id), None)
    else:
        next_quiz = next((q for q in pyqs if not q.get("posted", False)), None)

    if not next_quiz:
        print("All PYQs in pyqs.json have already been posted! Add more questions.")
        sys.exit(0)

    template = Template(TEMPLATE_PATH.read_text(encoding="utf-8"))
    post_type = next_quiz.get("post_type", "carousel")

    driver = create_driver()
    try:
        if post_type == "reel":
            pending = render_reel_assets(driver, template, next_quiz)
        else:
            pending = render_carousel_assets(driver, template, next_quiz)
    finally:
        driver.quit()

    PENDING_PATH.write_text(
        json.dumps(pending, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"Rendered {post_type}: {pending['id']}")


def ig_post(endpoint: str, payload: dict) -> dict:
    resp = requests.post(f"{IG_API_BASE}/{endpoint}", data=payload, timeout=30)
    data = resp.json()
    if resp.status_code >= 400 or "error" in data:
        raise RuntimeError(f"Instagram API error on {endpoint}: {data}")
    return data


def wait_for_container(container_id: str, token: str, timeout_sec: int = 90) -> None:
    start = time.time()
    while time.time() - start < timeout_sec:
        resp = requests.get(
            f"{IG_API_BASE}/{container_id}",
            params={"fields": "status_code", "access_token": token},
            timeout=20,
        ).json()
        status = resp.get("status_code")
        if status == "FINISHED":
            return
        if status in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"Media container failed: {resp}")
        time.sleep(5)
    raise TimeoutError(f"Timed out waiting for media container {container_id}")


def publish_pending() -> None:
    if not PENDING_PATH.exists():
        print("No pending post found (.pending_post.json missing). Skipping publish.")
        return

    token = os.environ.get("IG_ACCESS_TOKEN", "").strip()
    ig_user_id = os.environ.get("IG_USER_ID", "me").strip() or "me"
    repo = os.environ.get("GITHUB_REPOSITORY", "").strip()
    branch = os.environ.get("GITHUB_REF_NAME", "main").strip() or "main"

    if not token or not repo:
        raise RuntimeError("Missing IG_ACCESS_TOKEN or GITHUB_REPOSITORY.")

    pending = json.loads(PENDING_PATH.read_text(encoding="utf-8"))
    raw_base = f"https://raw.githubusercontent.com/{repo}/{branch}"

    if pending.get("post_type") == "reel":
        video_url = f"{raw_base}/{pending['video_rel']}"
        print(f"Publishing 7s Quiz Reel from: {video_url}")
        container_id = ig_post(
            f"{ig_user_id}/media",
            {
                "media_type": "REELS",
                "video_url": video_url,
                "caption": pending["caption"],
                "share_to_feed": "true",
                "access_token": token,
            },
        )["id"]
        wait_for_container(container_id, token)
        published = ig_post(
            f"{ig_user_id}/media_publish",
            {"creation_id": container_id, "access_token": token},
        )
    else:
        img1_url = f"{raw_base}/{pending['slide1_rel']}"
        img2_url = f"{raw_base}/{pending['slide2_rel']}"
        print(f"Publishing 2-slide carousel from:\n  1) {img1_url}\n  2) {img2_url}")
        c1 = ig_post(
            f"{ig_user_id}/media",
            {"image_url": img1_url, "is_carousel_item": "true", "access_token": token},
        )["id"]
        c2 = ig_post(
            f"{ig_user_id}/media",
            {"image_url": img2_url, "is_carousel_item": "true", "access_token": token},
        )["id"]
        time.sleep(5)
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
        published = ig_post(
            f"{ig_user_id}/media_publish",
            {"creation_id": parent_id, "access_token": token},
        )

    print(f"Published successfully! Media ID: {published['id']}")

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
    parser.add_argument("--force-id", type=str, default=None)
    args = parser.parse_args()

    if args.render_only:
        render_next_unposted(force_id=args.force_id)
    elif args.publish_only:
        publish_pending()
    else:
        render_next_unposted(force_id=args.force_id)
        publish_pending()


if __name__ == "__main__":
    main()