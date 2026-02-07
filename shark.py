"""
shark.py — BigSnapshot NBA Cushion Scanner
Run: streamlit run shark.py
"""

import streamlit as st
st.set_page_config(page_title="BigSnapshot NBA Cushion Scanner", page_icon="🏀", layout="wide")

import requests, json, time, hashlib, datetime as dt
from datetime import datetime, timedelta, timezone
from streamlit_autorefresh import st_autorefresh

# ══════════════════════════════════════════════════════════════════════
# OWNER MODE — password gate via URL param or input
# ══════════════════════════════════════════════════════════════════════
# Usage: https://yourapp.streamlit.app/?key=SHARK2026
# Or enter password in the input box on load.

OWNER_KEY = "SHARK2026"

def check_auth():
    params = st.query_params
    url_key = params.get("key", "")
    if url_key == OWNER_KEY:
        st.session_state["authenticated"] = True
        return True
    if st.session_state.get("authenticated"):
        return True
    st.markdown("### BigSnapshot NBA — Owner Access")
    pwd = st.text_input("Enter access key:", type="password", key="auth_input")
    if pwd:
        if pwd == OWNER_KEY:
            st.session_state["authenticated"] = True
            st.rerun()
        else:
            st.error("Wrong key.")
    st.stop()

check_auth()

st_autorefresh(interval=30_000, limit=10000, key="nba_refresh")

# ══════════════════════════════════════════════════════════════════════
# CONFIG
# ══════════════════════════════════════════════════════════════════════

VERSION = "1.0"
GAME_MINUTES = 48
QUARTER_MINUTES = 12
OT_MINUTES = 5
LEAGUE_AVG_TOTAL = 224
THRESHOLDS = [190.5, 195.5, 200.5, 205.5, 210.5, 215.5, 220.5,
              225.5, 230.5, 235.5, 240.5, 245.5, 250.5]
SHARK_MINUTES = 6.0

if "session_id" not in st.session_state:
    st.session_state["session_id"] = hashlib.md5(str(time.time()).encode()).hexdigest()[:12]

TEAM_COLORS = {
    "BOS": "#007A33", "MIL": "#00471B", "OKC": "#007AC1", "DEN": "#0E2240",
    "MIN": "#0C2340", "DAL": "#00538C", "NYK": "#F58426", "CLE": "#860038",
    "PHX": "#1D1160", "LAL": "#552583", "LAC": "#C8102E", "GSW": "#1D428A",
    "SAC": "#5A2D81", "MIA": "#98002E", "PHI": "#006BB6", "IND": "#002D62",
    "ORL": "#0077C0", "CHI": "#CE1141", "ATL": "#E03A3E", "BKN": "#000000",
    "TOR": "#CE1141", "HOU": "#CE1141", "MEM": "#5D76A9", "NOP": "#0C2340",
    "SAS": "#C4CED4", "POR": "#E03A3E", "UTA": "#002B5C", "WAS": "#002B5C",
    "DET": "#C8102E", "CHA": "#1D1160",
}

def get_team_color(abbr):
    return TEAM_COLORS.get(abbr.upper(), "#555555") if abbr else "#555555"


# ══════════════════════════════════════════════════════════════════════
# TIME / PACE CALCULATIONS
# ══════════════════════════════════════════════════════════════════════

def calc_minutes_elapsed(period, clock_str):
    try:
        if not clock_str or clock_str == "0:00":
            if period <= 4:
                return min(period * QUARTER_MINUTES, GAME_MINUTES)
            else:
                return GAME_MINUTES + (period - 4) * OT_MINUTES
        parts = clock_str.replace(" ", "").split(":")
        if len(parts) == 2:
            mins_left = int(parts[0])
            secs_left = int(parts[1])
        elif len(parts) == 1:
            mins_left = 0
            secs_left = int(parts[0])
        else:
            mins_left, secs_left = 0, 0
        time_left_in_period = mins_left + secs_left / 60.0
        if period <= 4:
            elapsed_before = (period - 1) * QUARTER_MINUTES
            elapsed_in_period = QUARTER_MINUTES - time_left_in_period
        else:
            elapsed_before = GAME_MINUTES + (period - 5) * OT_MINUTES
            elapsed_in_period = OT_MINUTES - time_left_in_period
        return max(0, elapsed_before + elapsed_in_period)
    except Exception:
        return 0.0

