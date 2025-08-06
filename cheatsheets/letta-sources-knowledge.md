# Letta Sources & Knowledge Management - Comprehensive Cheatsheet

## Knowledge System Overview

Letta's knowledge system allows agents to access external information through:
1. **Sources**: Knowledge bases that can be attached to agents
2. **Files**: Documents uploaded and processed into sources
3. **Passages**: Chunks of text extracted from files
4. **Embeddings**: Vector representations for semantic search

## Source Management

### Create Source
```python
# Create a new knowledge source
source = client.sources.create(
    name="Company Documentation",
    description="Internal company policies and procedures",
    metadata={
        "department": "HR",
        "version": "2024.1",
        "sensitivity": "internal"
    },
    embedding_config={
        "model": "openai/text-embedding-3-small",
        "chunk_size": 1000,
        "chunk_overlap": 200
    }
)
```

### List Sources
```python
# List all sources
sources = client.sources.list()

# List with filters
sources = client.sources.list(
    name="Documentation",  # Filter by name
    limit=50,             # Pagination
    project_id="proj_123" # Filter by project
)

# Count sources
count = client.sources.count()
```

### Source Operations
```python
# Get source details
source = client.sources.get(source_id="source_123")

# Source object contains:
# - id, name, description
# - metadata: Custom metadata
# - embedding_model: Model used for embeddings
# - file_count: Number of files in source
# - passage_count: Number of text passages
# - created_at, updated_at
# - created_by: User who created it

# Update source
updated_source = client.sources.update(
    source_id="source_123",
    name="Updated Documentation",
    description="Updated company policies",
    metadata={"version": "2024.2", "status": "active"}
)

# Delete source (removes all associated files and passages)
client.sources.delete(source_id="source_123")
```

### Source Metadata Management
```python
# Get source metadata
metadata = client.sources.metadata.get(source_id="source_123")

# Update source metadata
client.sources.metadata.update(
    source_id="source_123",
    metadata={
        "category": "policies",
        "last_reviewed": "2024-01-15",
        "owner": "hr@company.com",
        "tags": ["hr", "policies", "procedures"]
    }
)
```

## File Management

### Upload Files to Source
```python
# Upload single file
file_upload = client.sources.files.upload(
    source_id="source_123",
    file_path="/path/to/document.pdf",
    metadata={
        "document_type": "policy",
        "effective_date": "2024-01-01"
    }
)

# Upload multiple files
file_paths = [
    "/path/to/policy1.pdf",
    "/path/to/policy2.docx", 
    "/path/to/procedures.txt"
]

for file_path in file_paths:
    client.sources.files.upload(
        source_id="source_123",
        file_path=file_path,
        metadata={"batch": "policy_update_2024"}
    )
```

### Upload from URL
```python
# Upload file from URL
file_upload = client.sources.files.upload_from_url(
    source_id="source_123",
    url="https://example.com/document.pdf",
    filename="external_document.pdf",
    metadata={
        "source_url": "https://example.com/document.pdf",
        "downloaded_at": "2024-01-15T10:30:00Z"
    }
)
```

### Upload from Content
```python
# Upload content directly
content = """
This is the content of a document that we want to add to our knowledge base.
It contains important information about our procedures.
"""

file_upload = client.sources.files.upload_content(
    source_id="source_123",
    content=content,
    filename="procedures_summary.txt",
    content_type="text/plain",
    metadata={
        "created_by": "automation",
        "type": "summary"
    }
)
```

### List Files in Source
```python
# List all files in source
files = client.sources.files.list(source_id="source_123")

# List with filters
files = client.sources.files.list(
    source_id="source_123",
    filename="policy",     # Filter by filename
    content_type="pdf",    # Filter by content type
    limit=25              # Pagination
)

# Each file object contains:
# - id: File identifier
# - filename: Original filename
# - content_type: MIME type
# - size: File size in bytes
# - status: Processing status
# - passage_count: Number of extracted passages
# - metadata: Custom metadata
# - uploaded_at: Upload timestamp
```

### File Operations
```python
# Get file details
file_info = client.sources.files.get(
    source_id="source_123",
    file_id="file_456"
)

# Update file metadata
client.sources.files.update(
    source_id="source_123",
    file_id="file_456",
    metadata={
        "reviewed": True,
        "reviewer": "john@company.com",
        "review_date": "2024-01-20"
    }
)

# Delete file from source
client.sources.files.delete(
    source_id="source_123",
    file_id="file_456"
)

# Download file content
file_content = client.sources.files.download(
    source_id="source_123",
    file_id="file_456"
)
```

