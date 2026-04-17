from flask import Flask, render_template, request, jsonify, send_file
from flask_cors import CORS
from groq import Groq
import os
import json
from dotenv import load_dotenv
import io
import base64
import requests
from datetime import datetime
import sqlite3

load_dotenv()

app = Flask(__name__,
            template_folder=os.path.join(os.path.dirname(os.path.abspath(__file__)), 'templates'),
            static_folder=os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static'))
CORS(app)

client = Groq(api_key=os.getenv("GROQ_API_KEY"))

# ─── Database Setup ────────────────────────────────────────────────────────────
DB_PATH = "/tmp/listings.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS listings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_name TEXT,
            category TEXT,
            title TEXT,
            description TEXT,
            bullet_points TEXT,
            keywords TEXT,
            search_terms TEXT,
            image_base64 TEXT,
            language TEXT,
            created_at TEXT
        )
    """)
    conn.commit()
    conn.close()

init_db()

# ─── Routes ───────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/generate", methods=["POST"])
def generate():
    data = request.json
    product_name = data.get("product_name", "")
    category     = data.get("category", "")
    features     = data.get("features", "")
    audience     = data.get("audience", "")
    price_range  = data.get("price_range", "")
    language     = data.get("language", "en")

    lang_map = {
        "en":   "Generate all content in English only.",
        "ar":   "Generate all content in Arabic only (formal Gulf/Egyptian Arabic suitable for e-commerce).",
        "both": "Generate content in both English and Arabic. For each field provide English first then Arabic translation below it."
    }
    lang_instruction = lang_map.get(language, lang_map["en"])

    prompt = f"""You are an expert Amazon listing copywriter specializing in SEO optimization.

Product Details:
- Name: {product_name}
- Category: {category}
- Key Features: {features}
- Target Audience: {audience}
- Price Range: {price_range}

{lang_instruction}

Return ONLY a valid JSON object with these exact keys:
{{
  "title": "SEO-optimized title max 200 chars with main keyword",
  "description": "Engaging 250-300 word product description highlighting benefits",
  "bullet_points": [
    "BENEFIT ONE: detailed explanation...",
    "BENEFIT TWO: detailed explanation...",
    "BENEFIT THREE: detailed explanation...",
    "BENEFIT FOUR: detailed explanation...",
    "BENEFIT FIVE: detailed explanation..."
  ],
  "keywords": "15-20 comma-separated high-volume search keywords",
  "search_terms": "Amazon backend search terms string"
}}

