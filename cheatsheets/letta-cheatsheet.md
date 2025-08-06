# Letta AI Agent Framework - Claude Code Cheatsheet

## Overview
Letta is a platform for building stateful AI agents with persistent memory and learning capabilities. Agents exist as services and maintain context across long-running conversations.

## Quick Setup

### Installation
```bash
pip install letta-client
```

### Basic Agent Creation
```python
from letta_client import Letta

client = Letta(token="LETTA_API_KEY")

agent_state = client.agents.create(
    model="openai/gpt-4.1",
    embedding="openai/text-embedding-3-small",
    memory_blocks=[
        {"label": "human", "value": "The human's name is Chad."},
        {"label": "persona", "value": "My name is Sam, the all-knowing sentient AI."}
    ],
    tools=["web_search", "run_code"]
)

# Send message to agent
response = client.agents.messages.create(
    agent_id=agent_state.id,
    messages=[{"role": "user", "content": "Hello!"}]
)
```

## Core Concepts

### Memory Architecture
- **Core Memory**: In-context long-term memory for persistent agent state
- **Archival Memory**: External long-term memory for extended context
- **Context Hierarchy**: Manages different information types and priorities
- **Memory Blocks**: Configurable memory components (human, persona, etc.)

### Agent Types
- **MemGPT Agents**: Advanced memory-enabled agents
- **Sleep-time Agents**: Agents that can pause and resume
- **Low-latency Agents**: Optimized for fast responses  
- **ReAct Agents**: Reasoning and acting pattern agents
- **Stateful Workflows**: Multi-step process agents

## Key Features

### Tool Integration
- Built-in tools: `web_search`, `run_code`
- Model Context Protocol (MCP) support
- Custom tool creation capabilities
- Tool attachment and execution

### Advanced Capabilities
- Streaming agent responses
- JSON mode for structured outputs
- Multi-modal input (including images)
- Multi-agent systems with shared memory
- Scheduling and asynchronous message handling
- Voice chat completions
- Batch processing

## API Patterns

### Client Initialization
```python
from letta_client import Letta
client = Letta(token="LETTA_API_KEY")
```

### Agent Management
```python
# Create agent
agent = client.agents.create(...)

# List agents
agents = client.agents.list()

# Get agent details
agent_info = client.agents.get(agent_id)

# Update agent
client.agents.update(agent_id, ...)

# Delete agent
client.agents.delete(agent_id)
```

### Message Handling
```python
# Send message
response = client.agents.messages.create(
    agent_id=agent_id,
    messages=[{"role": "user", "content": "message"}]
)

# Stream responses
for chunk in client.agents.messages.create_stream(...):
    print(chunk)
```

### Memory Management
```python
# Update memory blocks
client.agents.memory.update(
    agent_id=agent_id,
    memory_blocks=[
        {"label": "human", "value": "Updated info"},
        {"label": "persona", "value": "Updated persona"}
    ]
)

# Access archival memory
archival_data = client.agents.archival.list(agent_id)
```

## Configuration Options

### Models
- OpenAI: `openai/gpt-4.1`, `openai/gpt-3.5-turbo`
- Anthropic: `anthropic/claude-3-opus`, `anthropic/claude-3-sonnet`
- Google AI: Various Gemini models
- Open source models supported

### Embeddings
- `openai/text-embedding-3-small`
- `openai/text-embedding-3-large`
- Other embedding providers supported

## Deployment Options

### Letta Cloud
- Managed service with API key authentication
- Quick setup and scaling
- Built-in monitoring and analytics

### Self-Hosting
- Local deployment capabilities
- Custom model provider integration
- Full control over infrastructure

## Development Environment

### Agent Development Environment (ADE)
- Web and desktop interfaces
- Agent simulation and testing
- Context window viewing
- Memory management tools
- Real-time monitoring

## Best Practices

### Memory Design
- Use meaningful memory block labels
- Keep core memory concise but informative
- Leverage archival memory for extended context
- Regular memory updates for accuracy

### Tool Usage
- Attach relevant tools based on agent purpose
- Test tool interactions in development
- Monitor tool execution performance
- Custom tools for specific use cases

### Multi-Agent Systems
- Design clear communication patterns
- Shared memory for coordination
- Proper agent role definition
- Conflict resolution strategies

## Common Use Cases

### Customer Support Agent
```python
agent = client.agents.create(
    model="openai/gpt-4.1",
    memory_blocks=[
        {"label": "persona", "value": "Helpful customer support agent"},
        {"label": "guidelines", "value": "Always be polite and helpful"}
    ],
    tools=["web_search", "knowledge_base_lookup"]
)
```

### Code Assistant Agent
```python
agent = client.agents.create(
    model="openai/gpt-4.1",
    memory_blocks=[
        {"label": "persona", "value": "Expert programming assistant"},
        {"label": "context", "value": "Working on Python web application"}
    ],
    tools=["run_code", "file_manager", "git_operations"]
)
```

### Research Agent
```python
agent = client.agents.create(
    model="openai/gpt-4.1",
    memory_blocks=[
        {"label": "persona", "value": "Research analyst"},
        {"label": "methodology", "value": "Systematic fact-checking approach"}
    ],
    tools=["web_search", "document_analysis", "data_processing"]
)
```

## Troubleshooting

### Common Issues
- API key authentication errors
- Model availability and quotas
- Tool execution timeouts
- Memory block size limits
- Context window management

### Performance Optimization
- Choose appropriate model sizes
- Optimize memory block content
- Efficient tool selection
- Streaming for long responses
- Batch operations when possible

## Resources
- Documentation: https://docs.letta.com
- API Reference: REST API with comprehensive endpoints
- SDKs: Python, TypeScript support
- Community: GitHub repository and discussions