## Passage Management

### List Passages
```python
# List passages in source
passages = client.sources.passages.list(
    source_id="source_123",
    limit=50
)

# List with search
passages = client.sources.passages.list(
    source_id="source_123",
    search="employee handbook",  # Search by content
    limit=25
)

# Each passage contains:
# - id: Passage identifier
# - text: The passage content
# - embedding: Vector embedding
# - file_id: Source file
# - metadata: File and passage metadata
# - created_at: When passage was created
```

### Search Passages
```python
# Semantic search in source
search_results = client.sources.passages.search(
    source_id="source_123",
    query="vacation policy",
    limit=10,
    threshold=0.7  # Similarity threshold
)

# Advanced search with filters
search_results = client.sources.passages.search(
    source_id="source_123",
    query="remote work guidelines",
    limit=15,
    filters={
        "file_type": "pdf",
        "department": "hr"
    },
    include_metadata=True
)
```

### Passage Operations
```python
# Get specific passage
passage = client.sources.passages.get(
    source_id="source_123",
    passage_id="passage_789"
)

# Update passage metadata
client.sources.passages.update(
    source_id="source_123", 
    passage_id="passage_789",
    metadata={
        "importance": "high",
        "category": "policy",
        "last_verified": "2024-01-20"
    }
)

# Delete passage
client.sources.passages.delete(
    source_id="source_123",
    passage_id="passage_789"
)
```

### Create Custom Passages
```python
# Add custom passage to source
custom_passage = client.sources.passages.create(
    source_id="source_123",
    text="Important company announcement: New remote work policy effective March 1, 2024.",
    metadata={
        "type": "announcement",
        "priority": "high",
        "effective_date": "2024-03-01"
    }
)
```

## Agent-Source Operations

### Attach Source to Agent
```python
# Attach source to agent
client.agents.sources.attach(
    agent_id="agent_123",
    source_id="source_456"
)

# Attach multiple sources
source_ids = ["source_1", "source_2", "source_3"]
for source_id in source_ids:
    client.agents.sources.attach(
        agent_id="agent_123",
        source_id=source_id
    )
```

### List Agent Sources
```python
# List sources attached to agent
agent_sources = client.agents.sources.list(agent_id="agent_123")

# Each source attachment contains:
# - source_id: Source identifier
# - source_name: Source name  
# - attached_at: When attached
# - access_level: read, write permissions
```

### Detach Source from Agent
```python
# Detach source from agent
client.agents.sources.detach(
    agent_id="agent_123",
    source_id="source_456"
)

# Detach all sources
agent_sources = client.agents.sources.list(agent_id="agent_123")
for source in agent_sources:
    client.agents.sources.detach(
        agent_id="agent_123",
        source_id=source["source_id"]
    )
```

## Document Processing

### Supported File Types
```python
# Supported file formats
SUPPORTED_FORMATS = {
    "text": [".txt", ".md", ".csv"],
    "documents": [".pdf", ".docx", ".doc", ".rtf"],
    "web": [".html", ".htm"],
    "code": [".py", ".js", ".java", ".cpp", ".c"],
    "structured": [".json", ".xml", ".yaml", ".yml"],
    "spreadsheets": [".xlsx", ".xls", ".csv"]
}
```

### Processing Configuration
```python
# Configure document processing
processing_config = {
    "chunk_size": 1000,        # Characters per passage
    "chunk_overlap": 200,      # Overlap between chunks
    "embedding_model": "openai/text-embedding-3-small",
    "extract_metadata": True,   # Extract document metadata
    "ocr_enabled": True,       # OCR for scanned documents
    "language": "en",          # Document language
    "remove_headers": True,    # Remove headers/footers
    "preserve_formatting": False  # Keep original formatting
}

# Create source with processing config
source = client.sources.create(
    name="Technical Documentation",
    description="API and technical documentation",
    processing_config=processing_config
)
```

### Monitor Processing Status
```python
# Check file processing status
def monitor_file_processing(source_id: str, file_id: str):
    """
    Monitor file processing progress.
    """
    while True:
        file_info = client.sources.files.get(
            source_id=source_id,
            file_id=file_id
        )
        
        status = file_info.get("status")
        print(f"Processing status: {status}")
        
        if status == "completed":
            print(f"Processing complete. {file_info['passage_count']} passages created.")
            break
        elif status == "failed":
            print(f"Processing failed: {file_info.get('error')}")
            break
        
        time.sleep(5)  # Check every 5 seconds
```

## Advanced Knowledge Operations

