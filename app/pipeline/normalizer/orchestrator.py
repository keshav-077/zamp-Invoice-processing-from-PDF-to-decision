"""Orchestrate all normalization steps on an extraction."""

import logging

from app.models.extraction import InvoiceExtraction
from app.pipeline.normalizer.date_normalizer import normalize_dates
from app.pipeline.normalizer.charge_normalizer import normalize_charges
from app.services.locale_normalizer import normalize_extraction_locale

logger = logging.getLogger(__name__)


def normalize_extraction(extraction: InvoiceExtraction) -> InvoiceExtraction:
    """Run normalization pipeline: dates, charges, amounts."""
    logger.info("Running extraction normalization")
    extraction = normalize_dates(extraction)
    extraction = normalize_charges(extraction)
    extraction = normalize_extraction_locale(extraction)
    return extraction
