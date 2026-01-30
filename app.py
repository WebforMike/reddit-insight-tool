import streamlit as st
import google.generativeai as genai
from tavily import TavilyClient
import requests
import json
import re
import os
import statistics
import time

# --- 1. PAGE CONFIGURATION ---
st.set_page_config(page_title="Reddit Insight Miner", page_icon="⚡", layout="wide")

# --- 2. SESSION STATE SETUP (Keeps data on screen) ---
if "results" not in st.session_state:
    st.session_state.results = None
if "status_log" not in st.session_state:
    st.session_state.status_log = ""

# --- 3. SIDEBAR: API KEYS ---
with st.sidebar:
    st.header("🔑 API Keys")
    
    # We check secrets first, then allow manual entry
    gemini_key = st.secrets.get("GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY")
    if not gemini_key:
        gemini_key = st.text_input("Gemini API Key", type="password")

    tavily_key = st.secrets.get("TAVILY_API_KEY") or os.getenv("TAVILY_API_KEY")
    if not tavily_key:
        tavily_key = st.text_input("Tavily API Key", type="password")

    jina_key = st.secrets.get("JINA_API_KEY") or os.getenv("JINA_API_KEY")
    if not jina_key:
        jina_key = st.text_input("Jina API Key", type="password")
        st.caption("Get one free at jina.ai/reader")

# --- 4. HELPER FUNCTIONS ---
def fetch_with_jina(url, api_key):
    if not api_key: return None, "Missing Key"
    try:
        headers = {'Authorization': f'Bearer {api_key}', 'X-Return-Format': 'markdown'}
        response = requests.get(f"https://r.jina.ai/{url}", headers=headers, timeout=25)
        return (response.text, "Success") if response.status_code == 200 else (None, f"Error {response.status_code}")
    except Exception as e:
        return None, str(e)

def run_analysis(topic, gemini_k, tavily_k, jina_k):
    """Main logic function called on form submit"""
    log = []
    try:
        # Init Clients
        tavily = TavilyClient(api_key=tavily_k)
        genai.configure(api_key=gemini_k)
        model = genai.GenerativeModel('gemini-2.0-flash') # Or 'gemini-1.5-flash' if 2.0 fails

        # 1. Search
        log.append(f"🕵️ Searching Reddit for '{topic}'...")
        search_result = tavily.search(query=f"site:reddit.com {topic}", search_depth="advanced", max_results=5)
        threads = search_result.get('results', [])
        
        if not threads:
            return None, log + ["❌ No threads found."]

        # 2. Scrape
        log.append(f"✅ Found {len(threads)} threads. Scraping via Jina...")
        combined_text = ""
        valid_count = 0
        
        for t in threads:
            content, msg = fetch_with_jina(t['url'], jina_k)
            if content:
                combined_text += f"SOURCE: {t['url']}\nTITLE: {t['title']}\nCONTENT:\n{content[:5000]}\n{'='*40}\n"
                valid_count += 1
            time.sleep(0.2)
            
        if valid_count == 0:
            return None, log + ["❌ All threads were blocked or empty."]

        # 3. Analyze
        log.append("🧠 Analyzing data with Gemini...")
        prompt = f"""
        Analyze these Reddit threads about "{topic}".
        Return JSON ONLY:
        - "raw_prices": [list of integers].
        - "sentiment": "Positive/Negative/Neutral".
        - "summary": String.
        - "currency": "$".
        - "key_quote": String.

        DATA:
        {combined_text}
        """
        response = model.generate_content(prompt)
        cleaned_json = re.sub(r"```json|```", "", response.text).strip()
        data = json.loads(cleaned_json)
        
        # Add sources to data for display
        data["sources"] = threads
        return data, log + ["✅ Analysis Complete!"]

    except Exception as e:
        return None, log + [f"❌ Error: {str(e)}"]

# --- 5. MAIN APP UI ---
st.title("⚡ Reddit Insight Miner")
st.markdown("Enter a topic below. Using **Jina** (Scraping) + **Gemini** (AI).")

# --- THE FIX: USE A FORM ---
with st.form("search_form"):
    topic_input = st.text_input("Enter Topic:", "Car Insurance Cost Florida")
    # This button now triggers the form submission properly
    submitted = st.form_submit_button("🚀 Mine Insights", type="primary")

if submitted:
    if not (gemini_key and tavily_key and jina_key):
        st.error("⚠️ Please enter ALL API keys in the sidebar first!")
    else:
        with st.spinner("Agent is working... (This may take 15-30 seconds)"):
            data, logs = run_analysis(topic_input, gemini_key, tavily_key, jina_key)
            st.session_state.results = data
            st.session_state.status_log = logs

# --- 6. DISPLAY RESULTS (FROM SESSION STATE) ---
if st.session_state.results:
    data = st.session_state.results
    
    # Statistics
    raw_prices = data.get("raw_prices", [])
    stats = {'min': 0, 'max': 0, 'avg': 0, 'median': 0, 'count': 0}
    if raw_prices:
        stats['min'] = min(raw_prices)
        stats['max'] = max(raw_prices)
        stats['avg'] = int(statistics.mean(raw_prices))
        stats['median'] = int(statistics.median(raw_prices))
        stats['count'] = len(raw_prices)

    st.divider()
    st.header(f"📊 Report: {topic_input}")
    
    c1, c2, c3, c4 = st.columns(4)
    currency = data.get("currency", "$")
    c1.metric("Avg Price", f"{currency}{stats['avg']}")
    c2.metric("Median Price", f"{currency}{stats['median']}")
    c3.metric("Min Found", f"{currency}{stats['min']}")
    c4.metric("Max Found", f"{currency}{stats['max']}")
    
    st.caption(f"Based on {stats['count']} data points.")
    
    st.subheader("📝 Summary")
    st.write(data.get("summary"))
    
    st.info(f"**Sentiment:** {data.get('sentiment')} | **Key Quote:** \"{data.get('key_quote')}\"")
    
    with st.expander("View Raw Sources"):
        for s in data.get("sources", []):
            st.markdown(f"- [{s['title']}]({s['url']})")

# Debug Logs (Optional, helps you see what happened)
if st.session_state.status_log:
    with st.expander("View Processing Logs"):
        for msg in st.session_state.status_log:
            st.write(msg)
