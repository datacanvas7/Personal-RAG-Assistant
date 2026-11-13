"""Turning an uploaded file into searchable chunks: validate, load, clean, chunk.

Nothing in this package touches the network, the database or the web framework, so every
step is a plain function that can be tested with plain data.
"""
