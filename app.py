"""Minimal local web UI for meta-ads-collector, for manual testing / lead research."""
import csv
import io
import re
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

from flask import Flask, Response, render_template_string, request

from meta_ads_collector import MetaAdsCollector

app = Flask(__name__)

PAGE = """
<!doctype html>
<html>
<head>
<title>Meta Ads Collector</title>
<style>
  body { font-family: system-ui, sans-serif; max-width: 1300px; margin: 2rem auto; padding: 0 1rem; color: #1a1a1a; }
  h1 { font-size: 1.4rem; }
  form { display: flex; gap: 0.5rem; flex-wrap: wrap; margin-bottom: 1.5rem; align-items: center; }
  input[type=text] { padding: 0.5rem; font-size: 1rem; flex: 1; min-width: 200px; }
  input[type=number] { padding: 0.5rem; font-size: 1rem; width: 90px; }
  select { padding: 0.5rem; font-size: 1rem; }
  button, .btn { padding: 0.5rem 1rem; font-size: 1rem; cursor: pointer; text-decoration: none; color: inherit; border: 1px solid #ccc; border-radius: 4px; background: #f5f5f5; }
  table { width: 100%; border-collapse: collapse; font-size: 0.9rem; }
  th, td { text-align: left; padding: 0.5rem; border-bottom: 1px solid #ddd; vertical-align: top; }
  th { background: #f5f5f5; }
  .error { color: #b00020; }
  .meta { color: #666; font-size: 0.9rem; margin-bottom: 1rem; display: flex; justify-content: space-between; align-items: center; }
  a { color: #1a5cff; }
</style>
</head>
<body>
  <h1>Meta Ads Collector — local test UI</h1>
  <form method="get">
    <input type="text" name="q" placeholder="Search keyword (e.g. solar panels)" value="{{ query }}">
    <select name="country">
      {% for c in countries %}
      <option value="{{ c }}" {% if c == country %}selected{% endif %}>{{ c }}</option>
      {% endfor %}
    </select>
    <input type="number" name="n" min="1" max="100" value="{{ max_results }}">
    <button type="submit">Search</button>
  </form>

  {% if error %}
    <p class="error">{{ error }}</p>
  {% endif %}

  {% if rows is not none %}
    <p class="meta">
      <span>{{ rows|length }} ads found for "{{ query }}" in {{ country }}</span>
      {% if rows %}<a class="btn" href="/export.csv?{{ query_string }}">Download CSV</a>{% endif %}
    </p>
    <table>
      <tr>
        <th>Page</th>
        <th>Category</th>
        <th>Headline</th>
        <th>Ad text</th>
        <th>CTA</th>
        <th>WhatsApp</th>
        <th>Domain</th>
        <th>Platforms</th>
        <th>Started</th>
        <th>Days running</th>
        <th>Variations</th>
        <th>Carousel items</th>
        <th>Website / landing page</th>
        <th>Facebook page</th>
        <th>Page likes</th>
      </tr>
      {% for r in rows %}
      <tr>
        <td>{{ r.page_name }}</td>
        <td>{{ r.category }}</td>
        <td>{{ r.title }}</td>
        <td>{{ r.body | truncate(140) }}</td>
        <td>{{ r.cta_text }}</td>
        <td>{% if r.whatsapp_number %}{{ r.whatsapp_number }}{% endif %}</td>
        <td>{{ r.domain }}</td>
        <td>{{ r.platforms }}</td>
        <td>{{ r.start_date }}</td>
        <td>{{ r.days_running }}</td>
        <td>{{ r.ad_variations }}</td>
        <td>{{ r.carousel_items }}</td>
        <td>{% if r.link_url %}<a href="{{ r.link_url }}" target="_blank">{{ r.link_url | truncate(40) }}</a>{% endif %}</td>
        <td>{% if r.page_url %}<a href="{{ r.page_url }}" target="_blank">page</a>{% endif %}</td>
        <td>{{ r.page_likes }}</td>
      </tr>
      {% endfor %}
    </table>
  {% endif %}
</body>
</html>
"""

COUNTRIES = ["US", "GB", "CA", "AU", "IN", "DE", "FR", "AE"]

CSV_COLUMNS = [
    "page_name", "category", "title", "body", "cta_text", "whatsapp_number", "domain",
    "platforms", "start_date", "days_running", "ad_variations", "carousel_items",
    "link_url", "page_url", "page_likes", "ad_id",
]


def extract_whatsapp_number(link_url):
    """Pull the phone number out of a WhatsApp CTA link when Meta includes it (not always present)."""
    if not link_url or "whatsapp.com" not in link_url:
        return None
    qs = parse_qs(urlparse(link_url).query)
    phone = qs.get("phone", [None])[0]
    if phone:
        return re.sub(r"[^\d+]", "", phone)
    return None


def ad_to_row(ad):
    creative = ad.creatives[0] if ad.creatives else None
    page = ad.page
    snapshot = (ad.raw_data or {}).get("snapshot", {})
    categories = snapshot.get("page_categories") or []

    days_running = ""
    if ad.delivery_start_time:
        end = ad.delivery_stop_time or datetime.now(timezone.utc).replace(tzinfo=ad.delivery_start_time.tzinfo)
        try:
            days_running = (end - ad.delivery_start_time).days
        except TypeError:
            days_running = ""

    return {
        "page_name": page.name if page else "",
        "category": ", ".join(categories),
        "title": creative.title if creative else "",
        "body": creative.body if creative else "",
        "cta_text": creative.cta_text if creative else "",
        "whatsapp_number": extract_whatsapp_number(creative.link_url if creative else None),
        "domain": creative.caption if creative else "",
        "platforms": ", ".join(ad.publisher_platforms or []),
        "start_date": ad.delivery_start_time.date() if ad.delivery_start_time else "",
        "days_running": days_running,
        "ad_variations": ad.collation_count or "",
        "carousel_items": len(ad.creatives) if ad.creatives else "",
        "link_url": creative.link_url if creative else "",
        "page_url": page.page_url if page else "",
        "page_likes": page.likes if page else "",
        "ad_id": ad.id,
    }


def run_search(query, country, max_results):
    with MetaAdsCollector() as collector:
        ads = list(collector.search(query=query, country=country, max_results=max_results))
    return [ad_to_row(ad) for ad in ads]


@app.route("/")
def index():
    query = request.args.get("q", "").strip()
    country = request.args.get("country", "US")
    max_results = int(request.args.get("n", 10))

    rows = None
    error = None

    if query:
        try:
            rows = run_search(query, country, max_results)
        except Exception as exc:
            error = f"Search failed: {exc}"

    return render_template_string(
        PAGE,
        query=query,
        country=country,
        max_results=max_results,
        countries=COUNTRIES,
        rows=rows,
        error=error,
        query_string=f"q={query}&country={country}&n={max_results}",
    )


@app.route("/export.csv")
def export_csv():
    query = request.args.get("q", "").strip()
    country = request.args.get("country", "US")
    max_results = int(request.args.get("n", 10))

    rows = run_search(query, country, max_results) if query else []

    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=CSV_COLUMNS)
    writer.writeheader()
    for row in rows:
        writer.writerow(row)

    filename = f"meta_ads_{query.replace(' ', '_')}_{country}.csv"
    return Response(
        buffer.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
