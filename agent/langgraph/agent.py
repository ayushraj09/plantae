from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from langchain_tavily import TavilySearch
from langgraph.prebuilt import create_react_agent
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import interrupt, Command
from typing import Annotated, TypedDict, List, Dict, Any
from dotenv import load_dotenv
from .tools import get_cart_items, add_to_cart, remove_cart_item, get_my_orders_url, get_orders_by_date, get_order_details_by_id, get_checkout_url, get_most_recent_order, recommend_products_for_plant, list_product_variations
from category.models import Category
from store.models import Product
from PIL import Image
import io
import base64
from openai import OpenAI
from django.core.files.base import ContentFile
from agent.models import ChatImage
from django.utils import timezone
from accounts.models import Account
import difflib
from langchain_core.messages.utils import trim_messages, count_tokens_approximately

load_dotenv()

# Create SQLite-based checkpointer for short-term memory
checkpointer = InMemorySaver()

# --- Plant Identification Function ---
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

def identify_plant_from_image(image_file) -> str:
    """
    Identify plant from uploaded image.
    Returns the plant name or "Unknown" if identification fails.
    """
    try:
        # Resize and prepare the image for OpenAI API (old logic)
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
                    {"type": "input_text", "text": "Analyze the uploaded image and determine if it contains a plant. If a plant is recognized, respond with only the plant name (no extra text). If the image does not contain a recognizable plant, respond with Unknown"},
                ],
            },
            {
                "role": "user",
                "content": [
                    {"type": "input_image", "image_url": image_url},
                ],
            }],
            max_output_tokens=1024,
            temperature=0.1,
            top_p=1,
        )
        # Use output_text as in the old code
        plant_name = response.output_text.strip()
        # Clean up the response
        if plant_name.lower() in ["unknown", "i cannot identify", "i don't know", "unclear", "cannot determine"]:
            plant_name = "Unknown"
        else:
            # Remove any extra text and keep only the plant name (first word)
            plant_name = plant_name.split("\n")[0].strip()
        if plant_name and plant_name != "Unknown":
            print(f"[PLANT-ID] Image recognized by LLM: {plant_name}")
        else:
            print(f"[PLANT-ID] Image NOT recognized by LLM.")
        return plant_name
    except Exception as e:
        print(f"Error in plant identification: {str(e)}")
        return "Unknown"

# --- State Definitions ---
class InputState(TypedDict):
    messages: Annotated[List, add_messages]
    user_id: int
    image_b64: str

class OutputState(TypedDict):
    messages: Annotated[List, add_messages]
    response: str

class OverallState(TypedDict):
    messages: Annotated[List, add_messages]
    user_id: int
    image_b64: str
    agent_type: List[str]
    intermediate_results: Dict[str, Any]
    response: str
    identified_plant: str
    pending_variation_selection: Dict[str, Any]  # For HIL variation selection

def pre_model_hook(state):
    trimmed_messages = trim_messages(
        state["messages"],
        strategy="last",
        token_counter=count_tokens_approximately,
        max_tokens=1024,  # adjust as needed for your LLM's context window
        start_on="human",
        end_on=("human", "tool"),
    )
    return {"llm_input_messages": trimmed_messages}

# --- LLMs and Agents ---
supervisor_llm = ChatOpenAI(model="gpt-4.1-nano-2025-04-14", temperature=0.3)
web_search = TavilySearch(max_results=2)

cart_agent_llm = ChatOpenAI(model="gpt-4.1-nano-2025-04-14", temperature=0.7)
cart_agent = create_react_agent(
    model=cart_agent_llm,
    tools=[get_cart_items, add_to_cart, remove_cart_item, list_product_variations],
    prompt="""You are a helpful plant store assistant. You can ONLY help users with:
    1. Checking their cart contents.
    2. Adding products to their cart (From the query, you need to extract the product name. For example: if user's query is \"Add rose to my cart\" OR \"Add rose plant to my cart\" then you should check both the product name, namely \"rose\" and \"rose plant\". DON'T GET CONFUSED by adding just a plant word. You are smart enough to get the product name correctly.)
    3. Removing items from cart.

    Always be friendly and helpful. When users ask about their cart, use the get_cart_items tool. Format the output of get_cart_items tool in a user friendly way.
    When they want to add products, first use the list_product_variations tool to check if the product has variations. If it has variations, you will need to ask the user to select them. If no variations are required, use the add_to_cart tool directly. Format the output of add_to_cart tool in a user friendly way.
    When they want to remove any product, use the remove_cart_item tool. Format the output of remove_cart_item tool in a user friendly way.
    If the user's question is not about plants or gardening, politely say you can only help with plant-related queries.
    Remember to include the user_id of currently logged in user when using cart-related tools.
    
    IMPORTANT: Remember previous interactions in this conversation. If the user refers to something mentioned earlier, use that context.
    IMPORTANT: If in the context you see previous messages of add to cart of a certain product IGNORE them ALL, ADD TO CART ONLY LATEST PRODUCT.
    """,
    pre_model_hook=pre_model_hook,
)

