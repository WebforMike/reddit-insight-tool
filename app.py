import streamlit as st
import google.generativeai as genai
from tavily import TavilyClient
import requests
import json
import re
import os
import statistics

# --- 1. PAGE CONFIGURATION ---
st.set_page_config(page_title="Reddit Insight Pro", page_icon="🧠", layout="wide")

# --- 2. SIDEBAR: API KEYS ---
with st.sidebar:
    st.header("🔑 API Keys")
    
    # Try to load from Streamlit Secrets or Environment Variables first
    gemini_key = st.secrets.get("GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY")
    if not gemini_key:
        gemini_key = st.text_input("Gemini API Key", type="password")
        if not gemini_key:
            st.info("Get a free key at aistudio.google.com")

    tavily_key = st.secrets.get("TAVILY_API_KEY") or os.getenv("TAVILY_API_KEY")
    if not tavily_key:
        tavily_key = st.text_input("Tavily API Key", type="password")
        if not tavily_key:
            st.info("Get a free key at tavily.com")

# --- 3. HELPER FUNCTION: FETCH REDDIT DATA ---
def fetch_smart_reddit_content(url):
    """
    Fetches Reddit data, sorts by 'Top' to get best answers, 
    and filters out bots/spam before sending to AI.
    """
    try:
        # Clean URL and force JSON + Sort by Top
        clean_url = url.split('?')[0].rstrip('/')
        if "reddit.com" not in clean_url: return None
        json_url = f"{clean_url}.json?sort=top"

        # Fake Browser Headers (Crucial to avoid 429 errors)
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }

        response = requests.get(json_url, headers=headers, timeout=10)
        if response.status_code != 200:
            return None

        data = response.json()
        
        # Parse Main Post
        post_data = data[0]['data']['children'][0]['data']
        content = f"--- THREAD START ---\n"
        content += f"TITLE: {post_data.get('title', 'Unknown')}\n"
        content += f"SCORE: {post_data.get('score', 0)}\n"
        content += f"BODY: {post_data.get('selftext', '')[:1000]}\n"
        content += "--- TOP COMMENTS ---\n"

        # Parse Comments (Filter bots & low quality)
        comments_data = data[1]['data']['children']
        for i, c in enumerate(comments_data[:15]): # Top 15 comments
            comment = c.get('data', {})
            author = comment.get('author', '[deleted]')
            
            # Skip bots and deleted comments
            if author.lower() in ['automoderator', '[deleted]', '[removed]']:
                continue
            if comment.get('stickied'): 
                continue
                
            content += f"[Comment] [Score: {comment.get('score', 0)}] {comment.get('body', '')[:800]}\n\n"
            
        return content

    except Exception as e:
        print(f"Error reading {url}: {e}")
        return None

# --- 4. MAIN APP UI ---
st.title("🧠 Reddit Insight Miner (Pro)")
st.markdown("Enter a topic. The AI will find threads, extract raw data, and calculate real statistics.")

topic = st.text_input("Enter Topic:", "Car Insurance Cost Florida")

if st.button("🚀 Mine Insights", type="primary"):
    
    # Validation
    if not (gemini_key and tavily_key):
        st.error("⚠️ Please enter both API Keys in the sidebar to proceed.")
        st.stop()

    # Initialize Clients
    try:
        tavily = TavilyClient(api_key=tavily_key)
        genai.configure(api_key=gemini_key)
        model = genai.GenerativeModel('gemini-2.0-flash') # Using the model we confirmed works
    except Exception as e:
        st.error(f"Connection Error: {e}")
        st.stop()

    # Step A: Search
    status = st.status("🕵️ Searching Reddit...", expanded=True)
    try:
        # Search specifically on reddit.com
        search_result = tavily.search(
            query=f"site:reddit.com {topic}", 
            search_depth="advanced", 
            max_results=5
        )
        threads = search_result.get('results', [])
        
        if not threads:
            status.update(label="❌ No threads found", state="error")
            st.stop()
            
        status.write(f"✅ Found {len(threads)} threads. Scraping content...")
    except Exception as e:
        st.error(f"Search failed: {e}")
        st.stop()

    # Step B: Scrape Content
    combined_context = ""
    valid_count = 0
    progress = st.progress(0)
    
    for i, t in enumerate(threads):
        status.write(f"Reading: {t['title'][:40]}...")
        raw_text = fetch_smart_reddit_content(t['url'])
        
        if raw_text:
            combined_context += f"SOURCE URL: {t['url']}\n{raw_text}\n{'='*40}\n"
            valid_count += 1
        
        progress.progress((i + 1) / len(threads))

    if valid_count == 0:
        status.update(label="❌ Reddit blocked access to all threads.", state="error")
        st.stop()

    # Step C: Analyze & Calculate
    status.write("🧠 AI Extracting data & Python calculating stats...")
    
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
        
        # PYTHON MATH SECTION
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

        status.update(label="✅ Analysis Complete!", state="complete", expanded=False)
        
        # Step D: Dashboard Display
        st.divider()
        st.header(f"🧮 Market Report: {topic}")
        
        # 1. Top Metrics
        c1, c2, c3, c4 = st.columns(4)
        currency = data.get("currency", "$")
        
        c1.metric("Average Price", f"{currency}{stats['avg']}")
        c2.metric("Median Price", f"{currency}{stats['median']}")
        c3.metric("Lowest Found", f"{currency}{stats['min']}")
        c4.metric("Highest Found", f"{currency}{stats['max']}")
        
        st.caption(f"Calculated from {stats['count']} data points found in discussion.")
        
        # 2. Summary & Sentiment
        st.subheader("📝 Analysis")
        st.write(data.get("summary"))
        st.info(f"Overall Sentiment: **{data.get('sentiment')}**")

        # 3. Transparency (Raw Data)
        with st.expander("See raw numbers used for calculation"):
            st.write(f"Extracted Prices: {raw_prices}")
            
        with st.expander("See Sources"):
            for t in threads:
                st.markdown(f"- [{t['title']}]({t['url']})")

    except Exception as e:
        status.update(label="❌ Error", state="error")
        st.error(f"Analysis Error: {e}")
