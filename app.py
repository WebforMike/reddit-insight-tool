import streamlit as st
import praw
import google.generativeai as genai
import json
import re
import os

# 1. App Layout & Config
st.set_page_config(page_title="Reddit Insight AI", page_icon="🧠", layout="wide")
st.title("🧠 Reddit Insight Extractor")
st.markdown("### AI-powered analysis of Reddit discussions, prices, and sentiment.")

# 2. API Key Management (Secrets or Sidebar)
# Check if keys are in Streamlit Secrets (for cloud) or Environment Variables
reddit_id = st.secrets.get("REDDIT_CLIENT_ID") or os.getenv("REDDIT_CLIENT_ID")
reddit_secret = st.secrets.get("REDDIT_CLIENT_SECRET") or os.getenv("REDDIT_CLIENT_SECRET")
gemini_key = st.secrets.get("GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY")

# If keys are missing, show sidebar inputs
if not (reddit_id and reddit_secret and gemini_key):
    with st.sidebar:
        st.warning("⚠️ API Keys not found in secrets. Please enter them below.")
        reddit_id = st.text_input("Reddit Client ID", type="password")
        reddit_secret = st.text_input("Reddit Client Secret", type="password")
        gemini_key = st.text_input("Gemini API Key", type="password")

# 3. Main Logic
topic = st.text_input("Enter a topic to analyze (e.g. 'Home Insurance cost Florida'):")

if st.button("Analyze Now", type="primary"):
    if not (reddit_id and reddit_secret and gemini_key):
        st.error("Please provide all API Keys to proceed.")
        st.stop()
        
    # Initialize Clients
    try:
        reddit = praw.Reddit(
            client_id=reddit_id,
            client_secret=reddit_secret,
            user_agent='InsightApp/1.0'
        )
        genai.configure(api_key=gemini_key)
        model = genai.GenerativeModel('gemini-1.5-flash')
    except Exception as e:
        st.error(f"Connection Error: {e}")
        st.stop()

    status_area = st.empty()
    
    # Step A: Search Reddit
    status_area.info(f"🔍 Searching Reddit for '{topic}'...")
    relevant_text = ""
    thread_count = 0
    
    try:
        search_results = reddit.subreddit("all").search(topic, limit=5, sort="relevance")
        
        for post in search_results:
            thread_count += 1
            post.comments.replace_more(limit=0)
            relevant_text += f"Title: {post.title}\n"
            relevant_text += f"Body: {post.selftext[:500]}\n"
            comments = [c.body for c in post.comments.list() if not c.stickied][:3]
            relevant_text += "Comments:\n" + "\n".join(comments) + "\n---\n"
            
        if thread_count == 0:
            status_area.warning("No threads found. Try a broader search term.")
            st.stop()

        # Step B: Analyze with Gemini
        status_area.info(f"🤖 Analyzing {thread_count} threads with Gemini AI...")
        
        prompt = f"""
        Analyze the following Reddit text about "{topic}".
        Return ONLY a raw JSON object with these exact keys:
        - "summary": (string) Brief summary of the consensus.
        - "avg_price": (string) Estimated price range mentioned (e.g. "$100-200"). If none, "N/A".
        - "sentiment": (string) One word: Positive, Negative, or Neutral.
        - "pain_points": (list of strings) Top 3 distinct user complaints.
        - "key_quote": (string) The most impactful direct quote.

        Input Text:
        {relevant_text}
        """
        
        response = model.generate_content(prompt)
        # clean markdown if present
        cleaned_json = re.sub(r"```json|```", "", response.text).strip()
        data = json.loads(cleaned_json)
        
        status_area.empty() # Clear status messages
        
        # Step C: Display Dashboard
        col1, col2, col3 = st.columns(3)
        col1.metric("Sentiment", data.get("sentiment", "N/A"))
        col2.metric("Price Estimate", data.get("avg_price", "N/A"))
        col3.metric("Threads Analyzed", thread_count)
        
        st.divider()
        st.subheader("📝 Summary")
        st.write(data.get("summary", "No summary available."))
        
        st.subheader("😤 Top Pain Points")
        for point in data.get("pain_points", []):
            st.write(f"• {point}")
            
        st.info(f"💡 **Key Quote:** \"{data.get('key_quote')}\"")
        
        with st.expander("View Raw Reddit Data"):
            st.text(relevant_text)

    except Exception as e:
        status_area.error(f"An error occurred: {e}")