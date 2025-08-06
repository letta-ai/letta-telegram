# Letta Messages & Conversations - Comprehensive Cheatsheet

## Message System Overview

Letta agents handle multiple types of messages:
1. **User Messages**: Input from users
2. **Assistant Messages**: Agent responses
3. **System Messages**: System-level communications
4. **Tool Call Messages**: Tool execution calls
5. **Reasoning Messages**: Agent internal reasoning

## Sending Messages

### Basic Message Sending
```python
# Send a simple message to agent
response = client.agents.messages.create(
    agent_id="agent_123",
    messages=[
        {"role": "user", "content": "Hello, how can you help me today?"}
    ]
)

# Response contains:
# - Agent's reply message
# - Any tool calls made
# - Updated memory state
# - Processing steps taken
```

### Advanced Message Options
```python
response = client.agents.messages.create(
    agent_id="agent_123",
    messages=[
        {"role": "user", "content": "Analyze this data and create a report"}
    ],
    stream=False,  # Set to True for streaming
    include_final_message=True,  # Include final response
    group_id="conversation_group_1",  # Group related messages
    use_assistant_message=True,  # Include assistant messages in response
    return_message_object=True  # Return full message objects
)
```

### Multi-Message Conversations
```python
# Send multiple messages in sequence
messages = [
    {"role": "user", "content": "I need help with a Python project"},
    {"role": "assistant", "content": "I'd be happy to help! What specific aspect?"},
    {"role": "user", "content": "I need to process CSV files and generate reports"}
]

response = client.agents.messages.create(
    agent_id="agent_123",
    messages=messages
)
```

## Streaming Messages

### Basic Streaming
```python
# Stream agent responses in real-time
for chunk in client.agents.messages.create_stream(
    agent_id="agent_123",
    messages=[{"role": "user", "content": "Explain machine learning concepts"}]
):
    if chunk.get("type") == "message_delta":
        print(chunk.get("content", ""), end="")
    elif chunk.get("type") == "tool_call":
        print(f"\n[Tool: {chunk.get('tool_name')}]")
```

### Advanced Streaming with Processing
```python
def handle_stream_response(agent_id: str, user_message: str):
    """
    Handle streaming response with different event types.
    """
    stream = client.agents.messages.create_stream(
        agent_id=agent_id,
        messages=[{"role": "user", "content": user_message}]
    )
    
    full_response = ""
    tool_calls = []
    
    for chunk in stream:
        chunk_type = chunk.get("type")
        
        if chunk_type == "message_delta":
            content = chunk.get("content", "")
            full_response += content
            print(content, end="", flush=True)
            
        elif chunk_type == "tool_call_start":
            tool_name = chunk.get("tool_name")
            print(f"\n🔧 Using tool: {tool_name}")
            
        elif chunk_type == "tool_call_result":
            result = chunk.get("result")
            tool_calls.append(result)
            print(f"✅ Tool completed")
            
        elif chunk_type == "reasoning":
            reasoning = chunk.get("content")
            print(f"💭 Reasoning: {reasoning}")
            
        elif chunk_type == "error":
            error = chunk.get("error")
            print(f"❌ Error: {error}")
            break
    
    return {
        "full_response": full_response,
        "tool_calls": tool_calls
    }
```

## Message Retrieval and History

### List Messages
```python
# Get recent messages
messages = client.agents.messages.list(
    agent_id="agent_123",
    limit=50  # Number of messages to retrieve
)

# Get messages with filters
messages = client.agents.messages.list(
    agent_id="agent_123",
    after="message_id_cursor",  # Pagination cursor
    before="message_id_end",    # End cursor
    limit=25,
    group_id="conversation_1",  # Filter by conversation group
    use_assistant_message=True  # Include assistant messages
)
```

### Message Pagination
```python
# Paginate through message history
def get_all_messages(agent_id: str, batch_size: int = 100) -> list:
    """
    Retrieve all messages for an agent with pagination.
    """
    all_messages = []
    after_cursor = None
    
    while True:
        batch = client.agents.messages.list(
            agent_id=agent_id,
            limit=batch_size,
            after=after_cursor
        )
        
        if not batch:
            break
            
        all_messages.extend(batch)
        after_cursor = batch[-1]["id"]  # Use last message ID as cursor
        
        if len(batch) < batch_size:
            break  # No more messages
    
    return all_messages
```

### Search Messages
```python
# Search messages by content (if supported)
search_results = client.agents.messages.search(
    agent_id="agent_123",
    query="database optimization",
    limit=20
)
```

## Asynchronous Messaging

### Send Async Message
```python
# Send message asynchronously
async_response = client.agents.messages.create_async(
    agent_id="agent_123",
    messages=[{"role": "user", "content": "Process this large dataset"}],
    callback_url="https://your-app.com/webhook/message-complete"  # Optional webhook
)

# Returns job ID for tracking
job_id = async_response["job_id"]
```

