# Letta AI Agent Framework - Master Cheatsheet

## 🚀 Quick Start

### Installation & Setup
```python
# Install Letta client
pip install letta-client

# Initialize client
from letta_client import Letta

# Cloud setup
client = Letta(
    project="YOUR_PROJECT",
    token="YOUR_TOKEN"
)

# Local server setup
client = Letta(base_url="http://localhost:8283")
```

### Create Your First Agent
```python
# Basic agent creation
agent = client.agents.create(
    name="my_assistant",
    model="openai/gpt-4.1",
    embedding="openai/text-embedding-3-small",
    memory_blocks=[
        {"label": "human", "value": "User is a software developer"},
        {"label": "persona", "value": "I am a helpful coding assistant"}
    ],
    tools=["web_search", "run_code"]
)

# Send first message
response = client.agents.messages.create(
    agent_id=agent.id,
    messages=[{"role": "user", "content": "Hello! Can you help me debug this Python code?"}]
)
```

## 📚 Documentation Structure

This master cheatsheet references these specialized guides:

1. **[letta-agent-management.md](./letta-agent-management.md)** - Agent CRUD, configuration, templates
2. **[letta-memory-management.md](./letta-memory-management.md)** - Core memory, blocks, archival memory
3. **[letta-tool-management.md](./letta-tool-management.md)** - Tool creation, attachment, MCP integration
4. **[letta-messages-conversations.md](./letta-messages-conversations.md)** - Messaging, streaming, async operations
5. **[letta-organization-users.md](./letta-organization-users.md)** - Projects, users, permissions, billing
6. **[letta-sources-knowledge.md](./letta-sources-knowledge.md)** - Knowledge bases, file processing, search

## 🏗️ Core Architecture

### System Components
```
Organization
├── Projects
│   ├── Agents
│   │   ├── Memory (Core + Archival)
│   │   ├── Tools (Built-in + Custom + MCP)
│   │   ├── Sources (Knowledge bases)
│   │   └── Messages/Conversations
│   ├── Sources (Shared knowledge)
│   └── Tools (Project-specific)
├── Users & Teams
└── Settings & Billing
```

### Agent Architecture
```
Agent
├── Core Memory
│   ├── Human Block (user context)
│   ├── Persona Block (agent personality)
│   └── Custom Blocks (domain-specific)
├── Archival Memory (passages)
├── Attached Tools
├── Attached Sources
└── Message History
```

## 🔧 Essential Operations

### Agent Lifecycle
```python
# Create → Configure → Use → Monitor → Update → Delete

# 1. Create
agent = client.agents.create(name="assistant", model="openai/gpt-4.1")

# 2. Configure
client.agents.tools.attach(agent_id=agent.id, tool_id="web_search")
client.agents.sources.attach(agent_id=agent.id, source_id="docs_source")

# 3. Use
response = client.agents.messages.create(
    agent_id=agent.id,
    messages=[{"role": "user", "content": "Help me with analysis"}]
)

# 4. Monitor
messages = client.agents.messages.list(agent_id=agent.id)
analytics = client.analytics.agents.get(agent_id=agent.id)

# 5. Update
client.agents.update(agent_id=agent.id, name="updated_assistant")

# 6. Delete
client.agents.delete(agent_id=agent.id)
```

### Memory Management
```python
# Core memory operations
core_memory = client.agents.core_memory.retrieve(agent_id=agent.id)
client.agents.blocks.update(
    agent_id=agent.id,
    block_label="human",
    value="Updated user context"
)

# Archival memory operations
passages = client.agents.passages.list(agent_id=agent.id, search="query")
client.agents.passages.create(
    agent_id=agent.id,
    text="Important information to remember"
)
```

### Tool Operations
```python
# List available tools
tools = client.tools.list()

# Create custom tool
tool = client.tools.create(
    name="calculator",
    source_code=function_code,
    description="Mathematical calculator"
)

# Attach/detach tools
client.agents.tools.attach(agent_id=agent.id, tool_id=tool.id)
client.agents.tools.detach(agent_id=agent.id, tool_id=tool.id)
```

