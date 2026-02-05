import streamlit as st
import pandas as pd
import requests
import time
import random

# ---------------------------------------------------------
# 1. PAGE CONFIG
# ---------------------------------------------------------
st.set_page_config(page_title="EdgeAlmanac: Final", layout="wide")
st.caption("🟢 System Status: Online | Season: 2025-26")

# CONTROL PANEL
USE_REAL_STATS = True   
USE_REAL_ODDS = True    

# IMPORT CHECK
try:
    from nba_api.stats.endpoints import leaguedashplayerstats, playergamelog
    NBA_API_AVAILABLE = True
except ImportError:
    NBA_API_AVAILABLE = False
    USE_REAL_STATS = False

# ---------------------------------------------------------
# 2. HELPER FUNCTIONS
# ---------------------------------------------------------

def get_vegas_odds(api_key):
    """ Tries to get real odds, returns empty if failed """
    if not api_key: return pd.DataFrame()
    
    try:
        # 3-Second Timeout
        url_odds = 'https://api.the-odds-api.com/v4/sports/basketball_nba/odds'
        r_odds = requests.get(url_odds, params={
            'apiKey': api_key,
            'regions': 'us',
            'markets': 'player_points',
            'oddsFormat': 'american'
        }, timeout=3)
        
        if r_odds.status_code != 200:
            return pd.DataFrame()

        data = r_odds.json()
        props = []
        if isinstance(data, list):
            for game in data:
                for book in game.get('bookmakers', []):
                    for market in book.get('markets', []):
                        if market['key'] == 'player_points':
                            for outcome in market['outcomes']:
                                if outcome.get('name') == 'Over':
                                    props.append({
                                        'PLAYER_NAME': outcome['description'],
                                        'Line': outcome['point']
                                    })
        
        df = pd.DataFrame(props)
        if not df.empty:
            df = df.groupby('PLAYER_NAME')['Line'].mean().reset_index()
            return df
        return pd.DataFrame()
            
    except Exception:
        return pd.DataFrame()

def generate_mock_stats():
    """ Fallback Data """
    players = ["Shai Gilgeous-Alexander", "Luka Doncic", "Ty Jerome", "Trae Young", "Jayson Tatum"]
    ids = [1628983, 1629029, 1629660, 1629027, 1628369]
    data = []
    for i, p in enumerate(players):
        avg = round(random.uniform(22, 32), 1)
        l5 = avg + random.uniform(-8, 10) 
        data.append({
            'PLAYER_ID': ids[i],
            'PLAYER_NAME': p,
            'TEAM': 'NBA',
            'Season_Avg': avg,
            'L5_Avg': round(l5, 1)
        })
    return pd.DataFrame(data)

def get_nba_stats():
    if not USE_REAL_STATS or not NBA_API_AVAILABLE:
        return generate_mock_stats()

    try:
        # Season Stats (PerGame fixed)
        stats_season = leaguedashplayerstats.LeagueDashPlayerStats(
            season='2025-26', 
            last_n_games=0, 
            per_mode_detailed='PerGame'
        )
        df_season = stats_season.get_data_frames()[0]
        time.sleep(0.6)
        
        # L5 Stats (PerGame fixed)
        stats_recent = leaguedashplayerstats.LeagueDashPlayerStats(
            season='2025-26', 
            last_n_games=5, 
            per_mode_detailed='PerGame'
        )
        df_recent = stats_recent.get_data_frames()[0]

        if df_season.empty: return generate_mock_stats()

        # Merge
        df_season = df_season[['PLAYER_ID', 'PLAYER_NAME', 'TEAM_ABBREVIATION', 'PTS']].rename(columns={'PTS': 'Season_Avg'})
        df_recent = df_recent[['PLAYER_ID', 'PTS']].rename(columns={'PTS': 'L5_Avg'})
        
        full_df = pd.merge(df_season, df_recent, on='PLAYER_ID')
        
        if 'PLAYER_NAME_y' in full_df.columns:
            full_df = full_df.drop(columns=['PLAYER_NAME_y'])
        full_df = full_df.rename(columns={'PLAYER_NAME_x': 'PLAYER_NAME', 'TEAM_ABBREVIATION_x': 'TEAM'})
        
        return full_df

    except Exception:
        return generate_mock_stats()

def get_game_logs(player_id):
    if not USE_REAL_STATS or not NBA_API_AVAILABLE:
        dates = pd.date_range(end=pd.Timestamp.now(), periods=5).strftime('%Y-%m-%d').tolist()
        pts = [random.randint(15, 35) for _ in range(5)]
        return pd.DataFrame({'GAME_DATE': dates, 'PTS': pts, 'MATCHUP': ['vs TEAM']*5})

    try:
        log = playergamelog.PlayerGameLog(player_id=player_id, season='2025-26')
        return log.get_data_frames()[0].head(10)
    except:
        return pd.DataFrame()

# ---------------------------------------------------------
# 3. MAIN EXECUTION
# ---------------------------------------------------------

st.title("EdgeAlmanac: L5 Sniper Engine")

# --- SIDEBAR ---
with st.sidebar:
    st.header("⚙️ Configuration")
    
    odds_key = ""
    is_secure_load = False
    
    try:
        if "ODDS_API_KEY" in st.secrets:
            odds_key = st.secrets["ODDS_API_KEY"]
            is_secure_load = True
    except:
        pass

    if is_secure_load:
        st.success("🔑 API Key Loaded")
    else:
        st.warning("⚠️ No backend key found.")
        odds_key = st.text_input("Enter Odds API Key", type="password")

    if st.button("🔄 System Refresh"):
        st.cache_data.clear()
        st.rerun()

