from fastapi import Security, HTTPException, status
from fastapi.security.api_key import APIKeyHeader

API_KEY_NAME = "X-API-Key"
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=True)

# In a real system, this would be a database table of API keys to Tenant IDs.
# For this assessment, we use a static map.
VALID_API_KEYS = {
    "buguard_org_a_123": "org_A",
    "buguard_org_b_456": "org_B",
}

async def get_current_tenant(api_key: str = Security(api_key_header)) -> str:
    """
    Validates the X-API-Key header and returns the associated tenant_id.
    """
    tenant_id = VALID_API_KEYS.get(api_key)
    if not tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Could not validate API key or tenant not found",
        )
    return tenant_id
