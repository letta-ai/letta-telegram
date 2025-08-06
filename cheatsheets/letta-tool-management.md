# Letta Tool Management - Comprehensive Cheatsheet

## Tool System Overview

Letta supports multiple types of tools:
1. **Built-in Tools**: Pre-built tools like `web_search`, `run_code`
2. **Custom Tools**: User-defined Python functions
3. **MCP Tools**: Model Context Protocol server tools
4. **Composio Tools**: Integration platform tools

## Agent Tool Operations

### List Agent Tools
```python
# Get all tools attached to an agent
tools = client.agents.tools.list(agent_id="agent_123")

# Each tool object contains:
# - id: Tool identifier
# - name: Tool name
# - description: What the tool does
# - source_code: Python function implementation
# - json_schema: Tool parameters schema
# - pip_requirements: Required packages
# - metadata: Additional tool information
```

### Attach Tool to Agent
```python
# Attach existing tool to agent
client.agents.tools.attach(
    agent_id="agent_123",
    tool_id="tool_456"
)

# Attach multiple tools
tool_ids = ["tool_1", "tool_2", "tool_3"]
for tool_id in tool_ids:
    client.agents.tools.attach(
        agent_id="agent_123",
        tool_id=tool_id
    )
```

### Detach Tool from Agent
```python
# Remove tool from agent
client.agents.tools.detach(
    agent_id="agent_123",
    tool_id="tool_456"
)

# Detach all tools
agent_tools = client.agents.tools.list(agent_id="agent_123")
for tool in agent_tools:
    client.agents.tools.detach(
        agent_id="agent_123",
        tool_id=tool["id"]
    )
```

## Tool CRUD Operations

### Create Custom Tool
```python
# Create a custom tool with Python function
tool_source = '''
def calculate_compound_interest(principal: float, rate: float, time: int, compound_frequency: int = 1) -> dict:
    """
    Calculate compound interest.
    
    Args:
        principal: Initial amount
        rate: Annual interest rate (as decimal, e.g., 0.05 for 5%)
        time: Time period in years
        compound_frequency: How many times interest is compounded per year
    
    Returns:
        Dictionary with calculation results
    """
    amount = principal * (1 + rate/compound_frequency) ** (compound_frequency * time)
    interest = amount - principal
    
    return {
        "principal": principal,
        "final_amount": round(amount, 2),
        "interest_earned": round(interest, 2),
        "rate": rate,
        "time_years": time
    }
'''

tool = client.tools.create(
    name="compound_interest_calculator",
    description="Calculate compound interest for investments",
    source_code=tool_source,
    pip_requirements=["math"],  # Optional: required packages
    tags=["finance", "calculator", "investment"]
)
```

### List All Tools
```python
# List all available tools
tools = client.tools.list()

# List with filters
tools = client.tools.list(
    name="calculator",  # Filter by name
    tags=["finance"],   # Filter by tags
    limit=50           # Pagination
)

# Count tools
count = client.tools.count()
```

### Retrieve Tool Details
```python
# Get specific tool
tool = client.tools.get(tool_id="tool_123")

# Tool object includes:
# - Complete source code
# - Function signature and parameters
# - Dependencies and requirements
# - Usage metadata
```

### Update Tool
```python
# Update tool properties
updated_tool = client.tools.update(
    tool_id="tool_123",
    name="updated_calculator",
    description="Enhanced calculation tool",
    source_code=updated_source_code,
    tags=["updated", "calculator", "v2"]
)
```

### Delete Tool
```python
# Delete tool (will detach from all agents)
client.tools.delete(tool_id="tool_123")
```

## Built-in Tools

### Common Built-in Tools
```python
# Web search tool
agent = client.agents.create(
    name="research_agent",
    tools=["web_search"],
    # ... other parameters
)

# Code execution tool
agent = client.agents.create(
    name="coding_agent", 
    tools=["run_code"],
    # ... other parameters
)

# File management tool
agent = client.agents.create(
    name="file_agent",
    tools=["file_manager"],
    # ... other parameters
)

# Multiple built-in tools
agent = client.agents.create(
    name="multi_tool_agent",
    tools=["web_search", "run_code", "file_manager"],
    # ... other parameters
)
```

## Tool Categories and Examples

