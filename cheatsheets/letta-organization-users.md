# Letta Organization & User Management - Comprehensive Cheatsheet

## Organization Structure

Letta uses a hierarchical structure:
1. **Organizations**: Top-level entities
2. **Projects**: Collections of agents and resources
3. **Users**: Members with roles and permissions
4. **Teams**: Groups of users for collaboration

## Project Management

### Create Project
```python
# Create new project
project = client.projects.create(
    name="E-commerce Assistant Project",
    description="AI agents for customer support and sales",
    metadata={
        "department": "customer_service",
        "budget": "high_priority",
        "owner": "team_lead@company.com"
    },
    tags=["customer-service", "e-commerce", "production"]
)
```

### List Projects
```python
# List all projects
projects = client.projects.list()

# List with filters
projects = client.projects.list(
    name="E-commerce",  # Filter by name
    tags=["production"],  # Filter by tags
    limit=50,  # Pagination
    include_metadata=True
)

# Count projects
count = client.projects.count()
```

### Project Operations
```python
# Get project details
project = client.projects.get(project_id="proj_123")

# Update project
updated_project = client.projects.update(
    project_id="proj_123",
    name="Updated Project Name",
    description="New description",
    metadata={"status": "active", "version": "2.0"},
    tags=["updated", "v2"]
)

# Delete project (and all contained resources)
client.projects.delete(project_id="proj_123")
```

### Project Resource Management
```python
# List agents in project
project_agents = client.agents.list(project_id="proj_123")

# List tools in project
project_tools = client.tools.list(project_id="proj_123")

# List sources in project  
project_sources = client.sources.list(project_id="proj_123")

# Move resources between projects
client.agents.update(
    agent_id="agent_123",
    project_id="new_proj_456"
)
```

## User Management

### User Information
```python
# Get current user info
current_user = client.users.me()

# User object contains:
# - id: User identifier
# - email: User email
# - name: Display name
# - role: User role (admin, member, viewer)
# - organization_id: Organization membership
# - projects: List of accessible projects
# - permissions: User permissions
# - created_at: Account creation date
```

### User Roles and Permissions
```python
# Define user roles
ROLES = {
    "admin": {
        "can_create_agents": True,
        "can_delete_agents": True,
        "can_manage_users": True,
        "can_manage_projects": True,
        "can_view_billing": True
    },
    "member": {
        "can_create_agents": True,
        "can_delete_agents": True,
        "can_manage_users": False,
        "can_manage_projects": False,
        "can_view_billing": False
    },
    "viewer": {
        "can_create_agents": False,
        "can_delete_agents": False,
        "can_manage_users": False,
        "can_manage_projects": False,
        "can_view_billing": False
    }
}

# Check user permissions
def check_permission(user: dict, permission: str) -> bool:
    user_role = user.get("role", "viewer")
    role_permissions = ROLES.get(user_role, {})
    return role_permissions.get(permission, False)
```

### Invite Users
```python
# Invite user to organization
invitation = client.users.invite(
    email="newuser@company.com",
    role="member",
    project_ids=["proj_123", "proj_456"],  # Optional: specific projects
    message="Welcome to our AI agent platform!"
)

# Invitation object contains:
# - invitation_id: Unique identifier
# - email: Invited user email
# - status: "pending", "accepted", "expired"
# - expires_at: Expiration date
# - invited_by: Who sent the invitation
```

### Manage User Roles
```python
# Update user role
client.users.update(
    user_id="user_123",
    role="admin",
    project_access=["proj_123", "proj_456", "proj_789"]
)

# Remove user from organization
client.users.remove(user_id="user_123")

# List organization users
users = client.users.list()
```

## Team Management

### Create Teams
```python
# Create team
team = client.teams.create(
    name="Customer Support Team",
    description="Team managing customer service agents",
    members=["user_123", "user_456", "user_789"],
    project_access=["proj_123"],
    permissions={
        "can_create_agents": True,
        "can_modify_agents": True,
        "can_delete_agents": False
    }
)
```

### Team Operations
```python
# List teams
teams = client.teams.list()

# Get team details
team = client.teams.get(team_id="team_123")

# Add team member
client.teams.add_member(
    team_id="team_123",
    user_id="user_999"
)

# Remove team member
client.teams.remove_member(
    team_id="team_123", 
    user_id="user_456"
)

# Update team permissions
client.teams.update(
    team_id="team_123",
    permissions={
        "can_create_agents": True,
        "can_modify_agents": True,
        "can_delete_agents": True,  # Elevated permissions
        "can_view_analytics": True
    }
)
```

## Access Control and Security

