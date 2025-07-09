from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_tavily import TavilySearch
from langgraph.prebuilt import create_react_agent
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langgraph.checkpoint.memory import InMemorySaver
from langchain_core.messages import AIMessage
from typing import Annotated, TypedDict, Literal
from dotenv import load_dotenv
from .tools import get_cart_items, add_to_cart, remove_cart_item, get_my_orders_url, get_orders_by_date, get_order_details_by_id, get_checkout_url, get_most_recent_order
from category.models import Category
from store.models import Product
from PIL import Image
import io
import base64
from openai import OpenAI


load_dotenv()

# Create SQLite-based checkpointer for short-term memory
checkpointer = InMemorySaver()

# Define the state schema
class SupervisorState(TypedDict):
    messages: Annotated[list, add_messages]
    agent_type: list[str]
    image_b64: str 


# Create the supervisor LLM
supervisor_llm = ChatOpenAI(model="gpt-4.1-nano-2025-04-14", temperature=0.3)

# Create the cart agent with memory
cart_agent = create_react_agent(
    model=ChatOpenAI(model="gpt-4.1-nano-2025-04-14", temperature=0.7),
    tools=[get_cart_items, add_to_cart, remove_cart_item],
    prompt="""You are a helpful plant store assistant. You can ONLY help users with:
1. Checking their cart contents
2. Adding products to their cart (The query of product may contain variations. From the query, you need to extract the product name and the variations)
3. Removing items from cart

Always be friendly and helpful. When users ask about their cart, use the get_cart_items tool. Format the output of get_cart_items tool in a user freindly way.
When they want to add products, first use the add_to_cart tool. Format the output of add_to_cart tool in a user freindly way.
When they want to remove any product, use the remove_cart_item tool. Format the output of remove_cart_item tool in a user freindly way.
If the user's question is not about plants or gardening, politely say you can only help with plant-related queries.
Remember to include the user_id when using cart-related tools.

IMPORTANT: Remember previous interactions in this conversation. If the user refers to something mentioned earlier, use that context.

LANGUAGE SELECTION:
If the user's message is in ENGLISH then respond in ENGLISH.
Else if the user's message is in HINDI then respond in HINDI.
"""
)

# Create the research agent with memory
web_search = TavilySearch(max_results=2)
research_agent = create_react_agent(
    model=ChatOpenAI(model="gpt-4.1-nano-2025-04-14", temperature=0.7),
    tools=[web_search],
    prompt="""You are a plant research assistant.

You answer ONLY questions about plant care, watering frequency, soil type, nutrients, sunlight, pests, diseases, and any other plant-related information.

Always use the web_search tool to provide up-to-date and accurate information. Be concise, friendly, and cite your sources if possible.

If the user's question is not about plants or gardening, politely say you can only help with plant-related queries.

Format the output of web_search tool in a user friendly way.

IMPORTANT: If the user asks for specific plant care or specific recommendations for any specific plant but mentions they don't know the plant's name, or says things like "I have a plant but don't know what it is", FIRST CHECK if 'Image uploaded: Yes' is present in the user's message. IF NOT, then ask them to upload a photo of the plant for the best possible advice. For general things you don't need an image of plant. Think from prompt if image is required or not.

IMPORTANT: Remember previous interactions in this conversation. If the user refers to something mentioned earlier, use that context.

LANGUAGE SELECTION:
If the user's message is in ENGLISH then respond in ENGLISH.
Else if the user's message is in HINDI then respond in HINDI.
"""

)

# Create order agent
order_agent = create_react_agent(
    model=ChatOpenAI(model="gpt-4.1-nano-2025-04-14", temperature=0.7),
    tools=[get_order_details_by_id, get_my_orders_url, get_orders_by_date, get_checkout_url, get_most_recent_order],
    prompt="""You are a helpful plant store assistant. You can ONLY help users with:
1. Redirecting them to the 'My Orders' page. Use the get_my_orders_url tool. Always share the link in a clear and user-friendly way.
2. Providing details about a specific order using the Order ID (such as status, products in that order, total price, and order date). Use the get_order_details_by_id tool.
3. Fetching a list of orders placed on a specific date. Use the get_orders_by_date tool.
4. Redirecting them to the 'Checkout' page. Use the get_checkout_url tool. Always share the link in a clear and user-friendly way.
5. Providing details about the most recent order placed by the user. Use the get_most_recent_order tool for queries about the most recent or latest order.

Always be friendly and helpful. Format the tool outputs in a clean, user-friendly way.
If the user's question is not about plant orders or purchases, politely say you can only assist with plant-related orders.

IMPORTANT: Always include the user_id when calling any tool.
Remember previous interactions in this conversation. If the user refers to something mentioned earlier (like a date or order ID), use that context.

LANGUAGE SELECTION:
If the user's message is in ENGLISH then respond in ENGLISH.
Else if the user's message is in HINDI then respond in HINDI.
"""
)


