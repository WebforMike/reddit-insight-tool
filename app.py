import streamlit as st
import google.generativeai as genai
from tavily import TavilyClient
import json
import re
import os
import time
import pandas as pd
import plotly.express as px

# --- CONFIG ---
st.set_page_config(page_title="Deep Reddit Crawler", page_icon="🕷️", layout="wide")

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

# --- CORE LOGIC ---
def run_analysis(mode, input_data, gemini_k, tavily_k, depth):
    log = []
    final_content_map = {} # Url -> Content
    
    try:
        tavily = TavilyClient(api_key=tavily_k)
        genai.configure(api_key=gemini_k)
        model = genai.GenerativeModel('gemini-2.5-flash') 

        # ==========================================
        # PHASE 1: INTELLIGENT GATHERING
        # ==========================================
        target_urls = []
        
        if mode == "Search":
            # BROAD DISCOVERY
            queries = [
                f"site:reddit.com {input_data}", 
                f"site:reddit.com {input_data} price paid",
                f"site:reddit.com {input_data} quote received"
            ]
            
            progress_bar = st.progress(0)
            
            for i, q in enumerate(queries):
                log.append(f"🕵️ Scout Query {i+1}: '{q}'...")
                try:
                    # We grab raw content immediately here as a backup
                    response = tavily.search(query=q, search_depth="advanced", max_results=5, include_raw_content=True)
                    
                    for item in response.get('results', []):
                        url = item['url']
                        content = item.get('raw_content', '')
                        
                        if url not in final_content_map and len(content) > 500:
                            final_content_map[url] = {
                                "title": item['title'],
                                "url": url,
                                "content": content
                            }
                            
                except Exception as e:
                    log.append(f"⚠️ Search error: {e}")
                
                time.sleep(0.3)
                progress_bar.progress((i + 1) / len(queries))

        elif mode == "Direct URL":
            # HYBRID CRAWL STRATEGY
            urls = [u.strip() for u in input_data.split(",") if "reddit.com" in u]
            log.append(f"🕷️ Attempting to crawl {len(urls)} links...")
            
            for url in urls:
                # STRATEGY A: Direct Extraction (Best quality, but risky)
                crawled_content = ""
                try:
                    response = tavily.extract(urls=[url], include_images=False)
                    raw_res = response.get('results', [])[0]
                    crawled_content = raw_res.get('raw_content', '')
                except:
                    pass

                # CHECK: Did we get blocked?
                if len(crawled_content) < 600 or "Whoops" in crawled_content:
                    log.append(f"⚠️ Direct crawl blocked for {url}. Switching to Cache Search...")
                    
                    # STRATEGY B: Search Cache Bypass (Reliable)
                    try:
                        # Search specifically for this URL to find the cached snippet
                        search_res = tavily.search(query=url, search_depth="advanced", max_results=1, include_raw_content=True)
                        if search_res.get('results'):
                            crawled_content = search_res['results'][0].get('raw_content', '')
                            log.append(f"✅ Recovered content via Cache ({len(crawled_content)} chars)")
                        else:
                             log.append(f"❌ Cache failed for {url}")
                    except Exception as e:
                        log.append(f"❌ Recovery failed: {e}")
                else:
                    log.append(f"✅ Direct crawl success ({len(crawled_content)} chars)")

                if len(crawled_content) > 300:
                    final_content_map[url] = {
                        "title": "Direct Import",
                        "url": url,
                        "content": crawled_content
                    }

        if not final_content_map:
            return None, log + ["❌ No accessible text found. Reddit likely blocked all attempts."]

        # ==========================================
        # PHASE 2: "MESSY DATA" EXTRACTION
        # ==========================================
        log.append(f"🧠 Analyzing {len(final_content_map)} threads with Gemini 2.0...")
        
        combined_text = ""
        for url, data in final_content_map.items():
            combined_text += f"SOURCE_ID: {url}\nCONTENT:\n{data['content'][:25000]}\n{'='*40}\n"

        prompt = f"""
        You are an Expert Data Actuary.
        
        GOAL: Extract insurance pricing data from this raw Reddit text.
        
        STRICT RULES:
        1. **Extract Everything:** If a user mentions a price, I want it. 
        2. **Messy Data is OK:** If they say "$100" but don't say the car, record it as "Unknown Car".
        3. **Context:** Capture the exact quote in "quote_snippet".
        4. **Source:** Map the data back to the 'SOURCE_ID' (URL).
        
        RETURN JSON ONLY:
        {{
            "dataset": [
                {{
                    "product_name": "Vehicle Model (or 'Unknown')",
                    "brand": "Insurance Company (or 'Unknown')",
                    "price_monthly": 123,
                    "location": "City/State (or 'Unknown')",
                    "quote_snippet": "The text proving the price",
                    "source_url": "The SOURCE_ID",
                    "sentiment": "Positive/Negative/Neutral"
                }}
            ],
            "market_summary": "Brief summary.",
            "recommendation": "One tip."
        }}
        
        DATA:
        {combined_text}
        """
        
        response = model.generate_content(prompt)
        text_resp = response.text.replace("```json", "").replace("```", "").strip()
        
        # Save raw debug text for the user to see
        raw_debug_text = combined_text
        
        try:
            data = json.loads(text_resp)
            # Attach debug text to data object for UI
            data['raw_debug'] = raw_debug_text 
        except:
            return None, log + ["❌ AI output was not valid JSON."]
            
        return data, log + ["✅ AI Analysis Complete!"]

    except Exception as e:
        return None, log + [f"❌ Critical Pipeline Error: {str(e)}"]

# --- MAIN UI ---
st.title("🕷️ Deep Reddit Crawler (Anti-Block)")

tab_search, tab_direct = st.tabs(["🔎 Auto-Search", "🔗 Direct Link"])

with tab_search:
    with st.form("search_form"):
        topic_input = st.text_input("Enter Topic", "Hyundai Car Insurance")
        submit_search = st.form_submit_button("🚀 Run Auto-Search")

with tab_direct:
    with st.form("direct_form"):
        url_input = st.text_area("Paste Reddit URLs", "https://www.reddit.com/r/Hyundai/comments/1l1mxlz/insurance_cost/")
        submit_direct = st.form_submit_button("🕷️ Run Direct Crawl")

if (submit_search or submit_direct) and gemini_key and tavily_key:
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
        
        t1, t2, t3, t4 = st.tabs(["Dashboard", "Raw Data Table", "Insights", "🕷️ Debug View"])
        
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
                st.warning("Prices mentioned were not numeric or only sentiment was found.")

        with t2:
            st.dataframe(
                df[['brand', 'price_monthly', 'product_name', 'location', 'quote_snippet', 'source_url']], 
                use_container_width=True,
                column_config={"source_url": st.column_config.LinkColumn("Source")}
            )
            
        with t3:
             st.info(data.get("market_summary"))
             st.success(data.get("recommendation"))

        # --- DEBUG TAB ---
        with t4:
            st.markdown("### 🕵️‍♂️ Audit: What did the AI actually read?")
            st.warning("This is the raw text extracted. If this is 'Whoops' or empty, Reddit blocked the crawler.")
            st.text_area("Raw Content", value=data.get('raw_debug', 'No debug info'), height=400)

    else:
        st.warning("Pipeline finished, but AI found no price data in the text.")
