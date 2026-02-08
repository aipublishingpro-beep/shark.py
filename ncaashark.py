"""
ncaashark.py — BigSnapshot NCAA Cushion Scanner
Only shows games with 7+ point lead. Court + plays in expander.
Run: streamlit run ncaashark.py
"""

import streamlit as st
st.set_page_config(page_title="BigSnapshot NCAA SHARK", page_icon="🦈", layout="wide")
import streamlit.components.v1 as components

import requests, time, hashlib
from datetime import datetime, timezone
from streamlit_autorefresh import st_autorefresh

# ══════════════════════════════════════════════════════════════════════
# OWNER MODE
# ══════════════════════════════════════════════════════════════════════

OWNER_KEY = "SHARK2026"

def check_auth():
    params = st.query_params
    url_key = params.get("key", "")
    if url_key == OWNER_KEY:
        st.session_state["authenticated"] = True
        return True
    if st.session_state.get("authenticated"):
        return True
    st.markdown("### BigSnapshot NCAA SHARK — Owner Access")
    pwd = st.text_input("Enter access key:", type="password", key="auth_input")
    if pwd:
        if pwd == OWNER_KEY:
            st.session_state["authenticated"] = True
            st.rerun()
        else:
            st.error("Wrong key.")
    st.stop()

check_auth()

st_autorefresh(interval=30_000, limit=10000, key="ncaa_shark_refresh")

# ══════════════════════════════════════════════════════════════════════
# CONFIG
# ══════════════════════════════════════════════════════════════════════

VERSION = "1.0"
GAME_MINUTES = 40
HALF_MINUTES = 20
LEAGUE_AVG_TOTAL = 135
THRESHOLDS = [120.5, 125.5, 130.5, 135.5, 140.5, 145.5, 150.5, 155.5, 160.5]
SHARK_MINUTES = 5.0
MIN_LEAD = 7

if "session_id" not in st.session_state:
    st.session_state["session_id"] = hashlib.md5(str(time.time()).encode()).hexdigest()[:12]


# ══════════════════════════════════════════════════════════════════════
# TIME / PACE CALCULATIONS
# ══════════════════════════════════════════════════════════════════════

def calc_minutes_elapsed(period, clock_str):
    try:
        if not clock_str or clock_str == "0:00":
            return min(period * HALF_MINUTES, GAME_MINUTES) if period else 0
        parts = clock_str.replace(" ", "").split(":")
        if len(parts) == 2:
            mins_left = int(parts[0])
            secs_left = int(parts[1])
        elif len(parts) == 1:
            mins_left = 0
            secs_left = int(parts[0])
        else:
            mins_left, secs_left = 0, 0
        time_left = mins_left + secs_left / 60.0
        if period <= 2:
            elapsed_before = (period - 1) * HALF_MINUTES
            elapsed_in = HALF_MINUTES - time_left
        else:
            elapsed_before = GAME_MINUTES + (period - 3) * 5
            elapsed_in = 5 - time_left
        return max(0, elapsed_before + elapsed_in)
    except Exception:
        return 0.0

def calc_total_game_minutes(period):
    if period <= 2:
        return GAME_MINUTES
    return GAME_MINUTES + (period - 2) * 5

def calc_projection(home_score, away_score, minutes_elapsed, total_game_mins):
    total = home_score + away_score
    if minutes_elapsed <= 0:
        return LEAGUE_AVG_TOTAL
    cur_pace = total / minutes_elapsed
    lg_pace = LEAGUE_AVG_TOTAL / GAME_MINUTES
    pct = minutes_elapsed / total_game_mins
    if pct < 0.15:
        blend = 0.3
    elif pct < 0.5:
        blend = 0.5 + (pct - 0.15) * 1.0
    else:
        blend = 0.85 + (pct - 0.5) * 0.3
    blend = min(blend, 0.98)
    return round(((cur_pace * blend) + (lg_pace * (1 - blend))) * total_game_mins, 1)

def get_pace_label(ppm):
    if ppm >= 4.0: return "VERY HIGH"
    if ppm >= 3.6: return "HIGH"
    if ppm >= 3.2: return "AVERAGE"
    if ppm >= 2.8: return "LOW"
    return "VERY LOW"


# ── Kalshi NCAA deep link ────────────────────────────────────────────