def calc_total_game_minutes(period):
    if period <= 4:
        return GAME_MINUTES
    return GAME_MINUTES + (period - 4) * OT_MINUTES

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
    if ppm >= 5.2: return "VERY HIGH"
    if ppm >= 4.8: return "HIGH"
    if ppm >= 4.4: return "AVERAGE"
    if ppm >= 3.8: return "LOW"
    return "VERY LOW"


# ══════════════════════════════════════════════════════════════════════
# ESPN NBA SCOREBOARD FETCH
# ══════════════════════════════════════════════════════════════════════

def fetch_nba_games():
    games = []
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    url = ("https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"
           "?dates=" + today + "&limit=50")
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
                "state": state,
                "period": period,
                "clock": clock,
                "home_team": ht.get("displayName", ""),
                "home_abbr": ht.get("abbreviation", ""),
                "home_score": int(home.get("score", 0) or 0),
                "home_color": "#" + str(ht.get("color", "555555")),
                "home_record": home_record,
                "away_team": at.get("displayName", ""),
                "away_abbr": at.get("abbreviation", ""),
                "away_score": int(away.get("score", 0) or 0),
                "away_color": "#" + str(at.get("color", "555555")),
                "away_record": away_record,
                "over_under": over_under,
                "spread": spread,
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


# ══════════════════════════════════════════════════════════════════════
# SCOREBOARD RENDERER
# ══════════════════════════════════════════════════════════════════════

