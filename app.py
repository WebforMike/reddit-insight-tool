import streamlit as st
import google.generativeai as genai
from tavily import TavilyClient
import json
import re
import os
import time
import pandas as pd
import plotly.express as px
import requests
from bs4 import BeautifulSoup

# --- CONFIG ---
st.set_page_config(page_title="Deep Reddit Analyst (Mirror Mode)", page_icon="🪞", layout="wide")

if "results" not in st.session_state:
    st.session_state.results = None

# --- SIDEBAR ---
with st.sidebar:
    st.header("🔑 API Keys")
    gemini_key = st.secrets.get("GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY") or st.text_input("Gemini Key", type="password")
    tavily_key = st.secrets.get("TAVILY_API_KEY") or os.getenv("TAVILY_API_KEY") or st.text_input("Tavily Key", type="password")
    
    st.divider()
    st.markdown("### ⚙️ Settings")
    search_depth = st.slider("Threads to Scan", 3, 10, 5)

# --- HELPER: MIRROR SCRAPER ---
def scrape_reddit_via_mirrors(url):
    """
    Attempts to scrape Reddit content by swapping the domain
    with public 'Libreddit'/'Redlib' mirrors to bypass blocking.
    """
    # 1. List of public mirrors (These are open source frontends)
    # We try them in order until one works.
    mirrors = [
        "https://r.mnfstr.com", 
        "https://libreddit.bus-hit.me",
        "https://lr.artemislena.eu",
        "https://reddit.invak.id"
    ]
    
    # Extract the path from the original URL (e.g., /r/Hyundai/...)
    if "reddit.com" in url:
        path = url.split("reddit.com")[-1]
    elif "redd.it" in url:
        path = "/" + url.split("redd.it/")[-1]
    else:
        path = url # Assume it's just a path or invalid
        
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    # 2. Try each mirror
    for mirror in mirrors:
        target_link = mirror + path
        try:
            response = requests.get(target_link, headers=headers, timeout=8)
            
            if response.status_code == 200:
                # 3. Success! Parse the HTML
                soup = BeautifulSoup(response.text, 'html.parser')
                
                # Extract Title
                title = soup.find('h1')
                title_text = title.text.strip() if title else "Unknown Title"
                
                # Extract Comments (Libreddit structure is simple)
                comments = []
                # Look for comment bodies (structure varies slightly by instance, broad catch)
                for div in soup.find_all('div', class_='body'):
                    comments.append(div.get_text(strip=True))
                
                # Fallback if class names differ
                if not comments:
                    for p in soup.find_all('p'):
                        if len(p.text) > 50: # Filter short UI text
                            comments.append(p.text.strip())
                            
                full_text = "\n---\n".join(comments)
                
                return {
                    "status": "success", 
                    "content": full_text[:25000], 
                    "mirror_used": mirror,
                    "title": title_text
                }
                
        except Exception:
            continue # Try next mirror
            
    return {"status": "error", "msg": "All mirrors failed or timed out."}

