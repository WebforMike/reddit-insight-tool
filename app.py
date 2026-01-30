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

        # 3. STRUCTURED EXTRACTION (The "Quality" Fix)
        # We ask for a JSON List of Objects, not just numbers.
        prompt = f"""
        You are a Data Scientist. I have scraped {len(unique_threads)} Reddit threads about "{topic}".
        
        Your Goal: Build a structured dataset of every specific price mention.
        
        Instructions:
        1. Identify every user who mentioned a price they pay or were quoted.
        2. Extract the specific "Insurer/Brand" if mentioned (e.g., Geico, Progressive). If unknown, use "Unknown".
        3. Extract the "Context" (e.g., "23M, clean record", "2015 Honda", "Full coverage").
        4. Extract the "Price" converted to a MONTHLY integer (e.g. $600/6-months -> 100).
        5. Extract the "Sentiment" of that specific user (Positive/Negative/Neutral).

        Return JSON ONLY with this structure:
        {{
            "dataset": [
                {{ "insurer": "Geico", "price_monthly": 150, "context": "2020 Civic, 25yo male", "sentiment": "Positive", "source_title": "..." }},
                ...
            ],
            "summary": "Overall market summary...",
            "key_insight": "The most important takeaway..."
        }}
        
        DATA:
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
    rows = data.get("dataset", [])
    
    if not rows:
        st.warning("No specific price data points found in these threads.")
    else:
        # Convert to DataFrame for powerful display
        df = pd.DataFrame(rows)
        
        st.divider()
        st.header(f"Results for: {topic_input}")
        
        # 1. HIGH LEVEL STATS
        c1, c2, c3 = st.columns(3)
        c1.metric("Data Points Found", len(df))
        c2.metric("Average Price", f"${int(df['price_monthly'].mean())}/mo")
        c3.metric("Median Price", f"${int(df['price_monthly'].median())}/mo")
        
        # 2. PRICE BY INSURER (The "Context" you wanted)
        st.subheader("🏆 Price & Sentiment by Brand")
        
        if "insurer" in df.columns:
            # Group by Insurer
            grouped = df.groupby("insurer").agg({
                "price_monthly": "mean",
                "sentiment": lambda x: x.mode()[0] if not x.mode().empty else "Mixed",
                "context": "count"
            }).rename(columns={"context": "count", "price_monthly": "avg_price"}).sort_values("count", ascending=False)
            
            st.dataframe(grouped, use_container_width=True)
            
            # Simple Bar Chart
            st.bar_chart(df.set_index("insurer")["price_monthly"])

        # 3. DETAILED DATA TABLE (Transparency)
        st.subheader("📝 Raw Data Extracted")
        st.markdown("This is the exact data the AI found. You can sort by price.")
        st.dataframe(
            df[["insurer", "price_monthly", "context", "sentiment"]], 
            use_container_width=True,
            hide_index=True
        )

        # 4. SUMMARY
        st.subheader("💡 Analysis")
        st.write(data.get("summary"))
        st.info(f"**Key Insight:** {data.get('key_insight')}")