### Track Async Jobs
```python
# Check async job status
job_status = client.jobs.get(job_id="job_123")

# Job status includes:
# - status: "pending", "running", "completed", "failed"
# - progress: percentage completion
# - result: final result when completed
# - error: error details if failed

# Wait for job completion
import time

def wait_for_job_completion(job_id: str, timeout: int = 300) -> dict:
    """
    Wait for async job to complete with timeout.
    """
    start_time = time.time()
    
    while time.time() - start_time < timeout:
        job = client.jobs.get(job_id=job_id)
        status = job.get("status")
        
        if status == "completed":
            return job.get("result")
        elif status == "failed":
            raise Exception(f"Job failed: {job.get('error')}")
        
        time.sleep(2)  # Poll every 2 seconds
    
    raise TimeoutError(f"Job {job_id} did not complete within {timeout} seconds")
```

## Message Groups and Organization

### Create Message Groups
```python
# Create conversation group
group = client.agents.groups.create(
    agent_id="agent_123",
    group_name="project_discussion",
    description="Messages related to project planning"
)

# Send messages to specific group
response = client.agents.messages.create(
    agent_id="agent_123",
    messages=[{"role": "user", "content": "Let's discuss the project timeline"}],
    group_id=group["id"]
)
```

### Manage Message Groups
```python
# List all groups for agent
groups = client.agents.groups.list(agent_id="agent_123")

# Get messages from specific group
group_messages = client.agents.messages.list(
    agent_id="agent_123",
    group_id="group_123"
)

# Update group
updated_group = client.agents.groups.update(
    agent_id="agent_123",
    group_id="group_123",
    group_name="updated_project_discussion",
    description="Updated description"
)

# Delete group (messages remain, just ungrouped)
client.agents.groups.delete(
    agent_id="agent_123",
    group_id="group_123"
)
```

## Message Types and Processing

### Handle Different Message Types
```python
def process_message_response(response: dict):
    """
    Process different types of messages in agent response.
    """
    messages = response.get("messages", [])
    
    for message in messages:
        msg_type = message.get("type")
        
        if msg_type == "user_message":
            print(f"User: {message['content']}")
            
        elif msg_type == "assistant_message":
            print(f"Assistant: {message['content']}")
            
        elif msg_type == "tool_call":
            print(f"🔧 Tool: {message['tool_name']}")
            print(f"   Args: {message['arguments']}")
            print(f"   Result: {message['result']}")
            
        elif msg_type == "reasoning":
            print(f"💭 Internal reasoning: {message['content']}")
            
        elif msg_type == "system_message":
            print(f"🖥️  System: {message['content']}")
            
        elif msg_type == "error":
            print(f"❌ Error: {message['content']}")
```

### Message Metadata
```python
# Extract message metadata
def analyze_message_metadata(message: dict):
    """
    Analyze message metadata and context.
    """
    metadata = {
        "id": message.get("id"),
        "timestamp": message.get("created_at"),
        "role": message.get("role"),
        "content_length": len(message.get("content", "")),
        "has_tool_calls": bool(message.get("tool_calls")),
        "group_id": message.get("group_id"),
        "user_id": message.get("user_id"),
        "tokens_used": message.get("token_count", 0)
    }
    
    return metadata
```

## Voice and Audio Messages

### Voice Message Handling
```python
# Send voice message (if supported)
voice_response = client.agents.voice.create(
    agent_id="agent_123",
    audio_data=audio_bytes,
    format="wav",  # or "mp3", "m4a"
    language="en-US"
)

# Voice response includes:
# - transcribed_text: What was said
# - agent_response: Text response
# - audio_response: Agent's audio response (if enabled)
```

### Audio Configuration
```python
# Configure agent for voice interactions
agent = client.agents.update(
    agent_id="agent_123",
    voice_config={
        "enabled": True,
        "voice_id": "voice_model_id",
        "language": "en-US",
        "speed": 1.0,
        "pitch": 1.0
    }
)
```

## Batch Message Processing

### Send Multiple Messages
```python
# Batch message creation
batch_messages = [
    {
        "agent_id": "agent_123",
        "messages": [{"role": "user", "content": "Message 1"}]
    },
    {
        "agent_id": "agent_456", 
        "messages": [{"role": "user", "content": "Message 2"}]
    }
]

batch_response = client.batches.create(
    messages=batch_messages,
    callback_url="https://your-app.com/webhook/batch-complete"
)
```

### Process Batch Results
```python
# Check batch status
batch_status = client.batches.get(batch_id="batch_123")

# Process completed batch
if batch_status["status"] == "completed":
    results = batch_status["results"]
    for result in results:
        agent_id = result["agent_id"]
        response = result["response"]
        # Process each agent's response
```

## Message Templates and Presets

