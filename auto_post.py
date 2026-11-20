#!/usr/bin/env python3
"""
Viral Hybrid SSC CGL Auto-Publisher (@ssc1.daily) — v5.1
--------------------------------------------------------
Engineered for maximum 2026 Instagram discovery reach, comments & saves:
  - Mon / Tue / Thu / Fri / Sat -> 6-second 9:16 (1080x1920) Open-Loop Exam-Paper Quiz Reel
      * Pattern-interrupt cream exam-paper UI + bold yellow trap highlighter
      * NO answer shown on screen -> drives 150%+ looping watch time & comments
      * Verified answer hidden below caption fold (`...more`)
      * Direct Meta Resumable Upload (`rupload.facebook.com`) with `video_url` fallback
  - Wed / Sun -> 4-Slide 3-Question Mini Mock Carousel (Dark Obsidian + Orange)
      * Drives high Saves & DM Sends for revision

Supports manual override via `--mode auto|reel|carousel`.
"""

import argparse
import base64
import datetime
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
REEL_PYQS_PATH = ROOT_DIR / "reel_pyqs.json"
PUBLISHED_DIR = ROOT_DIR / "published"
PENDING_PATH = ROOT_DIR / ".pending_post.json"

IG_API_BASE = (
    "https://graph.instagram.com/v21.0"
    if os.environ.get("IG_ACCESS_TOKEN", "").startswith("IG")
    else "https://graph.facebook.com/v21.0"
)

# IST = UTC+5:30; Wed(2) & Sun(6) -> 4-Slide Mini Mock Carousel; other 5 days -> Viral Open-Loop Reel
CAROUSEL_WEEKDAYS = {2, 6}


def resolve_mode(requested: str) -> str:
    if requested in ("carousel", "reel"):
        return requested
    ist_now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=5, minutes=30)))
    return "carousel" if ist_now.weekday() in CAROUSEL_WEEKDAYS else "reel"


