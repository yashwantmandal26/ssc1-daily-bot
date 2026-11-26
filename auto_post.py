#!/usr/bin/env python3
"""
Viral Hybrid SSC CGL Auto-Publisher (@ssc1.daily) - v6
------------------------------------------------------
Runs 2x daily on GitHub Actions (8:17 AM IST & 7:17 PM IST):
  - Morning (8:17 AM IST):
      * Mon / Tue / Thu / Fri / Sat -> 7-second 9:16 Exam-Paper Open-Loop Quiz Reel
      * Wed / Sun                   -> 4-Slide iOS Liquid Glass Light-Orange Mini Mock Carousel
  - Evening (7:17 PM IST):
      * Every day (Mon–Sun)         -> 7-second 9:16 Exam-Paper Open-Loop Quiz Reel

Features:
  - Soft, 100% copyright-free warm ambient lo-fi study pad BGM synthesized locally
  - Direct Meta Resumable Binary Upload (`rupload.facebook.com`) with `video_url` fallback
  - Detailed container `status_code,status` polling
  - Supports manual override via `--mode auto|reel|carousel`
"""

import argparse
import base64
import datetime
import html
import json
import math
import os
import random
import struct
import subprocess
import sys
import tempfile
import time
import wave
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

# IST = UTC+5:30; Wed(2) & Sun(6) morning (<15:00 IST) -> 4-Slide Mini Mock; all other slots -> Viral Reel
CAROUSEL_WEEKDAYS = set()  # 100% Reels (2/day) until 500+ followers; set {2, 6} to re-enable Carousels



LEVEL_CYCLE = ["Easy", "Medium", "Hard"]

# Balanced Easy -> Medium -> Hard rotation across all SSC CGL Reel PYQs
DIFFICULTY_MAP = {
    # Easy (direct NCERT / high-frequency fundamentals)
    "viral_science_03": "Easy", "viral_science_04": "Easy", "viral_science_05": "Easy",
    "viral_polity_08": "Easy", "viral_science_06": "Easy", "viral_science_07": "Easy",
    "viral_computer_03": "Easy", "viral_polity_11": "Easy", "viral_polity_15": "Easy",
    "viral_polity_17": "Easy", "viral_polity_18": "Easy", "viral_polity_22": "Easy",
    "viral_polity_23": "Easy", "viral_polity_24": "Easy", "viral_history_08": "Easy",
    "viral_history_10": "Easy", "viral_history_15": "Easy", "viral_history_16": "Easy",
    "viral_history_17": "Easy", "viral_geo_06": "Easy", "viral_geo_08": "Easy",
    "viral_geo_09": "Easy", "viral_geo_11": "Easy", "viral_geo_14": "Easy",
    "viral_geo_16": "Easy", "viral_science_08": "Easy", "viral_science_10": "Easy",
    "viral_science_11": "Easy", "viral_science_13": "Easy", "viral_science_15": "Easy",
    "viral_science_16": "Easy", "viral_science_18": "Easy", "viral_science_21": "Easy",
    "viral_science_22": "Easy", "viral_static_05": "Easy", "viral_computer_07": "Easy",
    "viral_computer_11": "Easy", "viral_eng_05": "Easy",
    # Medium (classic SSC traps & comparison questions)
    "viral_geo_02": "Medium", "viral_history_02": "Medium", "viral_polity_06": "Medium",
    "viral_polity_07": "Medium", "viral_history_03": "Medium", "viral_economy_02": "Medium",
    "viral_geo_03": "Medium", "viral_computer_02": "Medium", "viral_static_01": "Medium",
    "viral_polity_09": "Medium", "viral_geo_04": "Medium", "viral_polity_10": "Medium",
    "viral_polity_12": "Medium", "viral_polity_13": "Medium", "viral_polity_20": "Medium",
    "viral_polity_21": "Medium", "viral_history_05": "Medium", "viral_history_07": "Medium",
    "viral_history_09": "Medium", "viral_history_11": "Medium", "viral_history_13": "Medium",
    "viral_history_14": "Medium", "viral_geo_07": "Medium", "viral_geo_10": "Medium",
    "viral_geo_12": "Medium", "viral_geo_13": "Medium", "viral_science_09": "Medium",
    "viral_science_12": "Medium", "viral_science_14": "Medium", "viral_science_17": "Medium",
    "viral_science_19": "Medium", "viral_economy_04": "Medium", "viral_economy_05": "Medium",
    "viral_economy_06": "Medium", "viral_static_02": "Medium", "viral_static_07": "Medium",
    "viral_computer_04": "Medium", "viral_computer_06": "Medium", "viral_computer_09": "Medium",
    "viral_eng_01": "Medium", "viral_eng_03": "Medium", "viral_eng_06": "Medium",
    # Hard (tricky exceptions, deep Articles, Tier-2 & chronology traps)
    "viral_history_04": "Hard", "viral_polity_14": "Hard", "viral_polity_16": "Hard",
    "viral_polity_19": "Hard", "viral_history_06": "Hard", "viral_history_12": "Hard",
    "viral_geo_05": "Hard", "viral_geo_15": "Hard", "viral_science_20": "Hard",
    "viral_economy_03": "Hard", "viral_static_03": "Hard", "viral_static_04": "Hard",
    "viral_static_06": "Hard", "viral_computer_05": "Hard", "viral_computer_08": "Hard",
    "viral_computer_10": "Hard", "viral_eng_02": "Hard", "viral_eng_04": "Hard",
    "viral_eng_07": "Hard",
}


