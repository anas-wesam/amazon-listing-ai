# 🛒 Amazon AI Listing Generator

Generate professional Amazon product listings with AI — titles, descriptions, bullet points, keywords, and product images using GPT-4o and DALL·E 3.

## Features
- ✅ AI-generated Title (SEO optimized, 200 char limit)
- ✅ 5 Benefit-focused Bullet Points
- ✅ Full Product Description (250-300 words)
- ✅ Keywords + Backend Search Terms
- ✅ AI Product Image (DALL·E 3)
- ✅ Regenerate each field individually
- ✅ Export as TXT, JSON, or CSV (unlimited downloads)
- ✅ Save & view listing history (SQLite)
- ✅ English, Arabic, or both languages
- ✅ Dark mode UI

## Setup

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Add your OpenAI API key
cp .env.example .env
# Edit .env and add your key

# 3. Run the app
python app.py

# 4. Open in browser
# http://localhost:5000
```

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | /generate | Generate listing text |
| POST | /generate-image | Generate product image |
| POST | /save | Save listing to history |
| GET | /history | Get all saved listings |
| GET | /history/<id> | Get one listing |
| DELETE | /history/<id> | Delete listing |
| POST | /export | Download as TXT/JSON/CSV |

## Requirements
- Python 3.9+
- OpenAI API key (GPT-4o + DALL·E 3 access)
