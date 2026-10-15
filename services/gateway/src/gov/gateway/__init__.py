"""MCP gateway: the single enforcement point for Agent tool invocation.

Every tool call is authenticated, authorised, policy-checked, risk-classified,
approval-gated and audited before dispatch, and fails closed when any
enforcement dependency is unavailable (see contracts/mcp-gateway.md).
"""