# Recommendation agent functions
def extract_category_llm(user_prompt: str, llm) -> str:
    """Extract category from user prompt using LLM"""
    system_prompt = (
        "You are a classifier for a plant store. "
        "Given a user request, respond with ONLY one of these categories: "
        "'Plants', 'Seeds', 'Planters', 'Plant Care'.\n"
        "User request: " + user_prompt
    )
    response = llm.invoke([
        SystemMessage(content=system_prompt)
    ])
    return response.content.strip()

def fetch_products_by_category(category_name: str) -> list:
    """Fetch products by category using Django ORM"""
    try:
        category = Category.objects.get(category_name__iexact=category_name)
        products = Product.objects.filter(category=category)
        return list(products)
    except Category.DoesNotExist:
        return []

def format_products_for_llm(products: list) -> str:
    """Format products for LLM consumption"""
    if not products:
        return "No products found in this category."
    
    lines = []
    for p in products:
        # Get product description or use a default
        description = getattr(p, 'description', '') or 'A great plant store product'
        lines.append(f"- {p.product_name}: {description}")
    return "\n".join(lines)

def recommend_products_llm(user_prompt: str, product_list_str: str, llm) -> str:
    """Generate recommendations using LLM with product context"""
    system_prompt = f"""
You are a plant store recommendation assistant.

Here is a list of available products in the relevant category:
{product_list_str}

ONLY recommend from the provided product list. If the list is empty, say so and do NOT recommend anything else. Do NOT use external knowledge or make up products.

Be concise, helpful, and explain why each recommendation is suitable.

If no products are found, suggest that the user explore related categories or try a different search.

IMPORTANT: If the user asks for specific plant care or specific recommendations for any specific plant but mentions they don't know the plant's name, or says things like "I have a plant but don't know what it is", FIRST CHECK if 'Image uploaded: Yes' is present in the user's message. IF NOT, then ask them to upload a photo of the plant for the best possible advice. For general things you don't need an image of plant. Think from prompt if image is required or not.
"""


    response = llm.invoke([
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_prompt)
    ])
    return response.content

# Create recommendation agent using StateGraph
class RecommendationState(TypedDict):
    messages: Annotated[list, add_messages]
    category: str
    product_list: str

def category_extraction_node(state: RecommendationState) -> RecommendationState:
    """Extract category from user prompt"""
    user_prompt = state["messages"][-1].content
    category = extract_category_llm(user_prompt, supervisor_llm)
    return {**state, "category": category}

def product_fetch_node(state: RecommendationState) -> RecommendationState:
    """Fetch products by category, append DB-only message if empty"""
    products = fetch_products_by_category(state["category"])
    product_list = format_products_for_llm(products)
    if not products:
        product_list += "\n\nNo products found in this category in our store database."
    return {**state, "product_list": product_list}

def recommendation_node(state: RecommendationState) -> RecommendationState:
    """Generate recommendations"""
    user_prompt = state["messages"][-1].content
    product_list = state["product_list"]
    recommendation = recommend_products_llm(user_prompt, product_list, supervisor_llm)
    
    # Add the recommendation as an AI message
    from langchain_core.messages import AIMessage
    state["messages"].append(AIMessage(content=recommendation))
    return state

# Build the recommendation graph with memory
def create_recommendation_agent():
    """Create recommendation agent using StateGraph with memory"""
    graph = StateGraph(RecommendationState)
    graph.add_node("category", category_extraction_node)
    graph.add_node("fetch_products", product_fetch_node)
    graph.add_node("recommend", recommendation_node)
    graph.set_entry_point("category")
    graph.add_edge("category", "fetch_products")
    graph.add_edge("fetch_products", "recommend")
    graph.add_edge("recommend", END)
    return graph.compile(checkpointer=checkpointer)

