"""API-based model provider layer (OpenAI, Anthropic, Google Gemini) and the AI Agent runtime.

- ``catalog``    verified providers/models and their capabilities
- ``providers``  LangChain adapters, API-key resolution, connection tests
- ``errors``     provider exception normalisation (auth / availability / timeout / config)
- ``router``     primary/fallback routing with bounded retries and usage accounting
- ``structured`` text and JSON-schema generation with validation and bounded repair
- ``tools``      secure tool registry used by the AI Agent
- ``agent``      LangGraph agent graph (bounded model/tool loop)
"""