### Data Processing Tools
```python
# CSV processing tool
csv_tool_source = '''
import csv
import json
from io import StringIO

def process_csv_data(csv_content: str, operation: str = "summary") -> dict:
    """
    Process CSV data and return results.
    
    Args:
        csv_content: CSV data as string
        operation: Type of operation (summary, filter, transform)
    
    Returns:
        Processed data results
    """
    csv_file = StringIO(csv_content)
    reader = csv.DictReader(csv_file)
    data = list(reader)
    
    if operation == "summary":
        return {
            "row_count": len(data),
            "columns": list(data[0].keys()) if data else [],
            "sample_row": data[0] if data else {}
        }
    elif operation == "filter":
        # Add filtering logic
        return {"filtered_data": data}
    else:
        return {"data": data}
'''

csv_tool = client.tools.create(
    name="csv_processor",
    description="Process and analyze CSV data",
    source_code=csv_tool_source,
    pip_requirements=["pandas"],  # Optional for advanced processing
    tags=["data", "csv", "processing"]
)
```

### API Integration Tool
```python
# REST API client tool
api_tool_source = '''
import requests
import json

def make_api_request(url: str, method: str = "GET", headers: dict = None, data: dict = None) -> dict:
    """
    Make HTTP API requests.
    
    Args:
        url: API endpoint URL
        method: HTTP method (GET, POST, PUT, DELETE)
        headers: Request headers
        data: Request payload for POST/PUT
    
    Returns:
        API response data
    """
    try:
        response = requests.request(
            method=method.upper(),
            url=url,
            headers=headers or {},
            json=data
        )
        response.raise_for_status()
        
        return {
            "status_code": response.status_code,
            "data": response.json() if response.content else {},
            "success": True
        }
    except Exception as e:
        return {
            "error": str(e),
            "success": False
        }
'''

api_tool = client.tools.create(
    name="api_client",
    description="Make HTTP API requests",
    source_code=api_tool_source,
    pip_requirements=["requests"],
    tags=["api", "http", "integration"]
)
```

### Database Tool
```python
# SQLite database tool
db_tool_source = '''
import sqlite3
import json

def query_database(db_path: str, query: str, params: list = None) -> dict:
    """
    Execute SQL query on SQLite database.
    
    Args:
        db_path: Path to SQLite database file
        query: SQL query to execute
        params: Query parameters
    
    Returns:
        Query results
    """
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row  # Enable column access by name
        cursor = conn.cursor()
        
        cursor.execute(query, params or [])
        
        if query.strip().upper().startswith("SELECT"):
            results = [dict(row) for row in cursor.fetchall()]
            return {"data": results, "success": True}
        else:
            conn.commit()
            return {"rows_affected": cursor.rowcount, "success": True}
            
    except Exception as e:
        return {"error": str(e), "success": False}
    finally:
        if 'conn' in locals():
            conn.close()
'''

db_tool = client.tools.create(
    name="sqlite_client",
    description="Execute queries on SQLite databases",
    source_code=db_tool_source,
    tags=["database", "sqlite", "sql"]
)
```

## MCP (Model Context Protocol) Tools

### List MCP Servers
```python
# List available MCP servers
mcp_servers = client.tools.mcp.servers.list()
```

### Connect to MCP Server
```python
# Connect to MCP server
mcp_connection = client.tools.mcp.servers.connect(
    server_name="filesystem_server",
    config={
        "command": "npx",
        "args": ["@modelcontextprotocol/server-filesystem", "/path/to/directory"]
    }
)
```

### Use MCP Tools
```python
# List tools from MCP server
mcp_tools = client.tools.mcp.tools.list(server_name="filesystem_server")

# Attach MCP tool to agent
client.agents.tools.attach(
    agent_id="agent_123",
    tool_id="mcp_filesystem_read"
)
```

## Composio Integration

### List Composio Apps
```python
# List available Composio applications
apps = client.tools.composio.apps.list()
```

### Connect Composio App
```python
# Connect to Composio application
composio_integration = client.tools.composio.apps.connect(
    app_name="github",
    auth_config={
        "api_key": "your_github_token"
    }
)
```

### Use Composio Actions
```python
# List actions for Composio app
actions = client.tools.composio.actions.list(app_name="github")

# Create tool from Composio action
github_tool = client.tools.composio.create_tool(
    app_name="github",
    action_name="create_issue",
    tool_name="github_create_issue"
)

# Attach to agent
client.agents.tools.attach(
    agent_id="agent_123",
    tool_id=github_tool["id"]
)
```

## Tool Testing and Debugging

### Run Tool from Source
```python
# Test tool before creating
test_result = client.tools.run_from_source(
    source_code=tool_source_code,
    function_name="calculate_compound_interest",
    args={
        "principal": 1000,
        "rate": 0.05,
        "time": 5,
        "compound_frequency": 12
    }
)

print(f"Tool test result: {test_result}")
```

