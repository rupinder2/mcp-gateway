"""Tool search service with regex and BM25 search capabilities.

This module provides the ToolSearchService class for searching tools across
all registered MCP servers. It supports two search algorithms:

1. Regex Search: Pattern-based matching using Python regular expressions.
   Useful for exact matches and wildcards.

2. BM25 Search: Keyword-based relevance ranking similar to search engines.
   Uses term frequency, inverse document frequency, and field length normalization.

Usage:
    search = ToolSearchService(index_path="./search_index")
    search.index_tools("my-server", [{"name": "my_tool", ...}])
    
    # Regex search
    results = search.search_regex("weather|forecast", limit=5)
    
    # BM25 search
    results = search.search_bm25("get weather information", limit=5)

The service maintains an in-memory index of all tools and supports:
- Indexing tools from multiple servers with namespaced names
- Removing tools when servers are unregistered
- Fallback to regex when Whoosh is not available
"""

import re
import logging
from typing import List, Dict, Any, Optional, Set
from ..models import ToolReference

logger = logging.getLogger(__name__)


# Common English stop words to ignore in BM25 search
STOP_WORDS: Set[str] = {
    'a', 'an', 'and', 'are', 'as', 'at', 'be', 'by', 'can', 'could', 'did', 'do',
    'does', 'for', 'from', 'had', 'has', 'have', 'he', 'her', 'him', 'his', 'how',
    'i', 'if', 'in', 'into', 'is', 'it', 'its', 'may', 'might', 'must', 'my',
    'no', 'not', 'of', 'on', 'or', 'our', 'shall', 'she', 'should', 'so', 'some',
    'such', 'than', 'that', 'the', 'their', 'them', 'then', 'there', 'these',
    'they', 'this', 'those', 'to', 'too', 'was', 'we', 'were', 'what', 'when',
    'where', 'which', 'who', 'whom', 'whose', 'will', 'with', 'would', 'you',
    'your', 'get', 'me', 'myself', 'yourself', 'himself', 'herself', 'itself',
    'ourselves', 'themselves', 'am', 'being', 'been', 'having', 'do', 'does',
    'did', 'doing', 'a', 'an', 'the', 'and', 'but', 'if', 'or', 'because',
    'as', 'until', 'while', 'of', 'at', 'by', 'for', 'with', 'about',
    'against', 'between', 'into', 'through', 'during', 'before', 'after',
    'above', 'below', 'up', 'down', 'in', 'out', 'on', 'off', 'over',
    'under', 'again', 'further', 'then', 'once', 'here', 'there',
    'all', 'any', 'both', 'each', 'few', 'more', 'most', 'other',
    'some', 'such', 'no', 'nor', 'not', 'only', 'own', 'same',
    'than', 'too', 'very', 'just', 'should', 'now'
}


