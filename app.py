import streamlit as st
import google.generativeai as genai
from tavily import TavilyClient
import requests
import json
import re
import os
import statistics
import time

# --- 1. PAGE CONFIGURATION ---
st.set_page_config(page_title="Reddit Insight (Jina + Gemini 2.5)", page_icon="⚡", layout="wide")

# --- 2. SIDEBAR: API KEYS ---
with st.sidebar:
    st.header("🔑 API Keys")
    
    # 1. Gemini Key
    gemini_key = st.secrets.get("GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY")
    if not gemini_key:
        gemini_key = st.text_input("Gemini API Key", type="password")

    # 2. Tavily Key
    tavily_key = st.secrets.get("TAVILY_API_KEY") or os.getenv("TAVILY_API_KEY")
    if not tavily_key:
        tavily_key = st.text_input("Tavily API Key", type="password")

    # 3. Jina Key
    jina_key = st.secrets.get("JINA_API_KEY") or os.getenv("JINA_API_KEY")
    if not jina_key:
        jina_key = st.text_input("Jina API Key", type="password")
        st.caption("Get one free at jina.ai/reader")

# --- 3. HELPER: JINA READER ---
def fetch_with_jina(url, api_key):
    """
    Uses Jina Reader API to fetch clean markdown from Reddit.
    This bypasses most bot protections.
    """
    if not api_key:
        return None, "Missing Jina Key"
        
    jina_url = f"https://r.jina.ai/{url}"
    
    headers = {
        'Authorization': f'Bearer {api_key}',
        'X-Return-Format': 'markdown' 
    }

    try:
        # Jina does the heavy lifting of proxy rotation
        response = requests.get(jina_url, headers=headers, timeout=25)
        
        if response.status_code == 200:
            return response.text, "Jina Success"
        elif response.status_code == 429:
            return None, "Jina Rate Limited"
        else:
            return None, f"Jina Error {response.status_code}"
            
    except Exception as e:
        return None, f"Connection Failed: {e}"

# --- 4. MAIN APP ---
st.title("⚡ Reddit Market Miner (Jina + Gemini 2.5)")
st.markdown("Uses **Tavily** for search, **Jina** for scraping, and **Gemini 2.5** for analysis.")

topic = st.text_input("Enter Topic:", "Car Insurance Cost Florida")

if st.button("🚀 Mine Insights", type="primary"):
    
    # Validation
    if not (gemini_key and tavily_key and jina_key):
        st.error("⚠️ Please enter ALL API Keys (Gemini, Tavily, and Jina) in the sidebar.")
        st.stop()

    # Initialize Clients
    try:
        tavily = TavilyClient(api_key=tavily_key)
        genai.configure(api_key=gemini_key)
        # Using the specific model you requested
        model = genai.GenerativeModel('gemini-2.5-flash') 
    except Exception as e:
        st.error(f"Setup Error: {e}")
        st.stop()

    # Step A: Search