# --- CORE LOGIC ---
def run_analysis(mode, input_data, gemini_k, tavily_k, depth):
    log = []
    final_content_map = {} 
    
    try:
        tavily = TavilyClient(api_key=tavily_k)
        genai.configure(api_key=gemini_k)
        model = genai.GenerativeModel('gemini-2.5-flash') 

        # ==========================================
        # PHASE 1: GATHERING URLS
        # ==========================================
        target_urls = []
        
        if mode == "Search":
            queries = [
                f"site:reddit.com {input_data} price paid",
                f"site:reddit.com {input_data} quote received"
            ]
            
            progress_bar = st.progress(0)
            
            for i, q in enumerate(queries):
                log.append(f"🕵️ Scout Query {i+1}...")
                try:
                    response = tavily.search(query=q, search_depth="basic", max_results=5)
                    # FIX: Handle NoneType if API fails
                    if response and 'results' in response:
                        for item in response['results']:
                            if "reddit.com" in item['url'] and item['url'] not in target_urls:
                                target_urls.append(item['url'])
                    else:
                        log.append(f"⚠️ Query {i+1} returned no data.")
                            
                except Exception as e:
                    log.append(f"⚠️ Search failed: {e}")
                
                time.sleep(0.3)
                progress_bar.progress((i + 1) / len(queries))
            
            # Use top X urls
            target_urls = target_urls[:depth]

        elif mode == "Direct URL":
            target_urls = [u.strip() for u in input_data.split(",") if "reddit.com" in u]

        if not target_urls:
            return None, log + ["❌ No Reddit URLs found."]

        # ==========================================
        # PHASE 2: MIRROR SCRAPING
        # ==========================================
        log.append(f"🪞 Mirroring {len(target_urls)} threads (Bypassing Reddit.com)...")
        
        for url in target_urls:
            res = scrape_reddit_via_mirrors(url)
            
            if res['status'] == 'success':
                final_content_map[url] = res
                log.append(f"✅ Recovered via {res['mirror_used']} ({len(res['content'])} chars)")
            else:
                log.append(f"❌ Failed to mirror {url}")
            
            time.sleep(0.5) # Politeness

        if not final_content_map:
            return None, log + ["❌ All mirrors failed. Reddit is blocking heavily today."]

        # ==========================================
        # PHASE 3: AI EXTRACTION
        # ==========================================
        log.append(f"🧠 Analyzing extracted text...")
        
        combined_text = ""
        for url, data in final_content_map.items():
            combined_text += f"SOURCE_ID: {url}\nTITLE: {data['title']}\nTEXT:\n{data['content']}\n{'='*40}\n"

        prompt = f"""
        You are an Expert Data Actuary. Extract insurance pricing data.
        
        RULES:
        1. **Extract Everything:** Any user mentioning a price/quote/hike.
        2. **Implicit Data:** If user says "$100" but no car model, use "Unknown Model".
        3. **Context:** Copy the exact text into 'quote_snippet'.
        4. **Source:** Map data to 'SOURCE_ID'.
        
        RETURN JSON:
        {{
            "dataset": [
                {{
                    "product_name": "Vehicle Model",
                    "brand": "Insurance Company",
                    "price_monthly": 123,
                    "location": "City/State",
                    "quote_snippet": "exact quote",
                    "source_url": "SOURCE_ID",
                    "sentiment": "Positive/Negative/Neutral"
                }}
            ],
            "market_summary": "Summary.",
            "recommendation": "Tip."
        }}
        
        DATA:
        {combined_text}
        """
        
        response = model.generate_content(prompt)
        text_resp = response.text.replace("```json", "").replace("```", "").strip()
        
        try:
            data = json.loads(text_resp)
            data['raw_debug'] = combined_text 
        except:
            return None, log + ["❌ AI output was not valid JSON."]
            
        return data, log + ["✅ AI Analysis Complete!"]

    except Exception as e:
        return None, log + [f"❌ Critical Pipeline Error: {str(e)}"]

# --- MAIN UI ---
st.title("🪞 Deep Reddit Analyst (Mirror Mode)")
st.markdown("Bypasses Reddit blocking by routing requests through public 'Libreddit' mirrors.")

tab_search, tab_direct = st.tabs(["🔎 Search Mode", "🔗 Direct URL Mode"])

with tab_search:
    with st.form("search_form"):
        topic_input = st.text_input("Enter Topic", "Hyundai Car Insurance")
        submit_search = st.form_submit_button("🚀 Run Auto-Search")

with tab_direct:
    with st.form("direct_form"):
        url_input = st.text_area("Paste Reddit URLs", "https://www.reddit.com/r/Hyundai/comments/1l1mxlz/insurance_cost/")
        submit_direct = st.form_submit_button("🪞 Run Mirror Scrape")

if (submit_search or submit_direct) and gemini_key:
    mode = "Search" if submit_search else "Direct URL"
    input_data = topic_input if submit_search else url_input
    
    with st.status(f"🤖 Processing {mode}...", expanded=True) as status:
        data, logs = run_analysis(mode, input_data, gemini_key, tavily_key, search_depth)
        for l in logs: st.write(l)
        
        if data:
            st.session_state.results = data
            status.update(label="✅ Success!", state="complete", expanded=False)

# --- RESULTS ---
if st.session_state.results:
    data = st.session_state.results
    if "dataset" in data and data["dataset"]:
        df = pd.DataFrame(data["dataset"])
        df['price_monthly'] = pd.to_numeric(df['price_monthly'], errors='coerce').fillna(0)
        df.fillna("Unknown", inplace=True)

        st.divider()
        st.header("📊 Extraction Results")
        
        t1, t2, t3, t4 = st.tabs(["Dashboard", "Raw Data", "Insights", "🕷️ Debug Text"])
        
        with t1:
            valid = df[df['price_monthly'] > 0]
            k1, k2 = st.columns(2)
            k1.metric("Data Points", len(df))
            if not valid.empty:
                k2.metric("Median Price", f"${int(valid['price_monthly'].median())}")
                st.subheader("Price Distribution")
                st.plotly_chart(px.bar(valid, x='price_monthly', y='brand', orientation='h', color='price_monthly'), use_container_width=True)
            else:
                k2.metric("Median Price", "N/A")
                st.warning("No numeric prices found.")

        with t2:
            st.dataframe(
                df[['brand', 'price_monthly', 'product_name', 'location', 'quote_snippet', 'source_url']], 
                use_container_width=True,
                column_config={"source_url": st.column_config.LinkColumn("Source")}
            )
            
        with t3:
             st.info(data.get("market_summary"))
             st.success(data.get("recommendation"))

        with t4:
            st.text_area("Raw Content Read by AI", value=data.get('raw_debug', 'No debug info'), height=400)

    else:
        st.warning("Pipeline finished, but AI found no price data.")
