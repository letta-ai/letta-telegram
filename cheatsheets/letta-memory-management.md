# Letta Memory Management - Comprehensive Cheatsheet

## Memory Architecture Overview

Letta agents have two primary memory systems:
1. **Core Memory**: In-context memory blocks (always available to agent)
2. **Archival Memory**: External long-term memory (searched when needed)

## Core Memory Management

### Retrieve Core Memory
```python
# Get complete core memory state
core_memory = client.agents.core_memory.retrieve(agent_id="agent_123")

# Response includes:
# - blocks: List of memory blocks
# - file_blocks: Special file-related memory blocks
# - prompt_template: Jinja2 template for memory compilation
```

### Update Core Memory
```python
# Update entire core memory
updated_memory = client.agents.core_memory.update(
    agent_id="agent_123",
    memory_blocks=[
        {"label": "human", "value": "Updated user information"},
        {"label": "persona", "value": "Updated agent personality"},
        {"label": "custom", "value": "Custom memory context"}
    ]
)
```

## Memory Blocks Management

### Retrieve Individual Block
```python
# Get specific memory block
block = client.agents.blocks.retrieve(
    agent_id="agent_123",
    block_label="human"  # or "persona", "custom", etc.
)

# Block object contains:
# - value: Block content
# - limit: Character limit (default 5000)
# - label: Block identifier
# - is_template: Whether it's a saved template
# - read_only: Whether agent has read-only access
```

### Update Individual Block
```python
# Update specific memory block
updated_block = client.agents.blocks.update(
    agent_id="agent_123",
    block_label="human",
    value="New user context information",
    limit=6000  # Optional: change character limit
)
```

### Create Custom Memory Block
```python
# Add new custom memory block
new_block = client.agents.blocks.create(
    agent_id="agent_123",
    label="project_context",
    value="Working on e-commerce platform using React and Node.js",
    limit=3000
)
```

### Delete Memory Block
```python
# Remove memory block
client.agents.blocks.delete(
    agent_id="agent_123",
    block_label="project_context"
)
```

### List All Blocks
```python
# Get all memory blocks for agent
blocks = client.agents.blocks.list(agent_id="agent_123")
```

## Memory Variables

### Manage Memory Variables
```python
# List memory variables
variables = client.agents.memory_variables.list(agent_id="agent_123")

# Create memory variable
variable = client.agents.memory_variables.create(
    agent_id="agent_123",
    name="user_preference",
    value="prefers concise responses",
    description="User communication preference"
)

# Update memory variable
updated_var = client.agents.memory_variables.update(
    agent_id="agent_123",
    variable_id="var_123",
    value="prefers detailed explanations"
)

# Delete memory variable
client.agents.memory_variables.delete(
    agent_id="agent_123",
    variable_id="var_123"
)
```

## Archival Memory Management

### Retrieve Archival Memory (Passages)
```python
# Get archival memory passages with basic pagination
passages = client.agents.passages.list(
    agent_id="agent_123",
    limit=50  # Number of passages to retrieve
)

# Advanced archival memory retrieval
passages = client.agents.passages.list(
    agent_id="agent_123",
    after="passage_id_123",  # Cursor for pagination
    before="passage_id_456",  # End cursor
    limit=25,
    search="user preferences",  # Search by text content
    ascending=True  # Sort order (oldest to newest)
)

# Each passage contains:
# - text: The passage content
# - embedding: Vector embedding data
# - metadata: Creation date, source info
# - id: Unique passage identifier
```

### Create Archival Memory Passage
```python
# Add new passage to archival memory
passage = client.agents.passages.create(
    agent_id="agent_123",
    text="Important project requirement: all APIs must support pagination",
    metadata={"type": "requirement", "priority": "high"}
)
```

### Update Archival Memory Passage
```python
# Update existing passage
updated_passage = client.agents.passages.update(
    agent_id="agent_123",
    passage_id="passage_123",
    text="Updated requirement: APIs must support pagination and filtering"
)
```

### Delete Archival Memory Passage
```python
# Remove passage from archival memory
client.agents.passages.delete(
    agent_id="agent_123",
    passage_id="passage_123"
)
```

### Search Archival Memory
```python
# Search passages by content
search_results = client.agents.passages.list(
    agent_id="agent_123",
    search="API authentication methods",
    limit=10
)

# Advanced search with filters
results = client.agents.passages.list(
    agent_id="agent_123",
    search="database optimization",
    limit=20,
    ascending=False  # Most recent first
)
```

## File-Based Memory

### File Memory Blocks
```python
# Retrieve core memory including file blocks
core_memory = client.agents.core_memory.retrieve(agent_id="agent_123")
file_blocks = core_memory.get("file_blocks", [])

# File blocks represent files in agent's context
# Each file block contains:
# - file_id: Reference to the file
# - file_name: Name of the file
# - content: File content or summary
# - metadata: File type, size, etc.
```

## Memory Templates

### Using Memory Templates
```python
# Create agent with template-based memory
agent = client.agents.create(
    name="templated_agent",
    template="coding_assistant_template",  # Uses predefined memory structure
    memory_blocks=[
        {"label": "human", "value": "Override human context"},
        # Other template blocks will be used as defaults
    ]
)

# Save current memory as template
template = client.templates.create(
    name="my_memory_template",
    agent_id="agent_123"  # Use this agent's memory as template
)
```

