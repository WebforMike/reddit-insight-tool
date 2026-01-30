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
st.set_page_config(page_title="Reddit Insight Miner", page_icon="🛡️", layout="wide")

# --- 2. SESSION STATE ---
if "results" not in st.session_state:
    st.session_state.results = None
if "status_log" not in st.session_state:
    st.session_state.status_log = ""

# --- 3. SIDEBAR: API KEYS ---
with st.sidebar:
    st.header("🔑 API Keys")
    
    gemini_key = st.secrets.get("GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY")
    if not gemini_key:
        gemini_key = st.text_input("Gemini API Key", type="password")

    tavily_key = st.secrets.get("TAVILY_API_KEY") or os.getenv("TAVILY_API_KEY")
    if not tavily_key:
        tavily_key = st.text_input("Tavily API Key", type="password")

    # Jina is removed because it is getting blocked.
    
# --- 4. LOGIC: TAVILY CACHE MODE ---
def run_analysis_cached(topic, gemini_k, tavily_k):
    log = []
    try:
        tavily = TavilyClient(api_key=tavily_k)
        genai.configure(api_key=gemini_k)
        model = genai.GenerativeModel('gemini-2.0-flash')

        # 1. SEARCH WITH RAW CONTENT (The Fix)
        # We assume Reddit will block any direct visit, so we ask Tavily 
        # to give us the 'raw_content' it scraped during indexing.
        log.append(f"🕵️ Searching Reddit cache for '{topic}'...")
        
        search_result = tavily.search(
            query=f"site:reddit.com {topic}", 
            search_depth="advanced", 
            max_results=5, 
            include_raw_content=True # <--- CRITICAL: Get text immediately
        )
        
        threads = search_result.get('results', [])
        
        if not threads:
            return None, log + ["❌ No threads found."]

        # 2. COMPILE TEXT
        combined_text = ""
        valid_count = 0
        
        for t in threads:
            # We prioritize 'raw_content' (Full page cache).
            # If that fails, we use 'content' (Snippet).
            # We DO NOT visit the URL (avoids 403 Forbidden).
            
            source_text = t.get('raw_content')
            source_type = "Full Cache"
            
            if not source_text or len(source_text) < 100:
                source_text = t.get('content')
                source_type = "Snippet"
            
            if source_text:
                combined_text += f"SOURCE: {t['url']}\nTYPE: {source_type}\nCONTENT:\n{source_text[:6000]}\n{'='*40}\n"
                valid_count += 1
                log.append(f"✅ Loaded {source_type}: {t['title'][:30]}...")
            else:
                log.append(f"⚠️ Skipped {t['title'][:30]} (No text)")
            
        if valid_count == 0:
            return None, log + ["❌ Tavily found links but no text data attached."]

        # 3. ANALYZE
        log.append("🧠 Analyzing cached data with Gemini...")
        
        prompt = f"""
        Analyze these Reddit threads about "{topic}".
        
        Goal: Extract specific prices. 
        Note: Data may be messy/raw. Do your best to find numbers.
        
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
        data["sources"] = threads
        
        return data, log + ["✅ Analysis Complete!"]

    except Exception as e:
        return None, log + [f"❌ Error: {str(e)}"]

# --- 5. MAIN UI ---
st.title("🛡️ Reddit Insight (Block-Proof)")
st.markdown("Uses **Tavily's Cached Data** to bypass Reddit's firewalls completely.")

with st.form("search_form"):
    topic_input = st.text_input("Enter Topic:", "Car Insurance Cost Florida")
    submitted = st.form_submit_button("🚀 Mine Insights", type="primary")

if submitted:
    if not (gemini_key and tavily_key):
        st.error("⚠️ Please enter Gemini and Tavily keys.")
    else:
        with st.spinner("Mining data from search cache..."):
            data, logs = run_analysis_cached(topic_input, gemini_key, tavily_key)
            st.session_state.results = data
            st.session_state.status_log = logs

# --- 6. DISPLAY ---
if st.session_state.results:
    data = st.session_state.results
    
    # Math
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

if st.session_state.status_log:
    with st.expander("Processing Logs"):
        for msg in st.session_state.status_log:
            st.write(msg)
