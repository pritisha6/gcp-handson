"""Shared pytest fixtures.

Ensures required Settings fields have safe dummy values so tests don't
depend on a local .env file (which is gitignored and won't exist in CI).
Real env vars, if present, still take precedence over these defaults.
"""
import os

os.environ.setdefault("CLAUDE_API_KEY", "test-claude-key")
os.environ.setdefault("GCP_PROJECT_ID", "test-project")
os.environ.setdefault("PINECONE_API_KEY", "test-pinecone-key")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("ENVIRONMENT", "development")
