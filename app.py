import streamlit as st
import google.generativeai as genai
import requests
import json
import re
import os
from duckduckgo_search import DDGS

# --- CONFIG ---
st.set_page_config(page_title="Reddit Insight (No Keys)", page_icon="🕵️", layout="wide")
st.title("🕵️ Reddit Insight Extractor")
st.markdown("### specific insights without needing Reddit API keys.")

# --- SIDEBAR: ONLY GEMINI KEY NEEDED ---
# We check Streamlit secrets first, then environment variables, then sidebar
gemini_key = st.secrets.get("GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY")

if not gemini_key:
    with st.sidebar:
        st.warning("⚠️ Google Gemini Key missing.")
        gemini_key = st.text_input("Enter Gemini API Key", type="password")
        st.markdown("[Get a Key Here](https://aistudio.google.com/app/apikey)")

# --- FUNCTIONS ---
def search_reddit(topic):
    """Finds Reddit URLs using DuckDuckGo to bypass Reddit Search API"""
    with DDGS() as ddgs:
        # Search specifically on reddit.com
        query = f"site:reddit.com {topic}"
        results = list(ddgs.text(query, max_results=5))
    return results

def get_thread_data(url):
    """Fetches thread data by appending .json to the URL"""
    try:
        # We must use a browser-like User-Agent or Reddit blocks the request
        headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
        
        # Ensure URL ends in .json
        clean_url = url.split('?')[0] # Remove existing query params
        if not clean_url.endswith('.json'):
            json_url = f"{clean_url}.json"
        else:
            json_url = clean_url
            
        response = requests.get(json_url, headers=headers, timeout=10)
        
        if response.status_code != 200:
            return None
            
        data = response.json()
        
        # Reddit JSON is a list: [0] is the post, [1] is the comments
        post_data = data[0]['data']['children'][0]['data']
        comments_data = data[1]['data']['children']
        
        # Extract Post
        text = f"Title: {post_data.get('title', '')}\n"
        text += f"Body: {post_data.get('selftext', '')[:800]}\n" # Truncate body
        
        # Extract Top 5 Comments
        text += "--- Comments ---\n"
        count = 0
        for comment in comments_data:
            if count >= 5: break
            if 'data' in comment and 'body' in comment['data']:
                text += f"- {comment['data']['body'][:300]}\n"
                count += 1
                
        return text
    except Exception as e:
        print(f"Error fetching {url}: {e}")
        return None

# --- MAIN UI ---
topic = st.text_input("Enter a topic (or paste a specific Reddit link):", "Car Insurance Cost Florida")

if st.button("Analyze", type="primary"):
    if not gemini_key:
        st.error("Please enter your Gemini API Key in the sidebar.")
        st.stop()

    genai.configure(api_key=gemini_key)
    model = genai.GenerativeModel('gemini-1.5-flash')
    
    status = st.empty()
    status.info("🔍 Searching for threads...")
    
    # 1. Get URLs (either from search or direct input)
    urls_to_scrape = []
    if "reddit.com" in topic:
        urls_to_scrape = [{'href': topic, 'title': 'Direct Link'}]
    else:
        results = search_reddit(topic)
        urls_to_scrape = results

    if not urls_to_scrape:
        status.error("No Reddit threads found for that topic.")
        st.stop()

    # 2. Scrape Data
    combined_text = ""
    threads_read = 0
    
    progress_bar = st.progress(0)
    
    for i, item in enumerate(urls_to_scrape):
        url = item.get('href', item.get('link')) # DDG sometimes uses 'href', sometimes 'link'
        status.write(f"Reading: {item.get('title', 'Thread')}...")
        
        content = get_thread_data(url)
        if content:
            combined_text += f"\nSOURCE: {url}\n{content}\n{'='*20}\n"
            threads_read += 1
        
        progress_bar.progress((i + 1) / len(urls_to_scrape))

    if threads_read == 0:
        status.error("Could not read any threads (Reddit might be rate-limiting). Try again in a minute.")
        st.stop()

    # 3. Analyze with AI
    status.info(f"🧠 Analyzing {threads_read} threads with Gemini...")
    
    prompt = f"""
    Analyze these Reddit discussions about "{topic}".
    Return ONLY a raw JSON object with these keys:
    - "summary": (string) Consensus summary.
    - "avg_price": (string) Price estimates mentioned.
    - "sentiment": (string) Positive/Negative/Neutral.
    - "pain_points": (list) Top 3 user complaints.
    - "key_quote": (string) Best quote.

    Data:
    {combined_text}
    """
    
    try:
        response = model.generate_content(prompt)
        cleaned_json = re.sub(r"```json|```", "", response.text).strip()
        data = json.loads(cleaned_json)
        
        status.empty()
        progress_bar.empty()
        
        st.success("Analysis Complete!")
        
        # Metrics
        c1, c2, c3 = st.columns(3)
        c1.metric("Sentiment", data.get("sentiment", "N/A"))
        c2.metric("Price Est.", data.get("avg_price", "N/A"))
        c3.metric("Threads Read", threads_read)
        
        st.divider()
        st.subheader("📝 Summary")
        st.write(data.get("summary"))
        
        st.subheader("😤 Pain Points")
        for p in data.get("pain_points", []):
            st.markdown(f"- {p}")
            
        st.info(f"**Key Quote:** \"{data.get('key_quote')}\"")
        
        with st.expander("See Raw Data"):
            st.text(combined_text)

    except Exception as e:
        st.error(f"AI Analysis failed: {e}")
