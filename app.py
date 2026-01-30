import streamlit as st
import google.generativeai as genai
from tavily import TavilyClient
import json
import re
import os
import time
import pandas as pd
import plotly.express as px  # REQUIRED for charts

# --- CONFIG ---
st.set_page_config(page_title="Deep Reddit Analyst", page_icon="🕵️‍♂️", layout="wide")

# Initialize session state for results
if "results" not in st.session_state:
    st.session_state.results = None

# --- SIDEBAR ---
with st.sidebar:
    st.header("🔑 API Keys")
    gemini_key = st.secrets.get("GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY") or st.text_input("Gemini Key", type="password")
    tavily_key = st.secrets.get("TAVILY_API_KEY") or os.getenv("TAVILY_API_KEY") or st.text_input("Tavily Key", type="password")
    
    st.divider()
    st.markdown("### ⚙️ Settings")
    search_depth = st.slider("Threads to Scan", 5, 20, 10)
    filter_location = st.text_input("📍 Force Location Filter (Optional)", placeholder="e.g. Florida, Texas")

# --- CORE LOGIC ---
def run_deep_analysis(topic, gemini_k, tavily_k, max_threads, loc_filter):
    log = []
    
    try:
        tavily = TavilyClient(api_key=tavily_k)
        genai.configure(api_key=gemini_k)
        model = genai.GenerativeModel('gemini-2.5-flash') 

        # 1. SMART SEARCH STRATEGY (Fixed)
        # We now start with the BROADEST possible search to catch megathreads.
        queries = [
            f"site:reddit.com {topic}",  # Query 1: The Base Term (No modifiers)
            f"site:reddit.com {topic} quote received 2024 2025", # Query 2: Recent Quotes
            f"site:reddit.com {topic} insurance cost renewal increase" # Query 3: Price hikes
        ]
        
        all_threads = {} 
        progress_bar = st.progress(0)
        
        for i, q in enumerate(queries):
            log.append(f"🕵️ Scanning Query {i+1}: '{q}'...")
            try:
                # include_raw_content=True is critical
                response = tavily.search(query=q, search_depth="advanced", max_results=7, include_raw_content=True)
                
                for item in response.get('results', []):
                    url = item['url']
                    content = item.get('raw_content') or item.get('content')
                    
                    # Store if valid content exists & avoid duplicates
                    if url not in all_threads and content and len(content) > 300: 
                        all_threads[url] = {
                            "title": item['title'],
                            "url": url,
                            "content": content
                        }
            except Exception as e:
                log.append(f"⚠️ Search warning: {e}")
            
            time.sleep(0.5)
            progress_bar.progress((i + 1) / len(queries))
            
        unique_threads = list(all_threads.values())[:max_threads]
        
        if not unique_threads:
            return None, log + ["❌ No accessible Reddit threads found."]

        log.append(f"✅ Found {len(unique_threads)} unique discussions. Extracting Intelligence...")

        # 2. DATA PREP
        combined_text = ""
        for t in unique_threads:
            # We explicitly tag the URL so the LLM can reference it
            combined_text += f"SOURCE_ID: {t['url']}\nTITLE: {t['title']}\nCONTENT:\n{t['content'][:15000]}\n{'='*40}\n"

        # 3. EXTRACTION PROMPT
        location_instruction = ""
        if loc_filter:
            location_instruction = f"IMPORTANT: The user specifically wants data related to '{loc_filter}'. Prioritize rows mentioning '{loc_filter}'."

        prompt = f"""
        You are a Data Scraper. Your job is to extract insurance pricing data from Reddit threads.
        
        {location_instruction}
        
        RULES:
        1. EXTRACT EVERY SINGLE Mention of a price, quote, or renewal hike.
        2. If the user does not specify a Car Model, put "Unknown Car".
        3. If the user does not specify a Location, put "Unknown Location".
        4. IF NO PRICE IS MENTIONED but there is strong sentiment (e.g., "My rates doubled!"), capture it with price_monthly = 0.
        5. CONVERT all prices to MONTHLY estimates.
        6. YOU MUST map the 'source_url' to the 'SOURCE_ID' provided in the text.
        
        RETURN JSON ONLY:
        {{
            "dataset": [
                {{
                    "product_name": "Vehicle Model",
                    "brand": "Insurance Company (or 'Unknown')",
                    "price_monthly": 123,
                    "location": "City/State (or 'Unknown')",
                    "quote_snippet": "The exact text where they said it",
                    "source_url": "The exact SOURCE_ID url",
                    "source_title": "The Title of the thread",
                    "sentiment": "Positive/Negative/Neutral"
                }}
            ],
            "market_summary": "3-sentence summary of the market consensus.",
            "recommendation": "1 actionable tip for the user."
        }}
        
        RAW TEXT TO MINE:
        {combined_text}
        """
        
        response = model.generate_content(prompt)
        text_resp = response.text.replace("```json", "").replace("```", "").strip()
        
        try:
            data = json.loads(text_resp)
        except:
            # Fallback if JSON is malformed
            return None, log + ["❌ AI extraction failed. Try again."]
            
        return data, log + ["✅ Extraction Complete!"]

    except Exception as e:
        return None, log + [f"❌ Critical Error: {str(e)}"]
        