def render_scoreboard(g):
    state = g["state"]
    ha, aa = g["home_abbr"], g["away_abbr"]
    hc = g.get("home_color", get_team_color(ha))
    ac = g.get("away_color", get_team_color(aa))
    h_rec = " (" + g.get("home_record", "") + ")" if g.get("home_record") else ""
    a_rec = " (" + g.get("away_record", "") + ")" if g.get("away_record") else ""
    if state == "in":
        p = g.get("period", 0)
        ql = "Q" + str(p) if p <= 4 else "OT" + str(p - 4)
        status_html = "<span style='color:#e74c3c;font-weight:700'>LIVE " + ql + " " + str(g.get("clock", "")) + "</span>"
    elif state == "post":
        status_html = "<span style='color:#888'>FINAL</span>"
    else:
        status_html = "<span style='color:#aaa'>" + str(g.get("broadcast", "TBD")) + "</span>"
    venue = g.get("venue", "")
    venue_html = "<div style='font-size:10px;color:#777'>" + venue + "</div>" if venue else ""
    html = (
        "<div style='background:#1a1a2e;border-radius:10px;padding:12px;margin:6px 0;"
        "border-left:4px solid " + ac + ";border-right:4px solid " + hc + "'>"
        "<div style='display:flex;justify-content:space-between;align-items:center'>"
        "<div style='text-align:left;flex:1'>"
        "<div style='font-size:11px;color:" + ac + "'>" + str(g["away_team"]) + a_rec + "</div>"
        "<div style='font-size:22px;font-weight:700;color:white'>" + str(g["away_score"]) + "</div>"
        "</div>"
        "<div style='text-align:center;flex:1'>" + status_html + "</div>"
        "<div style='text-align:right;flex:1'>"
        "<div style='font-size:11px;color:" + hc + "'>" + str(g["home_team"]) + h_rec + "</div>"
        "<div style='font-size:22px;font-weight:700;color:white'>" + str(g["home_score"]) + "</div>"
        "</div></div>" + venue_html + "</div>"
    )
    st.markdown(html, unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════
# MAIN LAYOUT
# ══════════════════════════════════════════════════════════════════════

st.markdown("## BIGSNAPSHOT NBA CUSHION SCANNER")
st.caption("v" + VERSION + " | " + datetime.now(timezone.utc).strftime("%A %b %d, %Y | %H:%M UTC") + " | NBA | Cushion + Pace")

all_games = fetch_nba_games()

live_games = [g for g in all_games if g["state"] == "in"]
scheduled_games = [g for g in all_games if g["state"] == "pre"]
final_games = [g for g in all_games if g["state"] == "post"]

c1, c2, c3, c4 = st.columns(4)
c1.metric("Today's Games", len(all_games))
c2.metric("Live", len(live_games))
c3.metric("Scheduled", len(scheduled_games))
c4.metric("Final", len(final_games))
st.divider()


# ══════════════════════════════════════════════════════════════════════
# LIVE SCOREBOARD
# ══════════════════════════════════════════════════════════════════════

if live_games:
    st.markdown("### LIVE GAMES")
    for g in live_games:
        mins = g.get("minutes_elapsed", 0)
        total_game_mins = calc_total_game_minutes(g["period"])
        total = g["home_score"] + g["away_score"]
        pace = total / max(mins, 0.5)
        proj = calc_projection(g["home_score"], g["away_score"], mins, total_game_mins)
        remaining = total_game_mins - mins
        pace_label = get_pace_label(pace)
        pct = mins / total_game_mins * 100
        period = g.get("period", 0)
        ql = "Q" + str(period) if period <= 4 else "OT" + str(period - 4)
        shark = " SHARK" if remaining <= SHARK_MINUTES else ""

        render_scoreboard(g)
        lc, rc = st.columns(2)
        with lc:
            st.markdown("**Pace:** " + "{:.2f}".format(pace) + " pts/min " + pace_label)
            st.markdown("**Projected Total:** " + str(proj))
            st.markdown("**Progress:** " + "{:.0f}".format(pct) + "% (" + "{:.1f}".format(mins) + "/" + str(total_game_mins) + " min)")
        with rc:
            lead = g["home_score"] - g["away_score"]
            if lead > 0:
                st.markdown("**Lead:** " + str(g["home_team"]) + " +" + str(lead))
            elif lead < 0:
                st.markdown("**Lead:** " + str(g["away_team"]) + " +" + str(abs(lead)))
            else:
                st.markdown("**Lead:** TIE")
            st.markdown("**Remaining:** " + "{:.1f}".format(remaining) + " min" + (" **SHARK MODE**" if shark else ""))
            if g.get("over_under"):
                diff = proj - g["over_under"]
                if abs(diff) >= 5:
                    direction = "OVER" if diff > 0 else "UNDER"
                    st.markdown("**Totals Edge:** Proj " + str(proj) + " vs Line " + str(g["over_under"]) + " -> **" + direction + " (" + "{:+.1f}".format(diff) + ")**")
        st.markdown("---")
    st.divider()


# ══════════════════════════════════════════════════════════════════════
# CUSHION SCANNER — TOTALS (THE MONEY MAKER)
# ══════════════════════════════════════════════════════════════════════

if live_games:
    st.markdown("### CUSHION SCANNER — Totals")
    cs_games = [str(g["away_abbr"]) + " @ " + str(g["home_abbr"]) for g in live_games]
    cs_sel = st.selectbox("Game", ["ALL GAMES"] + cs_games, key="cs_game")
    cs_c1, cs_c2 = st.columns(2)
    cs_min = cs_c1.slider("Min minutes elapsed", 0, 48, 0, key="cs_min")
    cs_side = cs_c2.selectbox("Side", ["Both", "Over", "Under"], key="cs_side")

    found_any = False
    for g in live_games:
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

        for thresh in THRESHOLDS:
            # ── OVER ──────────────────────────────────────────────
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
                    "{:.2f}".format(pace) + "/min | **" + safety + "**")

            # ── UNDER ─────────────────────────────────────────────
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
                        "{:.1f}".format(under_cushion) + " pts | **" + u_safety + "**")

    if not found_any:
        st.info("No games match the current filter. Try lowering the minutes elapsed slider.")
    st.divider()


# ══════════════════════════════════════════════════════════════════════
# PACE SCANNER (with blue progress bars)
# ══════════════════════════════════════════════════════════════════════

if live_games:
    st.markdown("### PACE SCANNER")
    for g in live_games:
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
        ql = "Q" + str(period) if period <= 4 else "OT" + str(period - 4)
        pct = mins / total_game_mins * 100
        shark = " SHARK" if remaining <= SHARK_MINUTES else ""

        col1, col2, col3 = st.columns([2, 1, 1])
        col1.markdown(
            "**" + str(g["away_abbr"]) + " " + str(g["away_score"]) +
            " @ " + str(g["home_abbr"]) + " " + str(g["home_score"]) +
            "** | " + ql + " " + str(g["clock"]) + shark)
        col2.markdown("Pace: **" + "{:.2f}".format(pace) + "**/min " + plabel)
        col3.markdown("Proj: **" + str(proj) + "** | " + "{:.0f}".format(pct) + "% done")

        # THE BLUE BAR
        st.progress(min(pct / 100, 1.0))

        # O/U comparison
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
    st.divider()


