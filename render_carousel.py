#!/usr/bin/env python3
"""
SSC CGL 2-Slide Instagram Carousel Renderer (1080x1350 JPEG)
-------------------------------------------------------------
Renders Slide 1 (Question + 4 Options) and Slide 2 (Answer + NCERT Revision Notes)
using `slide_template.html` and headless Chromium via Selenium, then converts them
to Instagram-ready 1080x1350 JPEGs via Pillow.


Requirements:
  pip install jinja2 pillow selenium


Usage:
  python3 render_carousel.py                     # Renders the built-in sample PYQ
  python3 render_carousel.py --json quiz.json    # Renders from a custom JSON file
"""


import argparse
import base64
import html
import json
import os
import tempfile
from pathlib import Path


from jinja2 import Template
from PIL import Image
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By


SCRIPT_DIR = Path(__file__).resolve().parent
TEMPLATE_PATH = SCRIPT_DIR / "slide_template.html"


SAMPLE_QUIZ = {
    "id": "ssc_cgl_2024_polity_01",
    "exam_tag": "SSC CGL 2024 • POLITY",
    "question": "Which of the following Articles of the Indian Constitution contains Fundamental Duties?",
    "highlight_phrase": "Fundamental Duties",
    "options": [
        {"letter": "A", "text": "Article 45A"},
        {"letter": "B", "text": "Article 32A"},
        {"letter": "C", "text": "Article 51A"},
        {"letter": "D", "text": "Article 62B"},
    ],
    "correct_answer": "(C) Article 51A",
    "revision_notes": [
        {"label": "Part IV-A", "detail": "Article 51A is the only Article in Part IV-A."},
        {"label": "42nd Amendment (1976)", "detail": "Added 10 duties via Swaran Singh Committee (USSR)."},
        {"label": "86th Amendment (2002)", "detail": "Added 11th duty — Art. 51A(k) (education, ages 6–14)."},
        {"label": "Exam Trap", "detail": "Art. 51 is DPSP (International Peace), NOT Fundamental Duties!"},
    ],
    "slide1_cta": "Comment Your Answer  •  Swipe →",
    "slide2_cta": "Save for Revision  •  Follow for Daily PYQs",
    "brand_handle": "@YOUR_CHANNEL_HANDLE",
}




def format_question_html(question: str, highlight_phrase: str | None) -> str:
    """Safely escape question text and wrap the highlight phrase in an orange gradient span."""
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
    """Create a headless Chromium WebDriver with extra vertical room for full element capture."""
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
    """Render an HTML string to an exact 1080x1350 JPEG by screenshotting .canvas."""
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




def generate_carousel(
    driver: webdriver.Chrome, quiz_data: dict, output_dir: Path
) -> tuple[Path, Path]:
    """Generate both Slide 1 and Slide 2 JPEGs for a given quiz dictionary."""
    template = Template(TEMPLATE_PATH.read_text(encoding="utf-8"))
    qid = quiz_data.get("id", "quiz_post")


    slide1_html = template.render(
        slide_type="question",
        slide_number="1",
        badge_text=quiz_data["exam_tag"],
        question_html=format_question_html(
            quiz_data["question"], quiz_data.get("highlight_phrase")
        ),
        options=quiz_data["options"],
        cta_text=quiz_data.get("slide1_cta", "Comment Your Answer  •  Swipe →"),
        brand_handle=quiz_data.get("brand_handle", ""),
    )


    slide2_html = template.render(
        slide_type="answer",
        slide_number="2",
        badge_text="ANSWER & NCERT FLASHCARD",
        correct_answer=quiz_data["correct_answer"],
        revision_notes=quiz_data["revision_notes"],
        cta_text=quiz_data.get(
            "slide2_cta", "Save for Revision  •  Follow for Daily PYQs"
        ),
        brand_handle=quiz_data.get("brand_handle", ""),
    )


    slide1_path = output_dir / f"{qid}_slide1.jpg"
    slide2_path = output_dir / f"{qid}_slide2.jpg"


    render_html_to_jpeg(driver, slide1_html, slide1_path)
    render_html_to_jpeg(driver, slide2_html, slide2_path)
    return slide1_path, slide2_path




def main() -> None:
    parser = argparse.ArgumentParser(
        description="Render 1080x1350 SSC CGL 2-slide Instagram carousels."
    )
    parser.add_argument(
        "--json",
        type=Path,
        default=None,
        help="Path to a JSON file containing one quiz object (or list of objects).",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=SCRIPT_DIR / "rendered_slides",
        help="Output directory for rendered JPEGs.",
    )
    args = parser.parse_args()


    if args.json:
        payload = json.loads(args.json.read_text(encoding="utf-8"))
        items = payload if isinstance(payload, list) else [payload]
    else:
        items = [SAMPLE_QUIZ]


    driver = create_driver()
    try:
        for item in items:
            s1, s2 = generate_carousel(driver, item, args.out)
            print(f"Rendered: {s1} & {s2}")
    finally:
        driver.quit()




if __name__ == "__main__":
    main()