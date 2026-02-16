from langchain_openai import ChatOpenAI
from langchain_tavily import TavilySearch
from langchain_core.tools import tool
from .tools import get_cart_items, add_to_cart, search_product
import os
from dotenv import load_dotenv

load_dotenv()

# LLMs
llm = ChatOpenAI(model="gpt-4.1-nano-2025-04-14", temperature=0.7)
web_search = TavilySearch(max_results=3)

# Cart Agent
cart_agent = ChatOpenAI(model="gpt-4.1-nano-2025-04-14", temperature=0.7).bind_tools(
    [get_cart_items, add_to_cart, search_product]
)

# Research Agent  
research_agent = ChatOpenAI(model="gpt-4.1-nano-2025-04-14", temperature=0.7).bind_tools(
    [web_search]
)

def route_message(message: str) -> str:
    """Route message to appropriate agent"""
    cart_keywords = ["cart", "add", "buy", "purchase", "checkout"]
    research_keywords = ["tell me about", "what is", "how to care", "watering", "soil", "light"]
    
    message_lower = message.lower()
    
    if any(keyword in message_lower for keyword in cart_keywords):
        return "cart"
    elif any(keyword in message_lower for keyword in research_keywords):
        return "research"
    else:
        return "research"  # Default to research

def get_response(message: str, user_id: int) -> str:
    """Get response from appropriate agent"""
    agent_type = route_message(message)
    
    if agent_type == "cart":
        response = cart_agent.invoke({
            "messages": [{
                "role": "user", 
                "content": f"User ID: {user_id}. Message: {message}. Help with cart operations."
            }]
        })
    else:
        response = research_agent.invoke({
            "messages": [{
                "role": "user", 
                "content": f"Message: {message}. Research plant information using web search."
            }]
        })
    
    return response.content 