### API Key Management
```python
# Create API key for user
api_key = client.api_keys.create(
    name="Production API Key",
    scopes=["agents:read", "agents:write", "messages:create"],
    expires_at="2025-12-31T23:59:59Z",
    project_ids=["proj_123"]  # Restrict to specific projects
)

# List API keys
keys = client.api_keys.list()

# Revoke API key
client.api_keys.revoke(api_key_id="key_123")

# Rotate API key
new_key = client.api_keys.rotate(api_key_id="key_123")
```

### Client-Side Access Tokens
```python
# Create temporary access token for frontend
access_token = client.tokens.create(
    user_id="user_123",
    expires_in=3600,  # 1 hour
    scopes=["agents:read", "messages:create"],
    project_id="proj_123"
)

# Token object contains:
# - token: JWT token string
# - expires_at: Expiration timestamp
# - scopes: Allowed operations
# - project_id: Restricted project
```

### Permission Scopes
```python
# Available permission scopes
SCOPES = [
    "agents:read",      # View agents
    "agents:write",     # Create/modify agents
    "agents:delete",    # Delete agents
    "messages:create",  # Send messages
    "messages:read",    # View message history
    "tools:read",       # View tools
    "tools:write",      # Create/modify tools
    "tools:delete",     # Delete tools
    "sources:read",     # View sources
    "sources:write",    # Create/modify sources
    "sources:delete",   # Delete sources
    "projects:read",    # View projects
    "projects:write",   # Create/modify projects
    "users:read",       # View users
    "users:write",      # Manage users
    "billing:read",     # View billing info
    "analytics:read"    # View analytics
]
```

## Organization Settings

### Organization Configuration
```python
# Get organization settings
org_settings = client.organization.settings.get()

# Update organization settings
client.organization.settings.update(
    name="ACME AI Solutions",
    billing_email="billing@acme.com",
    security_settings={
        "require_2fa": True,
        "session_timeout": 3600,
        "ip_whitelist": ["203.0.113.0/24"],
        "api_rate_limits": {
            "requests_per_minute": 1000,
            "requests_per_hour": 10000
        }
    },
    compliance_settings={
        "data_retention_days": 365,
        "audit_logging": True,
        "encryption_at_rest": True
    }
)
```

### Billing and Usage
```python
# Get billing information
billing_info = client.billing.get()

# Billing info includes:
# - current_plan: Plan name and limits
# - usage: Current period usage
# - billing_cycle: Billing period
# - next_invoice: Upcoming charges
# - payment_method: Payment details

# Get usage statistics
usage_stats = client.billing.usage.get(
    start_date="2024-01-01",
    end_date="2024-01-31",
    breakdown_by=["project", "user", "model"]
)
```

## Audit and Compliance

### Audit Logging
```python
# Get audit logs
audit_logs = client.audit.logs.list(
    start_date="2024-01-01",
    end_date="2024-01-31",
    user_id="user_123",  # Filter by user
    action="agent_created",  # Filter by action
    resource_type="agent",  # Filter by resource
    limit=100
)

# Audit log entry contains:
# - timestamp: When action occurred
# - user_id: Who performed action
# - action: What was done
# - resource_type: Type of resource
# - resource_id: Specific resource
# - metadata: Additional context
# - ip_address: Source IP
# - user_agent: Client information
```

### Data Export and Compliance
```python
# Export organization data
data_export = client.compliance.export.create(
    export_type="full",  # or "user_data", "audit_logs"
    date_range={
        "start": "2024-01-01",
        "end": "2024-12-31"
    },
    include_deleted=True,
    format="json"  # or "csv"
)

# Check export status
export_status = client.compliance.export.get(export_id="export_123")

# Download completed export
if export_status["status"] == "completed":
    download_url = export_status["download_url"]
    # Download the file
```

## Multi-Organization Management

### Organization Switching
```python
# List accessible organizations
orgs = client.organizations.list()

# Switch to different organization
client.set_organization(org_id="org_456")

# Get current organization
current_org = client.organization.get()
```

### Cross-Organization Operations
```python
# Share resources across organizations (if permitted)
client.agents.share(
    agent_id="agent_123",
    target_organization="org_456",
    permissions=["read", "clone"]
)

# Accept shared resource
client.agents.accept_shared(
    shared_resource_id="shared_123",
    target_project="proj_789"
)
```

## Resource Quotas and Limits