def get_kalshi_ncaa_link(away_abbr, home_abbr):
    now = datetime.now(timezone.utc)
    date_str = now.strftime("%y") + now.strftime("%b").lower() + now.strftime("%d")
    away_k = away_abbr.lower().replace(" ", "").replace(".", "").replace("-", "")
    home_k = home_abbr.lower().replace(" ", "").replace(".", "").replace("-", "")
    ticker = "kxncaagame-" + date_str + away_k + home_k
    return "https://kalshi.com/markets/kxncaagame/college-basketball-game/" + ticker


# ══════════════════════════════════════════════════════════════════════
# ESPN FETCHERS
# ══════════════════════════════════════════════════════════════════════

def fetch_ncaa_games():
    games = []
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    url = ("https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard"
           "?dates=" + today + "&limit=200&groups=50")
    try:
        r = requests.get(url, timeout=10)
        if r.status_code != 200:
            return games
        data = r.json()
        for event in data.get("events", []):
            comp = event.get("competitions", [{}])[0]
            competitors = comp.get("competitors", [])
            if len(competitors) < 2:
                continue
            home = away = None
            for c in competitors:
                if c.get("homeAway") == "home":
                    home = c
                elif c.get("homeAway") == "away":
                    away = c
            if not home or not away:
                continue
            ht = home.get("team", {})
            at = away.get("team", {})
            status = event.get("status", {})
            state = status.get("type", {}).get("state", "pre")
            period = status.get("period", 0)
            clock = status.get("displayClock", "")
            odds_list = comp.get("odds", [])
            over_under = None
            spread = ""
            if odds_list:
                o = odds_list[0]
                ou_raw = o.get("overUnder")
                if ou_raw:
                    try:
                        over_under = float(ou_raw)
                    except (ValueError, TypeError):
                        pass
                spread = o.get("spread", "")
            home_record = home.get("records", [{}])[0].get("summary", "") if home.get("records") else ""
            away_record = away.get("records", [{}])[0].get("summary", "") if away.get("records") else ""
            home_rank = home.get("curatedRank", {}).get("current", 99)
            away_rank = away.get("curatedRank", {}).get("current", 99)
            bcasts = comp.get("broadcasts", [])
            broadcast = ""
            if bcasts:
                names = []
                for b in bcasts:
                    for n in b.get("names", []):
                        names.append(n)
                broadcast = ", ".join(names)
            game = {
                "id": str(event.get("id", "")),
                "name": event.get("name", ""),
                "shortName": event.get("shortName", ""),
                "state": state, "period": period, "clock": clock,
                "home_team": ht.get("displayName", ""),
                "home_abbr": ht.get("abbreviation", ""),
                "home_score": int(home.get("score", 0) or 0),
                "home_color": "#" + str(ht.get("color", "555555")),
                "home_record": home_record, "home_rank": home_rank,
                "home_id": str(ht.get("id", "")),
                "away_team": at.get("displayName", ""),
                "away_abbr": at.get("abbreviation", ""),
                "away_score": int(away.get("score", 0) or 0),
                "away_color": "#" + str(at.get("color", "555555")),
                "away_record": away_record, "away_rank": away_rank,
                "away_id": str(at.get("id", "")),
                "over_under": over_under, "spread": spread,
                "broadcast": broadcast,
                "venue": comp.get("venue", {}).get("fullName", ""),
                "minutes_elapsed": 0.0,
            }
            if state == "in":
                game["minutes_elapsed"] = calc_minutes_elapsed(period, clock)
            games.append(game)
    except Exception as e:
        st.error("ESPN fetch error: " + str(e))
    return games


def fetch_plays(game_id):
    plays = []
    try:
        url = "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/summary?event=" + str(game_id)
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            data = r.json()
            for item in data.get("plays", []):
                plays.append({
                    "text": item.get("text", ""),
                    "period": item.get("period", {}).get("number", 0),
                    "clock": item.get("clock", {}).get("displayValue", ""),
                    "score": item.get("scoreValue", 0),
                    "team_id": str(item.get("team", {}).get("id", "")),
                    "type": item.get("type", {}).get("text", ""),
                })
    except Exception:
        pass
    return plays


# ══════════════════════════════════════════════════════════════════════
# POSSESSION INFERENCE + COURT + PLAY ICONS
# ══════════════════════════════════════════════════════════════════════

