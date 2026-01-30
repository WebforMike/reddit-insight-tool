import streamlit as st
import google.generativeai as genai
from tavily import TavilyClient
import json
import re
import os
import time
import pandas as pd # New: For real data analysis

# --- CONFIG ---
st.set_page_config(page_title="Deep Reddit Analyst", page_icon="📊", layout="wide")

if "results" not in st.session_state:
    st.session_state.results = None

# --- SIDEBAR ---
with st.sidebar:
    st.header("🔑 API Keys")
    gemini_key = st.secrets.get("GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY") or st.text_input("Gemini Key", type="password")
    tavily_key = st.secrets.get("TAVILY_API_KEY") or os.getenv("TAVILY_API_KEY") or st.text_input("Tavily Key", type="password")

# --- LOGIC ---
def run_deep_analysis(topic, gemini_k, tavily_k):
    log = []
    
    try:
        tavily = TavilyClient(api_key=tavily_k)
        genai.configure(api_key=gemini_k)
        # Using Gemini 1.5 Pro or 2.0 Flash because we need a HUGE context window for this
        model = genai.GenerativeModel('gemini-2.5-flash') 

        # 1. MULTI-QUERY EXPANSION (The "Quantity" Fix)
        # We generate 3 variations of the search to find MORE threads.
        queries = [
            f"site:reddit.com {topic} price cost",
            f"site:reddit.com {topic} quote received",
            f"site:reddit.com {topic} review expensive cheap"
        ]
        
        all_threads = {} # Use dict to remove duplicates by URL
        
        progress_bar = st.progress(0)
        
        for i, q in enumerate(queries):
            log.append(f"🕵️ Running Query {i+1}: '{q}'...")
            
            # Use 'raw_content' to bypass blocking
            response = tavily.search(query=q, search_depth="advanced", max_results=7, include_raw_content=True)
            
            for item in response.get('results', []):
                # Only keep if it has decent text content
                content = item.get('raw_content') or item.get('content')
                if content and len(content) > 150:
                    all_threads[item['url']] = {
                        "title": item['title'],
                        "url": item['url'],
                        "content": content
                    }
            
            time.sleep(0.5) # Be polite
            progress_bar.progress((i + 1) / len(queries))
            
        unique_threads = list(all_threads.values())
        
        if len(unique_threads) < 2:
            return None, log + ["❌ Not enough data found."]
            
        log.append(f"✅ Aggregated {len(unique_threads)} unique threads. Analyzing...")

        # 2. BULK CONTEXT PREPARATION
        # We combine ALL 15-20 threads into one massive prompt
        combined_text = ""
        for t in unique_threads:
            combined_text += f"SOURCE: {t['url']}\nTITLE: {t['title']}\nCONTENT:\n{t['content'][:8000]}\n{'='*40}\n"

        # 3. ADVANCED "DATA VACUUM" PROMPT
        prompt = f"""
        You are an Expert Data Extraction Agent. I have scraped Reddit discussions about "{topic}".
        
        Your Goal: specific, tabular data extraction. Do NOT summarize yet.
        
        INSTRUCTIONS:
        1. Scan the text for ANY mention of a price, quote, or cost.
        2. For every price mention, create a data row.
        3. If a user mentions a range (e.g. "200-300"), use the average (250).
        4. CONVERT all prices to MONTHLY (if annual, divide by 12. If 6-month, divide by 6).
        5. LINKING: You MUST map the data back to the 'SOURCE_URL' provided in the text.
        
        REQUIRED JSON STRUCTURE:
        {{
            "dataset": [
                {{
                    "product_name": "Specific Model/Item",
                    "brand": "Company Name",
                    "price_monthly": 123,
                    "location": "City/State",
                    "user_profile": "Details (Age, History)",
                    "quote_snippet": "Exact text quote",
                    "source_url": "The exact URL this quote came from (copied from input)",
                    "source_title": "The Title of the Reddit thread",
                    "sentiment": "Positive/Negative/Neutral"
                }}
            ],
            "market_summary": "Summary...",
            "price_volatility": "High/Medium/Low",
            "recommendation": "Actionable tip"
        }}
        
        RAW TEXT DATA:
        {combined_text}
        """
        
        response = model.generate_content(prompt)
        cleaned_json = re.sub(r"```json|```", "", response.text).strip()
        data = json.loads(cleaned_json)
        
        return data, log + ["✅ Deep Analysis Complete!"]

    except Exception as e:
        return None, log + [f"❌ Error: {str(e)}"]

# --- MAIN UI ---
st.title("📊 Deep Reddit Analyst")
st.markdown("Aggregates data from multiple searches to build a **Price vs. Brand** dataset.")

with st.form("search_form"):
    topic_input = st.text_input("Enter Topic:", "Car Insurance Cost Florida")
    submitted = st.form_submit_button("🚀 Run Deep Analysis", type="primary")

if submitted:
    if not (gemini_key and tavily_key):
        st.error("Missing Keys.")
    else:
        with st.spinner("Running multi-step research..."):
            data, logs = run_deep_analysis(topic_input, gemini_key, tavily_key)
            st.session_state.results = data
            
            # Show logs in expader
            with st.expander("Processing Logs"):
                for l in logs: st.write(l)

