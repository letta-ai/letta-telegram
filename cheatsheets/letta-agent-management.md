# Letta Agent Management - Comprehensive Cheatsheet

## Client Setup

### Python SDK
```python
from letta_client import Letta

# Cloud setup
client = Letta(
    project="YOUR_PROJECT",
    token="YOUR_TOKEN"
)

# Local server setup
client = Letta(
    base_url="http://localhost:8283"
)
```

### TypeScript SDK
```typescript
import { Letta } from '@letta-ai/letta-client';

const client = new Letta({
    project: "YOUR_PROJECT",
    token: "YOUR_TOKEN"
});
```

## Agent CRUD Operations

### Create Agent
```python
# Basic agent creation
agent = client.agents.create(
    name="my_agent",
    model="openai/gpt-4.1",
    embedding="openai/text-embedding-3-small",
    memory_blocks=[
        {"label": "human", "value": "User is a software developer named Alex"},
        {"label": "persona", "value": "I am a helpful AI assistant specialized in coding"}
    ]
)

# Advanced agent creation with all options
agent = client.agents.create(
    name="advanced_agent",
    model="openai/gpt-4.1",
    embedding="openai/text-embedding-3-small", 
    memory_blocks=[
        {"label": "human", "value": "Context about the user"},
        {"label": "persona", "value": "Agent personality and role"}
    ],
    tools=["web_search", "run_code"],  # Tool names or IDs
    sources=["source_id_1", "source_id_2"],  # Source IDs
    template="custom_template_id",  # Optional template
    metadata={"department": "engineering", "version": "1.0"},
    description="Specialized coding assistant",
    tags=["coding", "development", "assistant"]
)
```

### List Agents
```python
# List all agents
agents = client.agents.list()

# List with filters
agents = client.agents.list(
    name="my_agent",  # Filter by name
    tags=["coding"],  # Filter by tags
    project_id="project_123",  # Filter by project
    limit=50,  # Pagination
    after="agent_id_cursor"  # Cursor for pagination
)

# Count agents
count = client.agents.count()
```

### Retrieve Agent
```python
# Get agent details
agent = client.agents.get(agent_id="agent_123")

# Agent object contains:
# - id, name, description
# - model, embedding configurations
# - memory_blocks, tools, sources
# - metadata, tags
# - created_by, last_updated_by
# - created_at, updated_at
```

### Modify Agent
```python
# Update agent properties
updated_agent = client.agents.update(
    agent_id="agent_123",
    name="new_name",
    description="Updated description",
    model="openai/gpt-4.1",
    embedding="openai/text-embedding-3-large",
    metadata={"version": "2.0"},
    tags=["updated", "v2"]
)

# Partial updates are supported - only provide fields to change
```

### Delete Agent
```python
# Delete agent permanently
client.agents.delete(agent_id="agent_123")
```

## Agent Export/Import

### Export Agent
```python
# Export agent configuration and state
exported_data = client.agents.export(agent_id="agent_123")

# Returns serialized agent data including:
# - Agent configuration
# - Memory state
# - Tool attachments
# - Source attachments
```

### Import Agent
```python
# Import agent from exported data
imported_agent = client.agents.import_agent(
    agent_data=exported_data,
    name="imported_agent",  # Optional new name
    project_id="new_project"  # Optional different project
)
```

## Agent Search and Discovery

### Search Deployed Agents
```python
# Search agents by various criteria
results = client.agents.search(
    query="coding assistant",  # Text search
    tags=["development"],  # Filter by tags
    model="openai/gpt-4.1",  # Filter by model
    limit=25
)
```

## Agent Templates

### Using Templates
```python
# Create agent from template
agent = client.agents.create(
    template="coding_assistant_template",
    name="my_coding_bot",
    memory_blocks=[
        {"label": "human", "value": "User context"},
        {"label": "persona", "value": "Specialized persona"}
    ]
)

# List available templates
templates = client.templates.list()
```

## Agent Configuration Options

### Models
- **OpenAI**: `openai/gpt-4.1`, `openai/gpt-4o`, `openai/gpt-3.5-turbo`
- **Anthropic**: `anthropic/claude-3-opus`, `anthropic/claude-3-sonnet`, `anthropic/claude-3-haiku`
- **Google**: `google/gemini-pro`, `google/gemini-1.5-pro`
- **Open Source**: Various local and hosted models

