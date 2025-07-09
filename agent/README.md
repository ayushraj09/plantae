# Plantae Supervisor Agent

This directory contains the implementation of a supervisor agent that routes user queries between two specialized agents:

1. **Cart Agent** - Handles cart operations, product searches, and store-related queries
2. **Research Agent** - Provides plant care information, watering advice, soil recommendations, etc.

## Architecture

The supervisor agent uses LangGraph to create a workflow that:
1. Analyzes user input to determine intent
2. Routes to the appropriate specialized agent
3. Returns the response to the user

## Files

- `langgraph/agent.py` - Main supervisor agent implementation
- `langgraph/tools.py` - Tools for cart operations and product management
- `views.py` - Django views for the chat interface
- `templates/agent/chat.html` - Chat interface template
- `test_supervisor.py` - Test script to verify functionality

## Features

### Cart Agent Capabilities
- Check cart contents
- Add products to cart
- Search for products
- Handle product variations

### Research Agent Capabilities
- Plant care advice
- Watering frequency recommendations
- Soil type suggestions
- Pest and disease information
- Sunlight requirements
- Nutrient needs

## Usage

### Web Interface
1. Navigate to `/agent/chat/` in your browser
2. Type your query in the chat interface
3. The supervisor will automatically route to the appropriate agent

### Programmatic Usage
```python
from agent.langgraph.agent import run_supervisor_agent

# Cart-related query
response = run_supervisor_agent(user_id=1, message="What's in my cart?")

# Research query
response = run_supervisor_agent(user_id=1, message="How often should I water succulents?")
```

### Testing
Run the test script to verify functionality:
```bash
python agent/test_supervisor.py
```

## Environment Variables

Make sure you have the following environment variables set in your `.env` file:
- `OPENAI_API_KEY` - Your OpenAI API key
- `TAVILY_API_KEY` - Your Tavily API key for web search

## Dependencies

All required dependencies are listed in `requirements.txt`:
- langchain
- langchain-openai
- langchain-tavily
- langgraph
- langgraph-prebuilt

## Troubleshooting

1. **Django Setup**: Ensure Django is properly set up with `DJANGO_SETTINGS_MODULE`
2. **Async Context**: The `DJANGO_ALLOW_ASYNC_UNSAFE` environment variable is set to handle async operations
3. **API Keys**: Verify that your OpenAI and Tavily API keys are valid
4. **Database**: Ensure your Django models (CartItem, Product, Variation) are properly migrated

## Example Queries

### Cart Operations
- "What's in my cart?"
- "Add an adenium plant to my cart"
- "Search for planters"
- "Add a Stone Grey 22 inch planter to my cart"

### Plant Research
- "What soil type is best for succulents?"
- "How often should I water my plants?"
- "What are the best conditions for growing tomatoes?"
- "How to care for indoor plants?"
- "What nutrients do plants need?" 