# --- DISPLAY RESULTS ---
if st.session_state.results:
    data = st.session_state.results
    
    # Check if 'dataset' key exists to prevent errors
    if not data or "dataset" not in data:
        st.error("The AI did not return a valid dataset. Please try again.")
    else:
        df = pd.DataFrame(data["dataset"])
        
        if df.empty:
            st.warning("Analysis finished, but no specific price points were found in the text.")
        else:
            # 1. CLEANING: Convert Price to Numbers
            df['price_monthly'] = pd.to_numeric(df['price_monthly'], errors='coerce')
            df = df.dropna(subset=['price_monthly']) # Remove rows without prices
            
            st.divider()
            st.header(f"Results for: {topic_input}")
            
            # --- TABBED LAYOUT ---
            tab1, tab2, tab3 = st.tabs(["📊 Market Dashboard", "📝 Raw Data & Sources", "🤖 AI Insights"])
            
            # === TAB 1: DASHBOARD ===
            with tab1:
                # KPIS
                k1, k2, k3, k4 = st.columns(4)
                k1.metric("Data Points", len(df))
                k2.metric("Median Price", f"${int(df['price_monthly'].median())}/mo")
                k3.metric("Lowest Price", f"${int(df['price_monthly'].min())}/mo")
                k4.metric("Highest Price", f"${int(df['price_monthly'].max())}/mo")
                
                st.divider()
                
                # CHARTS
                c1, c2 = st.columns(2)
                
                with c1:
                    st.subheader("💰 Average Price by Brand")
                    if "brand" in df.columns:
                        # Calculate average price per brand
                        brand_stats = df.groupby("brand")['price_monthly'].mean().reset_index()
                        brand_stats = brand_stats.sort_values("price_monthly", ascending=True)
                        
                        fig_bar = px.bar(
                            brand_stats, 
                            x='price_monthly', 
                            y='brand', 
                            orientation='h', 
                            text_auto='.0f',
                            color='price_monthly',
                            color_continuous_scale='Bluered'
                        )
                        st.plotly_chart(fig_bar, use_container_width=True)
                
                with c2:
                    st.subheader("📈 Price Range Distribution")
                    fig_hist = px.histogram(
                        df, 
                        x="price_monthly", 
                        nbins=15, 
                        color_discrete_sequence=['#00CC96']
                    )
                    st.plotly_chart(fig_hist, use_container_width=True)

            # === TAB 2: RAW DATA & SOURCES ===
            with tab2:
                st.markdown("### 🔍 Granular Data Explorer")
                
                # Download Button
                csv = df.to_csv(index=False).encode('utf-8')
                st.download_button("📥 Download Data as CSV", data=csv, file_name="reddit_market_data.csv", mime="text/csv")
                
                # Configure the Data Table with Clickable Links
                # We check if columns exist first to avoid errors
                cols_to_show = [c for c in ['brand', 'price_monthly', 'product_name', 'location', 'quote_snippet', 'source_url'] if c in df.columns]
                
                st.dataframe(
                    df[cols_to_show],
                    use_container_width=True,
                    height=500,
                    column_config={
                        "price_monthly": st.column_config.NumberColumn("Price ($/mo)", format="$%d"),
                        "source_url": st.column_config.LinkColumn("Source Link", display_text="View Thread"),
                        "quote_snippet": st.column_config.TextColumn("Evidence", width="medium"),
                    }
                )
                
                st.divider()
                
                # BIBLIOGRAPHY SECTION
                st.markdown("### 📚 Bibliography (Threads Analyzed)")
                if 'source_title' in df.columns and 'source_url' in df.columns:
                    unique_sources = df[['source_title', 'source_url']].drop_duplicates()
                    for _, row in unique_sources.iterrows():
                        st.markdown(f"- [{row['source_title']}]({row['source_url']})")
                else:
                    st.info("Source titles not available in this dataset.")

            # === TAB 3: AI INSIGHTS ===
            with tab3:
                st.header("🧠 AI Market Analysis")
                
                st.info(f"**Market Summary:** {data.get('market_summary', 'No summary available.')}")
                
                col_a, col_b = st.columns(2)
                with col_a:
                    st.warning(f"**Volatility:** {data.get('price_volatility', 'Unknown')}")
                with col_b:
                    st.success(f"**Recommendation:** {data.get('recommendation', 'No recommendation available.')}")
                
                st.divider()
                st.markdown("### 🗣️ Notable Quotes")
                
                # Filter for sentiments if the column exists
                if 'sentiment' in df.columns:
                    neg_reviews = df[df['sentiment'].str.lower().str.contains("neg", na=False)]
                    pos_reviews = df[df['sentiment'].str.lower().str.contains("pos", na=False)]
                    
                    sc1, sc2 = st.columns(2)
                    with sc1:
                        st.error("😡 Negative Sentiment Examples")
                        if not neg_reviews.empty:
                            for _, row in neg_reviews.head(3).iterrows():
                                st.markdown(f"> *\"{row.get('quote_snippet', 'No quote')}\"*")
                                st.caption(f"— {row.get('brand', 'Unknown')} User")
                        else:
                            st.write("No negative examples found.")
                            
                    with sc2:
                        st.success("😍 Positive Sentiment Examples")
                        if not pos_reviews.empty:
                            for _, row in pos_reviews.head(3).iterrows():
                                st.markdown(f"> *\"{row.get('quote_snippet', 'No quote')}\"*")
                                st.caption(f"— {row.get('brand', 'Unknown')} User")
                        else:
                            st.write("No positive examples found.")