def infer_possession(plays, home_abbr, away_abbr, home_name, away_name, home_id="", away_id=""):
    if not plays:
        return None, None
    h_ab, a_ab = home_abbr.lower(), away_abbr.lower()
    h_nm, a_nm = home_name.lower(), away_name.lower()
    h_id, a_id = str(home_id), str(away_id)

    def _match_home(tid, txt):
        return str(tid) == h_id or h_ab in txt or h_nm in txt

    def _match_away(tid, txt):
        return str(tid) == a_id or a_ab in txt or a_nm in txt

    for p in reversed(plays[-12:]):
        tid = str(p.get("team_id", ""))
        txt = (p.get("text", "") or "").lower()
        ptype = (p.get("type", "") or "").lower()
        if "steal" in ptype or "steal" in txt:
            if _match_home(tid, txt): return home_name, "home"
            if _match_away(tid, txt): return away_name, "away"
        if "turnover" in ptype or "turnover" in txt:
            continue
        if "made" in txt or "make" in ptype:
            if _match_home(tid, txt): return away_name, "away"
            if _match_away(tid, txt): return home_name, "home"
        if "rebound" in ptype or "rebound" in txt:
            if _match_home(tid, txt): return home_name, "home"
            if _match_away(tid, txt): return away_name, "away"
        if "foul" in ptype or "foul" in txt:
            continue
        if "missed" in txt or "miss" in ptype:
            continue
        if _match_home(tid, txt): return home_name, "home"
        if _match_away(tid, txt): return away_name, "away"
    return None, None


def render_court(home_abbr, away_abbr, score_home=0, score_away=0, poss_name=None, poss_side=None):
    ball_x = 375 if poss_side == "home" else 125 if poss_side == "away" else -100
    ball_vis = "visible" if poss_side in ("home", "away") else "hidden"
    svg = (
        "<svg viewBox='0 0 500 280' style='width:100%;max-width:500px;background:#1a1a2e;border-radius:8px'>"
        "<rect x='25' y='15' width='450' height='230' fill='none' stroke='#444' stroke-width='2' rx='5'/>"
        "<line x1='250' y1='15' x2='250' y2='245' stroke='#444' stroke-width='1.5'/>"
        "<circle cx='250' cy='130' r='35' fill='none' stroke='#444' stroke-width='1.5'/>"
        "<rect x='25' y='70' width='80' height='120' fill='none' stroke='#444' stroke-width='1'/>"
        "<rect x='395' y='70' width='80' height='120' fill='none' stroke='#444' stroke-width='1'/>"
        "<text x='125' y='135' text-anchor='middle' fill='#aaa' font-size='16' font-weight='700'>" + str(away_abbr) + "</text>"
        "<text x='375' y='135' text-anchor='middle' fill='#aaa' font-size='16' font-weight='700'>" + str(home_abbr) + "</text>"
        "<text x='125' y='155' text-anchor='middle' fill='white' font-size='20' font-weight='700'>" + str(score_away) + "</text>"
        "<text x='375' y='155' text-anchor='middle' fill='white' font-size='20' font-weight='700'>" + str(score_home) + "</text>"
        "<text x='" + str(ball_x) + "' y='270' text-anchor='middle' fill='#f1c40f' font-size='13' font-weight='700' visibility='" + ball_vis + "'>BALL</text>"
        "</svg>"
    )
    st.markdown(svg, unsafe_allow_html=True)
    if poss_name:
        st.markdown("<div style='text-align:center;padding:2px;color:#f1c40f;font-size:13px;font-weight:700'>" + str(poss_name) + " BALL</div>", unsafe_allow_html=True)


def get_play_icon(text):
    t = (text or "").lower()
    if "three" in t or "3pt" in t: return "[3PT]"
    if "dunk" in t: return "[DUNK]"
    if "steal" in t: return "[STL]"
    if "block" in t: return "[BLK]"
    if "turnover" in t: return "[TO]"
    if "foul" in t: return "[FOUL]"
    if "free throw" in t: return "[FT]"
    if "rebound" in t: return "[REB]"
    return ">"


def speak_play(text):
    clean_text = text.replace("'", "").replace('"', '').replace('\n', ' ')[:100]
    js = '<script>if(!window.lastSpoken||window.lastSpoken!=="' + clean_text + '"){window.lastSpoken="' + clean_text + '";var u=new SpeechSynthesisUtterance("' + clean_text + '");u.rate=1.1;window.speechSynthesis.speak(u);}</script>'
    components.html(js, height=0)


