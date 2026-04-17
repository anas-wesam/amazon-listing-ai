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


def ddg_image_search(query, max_results=6):
    """Search DuckDuckGo images and return list of image result dicts."""
    import re
    headers = {"User-Agent": "Mozilla/5.0"}
    # Step 1: get vqd token
    r = requests.get("https://duckduckgo.com/", params={"q": query, "iax": "images", "ia": "images"}, headers=headers, timeout=10)
    vqd = re.search(r'vqd=(["\'])([^"\']+)\1', r.text)
    if not vqd:
        return []
    vqd_token = vqd.group(2)
    # Step 2: fetch image results
    r2 = requests.get("https://duckduckgo.com/i.js",
                       params={"q": query, "o": "json", "vqd": vqd_token, "f": ",,,,,", "p": "1"},
                       headers=headers, timeout=10)
    results = r2.json().get("results", [])
    return [{"image": x["image"], "title": x.get("title",""), "url": x.get("url","")} for x in results[:max_results]]


@app.route("/image-search", methods=["POST"])
def image_search():
    data = request.json
    image_b64 = data.get("image_base64", "")
    if not image_b64:
        return jsonify({"error": "No image provided"}), 400

    # Strip data URI prefix
    raw_b64 = image_b64.split(",", 1)[1] if "," in image_b64 else image_b64

    # Step 1: identify product using Groq vision
    vision_response = client.chat.completions.create(
        model="meta-llama/llama-4-scout-17b-16e-instruct",
        messages=[{
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": image_b64}},
                {"type": "text", "text": "What product is in this image? Reply with ONLY a short product search query (3-6 words max), no explanation."}
            ]
        }],
        max_tokens=30
    )
    product_query = vision_response.choices[0].message.content.strip().strip('"').strip("'")

    # Step 2: search each platform
    from urllib.parse import quote
    results = {
        "product_query": product_query,
        "amazon":     ddg_image_search(f"{product_query} site:amazon.com"),
        "alibaba":    ddg_image_search(f"{product_query} site:alibaba.com"),
        "aliexpress": ddg_image_search(f"{product_query} site:aliexpress.com"),
        "google":     ddg_image_search(f"{product_query} product"),
    }
    return jsonify(results)


@app.route("/proxy-image")
def proxy_image():
    url = request.args.get("url", "")
    if not url:
        return "No URL", 400
    try:
        r = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        ext = url.split("?")[0].split(".")[-1].lower()
        mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
                "webp": "image/webp", "gif": "image/gif"}.get(ext, "image/jpeg")
        from flask import Response
        return Response(r.content, content_type=mime,
                        headers={"Content-Disposition": f"attachment; filename=product.{ext}"})
    except Exception as e:
        return str(e), 500


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


# ─── Amazon SP-API OAuth ──────────────────────────────────────────────────────
AMAZON_CLIENT_ID     = os.getenv("AMAZON_CLIENT_ID", "")
AMAZON_CLIENT_SECRET = os.getenv("AMAZON_CLIENT_SECRET", "")
AMAZON_MARKETPLACE   = os.getenv("AMAZON_MARKETPLACE_ID", "ARBP9OOSHTCHU")
REDIRECT_URI         = "https://amazon-listing-ai.vercel.app/amazon/callback"

