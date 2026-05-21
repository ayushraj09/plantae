import logging
import traceback

logger = logging.getLogger('django')

class ErrorLoggingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        logger.debug("ErrorLoggingMiddleware initialized")

    def __call__(self, request):
        try:
            response = self.get_response(request)
            return response
        except Exception as e:
            # Log the exception with detailed traceback
            logger.error(
                f"Unhandled exception at path: {request.path}\n"
                f"Exception type: {type(e).__name__}\n"
                f"Exception message: {str(e)}\n"
                f"Traceback: {traceback.format_exc()}"
            )
            # Re-raise the exception to let Django's default exception handling kick in
            raise