## Advanced Memory Operations

### Memory Recall Operations
```python
# Force memory recall (search archival memory)
recall_results = client.agents.recall(
    agent_id="agent_123",
    query="previous conversations about pricing",
    limit=5
)
```

### Batch Memory Operations
```python
# Batch update multiple memory blocks
memory_updates = [
    {"label": "human", "value": "Updated user info"},
    {"label": "persona", "value": "Updated personality"},
    {"label": "context", "value": "New project context"}
]

for update in memory_updates:
    client.agents.blocks.update(
        agent_id="agent_123",
        block_label=update["label"],
        value=update["value"]
    )
```

## Memory Monitoring and Analytics

### Memory Usage Statistics
```python
# Get memory statistics
core_memory = client.agents.core_memory.retrieve(agent_id="agent_123")

# Calculate memory usage
total_core_chars = sum(len(block.get("value", "")) for block in core_memory.get("blocks", []))
archival_count = len(client.agents.passages.list(agent_id="agent_123"))

print(f"Core memory usage: {total_core_chars} characters")
print(f"Archival passages: {archival_count}")
```

## Memory Best Practices

### Core Memory Design
1. **Concise and Relevant**: Keep blocks focused on essential information
2. **Regular Updates**: Update memory as context changes
3. **Clear Structure**: Use meaningful labels and organized content
4. **Size Management**: Monitor character limits (default 5000 per block)

### Archival Memory Strategy
1. **Meaningful Content**: Store important conversations and decisions
2. **Good Metadata**: Include relevant metadata for better searchability
3. **Regular Cleanup**: Remove outdated or irrelevant passages
4. **Search Optimization**: Use descriptive text that matches likely queries

### Memory Block Labels
- **human**: Information about the user, their preferences, context
- **persona**: Agent's personality, role, capabilities, limitations
- **context**: Current project, task, or conversation context
- **rules**: Behavioral guidelines, constraints, protocols
- **knowledge**: Domain-specific information, facts, procedures

## Common Memory Patterns

### User Context Management
```python
# Comprehensive user context
user_context = {
    "name": "Alex Johnson",
    "role": "Senior Developer",
    "preferences": "Concise explanations with code examples",
    "current_project": "E-commerce platform migration",
    "tech_stack": "React, Node.js, PostgreSQL",
    "experience_level": "5 years full-stack development"
}

client.agents.blocks.update(
    agent_id="agent_123",
    block_label="human",
    value=json.dumps(user_context, indent=2)
)
```

### Project Memory Management
```python
# Project-specific memory block
project_memory = {
    "project_name": "Customer Portal Redesign",
    "phase": "Development",
    "requirements": ["Mobile responsive", "SSO integration", "Performance optimization"],
    "constraints": ["Budget: $50k", "Timeline: 3 months", "Team: 4 developers"],
    "decisions": ["React for frontend", "Express.js for API", "MongoDB for data"]
}

client.agents.blocks.create(
    agent_id="agent_123",
    label="project_context",
    value=json.dumps(project_memory, indent=2)
)
```

### Conversation History Archival
```python
# Archive important conversation points
important_points = [
    "User prefers TDD approach for all new features",
    "Database performance is critical - query optimization required",
    "Security review needed before production deployment",
    "Weekly progress reports required every Friday"
]

for point in important_points:
    client.agents.passages.create(
        agent_id="agent_123",
        text=point,
        metadata={"type": "decision", "importance": "high"}
    )
```

## Memory Troubleshooting

### Common Issues
1. **Memory Block Size Limits**: Default 5000 characters per block
2. **Search Performance**: Large archival memory may slow searches
3. **Context Relevance**: Outdated memory affecting agent responses
4. **Memory Conflicts**: Contradictory information in different blocks

### Debugging Memory Issues
```python
# Check memory block sizes
core_memory = client.agents.core_memory.retrieve(agent_id="agent_123")
for block in core_memory.get("blocks", []):
    size = len(block.get("value", ""))
    limit = block.get("limit", 5000)
    print(f"Block '{block['label']}': {size}/{limit} characters")

# Audit archival memory
passages = client.agents.passages.list(agent_id="agent_123", limit=100)
print(f"Total archival passages: {len(passages)}")

# Search for conflicting information
conflicts = client.agents.passages.list(
    agent_id="agent_123",
    search="contradictory OR conflict OR different"
)
```

### Memory Cleanup
```python
# Remove old or irrelevant passages
old_passages = client.agents.passages.list(
    agent_id="agent_123",
    before="cutoff_date_passage_id",
    limit=50
)

for passage in old_passages:
    # Review and delete if necessary
    if should_delete(passage):
        client.agents.passages.delete(
            agent_id="agent_123",
            passage_id=passage["id"]
        )
```

## Memory Export/Import

### Export Memory State
```python
# Export complete agent state including memory
exported_agent = client.agents.export(agent_id="agent_123")

# Extract memory components
core_memory = exported_agent.get("memory", {})
archival_memory = exported_agent.get("archival_memory", [])
```

### Import Memory State
```python
# Import agent with memory state
imported_agent = client.agents.import_agent(
    agent_data=exported_agent,
    name="memory_restored_agent"
)
```