### Message Templates
```python
# Define reusable message templates
templates = {
    "code_review": {
        "role": "user",
        "content": "Please review this code for: 1) Bugs 2) Performance 3) Best practices\n\nCode:\n{code}"
    },
    "data_analysis": {
        "role": "user", 
        "content": "Analyze this dataset and provide insights on: {analysis_points}\n\nData:\n{data}"
    },
    "meeting_summary": {
        "role": "user",
        "content": "Summarize this meeting transcript, highlighting: {focus_areas}\n\nTranscript:\n{transcript}"
    }
}

# Use template
def send_templated_message(agent_id: str, template_name: str, **kwargs):
    template = templates[template_name]
    content = template["content"].format(**kwargs)
    
    return client.agents.messages.create(
        agent_id=agent_id,
        messages=[{
            "role": template["role"],
            "content": content
        }]
    )

# Example usage
response = send_templated_message(
    agent_id="agent_123",
    template_name="code_review", 
    code="def hello():\n    print('world')"
)
```

## Conversation Management

### Reset Conversations
```python
# Reset agent conversation (clear message history)
client.agents.messages.reset(agent_id="agent_123")

# Reset specific conversation group
client.agents.messages.reset(
    agent_id="agent_123",
    group_id="group_123"
)
```

### Export Conversations
```python
# Export conversation history
conversation_export = client.agents.messages.export(
    agent_id="agent_123",
    format="json",  # or "csv", "txt"
    include_metadata=True,
    date_range={
        "start": "2024-01-01",
        "end": "2024-12-31"
    }
)
```

### Conversation Analytics
```python
# Analyze conversation patterns
def analyze_conversation(agent_id: str) -> dict:
    """
    Analyze conversation metrics and patterns.
    """
    messages = client.agents.messages.list(agent_id=agent_id, limit=1000)
    
    analysis = {
        "total_messages": len(messages),
        "user_messages": len([m for m in messages if m["role"] == "user"]),
        "assistant_messages": len([m for m in messages if m["role"] == "assistant"]),
        "tool_calls": len([m for m in messages if m.get("tool_calls")]),
        "average_response_length": 0,
        "most_used_tools": {},
        "conversation_topics": []
    }
    
    # Calculate averages and patterns
    assistant_msgs = [m for m in messages if m["role"] == "assistant"]
    if assistant_msgs:
        total_length = sum(len(m.get("content", "")) for m in assistant_msgs)
        analysis["average_response_length"] = total_length / len(assistant_msgs)
    
    # Analyze tool usage
    for message in messages:
        tool_calls = message.get("tool_calls", [])
        for tool_call in tool_calls:
            tool_name = tool_call.get("function", {}).get("name")
            if tool_name:
                analysis["most_used_tools"][tool_name] = analysis["most_used_tools"].get(tool_name, 0) + 1
    
    return analysis
```

## Error Handling and Recovery

### Message Error Handling
```python
def safe_send_message(agent_id: str, content: str, max_retries: int = 3):
    """
    Send message with error handling and retries.
    """
    for attempt in range(max_retries):
        try:
            response = client.agents.messages.create(
                agent_id=agent_id,
                messages=[{"role": "user", "content": content}]
            )
            return response
            
        except Exception as e:
            error_type = type(e).__name__
            
            if "rate_limit" in str(e).lower():
                # Handle rate limiting
                wait_time = 2 ** attempt  # Exponential backoff
                time.sleep(wait_time)
                continue
                
            elif "context_length" in str(e).lower():
                # Handle context length errors
                print("Context too long, consider resetting conversation")
                return {"error": "context_length_exceeded"}
                
            elif attempt == max_retries - 1:
                # Final attempt failed
                return {"error": str(e)}
            
            time.sleep(1)  # Brief pause before retry
    
    return {"error": "max_retries_exceeded"}
```

### Cancel Running Operations
```python
# Cancel agent run/message processing
client.agents.runs.cancel(
    agent_id="agent_123",
    run_id="run_456"
)

# Cancel all running operations for agent
runs = client.agents.runs.list(agent_id="agent_123", status="running")
for run in runs:
    client.agents.runs.cancel(
        agent_id="agent_123",
        run_id=run["id"]
    )
```

## Performance Optimization

### Message Batching
```python
# Batch multiple messages for efficiency
def batch_send_messages(agent_messages: list, batch_size: int = 10):
    """
    Send messages in batches to optimize performance.
    """
    results = []
    
    for i in range(0, len(agent_messages), batch_size):
        batch = agent_messages[i:i + batch_size]
        
        # Process batch
        batch_results = []
        for msg_data in batch:
            result = client.agents.messages.create(**msg_data)
            batch_results.append(result)
        
        results.extend(batch_results)
        
        # Brief pause between batches
        time.sleep(0.5)
    
    return results
```

### Message Caching
```python
# Cache frequent message patterns
from functools import lru_cache
import hashlib

@lru_cache(maxsize=100)
def cached_message_send(agent_id: str, content_hash: str, content: str):
    """
    Cache message responses for identical content.
    """
    return client.agents.messages.create(
        agent_id=agent_id,
        messages=[{"role": "user", "content": content}]
    )

def send_with_cache(agent_id: str, content: str):
    content_hash = hashlib.md5(content.encode()).hexdigest()
    return cached_message_send(agent_id, content_hash, content)
```