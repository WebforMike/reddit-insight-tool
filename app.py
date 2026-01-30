import streamlit as st
import google.generativeai as genai
from tavily import TavilyClient
import json
import re
import os
import time
import pandas as pd
import plotly.express as px  # <--- THIS WAS MISSING CAUSING THE ERROR

# --- CONFIG ---
st.set_page_config(page_title="Deep Reddit Market Analyst", page_icon="🕵️‍♂️", layout="wide")

if "results" not in st.session_state:
    st.session_state.results = None

# --- SIDEBAR ---
with st.sidebar:
    st.header("🔑 API Keys")
    gemini_key = st.secrets.get("GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY") or st.text_input("Gemini Key", type="password")
    tavily_key = st.secrets.get("TAVILY_API_KEY") or os.getenv("TAVILY_API_KEY") or st.text_input("Tavily Key", type="password")
    
    st.divider()
    st.markdown("### ⚙️ Search Settings")
    search_depth = st.slider("Threads to Analyze", min_value=5, max_value=20, value=10)

# --- LOGIC ---
def run_deep_analysis(topic, gemini_k, tavily_k, max_threads):
    log = []
    
    try:
        tavily = TavilyClient(api_key=tavily_k)
        genai.configure(api_key=gemini_k)
        model = genai.GenerativeModel('gemini-2.0-flash') 

        # 1. AGGRESSIVE SEARCH
        queries = [
            f"site:reddit.com {topic} price paid 2024 2025",
            f"site:reddit.com {topic} quote received renewal",
            f"site:reddit.com {topic} cost per month"
        ]
        
        all_threads = {} 
        progress_bar = st.progress(0)
        
        for i, q in enumerate(queries):
            log.append(f"🕵️ Running Query {i+1}: '{q}'...")
            try:
                # include_raw_content=True is critical for reading the whole thread
                response = tavily.search(query=q, search_depth="advanced", max_results=7, include_raw_content=True)
                
                for item in response.get('results', []):
                    url = item['url']
                    # Prefer raw_content (full text), fall back to content (snippet)
                    content = item.get('raw_content') or item.get('content')
                    
                    if content and len(content) > 300: # Filter out short junk
                        all_threads[url] = {
                            "title": item['title'],
                            "url": url,
                            "content": content
                        }
            except Exception as e:
                log.append(f"⚠️ Search error: {e}")
            
            time.sleep(0.5)
            progress_bar.progress((i + 1) / len(queries))
            
        unique_threads = list(all_threads.values())[:max_threads]
        
        if len(unique_threads) < 1:
            return None, log + ["❌ No valid data found. Try a different topic."]
            
        log.append(f"✅ Found {len(unique_threads)} unique threads. Extracting data...")

        # 2. DATA PREP
        combined_text = ""
        for t in unique_threads:
            # tag each section so the AI knows where the info came from
            combined_text += f"SOURCE_ID: {t['url']}\nTITLE: {t['title']}\nCONTENT:\n{t['content'][:12000]}\n{'='*40}\n"

        # 3. RELAXED EXTRACTION PROMPT (Fixes "Only 2 datapoints" issue)
        prompt = f"""
        You are a Data Scraper. Extract pricing data from this Reddit text.
        
        CRITICAL RULES:
        1. EXTRACT EVERY SINGLE price mention. Do not be picky. 
        2. If the user doesn't say their car, list it as "Unknown Vehicle".
        3. If the user doesn't say their location, list "Unknown Location".
        4. Capture the "Source Quote" so we can verify it.
        5. Map every row back to the 'SOURCE_ID' (URL) provided in the text.
        
        RETURN JSON ONLY:
        {{
            "dataset": [
                {{
                    "product_name": "Vehicle Model (or 'Unknown')",
                    "brand": "Insurance Company (or 'Unknown')",
                    "price_monthly": 123,
                    "location": "City/State",
                    "user_profile": "Age, Credit, Tickets (or 'None')",
                    "quote_snippet": "The specific text mentioning the price",
                    "source_url": "The SOURCE_ID url matching this quote",
                    "source_title": "The Title of the thread",
                    "sentiment": "Positive/Negative/Neutral"
                }}
            ],
            "market_summary": "Brief summary of the market.",
            "price_volatility": "High/Medium/Low",
            "recommendation": "One tip for buyers."
        }}
        
        TEXT TO ANALYZE:
        {combined_text}
        """
        
        response = model.generate_content(prompt)
        text_resp = response.text.replace("```json", "").replace("```", "").strip()
        data = json.loads(text_resp)
        
        return data, log + ["✅ Extraction Complete!"]

    except Exception as e:
        return None, log + [f"❌ Error: {str(e)}"]