### Embeddings
- `openai/text-embedding-3-small`
- `openai/text-embedding-3-large`
- `openai/text-embedding-ada-002`

### Memory Block Types
- **human**: Information about the user
- **persona**: Agent personality and behavior
- **custom**: Any custom memory context

## Agent Folders and Organization

### Folder Management
```python
# List agent folders
folders = client.agents.folders.list()

# Create folder
folder = client.agents.folders.create(
    name="Development Agents",
    description="Agents for software development tasks"
)

# Move agent to folder
client.agents.update(
    agent_id="agent_123",
    folder_id="folder_456"
)
```

## Agent Groups

### Group Management
```python
# List agent groups
groups = client.agents.groups.list(agent_id="agent_123")

# Add agent to group
client.agents.groups.create(
    agent_id="agent_123",
    group_name="development_team"
)

# Remove from group
client.agents.groups.delete(
    agent_id="agent_123", 
    group_id="group_456"
)
```

## Conversation Management

### Summarize Conversations
```python
# Get conversation summary
summary = client.agents.summarize(
    agent_id="agent_123",
    message_limit=100  # Number of recent messages to summarize
)
```

## Best Practices

### Agent Creation
1. **Meaningful Names**: Use descriptive names for easy identification
2. **Clear Personas**: Define specific roles and capabilities
3. **Appropriate Models**: Choose models based on task complexity
4. **Useful Tags**: Tag agents for easy filtering and search
5. **Version Control**: Use metadata to track agent versions

### Memory Design
1. **Concise Context**: Keep memory blocks focused and relevant
2. **Regular Updates**: Update memory as context changes
3. **Clear Labels**: Use descriptive labels for memory blocks

### Performance Optimization
1. **Model Selection**: Balance capability with cost and speed
2. **Embedding Choice**: Use appropriate embedding models for your use case
3. **Tool Attachment**: Only attach necessary tools
4. **Source Management**: Limit sources to relevant knowledge

### Error Handling
```python
try:
    agent = client.agents.create(...)
except Exception as e:
    print(f"Agent creation failed: {e}")
    # Handle specific error cases
```

## Common Patterns

### Multi-Purpose Agent
```python
agent = client.agents.create(
    name="general_assistant",
    model="openai/gpt-4.1",
    memory_blocks=[
        {"label": "human", "value": "Multi-skilled user needing various assistance"},
        {"label": "persona", "value": "Versatile AI assistant capable of multiple tasks"}
    ],
    tools=["web_search", "run_code", "file_manager"],
    tags=["general", "versatile", "multi-purpose"]
)
```

### Specialized Domain Agent
```python
agent = client.agents.create(
    name="medical_researcher",
    model="openai/gpt-4.1",
    memory_blocks=[
        {"label": "human", "value": "Medical researcher studying cardiovascular disease"},
        {"label": "persona", "value": "Medical AI assistant with expertise in cardiology research"}
    ],
    sources=["medical_journals_source", "pubmed_source"],
    tools=["research_search", "data_analysis"],
    tags=["medical", "research", "cardiology"]
)
```

### Customer Service Agent
```python
agent = client.agents.create(
    name="support_bot",
    model="openai/gpt-4.1",
    memory_blocks=[
        {"label": "human", "value": "Customer needing product support"},
        {"label": "persona", "value": "Friendly and helpful customer service representative"}
    ],
    sources=["knowledge_base_source", "faq_source"],
    tools=["ticket_management", "escalation_tool"],
    tags=["support", "customer-service", "help-desk"]
)
```

## Troubleshooting

### Common Issues
- **Authentication Errors**: Verify token and project ID
- **Model Availability**: Check model names and provider quotas
- **Memory Limits**: Monitor memory block sizes (default limit: 5000 chars)
- **Tool Conflicts**: Ensure tool compatibility
- **Rate Limits**: Implement proper retry logic

### Debugging
```python
# Enable debug logging
import logging
logging.basicConfig(level=logging.DEBUG)

# Check agent status
agent_details = client.agents.get(agent_id="agent_123")
print(f"Agent status: {agent_details}")
```