def get_db_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_amazon_table():
    conn = get_db_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS amazon_tokens (
            id INTEGER PRIMARY KEY,
            access_token TEXT,
            refresh_token TEXT,
            expires_at INTEGER
        )
    """)
    conn.commit()
    conn.close()

init_amazon_table()

def save_tokens(access_token, refresh_token, expires_in=3600):
    import time
    conn = get_db_conn()
    conn.execute("DELETE FROM amazon_tokens")
    conn.execute("INSERT INTO amazon_tokens (access_token, refresh_token, expires_at) VALUES (?,?,?)",
                 (access_token, refresh_token, int(time.time()) + expires_in))
    conn.commit()
    conn.close()

def get_valid_access_token():
    import time
    conn = get_db_conn()
    row = conn.execute("SELECT * FROM amazon_tokens ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()
    if not row:
        return None
    if int(time.time()) < row["expires_at"] - 60:
        return row["access_token"]
    # Refresh
    resp = requests.post("https://api.amazon.com/auth/o2/token", data={
        "grant_type":    "refresh_token",
        "refresh_token": row["refresh_token"],
        "client_id":     AMAZON_CLIENT_ID,
        "client_secret": AMAZON_CLIENT_SECRET,
    })
    if resp.status_code == 200:
        data = resp.json()
        save_tokens(data["access_token"], data.get("refresh_token", row["refresh_token"]), data.get("expires_in", 3600))
        return data["access_token"]
    return None

@app.route("/amazon/login")
def amazon_login():
    from urllib.parse import urlencode
    params = urlencode({
        "application_id": AMAZON_CLIENT_ID,
        "state":          "listing_ai",
        "version":        "beta",
    })
    return jsonify({"url": f"https://sellercentral.amazon.eg/apps/authorize/consent?{params}"})

@app.route("/amazon/callback")
def amazon_callback():
    code         = request.args.get("code", "")
    selling_partner_id = request.args.get("selling_partner_id", "")
    if not code:
        return "Error: no code", 400
    resp = requests.post("https://api.amazon.com/auth/o2/token", data={
        "grant_type":    "authorization_code",
        "code":          code,
        "client_id":     AMAZON_CLIENT_ID,
        "client_secret": AMAZON_CLIENT_SECRET,
        "redirect_uri":  REDIRECT_URI,
    })
    if resp.status_code != 200:
        return f"Token error: {resp.text}", 400
    data = resp.json()
    save_tokens(data["access_token"], data["refresh_token"], data.get("expires_in", 3600))
    # Save seller ID
    conn = get_db_conn()
    conn.execute("CREATE TABLE IF NOT EXISTS amazon_seller (seller_id TEXT)")
    conn.execute("DELETE FROM amazon_seller")
    conn.execute("INSERT INTO amazon_seller (seller_id) VALUES (?)", (selling_partner_id,))
    conn.commit()
    conn.close()
    return """<html><body style='background:#0f1117;color:#68d391;font-family:sans-serif;text-align:center;padding:80px'>
        <h1>✅ تم الربط بنجاح!</h1><p>يمكنك إغلاق هذه النفذة والعودة للتطبيق</p>
        <script>window.close()</script></body></html>"""

@app.route("/amazon/status")
def amazon_status():
    token = get_valid_access_token()
    conn = get_db_conn()
    try:
        row = conn.execute("SELECT seller_id FROM amazon_seller LIMIT 1").fetchone()
        seller_id = row["seller_id"] if row else None
    except:
        seller_id = None
    conn.close()
    return jsonify({"connected": token is not None, "seller_id": seller_id})

@app.route("/amazon/publish", methods=["POST"])
def amazon_publish():
    token = get_valid_access_token()
    if not token:
        return jsonify({"error": "Not connected to Amazon. Please login first."}), 401

    data         = request.json
    content      = data.get("content", {})
    product_name = data.get("product_name", "")
    sku          = data.get("sku", f"SKU-{datetime.now().strftime('%Y%m%d%H%M%S')}")

    conn = get_db_conn()
    try:
        row = conn.execute("SELECT seller_id FROM amazon_seller LIMIT 1").fetchone()
        seller_id = row["seller_id"]
    except:
        return jsonify({"error": "Seller ID not found"}), 400
    finally:
        conn.close()

    bullets = content.get("bullet_points", [])
    payload = {
        "productType": "PRODUCT",
        "requirements": "LISTING",
        "attributes": {
            "item_name":         [{"value": content.get("title", product_name), "marketplace_id": AMAZON_MARKETPLACE, "language_tag": "en_EG"}],
            "product_description":[{"value": content.get("description", ""), "marketplace_id": AMAZON_MARKETPLACE, "language_tag": "en_EG"}],
            "bullet_point":      [{"value": b, "marketplace_id": AMAZON_MARKETPLACE, "language_tag": "en_EG"} for b in bullets[:5]],
            "generic_keyword":   [{"value": content.get("search_terms", ""), "marketplace_id": AMAZON_MARKETPLACE}],
        }
    }

    headers = {
        "Authorization": f"Bearer {token}",
        "x-amz-access-token": token,
        "Content-Type": "application/json",
    }
    url = f"https://sellingpartnerapi-eu.amazon.com/listings/2021-08-01/items/{seller_id}/{sku}?marketplaceIds={AMAZON_MARKETPLACE}"
    resp = requests.put(url, json=payload, headers=headers, timeout=30)

    if resp.status_code in (200, 201):
        return jsonify({"success": True, "sku": sku, "status": resp.json().get("status", "ACCEPTED")})
    return jsonify({"error": resp.text, "status_code": resp.status_code}), 400


if __name__ == "__main__":
    print("🚀 Amazon AI Listing Generator running on http://localhost:5000")
    app.run(debug=True, port=5000)
