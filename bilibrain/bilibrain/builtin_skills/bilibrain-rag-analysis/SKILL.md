---
name: bilibrain-rag-analysis
description: Use for reasoning about BiliBrain's retrieval, transcript, summary, and evaluation pipeline when the task is about the existing video knowledge workflow.
allowed-tools: [read_file, list_dir]
metadata:
  short-description: BiliBrain RAG workflow guidance
---

# BiliBrain RAG Analysis

Use this skill for tasks that focus on BiliBrain's current Agentic RAG implementation.

## Focus Areas

- Transcript ingestion and chunking
- Summary-first routing and retrieval
- Query scope selection
- Evaluation adapter and RAGAS wiring

## Working Style

- Prefer tracing the existing path through config, graph nodes, and services before proposing changes.
- Preserve the current RAG route unless the task explicitly asks for behavior changes.
- When describing tradeoffs, separate retrieval accuracy, answer quality, latency, and token cost.
