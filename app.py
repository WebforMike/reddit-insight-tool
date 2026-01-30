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
    search_depth = st.slider("Threads to Scan (Search Mode)", 3, 15, 7)

# --- CORE LOGIC ---
def run_analysis(mode, input_data, gemini_k, tavily_k):
    log = []
    all_threads = {}
    
    try:
        tavily = TavilyClient(api_key=tavily_k)
        genai.configure(api_key=gemini_k)
        model = genai.GenerativeModel('gemini-2.5-flash') 

        # === STEP 1: GATHER CONTENT ===
        if mode == "Search":
            # BROAD SEARCH to catch Megathreads
            queries = [
                f"site:reddit.com {input_data}",  # The Base Term (Most important)
                f"site:reddit.com {input_data} price paid",
                f"site:reddit.com {input_data} quote renewal"
            ]
            
            progress_bar = st.progress(0)
            for i, q in enumerate(queries):
                log.append(f"🕵️ Search Query {i+1}: '{q}'...")
                try:
                    # include_raw_content=True is VITAL
                    response = tavily.search(query=q, search_depth="advanced", max_results=5, include_raw_content=True)
                    for item in response.get('results', []):
                        if item['url'] not in all_threads and item.get('raw_content'):
                            all_threads[item['url']] = {
                                "title": item['title'],
                                "url": item['url'],
                                "content": item['raw_content']
                            }
                except Exception as e:
                    log.append(f"⚠️ Search failed: {e}")
                time.sleep(0.5)
                progress_bar.progress((i + 1) / len(queries))

        elif mode == "Direct URL":
            # DEEP CRAWLER strategy
            urls = [u.strip() for u in input_data.split(",")]
            log.append(f"🕷️ Crawling {len(urls)} specific URLs...")
            
            for url in urls:
                if "reddit.com" in url:
                    try:
                        # 'extract' grabs the FULL page, not just a snippet
                        response = tavily.extract(urls=[url], include_images=False)
                        
                        # Tavily extract result structure handling
                        extract_results = response.get('results', [])
                        
                        if extract_results:
                            for item in extract_results:
                                raw_text = item.get('raw_content', '')
                                if len(raw_text) < 500:
                                    log.append(f"⚠️ Warning: Extracted text for {url} is very short ({len(raw_text)} chars). Content might be blocked.")
                                
                                all_threads[url] = {
                                    "title": "Direct URL Import",
                                    "url": url,
                                    "content": raw_text
                                }
                                log.append(f"✅ Successfully crawled: {url} ({len(raw_text)} chars)")
                        else:
                             log.append(f"❌ Crawl failed (No data returned): {url}")
                             
                    except Exception as e:
                        log.append(f"❌ Failed to crawl {url}: {e}")

        if not all_threads:
            return None, log + ["❌ No content found. If pasting URLs, ensure they are valid."]

        # === STEP 2: PREPARE DATA ===
        log.append(f"✅ Processing {len(all_threads)} threads...")
        combined_text = ""
        for t in all_threads.values():
            combined_text += f"SOURCE_ID: {t['url']}\nTITLE: {t['title']}\nCONTENT:\n{t['content'][:30000]}\n{'='*40}\n"

        # === STEP 3: "MESSY DATA" EXTRACTION ===
        # The prompt is now permissive ("Quantity over Perfection")
        prompt = f"""
        You are a Data Scraper. Your job is to extract insurance pricing data from Reddit threads.
        
        CRITICAL RULES:
        1. **Quantity over Perfection:** Extract EVERY price mention, even if the user didn't say their car model or location.
        2. **Partial Data:** If "Car Model" is missing, fill it with "Unknown Model". If "Location" is missing, fill with "Unknown".
        3. **Context:** Capture the "quote_snippet" so we can see what they said.
        4. **Source Mapping:** You MUST map the 'source_url' to the 'SOURCE_ID' provided in the text.
        
        RETURN JSON ONLY:
        {{
            "dataset": [
                {{
                    "product_name": "Vehicle Model (or 'Unknown')",
                    "brand": "Insurance Company (or 'Unknown')",
                    "price_monthly": 123,
                    "location": "City/State (or 'Unknown')",
                    "quote_snippet": "The exact text where they said it",
                    "source_url": "The exact SOURCE_ID url",
                    "sentiment": "Positive/Negative/Neutral"
                }}
            ],
            "market_summary": "Summary of the market consensus.",
            "recommendation": "1 actionable tip."
        }}
        
        DATA TO MINE:
        {combined_text}
        """
        
        response = model.generate_content(prompt)
        text_resp = response.text.replace("```json", "").replace("```", "").strip()
        
        try:
            data = json.loads(text_resp)
        except:
            return None, log + ["❌ AI Response was not valid JSON. Try again."]
            
        return data, log + ["✅ Extraction Complete!"]

    except Exception as e:
        return None, log + [f"❌ Error: {str(e)}"]