research_agent = create_react_agent(
    model=ChatOpenAI(model="gpt-4.1-nano-2025-04-14", temperature=0.7),
    tools=[web_search],
    prompt="""You are a plant research assistant.
    You answer ONLY questions about plant care, watering frequency, soil type, nutrients, sunlight, pests, diseases, and any other plant-related information.
    Always use the web_search tool to provide up-to-date and accurate information. Be concise, friendly, and cite your sources if possible.
    If the user's question is not about plants or gardening, politely say you can only help with plant-related queries.
    
    Format the output of web_search tool in a user friendly way.
    
    IMPORTANT: If the user asks for specific plant care or specific recommendations for any specific plant but mentions they don't know the plant's name, or says things like \"I have a plant but don't know what it is\", FIRST CHECK if 'Image uploaded: Yes' is present in the user's message. IF NOT, then ask them to upload a photo of the plant for the best possible advice. For general things you don't need an image of plant. Think from prompt if image is required or not.
    IMPORTANT: Remember previous interactions in this conversation. If the user refers to something mentioned earlier, use that context.
    IMPORTANT: If a specific plant is identified (e.g., "Plant identified: rose"), provide care information specifically for that plant type. Focus on watering, sunlight, soil, and care tips for that particular plant.""",
    pre_model_hook=pre_model_hook,
)

order_agent = create_react_agent(
    model=ChatOpenAI(model="gpt-4.1-nano-2025-04-14", temperature=0.7),
    tools=[get_order_details_by_id, get_my_orders_url, get_orders_by_date, get_checkout_url, get_most_recent_order],
    prompt="""You are a helpful plant store assistant. You can ONLY help users with:
    1. Redirecting them to the 'My Orders' page. Use the get_my_orders_url tool. Always share the link in a clear and user-friendly way.
    2. Providing details about a specific order using the Order ID (such as status, products in that order, total price, and order date). Use the get_order_details_by_id tool.\n3. Fetching a list of orders placed on a specific date. Use the get_orders_by_date tool.\n4. Redirecting them to the 'Checkout' page. Use the get_checkout_url tool. Always share the link in a clear and user-friendly way.\n5. Providing details about the most recent order placed by the user. Use the get_most_recent_order tool for queries about the most recent or latest order.\n\nAlways be friendly and helpful. Format the tool outputs in a clean, user-friendly way.\nIf the user's question is not about plant orders or purchases, politely say you can only assist with plant-related orders.\n\nIMPORTANT: Always include the user_id of currently logged in user when calling any tool.\nRemember previous interactions in this conversation. If the user refers to something mentioned earlier (like a date or order ID), use that context.\n""",
    pre_model_hook=pre_model_hook,
)

# --- Utility Functions ---
def extract_category_llm(user_prompt: str, llm) -> str:
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
    try:
        category = Category.objects.get(category_name__iexact=category_name)
        products = Product.objects.filter(category=category)
        return list(products)
    except Category.DoesNotExist:
        return []

def format_products_for_llm(products: list) -> str:
    if not products:
        return "No products found in this category."
    lines = []
    for p in products:
        description = getattr(p, 'description', '') or 'A great plant store product'
        lines.append(f"- {p.product_name}: {description}")
    return "\n".join(lines)

def recommend_products_llm(user_prompt: str, product_list_str: str, llm) -> str:
    system_prompt = f"""
You are a plant store recommendation assistant.

Here is a list of available products in the relevant category:
{product_list_str}

Recommend the best product(s) for the user's plant or need from the list above.
Do NOT mention the full list of available products in your response.
Just give your recommendation and a short, friendly explanation of why it is suitable.

If no products are found, suggest that the user explore related categories or try a different search.

IMPORTANT: If the user asks for specific plant care or recommendations but doesn't know the plant's name, and 'Image uploaded: Yes' is not present, ask them to upload a photo for the best advice.
"""
    response = llm.invoke([
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_prompt)
    ])
    return response.content

