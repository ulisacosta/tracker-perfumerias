"""
Genera index.html con un gráfico de evolución de precio por cada producto,
a partir de price_history.json. Se usa después de price_tracker.py.
"""
import json
import os
from datetime import datetime

HISTORY_FILE = "price_history.json"
OUTPUT_FILE = "index.html"


def load_history():
    if not os.path.exists(HISTORY_FILE):
        return {}
    with open(HISTORY_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def fmt_price(value):
    return f"${value:,.0f}".replace(",", ".")


def fmt_date(iso):
    try:
        return datetime.fromisoformat(iso).strftime("%d/%m %H:%M")
    except Exception:
        return iso


def build_card(url, entry, idx):
    name = entry.get("name", url)
    history = entry.get("history", [])
    if not history:
        return ""

    prices = [h["price"] for h in history]
    labels = [fmt_date(h["date"]) for h in history]
    current = prices[-1]
    lowest = min(prices)
    highest = max(prices)

    change_html = ""
    if len(prices) >= 2 and prices[-1] != prices[-2]:
        diff = prices[-1] - prices[-2]
        pct = (diff / prices[-2]) * 100
        cls = "down" if diff < 0 else "up"
        arrow = "↓" if diff < 0 else "↑"
        change_html = f'<span class="change {cls}">{arrow} {pct:+.1f}%</span>'

    return f"""
    <div class="card">
      <div class="card-header">
        <a href="{url}" target="_blank" class="name">{name}</a>
        {change_html}
      </div>
      <div class="stats">
        <div><span class="label">Actual</span><span class="value">{fmt_price(current)}</span></div>
        <div><span class="label">Mínimo</span><span class="value low">{fmt_price(lowest)}</span></div>
        <div><span class="label">Máximo</span><span class="value high">{fmt_price(highest)}</span></div>
      </div>
      <canvas id="chart{idx}" height="90"></canvas>
    </div>
    <script>
      new Chart(document.getElementById('chart{idx}'), {{
        type: 'line',
        data: {{
          labels: {json.dumps(labels)},
          datasets: [{{
            data: {json.dumps(prices)},
            borderColor: '#4fd1c5',
            backgroundColor: 'rgba(79,209,197,0.1)',
            fill: true,
            tension: 0.25,
            pointRadius: 2,
          }}]
        }},
        options: {{
          plugins: {{ legend: {{ display: false }} }},
          scales: {{
            x: {{ ticks: {{ color: '#888', maxTicksLimit: 6 }}, grid: {{ display: false }} }},
            y: {{ ticks: {{ color: '#888' }}, grid: {{ color: '#2a2a2a' }} }}
          }}
        }}
      }});
    </script>
    """


def main():
    history = load_history()
    now = datetime.now().strftime("%d/%m/%Y %H:%M")

    cards = "".join(
        build_card(url, entry, idx) for idx, (url, entry) in enumerate(history.items())
    )

    html = f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Tracker de precios - Perfumerías</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<style>
  body {{ background:#121212; color:#eee; font-family: -apple-system, Arial, sans-serif; margin:0; padding:20px; }}
  h1 {{ font-size:1.4rem; margin-bottom:4px; }}
  .updated {{ color:#888; font-size:0.85rem; margin-bottom:20px; }}
  .grid {{ display:grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap:16px; }}
  .card {{ background:#1c1c1c; border-radius:12px; padding:16px; }}
  .card-header {{ display:flex; justify-content:space-between; align-items:center; margin-bottom:10px; gap:8px; }}
  .name {{ color:#fff; text-decoration:none; font-weight:600; font-size:0.95rem; }}
  .name:hover {{ color:#4fd1c5; }}
  .change {{ font-weight:700; font-size:0.85rem; white-space:nowrap; }}
  .change.down {{ color:#48bb78; }}
  .change.up {{ color:#f56565; }}
  .stats {{ display:flex; gap:16px; margin-bottom:10px; }}
  .stats .label {{ display:block; color:#888; font-size:0.7rem; }}
  .stats .value {{ display:block; font-size:1rem; font-weight:600; }}
  .value.low {{ color:#48bb78; }}
  .value.high {{ color:#f56565; }}
</style>
</head>
<body>
  <h1>📈 Tracker de precios - Perfumerías</h1>
  <div class="updated">Última actualización: {now}</div>
  <div class="grid">
    {cards if cards else "<p>Todavía no hay historial suficiente.</p>"}
  </div>
</body>
</html>
"""

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"{OUTPUT_FILE} generado con {len(history)} producto(s).")


if __name__ == "__main__":
    main()
