"""
Extractors específicos por tipo de documento.

Cada módulo define un conjunto de prompts + ejemplos few-shot que
langextract usa para producir extracciones tipadas. La salida se
serializa al schema Pydantic correspondiente con `_parse_extractions`.
"""
from src.extractors.base import BaseExtractor, get_extractor

__all__ = ["BaseExtractor", "get_extractor"]
