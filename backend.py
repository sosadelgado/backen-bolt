from fastapi import FastAPI
from pydantic import BaseModel
import httpx
from bs4 import BeautifulSoup
import time
import re

app = FastAPI()

CACHE = {"timestamp": 0, "data": []}

class EvaluateRequest(BaseModel):
    player_name: str
    kill_line: float
    hs_line: float
    salary: float
    map_count: int = 2

def fetch_hltv_stats(player_name: str):
    """Fetch KPR and HS% for a CS2 player from HLTV."""
    url = f"https://www.hltv.org/search?query={player_name}"
    with httpx.Client(timeout=10.0) as client:
        r = client.get(url)
        soup = BeautifulSoup(r.text, "lxml")

        link = soup.select_one("a.col-custom")
        if not link:
            return None, None

        player_url = "https://www.hltv.org" + link["href"]
        r2 = client.get(player_url)
        soup2 = BeautifulSoup(r2.text, "lxml")

        stats_row = soup2.select_one(".stats-row")
        if not stats_row:
            return None, None

        text = stats_row.get_text(" ", strip=True)
        kpr_match = re.search(r"KPR\s([\d.]+)", text)
        hs_match = re.search(r"HS\s([\d.]+)%", text)

        kpr = float(kpr_match.group(1)) if kpr_match else None
        hs_pct = float(hs_match.group(1))/100 if hs_match else None

        return kpr, hs_pct

def evaluate_prop(player_name, kill_line, hs_line, salary, map_count):
    kpr, hs_pct = fetch_hltv_stats(player_name)
    if not kpr or not hs_pct:
        return {
            "verdict": "No HLTV data found",
            "value_score": None,
            "expected_kills": None,
            "used_kpr": None,
            "used_hs": None,
            "notes": "Could not fetch HLTV stats"
        }

    expected_kills = kpr * (map_count * 24)  # est. 24 rounds per map
    value_score = (hs_line * 0.65 + kill_line * 0.35) - salary

    verdict = "Good value" if salary <= 15 and value_score >= 12.5 else "Overpriced"
    return {
        "verdict": verdict,
        "value_score": round(value_score, 2),
        "expected_kills": round(expected_kills, 2),
        "used_kpr": kpr,
        "used_hs": hs_pct,
        "notes": f"Stats from HLTV for {player_name}"
    }

@app.get("/")
def health():
    return {"status": "Backend is live"}

@app.get("/esports/board")
def get_esports_board():
    now = time.time()
    if now - CACHE["timestamp"] < 1800:
        return {"cached": True, "data": CACHE["data"]}

    url = "https://api.prizepicks.com/projections"
    with httpx.Client(timeout=10.0) as client:
        r = client.get(url)
        if r.status_code != 200:
            return {"error": "Could not fetch PrizePicks board"}

        data = r.json()
        board = []
        for item in data.get("data", []):
            attr = item.get("attributes", {})
            if attr.get("league", "").lower() in ["cs2", "counter-strike", "valorant", "league of legends"]:
                board.append({
                    "player": attr.get("name"),
                    "stat_type": attr.get("stat_type"),
                    "line_score": attr.get("line_score"),
                    "league": attr.get("league"),
                })

        CACHE["timestamp"] = now
        CACHE["data"] = board
        return {"cached": False, "data": board}

@app.post("/evaluate")
def evaluate_endpoint(req: EvaluateRequest):
    return evaluate_prop(req.player_name, req.kill_line, req.hs_line, req.salary, req.map_count)