# Create the recommendation agent
recommendation_agent = create_recommendation_agent()

## Image recognition
#Resize
def resize_image_if_needed(image_file, max_size=1024):
    image = Image.open(image_file)
    if max(image.size) > max_size:
        image.thumbnail((max_size, max_size))
        output = io.BytesIO()
        image.save(output, format=image.format)
        output.seek(0)
        return output, image.format
    else:
        image_file.seek(0)
        return image_file, image.format


def identify_plant_from_image(image_file):

    resized_file, img_format = resize_image_if_needed(image_file)

    image_bytes = resized_file.read()
    image_b64 = base64.b64encode(image_bytes).decode('utf-8')
    mime_type = f"image/{img_format.lower()}"
    image_url = f"data:{mime_type};base64,{image_b64}"

    client = OpenAI()
    response = client.responses.create(
        model="gpt-4.1-nano-2025-04-14",
        input=[{
            "role": "system",
            "content": [
                {"type": "input_text", "text": "Analyze the uploaded image and determine if it contains a plant. If a plant is recognized, respond with only the plant name (no extra text). If the image does not contain a recognizable plant, respond with DON'T KNOW"},
            ],
        },
        {
            "role": "user",
            "content": [
                {"type": "input_image", "image_url": image_url},
            ],
        }],
        max_output_tokens=1024,
        temperature=0.7,
        top_p=1,
    )
    # Extract the output text
    output = response.output_text.strip()
    return output

# LLM-based classifier for specific plant care/identification queries

def is_specific_plant_query_llm(user_prompt: str, llm) -> bool:
    """Use LLM to classify if the query is about specific plant care/identification or general/generic."""
    system_prompt = (
        "You are a classifier for a plant assistant. "
        "Given a user request, respond with ONLY 'specific' if the query is about a specific plant, plant care, or plant identification, "
        "or 'general' if it is a general/generic plant question (like 'suggest indoor plants', 'what are some easy plants', etc).\n"
        "User request: " + user_prompt
    )
    response = llm.invoke([SystemMessage(content=system_prompt)])
    return response.content.strip().lower() == "specific"

def supervisor_node(state: SupervisorState) -> SupervisorState:
    """Supervisor node that decides which agent(s) to route to"""
    messages = state["messages"]
    image_b64 = state.get("image_b64", "")
    user_prompt = messages[-1].content.lower()

    # 🔍 Force routing to recommendation if product-related or image present
    if any(kw in user_prompt for kw in ["fertilizer", "buy", "recommend", "suggest", "booster"]) or image_b64:
        agent_list = ["recommendation"]
    else:
        # Use LLM-based classification
        system_prompt = """You are a supervisor that routes user queries to the appropriate agents.

Available agents:
1. CART_AGENT - For cart operations (add/view/remove items)
2. RESEARCH_AGENT - For plant care, watering, sunlight, soil, diseases
3. RECOMMENDATION_AGENT - For product suggestions (like indoor plants, fertilizers)
4. ORDER_AGENT – For viewing order history or order details

Respond with a comma-separated list (no extra text) of the agent types the query should be routed to:
- cart
- research
- recommendation
- order
For example, respond with: recommendation,research
"""

        decision_messages = [
            SystemMessage(content=system_prompt),
            messages[-1]
        ]

        response = supervisor_llm.invoke(decision_messages)
        raw_decision = response.content.strip().lower()

        agent_list = [a.strip() for a in raw_decision.split(",") if a.strip() in ["cart", "research", "recommendation", "order"]]

        if not agent_list:
            agent_list = ["research"]  # default fallback

    return {
        "messages": messages,
        "agent_type": agent_list,
        "image_b64": image_b64
    }