class ToolSearchService:
    """Service for searching tools across registered servers."""
    
    def __init__(self, index_path: Optional[str] = None):
        self._index_path = index_path
        self._tools: Dict[str, Dict[str, Any]] = {}  # namespaced_name -> tool data
        self._bm25_index = None
        self._whoosh_available = False
        
        # Try to import whoosh for BM25 search
        try:
            import whoosh
            self._whoosh_available = True
        except ImportError:
            pass
    
    def _namespaced_name(self, server_name: str, tool_name: str) -> str:
        """Create namespaced tool name."""
        return f"{server_name}__{tool_name}"
    
    def _build_searchable_text(
        self,
        tool_data: Dict[str, Any],
        apply_weighting: bool = False,
    ) -> str:
        """Build searchable text from tool data with optional weighting.
        
        Args:
            tool_data: Tool definition with name, description, input_schema
            apply_weighting: If True, duplicate important fields for higher relevance
            
        Returns:
            Space-separated searchable text
        """
        parts = []
        
        tool_name = tool_data.get("tool_name") or tool_data.get("name", "")
        description = tool_data.get("description", "")
        
        if apply_weighting and tool_name:
            parts.append(tool_name)
        parts.append(tool_name)
        
        if apply_weighting and description:
            parts.append(description)
        parts.append(description)
        
        input_schema = tool_data.get("input_schema", {})
        properties = input_schema.get("properties", {})
        
        for prop_name, prop_data in properties.items():
            parts.append(prop_name)
            if isinstance(prop_data, dict):
                if "description" in prop_data:
                    parts.append(prop_data["description"])
                if "enum" in prop_data:
                    for enum_val in prop_data["enum"]:
                        parts.append(str(enum_val))
        
        required = input_schema.get("required", [])
        for req in required:
            parts.append(str(req))
        
        return " ".join(filter(None, parts))
    
    def _build_search_document(self, tool_meta: Dict[str, Any]) -> str:
        """Build a searchable text document from tool metadata.
        
        Used when rebuilding index from stored metadata.
        """
        return self._build_searchable_text(tool_meta, apply_weighting=False)
    
    def _extract_searchable_text(self, tool: Dict[str, Any]) -> str:
        """Extract searchable text from tool definition with weighting.
        
        Used for live tool indexing with relevance boosting.
        """
        return self._build_searchable_text(tool, apply_weighting=True)
    
    def index_tool(self, server_name: str, tool: Dict[str, Any]) -> None:
        """Index a tool for searching."""
        tool_name = tool.get("name", "")
        namespaced = self._namespaced_name(server_name, tool_name)
        
        tool_data = {
            "server_name": server_name,
            "tool_name": tool_name,
            "namespaced_name": namespaced,
            "description": tool.get("description", ""),
            "input_schema": tool.get("input_schema", {}),
            "searchable_text": self._extract_searchable_text(tool),
            "defer_loading": True
        }
        
        self._tools[namespaced] = tool_data
    
    def index_tools(self, server_name: str, tools: List[Dict[str, Any]]) -> None:
        """Index multiple tools from a server."""
        for tool in tools:
            self.index_tool(server_name, tool)
    
    def index_tool_metadata(self, tool_meta: Dict[str, Any]) -> None:
        """Index a tool from stored metadata.
        
        This is useful for rebuilding the search index from stored metadata
        without needing to rediscover tools from downstream servers.
        """
        namespaced = tool_meta.get("namespaced_name", "")
        if not namespaced:
            return
        
        tool_data = {
            "server_name": tool_meta.get("server_name", ""),
            "tool_name": tool_meta.get("tool_name", ""),
            "namespaced_name": namespaced,
            "description": tool_meta.get("description", ""),
            "input_schema": tool_meta.get("input_schema", {}),
            "searchable_text": self._build_search_document(tool_meta),
            "defer_loading": True
        }
        
        self._tools[namespaced] = tool_data
    
    def index_all_metadata(self, metadata_list: List[Dict[str, Any]]) -> None:
        """Index all tools from a list of metadata entries."""
        for tool_meta in metadata_list:
            self.index_tool_metadata(tool_meta)
    
    def remove_server_tools(self, server_name: str) -> None:
        """Remove all tools from a server."""
        prefix = f"{server_name}__"
        to_remove = [
            name for name in self._tools.keys()
            if name.startswith(prefix)
        ]
        for name in to_remove:
            del self._tools[name]
    
    def search_regex(
        self,
        query: str,
        limit: int = 5
    ) -> List[ToolReference]:
        """Search tools using regex pattern matching."""
        try:
            pattern = re.compile(query, re.IGNORECASE)
        except re.error as e:
            raise ValueError(f"Invalid regex pattern: {e}")
        
        results = []
        for tool_data in self._tools.values():
            searchable_text = tool_data.get("searchable_text", "")
            if pattern.search(searchable_text):
                results.append(ToolReference(
                    server_name=tool_data["server_name"],
                    tool_name=tool_data["tool_name"],
                    namespaced_name=tool_data["namespaced_name"],
                    description=tool_data["description"],
                    input_schema=tool_data["input_schema"],
                    defer_loading=tool_data["defer_loading"]
                ))
        
        return results[:limit]
    
    def _extract_keywords(self, text: str) -> List[str]:
        """Extract meaningful keywords from text, removing stop words."""
        # Convert to lowercase and extract words
        words = re.findall(r'\b[a-zA-Z_]+\b', text.lower())
        # Filter out stop words and short words
        return [w for w in words if w not in STOP_WORDS and len(w) > 2]
    
    def _calculate_bm25_score(self, query: str, tool_data: Dict[str, Any]) -> float:
        """Calculate BM25-like relevance score with improved semantic weighting."""
        query_keywords = self._extract_keywords(query)
        if not query_keywords:
            return 0.0
        
        tool_name = tool_data["tool_name"].lower()
        description = tool_data.get("description", "").lower()
        searchable_text = tool_data.get("searchable_text", "").lower()
        
        score = 0.0
        name_matches = 0
        desc_matches = 0
        
        for keyword in query_keywords:
            # Name match (high priority)
            if keyword in tool_name:
                score += 8.0
                name_matches += 1
                # Extra boost if keyword appears at start of name
                if tool_name.startswith(keyword):
                    score += 4.0
            
            # Description match (VERY high priority - most important for semantic search)
            if keyword in description:
                # Give description matches much higher weight
                score += 15.0
                desc_matches += 1
                # Extra boost if in first sentence/100 chars
                if keyword in description[:100]:
                    score += 5.0
            
            # Searchable text (params, etc) - lower weight
            count = searchable_text.count(keyword)
            if count > 0:
                score += count * 0.5
            
            # Semantic equivalents boost
            semantic_boosts = {
                'search': ['query', 'find', 'lookup', 'fetch', 'get'],
                'query': ['search', 'find', 'lookup'],
                'documentation': ['docs', 'document', 'guide', 'reference', 'manual'],
                'docs': ['documentation', 'document', 'guide'],
                'library': ['package', 'module', 'dependency'],
                'mcp': ['model', 'context', 'protocol'],
            }
            
            # Check for semantic equivalents in name
            if keyword in semantic_boosts:
                for equiv in semantic_boosts[keyword]:
                    if equiv in tool_name:
                        score += 5.0
                    if equiv in description:
                        score += 8.0
            
            # Partial word matching (fuzzy)
            name_words = tool_name.replace('_', ' ').replace('-', ' ').split()
            desc_words = description.split()
            
            for word in name_words:
                word = word.strip()
                if len(word) > 3 and keyword in word and keyword != word:
                    score += 2.0
            
            for word in desc_words:
                word = word.strip('.,;:')
                if len(word) > 3 and keyword in word and keyword != word:
                    score += 1.0
        
        # Strong boost if both name AND description have matches
        if name_matches > 0 and desc_matches > 0:
            score *= 2.0
        # Boost if all keywords found in description (strong semantic match)
        elif desc_matches >= len(query_keywords):
            score *= 1.8
        # Boost if most keywords matched
        elif (name_matches + desc_matches) >= len(query_keywords) * 0.7:
            score *= 1.4
        
        return score
    
    def search_bm25(
        self,
        query: str,
        limit: int = 5
    ) -> List[ToolReference]:
        """Search tools using BM25 relevance ranking."""
        query_keywords = self._extract_keywords(query)
        logger.debug(f"BM25 search query: '{query}' -> keywords: {query_keywords}")
        
        if not self._whoosh_available:
            # Use improved fallback with keyword extraction
            if query_keywords:
                # Create regex pattern from keywords
                pattern = ".*".join(query_keywords)
                return self.search_regex(pattern, limit)
            return []
        
        # Calculate BM25-like scores for all tools
        scored_results = []
        
        for tool_data in self._tools.values():
            score = self._calculate_bm25_score(query, tool_data)
            
            if score > 0:
                scored_results.append((score, tool_data))
                logger.debug(f"Tool '{tool_data['tool_name']}' score: {score}")
        
        # Sort by score descending
        scored_results.sort(key=lambda x: x[0], reverse=True)
        
        # Log top results for debugging
        if scored_results:
            logger.debug(f"Top result: {scored_results[0][1]['tool_name']} (score: {scored_results[0][0]})")
        
        return [
            ToolReference(
                server_name=tool_data["server_name"],
                tool_name=tool_data["tool_name"],
                namespaced_name=tool_data["namespaced_name"],
                description=tool_data["description"],
                input_schema=tool_data["input_schema"],
                defer_loading=tool_data["defer_loading"]
            )
            for score, tool_data in scored_results[:limit]
        ]
    
    def search(
        self,
        query: str,
        limit: int = 3,
        use_regex: bool = False
    ) -> List[ToolReference]:
        """Search tools using either regex or BM25.
        
        Args:
            query: Search query (regex pattern if use_regex=True, natural language otherwise)
            limit: Maximum number of results (default 3)
            use_regex: If True, treat query as regex pattern; otherwise use BM25
        
        Returns:
            List of matching tools as ToolReference objects
        """
        if use_regex:
            return self.search_regex(query, limit)
        else:
            return self.search_bm25(query, limit)
    
    def get_all_tools(self) -> List[ToolReference]:
        """Get all indexed tools."""
        return [
            ToolReference(
                server_name=tool_data["server_name"],
                tool_name=tool_data["tool_name"],
                namespaced_name=tool_data["namespaced_name"],
                description=tool_data["description"],
                input_schema=tool_data["input_schema"],
                defer_loading=tool_data["defer_loading"]
            )
            for tool_data in self._tools.values()
        ]
    
    def get_tool(self, namespaced_name: str) -> Optional[ToolReference]:
        """Get a specific tool by namespaced name."""
        tool_data = self._tools.get(namespaced_name)
        if tool_data:
            return ToolReference(
                server_name=tool_data["server_name"],
                tool_name=tool_data["tool_name"],
                namespaced_name=tool_data["namespaced_name"],
                description=tool_data["description"],
                input_schema=tool_data["input_schema"],
                defer_loading=tool_data["defer_loading"]
            )
        return None