Rules:
- Title must include main keyword naturally and be compelling
- Each bullet point must start with 1-2 capitalized benefit words followed by a colon
- Description must be benefit-focused and persuasive
- Keywords must be relevant and high-volume
- Follow Amazon A9 algorithm best practices"""

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": "You are an expert Amazon listing specialist. Always respond with valid JSON only. No markdown, no extra text."},
            {"role": "user", "content": prompt}
        ],
        response_format={"type": "json_object"}
    )

    result = json.loads(response.choices[0].message.content)
    return jsonify(result)


@app.route("/image-search", methods=["POST"])
def image_search():
    data = request.json
    image_b64 = data.get("image_base64", "")
    if not image_b64:
        return jsonify({"error": "No image provided"}), 400

    # Strip data URI prefix if present
    if "," in image_b64:
        image_b64 = image_b64.split(",", 1)[1]

    imgbb_key = os.getenv("IMGBB_API_KEY")
    if not imgbb_key:
        return jsonify({"error": "IMGBB_API_KEY not configured"}), 500

    resp = requests.post(
        "https://api.imgbb.com/1/upload",
        data={"key": imgbb_key, "image": image_b64},
        timeout=30
    )
    resp.raise_for_status()
    result = resp.json()
    image_url = result["data"]["url"]

    from urllib.parse import quote
    enc = quote(image_url, safe="")

    return jsonify({
        "image_url": image_url,
        "links": {
            "google_lens":  f"https://lens.google.com/uploadbyurl?url={enc}",
            "alibaba":      f"https://www.alibaba.com/trade/search?imageAddress={enc}&SearchText=",
            "aliexpress":   f"https://www.aliexpress.com/wholesale?imgUrl={enc}",
            "amazon":       f"https://www.amazon.com/s?k={enc}&i=aps",
        }
    })


@app.route("/generate-image", methods=["POST"])
def generate_image():
    data         = request.json
    product_name = data.get("product_name", "")
    category     = data.get("category", "")
    features     = data.get("features", "")

    image_prompt = (
        f"Professional Amazon product photography of {product_name}, "
        f"category: {category}, key features: {features}. "
        "Pure white background, studio lighting, sharp focus, "
        "high resolution commercial product photo, centered composition, "
        "no text or watermarks, e-commerce ready image."
    )

    from urllib.parse import quote
    encoded_prompt = quote(image_prompt)
    image_url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1024&height=1024&nologo=true&seed={hash(product_name) % 99999}"

    return jsonify({"image_url": image_url})


@app.route("/save", methods=["POST"])
def save_listing():
    data = request.json
    content      = data.get("content", {})
    product_name = data.get("product_name", "")
    category     = data.get("category", "")
    language     = data.get("language", "en")
    image_b64    = data.get("image_base64", "")
    timestamp    = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        INSERT INTO listings
          (product_name, category, title, description, bullet_points, keywords, search_terms, image_base64, language, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        product_name,
        category,
        content.get("title", ""),
        content.get("description", ""),
        json.dumps(content.get("bullet_points", []), ensure_ascii=False),
        content.get("keywords", ""),
        content.get("search_terms", ""),
        image_b64,
        language,
        timestamp
    ))
    conn.commit()
    listing_id = c.lastrowid
    conn.close()
    return jsonify({"success": True, "id": listing_id})


@app.route("/history", methods=["GET"])
def get_history():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, product_name, category, title, language, created_at FROM listings ORDER BY id DESC LIMIT 50")
    rows = c.fetchall()
    conn.close()
    return jsonify([
        {"id": r[0], "product_name": r[1], "category": r[2], "title": r[3], "language": r[4], "created_at": r[5]}
        for r in rows
    ])


@app.route("/history/<int:listing_id>", methods=["GET"])
def get_listing(listing_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM listings WHERE id = ?", (listing_id,))
    row = c.fetchone()
    conn.close()
    if not row:
        return jsonify({"error": "Not found"}), 404
    return jsonify({
        "id": row[0], "product_name": row[1], "category": row[2],
        "title": row[3], "description": row[4],
        "bullet_points": json.loads(row[5]),
        "keywords": row[6], "search_terms": row[7],
        "image_base64": row[8], "language": row[9], "created_at": row[10]
    })


@app.route("/history/<int:listing_id>", methods=["DELETE"])
def delete_listing(listing_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM listings WHERE id = ?", (listing_id,))
    conn.commit()
    conn.close()
    return jsonify({"success": True})


@app.route("/export", methods=["POST"])
def export():
    data         = request.json
    content      = data.get("content", {})
    product_name = data.get("product_name", "product").replace(" ", "_")
    fmt          = data.get("format", "txt")
    timestamp    = datetime.now().strftime("%Y%m%d_%H%M%S")

    if fmt == "txt":
        bullets = "\n".join([f"  • {bp}" for bp in content.get("bullet_points", [])])
        text = f"""AMAZON PRODUCT LISTING
Generated: {timestamp}
{'='*60}

📌 TITLE:
{content.get('title', '')}

🔸 BULLET POINTS:
{bullets}

📝 DESCRIPTION:
{content.get('description', '')}

🔍 KEYWORDS:
{content.get('keywords', '')}

🔎 SEARCH TERMS:
{content.get('search_terms', '')}
{'='*60}
Generated by Amazon AI Listing Generator
"""
        buf = io.BytesIO(text.encode("utf-8"))
        return send_file(buf, as_attachment=True,
                         download_name=f"listing_{product_name}_{timestamp}.txt",
                         mimetype="text/plain")

    elif fmt == "json":
        obj = {"generated_at": timestamp, "product_name": product_name, **content}
        buf = io.BytesIO(json.dumps(obj, ensure_ascii=False, indent=2).encode("utf-8"))
        return send_file(buf, as_attachment=True,
                         download_name=f"listing_{product_name}_{timestamp}.json",
                         mimetype="application/json")

    elif fmt == "csv":
        bullets = " | ".join(content.get("bullet_points", []))
        csv = f"Title,Description,Bullet Points,Keywords,Search Terms\n"
        csv += f'"{content.get("title","")}","{content.get("description","")}","{bullets}","{content.get("keywords","")}","{content.get("search_terms","")}"'
        buf = io.BytesIO(csv.encode("utf-8"))
        return send_file(buf, as_attachment=True,
                         download_name=f"listing_{product_name}_{timestamp}.csv",
                         mimetype="text/csv")

    return jsonify({"error": "Unknown format"}), 400


if __name__ == "__main__":
    print("🚀 Amazon AI Listing Generator running on http://localhost:5000")
    app.run(debug=True, port=5000)
