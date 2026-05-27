import functools
import logging
import math
import traceback
import inspect
import time
from typing import Any, Optional
from mcp.server.fastmcp import Context

from core.logging_config import DKSMCPLogger

def log_exceptions_decorator():
	"""
	Decorator to log all exceptions in an async function.
	Usage: @log_exceptions_decorator(logger_name="tool_error_logger")
	If logger_name is None, uses default logger.
	"""
	def decorator(func):
		@functools.wraps(func)
		async def wrapper(self, query:str, ctx: Context, auditcontext: Optional[dict[str, Any]] = None):
			tool_logger = DKSMCPLogger.get_logger(func.__name__)
			elapsed: float = 0.0
			start_time = time.perf_counter()
			try:
				tool_logger.info(f"[{ctx['transaction_id']}][{ctx['alias']}] Starting execution of {func.__qualname__}")
				result = await func(self, query, ctx, auditcontext)
				elapsed = time.perf_counter() - start_time
				return result
			except Exception as ex:
				# Get caller info using inspect
				stack = inspect.stack()
				# stack[0] is this wrapper, stack[1] is the decorated function, stack[2] is the caller
				caller_info = None
				if len(stack) > 2:
					caller_frame = stack[2]
					caller_info = f"Caller: {caller_frame.function} in {caller_frame.filename}:{caller_frame.lineno}"
				else:
					caller_info = "Caller: <unknown>"

				tool_logger.error(
					f"[{ctx['transaction_id']}][{ctx['alias']}][{caller_info}] Exception in {func.__qualname__}: {ex}\n{traceback.format_exc()}"
				)

				tool_logger.exception("Stacktrace Exception occurred")
				raise
			finally:
				if math.isclose(elapsed, 0.0):
					elapsed = time.perf_counter() - start_time
				tool_logger.info(f"[{ctx['transaction_id']}][{ctx['alias']}] Finished Execution of {func.__qualname__} took {elapsed:.4f} seconds")
		return wrapper
	return decorator
