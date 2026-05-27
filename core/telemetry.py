# import os
# import sys
# from azure.monitor.opentelemetry import configure_azure_monitor
# from core.logging_config import DKSMCPLogger

# # https://pypi.org/project/azure-monitor-opentelemetry/

# logger = DKSMCPLogger.get_logger(__name__)
# _initialized: bool = False

# def setup_app_insights(logger_name: str) -> bool:
#     global _initialized

#     if __debug__ or sys.gettrace() is not None:
#         return False
    
#     if _initialized:
#         return True
#     conn = os.getenv("FDP_APPLICATIONINSIGHTS_CONNECTION_STRING")
#     if not conn:
#         logger.exception("Missing Environment variable - FDP_APPLICATIONINSIGHTS_CONNECTION_STRING", stack_info=True)
#         raise ValueError("Missing Environment variable - FDP_APPLICATIONINSIGHTS_CONNECTION_STRING")

#     sampling_rate_str = float(os.getenv("FDP_APPLICATION_INSIGHTS_SAMPLING_RATE", "0.2"))
#     configure_azure_monitor(connection_string=conn, 
#                             enable_live_metrics=True,
#                             logger_name=logger_name,
#                             sampling_rate= sampling_rate_str if 0.0 <= sampling_rate_str <= 1.0 else 0.2,
#                             logging_format="[%(asctime)s,%(msecs)03d] [%(name)s] [%(levelname)s] [%(module)s] [%(lineno)d] [%(message)s]",
#                             )
#     _initialized = True
#     return True