def extract_ai_message(result: Dict) -> str:
    """Helper function to extract AI message content from agent result"""
    for msg in reversed(result["messages"]):
        if isinstance(msg, AIMessage):
            return msg.content
    return ""

# --- Agent Nodes ---
def variation_selection_node(state: OverallState) -> OverallState:
    """
    Node that handles human-in-the-loop variation selection using interrupt.
    This node pauses execution and waits for user to select variations.
    """
    user_id = state["user_id"]
    pending_selection = state.get("pending_variation_selection", {})
    
    if not pending_selection:
        return {"intermediate_results": {"variation_selection": "No pending variation selection"}}
    
    product_name = pending_selection.get("product_name", "")
    variations_data = pending_selection.get("variations", {})
    
    # Use interrupt to pause execution and present variations to user
    user_selections = interrupt({
        "type": "variation_selection",
        "product_name": product_name,
        "variation_dict": variations_data,
        "message": f"Please select your desired variations for {product_name}",
        "user_id": user_id
    })
    
    # When resumed, user_selections will contain the user's choices
    try:
        # Parse the user selections (should be a dict from Command resume)
        if isinstance(user_selections, dict):
            selected_variations = user_selections
        else:
            # Fallback for string input (shouldn't happen with proper Command usage)
            import json
            selected_variations = json.loads(str(user_selections))
        if not selected_variations:
            print(f"[WARNING] variation_selection_node: selected_variations is empty!")
        # Add the product to cart with selected variations
        from .tools import add_to_cart
        result = add_to_cart.invoke({"user_id": user_id, "product_name": product_name, "variation_dict": selected_variations})
        
        return {
            "intermediate_results": {"variation_selection": result},
            "pending_variation_selection": {}  # Clear pending selection
        }
        
    except Exception as e:
        print(f"Error processing variations: {str(e)}")
        return {
            "intermediate_results": {"variation_selection": f"Error processing variations: {str(e)}"},
            "pending_variation_selection": {}
        }

def recommendation_node(state: OverallState) -> OverallState:
    user_prompt = state["messages"][-1].content
    identified_plant = state.get("identified_plant", "")
    
    # If we have an identified plant, use the specialized recommendation tool
    if identified_plant and identified_plant != "Unknown":
        try:
            recommendation = recommend_products_for_plant(identified_plant, user_prompt)
            return {"intermediate_results": {"recommendation": recommendation}}
        except Exception as e:
            print(f"Error in plant-specific recommendation: {e}")
            # Fall back to general recommendation
    
    # General recommendation logic for non-identified plants
    category = extract_category_llm(user_prompt, supervisor_llm)
    products = fetch_products_by_category(category)
    product_list = format_products_for_llm(products)
    recommendation = recommend_products_llm(user_prompt, product_list, supervisor_llm)
    return {"intermediate_results": {"recommendation": recommendation}}

def get_best_product_match(user_product_name):
    from store.models import Product
    all_names = list(Product.objects.values_list('product_name', flat=True))
    matches = difflib.get_close_matches(user_product_name, all_names, n=1, cutoff=0.6)
    if matches:
        return matches[0]
    return None

