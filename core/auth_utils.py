import os

import jwt
from typing import Optional, Dict
import requests
import time
from mcp.server.fastmcp.exceptions import ToolError

from core.logging_config import DKSMCPLogger

logger = DKSMCPLogger.get_logger()

# Cache for metadata and JWKS to avoid repeated network calls
_metadata_cache: Dict = {"issuer": None, "jwks_uri": None, "expires": 0}
_jwks_cache: Dict = {"keys": [], "expires": 0}
CACHE_TTL = 3600  # 1 hour

def _get_openid_metadata(tenant_id: str) -> Dict:
	"""
	Fetch and cache Azure AD OpenID Connect metadata.
	"""
	global _metadata_cache
	
	# Return cached metadata if still valid
	if _metadata_cache["jwks_uri"] and time.time() < _metadata_cache["expires"]:
		return _metadata_cache
	try:
		metadata_url = f"https://login.microsoftonline.com/{tenant_id}/v2.0/.well-known/openid-configuration"
		response = requests.get(metadata_url, timeout=5)
		response.raise_for_status()
		
		metadata = response.json()
		_metadata_cache = {
			"issuer": metadata.get("issuer"),
			"jwks_uri": metadata.get("jwks_uri"),
			"expires": time.time() + CACHE_TTL
		}
		return _metadata_cache
	except Exception as ex:
		logger.error(f"Failed to fetch OpenID Connect metadata: {str(ex)}")
		raise ToolError(f"Authentication failed: Unable to fetch metadata. {str(ex)}")

def _get_jwks(tenant_id: str) -> Dict:
    """
    Fetch and cache Azure AD JWKS using the discovered jwks_uri.
    """
    global _jwks_cache
    
    # Return cached keys if still valid
    if _jwks_cache["keys"] and time.time() < _jwks_cache["expires"]:
        return _jwks_cache
    
    try:
        metadata = _get_openid_metadata(tenant_id)
        jwks_uri = metadata["jwks_uri"]
        
        response = requests.get(jwks_uri, timeout=5)
        response.raise_for_status()
        
        _jwks_cache = {
            "keys": response.json()["keys"],
            "expires": time.time() + CACHE_TTL
        }
        return _jwks_cache
    except Exception as ex:
        logger.error(f"Failed to fetch JWKS: {str(ex)}")
        raise ToolError(f"Authentication failed: Unable to fetch signing keys. {str(ex)}")


def _get_signing_key(access_token: str, tenant_id: str) -> str:
    """
    Get the signing key from Azure AD JWKS based on the token's kid (key ID).
    """
    try:
        unverified_header = jwt.get_unverified_header(access_token)
        kid = unverified_header.get("kid")
        
        if not kid:
            raise ToolError("Authentication failed: Token missing 'kid' in header.")
        
        jwks_data = _get_jwks(tenant_id)
        
        # Find the matching key by kid
        for key in jwks_data["keys"]:
            if key.get("kid") == kid:
                return jwt.algorithms.RSAAlgorithm.from_jwk(key)
        
        raise ToolError(f"Authentication failed: Signing key with kid '{kid}' not found.")
    except Exception as ex:
        if isinstance(ex, ToolError):
            raise
        logger.error(f"Error resolving signing key: {str(ex)}")
        raise ToolError(f"Authentication failed: {str(ex)}")

def verify_audience_and_expiry(access_token: str) -> tuple[bool, Optional[str]]:
	"""
	Validates token expiry and tenant claims.
	Expected tenant and audience are read from environment.
	"""
	try:
		expected_tenant = os.environ.get("AZURE_TENANT_ID")
		expected_client_audience_id = os.environ.get("AZURE_CLIENT_AUDIENCE_ID")

		if not expected_tenant:
			raise ToolError(
				"Authentication failed: Missing tenant configuration. Set TENANT_ID in environment variables."
			)
		
		# Get OpenID Connect metadata to obtain issuer
		metadata = _get_openid_metadata(expected_tenant)
		issuer = metadata["issuer"]

		# Get the signing key from Azure AD JWKS
		signing_key = _get_signing_key(access_token, expected_tenant)

		payload = jwt.decode(
			access_token,
			key=signing_key,
			algorithms=["RS256"],
			issuer=issuer,
			audience=expected_client_audience_id,
			options={
				"verify_signature": True, 
				"verify_exp": True
			}
		)

		# Tenant Validation
		token_tenant = payload.get("tid") or payload.get("tenant")
		if not token_tenant and isinstance(payload.get("iss"), str):
			issuer = payload.get("iss", "")
			token_tenant = issuer.rstrip("/").split("/")[-2] if issuer else None

		if not token_tenant or str(token_tenant).lower() != str(expected_tenant).lower():
			raise ToolError("Authentication failed: Token tenant is invalid.")
		
		# Audience Validation
		token_audience = payload.get("aud", "")
		
		if not token_audience:
			raise ToolError("Authentication failed: Token audience is missing.")
		if not token_audience or str(token_audience).lower() != str(expected_client_audience_id).lower():
			raise ToolError("Authentication failed: Token audience is invalid.")
		
		user_id = payload.get("preferred_username") or payload.get("email")

		return True, user_id
	
	except jwt.ExpiredSignatureError as ex:
		logger.error(f"Authentication failed: Token has expired. {str(ex)}")
		return False, None
	except jwt.InvalidAudienceError as ex:
		logger.error(f"Authentication failed: Token audience is invalid. {str(ex)}")
		return False, None
	except jwt.InvalidTokenError as ex:
		logger.error(f"Authentication failed: Invalid token. {str(ex)}")
		return False, None
	except Exception:
		logger.exception("Authentication failed: An unexpected error occurred during token validation and decoding access token.", stack_info=True)
		return False, None