# --- MAIN UI ---
st.title("🕵️‍♂️ Deep Reddit Analyst")
st.caption("Extracts pricing, quotes, and sentiment from real user discussions.")

with st.form("search_form"):
    c1, c2 = st.columns([3, 1])
    with c1:
        topic_input = st.text_input("Research Topic", "Hyundai Car Insurance Cost")
    with c2:
        submitted = st.form_submit_button("🚀 Run Analysis", type="primary", use_container_width=True)

if submitted and gemini_key and tavily_key:
    with st.status("🤖 AI Agent Working...", expanded=True) as status:
        data, logs = run_deep_analysis(topic_input, gemini_key, tavily_key, search_depth, filter_location)
        for l in logs: st.write(l)
        
        if data:
            st.session_state.results = data
            status.update(label="✅ Analysis Complete!", state="complete", expanded=False)

# --- RESULTS DISPLAY ---
if st.session_state.results:
    data = st.session_state.results
    
    if "dataset" in data and data["dataset"]:
        df = pd.DataFrame(data["dataset"])
        
        # 1. CLEANING
        # Convert price to numeric, force 0 for non-numbers
        df['price_monthly'] = pd.to_numeric(df['price_monthly'], errors='coerce').fillna(0)
        
        # Filter by Location if requested
        if filter_location:
            # Simple string match, case insensitive
            df = df[df['location'].str.contains(filter_location, case=False, na=False) | 
                    df['quote_snippet'].str.contains(filter_location, case=False, na=False)]
            if df.empty:
                st.warning(f"No specific data points found for '{filter_location}', showing all results instead.")
                df = pd.DataFrame(data["dataset"]) # Revert
                df['price_monthly'] = pd.to_numeric(df['price_monthly'], errors='coerce').fillna(0)

        # Fill text NaNs
        for col in ['brand', 'product_name', 'location', 'quote_snippet', 'source_url']:
            if col not in df.columns: df[col] = "Unknown"

        st.divider()
        st.header(f"Results for: {topic_input}")

        # TABS
        tab1, tab2, tab3 = st.tabs(["📊 Dashboard", "📝 Raw Data", "🧠 Insights"])

        # === TAB 1: DASHBOARD ===
        with tab1:
            # Filter out 0 prices for stats (since 0 = sentiment only)
            valid_prices = df[df['price_monthly'] > 0]
            
            k1, k2, k3 = st.columns(3)
            k1.metric("Mentions Found", len(df))
            if not valid_prices.empty:
                k2.metric("Median Price", f"${int(valid_prices['price_monthly'].median())}/mo")
                k3.metric("Max Price", f"${int(valid_prices['price_monthly'].max())}/mo")
            else:
                k2.metric("Median Price", "N/A")
                k3.metric("Max Price", "N/A")
            
            st.divider()
            
            c1, c2 = st.columns(2)
            
            with c1:
                st.subheader("💰 Price by Brand")
                if not valid_prices.empty:
                    # Clean up brand names (simple logic)
                    valid_prices['brand'] = valid_prices['brand'].str.title()
                    
                    fig_bar = px.bar(
                        valid_prices.groupby("brand")['price_monthly'].mean().reset_index(), 
                        x='price_monthly', 
                        y='brand', 
                        orientation='h', 
                        title="Avg Monthly Cost ($)",
                        color='price_monthly',
                        color_continuous_scale='Bluered'
                    )
                    st.plotly_chart(fig_bar, use_container_width=True)
                else:
                    st.info("No numerical price data to chart.")

            with c2:
                st.subheader("📈 Sentiment Split")
                if 'sentiment' in df.columns:
                    fig_pie = px.pie(df, names='sentiment', title='User Sentiment', color_discrete_sequence=px.colors.sequential.RdBu)
                    st.plotly_chart(fig_pie, use_container_width=True)

        # === TAB 2: RAW DATA ===
        with tab2:
            st.markdown("### 🔍 Granular Data Explorer")
            
            # Download
            csv = df.to_csv(index=False).encode('utf-8')
            st.download_button("📥 Download CSV", data=csv, file_name="reddit_data.csv", mime="text/csv")
            
            # Table
            st.dataframe(
                df[['brand', 'price_monthly', 'product_name', 'location', 'quote_snippet', 'source_url']],
                use_container_width=True,
                column_config={
                    "price_monthly": st.column_config.NumberColumn("Price ($)", format="$%d"),
                    "source_url": st.column_config.LinkColumn("Source", display_text="🔗 View Thread"),
                    "quote_snippet": st.column_config.TextColumn("Evidence", width="medium"),
                }
            )

        # === TAB 3: INSIGHTS ===
        with tab3:
            st.subheader("Market Summary")
            st.info(data.get("market_summary", "No summary available."))
            
            st.subheader("Recommendation")
            st.success(data.get("recommendation", "No specific recommendation."))
            
            st.divider()
            st.subheader("🗣️ Notable Quotes")
            for index, row in df.head(5).iterrows():
                st.markdown(f"> *\"{row['quote_snippet']}\"*")
                st.caption(f"Details: {row['brand']} | {row['location']} | [Source]({row['source_url']})")
                st.write("---")

    else:
        st.warning("⚠️ Analysis ran, but no specific data points could be extracted.")