def format_question_html(
    question: str, highlight_phrase: str | None, css_class: str = "highlight-orange"
) -> str:
    escaped_q = html.escape(question)
    if highlight_phrase:
        escaped_hl = html.escape(highlight_phrase)
        if escaped_hl in escaped_q:
            return escaped_q.replace(
                escaped_hl,
                f'<span class="{css_class}">{escaped_hl}</span>',
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


def build_carousel_caption(batch: list[dict]) -> str:
    handle = batch[0].get("brand_handle", "@ssc1.daily")
    topics = " • ".join(q.get("highlight_phrase", "Static GK") for q in batch)
    return (
        f"SSC CGL Daily 3-Question Mini Mock ({topics}) — Can you score 3/3? 🔥👇\n\n"
        f"90% aspirants miss at least 1 question! Solve Q1, Q2, and Q3 honestly, then swipe to Slide 4 for the verified Answer Key & NCERT notes.\n\n"
        f"💬 Comment your score: 3/3 🔥 | 2/3 ⚡ | 1/3 📖\n"
        f"✈️ Send this to your SSC study buddy and challenge them!\n"
        f"🔖 Save for 1-minute revision • Follow {handle} for daily PYQ mocks.\n\n"
        f"#SSCCGL2026 #SSCMiniMock #SSCStaticGK #SSCPYQ"
    )


def build_viral_reel_caption(quiz: dict) -> str:
    handle = quiz.get("brand_handle", "@ssc1.daily")
    topic = quiz.get("highlight_phrase", "SSC CGL PYQ")
    ans = quiz["correct_answer"]
    src = quiz.get("verified_source", "Official SSC PYQ & NCERT")
    explanation = quiz.get("explanation")
    if not explanation and quiz.get("revision_notes"):
        first = quiz["revision_notes"][0]
        explanation = f"{first.get('label', '')}: {first.get('detail', '')}".strip(": ")
    explanation = explanation or "Verified from Official SSC Answer Key & NCERT."

    return (
        f"Comment (a), (b), (c), or (d) BEFORE checking the answer! 👇🔥\n"
        f"Most SSC CGL aspirants fall for this '{topic}' trap — let's see who gets it right!\n\n"
        f"✈️ Send this to your SSC study partner to test them!\n"
        f"🔖 Save for quick revision • Follow {handle} for daily PYQ traps.\n"
        f".\n.\n.\n.\n"
        f"✅ Correct Answer: {ans}\n"
        f"📖 Explanation: {explanation}\n"
        f"✓ Source: {src}\n\n"
        f"#SSCCGL2026 #SSCPYQ #SSCStaticGK #GovtJobsIndia"
    )


def render_mini_mock(driver: webdriver.Chrome, template: Template, batch: list[dict]) -> dict:
    mock_id = f"mock_{batch[0]['id']}"
    handle = batch[0].get("brand_handle", "@ssc1.daily")

    ctas = [
        "Q1 of 3  •  Swipe for Q2 →",
        "Q2 of 3  •  Swipe for Q3 →",
        "Last Question!  Swipe for Score & Answers →",
    ]
    hooks = [
        "⚡ CAN YOU SCORE 3/3? • 90% ASPIRANTS MISS Q3!",
        "",
        "",
    ]

    slide_rels: list[str] = []
    for idx, quiz in enumerate(batch):
        slide_html = template.render(
            slide_type="question",
            badge_text=f"MINI MOCK • {quiz['exam_tag']}",
            page_label=f"Q{idx + 1} / 3",
            hook_text=hooks[idx],
            repeat_tag=quiz.get("repeat_tag", ""),
            difficulty=quiz.get("difficulty", ""),
            question_html=format_question_html(
                quiz["question"], quiz.get("highlight_phrase"), "highlight-orange"
            ),
            question_hi=quiz.get("question_hi", ""),
            options=quiz["options"],
            cta_text=ctas[idx],
            brand_handle=handle,
        )
        out_path = PUBLISHED_DIR / f"{mock_id}_slide{idx + 1}.jpg"
        render_html_to_image(driver, slide_html, out_path)
        slide_rels.append(f"published/{out_path.name}")

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
    render_html_to_image(driver, slide4_html, out_path4)
    slide_rels.append(f"published/{out_path4.name}")

    return {
        "post_type": "carousel",
        "source_file": "pyqs.json",
        "mock_id": mock_id,
        "question_ids": [q["id"] for q in batch],
        "slides": slide_rels,
        "caption": build_carousel_caption(batch),
    }


def render_viral_open_loop_reel(
    driver: webdriver.Chrome, template: Template, quiz: dict, source_file: str
) -> dict:
    qid = quiz["id"]
    handle = quiz.get("brand_handle", "@ssc1.daily")
    video_path = PUBLISHED_DIR / f"reel_{qid}.mp4"
    preview_path = PUBLISHED_DIR / f"reel_{qid}_preview.jpg"
    PUBLISHED_DIR.mkdir(parents=True, exist_ok=True)

    paper_options = [
        {"letter": opt["letter"].lower(), "text": opt["text"]}
        for opt in quiz["options"]
    ]

    reel_html = template.render(
        slide_type="viral_reel",
        badge_text=quiz["exam_tag"],
        hook_text=quiz.get("curiosity_tag", "90% Aspirants Get This Wrong!"),
        question_html=format_question_html(
            quiz["question"], quiz.get("highlight_phrase"), "highlight-yellow"
        ),
        question_hi=quiz.get("question_hi", ""),
        options=paper_options,
        brand_handle=handle,
    )
    render_html_to_image(driver, reel_html, preview_path, quality=96)

    # Strict Meta Reels-compliant 9:16 (1080x1920) MP4:
    # - Pads 1080x1350 card cleanly inside 1080x1920 safe zones with matching #fbf7ee cream
    # - Standard H.264 Main Profile, closed GOP (30fps, keyframe every 1s), 48kHz stereo AAC, faststart
    cmd = [
        "ffmpeg",
        "-y",
        "-loop", "1",
        "-framerate", "30",
        "-i", str(preview_path),
        "-f", "lavfi",
        "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
        "-t", "6",
        "-vf", "pad=1080:1920:0:285:color=#fbf7ee,format=yuv420p,fps=30",
        "-c:v", "libx264",
        "-profile:v", "main",
        "-level", "4.0",
        "-g", "30",
        "-keyint_min", "30",
        "-sc_threshold", "0",
        "-b:v", "2500k",
        "-maxrate", "4000k",
        "-bufsize", "5000k",
        "-c:a", "aac",
        "-ar", "48000",
        "-ac", "2",
        "-b:a", "128k",
        "-shortest",
        "-movflags", "+faststart",
        str(video_path),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if res.returncode != 0 or not video_path.exists():
        raise RuntimeError(f"ffmpeg failed: {res.stderr}")

    return {
        "post_type": "reel",
        "source_file": source_file,
        "mock_id": f"reel_{qid}",
        "question_ids": [qid],
        "video_rel": f"published/{video_path.name}",
        "preview_rel": f"published/{preview_path.name}",
        "caption": build_viral_reel_caption(quiz),
    }


def render_next(mode: str) -> None:
    chosen_mode = resolve_mode(mode)
    template = Template(TEMPLATE_PATH.read_text(encoding="utf-8"))

    if chosen_mode == "reel":
        source_file = "reel_pyqs.json"
        unposted_reel = []
        if REEL_PYQS_PATH.exists():
            reel_pyqs = json.loads(REEL_PYQS_PATH.read_text(encoding="utf-8"))
            unposted_reel = [q for q in reel_pyqs if not q.get("posted", False)]

        if unposted_reel:
            target_quiz = unposted_reel[0]
        else:
            source_file = "pyqs.json"
            pyqs = json.loads(PYQS_PATH.read_text(encoding="utf-8"))
            unposted = [q for q in pyqs if not q.get("posted", False)]
            if not unposted:
                print("All PYQs posted! Add more questions to reel_pyqs.json or pyqs.json.")
                sys.exit(0)
            target_quiz = unposted[0]

        driver = create_driver()
        try:
            pending = render_viral_open_loop_reel(driver, template, target_quiz, source_file)
        finally:
            driver.quit()
    else:
        pyqs = json.loads(PYQS_PATH.read_text(encoding="utf-8"))
        unposted = [q for q in pyqs if not q.get("posted", False)]
        if len(unposted) < 3:
            if len(unposted) >= 1:
                print("Less than 3 PYQs left in pyqs.json; falling back to Viral Reel mode.")
                driver = create_driver()
                try:
                    pending = render_viral_open_loop_reel(driver, template, unposted[0], "pyqs.json")
                finally:
                    driver.quit()
            else:
                print("All PYQs posted! Add more questions to pyqs.json.")
                sys.exit(0)
        else:
            driver = create_driver()
            try:
                pending = render_mini_mock(driver, template, unposted[:3])
            finally:
                driver.quit()

    PENDING_PATH.write_text(
        json.dumps(pending, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"Rendered ({pending['post_type']} from {pending['source_file']}): {pending['mock_id']}")


def ig_post(endpoint: str, payload: dict) -> dict:
    resp = requests.post(f"{IG_API_BASE}/{endpoint}", data=payload, timeout=30)
    data = resp.json()
    if resp.status_code >= 400 or "error" in data:
        raise RuntimeError(f"Instagram API error on {endpoint}: {data}")
    return data


def wait_for_container(container_id: str, token: str, timeout_sec: int = 120) -> None:
    start = time.time()
    while time.time() - start < timeout_sec:
        resp = requests.get(
            f"{IG_API_BASE}/{container_id}",
            params={"fields": "status_code,status", "access_token": token},
            timeout=20,
        ).json()
        status = resp.get("status_code")
        print(f"Container {container_id} status: {resp}")
        if status == "FINISHED":
            return
        if status in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"Media container failed: {resp}")
        time.sleep(5)
    raise TimeoutError(f"Timed out waiting for container {container_id}")


def upload_reel_resumable(
    ig_user_id: str, video_file: Path, caption: str, token: str
) -> str:
    """Upload local MP4 directly to Meta rupload.facebook.com (bypasses GitHub raw MIME issues)."""
    init_resp = ig_post(
        f"{ig_user_id}/media",
        {
            "media_type": "REELS",
            "upload_type": "resumable",
            "caption": caption,
            "share_to_feed": "true",
            "access_token": token,
        },
    )
    container_id = init_resp["id"]
    upload_uri = init_resp.get(
        "uri", f"https://rupload.facebook.com/ig-api-upload/v21.0/{container_id}"
    )
    video_bytes = video_file.read_bytes()
    print(f"Uploading {len(video_bytes)} bytes directly to {upload_uri} ...")
    up_resp = requests.post(
        upload_uri,
        headers={
            "Authorization": f"OAuth {token}",
            "offset": "0",
            "file_size": str(len(video_bytes)),
            "Content-Type": "application/octet-stream",
        },
        data=video_bytes,
        timeout=90,
    )
    if up_resp.status_code >= 400:
        raise RuntimeError(f"Resumable upload failed ({up_resp.status_code}): {up_resp.text}")
    print(f"Resumable upload response: {up_resp.text}")
    return container_id


def publish_pending() -> None:
    if not PENDING_PATH.exists():
        print("No pending post found (.pending_post.json missing). Skipping.")
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
        local_video = ROOT_DIR / pending["video_rel"]
        container_id = None

        # Prefer direct binary resumable upload on Facebook Login / Unified Login (EAA... tokens)
        if not token.startswith("IG") and local_video.exists():
            try:
                container_id = upload_reel_resumable(
                    ig_user_id, local_video, pending["caption"], token
                )
            except Exception as exc:
                print(f"Resumable upload fallback triggered: {exc}")

        if not container_id:
            video_url = f"{raw_base}/{pending['video_rel']}"
            print(f"Publishing 6s 9:16 Viral Quiz Reel via URL: {video_url}")
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

    print(f"Published ({pending['post_type']})! Media ID: {published['id']}")

    source_path = ROOT_DIR / pending.get("source_file", "pyqs.json")
    pyqs = json.loads(source_path.read_text(encoding="utf-8"))
    posted_set = set(pending["question_ids"])
    for q in pyqs:
        if q["id"] in posted_set:
            q["posted"] = True
            q["ig_media_id"] = published["id"]
    source_path.write_text(
        json.dumps(pyqs, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    PENDING_PATH.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--render-only", action="store_true")
    parser.add_argument("--publish-only", action="store_true")
    parser.add_argument("--mode", choices=["auto", "carousel", "reel"], default="auto")
    args = parser.parse_args()

    if args.render_only:
        render_next(args.mode)
    elif args.publish_only:
        publish_pending()
    else:
        render_next(args.mode)
        publish_pending()


if __name__ == "__main__":
    main()