# ══════════════════════════════════════════════════════════════════════
# ALL GAMES TODAY
# ══════════════════════════════════════════════════════════════════════

st.markdown("### ALL GAMES TODAY")
for g in all_games:
    ha, aa = g["home_abbr"], g["away_abbr"]
    h_rec = " (" + g.get("home_record", "") + ")" if g.get("home_record") else ""
    a_rec = " (" + g.get("away_record", "") + ")" if g.get("away_record") else ""

    if g["state"] == "in":
        p = g.get("period", 0)
        ql = "Q" + str(p) if p <= 4 else "OT" + str(p - 4)
        st.markdown(
            "LIVE **" + str(g["away_team"]) + a_rec + " " +
            str(g["away_score"]) + "** @ **" + str(g["home_team"]) +
            h_rec + " " + str(g["home_score"]) + "** — " +
            ql + " " + str(g["clock"]))
    elif g["state"] == "post":
        st.markdown(
            "FINAL **" + str(g["away_team"]) + a_rec + " " +
            str(g["away_score"]) + "** @ **" + str(g["home_team"]) +
            h_rec + " " + str(g["home_score"]) + "**")
    else:
        parts = []
        if g.get("spread"):
            parts.append("Spread: " + str(g["spread"]))
        if g.get("over_under"):
            parts.append("O/U: " + str(g["over_under"]))
        if g.get("broadcast"):
            parts.append(str(g["broadcast"]))
        st.markdown(
            "SCHED **" + str(g["away_team"]) + a_rec + "** @ **" +
            str(g["home_team"]) + h_rec + "** — " + " | ".join(parts))

st.divider()


# ══════════════════════════════════════════════════════════════════════
# HOW TO USE
# ══════════════════════════════════════════════════════════════════════

with st.expander("How to Use This App", expanded=False):
    st.markdown("""
### The Strategy

1. Set **Min minutes elapsed** slider to **42-46** (late 4th quarter)
2. Set **Side** to **Under** (or Over depending on your read)
3. Watch for **FORTRESS SHARK** and **SAFE SHARK** ratings
4. These are games where the projected total is locked below/above a threshold with <6 min left
5. Buy the position on Kalshi — settlement is almost guaranteed

### Cushion Scanner Labels

| Label | Meaning |
|-------|---------|
| **FORTRESS** | Extremely safe, would need collapse |
| **SAFE** | Comfortable cushion, pace supports it |
| **TIGHT** | Close, could go either way |
| **RISKY** | Against current pace |
| **SHARK** | Under 6 min left — high confidence window |

### NBA Timing

- NBA games = 48 minutes (4 x 12 min quarters)
- OT = 5 min each
- **SHARK MODE** triggers at ≤6 min remaining
- Slider goes to 58 min to cover OT games
- Sweet spot: **42-46 min elapsed** = last 2-6 min of Q4

### Pace Labels (NBA scale)

| Pace | Rating |
|------|--------|
| 5.2+ pts/min | VERY HIGH |
| 4.8-5.2 | HIGH |
| 4.4-4.8 | AVERAGE |
| 3.8-4.4 | LOW |
| <3.8 | VERY LOW |

### Important Notes

- For **educational and informational purposes only**
- **NOT financial advice** and NOT betting advice
- Past performance does **NOT** guarantee future results
- Prediction markets involve real financial risk
- **Only trade what you can afford to lose**
    """)


# ══════════════════════════════════════════════════════════════════════
# FOOTER
# ══════════════════════════════════════════════════════════════════════

st.markdown(
    "<div style='text-align:center;color:#555;font-size:11px;padding:20px'>"
    "<b>BigSnapshot NBA Cushion Scanner v" + VERSION + "</b><br>"
    "For entertainment and educational purposes only. Not financial advice.<br>"
    "Past performance does not guarantee future results. Prediction markets involve risk.<br>"
    "Only wager what you can afford to lose.<br><br>"
    "<a href='https://bigsnapshot.com' style='color:#888'>bigsnapshot.com</a>"
    "</div>", unsafe_allow_html=True)
