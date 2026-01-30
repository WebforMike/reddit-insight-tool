import streamlit as st
import google.generativeai as genai
from tavily import TavilyClient
import json
import re
import os

# --- PAGE SETUP ---
st.set_page_config(page_title="Reddit Market Researcher", page_icon="🚀", layout="wide")

st.title("🚀 Reddit Topic Researcher")
st.markdown("""
**Goal:** Enter a topic (e.g., "Car Insurance Florida"). 
The AI will **find** the threads, **read** the discussions, and **extract** the data.
""")

# --- SIDEBAR: INPUTS ---
with st.sidebar:
    st.header("🔑 API Keys")
    
    # 1. GEMINI KEY
    gemini_key = st.secrets.get("GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY")
    if not gemini_key:
        gemini_key = st.text_input("Gemini API Key", type="password")
        if not gemini_key:
            st.info("Get a free key at aistudio.google.com")

    # 2. TAVILY KEY
    tavily_key = st.secrets.get("TAVILY_API_KEY") or os.getenv("TAVILY_API_KEY")
    if not tavily_key:
        tavily_key = st.text_input("Tavily API Key", value="", type="password")

# --- MAIN LOGIC ---
topic = st.text_input("Enter a Topic to Research:", placeholder="e.g. Best homeowners insurance for flood zones")

if st.button("🚀 Find & Analyze Threads", type="primary"):
    
    # 1. Validation
    if not gemini_key or not tavily_key:
        st.error("⚠️ Please enter both API Keys in the sidebar!")
        st.stop()
        
    # 2. Setup Clients
    try:
        tavily = TavilyClient(api_key=tavily_key)
        genai.configure(api_key=gemini_key)
        model = genai.GenerativeModel('gemini-2.0-flash')
    except Exception as e:
        st.error(f"Error connecting to APIs: {e}")
        st.stop()

    # 3. SEARCH (Tavily)
    status_box = st.status("🕵️ Agent is working...", expanded=True)
    
    try:
        status_box.write(f"Searching the web for Reddit threads about: '{topic}'...")
        
        search_result = tavily.search(
            query=f"site:reddit.com {topic}", 
            search_depth="advanced", 
            max_results=5,
            include_raw_content=True
        )
        
        threads = search_result.get('results', [])
        
        if not threads:
            status_box.update(label="❌ No results found", state="error")
            st.error("Tavily couldn't find any threads. Try a broader topic.")
            st.stop()
            
        status_box.write(f"✅ Found {len(threads)} relevant threads.")
        
        # --- SHOW LINKS IMMEDIATELY ---
        st.subheader("🔗 Sources Found")
        for t in threads:
            st.markdown(f"- [{t['title']}]({t['url']})")
        
        # Prepare text for AI (CRASH FIX HERE)
        combined_text = ""
        for t in threads:
            # SAFETY CHECK: If raw_content is None, use empty string
            content = t.get('raw_content') or "" 
            url = t.get('url', 'No URL')
            title = t.get('title', 'No Title')
            
            combined_text += f"\nSOURCE URL: {url}\nTITLE: {title}\nCONTENT: {content[:1500]}\n{'='*20}\n"

        # 4. ANALYZE (Gemini)
        status_box.write("🧠 Reading threads and extracting insights...")
        
        prompt = f"""
        You are a market research bot. Read these Reddit threads about "{topic}".
        
        Return ONLY a raw JSON object with these keys:
        - "summary": (string) 2-sentence summary of the consensus.
        - "price_range": (string) Any prices mentioned (e.g. "$500-$800"). If none, "N/A".
        - "sentiment": (string) Positive, Negative, or Neutral.
        - "pain_points": (list of strings) Top 3 user complaints.
        - "key_quote": (string) The most useful direct quote.

        DATA:
        {combined_text}
        """
        
        response = model.generate_content(prompt)
        
        # Clean up JSON (remove ```json wrappers)
        cleaned_json = re.sub(r"```json|```", "", response.text).strip()
        
        # Parse JSON
        try:
            data = json.loads(cleaned_json)
        except json.JSONDecodeError:
            # Fallback if AI returns bad JSON
            data = {"summary": "Error parsing AI response", "sentiment": "Error", "price_range": "N/A", "pain_points": [], "key_quote": "N/A"}
        
        status_box.update(label="✅ Analysis Complete!", state="complete", expanded=False)

        # 5. DISPLAY RESULTS
        st.divider()
        col1, col2 = st.columns(2)
        col1.metric("Sentiment", data.get("sentiment", "N/A"))
        col2.metric("Price Est.", data.get("price_range", "N/A"))
        
        st.subheader("📝 Summary")
        st.write(data.get("summary", "No summary available."))
        
        st.subheader("😤 Top Pain Points")
        for p in data.get("pain_points", []):
            st.warning(f"• {p}")
            
        st.info(f"**📢 Top Quote:** \"{data.get('key_quote', 'No quote found')}\"")

    except Exception as e:
        status_box.update(label="❌ Error", state="error")
        st.error(f"Something went wrong: {e}")