def cart_agent_node(state: OverallState) -> OverallState:
    user_id = state["user_id"]
    # Use trimmed messages if available, else fallback to full messages
    context_messages = state.get("llm_input_messages") or list(state["messages"])
    # Enhance the latest user message with user_id
    from langchain_core.messages import HumanMessage
    context_messages[-1] = HumanMessage(content=f"User ID: {user_id}. {context_messages[-1].content}")
    result = cart_agent.invoke({"messages": context_messages})

    from store.models import Product, Variation
    # Extract tool_calls from all AIMessage objects in result["messages"]
    tool_calls = []
    from langchain_core.messages import AIMessage
    for msg in result.get("messages", []):
        if isinstance(msg, AIMessage):
            tool_calls.extend(msg.additional_kwargs.get("tool_calls", []))
    product_name = None
    found_variation_needed = False
    variations_data = None
    allowed_types = []
    # Prioritize add_to_cart, but also check list_product_variations
    import json
    for call in tool_calls:
        tool_name = call.get("function", {}).get("name")
        args_str = call.get("function", {}).get("arguments", "{}")
        try:
            args = json.loads(args_str)
        except Exception:
            args = {}
        if "product_name" in args:
            candidate_name = args["product_name"]
            product_qs = Product.objects.filter(product_name__iexact=candidate_name)
            if product_qs.exists():
                product = product_qs.first()
                allowed = product.allowed_variations
                if allowed:
                    allowed_types = [x.strip() for x in allowed.split(",") if x.strip()]
                    has_variations = Variation.objects.filter(product=product, variation_category__in=allowed_types, is_active=True).exists()
                    if has_variations:
                        # If add_to_cart, prioritize this
                        if tool_name == "add_to_cart":
                            product_name = candidate_name
                            found_variation_needed = True
                            variations_data = {}
                            for var_type in allowed_types:
                                values = Variation.objects.filter(product=product, variation_category__iexact=var_type, is_active=True).values_list('variation_value', flat=True).distinct()
                                variations_data[var_type.lower()] = list(values)
                            break  # Prioritize add_to_cart
                        # Otherwise, if not set yet, use list_product_variations
                        elif not found_variation_needed and tool_name == "list_product_variations":
                            product_name = candidate_name
                            found_variation_needed = True
                            variations_data = {}
                            for var_type in allowed_types:
                                values = Variation.objects.filter(product=product, variation_category__iexact=var_type, is_active=True).values_list('variation_value', flat=True).distinct()
                                variations_data[var_type.lower()] = list(values)
    if found_variation_needed and product_name and variations_data:
        return {
            "intermediate_results": {"cart": f"Please select variations for '{product_name}'."},
            "pending_variation_selection": {
                "product_name": product_name,
                "variations": variations_data
            }
        }

    # # --- NEW: Scan tool messages for add_to_cart variation prompts ---
    # from langchain_core.messages import ToolMessage
    # for msg in result.get("messages", []):
    #     if isinstance(msg, ToolMessage) and msg.name == "add_to_cart":
    #         content = msg.content
    #         return {"intermediate_results": {"cart": content}}
    # Otherwise, just return the agent's message
    ai_msg = extract_ai_message(result)
    return {"intermediate_results": {"cart": ai_msg or "Sorry, I couldn't generate a proper response."}}

def research_agent_node(state: OverallState) -> OverallState:
    user_id = state["user_id"]
    identified_plant = state.get("identified_plant", "")
    # Use trimmed messages if available, else fallback to full messages
    context_messages = state.get("llm_input_messages") or list(state["messages"])
    # Only pass the last agent message (if present) and the latest user message
    if len(context_messages) >= 2 and hasattr(context_messages[-2], 'content'):
        context_messages = [context_messages[-2], context_messages[-1]]
    else:
        context_messages = [context_messages[-1]]
    # Enhance the latest user message with user_id and plant identification
    if identified_plant and identified_plant != "Unknown":
        context_messages[-1] = HumanMessage(content=f"User ID: {user_id}. Plant identified: {identified_plant}. {context_messages[-1].content}")
    else:
        context_messages[-1] = HumanMessage(content=f"User ID: {user_id}. {context_messages[-1].content}")
    result = research_agent.invoke({"messages": context_messages})
    ai_msg = extract_ai_message(result)
    return {"intermediate_results": {"research": ai_msg or ""}}

def order_agent_node(state: OverallState) -> OverallState:
    user_id = state["user_id"]
    # Use trimmed messages if available, else fallback to full messages
    context_messages = state.get("llm_input_messages") or list(state["messages"])
    # Create a new message that includes user_id context
    enhanced_message = f"User ID: {user_id}. {context_messages[-1].content}"
    from langchain_core.messages import HumanMessage
    enhanced_messages = context_messages[:-1] + [HumanMessage(content=enhanced_message)]
    result = order_agent.invoke({"messages": enhanced_messages})
    ai_msg = extract_ai_message(result)
    return {"intermediate_results": {"order": ai_msg or ""}}

