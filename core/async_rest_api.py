import aiohttp
import ssl
import asyncio
import math
from typing import Dict, Any, Optional, Union, Set, Mapping
from aiohttp import ClientError
from tenacity import retry
from core.logging_config import DKSMCPLogger
from opentelemetry import trace
tracer = trace.get_tracer(__name__)


class AsyncHttpClient:
    """
    Async HTTP client with exponential backoff retry logic for transient failures.
    Retries only idempotent operations (GET, PUT, DELETE) on specific errors.
    Respects server's Retry-After header for rate limiting.
    """

    logger = DKSMCPLogger.get_logger(__name__)

    # Retry configuration - class-level defaults
    DEFAULT_RETRY_DELAYS = [1, 3, 7]  # Fixed delays for backward compatibility
    DEFAULT_MAX_RETRIES = 3
    DEFAULT_BACKOFF_FACTOR = 3  # Base delay for exponential backoff
    
    # Status codes that should be retried (transient failures only)
    RETRYABLE_STATUS_CODES: Set[int] = {
        408,  # Request Timeout
        429,  # Too Many Requests (rate limiting)
        # 500,  # Internal Server Error
        502,  # Bad Gateway
        503,  # Service Unavailable
        504,  # Gateway Timeout
    }
    
    # Status codes that should NEVER be retried (permanent failures)
    NON_RETRYABLE_STATUS_CODES: Set[int] = {
        400,  # Bad Request - invalid input
        401,  # Unauthorized - authentication failed
        403,  # Forbidden - insufficient permissions
        404,  # Not Found - resource doesn't exist
        405,  # Method Not Allowed
        406,  # Not Acceptable
        409,  # Conflict
        410,  # Gone
        422,  # Unprocessable Entity - validation failed
    }
    
    # Methods that are safe to retry (idempotent)
    RETRYABLE_METHODS: Set[str] = {"GET", "PUT", "DELETE", "HEAD", "OPTIONS"}

    def __init__(
        self, 
        base_url: str, 
        headers: Optional[Dict[str, str]] = None, 
        verify_ssl: Union[bool, str] = True,
        retry_delays: Optional[list] = None,
        max_retries: Optional[int] = None,
        backoff_factor: Optional[int] = None,
        enable_retry: bool = True,
        use_exponential_backoff: bool = False
    ):
        """
        Initialize AsyncHttpClient.
        
        Args:
            base_url: Base URL for API requests
            headers: Optional default headers
            verify_ssl: SSL verification (False, True, or path to CA cert)
            retry_delays: Custom fixed retry delays (default: [1, 3, 7])
            max_retries: Maximum number of retries (default: 3)
            backoff_factor: Base delay for exponential backoff (default: 3)
            enable_retry: Enable/disable retry logic (default: True)
            use_exponential_backoff: Use exponential backoff instead of fixed delays
        """
        self.base_url = base_url.rstrip("/")
        self.headers = headers or {}
        self.verify_ssl = verify_ssl
        self.retry_delays = retry_delays or self.DEFAULT_RETRY_DELAYS
        self.max_retries = max_retries or self.DEFAULT_MAX_RETRIES
        self.backoff_factor = backoff_factor or self.DEFAULT_BACKOFF_FACTOR
        self.enable_retry = enable_retry
        self.use_exponential_backoff = use_exponential_backoff

   
    def _is_retryable(
        self, 
        method: str, 
        status_code: Optional[int] = None, 
        exception: Optional[Exception] = None
    ) -> bool:
        """
        Determine if a request should be retried.
        
        Args:
            method: HTTP method (GET, POST, etc.)
            status_code: HTTP status code (if available)
            exception: Exception raised (if any)
            
        Returns:
            True if retryable, False otherwise
        """
        # Only retry idempotent methods (safe operations)
        if method.upper() not in self.RETRYABLE_METHODS:
            self.logger.info(f"Method {method} is not retryable (non-idempotent)")
            return False
        
        # Check status code if provided
        if status_code:
            # NEVER retry authentication/authorization failures
            if status_code in self.NON_RETRYABLE_STATUS_CODES:
                self.logger.info(
                    f"Status code {status_code} is NOT retryable "
                    f"(permanent failure - auth/validation/client error)"
                )
                return False
            
            # Retry only specific transient errors
            if status_code in self.RETRYABLE_STATUS_CODES:
                self.logger.info(f"Status code {status_code} is retryable (transient failure)")
                return True
            
            # Unknown status code - don't retry to be safe
            self.logger.info(f"Status code {status_code} is NOT retryable (unknown/unlisted)")
            return False
        
        # Retry on network errors (timeouts, connection errors)
        if exception and isinstance(exception, (asyncio.TimeoutError, aiohttp.ClientConnectionError)):
            self.logger.info(f"Exception {type(exception).__name__} is retryable (network error)")
            return True
        
        return False

    def _calculate_retry_delay(self, attempt: int, response_headers: Optional[Dict[str, str]] = None) -> float:
        """
        Calculate delay before next retry attempt.
        
        Args:
            attempt: Current retry attempt number (0-indexed)
            response_headers: HTTP response headers (to check Retry-After)
            
        Returns:
            Delay in seconds
        """
        # First, check if server provided Retry-After header
        if response_headers:
            retry_after = response_headers.get("Retry-After") or response_headers.get("retry-after")
            if retry_after:
                # Retry-After can be in seconds (integer) or HTTP-date
                if retry_after.isdigit():
                    delay = int(retry_after)
                    self.logger.info(f"Using server's Retry-After header: {delay}s")
                    return delay
        
        # Use exponential backoff if enabled
        if self.use_exponential_backoff:
            delay = self.backoff_factor * math.pow(2, attempt)
            self.logger.info(f"Using exponential backoff: {delay}s")
            return delay
        
        # Use fixed delays (backward compatible)
        if attempt < len(self.retry_delays):
            delay = self.retry_delays[attempt]
            self.logger.info(f"Using fixed delay: {delay}s")
            return delay
        
        # Fallback to last delay if we exceed configured delays
        delay = self.retry_delays[-1]
        self.logger.info(f"Using fallback delay: {delay}s")
        return delay

    async def _make_request_with_retry(
        self, 
        method: str, 
        endpoint: str, 
        **kwargs
    ) -> Dict[str, Any]:
        """
        Make REST API request with exponential backoff retry logic.
        
        Args:
            method: HTTP method (GET, POST, PUT, DELETE, etc.)
            endpoint: API endpoint path
            **kwargs: Additional arguments for aiohttp request
            
        Returns:
            JSON response as dictionary
            
        Raises:
            Exception: If all retries exhausted or non-retryable error occurs
        """
        last_exception = None
        retry_count = 0
        max_attempts = self.max_retries + 1  # Initial + retries

        while retry_count < max_attempts:
            try:
                attempt_num = retry_count + 1
                self.logger.info(f"Attempt {attempt_num}/{max_attempts} for {method} {endpoint}")
                
                # Make the actual request
                result = await self._make_request(method, endpoint, **kwargs)
                # Success - log if it was a retry
                if retry_count > 0:
                    self.logger.info(f"Request succeeded on attempt {attempt_num}/{max_attempts}")
                
                return result
                
            except aiohttp.ClientResponseError as crex:
                last_exception = crex
                response_headers = dict(crex.headers) if hasattr(crex, 'headers') else None
                
                # Check if retryable
                if not self.enable_retry or not self._is_retryable(method, status_code=crex.status):
                    # Log specific message for auth failures
                    if crex.status in {401}:
                        self.logger.error(
                            f"Authentication/Authorization failed: HTTP {crex.status} - {crex.message}. "
                            f"Not retrying."
                        )
                    else:
                        self.logger.error(
                            f"Non-retryable HTTP error: {crex.status} - {crex.message}"
                        )
                    raise
                
                # Last attempt - fail
                if retry_count >= self.max_retries:
                    self.logger.error(
                        f"All {max_attempts} attempts failed for {method} {endpoint}. "
                        f"Last error: HTTP {crex.status}"
                    )
                    raise Exception(
                        f"Request failed after {max_attempts} attempts. "
                        f"Last error: HTTP {crex.status} - {crex.message}"
                    )
                
                # Calculate delay (respects Retry-After header)
                delay = self._calculate_retry_delay(retry_count, response_headers)
                
                self.logger.warning(
                    f"Attempt {attempt_num}/{max_attempts} failed with HTTP {crex.status}. "
                    f"Retrying in {delay}s..."
                )
                
                retry_count += 1
                await asyncio.sleep(delay)
                
            except (asyncio.TimeoutError, aiohttp.ClientConnectionError) as net_ex:
                last_exception = net_ex
                
                # Check if retryable
                if not self.enable_retry or not self._is_retryable(method, exception=net_ex):
                    self.logger.error(f"Non-retryable network error: {type(net_ex).__name__}")
                    raise
                
                # Last attempt - fail
                if retry_count >= self.max_retries:
                    self.logger.error(
                        f"All {max_attempts} attempts failed for {method} {endpoint}. "
                        f"Last error: {type(net_ex).__name__}"
                    )
                    raise Exception(
                        f"Request failed after {max_attempts} attempts. "
                        f"Last error: {type(net_ex).__name__} - {net_ex}"
                    )
                
                # Calculate delay (exponential backoff for network errors)
                delay = self._calculate_retry_delay(retry_count)
                
                self.logger.warning(
                    f"Attempt {attempt_num}/{max_attempts} failed with {type(net_ex).__name__}. "
                    f"Retrying in {delay}s..."
                )
                
                retry_count += 1
                await asyncio.sleep(delay)
                
            except Exception as ex:
                # Non-retryable exception - fail immediately
                self.logger.error(f"Non-retryable exception: {type(ex).__name__} - {ex}")
                raise
        
        # Fallback (should never reach here)
        raise Exception(
            f"Request failed after {max_attempts} attempts. "
            f"Last error: {type(last_exception).__name__} - {last_exception}"
        )

    async def _handle_error(self, response, method: str, url: str):
        """Handle error responses and raise appropriate exceptions with proper messages."""
        response_body = None
        try:
            response_body = await response.json()
        except Exception:
            try:
                response_body = await response.text()
            except Exception:
                pass
        
        # Check if this error is retryable
        is_retryable = self._is_retryable(method, response.status)
        
        # Format error message based on status code
        if response.status == 403:
            error_message = "Access forbidden."
            
            if isinstance(response_body, dict) and not response_body.get("IsAuthorized", True):
                auth_info = response_body.get("AuthorizationInfo", {})
                ops_location = auth_info.get("RequiredOpsLocation", "")
                entitlements = auth_info.get("RequiredEntitlementNames", [])
                
                # Both are empty - resource not found in FDP
                if not ops_location and not entitlements:
                    error_message = "The ID provided is not present in FDP. Please check again."
                # Both are present - authorization required
                elif ops_location and entitlements:
                    entitlements_str = ", ".join(entitlements)
                    error_message = (
                        f"The information you are trying to access requires an Entitlement "
                        f"with access to Ops Location: {ops_location}. "
                        f"Please choose one of the following Entitlement(s) in your Profile to access the same. "
                        f"- {entitlements_str}"
                    )
                
                # Only ops location present
                elif ops_location:
                    error_message = (
                        f"The information you are trying to access requires access to Ops Location: {ops_location}. "
                        f"Please ensure your profile has the required entitlements access."
                        f" Please raise a new entitlement access request in FDP for {ops_location}."
                    )
                # Only entitlements present
                elif entitlements:
                    entitlements_str = ", ".join(entitlements)
                    error_message = (
                        f"The information you are trying to access requires one of the following Entitlement(s): {entitlements_str}. "
                        f"Please update your profile accordingly."
                    )
        
        elif response.status == 400:
            error_message = "Bad request, Please check the inputs."
            if isinstance(response_body, dict):
                msg = response_body.get("message") or response_body.get("error") or response_body.get("Message")
                if msg:
                    error_message = f"Bad request: {msg}"
        
        elif response.status == 401:
            error_message = "Authentication required. Please check your credentials."
        
        elif response.status == 404:
            error_message = "The requested resource was not found."
        
        elif response.status == 500:
            error_message = "Internal server error occurred. Please try again later."
        
        elif response.status == 502:
            error_message = "Bad gateway error. The server is temporarily unavailable."
        
        elif response.status == 503:
            error_message = "Service temporarily unavailable. Please try again later."
        
        elif response.status == 504:
            error_message = "Gateway timeout. The server took too long to respond."
        
        else:
            error_message = f"Request failed with status {response.status}."
            if isinstance(response_body, dict):
                msg = response_body.get("message") or response_body.get("error") or response_body.get("Message")
                if msg:
                    error_message = msg
        
        # Log with retry info
        retry_info = " (retryable)" if is_retryable else " (non-retryable)"
        self.logger.error(f"HTTP {response.status}{retry_info}: {error_message}")
        
        # Raise a simple Exception to avoid URL in message
        raise Exception(f"{response.status}, message='{error_message}'")

    @tracer.start_as_current_span(__name__ + "._make_request", attributes={}, kind=trace.SpanKind.SERVER)
    async def _make_request(
        self, 
        method: str, 
        endpoint: str, 
        params: Optional[Dict[str, Any]] = None,
        data: Optional[Union[bytes, str, bytearray, memoryview, Mapping]] = None,
        json: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Make REST API request asynchronously (core implementation).
        
        Args:
            method: HTTP method
            endpoint: API endpoint path
            params: Query parameters
            data: Request body (various formats)
            json: JSON request body
            **kwargs: Additional arguments for aiohttp
            
        Returns:
            JSON response as dictionary
            
        Raises:
            aiohttp.ClientResponseError: On HTTP errors
            ClientError: On network errors
        """
        span = trace.get_current_span()
        span.set_attribute("http.method", method)

        # Setup SSL context
        # if self.verify_ssl is False:
        #     ssl_context = ssl._create_unverified_context()
        if self.verify_ssl is True:
            ssl_context = ssl.create_default_context()
        elif isinstance(self.verify_ssl, str):
            ssl_context = ssl.create_default_context(cafile=self.verify_ssl)
        else:
            raise ValueError("verify_ssl must be False, True, or a certificate path string")

        connector = aiohttp.TCPConnector(ssl=ssl_context)
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        span.set_attribute("http.url", url)
        self.logger.info(f"Making ====> {method} request to: {url}")
        
        try:
            async with aiohttp.ClientSession(headers=self.headers, connector=connector) as session:
                # Handle different data types (like your old implementation)
                request_kwargs = {"params": params, **kwargs}
                
                if data is not None:
                    if isinstance(data, (bytes, bytearray, memoryview)):
                        # Binary data
                        request_kwargs["data"] = data
                    elif isinstance(data, str):
                        # String content
                        request_kwargs["data"] = data.encode('utf-8')
                    elif isinstance(data, Mapping):
                        # Form-like mapping (dict)
                        request_kwargs["data"] = data
                    else:
                        # Fallback: coerce to string
                        request_kwargs["data"] = str(data).encode('utf-8')
                elif json is not None:
                    # JSON payload
                    request_kwargs["json"] = json
                
                async with session.request(method, url, **request_kwargs) as response:
                    span.set_attribute("http.status_code", response.status)
                    if not (200 <= response.status < 300):
                        self.logger.error(f"Received error response: HTTP {response.status}")
                        await self._handle_error(response, method, url)
                    return await response.json()
                    
        except aiohttp.ClientResponseError as crex:
            self.logger.error(
                f"HTTP error {crex.status} for {method} {url}: {crex.message}",
                exc_info=True
            )
            span.record_exception(crex)
            span.set_status(trace.Status(trace.status.StatusCode.ERROR))
            raise
            
        except ClientError as ex:
            self.logger.error(f"Client error for {method} {url}: {ex}", exc_info=True)
            span.record_exception(ex)
            span.set_status(trace.Status(trace.status.StatusCode.ERROR))
            raise
            
        except Exception as ex:
            self.logger.error(f"Unexpected error for {method} {url}: {ex}", exc_info=True)
            span.record_exception(ex)
            span.set_status(trace.Status(trace.status.StatusCode.ERROR))
            raise

    # Public API methods
    
    async def get(
        self, 
        endpoint: str, 
        params: Optional[Dict[str, Any]] = None,
        retry: Optional[bool] = False
    ) -> Dict[str, Any]:
        """Perform a GET request with retry logic."""
        if retry:
            return await self._make_request_with_retry("GET", endpoint, params=params)
        else:
            return await self._make_request("GET", endpoint, params=params)

    async def post(
        self,
        endpoint: str,
        data: Optional[Union[bytes, str, bytearray, memoryview, Mapping]] = None,
        json: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Perform a POST request (no retry - not idempotent)."""
        return await self._make_request("POST", endpoint, params=params, data=data, json=json)

    async def put(
        self,
        endpoint: str,
        data: Optional[Union[bytes, str, bytearray, memoryview, Mapping]] = None,
        json: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        retry: Optional[bool] = False
    ) -> Dict[str, Any]:
        """Perform a PUT request with retry logic."""
        if retry:
            return await self._make_request_with_retry("PUT", endpoint, params=params, data=data, json=json)
        else:
            return await self._make_request("PUT", endpoint, params=params, data=data, json=json)

    async def patch(
        self,
        endpoint: str,
        data: Optional[Union[bytes, str, bytearray, memoryview, Mapping]] = None,
        json: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Perform a PATCH request (no retry - not idempotent)."""
        return await self._make_request("PATCH", endpoint, params=params, data=data, json=json)

    async def delete(
        self, 
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        retry: Optional[bool] = False
    ) -> Dict[str, Any]:
        """Perform a DELETE request with retry logic."""
        if retry:
            return await self._make_request_with_retry("DELETE", endpoint, params=params)
        else:
            return await self._make_request("DELETE", endpoint, params=params)
    

    # Header management
    
    def set_auth_token(self, token: str) -> None:
        """Set the Authorization Bearer token for subsequent requests."""
        self.headers["Authorization"] = f"Bearer {token}"

    def set_header(self, key: str, value: str) -> None:
        """Set a custom header for subsequent requests."""
        self.headers[key] = value

    def remove_header(self, key: str) -> None:
        """Remove a custom header from subsequent requests."""
        self.headers.pop(key, None)
