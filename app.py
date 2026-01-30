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
st.set_page_config(page_title="Reddit Insight Pro", page_icon="🧠", layout="wide")

# --- 2. SIDEBAR: API KEYS ---
with st.sidebar:
    st.header("🔑 API Keys")
    
    gemini_key = st.secrets.get("GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY")
    if not gemini_key:
        gemini_key = st.text_input("Gemini API Key", type="password")

    tavily_key = st.secrets.get("TAVILY_API_KEY") or os.getenv("TAVILY_API_KEY")
    if not tavily_key:
        tavily_key = st.text_input("Tavily API Key", type="password")

# --- 3. HELPER FUNCTION: ROBUST FETCHING ---
def fetch_content_hybrid(url, fallback_text=None):
    """
    Attempts to fetch high-quality JSON from Reddit.
    If blocked (429/403), falls back to the text Tavily found.
    """
    # PLAN A: Try Direct JSON (Best Quality)
    try:
        clean_url = url.split('?')[0].rstrip('/')
        json_url = f"{clean_url}.json?sort=top"

        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Referer': 'https://www.google.com/'
        }

        # Short timeout to fail fast if blocked
        response = requests.get(json_url, headers=headers, timeout=5)
        
        if response.status_code == 200:
            data = response.json()
            # Parse Main Post
            post = data[0]['data']['children'][0]['data']
            content = f"--- THREAD: {post.get('title', 'Unknown')} ---\n"
            content += f"SCORE: {post.get('score', 0)}\n"
            content += f"BODY: {post.get('selftext', '')[:1000]}\n"
            content += "--- BEST COMMENTS ---\n"
            
            # Parse Comments
            comments = data[1]['data']['children']
            for c in comments[:15]:
                d = c.get('data', {})
                if d.get('author') not in ['[deleted]', 'AutoModerator']:
                    content += f"[Score: {d.get('score',0)}] {d.get('body', '')[:600]}\n\n"
            
            return content, "Direct"

    except Exception as e:
        pass # Plan A failed, proceed to Plan B

    # PLAN B: Use Tavily's Backup Text (Reliable)
    if fallback_text:
        # Clean up the fallback text a bit
        clean_fallback = fallback_text[:2500] # Limit length
        return f"--- SOURCE (TAVILY BACKUP) ---\nURL: {url}\nCONTENT: {clean_fallback}", "Backup"
    
    return None, "Failed"

# --- 4. MAIN APP UI ---
st.title("🧠 Reddit Insight Miner (Anti-Block Version)")
st.markdown("Finds threads and calculates market statistics. Includes **Cloud-Bypass** technology.")

topic = st.text_input("Enter Topic:", "Car Insurance Cost Florida")

if st.button("🚀 Mine Insights", type="primary"):
    
    if not (gemini_key and tavily_key):
        st.error("⚠️ Please enter both API Keys in the sidebar.")
        st.stop()

    try:
        tavily = TavilyClient(api_key=tavily_key)
        genai.configure(api_key=gemini_key)
        model = genai.GenerativeModel('gemini-2.0-flash') 
    except Exception as e:
        st.error(f"Setup Error: {e}")
        st.stop()

    # Step A: Search
    status = st.status("🕵️ Searching...", expanded=True)
    try:
        # CRITICAL: We ask Tavily for 'include_raw_content' so we have a backup if Reddit blocks us
        search_result = tavily.search(
            query=f"site:reddit.com {topic}", 
            search_depth="advanced", 
            max_results=5,
            include_raw_content=True 
        )
        threads = search_result.get('results', [])
        
        if not threads:
            status.update(label="❌ No threads found.", state="error")
            st.stop()
            
        status.write(f"✅ Found {len(threads)} threads. fetching details...")
    except Exception as e:
        st.error(f"Search failed: {e}")
        st.stop()

    # Step B: Hybrid Fetch
    combined_context = ""
    valid_count = 0
    direct_hits = 0
    backup_hits = 0
    
    progress = st.progress(0)
    
    for i, t in enumerate(threads):
        status.write(f"Reading: {t['title'][:30]}...")
        
        # We pass BOTH the url and the raw_content Tavily found
        text, method = fetch_content_hybrid(t['url'], t.get('raw_content'))
        
        if text:
            combined_context += f"{text}\n{'='*40}\n"
            valid_count += 1
            if method == "Direct": direct_hits += 1
            else: backup_hits += 1
        
        # Be nice to the API
        time.sleep(0.5)
        progress.progress((i + 1) / len(threads))

    if valid_count == 0:
        status.update(label="❌ All access blocked.", state="error")
        st.error("Could not read any data. Reddit is blocking both direct access and search crawlers.")
        st.stop()

    status.write(f"✅ Read {valid_count} threads ({direct_hits} Direct, {backup_hits} Backup).")

    # Step C: Analyze
    status.write("🧠 Extracting statistics...")
    
    prompt = f"""
    You are a Data Extractor. Analyze these Reddit threads about "{topic}".
    
    Your ONLY goal is to extract specific price numbers mentioned by users so we can calculate statistics.
    Ignore generic advice. Focus on hard numbers.
    
    Return ONLY a raw JSON object with these keys:
    - "raw_prices": (list of integers) Every single price mentioned (e.g. [120, 150, 300]). Convert "$1.2k" to 1200. Ignore outliers like "$0" or "$1,000,000".
    - "sentiment": (string) "Positive", "Negative", or "Neutral".
    - "summary": (string) Brief summary of the pricing consensus.
    - "currency": (string) The currency symbol usually used (e.g. "$").

    DATA:
    {combined_context}
    """
    
    try:
        response = model.generate_content(prompt)
        cleaned_json = re.sub(r"```json|```", "", response.text).strip()
        data = json.loads(cleaned_json)
        
        # Python Math
        raw_prices = data.get("raw_prices", [])
        stats = {}
        if raw_prices:
            stats['min'] = min(raw_prices)
            stats['max'] = max(raw_prices)
            stats['avg'] = int(statistics.mean(raw_prices))
            stats['median'] = int(statistics.median(raw_prices))
            stats['count'] = len(raw_prices)
        else:
            stats = {'min': 0, 'max': 0, 'avg': 0, 'median': 0, 'count': 0}

        status.update(label="✅ Success!", state="complete", expanded=False)
        
        # Step D: Display
        st.divider()
        st.header(f"🧮 Market Report: {topic}")
        
        c1, c2, c3, c4 = st.columns(4)
        currency = data.get("currency", "$")
        
        c1.metric("Average", f"{currency}{stats['avg']}")
        c2.metric("Median", f"{currency}{stats['median']}")
        c3.metric("Lowest", f"{currency}{stats['min']}")
        c4.metric("Highest", f"{currency}{stats['max']}")
        
        st.caption(f"Calculated from {stats['count']} data points.")
        
        st.subheader("📝 Summary")
        st.write(data.get("summary"))
        
        if backup_hits > 0:
            st.warning(f"Note: {backup_hits} threads were read using Backup Mode (Reddit blocked direct access). Data may be less detailed.")

        with st.expander("See Raw Data & Sources"):
            st.write(f"Prices used: {raw_prices}")
            for t in threads:
                st.markdown(f"- [{t['title']}]({t['url']})")

    except Exception as e:
        status.update(label="❌ AI Error", state="error")
        st.error(f"Error: {e}")