### Batch Processing
```python
# Batch upload and process files
def batch_upload_files(source_id: str, file_directory: str):
    """
    Upload all files from a directory to a source.
    """
    import os
    
    uploaded_files = []
    
    for filename in os.listdir(file_directory):
        file_path = os.path.join(file_directory, filename)
        
        if os.path.isfile(file_path):
            try:
                file_upload = client.sources.files.upload(
                    source_id=source_id,
                    file_path=file_path,
                    metadata={
                        "batch": "directory_upload",
                        "original_path": file_path
                    }
                )
                uploaded_files.append(file_upload)
                print(f"Uploaded: {filename}")
                
            except Exception as e:
                print(f"Failed to upload {filename}: {e}")
    
    return uploaded_files
```

### Knowledge Graph Integration
```python
# Create knowledge graph relationships
def create_knowledge_relationships(source_id: str):
    """
    Analyze passages to create relationships between concepts.
    """
    passages = client.sources.passages.list(source_id=source_id, limit=1000)
    
    # Extract key concepts and relationships
    relationships = []
    
    for passage in passages:
        # Analyze passage content for relationships
        # This would use NLP techniques or LLM analysis
        concepts = extract_concepts(passage["text"])
        
        for concept in concepts:
            relationships.append({
                "passage_id": passage["id"],
                "concept": concept,
                "context": passage["text"][:200]
            })
    
    return relationships

def extract_concepts(text: str) -> list:
    """
    Extract key concepts from text.
    """
    # Placeholder for concept extraction logic
    # Could use spaCy, NLTK, or LLM-based extraction
    return []
```

### Embedding Management
```python
# Re-embed passages with different model
def re_embed_source(source_id: str, new_embedding_model: str):
    """
    Re-embed all passages in a source with a new embedding model.
    """
    # Update source embedding model
    client.sources.update(
        source_id=source_id,
        embedding_model=new_embedding_model
    )
    
    # Trigger re-embedding process
    job = client.sources.embeddings.regenerate(source_id=source_id)
    
    # Monitor progress
    while True:
        job_status = client.jobs.get(job_id=job["id"])
        
        if job_status["status"] == "completed":
            print("Re-embedding completed")
            break
        elif job_status["status"] == "failed":
            print(f"Re-embedding failed: {job_status['error']}")
            break
        
        time.sleep(10)
```

## Source Analytics and Monitoring

### Usage Analytics
```python
# Get source usage analytics
analytics = client.sources.analytics.get(
    source_id="source_123",
    start_date="2024-01-01",
    end_date="2024-01-31"
)

# Analytics include:
# - search_queries: Most common search terms
# - passage_hits: Most accessed passages
# - agent_usage: Which agents use the source
# - performance_metrics: Search latency, relevance scores
```

### Quality Metrics
```python
# Analyze source quality
def analyze_source_quality(source_id: str) -> dict:
    """
    Analyze quality metrics for a knowledge source.
    """
    source_info = client.sources.get(source_id=source_id)
    passages = client.sources.passages.list(source_id=source_id, limit=1000)
    
    metrics = {
        "total_passages": len(passages),
        "average_passage_length": 0,
        "duplicate_passages": 0,
        "empty_passages": 0,
        "quality_score": 0
    }
    
    if passages:
        # Calculate average passage length
        total_length = sum(len(p["text"]) for p in passages)
        metrics["average_passage_length"] = total_length / len(passages)
        
        # Check for duplicates and empty passages
        passage_texts = [p["text"] for p in passages]
        metrics["duplicate_passages"] = len(passage_texts) - len(set(passage_texts))
        metrics["empty_passages"] = sum(1 for text in passage_texts if not text.strip())
        
        # Calculate quality score (simple heuristic)
        quality_factors = []
        quality_factors.append(min(metrics["average_passage_length"] / 500, 1.0))  # Ideal length ~500 chars
        quality_factors.append(1.0 - (metrics["duplicate_passages"] / len(passages)))
        quality_factors.append(1.0 - (metrics["empty_passages"] / len(passages)))
        
        metrics["quality_score"] = sum(quality_factors) / len(quality_factors)
    
    return metrics
```

## Best Practices

### Source Organization
1. **Logical Grouping**: Group related documents in sources
2. **Clear Naming**: Use descriptive source and file names
3. **Consistent Metadata**: Maintain consistent metadata schema
4. **Version Control**: Track document versions and updates
5. **Regular Maintenance**: Remove outdated or duplicate content