### Knowledge Management
```python
# Create source
source = client.sources.create(
    name="Documentation",
    description="Product documentation"
)

# Upload files
client.sources.files.upload(
    source_id=source.id,
    file_path="/path/to/document.pdf"
)

# Attach to agent
client.agents.sources.attach(agent_id=agent.id, source_id=source.id)

# Search knowledge
results = client.sources.passages.search(
    source_id=source.id,
    query="installation instructions"
)
```

## 🎛️ Advanced Patterns

### Multi-Agent System
```python
# Create specialized agents
agents = {
    "researcher": client.agents.create(
        name="research_agent",
        tools=["web_search", "data_analysis"],
        sources=["research_papers_source"]
    ),
    "writer": client.agents.create(
        name="writing_agent", 
        tools=["document_generator", "style_checker"],
        sources=["style_guide_source"]
    ),
    "reviewer": client.agents.create(
        name="review_agent",
        tools=["quality_checker", "fact_verifier"]
    )
}

# Coordinate agents
def research_and_write_report(topic: str):
    # Step 1: Research
    research = client.agents.messages.create(
        agent_id=agents["researcher"].id,
        messages=[{"role": "user", "content": f"Research: {topic}"}]
    )
    
    # Step 2: Write based on research
    draft = client.agents.messages.create(
        agent_id=agents["writer"].id,
        messages=[{
            "role": "user", 
            "content": f"Write report on {topic} using: {research}"
        }]
    )
    
    # Step 3: Review and refine
    final = client.agents.messages.create(
        agent_id=agents["reviewer"].id,
        messages=[{
            "role": "user",
            "content": f"Review and improve: {draft}"
        }]
    )
    
    return final
```

### Streaming with Real-time Processing
```python
def handle_streaming_conversation(agent_id: str, user_message: str):
    """
    Handle streaming conversation with real-time processing.
    """
    print(f"User: {user_message}")
    print("Assistant: ", end="", flush=True)
    
    full_response = ""
    tool_calls = []
    
    stream = client.agents.messages.create_stream(
        agent_id=agent_id,
        messages=[{"role": "user", "content": user_message}]
    )
    
    for chunk in stream:
        chunk_type = chunk.get("type")
        
        if chunk_type == "message_delta":
            content = chunk.get("content", "")
            full_response += content
            print(content, end="", flush=True)
            
        elif chunk_type == "tool_call_start":
            tool_name = chunk.get("tool_name")
            print(f"\n[🔧 Using {tool_name}...]", end="", flush=True)
            
        elif chunk_type == "tool_call_result":
            print(" ✅", end="", flush=True)
            tool_calls.append(chunk)
    
    print("\n")
    return {"response": full_response, "tools_used": tool_calls}
```

### Dynamic Tool Creation
```python
def create_api_integration_tool(api_name: str, base_url: str, endpoints: dict):
    """
    Dynamically create API integration tool.
    """
    tool_source = f'''
import requests
import json

def call_{api_name.lower()}_api(endpoint: str, method: str = "GET", data: dict = None, headers: dict = None) -> dict:
    """
    Call {api_name} API.
    
    Available endpoints: {list(endpoints.keys())}
    """
    if endpoint not in {list(endpoints.keys())}:
        return {{"error": f"Unknown endpoint: {{endpoint}}"}}
    
    url = "{base_url}" + endpoints[endpoint]
    
    try:
        response = requests.request(
            method=method.upper(),
            url=url,
            json=data,
            headers=headers or {{}}
        )
        response.raise_for_status()
        
        return {{
            "success": True,
            "status_code": response.status_code,
            "data": response.json() if response.content else {{}}
        }}
    except Exception as e:
        return {{
            "success": False,
            "error": str(e)
        }}
    '''
    
    return client.tools.create(
        name=f"{api_name.lower()}_client",
        description=f"Client for {api_name} API integration",
        source_code=tool_source,
        pip_requirements=["requests"],
        tags=["api", "integration", api_name.lower()]
    )
```

