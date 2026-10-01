"""Deterministic itinerary logic: optimizer, validator, assembler, budget, quality.

Nothing in this package calls an LLM. The LLM proposes a draft; these
functions trim, check, complete and price it with rules you can read and test.
"""