# --- LOADING SEQUENCE ---
status_text = st.empty()

status_text.text("⏳ Fetching L5 Stats...")
df_stats = get_nba_stats()

status_text.text("⏳ Fetching Live Odds...")
df_odds = pd.DataFrame()
if odds_key:
    df_odds = get_vegas_odds(odds_key)

status_text.text("⏳ Calculating Edges...")

# MERGE
if not df_odds.empty:
    df_final = pd.merge(df_stats, df_odds, on='PLAYER_NAME', how='left')
    df_final['Line'] = df_final['Line'].fillna(0)
    # NEW: Flag to tell us if line is real
    df_final['Line_Source'] = df_final['Line'].apply(lambda x: "Vegas" if x > 0 else "Sim")
else:
    df_final = df_stats
    df_final['Line'] = 0
    df_final['Line_Source'] = "Sim"

# --- THE FIX: SYNTHETIC LINES ---
# If Line is 0, we set it to Season Avg (rounded) so the Edge math works
def fill_synthetic_line(row):
    if row['Line'] > 0:
        return row['Line']
    else:
        # Create a "Standard" line based on their average
        return round(row['Season_Avg'] * 2) / 2 # Round to nearest 0.5

df_final['Line'] = df_final.apply(fill_synthetic_line, axis=1)

# CALCULATION (Edge = Recent L5 - Line)
df_final['Edge'] = df_final['L5_Avg'] - df_final['Line']
df_final['Edge'] = df_final['Edge'].round(1)

def classify(val):
    if val >= 5.0: return "🔥 NOVA"     # Super Heater
    elif val >= 3.0: return "🔥 HEATER"
    elif val >= 1.5: return "✅ VALUE"
    elif val <= -5.0: return "❄️ ARCTIC" # Super Cold
    elif val <= -3.0: return "❄️ FREEZER"
    else: return "➖ NORMAL"

df_final['Status'] = df_final['Edge'].apply(classify)
df = df_final

status_text.empty() 

# --- TABS ---
tab_board, tab_sniper = st.tabs(["📊 The Board", "🔭 Sniper Scope"])

with tab_board:
    if not df.empty:
        # Sort by Edge
        df_sorted = df.sort_values(by='Edge', ascending=False)
        
        if not df_sorted.empty:
            top_play = df_sorted.iloc[0]
            
            c1, c2, c3 = st.columns(3)
            c1.metric("🏆 Top Edge", top_play['PLAYER_NAME'], f"{top_play['Edge']}")
            c2.metric("🎲 Data Source", "Real Vegas" if "Vegas" in df['Line_Source'].values else "Projected Lines")
            c3.metric("📅 Scope", "Last 5 Games")
            
            st.divider()
            
            search = st.text_input("🔍 Search Player", "")
            if search:
                df_display = df[df['PLAYER_NAME'].str.contains(search, case=False)]
            else:
                df_display = df_sorted

            def highlight_edge(val):
                color = '#228B22' if val > 2.0 else ('#FF4B4B' if val < -2.0 else 'white')
                return f'color: {color}'

            # Display
            st.dataframe(
                df_display[['Status', 'PLAYER_NAME', 'Season_Avg', 'L5_Avg', 'Line', 'Edge']]
                .style.applymap(highlight_edge, subset=['Edge'])
                .format("{:.1f}", subset=['Season_Avg', 'L5_Avg', 'Line', 'Edge']),
                use_container_width=True,
                height=600
            )
        else:
            st.warning("Dataframe empty.")
    else:
        st.error("No data loaded.")

with tab_sniper:
    st.subheader("🔭 Sniper Scope")
    if not df.empty:
        targets = df.sort_values(by='Edge', ascending=False)['PLAYER_NAME'].tolist()
        if targets:
            target_name = st.selectbox("Select Target", targets)
            
            player_row = df[df['PLAYER_NAME'] == target_name].iloc[0]
            pid = player_row['PLAYER_ID']
            auto_line = player_row['Line']
            l5_val = player_row['L5_Avg']
            
            c_set1, c_set2 = st.columns(2)
            with c_set1:
                line_input = st.number_input(
                    "Target Line", 
                    value=float(auto_line) if auto_line > 0 else float(l5_val), 
                    step=0.5
                )
            
            if st.button("🎯 Analyze Target"):
                logs = get_game_logs(pid)
                if not logs.empty:
                    if 'PTS' in logs.columns:
                        logs['Hit'] = logs['PTS'] > line_input
                        hit_rate = logs['Hit'].mean() * 100
                        
                        m1, m2, m3 = st.columns(3)
                        m1.metric("Target", target_name)
                        m2.metric("Hit Rate (L10)", f"{int(hit_rate)}%")
                        m3.metric("Trend", "✅ OVER" if hit_rate >= 60 else "⚠️ UNDER")
                        
                        st.bar_chart(logs, x="GAME_DATE", y="PTS")
                        st.dataframe(logs[['GAME_DATE', 'MATCHUP', 'PTS', 'Hit']])
                    else:
                        st.error("Log data missing Points column.")
                else:
                    st.error("No logs found.")
        else:
            st.warning("No targets available.")