### Knowledge Pipeline
```python
def setup_knowledge_pipeline(project_id: str, docs_directory: str):
    """
    Set up automated knowledge processing pipeline.
    """
    # Create source
    source = client.sources.create(
        name="Auto-processed Documentation",
        description="Automatically processed documentation",
        project_id=project_id,
        processing_config={
            "chunk_size": 1000,
            "chunk_overlap": 200,
            "extract_metadata": True,
            "ocr_enabled": True
        }
    )
    
    # Batch upload files
    import os
    uploaded_files = []
    
    for root, dirs, files in os.walk(docs_directory):
        for file in files:
            if file.endswith(('.pdf', '.docx', '.txt', '.md')):
                file_path = os.path.join(root, file)
                
                upload = client.sources.files.upload(
                    source_id=source.id,
                    file_path=file_path,
                    metadata={
                        "directory": os.path.relpath(root, docs_directory),
                        "auto_processed": True,
                        "processed_at": "2024-01-20T10:00:00Z"
                    }
                )
                uploaded_files.append(upload)
    
    # Monitor processing
    def monitor_processing():
        while True:
            all_processed = True
            for file_upload in uploaded_files:
                file_info = client.sources.files.get(
                    source_id=source.id,
                    file_id=file_upload["id"]
                )
                if file_info["status"] not in ["completed", "failed"]:
                    all_processed = False
                    break
            
            if all_processed:
                break
            
            time.sleep(10)
        
        print(f"Knowledge pipeline complete. Source: {source.id}")
    
    return source, monitor_processing
```

## 📊 Monitoring & Analytics

### Performance Monitoring
```python
def monitor_agent_performance(agent_id: str, days: int = 7):
    """
    Monitor agent performance metrics.
    """
    import datetime
    
    end_date = datetime.datetime.now()
    start_date = end_date - datetime.timedelta(days=days)
    
    # Get message analytics
    messages = client.agents.messages.list(
        agent_id=agent_id,
        limit=1000,
        after=start_date.isoformat()
    )
    
    metrics = {
        "total_messages": len(messages),
        "user_messages": len([m for m in messages if m["role"] == "user"]),
        "assistant_messages": len([m for m in messages if m["role"] == "assistant"]),
        "tool_calls": 0,
        "average_response_time": 0,
        "most_used_tools": {},
        "error_rate": 0
    }
    
    response_times = []
    errors = 0
    
    for i, message in enumerate(messages):
        if message["role"] == "assistant" and i > 0:
            # Calculate response time (if timestamps available)
            if "created_at" in message and "created_at" in messages[i-1]:
                # Response time calculation logic
                pass
        
        # Count tool calls
        if message.get("tool_calls"):
            metrics["tool_calls"] += len(message["tool_calls"])
            for tool_call in message["tool_calls"]:
                tool_name = tool_call.get("function", {}).get("name")
                if tool_name:
                    metrics["most_used_tools"][tool_name] = \
                        metrics["most_used_tools"].get(tool_name, 0) + 1
        
        # Count errors
        if message.get("type") == "error":
            errors += 1
    
    metrics["error_rate"] = errors / len(messages) if messages else 0
    
    return metrics
```

### Cost Tracking
```python
def track_usage_costs(project_id: str, month: str):
    """
    Track usage costs for budgeting.
    """
    usage = client.billing.usage.get(
        project_id=project_id,
        start_date=f"{month}-01",
        end_date=f"{month}-31"
    )
    
    cost_breakdown = {
        "total_cost": usage.get("total_cost", 0),
        "model_costs": usage.get("model_usage", {}),
        "message_volume": usage.get("message_count", 0),
        "tool_executions": usage.get("tool_calls", 0),
        "storage_costs": usage.get("storage_cost", 0),
        "embedding_costs": usage.get("embedding_cost", 0)
    }
    
    # Cost optimization suggestions
    suggestions = []
    
    if cost_breakdown["total_cost"] > 500:  # $500 threshold
        suggestions.append("Consider reviewing model usage for optimization")
    
    if cost_breakdown["message_volume"] > 10000:
        suggestions.append("High message volume - consider implementing caching")
    
    expensive_models = {k: v for k, v in cost_breakdown["model_costs"].items() if v > 100}
    if expensive_models:
        suggestions.append(f"High-cost models: {list(expensive_models.keys())}")
    
    return cost_breakdown, suggestions
```