### Tool Execution Monitoring
```python
# Monitor tool usage in agent conversations
messages = client.agents.messages.list(agent_id="agent_123")

for message in messages:
    if message.get("type") == "tool_call":
        print(f"Tool used: {message['tool_name']}")
        print(f"Arguments: {message['arguments']}")
        print(f"Result: {message['result']}")
```

## Tool Best Practices

### Tool Design Principles
1. **Single Responsibility**: Each tool should have one clear purpose
2. **Clear Documentation**: Comprehensive docstrings and parameter descriptions
3. **Error Handling**: Robust exception handling and error reporting
4. **Type Hints**: Proper Python type annotations
5. **Validation**: Input parameter validation

### Performance Optimization
1. **Lightweight Tools**: Minimize dependencies and processing time
2. **Caching**: Implement caching for expensive operations
3. **Async Support**: Use async patterns for I/O operations
4. **Resource Management**: Proper cleanup of files, connections, etc.

### Security Considerations
1. **Input Sanitization**: Validate and sanitize all inputs
2. **Permission Checks**: Implement appropriate access controls
3. **Secret Management**: Never hardcode credentials
4. **Safe Execution**: Sandbox dangerous operations

## Advanced Tool Patterns

### Tool Composition
```python
# Create a composite tool that uses other tools
composite_tool_source = '''
def analyze_and_report(data_source: str, report_format: str = "json") -> dict:
    """
    Analyze data from source and generate report.
    Combines data fetching, processing, and formatting.
    """
    # This tool would internally call other tools
    # - Data fetcher tool
    # - Data analyzer tool  
    # - Report formatter tool
    
    results = {
        "data_source": data_source,
        "analysis": "completed",
        "report_format": report_format,
        "generated_at": "timestamp"
    }
    
    return results
'''
```

### Dynamic Tool Creation
```python
# Create tools dynamically based on requirements
def create_api_tool(api_name: str, base_url: str, endpoints: list):
    """
    Dynamically create API client tool for specific service.
    """
    tool_source = f'''
def call_{api_name}_api(endpoint: str, method: str = "GET", data: dict = None):
    """
    Call {api_name} API endpoints.
    
    Available endpoints: {endpoints}
    """
    import requests
    url = "{base_url}" + endpoint
    # Implementation here
    '''
    
    return client.tools.create(
        name=f"{api_name}_client",
        description=f"Client for {api_name} API",
        source_code=tool_source,
        pip_requirements=["requests"]
    )
```

### Tool Chains
```python
# Create workflow tools that chain operations
workflow_tool_source = '''
def data_processing_workflow(input_data: str, steps: list) -> dict:
    """
    Execute a series of data processing steps.
    
    Args:
        input_data: Initial data
        steps: List of processing steps to execute
    
    Returns:
        Final processed result
    """
    current_data = input_data
    results = []
    
    for step in steps:
        # Execute each step in sequence
        step_result = process_step(current_data, step)
        results.append(step_result)
        current_data = step_result.get("output", current_data)
    
    return {
        "final_result": current_data,
        "step_results": results,
        "workflow_complete": True
    }
'''
```

## Tool Troubleshooting

### Common Issues
1. **Import Errors**: Missing pip requirements
2. **Execution Timeouts**: Long-running operations
3. **Permission Errors**: File/network access issues
4. **Memory Issues**: Large data processing
5. **API Rate Limits**: External service limitations

### Debugging Tools
```python
# Add logging to tools
import logging

logging_tool_source = '''
import logging

logger = logging.getLogger(__name__)

def debug_tool_function(param: str) -> dict:
    """Tool function with debug logging."""
    logger.info(f"Tool called with param: {param}")
    
    try:
        result = perform_operation(param)
        logger.info(f"Tool completed successfully: {result}")
        return {"result": result, "success": True}
    except Exception as e:
        logger.error(f"Tool failed with error: {e}")
        return {"error": str(e), "success": False}
'''
```

### Tool Validation
```python
# Validate tool before deployment
def validate_tool(tool_source: str, test_cases: list) -> bool:
    """
    Validate tool functionality with test cases.
    """
    for test_case in test_cases:
        try:
            result = client.tools.run_from_source(
                source_code=tool_source,
                function_name=test_case["function"],
                args=test_case["args"]
            )
            
            if not result.get("success"):
                print(f"Test failed: {test_case}")
                return False
                
        except Exception as e:
            print(f"Test error: {e}")
            return False
    
    return True
```