### Document Preparation
1. **Clean Text**: Remove unnecessary formatting and artifacts
2. **Consistent Structure**: Use consistent document structure
3. **Rich Metadata**: Include comprehensive metadata
4. **Quality Content**: Ensure high-quality, accurate information
5. **Regular Updates**: Keep content current and relevant

### Performance Optimization
1. **Appropriate Chunking**: Choose optimal chunk sizes for your content
2. **Quality Embeddings**: Use appropriate embedding models
3. **Efficient Search**: Optimize search queries and filters
4. **Caching**: Cache frequently accessed passages
5. **Regular Cleanup**: Remove unused or low-quality passages

## Common Patterns

### Documentation Source
```python
# Create comprehensive documentation source
doc_source = client.sources.create(
    name="Product Documentation",
    description="Complete product documentation and guides",
    processing_config={
        "chunk_size": 800,
        "chunk_overlap": 150,
        "preserve_formatting": True,
        "extract_metadata": True
    },
    metadata={
        "type": "documentation",
        "product": "platform_v2",
        "maintained_by": "docs_team"
    }
)

# Upload documentation files
doc_files = [
    "api_reference.pdf",
    "user_guide.docx", 
    "installation_guide.md",
    "troubleshooting.txt"
]

for doc_file in doc_files:
    client.sources.files.upload(
        source_id=doc_source["id"],
        file_path=f"/docs/{doc_file}",
        metadata={
            "document_type": doc_file.split("_")[0],
            "format": doc_file.split(".")[-1]
        }
    )
```

### FAQ Source
```python
# Create FAQ knowledge base
faq_source = client.sources.create(
    name="Customer FAQ",
    description="Frequently asked questions and answers"
)

# Add FAQ content as passages
faqs = [
    {
        "question": "How do I reset my password?",
        "answer": "To reset your password, go to the login page and click 'Forgot Password'..."
    },
    {
        "question": "What are your business hours?", 
        "answer": "Our business hours are Monday-Friday 9 AM to 5 PM EST..."
    }
]

for faq in faqs:
    passage_text = f"Q: {faq['question']}\nA: {faq['answer']}"
    
    client.sources.passages.create(
        source_id=faq_source["id"],
        text=passage_text,
        metadata={
            "type": "faq",
            "category": "customer_service",
            "question": faq["question"]
        }
    )
```

### Policy Source
```python
# Create company policy source
policy_source = client.sources.create(
    name="Company Policies",
    description="HR policies and procedures",
    processing_config={
        "chunk_size": 1200,  # Larger chunks for policy context
        "chunk_overlap": 300,
        "extract_metadata": True
    }
)

# Upload policy documents with rich metadata
policy_docs = [
    {"file": "employee_handbook.pdf", "type": "handbook", "department": "hr"},
    {"file": "remote_work_policy.docx", "type": "policy", "department": "hr"},
    {"file": "expense_policy.pdf", "type": "policy", "department": "finance"}
]

for doc in policy_docs:
    client.sources.files.upload(
        source_id=policy_source["id"],
        file_path=f"/policies/{doc['file']}",
        metadata={
            "document_type": doc["type"],
            "department": doc["department"],
            "classification": "internal",
            "requires_acknowledgment": True
        }
    )
```

## Troubleshooting

### Common Issues
1. **Processing Failures**: Large files, unsupported formats, corrupted content
2. **Poor Search Results**: Inappropriate chunking, wrong embedding model
3. **Slow Performance**: Large sources, inefficient queries
4. **Memory Issues**: Too many sources attached to agent
5. **Content Quality**: Duplicate passages, empty content

### Debugging Knowledge Issues
```python
# Debug source issues
def debug_source_issues(source_id: str):
    """
    Comprehensive source debugging.
    """
    issues = []
    
    # Check source basic info
    source = client.sources.get(source_id=source_id)
    if source["passage_count"] == 0:
        issues.append("No passages found in source")
    
    # Check file processing status
    files = client.sources.files.list(source_id=source_id)
    failed_files = [f for f in files if f["status"] == "failed"]
    if failed_files:
        issues.append(f"{len(failed_files)} files failed to process")
    
    # Check for empty passages
    passages = client.sources.passages.list(source_id=source_id, limit=100)
    empty_passages = [p for p in passages if not p["text"].strip()]
    if empty_passages:
        issues.append(f"{len(empty_passages)} empty passages found")
    
    # Check embedding quality
    if len(passages) > 0:
        avg_length = sum(len(p["text"]) for p in passages) / len(passages)
        if avg_length < 50:
            issues.append("Passages are very short - may need larger chunk size")
        elif avg_length > 2000:
            issues.append("Passages are very long - may need smaller chunk size")
    
    return issues
```