## 🔒 Security & Best Practices

### Security Checklist
```python
def security_audit(project_id: str):
    """
    Perform security audit of project resources.
    """
    issues = []
    
    # Check API key permissions
    api_keys = client.api_keys.list(project_id=project_id)
    for key in api_keys:
        if key.get("expires_at") is None:
            issues.append(f"API key {key['name']} has no expiration")
        
        if "*" in key.get("scopes", []):
            issues.append(f"API key {key['name']} has overly broad permissions")
    
    # Check user permissions
    users = client.users.list(project_id=project_id)
    admin_count = len([u for u in users if u["role"] == "admin"])
    if admin_count > 3:
        issues.append(f"Too many admin users: {admin_count}")
    
    # Check agent configurations
    agents = client.agents.list(project_id=project_id)
    for agent in agents:
        # Check for sensitive data in memory blocks
        core_memory = client.agents.core_memory.retrieve(agent_id=agent["id"])
        for block in core_memory.get("blocks", []):
            if any(keyword in block.get("value", "").lower() 
                   for keyword in ["password", "key", "secret", "token"]):
                issues.append(f"Agent {agent['name']} may contain sensitive data")
    
    return issues
```

### Data Privacy Compliance
```python
def ensure_data_privacy(agent_id: str):
    """
    Ensure agent complies with data privacy requirements.
    """
    # Add privacy-focused memory block
    privacy_guidelines = """
    Privacy Guidelines:
    - Never store or remember personal identifiable information (PII)
    - Don't retain sensitive user data beyond the conversation
    - Anonymize any examples or references to user data
    - Comply with GDPR, CCPA, and other privacy regulations
    """
    
    client.agents.blocks.create(
        agent_id=agent_id,
        label="privacy_guidelines",
        value=privacy_guidelines,
        read_only=True  # Agent cannot modify these guidelines
    )
    
    # Regular memory cleanup
    def cleanup_sensitive_data():
        passages = client.agents.passages.list(agent_id=agent_id, limit=1000)
        
        sensitive_patterns = [
            r'\b\d{3}-\d{2}-\d{4}\b',  # SSN
            r'\b\d{4}[- ]?\d{4}[- ]?\d{4}[- ]?\d{4}\b',  # Credit card
            r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'  # Email
        ]
        
        import re
        for passage in passages:
            for pattern in sensitive_patterns:
                if re.search(pattern, passage["text"]):
                    # Remove or anonymize sensitive passage
                    client.agents.passages.delete(
                        agent_id=agent_id,
                        passage_id=passage["id"]
                    )
                    break
    
    return cleanup_sensitive_data
```

## 🚨 Error Handling & Recovery

### Comprehensive Error Handling
```python
class LettaOperationError(Exception):
    """Custom exception for Letta operations."""
    pass

def safe_letta_operation(operation_func, *args, max_retries=3, **kwargs):
    """
    Execute Letta operation with comprehensive error handling.
    """
    import time
    import random
    
    for attempt in range(max_retries):
        try:
            return operation_func(*args, **kwargs)
            
        except Exception as e:
            error_msg = str(e).lower()
            
            # Handle specific error types
            if "rate limit" in error_msg:
                wait_time = (2 ** attempt) + random.uniform(0, 1)
                print(f"Rate limited. Waiting {wait_time:.1f}s...")
                time.sleep(wait_time)
                continue
                
            elif "context length" in error_msg:
                print("Context length exceeded. Consider resetting conversation.")
                raise LettaOperationError("Context length exceeded")
                
            elif "authentication" in error_msg:
                print("Authentication failed. Check your API key.")
                raise LettaOperationError("Authentication failed")
                
            elif "not found" in error_msg:
                print("Resource not found. Check IDs.")
                raise LettaOperationError("Resource not found")
                
            elif attempt == max_retries - 1:
                print(f"Operation failed after {max_retries} attempts: {e}")
                raise LettaOperationError(f"Operation failed: {e}")
            
            else:
                wait_time = 2 ** attempt
                print(f"Operation failed, retrying in {wait_time}s... ({attempt + 1}/{max_retries})")
                time.sleep(wait_time)
    
    raise LettaOperationError("Max retries exceeded")

# Usage examples
agent = safe_letta_operation(
    client.agents.create,
    name="test_agent",
    model="openai/gpt-4.1"
)

response = safe_letta_operation(
    client.agents.messages.create,
    agent_id=agent.id,
    messages=[{"role": "user", "content": "Hello"}]
)
```