### Quota Management
```python
# Check current quotas
quotas = client.organization.quotas.get()

# Quotas include:
# - agents: Maximum number of agents
# - messages_per_month: Message limit
# - tools: Maximum custom tools
# - sources: Maximum knowledge sources
# - projects: Maximum projects
# - storage_gb: Storage limit

# Monitor quota usage
usage = client.organization.usage.get()

# Usage monitoring
def check_quota_usage():
    quotas = client.organization.quotas.get()
    usage = client.organization.usage.get()
    
    warnings = []
    
    for resource, limit in quotas.items():
        current_usage = usage.get(resource, 0)
        usage_percent = (current_usage / limit) * 100
        
        if usage_percent > 90:
            warnings.append(f"{resource}: {usage_percent:.1f}% used ({current_usage}/{limit})")
        elif usage_percent > 75:
            warnings.append(f"{resource}: {usage_percent:.1f}% used ({current_usage}/{limit})")
    
    return warnings
```

## Monitoring and Analytics

### Organization Analytics
```python
# Get organization analytics
analytics = client.analytics.organization.get(
    start_date="2024-01-01",
    end_date="2024-01-31",
    metrics=["agent_usage", "message_volume", "tool_calls", "user_activity"]
)

# Analytics include:
# - agent_metrics: Agent usage patterns
# - user_metrics: User activity levels  
# - cost_metrics: Usage costs breakdown
# - performance_metrics: Response times, success rates
```

### User Activity Monitoring
```python
# Track user activity
user_activity = client.analytics.users.activity(
    user_id="user_123",
    date_range={"start": "2024-01-01", "end": "2024-01-31"}
)

# Activity includes:
# - login_frequency: How often user logs in
# - agents_created: Number of agents created
# - messages_sent: Message volume
# - tools_used: Tool usage patterns
# - projects_accessed: Project interaction
```

## Best Practices

### Organization Design
1. **Clear Hierarchy**: Organize projects logically by team/function
2. **Appropriate Permissions**: Grant minimum necessary permissions
3. **Regular Audits**: Review user access and permissions regularly
4. **Resource Naming**: Use consistent naming conventions
5. **Documentation**: Document team roles and responsibilities

### Security Best Practices
1. **Multi-Factor Authentication**: Require 2FA for all users
2. **API Key Rotation**: Regular rotation of API keys
3. **Access Reviews**: Periodic review of user permissions
4. **Audit Monitoring**: Monitor audit logs for suspicious activity
5. **Data Classification**: Classify and protect sensitive data

### Compliance Management
1. **Data Retention**: Implement appropriate data retention policies
2. **Export Procedures**: Regular data exports for compliance
3. **Audit Trails**: Maintain comprehensive audit trails
4. **Privacy Controls**: Implement privacy controls as required
5. **Incident Response**: Have procedures for security incidents

## Common Patterns

### Multi-Team Organization
```python
# Setup for multiple teams
teams_config = [
    {
        "name": "Customer Support",
        "projects": ["support_agents"],
        "permissions": ["agents:read", "agents:write", "messages:create"]
    },
    {
        "name": "Sales Team", 
        "projects": ["sales_agents"],
        "permissions": ["agents:read", "agents:write", "messages:create", "analytics:read"]
    },
    {
        "name": "Engineering",
        "projects": ["dev_agents", "qa_agents"],
        "permissions": ["*"]  # Full access
    }
]

for team_config in teams_config:
    team = client.teams.create(
        name=team_config["name"],
        project_access=team_config["projects"],
        permissions={perm: True for perm in team_config["permissions"]}
    )
```

### Resource Governance
```python
# Implement resource governance
def enforce_resource_governance():
    """
    Enforce organizational resource policies.
    """
    # Check naming conventions
    agents = client.agents.list()
    for agent in agents:
        if not agent["name"].startswith(("prod_", "dev_", "test_")):
            print(f"Warning: Agent {agent['name']} doesn't follow naming convention")
    
    # Check resource limits
    warnings = check_quota_usage()
    if warnings:
        print("Quota warnings:")
        for warning in warnings:
            print(f"  - {warning}")
    
    # Check for unused resources
    inactive_agents = []
    for agent in agents:
        last_message = client.agents.messages.list(agent_id=agent["id"], limit=1)
        if not last_message:  # No messages
            inactive_agents.append(agent["name"])
    
    if inactive_agents:
        print(f"Inactive agents: {inactive_agents}")
```

### Cost Management
```python
# Monitor and optimize costs
def analyze_costs():
    """
    Analyze organizational costs and suggest optimizations.
    """
    usage = client.billing.usage.get()
    
    # Analyze by model costs
    model_costs = usage.get("model_usage", {})
    expensive_models = {k: v for k, v in model_costs.items() if v > 100}
    
    if expensive_models:
        print("High-cost models:")
        for model, cost in expensive_models.items():
            print(f"  {model}: ${cost}")
    
    # Suggest optimizations
    suggestions = []
    
    if usage.get("message_volume", 0) > 10000:
        suggestions.append("Consider implementing message caching")
    
    if len(expensive_models) > 0:
        suggestions.append("Review if expensive models are necessary for all use cases")
    
    return suggestions
```