import streamlit as st
import google.generativeai as genai
from apify_client import ApifyClient
import json
import pandas as pd
import plotly.express as px
import os

# --- CONFIG ---
st.set_page_config(page_title="Deep Reddit Analyst (Apify)", page_icon="⚡", layout="wide")

if "results" not in st.session_state:
    st.session_state.results = None

# --- SIDEBAR ---
with st.sidebar:
    st.header("🔑 API Keys")
    
    with st.expander("⚡ Apify & Gemini Keys", expanded=True):
        apify_token = st.secrets.get("APIFY_API_TOKEN") or st.text_input("Apify API Token", type="password")
        gemini_key = st.secrets.get("GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY") or st.text_input("Gemini Key", type="password")

    st.divider()
    st.markdown("### ⚙️ Scraper Settings")
    max_posts = st.slider("Max Posts to Analyze", 5, 20, 10)
    max_comments = st.slider("Max Comments per Post", 20, 100, 50)

# --- CORE LOGIC ---
def run_apify_analysis(mode, input_data, apify_token, gemini_k):
    log = []
    
    try:
        # 1. INITIALIZE CLIENTS
        client = ApifyClient(apify_token)
        genai.configure(api_key=gemini_k)
        model = genai.GenerativeModel('gemini-2.5-flash') 

        # 2. PREPARE APIFY INPUT
        # We use the "Reddit Scraper" actor (jwR5FKaWaGSmkeq2b)
        run_input = {
            "searchMode": "link",
            "time": "all",
            "includeComments": True,  # CRITICAL: Must be True to find prices
            "maxItems": max_posts,
            "maxComments": max_comments,
            "proxy": {
                "useApifyProxy": True,
                "apifyProxyGroups": ["RESIDENTIAL"], # The magic anti-block layer
            },
        }

        if mode == "Search":
            log.append(f"⚡ Searching Reddit via Apify for: '{input_data}'")
            run_input["search"] = input_data
            run_input["startUrls"] = [] # Clear URLs if searching
            
        elif mode == "Direct URL":
            urls = [u.strip() for u in input_data.split(",") if "reddit.com" in u]
            log.append(f"⚡ targeting {len(urls)} specific URLs...")
            run_input["startUrls"] = [{"url": u} for u in urls]
            run_input["search"] = "" # Clear search if using URLs

        # 3. RUN THE ACTOR
        log.append("🚀 Sending task to Apify cloud (this takes 10-20s)...")
        
        # Run the actor and wait for it to finish
        run = client.actor("jwR5FKaWaGSmkeq2b").call(run_input=run_input)
        
        # 4. FETCH RESULTS
        dataset_items = client.dataset(run["defaultDatasetId"]).iterate_items()
        
        combined_text = ""
        item_count = 0
        
        for item in dataset_items:
            # Parse the complex Apify JSON into simple text for Gemini
            title = item.get('title', 'Unknown Title')
            url = item.get('url', 'Unknown URL')
            self_text = item.get('body', '')
            
            thread_text = f"SOURCE_ID: {url}\nTITLE: {title}\nOP_TEXT: {self_text[:500]}\nCOMMENTS:\n"
            
            # Apify returns comments in a nested structure or flat list depending on config
            # This actor usually returns them in 'comments' list
            comments = item.get('comments', [])
            for c in comments:
                if isinstance(c, dict):
                    author = c.get('author', 'user')
                    body = c.get('body', '')
                    if body:
                        thread_text += f"- [{author}]: {body}\n"
            
            thread_text += f"{'='*40}\n"
            combined_text += thread_text
            item_count += 1

        if item_count == 0:
            return None, log + ["❌ Apify finished but returned 0 results. Check your inputs."]

        log.append(f"✅ Retrieved {item_count} threads. Sending to AI...")

        # 5. AI EXTRACTION (The "Messy Data" Logic)
        prompt = f"""
        You are an Insurance Data Actuary.
        
        GOAL: Extract insurance pricing data from this raw Reddit text.
        
        RULES:
        1. **Extract Everything:** Every specific price mention.
        2. **Messy Data:** If car/location is missing, write "Unknown".
        3. **Context:** Capture the exact quote.
        4. **Source:** Map to 'SOURCE_ID'.
        
        RETURN JSON ONLY:
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
        {combined_text[:40000]} 
        """
        # Note: We limit text to 40k chars to stay within standard token limits, 
        # though Gemini Flash can handle much more if needed.
        
        response = model.generate_content(prompt)
        text_resp = response.text.replace("```json", "").replace("```", "").strip()
        
        try:
            data = json.loads(text_resp)
            data['raw_debug'] = combined_text # Save for debugging
        except:
            return None, log + ["❌ AI Response was not valid JSON."]

        return data, log + ["✅ Analysis Complete!"]

    except Exception as e:
        return None, log + [f"❌ Error: {str(e)}"]

# --- MAIN UI ---
st.title("⚡ Deep Reddit Analyst (Apify Edition)")
st.markdown("Uses **Apify Residential Proxies** to guarantee access to Reddit data.")

tab_search, tab_direct = st.tabs(["🔎 Search Mode", "🔗 Direct URL Mode"])

with tab_search:
    with st.form("search_form"):
        topic_input = st.text_input("Enter Topic", "Hyundai Car Insurance")
        submit_search = st.form_submit_button("🚀 Run Apify Search")

with tab_direct:
    with st.form("direct_form"):
        url_input = st.text_area("Paste Reddit URLs", "https://www.reddit.com/r/Hyundai/comments/1l1mxlz/insurance_cost/")
        submit_direct = st.form_submit_button("⚡ Run Apify Crawler")

if submit_search or submit_direct:
    if not (apify_token and gemini_key):
        st.error("⚠️ Please provide Apify and Gemini keys in the sidebar.")
    else:
        mode = "Search" if submit_search else "Direct URL"
        input_data = topic_input if submit_search else url_input
        
        with st.status(f"🤖 Running Apify Agent ({mode})...", expanded=True) as status:
            data, logs = run_apify_analysis(mode, input_data, apify_token, gemini_key)
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
        
        t1, t2, t3 = st.tabs(["Dashboard", "Raw Data", "Debug Text"])
        
        with t1:
            valid = df[df['price_monthly'] > 0]
            k1, k2 = st.columns(2)
            k1.metric("Data Points", len(df))
            if not valid.empty:
                k2.metric("Median Price", f"${int(valid['price_monthly'].median())}")
                st.plotly_chart(px.bar(valid, x='price_monthly', y='brand', orientation='h', color='price_monthly'), use_container_width=True)
            else:
                st.info("No numeric prices extracted.")

        with t2:
            st.dataframe(
                df[['brand', 'price_monthly', 'product_name', 'location', 'quote_snippet', 'source_url']], 
                use_container_width=True,
                column_config={"source_url": st.column_config.LinkColumn("Source")}
            )
            
        with t3:
            st.text_area("Raw Data from Apify", value=data.get('raw_debug', ''), height=400)
            
    else:
        st.warning("Apify finished, but AI found no price data.")