## 📋 Quick Reference

### Common Commands
```python
# Agents
agents = client.agents.list()
agent = client.agents.get(agent_id="id")
client.agents.delete(agent_id="id")

# Messages  
response = client.agents.messages.create(agent_id="id", messages=[...])
messages = client.agents.messages.list(agent_id="id")

# Tools
tools = client.tools.list()
client.agents.tools.attach(agent_id="id", tool_id="tool_id")

# Sources
sources = client.sources.list()
client.sources.files.upload(source_id="id", file_path="path")

# Memory
core_memory = client.agents.core_memory.retrieve(agent_id="id")
client.agents.blocks.update(agent_id="id", block_label="human", value="...")
```

### Environment Variables
```bash
# Configuration
export LETTA_API_KEY="your_api_key"
export LETTA_PROJECT="your_project" 
export LETTA_BASE_URL="https://api.letta.com"  # or local server

# Optional settings
export LETTA_TIMEOUT=30
export LETTA_MAX_RETRIES=3
export LETTA_LOG_LEVEL="INFO"
```

### Model Options
```python
# Popular model configurations
MODELS = {
    "fast": "openai/gpt-3.5-turbo",
    "balanced": "openai/gpt-4.1", 
    "powerful": "openai/gpt-4o",
    "claude_fast": "anthropic/claude-3-haiku",
    "claude_balanced": "anthropic/claude-3-sonnet",
    "claude_powerful": "anthropic/claude-3-opus"
}

EMBEDDINGS = {
    "small": "openai/text-embedding-3-small",
    "large": "openai/text-embedding-3-large"
}
```

## 🎯 Use Case Templates

### Customer Support Agent
```python
support_agent = client.agents.create(
    name="customer_support",
    model="openai/gpt-4.1",
    memory_blocks=[
        {"label": "persona", "value": "Friendly, helpful customer support representative"},
        {"label": "guidelines", "value": "Always be patient, empathetic, and solution-focused"}
    ],
    tools=["web_search", "ticket_system"],
    sources=["faq_source", "product_docs_source"],
    tags=["customer-service", "support"]
)
```

### Code Assistant Agent  
```python
code_agent = client.agents.create(
    name="coding_assistant", 
    model="openai/gpt-4.1",
    memory_blocks=[
        {"label": "persona", "value": "Expert programming assistant"},
        {"label": "context", "value": "Specializes in Python, JavaScript, and system design"}
    ],
    tools=["run_code", "file_manager", "git_operations"],
    sources=["documentation_source", "code_examples_source"],
    tags=["development", "coding", "technical"]
)
```

### Research Agent
```python
research_agent = client.agents.create(
    name="research_analyst",
    model="openai/gpt-4.1", 
    memory_blocks=[
        {"label": "persona", "value": "Thorough research analyst"},
        {"label": "methodology", "value": "Evidence-based analysis with multiple sources"}
    ],
    tools=["web_search", "data_analysis", "pdf_reader"],
    sources=["research_papers_source", "industry_reports_source"],
    tags=["research", "analysis", "data"]
)
```

This master cheatsheet provides a comprehensive overview of Letta's capabilities. Refer to the specialized cheatsheets for detailed information on each component.

## 📞 Support & Resources

- **Documentation**: https://docs.letta.com
- **API Reference**: https://docs.letta.com/api-reference
- **GitHub Issues**: Report bugs and feature requests
- **Community**: Join the Letta community for discussions
- **Status Page**: Monitor service status and updates