def supervisor_node(state: OverallState) -> OverallState:
    # If resuming from a variation selection, force cart agent
    if state.get("pending_variation_selection") and state.get("pending_variation_selection") != {}:
        return {"agent_type": ["cart"]}
    messages = state["messages"]
    image_b64 = state.get("image_b64", "")
    identified_plant = state.get("identified_plant", "")
    user_prompt = messages[-1].content.lower()
    
    # Use LLM to decide which single agent to route to
    system_prompt = """You are a supervisor that routes user queries to the most appropriate agent.

Available agents:
1. CART_AGENT - For cart operations (add/view/remove items, shopping cart)
2. ORDER_AGENT - For order history, order details, order status
3. RECOMMENDATION_AGENT - For product suggestions, recommendations, fertilizers, when user wants to buy something
4. RESEARCH_AGENT - For plant care, watering, sunlight, soil, diseases, general plant questions

IMPORTANT: Choose only ONE agent that best fits the user's request. Respond with exactly one of: cart, order, recommendation, research
IMPORTANT: If the previous agent response was a product recommendation and the user now says things like "add that to my cart", "buy this", "add to cart", etc., route to the cart agent.

Examples:
- "What's in my cart" → cart
- "Add maize seeds" → cart  
- "My recent orders" → order
- "Recommend indoor plants" → recommendation
- "How to water succulents" → research
- "Show me fertilizers" → recommendation
- "Order status" → order
- "Suggest fertilizer for my rose" → recommendation
- "How to care for my rose" → research
"""
    
    # Add image and plant identification context if present
    if image_b64 and identified_plant and identified_plant != "Unknown":
        system_prompt += f"\n\nNOTE: User has uploaded an image of a {identified_plant}. Use this information to route appropriately:"
        system_prompt += f"\n- If they ask for fertilizer, similar plants, or want to buy products for their {identified_plant} → RECOMMENDATION_AGENT"
        system_prompt += f"\n- If they ask for care tips, watering, sunlight, or general care for their {identified_plant} → RESEARCH_AGENT"
    elif image_b64:
        system_prompt += "\n\nNOTE: User has uploaded an image but plant identification failed. Route based on their text query."
    
    decision_messages = [
        SystemMessage(content=system_prompt),
        messages[-1]
    ]
    
    response = supervisor_llm.invoke(decision_messages)
    raw_decision = response.content.strip().lower()
    
    # Extract the agent type from the response
    agent_type = "research"  # default
    for agent in ["cart", "order", "recommendation", "research"]:
        if agent in raw_decision:
            agent_type = agent
            break
    
    return {"agent_type": [agent_type]}

def response_node(state: OverallState) -> OverallState:
    priority_order = ["cart", "order", "recommendation", "research", "variation_selection"]
    combined = []
    for agent in priority_order:
        if agent in state.get("intermediate_results", {}):
            combined.append(state["intermediate_results"][agent])
    response = "\n\n".join([c for c in combined if c]) or "Sorry, I couldn't generate a proper response."
    return {"response": response}

# --- Graph Construction ---
def create_supervisor_agent():
    workflow = StateGraph(
        OverallState,
        input=InputState,
        output=OutputState,
    )
    workflow.add_node("supervisor", supervisor_node)
    workflow.add_node("cart_agent", cart_agent_node)
    workflow.add_node("variation_selection", variation_selection_node)
    workflow.add_node("research_agent", research_agent_node)
    workflow.add_node("recommendation_agent", recommendation_node)
    workflow.add_node("order_agent", order_agent_node)
    workflow.add_node("response", response_node)
    workflow.set_entry_point("supervisor")
    
    def route_to_agents(state: OverallState) -> List[str]:
        agent_list = []
        for agent in state.get("agent_type", []):
            if agent in ["cart", "research", "recommendation", "order"]:
                agent_list.append(f"{agent}_agent")
        # If cart agent was called and there's pending variation selection, route to variation_selection
        if "cart_agent" in agent_list and state.get("pending_variation_selection") and state.get("pending_variation_selection") != {}:
            agent_list.remove("cart_agent")
            agent_list.append("variation_selection")
        return agent_list or ["research_agent"]
    
    def cart_agent_conditional(state: OverallState) -> str:
        if state.get("pending_variation_selection") and state.get("pending_variation_selection") != {}:
            return "variation_selection"
        return "response"

    workflow.add_conditional_edges("supervisor", route_to_agents)
    workflow.add_conditional_edges("cart_agent", cart_agent_conditional)
    workflow.add_edge("variation_selection", "response")
    workflow.add_edge("research_agent", "response")
    workflow.add_edge("recommendation_agent", "response")
    workflow.add_edge("order_agent", "response")
    workflow.add_edge("response", END)
    return workflow.compile(checkpointer=checkpointer)

