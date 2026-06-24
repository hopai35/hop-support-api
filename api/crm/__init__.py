"""
Hop Support - CRM Provider Factory

Factory function to create the appropriate CRM provider based on
configuration or environment variables.
"""

import os
import logging
from typing import Optional

from .base import BaseCRMProvider
from .mock import MockCRMProvider
from .zendesk import ZendeskProvider
from .salesforce import SalesforceProvider
from .warby_parker import WarbyParkerSalesforceProvider, WarbyParkerMockProvider

logger = logging.getLogger(__name__)


def get_crm_provider(
    provider: Optional[str] = None,
) -> BaseCRMProvider:
    """
    Factory function to get the appropriate CRM provider.

    Args:
        provider: One of 'mock', 'zendesk', 'salesforce', 'warby_parker'.
                  Defaults to CRM_PROVIDER env var, then 'mock'.

    Returns:
        A CRM provider instance.
    """
    provider = provider or os.getenv("CRM_PROVIDER", "mock").lower()

    if provider == "warby_parker":
        logger.info("Creating Warby Parker Salesforce CRM provider")
        # Use mock if credentials not configured
        if os.getenv("SF_CLIENT_ID"):
            return WarbyParkerSalesforceProvider()
        logger.warning("SF credentials not set, using WarbyParkerMockProvider")
        return WarbyParkerMockProvider()

    if provider == "zendesk":
        logger.info("Creating Zendesk CRM provider")
        return ZendeskProvider()

    if provider == "salesforce":
        logger.info("Creating Salesforce CRM provider")
        return SalesforceProvider()

    logger.info("Creating Mock CRM provider (no real CRM configured)")
    return MockCRMProvider()