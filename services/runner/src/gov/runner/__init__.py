"""Isolated execution runtime for tool adapters.

Low and medium risk tools run in a shared restricted pool; high and critical
risk tools run in a dedicated sandbox with no ambient credentials and no
default egress.
"""