def create_supervisor_agent():
    """Create a supervisor agent that can route to multiple agents in parallel using memory"""

    workflow = StateGraph(SupervisorState)

    # Add nodes
    workflow.add_node("supervisor", supervisor_node)
    workflow.add_node("cart_agent", cart_agent)
    workflow.add_node("research_agent", research_agent)
    workflow.add_node("recommendation_agent", recommendation_agent)
    workflow.add_node("order_agent", order_agent)

    # Set entry point
    workflow.set_entry_point("supervisor")

    # New multi-agent routing function
    def route_to_agents(state: SupervisorState) -> list[str]:
        """Route to one or more agents based on multi-label classification"""
        return [f"{agent}_agent" for agent in state.get("agent_type", []) if agent in ["cart", "research", "recommendation", "order"]]

    # Use multi-agent routing
    workflow.add_conditional_edges("supervisor", route_to_agents)

    # Each agent ends after completion
    workflow.add_edge("cart_agent", END)
    workflow.add_edge("research_agent", END)
    workflow.add_edge("recommendation_agent", END)
    workflow.add_edge("order_agent", END)

    return workflow.compile(checkpointer=checkpointer)

# Create the supervisor agent
supervisor_agent = create_supervisor_agent()

def run_supervisor_agent(user_id: int, message: str, thread_id: str = None, image_file=None) -> str:
    """Run the supervisor agent with optional image handling and plant identification"""
    if thread_id is None:
        thread_id = f"user_{user_id}"

    image_b64 = ""
    # Use LLM-based classification for image flag logic
    is_care_query = is_specific_plant_query_llm(message, supervisor_llm)

    if image_file is not None and is_care_query:
        plant_name = identify_plant_from_image(image_file)
        if not plant_name or plant_name.strip().upper() == "DON'T KNOW":
            return "Sorry, I couldn't identify the plant in your image. Please try another image or describe your plant."
        message = f"Image uploaded: Yes. This is a photo of a {plant_name}. {message}"
        image_file.seek(0)
        image_bytes = image_file.read()
        image_b64 = base64.b64encode(image_bytes).decode('utf-8')
    elif is_care_query:
        message = f"Image uploaded: No. {message}"
    # For general queries, do NOT add the image flag

    inputs = {
        "messages": [HumanMessage(content=message)],
        "agent_type": [],
        "image_b64": image_b64
    }

    config = {
        "configurable": {
            "thread_id": thread_id,
            "user_id": user_id
        }
    }

    try:
        result = supervisor_agent.invoke(inputs, config=config)
        print("Supervisor agent result:", result)

        #Extract the last message from each agent's output cleanly
        def extract_combined_ai_messages(agent_outputs: dict) -> str:
            # If it's a single-agent output (flat dict with "messages" key)
            if "messages" in agent_outputs and isinstance(agent_outputs["messages"], list):
                for msg in reversed(agent_outputs["messages"]):
                    if isinstance(msg, AIMessage):
                        return msg.content.strip()
                return "Sorry, I couldn't generate a proper response."

            # If it's multi-agent output, prioritize agents
            priority_order = ["cart_agent", "order_agent", "recommendation_agent", "research_agent"]
            combined = []

            for agent in priority_order:
                if agent in agent_outputs:
                    val = agent_outputs[agent]
                    if isinstance(val, dict) and "messages" in val:
                        for msg in reversed(val["messages"]):
                            if isinstance(msg, AIMessage):
                                combined.append(msg.content.strip())
                                break  # only one response per agent

            return "\n\n".join(combined) if combined else "Sorry, I couldn't generate a proper response."

        return extract_combined_ai_messages(result)

    except Exception as e:
        return f"Sorry, there was an error processing your request: {str(e)}"


def clear_user_memory(user_id: int, thread_id: str = None) -> bool:
    try:
        # Only clear if the checkpointer has a clear method
        if thread_id is None:
            thread_id = f"user_{user_id}"
        if hasattr(checkpointer, "clear"):
            checkpointer.clear({"configurable": {"thread_id": thread_id}})
        return True
    except Exception as e:
        print(f"Error clearing memory: {str(e)}")
        return False

def get_conversation_history(user_id: int, thread_id: str = None) -> list:
    """Get conversation history for a user/thread"""
    try:
        if thread_id is None:
            thread_id = f"user_{user_id}"
        
        # Get the checkpoint for this thread
        checkpoint = checkpointer.get({"configurable": {"thread_id": thread_id}})
        if checkpoint and "messages" in checkpoint:
            return checkpoint["messages"]
        return []
    except Exception as e:
        print(f"Error getting conversation history: {str(e)}")
        return []