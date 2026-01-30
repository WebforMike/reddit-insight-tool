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
        # PHASE 1: DISCOVERY (Find the URLs)
        # ==========================================
        target_urls = []
        
        if mode == "Search":
            # We use a broad search just to grab the Links.
            # We do NOT filter by content length here anymore.
            queries = [
                f"site:reddit.com {input_data}", 
                f"site:reddit.com {input_data} cost",
                f"site:reddit.com {input_data} quote",
                f"site:reddit.com {input_data} price"
            ]
            
            progress_bar = st.progress(0)
            
            for i, q in enumerate(queries):
                log.append(f"🕵️ Scout Query {i+1}: '{q}'...")
                try:
                    # We just want the URLs, so search_depth="basic" is faster for discovery
                    response = tavily.search(query=q, search_depth="advanced", max_results=5)
                    
                    for item in response.get('results', []):
                        url = item['url']
                        # Basic dedup
                        if url not in target_urls and "reddit.com" in url:
                            target_urls.append(url)
                            
                except Exception as e:
                    log.append(f"⚠️ Search error: {e}")
                
                time.sleep(0.3)
                progress_bar.progress((i + 1) / len(queries))
            
            # Limit to the requested depth
            target_urls = target_urls[:depth]
            log.append(f"🎯 identified {len(target_urls)} promising threads to crawl.")

        elif mode == "Direct URL":
            target_urls = [u.strip() for u in input_data.split(",") if "reddit.com" in u]

        if not target_urls:
            return None, log + ["❌ No Reddit URLs found. Try a broader topic."]

        # ==========================================
        # PHASE 2: HARVESTING (Extract Full Content)
        # ==========================================
        log.append(f"🚜 Crawling {len(target_urls)} threads for deep comments...")
        
        # We explicitly call 'extract' on the URLs we found.
        # This bypasses the "short snippet" issue.
        try:
            # Check if using the extract feature (supports batch)
            extracted_data = tavily.extract(urls=target_urls, include_images=False)
            
            results_list = extracted_data.get('results', [])
            
            for item in results_list:
                url = item['url']
                raw_text = item.get('raw_content', '')
                
                # NOW we check length, but on the full extraction, not the snippet
                if len(raw_text) > 500:
                    final_content_map[url] = {
                        "title": "Reddit Thread", # Extract doesn't always give title, generic is fine
                        "url": url,
                        "content": raw_text
                    }
                else:
                    log.append(f"⚠️ Skipped {url} (Content blocked or empty)")
                    
        except Exception as e:
            log.append(f"⚠️ Extraction Error: {e}")

        valid_thread_count = len(final_content_map)
        if valid_thread_count == 0:
            return None, log + ["❌ Crawled threads, but content was empty/blocked. Reddit might be blocking the bot."]

        log.append(f"✅ Successfully extracted full text from {valid_thread_count} threads.")

        # ==========================================
        # PHASE 3: AI EXTRACTION
        # ==========================================
        combined_text = ""
        for url, data in final_content_map.items():
            combined_text += f"SOURCE_ID: {url}\nCONTENT:\n{data['content'][:20000]}\n{'='*40}\n"

        prompt = f"""
        You are an Expert Data Actuary.
        
        GOAL: Extract insurance pricing data from this raw Reddit text.
        
        STRICT RULES:
        1. **Extract Everything:** If a user mentions a price, I want it. 
        2. **Messy Data is OK:** If they say "$100" but don't say the car, record it as "Unknown Car".
        3. **Context:** Capture the exact quote in "quote_snippet".
        4. **Source:** Map the data back to the 'SOURCE_ID' (URL).
        
        RETURN JSON:
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
        data = json.loads(text_resp)
            
        return data, log + ["✅ AI Analysis Complete!"]

    except Exception as e:
        return None, log + [f"❌ Critical Pipeline Error: {str(e)}"]

# --- MAIN UI ---
st.title("🕷️ Deep Reddit Crawler (Search & Extract)")

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
        
        t1, t2 = st.tabs(["Dashboard", "Raw Data Table"])
        
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
    else:
        st.warning("Pipeline finished, but AI found no price data in the text.")