# ══════════════════════════════════════════════════════════════════════
# SCOREBOARD RENDERER
# ══════════════════════════════════════════════════════════════════════

def render_scoreboard(g):
    ha, aa = g["home_abbr"], g["away_abbr"]
    hc = g.get("home_color", "#555555")
    ac = g.get("away_color", "#555555")
    h_rec = " (" + g.get("home_record", "") + ")" if g.get("home_record") else ""
    a_rec = " (" + g.get("away_record", "") + ")" if g.get("away_record") else ""
    hr = "#" + str(g["home_rank"]) + " " if g.get("home_rank", 99) <= 25 else ""
    ar = "#" + str(g["away_rank"]) + " " if g.get("away_rank", 99) <= 25 else ""
    p = g.get("period", 0)
    hl = "H" + str(p) if p <= 2 else "OT" + str(p - 2)
    lead = abs(g["home_score"] - g["away_score"])
    leader = g["home_abbr"] if g["home_score"] > g["away_score"] else g["away_abbr"]
    status_html = "<span style='color:#e74c3c;font-weight:700'>LIVE " + hl + " " + str(g.get("clock", "")) + " | " + leader + " +" + str(lead) + "</span>"
    html = (
        "<div style='background:#1a1a2e;border-radius:10px;padding:12px;margin:6px 0;"
        "border-left:4px solid " + ac + ";border-right:4px solid " + hc + "'>"
        "<div style='display:flex;justify-content:space-between;align-items:center'>"
        "<div style='text-align:left;flex:1'>"
        "<div style='font-size:11px;color:" + ac + "'>" + ar + str(g["away_team"]) + a_rec + "</div>"
        "<div style='font-size:22px;font-weight:700;color:white'>" + str(g["away_score"]) + "</div>"
        "</div>"
        "<div style='text-align:center;flex:1'>" + status_html + "</div>"
        "<div style='text-align:right;flex:1'>"
        "<div style='font-size:11px;color:" + hc + "'>" + hr + str(g["home_team"]) + h_rec + "</div>"
        "<div style='font-size:22px;font-weight:700;color:white'>" + str(g["home_score"]) + "</div>"
        "</div></div></div>"
    )
    st.markdown(html, unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════
# MAIN LAYOUT
# ══════════════════════════════════════════════════════════════════════

st.markdown("## 🦈 NCAA SHARK SCANNER")
st.caption("v" + VERSION + " | " + datetime.now(timezone.utc).strftime("%A %b %d, %Y | %H:%M UTC") + " | NCAA Men's Basketball | Lead 7+ filter")

all_games = fetch_ncaa_games()
live_games = [g for g in all_games if g["state"] == "in"]

shark_games = []
for g in live_games:
    lead = abs(g["home_score"] - g["away_score"])
    if lead >= MIN_LEAD:
        shark_games.append(g)

c1, c2, c3 = st.columns(3)
c1.metric("Live Games", len(live_games))
c2.metric("7+ Lead (Tradeable)", len(shark_games))
c3.metric("Filtered Out", len(live_games) - len(shark_games))
st.divider()

if not shark_games:
    st.info("No live games with 7+ point lead right now. Waiting for games to separate...")


# ══════════════════════════════════════════════════════════════════════
# CUSHION SCANNER — TOTALS
# ══════════════════════════════════════════════════════════════════════

if shark_games:
    st.markdown("### CUSHION SCANNER — Totals")
    st.caption("Only showing games with **7+ point lead** — close games filtered out")

    cs_games = [str(g["away_abbr"]) + " @ " + str(g["home_abbr"]) for g in shark_games]
    cs_sel = st.selectbox("Game", ["ALL GAMES"] + cs_games, key="cs_game")
    cs_c1, cs_c2 = st.columns(2)
    cs_min = cs_c1.slider("Min minutes elapsed", 0, 40, 40, key="cs_min")
    cs_side = cs_c2.selectbox("Side", ["Both", "Over", "Under"], key="cs_side")

    found_any = False
    for g in shark_games:
        label = str(g["away_abbr"]) + " @ " + str(g["home_abbr"])
        if cs_sel != "ALL GAMES" and cs_sel != label:
            continue
        mins = g.get("minutes_elapsed", 0)
        if mins < cs_min:
            continue
        total = g["home_score"] + g["away_score"]
        total_game_mins = calc_total_game_minutes(g["period"])
        remaining = total_game_mins - mins
        pace = total / max(mins, 0.5)
        is_shark = remaining <= SHARK_MINUTES
        lead = abs(g["home_score"] - g["away_score"])
        leader = g["home_abbr"] if g["home_score"] > g["away_score"] else g["away_abbr"]

        for thresh in THRESHOLDS:
            needed_over = thresh - total
            if cs_side in ["Both", "Over"] and needed_over > 0 and remaining > 0:
                rate_needed = needed_over / remaining
                cushion = pace - rate_needed
                if cushion > 1.0:
                    safety = "FORTRESS"
                elif cushion > 0.4:
                    safety = "SAFE"
                elif cushion > 0.0:
                    safety = "TIGHT"
                else:
                    safety = "RISKY"
                if is_shark:
                    safety += " SHARK"
                found_any = True
                st.markdown(
                    "**" + label + "** OVER " + str(thresh) +
                    " — Need " + "{:.0f}".format(needed_over) +
                    " in " + "{:.0f}".format(remaining) + "min (" +
                    "{:.2f}".format(rate_needed) + "/min) | Pace " +
                    "{:.2f}".format(pace) + "/min | Lead: " +
                    leader + " +" + str(lead) + " | **" + safety + "**")

            if cs_side in ["Both", "Under"] and remaining > 0:
                projected_final = total + (remaining * pace)
                under_cushion = thresh - projected_final
                if projected_final < thresh:
                    if under_cushion > 10:
                        u_safety = "FORTRESS"
                    elif under_cushion > 4:
                        u_safety = "SAFE"
                    elif under_cushion > 0:
                        u_safety = "TIGHT"
                    else:
                        u_safety = "RISKY"
                    if is_shark:
                        u_safety += " SHARK"
                    found_any = True
                    st.markdown(
                        "**" + label + "** UNDER " + str(thresh) +
                        " — Proj " + "{:.0f}".format(projected_final) +
                        " vs Line " + str(thresh) + " | Cushion " +
                        "{:.1f}".format(under_cushion) + " pts | Lead: " +
                        leader + " +" + str(lead) + " | **" + u_safety + "**")

    if not found_any:
        st.info("No games match the current filter. Try lowering the minutes elapsed slider.")
    st.divider()


# ══════════════════════════════════════════════════════════════════════
# PACE SCANNER + COURT + PLAYS (expander per game)
# ══════════════════════════════════════════════════════════════════════

if shark_games:
    st.markdown("### PACE SCANNER")
    st.caption("Only games with 7+ point lead | Click game to see court + plays")

    for g in shark_games:
        mins = g.get("minutes_elapsed", 0)
        if mins < 2:
            continue
        total = g["home_score"] + g["away_score"]
        total_game_mins = calc_total_game_minutes(g["period"])
        remaining = total_game_mins - mins
        pace = total / max(mins, 0.5)
        proj = calc_projection(g["home_score"], g["away_score"], mins, total_game_mins)
        plabel = get_pace_label(pace)
        period = g.get("period", 0)
        hl = "H" + str(period) if period <= 2 else "OT" + str(period - 2)
        pct = mins / total_game_mins * 100
        shark = " SHARK" if remaining <= SHARK_MINUTES else ""
        lead = abs(g["home_score"] - g["away_score"])
        leader = g["home_abbr"] if g["home_score"] > g["away_score"] else g["away_abbr"]

        # ── Header line + progress bar ────────────────────────────
        col1, col2, col3 = st.columns([2, 1, 1])
        col1.markdown(
            "**" + str(g["away_abbr"]) + " " + str(g["away_score"]) +
            " @ " + str(g["home_abbr"]) + " " + str(g["home_score"]) +
            "** | " + hl + " " + str(g["clock"]) + " | " +
            leader + " +" + str(lead) + shark)
        col2.markdown("Pace: **" + "{:.2f}".format(pace) + "**/min " + plabel)
        col3.markdown("Proj: **" + str(proj) + "** | " + "{:.0f}".format(pct) + "% done")

        st.progress(min(pct / 100, 1.0))

        if g.get("over_under"):
            try:
                diff = proj - g["over_under"]
                if abs(diff) >= 5:
                    arrow = "OVER" if diff > 0 else "UNDER"
                    st.markdown(
                        "→ Proj " + str(proj) + " vs Line " +
                        str(g["over_under"]) + ": **" + arrow +
                        " (" + "{:+.1f}".format(diff) + ")**")
            except (ValueError, TypeError):
                pass

        kalshi_link = get_kalshi_ncaa_link(g["away_abbr"], g["home_abbr"])
        st.markdown("[Trade on Kalshi](" + kalshi_link + ")")

        # ── EXPANDER: Court + Plays ───────────────────────────────
        exp_label = "🏀 " + g["away_abbr"] + " @ " + g["home_abbr"] + " — Court + Plays"
        with st.expander(exp_label, expanded=False):
            render_scoreboard(g)

            plays = fetch_plays(g["id"])
            poss_name, poss_side = infer_possession(
                plays, g["home_abbr"], g["away_abbr"],
                g["home_team"], g["away_team"],
                g.get("home_id", ""), g.get("away_id", ""))

            lc, rc = st.columns(2)
            with lc:
                render_court(g["home_abbr"], g["away_abbr"],
                    score_home=g["home_score"], score_away=g["away_score"],
                    poss_name=poss_name, poss_side=poss_side)
            with rc:
                st.markdown("**Pace:** " + "{:.2f}".format(pace) + " pts/min " + plabel)
                st.markdown("**Projected Total:** " + str(proj))
                st.markdown("**Remaining:** " + "{:.1f}".format(remaining) + " min" + (" **SHARK MODE**" if shark else ""))
                st.markdown("**Lead:** " + leader + " +" + str(lead))

            if plays:
                st.markdown("**Recent Plays:**")
                tts_on = st.checkbox("Announce plays", key="tts_" + str(g["id"]))
                for idx_p, p in enumerate(plays[-8:]):
                    icon = get_play_icon(p.get("type", ""))
                    hp = "H" + str(p["period"]) if p.get("period", 0) <= 2 else "OT" + str(p["period"] - 2)
                    st.markdown(
                        "<span style='color:#888;font-size:12px'>" + hp + " " +
                        str(p.get("clock", "")) + " " + icon + " " +
                        str(p.get("text", "")) + "</span>", unsafe_allow_html=True)
                    if idx_p == len(plays[-8:]) - 1 and tts_on and p.get("text"):
                        speak_play(hp + " " + p.get("clock", "") + ". " + p.get("text", ""))
            else:
                st.info("No play-by-play data available yet.")

        st.markdown("---")
    st.divider()


# ══════════════════════════════════════════════════════════════════════
# HOW TO USE
# ══════════════════════════════════════════════════════════════════════

with st.expander("How to Use", expanded=False):
    st.markdown("""
### The Strategy

1. Slider defaults to **40 min** — only shows games near the end
2. **Only games with 7+ point lead** appear — close games are hidden
3. Click any game expander to see the **court, possession, and play-by-play**
4. Look for **FORTRESS SHARK** and **SAFE SHARK** ratings
5. Click **Trade on Kalshi** to go straight to the order book

### Why 7+ Lead Filter?

- Prevents ties and late comebacks from ruining your position
- A team down 7+ with 2-3 min left needs 3+ possessions plus stops
- The total is basically locked — free money window
- Close games (1-6 point leads) = chaos, skip them

### Cushion Labels

| Label | Meaning |
|-------|---------|
| **FORTRESS** | Locked in, would need miracle to lose |
| **SAFE** | Comfortable, pace supports it |
| **TIGHT** | Close, could swing |
| **RISKY** | Against pace |
| **SHARK** | Under 5 min left — high confidence |

### Important

- **Educational and informational purposes only**
- **NOT financial advice**
- Only trade what you can afford to lose
    """)


# ══════════════════════════════════════════════════════════════════════
# FOOTER
# ══════════════════════════════════════════════════════════════════════

st.markdown(
    "<div style='text-align:center;color:#555;font-size:11px;padding:20px'>"
    "<b>BigSnapshot NCAA SHARK Scanner v" + VERSION + "</b><br>"
    "For entertainment and educational purposes only. Not financial advice.<br>"
    "Past performance does not guarantee future results. Prediction markets involve risk.<br>"
    "Only wager what you can afford to lose.<br><br>"
    "<a href='https://bigsnapshot.com' style='color:#888'>bigsnapshot.com</a>"
    "</div>", unsafe_allow_html=True)