supervisor_agent = create_supervisor_agent()

# --- Entrypoint ---
def run_supervisor_agent(user_id: int, message: str, thread_id: str = None, image_file=None, resume_data=None, messages=None) -> dict:
    
    image_b64 = ""
    identified_plant = ""
    
    if image_file is not None:
        try:
            # Resize image if needed
            image = Image.open(image_file)
            max_size = 1024
            if max(image.size) > max_size:
                image.thumbnail((max_size, max_size))
                output = io.BytesIO()
                image.save(output, format=image.format)
                output.seek(0)
                resized_file = output
            else:
                image_file.seek(0)
                resized_file = image_file

            # Save resized image to DB
            resized_file.seek(0)
            django_file = ContentFile(resized_file.read())
            ext = image.format.lower() if image.format else 'jpg'
            filename = f"user_{user_id}_chat_{timezone.now().strftime('%Y%m%d%H%M%S')}.{ext}"
            
            try:
                user_obj = Account.objects.get(id=user_id)
            except Account.DoesNotExist:
                return {"response": "Sorry, the user account was not found. Please contact support."}
            
            chat_image = ChatImage.objects.create(user=user_obj)
            chat_image.image.save(filename, django_file, save=True)

            # For base64 encoding and plant identification
            resized_file.seek(0)
            image_bytes = resized_file.read()
            image_b64 = base64.b64encode(image_bytes).decode('utf-8')
            
            # Identify plant from image
            resized_file.seek(0)
            identified_plant = identify_plant_from_image(resized_file)
            if identified_plant and identified_plant != "Unknown":
                print(f"[PLANT-ID] Image recognized by LLM: {identified_plant}")
            else:
                print(f"[PLANT-ID] Image NOT recognized by LLM.")

            # Always add plant/image context to the user message
            if identified_plant and identified_plant != "Unknown":
                message = f"Image uploaded: Yes. Plant identified: {identified_plant}. {message}"
            else:
                message = f"Image uploaded: Yes. {message}"
            
        except Exception as e:
            print(f"Error processing image: {e}")
    
    # If resuming from interrupt, use Command
    if resume_data is not None:
        # Force agent_type to ['cart'] if resuming a variation selection
        inputs = Command(resume=resume_data)
        # The graph will use the previous state, but we want to ensure agent_type is ['cart']
        # This is handled in the state update logic of the graph (if needed, can patch in the node)
    else:
        # Use provided messages if available, else default to latest message
        if messages is not None:
            context_messages = messages
        else:
            from langchain_core.messages import HumanMessage
            context_messages = [HumanMessage(content=message)]
        inputs = {
            "messages": context_messages,
            "user_id": user_id,
            "image_b64": image_b64,
            "agent_type": [],
            "intermediate_results": {},
            "response": "",
            "identified_plant": identified_plant,
            "pending_variation_selection": {}
        }
    
    config = {
        "configurable": {
            "thread_id": thread_id or f"user_{user_id}"
        }
    }
    
    try:
        result = supervisor_agent.invoke(inputs, config=config)
        
        # Check if there's an interrupt
        if "__interrupt__" in result:
            return {
                "interrupt": True,
                "interrupt_data": result["__interrupt__"][0].value,
                "response": "Waiting for user input..."
            }
        
        return {
            "interrupt": False,
            "response": result.get("response") or "Sorry, I couldn't generate a proper response."
        }
        
    except Exception as e:
        print(f"Exception occurred: {str(e)}")
        return {
            "interrupt": False,
            "response": f"Sorry, there was an error processing your request: {str(e)}"
        }

# --- Memory Management ---
def clear_user_memory(user_id: int, thread_id: str = None) -> bool:
    try:
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

def is_variation_exist(product_name: str) -> bool:
    from store.models import Product, Variation
    product_qs = Product.objects.filter(product_name__icontains=product_name)
    if not product_qs.exists():
        return False
    product = product_qs.first()
    allowed = product.allowed_variations
    if not allowed:
        return False
    allowed_types = [x.strip() for x in allowed.split(",") if x.strip()]
    if not allowed_types:
        return False
    return Variation.objects.filter(product=product, variation_category__in=allowed_types, is_active=True).exists()