def get_quiz_difficulty(quiz: dict) -> str:
    if quiz.get("difficulty") in ("Easy", "Medium", "Hard"):
        return quiz["difficulty"]
    return DIFFICULTY_MAP.get(quiz.get("id", ""), "Medium")


def pick_next_reel_by_difficulty(all_reels: list[dict]) -> dict | None:
    unposted = [q for q in all_reels if not q.get("posted", False)]
    if not unposted:
        return None
    posted_count = sum(1 for q in all_reels if q.get("posted", False))
    target_level = LEVEL_CYCLE[posted_count % 3]
    print(f"Difficulty loop -> Posted so far: {posted_count} | Target next level: {target_level}")
    for q in unposted:
        if get_quiz_difficulty(q) == target_level:
            return q
    return unposted[0]

def resolve_mode(requested: str) -> str:
    if requested in ("carousel", "reel"):
        return requested
    ist_now = datetime.datetime.now(
        datetime.timezone(datetime.timedelta(hours=5, minutes=30))
    )
    if ist_now.hour < 15 and ist_now.weekday() in CAROUSEL_WEEKDAYS:
        return "carousel"
    return "reel"


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


def create_driver(width: int = 1080, height: int = 2000) -> webdriver.Chrome:
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


def generate_ambient_pad_wav(output_wav: Path, duration_sec: float = 6.0, sr: int = 48000) -> None:
    """Synthesize a soft, warm, copyright-free lo-fi study pad (Cmaj9 -> Fmaj7 gentle swell)."""
    n_samples = int(duration_sec * sr)
    # Warm low-mid chord voices (Hz): C3, G3, B3, D4, E4 with subtle stereo detune
    chord_a = [130.81, 196.00, 246.94, 293.66, 329.63]
    chord_b = [174.61, 220.00, 261.63, 329.63, 392.00]
    amp = 0.055  # Gentle background ambience (~-22 dBFS)

    frames = bytearray()
    for i in range(n_samples):
        t = i / sr
        # Smooth crossfade from chord A to chord B around midpoint
        blend = 0.5 * (1.0 + math.tanh((t - duration_sec * 0.52) * 1.4))
        # Gentle breathing LFO
        lfo = 0.85 + 0.15 * math.sin(2.0 * math.pi * 0.35 * t)
        # Smooth 0.6s fade-in and 0.8s fade-out for seamless Reel looping
        env = 1.0
        if t < 0.6:
            env = t / 0.6
        elif t > duration_sec - 0.8:
            env = max(0.0, (duration_sec - t) / 0.8)

        left = 0.0
        right = 0.0
        for idx, (fa, fb) in enumerate(zip(chord_a, chord_b)):
            wa = math.sin(2.0 * math.pi * fa * t) + 0.25 * math.sin(4.0 * math.pi * fa * t)
            wb = math.sin(2.0 * math.pi * fb * t) + 0.25 * math.sin(4.0 * math.pi * fb * t)
            val = (1.0 - blend) * wa + blend * wb
            # Slight stereo width via tiny frequency offset
            wa_r = math.sin(2.0 * math.pi * (fa + 0.25) * t + 0.4)
            wb_r = math.sin(2.0 * math.pi * (fb + 0.25) * t + 0.4)
            val_r = (1.0 - blend) * wa_r + blend * wb_r
            weight = 1.0 if idx < 2 else 0.65
            left += val * weight
            right += val_r * weight

        s_l = max(-0.95, min(0.95, left * amp * lfo * env))
        s_r = max(-0.95, min(0.95, right * amp * lfo * env))
        frames += struct.pack("<hh", int(s_l * 32767), int(s_r * 32767))

    with wave.open(str(output_wav), "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(bytes(frames))


def build_carousel_caption(batch: list[dict]) -> str:
    handle = batch[0].get("brand_handle", "@ssc1.daily")
    topics = " • ".join(q.get("highlight_phrase", "Static GK") for q in batch)
    return (
        f"SSC CGL Daily 3-Question Mini Mock ({topics}) - Can you score 3/3? 🔥👇\n\n"
        f"90% aspirants miss at least 1 question! Solve Q1, Q2, and Q3 honestly, then swipe to Slide 4 for the verified Answer Key & NCERT notes.\n\n"
        f"💬 Comment your score: 3/3 🔥 | 2/3 ⚡ | 1/3 📖\n"
        f"✈️ Send this to your SSC study buddy and challenge them!\n"
        f"🔖 Save for 1-minute revision • Follow {handle} for daily PYQ mocks.\n\n"
        f"#SSCCGL2026 #SSCMiniMock #SSCStaticGK #SSCPYQ"
    )


def _extract_subject(exam_tag: str) -> str:
    if "•" in exam_tag:
        raw_subject = exam_tag.split("•", 1)[1].strip()
    elif "|" in exam_tag:
        raw_subject = exam_tag.split("|", 1)[1].strip()
    else:
        raw_subject = ""

    raw_subject = " ".join(raw_subject.replace("—", "-").replace("–", "-").split())
    if not raw_subject or raw_subject.upper() in {"PYQ", "SSC", "SSC CGL"}:
        return "Static GK"

    acronyms = {"GK", "GS", "IT", "CA"}
    words = []
    for word in raw_subject.split():
        if word.upper() in acronyms:
            words.append(word.upper())
        else:
            words.append(word.capitalize())
    return " ".join(words)


def build_youtube_short_title(quiz: dict) -> str:
    subject = _extract_subject(quiz.get("exam_tag", ""))
    suffix = f" | SSC CGL {subject} PYQ #shorts #ssccgl"
    max_total = 94

    highlight = " ".join(
        (quiz.get("highlight_phrase") or "")
        .replace("—", "-")
        .replace("–", "-")
        .split()
    )
    question = " ".join(
        (quiz.get("question") or "Daily GK Quiz")
        .replace("—", "-")
        .replace("–", "-")
        .split()
    )

    topic = highlight if len(highlight) >= 12 else question
    budget = max_total - len(suffix)
    if len(topic) > budget:
        trimmed = topic[: max(1, budget - 3)].rsplit(" ", 1)[0].rstrip(" ,.;:-?!")
        if not trimmed:
            trimmed = topic[: max(1, budget - 3)].rstrip()
        topic = f"{trimmed}..."

    return f"{topic}{suffix}"[:max_total]


def build_youtube_short_description(quiz: dict) -> str:
    subject = _extract_subject(quiz.get("exam_tag", ""))
    subject_hashtag = "".join(ch for ch in subject.lower() if ch.isalnum()) or "staticgk"

    ans = quiz["correct_answer"]
    src = quiz.get("verified_source", "Official SSC PYQ & NCERT")
    explanation = quiz.get("explanation")
    if not explanation and quiz.get("revision_notes"):
        first = quiz["revision_notes"][0]
        explanation = f"{first.get('label', '')}: {first.get('detail', '')}".strip(": ")
    explanation = explanation or "Verified from Official SSC Answer Key & NCERT."

    lines = [
        "Comment (a), (b), (c), or (d) before checking the answer below!",
        "",
        f"Q: {quiz['question']}",
    ]
    question_hi = (quiz.get("question_hi") or "").strip()
    if question_hi:
        lines.append(f"प्रश्न: {question_hi}")

    lines.append("")
    for opt in quiz["options"]:
        lines.append(f"({opt['letter'].lower()}) {opt['text']}")

    lines.extend([
        ".",
        ".",
        ".",
        f"✅ Correct Answer: {ans}",
        f"📖 Explanation: {explanation}",
        f"✓ Source: {src}",
        "",
        "Subscribe to @ssc1daily for 2 daily 7-second SSC CGL, CHSL, CPO & MTS PYQ quizzes!",
        "Instagram: https://www.instagram.com/ssc1.daily/",
        "",
    ])

    hashtags: list[str] = []
    for tag in ["shorts", "ssccgl", "sscpyq", subject_hashtag, "staticgk", "gkquiz"]:
        clean = f"#{tag.lower()}"
        if clean not in hashtags:
            hashtags.append(clean)
        if len(hashtags) == 5:
            break
    lines.append(" ".join(hashtags))
    return "\n".join(lines)


def build_youtube_short_tags(quiz: dict) -> list[str]:
    subject = _extract_subject(quiz.get("exam_tag", ""))
    candidates = [
        "SSC CGL",
        "SSC CGL 2026",
        "SSC CGL PYQ",
        "SSC CHSL",
        "SSC CPO",
        "SSC MTS",
        "Static GK",
        "SSC GK Quiz",
        "Shorts",
        f"{subject} PYQ",
        f"{subject} for SSC CGL",
    ]
    if subject.lower() in {"polity", "history", "geography", "economy", "economics", "constitution"}:
        candidates.append(f"Indian {subject}")

    highlight = " ".join((quiz.get("highlight_phrase") or "").split())
    if highlight:
        candidates.append(highlight)

    tags: list[str] = []
    seen: set[str] = set()
    for tag in candidates:
        key = tag.strip().lower()
        if not key or key in seen:
            continue
        candidate_list = tags + [tag.strip()]
        if len(",".join(candidate_list)) >= 500:
            continue
        seen.add(key)
        tags.append(tag.strip())
    return tags


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
        f"Most SSC CGL aspirants fall for this '{topic}' trap - let's see who gets it right!\n\n"
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
        render_html_to_image(driver, slide_html, out_path, width=1080, height=1350)
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
    render_html_to_image(driver, slide4_html, out_path4, width=1080, height=1350)
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

    tag_parts = [p.strip() for p in quiz["exam_tag"].split("•")]
    exam_main = tag_parts[0] if tag_parts else "SSC CGL • PYQ"
    subject_name = tag_parts[1] if len(tag_parts) > 1 else "GENERAL AWARENESS"
    if exam_main.upper() == "SSC CGL PYQ":
        exam_main = "SSC CGL • PYQ"

    reel_html = template.render(
        slide_type="viral_reel",
        badge_text=quiz["exam_tag"],
        exam_main=exam_main,
        subject_name=subject_name,
        difficulty_level=get_quiz_difficulty(quiz),
        hook_text=quiz.get("curiosity_tag", "90% Aspirants Get This Wrong!"),
        question_html=format_question_html(
            quiz["question"], quiz.get("highlight_phrase"), "highlight-yellow"
        ),
        question_hi=quiz.get("question_hi", ""),
        options=paper_options,
        brand_handle=handle,
    )
    # Render native full 9:16 (1080x1920) Exam-Paper Reel frame
    render_html_to_image(
        driver, reel_html, preview_path, width=1080, height=1920, quality=96
    )

    with tempfile.TemporaryDirectory(prefix="ig_bgm_") as tmpdir:
        bgm_dir = ROOT_DIR / "bgm"
        mp3s = sorted(bgm_dir.glob("*.mp3")) if bgm_dir.exists() else []
        if mp3s:
            audio_input = random.choice(mp3s)
            print(f"Using royalty-free BGM track: {audio_input.name}")
            audio_filter = "volume=0.35,afade=t=in:st=0:d=0.5,afade=t=out:st=6.2:d=0.8"
        else:
            audio_input = Path(tmpdir) / "ambient_pad.wav"
            generate_ambient_pad_wav(audio_input, duration_sec=7.0, sr=48000)
            audio_filter = "anull"

        cmd = [
            "ffmpeg",
            "-y",
            "-loop", "1",
            "-framerate", "30",
            "-i", str(preview_path),
            "-i", str(audio_input),
            "-t", "7",
            "-vf", "format=yuv420p,fps=30",
            "-af", audio_filter,
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
        "yt_title": build_youtube_short_title(quiz),
        "yt_description": build_youtube_short_description(quiz),
        "yt_tags": build_youtube_short_tags(quiz),
    }


def render_next(mode: str) -> None:
    chosen_mode = resolve_mode(mode)
    template = Template(TEMPLATE_PATH.read_text(encoding="utf-8"))

    if chosen_mode == "reel":
        source_file = "reel_pyqs.json"
        target_quiz = None
        if REEL_PYQS_PATH.exists():
            reel_pyqs = json.loads(REEL_PYQS_PATH.read_text(encoding="utf-8"))
            target_quiz = pick_next_reel_by_difficulty(reel_pyqs)

        if not target_quiz:
            source_file = "pyqs.json"
            pyqs = json.loads(PYQS_PATH.read_text(encoding="utf-8"))
            unposted = [q for q in pyqs if not q.get("posted", False)]
            if not unposted:
                print("All PYQs posted! Add more questions to reel_pyqs.json or pyqs.json.")
                sys.exit(0)
            target_quiz = unposted[0]

        driver = create_driver(width=1080, height=2000)
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
                driver = create_driver(width=1080, height=2000)
                try:
                    pending = render_viral_open_loop_reel(driver, template, unposted[0], "pyqs.json")
                finally:
                    driver.quit()
            else:
                print("All PYQs posted! Add more questions to pyqs.json.")
                sys.exit(0)
        else:
            driver = create_driver(width=1080, height=1500)
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


def upload_youtube_short(
    video_path: Path, title: str, description: str, tags: list[str] | None = None
) -> str | None:
    client_id = os.environ.get("YT_CLIENT_ID", "").strip()
    client_secret = os.environ.get("YT_CLIENT_SECRET", "").strip()
    refresh_token = os.environ.get("YT_REFRESH_TOKEN", "").strip()
    if not (client_id and client_secret and refresh_token):
        print("Skipping YouTube Shorts upload (missing YT_CLIENT_ID, YT_CLIENT_SECRET, or YT_REFRESH_TOKEN).")
        return None

    token_resp = requests.post(
        "https://oauth2.googleapis.com/token",
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
        timeout=30,
    )
    if token_resp.status_code >= 400:
        raise RuntimeError(
            f"YouTube OAuth token refresh failed ({token_resp.status_code}): {token_resp.text}"
        )
    access_token = token_resp.json()["access_token"]

    video_bytes = video_path.read_bytes()
    init_resp = requests.post(
        "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json; charset=UTF-8",
            "X-Upload-Content-Type": "video/mp4",
            "X-Upload-Content-Length": str(len(video_bytes)),
        },
        json={
            "snippet": {
                "title": title[:100],
                "description": description,
                "tags": tags or ["SSC CGL", "SSC CGL PYQ", "Static GK", "SSC CHSL", "SSC Exam", "Shorts"],
                "categoryId": "27",
                "defaultLanguage": "en-IN",
            },
            "status": {
                "privacyStatus": "public",
                "selfDeclaredMadeForKids": False,
            },
        },
        timeout=30,
    )
    if init_resp.status_code >= 400:
        raise RuntimeError(
            f"YouTube resumable upload init failed ({init_resp.status_code}): {init_resp.text}"
        )

    upload_url = init_resp.headers.get("Location")
    if not upload_url:
        raise RuntimeError("YouTube resumable upload init did not return a Location header.")

    put_resp = requests.put(
        upload_url,
        headers={"Content-Type": "video/mp4"},
        data=video_bytes,
        timeout=180,
    )
    if put_resp.status_code >= 400:
        raise RuntimeError(
            f"YouTube video upload failed ({put_resp.status_code}): {put_resp.text}"
        )
    return put_resp.json()["id"]


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
    yt_video_id = None

    if pending.get("post_type") == "reel":
        local_video = ROOT_DIR / pending["video_rel"]
        container_id = None

        if not token.startswith("IG") and local_video.exists():
            try:
                container_id = upload_reel_resumable(
                    ig_user_id, local_video, pending["caption"], token
                )
            except Exception as exc:
                print(f"Resumable upload fallback triggered: {exc}")

        if not container_id:
            video_url = f"{raw_base}/{pending['video_rel']}"
            print(f"Publishing 7s 9:16 Viral Quiz Reel via URL: {video_url}")
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
        try:
            yt_video_id = upload_youtube_short(
                local_video,
                pending.get("yt_title") or "SSC CGL Daily PYQ #shorts",
                pending.get("yt_description", pending["caption"]),
                pending.get("yt_tags"),
            )
            if yt_video_id:
                print(f"Published YouTube Short! https://youtube.com/shorts/{yt_video_id}")
        except Exception as exc:
            print(f"YouTube Shorts upload failed (non-blocking): {exc}")
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
            if yt_video_id:
                q["yt_video_id"] = yt_video_id
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