# --- MAIN UI ---
st.title("🕷️ Deep Reddit Crawler")
st.markdown("Extract pricing data via **Search** OR **Direct URL** (for maximum accuracy).")

# TABS FOR INPUT METHOD
tab_search, tab_direct = st.tabs(["🔎 Search Mode", "🔗 Direct URL Crawler"])

with tab_search:
    with st.form("search_form"):
        topic_input = st.text_input("Enter Topic", "Hyundai Car Insurance")
        submit_search = st.form_submit_button("🚀 Run Search Analysis")

with tab_direct:
    with st.form("direct_form"):
        url_input = st.text_area("Paste Reddit URLs (comma separated)", "https://www.reddit.com/r/Hyundai/comments/1l1mxlz/insurance_cost/")
        submit_direct = st.form_submit_button("🕷️ Run Crawler Analysis")

# EXECUTION LOGIC
if (submit_search or submit_direct) and gemini_key and tavily_key:
    mode = "Search" if submit_search else "Direct URL"
    input_data = topic_input if submit_search else url_input
    
    with st.status(f"🤖 Running {mode} Analysis...", expanded=True) as status:
        data, logs = run_analysis(mode, input_data, gemini_key, tavily_key)
        for l in logs: st.write(l)
        
        if data:
            st.session_state.results = data
            status.update(label="✅ Done!", state="complete", expanded=False)

# --- RESULTS DISPLAY ---
if st.session_state.results:
    data = st.session_state.results
    
    if "dataset" in data and data["dataset"]:
        df = pd.DataFrame(data["dataset"])
        
        # CLEANING: Handle messy data
        df['price_monthly'] = pd.to_numeric(df['price_monthly'], errors='coerce').fillna(0)
        df.fillna("Unknown", inplace=True)

        st.divider()
        st.header("📊 Extraction Results")

        t1, t2, t3, t4 = st.tabs(["Dashboard", "Raw Data", "Insights", "🕷️ Debug: Raw Text"])

        with t1:
            valid = df[df['price_monthly'] > 0]
            k1, k2, k3 = st.columns(3)
            k1.metric("Data Points", len(df))
            if not valid.empty:
                k2.metric("Median Price", f"${int(valid['price_monthly'].median())}")
                k3.metric("Max Price", f"${int(valid['price_monthly'].max())}")
            
            if not valid.empty:
                st.subheader("💰 Price Distribution by Brand")
                fig = px.scatter(valid, x="brand", y="price_monthly", color="sentiment", size="price_monthly", hover_data=["product_name", "location"])
                st.plotly_chart(fig, use_container_width=True)

        with t2:
            st.markdown("### 🔍 Granular Data")
            st.dataframe(
                df[['brand', 'price_monthly', 'product_name', 'location', 'quote_snippet', 'source_url']],
                use_container_width=True,
                column_config={"source_url": st.column_config.LinkColumn("Source")}
            )

        with t3:
            st.info(data.get("market_summary"))
            st.success(data.get("recommendation"))

        # --- NEW DEBUG TAB ---
        with t4:
            st.markdown("### 🕵️‍♂️ Audit: What did the AI actually read?")
            st.warning("This is the raw text extracted from the URL. If this is empty or short, the scraping failed.")
            st.text_area("Raw Extracted Content", value=str(st.session_state.results).get('raw_debug', 'Raw text not saved to session state (check logs)'), height=400)
    else:
        st.warning("⚠️ Analysis ran, but no specific data points could be extracted.")