# --- MAIN UI ---
st.title("🕵️‍♂️ Deep Reddit Market Analyst")

with st.form("search_form"):
    topic_input = st.text_input("Research Topic", "Car Insurance Cost Florida")
    submitted = st.form_submit_button("🚀 Run Analysis")

if submitted and gemini_key and tavily_key:
    with st.status("🤖 AI Agent Working...", expanded=True) as status:
        data, logs = run_deep_analysis(topic_input, gemini_key, tavily_key, search_depth)
        for l in logs: st.write(l)
        if data:
            st.session_state.results = data
            status.update(label="✅ Analysis Complete!", state="complete", expanded=False)

# --- RESULTS DISPLAY ---
if st.session_state.results:
    data = st.session_state.results
    
    if "dataset" in data and data["dataset"]:
        df = pd.DataFrame(data["dataset"])
        
        # 1. Clean Data (Handle missing values safely)
        df['price_monthly'] = pd.to_numeric(df['price_monthly'], errors='coerce')
        df = df.dropna(subset=['price_monthly'])
        
        # Fill missing string columns to prevent errors
        for col in ['brand', 'product_name', 'location', 'source_url', 'source_title', 'quote_snippet']:
            if col not in df.columns:
                df[col] = "Unknown"
        
        st.divider()
        st.header(f"Results for: {topic_input}")

        tab1, tab2, tab3 = st.tabs(["📊 Market Dashboard", "📝 Raw Data & Sources", "🤖 AI Insights"])

        # === TAB 1: DASHBOARD ===
        with tab1:
            k1, k2, k3 = st.columns(3)
            k1.metric("Data Points", len(df))
            k2.metric("Median Price", f"${int(df['price_monthly'].median())}/mo")
            k3.metric("Max Price", f"${int(df['price_monthly'].max())}/mo")
            
            st.divider()
            
            c1, c2 = st.columns(2)
            with c1:
                st.subheader("💰 Price by Brand")
                # Error check: Ensure we have data before plotting
                if not df.empty:
                    brand_counts = df['brand'].value_counts().reset_index()
                    brand_counts.columns = ['brand', 'count'] # Rename for safety
                    
                    # Only plot brands with > 0 mentions
                    fig_bar = px.bar(
                        df.groupby("brand")['price_monthly'].mean().reset_index(), 
                        x='price_monthly', 
                        y='brand', 
                        orientation='h', 
                        title="Avg Price ($)",
                        color='price_monthly'
                    )
                    st.plotly_chart(fig_bar, use_container_width=True)
                else:
                    st.info("Not enough data to plot brands.")

            with c2:
                st.subheader("📈 Price Distribution")
                if not df.empty:
                    fig_hist = px.histogram(df, x="price_monthly", nbins=10, title="Price Ranges")
                    st.plotly_chart(fig_hist, use_container_width=True)

        # === TAB 2: RAW DATA ===
        with tab2:
            st.markdown("### 🔍 Granular Data")
            
            # Safe CSV Download
            csv = df.to_csv(index=False).encode('utf-8')
            st.download_button("📥 Download CSV", data=csv, file_name="reddit_data.csv", mime="text/csv")

            st.dataframe(
                df[['brand', 'price_monthly', 'product_name', 'location', 'quote_snippet', 'source_url']],
                use_container_width=True,
                column_config={
                    "source_url": st.column_config.LinkColumn("Source", display_text="View Link")
                }
            )
            
            st.markdown("### 📚 Bibliography")
            # Deduplicate safely
            if 'source_title' in df.columns:
                unique_sources = df[['source_title', 'source_url']].drop_duplicates()
                for _, row in unique_sources.iterrows():
                    st.markdown(f"- [{row.get('source_title', 'Link')}]({row.get('source_url', '#')})")

        # === TAB 3: AI INSIGHTS ===
        with tab3:
            st.info(f"**Summary:** {data.get('market_summary', 'N/A')}")
            st.success(f"**Recommendation:** {data.get('recommendation', 'N/A')}")

    else:
        st.warning("⚠️ Analysis ran, but no specific price data could be extracted from the found threads.")
